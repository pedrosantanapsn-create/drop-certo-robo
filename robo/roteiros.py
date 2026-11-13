"""📄 Página de roteiros (certodrop.netlify.app/roteiros.html) — os kits do dia, prontos para copiar.

O robô escolhe as melhores ofertas (as da fila, pela nota; se faltar, as últimas postadas), monta o
kit de cada uma (fotos + comandos de imagem/vídeo para o Gemini + textos da edição — ver roteiro.py)
e grava tudo num arquivo público do Supabase (robo/roteiros.json). A página só lê esse arquivo.

Atualiza sozinho a cada ROTEIROS_HORAS (8h–23h) e na hora com /roteiros. Kits já feitos são
reaproveitados (não gasta outra chamada ao Gemini para o mesmo produto).
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import requests

from . import config, fila, mercadolivre, roteiro, shopee, supabase
from .produto import Produto, baixar_imagens, buscar_produto, formatar_preco, ler_mensagem

CHAVE_PROXIMO = "roteiros_proximo"
ARQUIVO = "robo/roteiros.json"


def url_pagina() -> str:
    return f"{config.SITE_URL.rstrip('/')}/roteiros.html"


def _url_arquivo() -> str:
    return f"{config.SUPABASE_URL}/storage/v1/object/public/{config.SUPABASE_BUCKET}/{ARQUIVO}"


def ler_produto(corpo: str) -> tuple[Produto, list[str]]:
    """Produto de um texto de oferta (link + nome:/preco:/foto:). Só consulta a loja para o que faltar."""
    dados = ler_mensagem(corpo)
    link = dados.get("link") or ""
    p = Produto(link=link, nome=dados.get("nome", ""), preco=dados.get("preco"), preco_antigo=dados.get("preco_antigo"))
    imagens = [dados["imagem"]] if str(dados.get("imagem", "")).startswith("http") else []
    if not (p.nome and imagens):
        try:
            if shopee.ativo() and shopee.e_shopee(link):
                oficial = shopee.ler(link)
            elif mercadolivre.ativo() and mercadolivre.e_mercadolivre(link):
                oficial = mercadolivre.ler(link)
            else:
                lido = buscar_produto(link)
                oficial = {"nome": lido.nome if not lido.nome_do_link else "", "preco": lido.preco,
                           "preco_antigo": lido.preco_antigo, "imagens": lido.imagens}
        except Exception as erro:  # noqa: BLE001
            print(f"::warning::Roteiro (leitura): {str(erro)[:150]}")
            oficial = {}
        p.nome = p.nome or str(oficial.get("nome") or "").strip()
        p.preco = p.preco or oficial.get("preco")
        p.preco_antigo = p.preco_antigo or oficial.get("preco_antigo")
        imagens += [i for i in ([oficial.get("imagem")] + list(oficial.get("imagens") or [])) if i]
    p.imagens = list(dict.fromkeys(imagens))[:3]
    return p, p.imagens


def _candidatos(quantos: int) -> list[dict]:
    """[{corpo, origem}] — fila pela nota; completa com os últimos produtos postados no site."""
    lista = []
    for item in sorted([i for i in fila.itens() if i.get("texto")], key=lambda i: -fila._nota_do_item(i)):
        corpo = item["texto"]
        if item.get("foto_url") and "foto:" not in corpo:
            corpo += f"\nfoto: {item['foto_url']}"
        lista.append({"corpo": corpo, "origem": "fila"})
    if len(lista) < quantos:
        try:
            r = requests.get(f"{config.SUPABASE_URL}/rest/v1/{config.SUPABASE_TABELA}", headers=supabase._cabecalhos(),
                             timeout=30, params={"select": f"{config.COL_NOME},{config.COL_PRECO},{config.COL_LINK},"
                                                           f"{config.COL_IMAGEM}", "ativo": "eq.true",
                                                 "order": "criado_em.desc", "limit": str(quantos * 2)})
            r.raise_for_status()
            for linha in r.json():
                if linha.get(config.COL_LINK) and linha.get(config.COL_NOME):
                    corpo = f"{linha[config.COL_LINK]}\nnome: {linha[config.COL_NOME]}"
                    if linha.get(config.COL_PRECO):
                        corpo += "\npreco: " + f"{float(linha[config.COL_PRECO]):.2f}".replace(".", ",")
                    if linha.get(config.COL_IMAGEM):
                        corpo += f"\nfoto: {linha[config.COL_IMAGEM]}"
                    lista.append({"corpo": corpo, "origem": "postado"})
        except Exception as erro:  # noqa: BLE001
            print(f"::warning::Roteiros (site): {str(erro)[:120]}")
    vistos, unicos = set(), []
    for c in lista:
        chave = fila.chave_link(c["corpo"])
        if chave and chave not in vistos:
            vistos.add(chave)
            unicos.append(c)
    return unicos[:quantos]


def _anteriores() -> dict:
    try:
        r = requests.get(_url_arquivo(), params={"t": int(datetime.now().timestamp())}, timeout=20)
        return {i["id"]: i for i in r.json().get("itens", [])} if r.status_code == 200 else {}
    except Exception:  # noqa: BLE001
        return {}


def gerar(quantos: int | None = None) -> int:
    """Monta os kits e publica o arquivo que a página lê. Devolve quantos produtos ficaram na página."""
    quantos = quantos or config.ROTEIROS_QUANTOS
    antigos, itens = _anteriores(), []
    with tempfile.TemporaryDirectory() as tmp:
        for n, c in enumerate(_candidatos(quantos)):
            ident = fila.chave_link(c["corpo"])
            if ident in antigos and antigos[ident].get("img1"):
                itens.append({**antigos[ident], "origem": c["origem"]})     # kit já feito: reaproveita
                continue
            try:
                p, fotos_url = ler_produto(c["corpo"])
                if not p.nome:
                    continue
                pasta = Path(tmp) / str(n)
                pasta.mkdir()
                baixadas = baixar_imagens(p, pasta)
                k = roteiro.kit(p, baixadas[0] if baixadas else None)
                itens.append({"id": ident, "origem": c["origem"], "nome": p.nome[:140], "link": p.link,
                              "preco": formatar_preco(p.preco) if p.preco else "",
                              "de": (formatar_preco(p.preco_antigo)
                                     if p.preco and p.preco_antigo and p.preco_antigo > p.preco else ""),
                              "fotos": fotos_url, **k})
            except Exception as erro:  # noqa: BLE001
                print(f"::warning::Roteiros ({ident[:40]}): {str(erro)[:150]}")
        arquivo = Path(tmp) / "roteiros.json"
        arquivo.write_text(json.dumps({"gerado": datetime.now(fila.FUSO).isoformat(timespec="minutes"),
                                       "itens": itens}, ensure_ascii=False), encoding="utf-8")
        supabase.enviar_arquivo(arquivo, ARQUIVO, "application/json")
    return len(itens)


def se_for_hora() -> int:
    """Chamado nas rodadas leves: atualiza a página a cada ROTEIROS_HORAS, das 8h às 23h."""
    if not (config.ROTEIROS and supabase.ativo() and config.GEMINI_API_KEY):
        return 0
    agora = datetime.now(fila.FUSO)
    valor = str((supabase.ler_config(CHAVE_PROXIMO) or {}).get("valor") or "")
    if not (8 <= agora.hour < 23) or (valor.isdigit() and agora.timestamp() < int(valor)):
        return 0
    supabase.gravar_config(CHAVE_PROXIMO, str(int((agora + timedelta(hours=config.ROTEIROS_HORAS)).timestamp())))
    return gerar()

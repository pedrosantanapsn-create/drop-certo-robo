"""📄 Página de roteiros (certodrop.netlify.app/roteiros.html) — os kits do dia, prontos para copiar.

O robô escolhe só os MELHORES produtos para vídeo (fila + postados nos últimos 3 dias, por pontuação:
rende cena de uso, marca conhecida, desconto, nota e cliques — peça interna, cabo e sem foto ficam fora), monta o
kit de cada uma (fotos + comandos de imagem/vídeo para o Gemini + textos da edição — ver roteiro.py)
e grava tudo num arquivo público do Supabase (robo/roteiros.json). A página só lê esse arquivo.

Atualiza sozinho a cada ROTEIROS_HORAS (8h–23h) e na hora com /roteiros. Kits já feitos são
reaproveitados (não gasta outra chamada ao Gemini para o mesmo produto).
"""
from __future__ import annotations

import json
import re
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


# ---------------------------------------------------------------------------
# Quais produtos valem um vídeo feito à mão
# ---------------------------------------------------------------------------
# Rendem cena boa de "pessoa usando" e de produto em destaque
RE_BOM_DE_VIDEO = re.compile(
    r"\b(?:headset|fone|earbud|buds|teclado|mouse|monitor|cadeira|smart ?watch|rel[óo]gio|caixa de som|soundbar|celular|"
    r"smartphone|iphone|galaxy|notebook|controle|console|playstation|ps5|xbox|switch|smart ?tv|tv|webcam|microfone|"
    r"tablet|ipad|kindle|alexa|echo|rob[ôo] aspirador|ring light|lumin[áa]ria|mesa gamer|mousepad|gabinete|pc gamer|"
    r"c[âa]mera|drone|projetor|parafusadeira|furadeira)", re.I)
# Difíceis de mostrar em uso (peça interna, cabo, adaptador): a IA inventa e o vídeo fica fraco
RE_RUIM_DE_VIDEO = re.compile(
    r"\b(?:ssd|hd|nvme|mem[óo]ria|ram|ddr\d|processador|ryzen|core i\d|placa[- ]m[ãa]e|fonte|cabo|adaptador|hub|"
    r"pasta t[ée]rmica|cooler|water ?cooler|pen ?drive|cart[ãa]o de mem[óo]ria|carregador|filtro de linha|suporte|"
    r"pel[íi]cula|capa|capinha|kit \d+)", re.I)
PONTOS_MINIMOS = 35
MAX_POR_TIPO = 2            # no máximo 2 produtos do mesmo tipo na página


def _pontuar(nome: str, preco, de, tem_foto: bool, nota: int = 0, cliques: int = 0) -> tuple[int, list[str]]:
    """(pontos, motivos) — quanto o produto vale um vídeo caprichado. Sem foto ou com nome ruim = fora."""
    from . import canais, marcas
    if not tem_foto or len(nome.split()) < 3 or canais.RE_CONVERSA.search(nome):
        return -1, []
    pontos, motivos = 20, []
    bom, ruim = RE_BOM_DE_VIDEO.search(nome), RE_RUIM_DE_VIDEO.search(nome)
    if ruim and (not bom or ruim.start() < bom.start()):      # "Suporte para monitor" é suporte, não monitor
        pontos -= 20
    elif bom:
        pontos += 25
        motivos.append("rende boa cena de uso")
    if marcas.conhecida(nome):
        pontos += 12
        motivos.append("marca conhecida")
    if preco:
        if not canais.preco_plausivel(nome, preco):
            return -1, []
        if 60 <= preco <= 1500:
            pontos += 10
        elif preco < 25:
            pontos -= 15
        if de and de > preco:
            desconto = round(100 * (1 - preco / de))
            if 10 <= desconto <= 80:
                pontos += min(desconto, 40) // 2
                motivos.append(f"{desconto}% de desconto")
    if nota:
        pontos += int(nota * 0.3)
        if nota >= 70:
            motivos.append(f"nota {nota} do robô")
    if cliques:
        pontos += min(cliques * 5, 25)
        motivos.append(f"{cliques} clique(s) no site")
    return pontos, motivos


def _cliques_por_produto() -> dict:
    """{id do produto no site: cliques nos últimos 7 dias}."""
    try:
        desde = (datetime.now(fila.FUSO) - timedelta(days=7)).isoformat()
        r = requests.get(f"{config.SUPABASE_URL}/rest/v1/cliques", headers=supabase._cabecalhos(), timeout=30,
                         params={"select": "produto_id", "criado_em": f"gte.{desde}", "limit": "5000"})
        r.raise_for_status()
        contagem: dict = {}
        for c in r.json():
            if c.get("produto_id"):
                contagem[str(c["produto_id"])] = contagem.get(str(c["produto_id"]), 0) + 1
        return contagem
    except Exception:  # noqa: BLE001
        return {}


def _candidatos(quantos: int) -> list[dict]:
    """Os MELHORES para vídeo: [{corpo, origem, pontos, motivos}] — fila + últimos postados, por pontuação."""
    lista = []
    for item in fila.itens():
        corpo = str(item.get("texto") or "")
        if not corpo:
            continue
        if item.get("foto_url") and "foto:" not in corpo:
            corpo += f"\nfoto: {item['foto_url']}"
        dados = ler_mensagem(corpo)
        # na fila, Shopee e Mercado Livre trazem a foto pela API na hora de postar: contam como "com foto"
        tem_foto = bool(dados.get("imagem")) or shopee.e_shopee(dados.get("link") or "") \
            or mercadolivre.e_mercadolivre(dados.get("link") or "")
        nome = dados.get("nome") or ""
        if not nome:                       # item automático só com o link: o nome vem da loja depois
            pontos, motivos = 20 + int(fila._nota_do_item(item) * 0.3), []
        else:
            pontos, motivos = _pontuar(nome, dados.get("preco"), dados.get("preco_antigo"), tem_foto,
                                       fila._nota_do_item(item))
        lista.append({"corpo": corpo, "origem": "fila", "pontos": pontos, "motivos": motivos})
    try:
        cliques = _cliques_por_produto()
        colunas = ",".join(c for c in ("id", config.COL_NOME, config.COL_PRECO, config.COL_PRECO_ANTIGO, config.COL_LINK,
                                       config.COL_IMAGEM) if c and c != "-")
        desde = (datetime.now(fila.FUSO) - timedelta(days=3)).isoformat()
        r = requests.get(f"{config.SUPABASE_URL}/rest/v1/{config.SUPABASE_TABELA}", headers=supabase._cabecalhos(),
                         timeout=30, params={"select": colunas, "ativo": "eq.true", "criado_em": f"gte.{desde}",
                                             "order": "criado_em.desc", "limit": "80"})
        r.raise_for_status()
        for linha in r.json():
            nome, link = str(linha.get(config.COL_NOME) or ""), linha.get(config.COL_LINK)
            if not (nome and link):
                continue
            preco = float(linha[config.COL_PRECO]) if linha.get(config.COL_PRECO) else None
            de = float(linha[config.COL_PRECO_ANTIGO]) if linha.get(config.COL_PRECO_ANTIGO) else None
            pontos, motivos = _pontuar(nome, preco, de, bool(linha.get(config.COL_IMAGEM)), 0,
                                       cliques.get(str(linha.get("id")), 0))
            corpo = f"{link}\nnome: {nome}"
            if preco:
                corpo += "\npreco: " + f"{preco:.2f}".replace(".", ",")
            if de and preco and de > preco:
                corpo += "\nde: " + f"{de:.2f}".replace(".", ",")
            if linha.get(config.COL_IMAGEM):
                corpo += f"\nfoto: {linha[config.COL_IMAGEM]}"
            lista.append({"corpo": corpo, "origem": "postado", "pontos": pontos, "motivos": motivos})
    except Exception as erro:  # noqa: BLE001
        print(f"::warning::Roteiros (site): {str(erro)[:120]}")
    vistos, unicos, por_tipo = set(), [], {}
    for c in sorted(lista, key=lambda c: -c["pontos"]):
        chave = fila.chave_link(c["corpo"])
        nome = ler_mensagem(c["corpo"]).get("nome") or ""
        nome_chave = re.sub(r"[^a-z0-9]", "", nome.lower())[:28]
        if c["pontos"] < PONTOS_MINIMOS or not chave or chave in vistos or (nome_chave and nome_chave in vistos):
            continue
        achado = RE_BOM_DE_VIDEO.search(nome)
        tipo = achado.group(0).lower().replace(" ", "") if achado else "outros"
        if por_tipo.get(tipo, 0) >= MAX_POR_TIPO:          # variedade: não encher a página só de monitor
            continue
        por_tipo[tipo] = por_tipo.get(tipo, 0) + 1
        vistos.update({chave, nome_chave} - {""})
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
                itens.append({**antigos[ident], "origem": c["origem"], "pontos": c["pontos"],
                              "motivos": c["motivos"]})                     # kit já feito: reaproveita
                continue
            try:
                p, fotos_url = ler_produto(c["corpo"])
                if not p.nome:
                    continue
                pasta = Path(tmp) / str(n)
                pasta.mkdir()
                baixadas = baixar_imagens(p, pasta)
                k = roteiro.kit(p, baixadas[0] if baixadas else None)
                if not baixadas:
                    continue                          # sem foto não dá para gerar a cena: fica fora da página
                itens.append({"id": ident, "origem": c["origem"], "pontos": c["pontos"], "motivos": c["motivos"],
                              "nome": p.nome[:140], "link": p.link,
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

"""Quadro de ofertas (site/quadro.html): você monta quadradinhos com a imagem
(print/foto) e o link embaixo, e envia tudo de uma vez para a fila.

Como chega até o robô (sem chave secreta no navegador):
  1. A página (logada no admin) sobe cada imagem para o Storage do Supabase,
     pasta  quadro/<lote>/<n>.jpg  do bucket "produtos";
  2. e por último um arquivo  quadro/<lote>.json  com a lista {link, preco, nome, foto}.
  3. A cada rodada de 10 min o robô procura esses .json, coloca as ofertas na
     fila (cada uma com a sua imagem) e move o .json para quadro/importados/.

A imagem é lida pelo Gemini como um print (nome e preço) e vira a foto do post.
"""
from __future__ import annotations

import json

import requests

from . import amazon, config, fila, supabase

BUCKET = "produtos"
PASTA = "quadro/"


def _storage(caminho: str) -> str:
    return f"{config.SUPABASE_URL}/storage/v1/{caminho}"


def pendentes() -> list[str]:
    r = requests.post(_storage(f"object/list/{BUCKET}"), timeout=30,
                      headers=supabase._cabecalhos({"Content-Type": "application/json"}),
                      json={"prefix": PASTA, "limit": 100, "sortBy": {"column": "name", "order": "asc"}})
    if r.status_code >= 300:
        return []
    return [PASTA + o["name"] for o in r.json() if str(o.get("name", "")).endswith(".json")]


def _ler(caminho: str) -> dict:
    r = requests.get(_storage(f"object/{BUCKET}/{caminho}"), headers=supabase._cabecalhos(), timeout=30)
    r.raise_for_status()
    return r.json()


def _arquivar(caminho: str) -> None:
    destino = PASTA + "importados/" + caminho[len(PASTA):]
    requests.post(_storage("object/move"), timeout=30,
                  headers=supabase._cabecalhos({"Content-Type": "application/json"}),
                  json={"bucketId": BUCKET, "sourceKey": caminho, "destinationKey": destino})


def _texto(item: dict) -> str:
    linhas = [str(item.get("link", "")).strip()]
    if str(item.get("preco") or "").strip():
        linhas.append(f"preco: {str(item['preco']).strip()}")
    if str(item.get("nome") or "").strip():
        linhas.append(f"nome: {str(item['nome']).strip()}")
    return "\n".join(linhas)


def importar(enviar) -> int:
    """Coloca na fila os quadros enviados pelo site. Devolve quantas ofertas entraram."""
    if not (supabase.ativo() and fila.ativa()):
        return 0
    total_novas = 0
    for caminho in pendentes():
        try:
            dados = _ler(caminho)
        except Exception as erro:  # noqa: BLE001
            print(f"::warning::Quadro {caminho}: {str(erro)[:150]}")
            _arquivar(caminho)
            continue
        itens = [i for i in (dados.get("itens") or []) if isinstance(i, dict)
                 and fila.RE_LINK.search(str(i.get("link", "")))]
        _arquivar(caminho)                 # primeiro arquiva: nunca importa duas vezes
        if not itens:
            continue
        textos = [_texto(i) for i in itens]
        fotos = [str(i.get("foto") or "") or None for i in itens]
        total, proxima, ignorados = fila.adicionar(textos, fotos)
        novas = len(textos) - ignorados
        total_novas += novas
        avisos = []
        for i in itens:
            if amazon.e_amazon(i["link"]):
                novo_link, texto_tag = amazon.link_com_minha_tag(i["link"])
                if not novo_link:
                    avisos.append(f"{i['link']}\n{texto_tag}\n(na hora dele o robô pula esse link)")
                elif novo_link != i["link"]:
                    avisos.append(f"🔧 {i['link']}\n{texto_tag} (o robô ajusta na hora do post)")
        sem_foto = sum(1 for f in fotos if not f)
        linhas = [f"🗓️🖼️ Quadro do site: {novas} oferta(s) na fila (total: {total})."]
        if ignorados:
            linhas.append(f"♻️ {ignorados} link(s) repetido(s) ignorado(s).")
        if sem_foto:
            linhas.append(f"⚠️ {sem_foto} quadro(s) sem imagem — o robô tenta ler pela loja.")
        linhas.append(f"⏰ Próximo post: {proxima.strftime('%d/%m às %H:%M')}")
        linhas += ["", *avisos] if avisos else []
        linhas.append("\nMande /fila para conferir.")
        enviar("\n".join(linhas))
    return total_novas

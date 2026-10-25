"""Links rastreados do canal do Telegram.

Em vez do link da loja direto, o canal usa  certodrop.netlify.app/r.html?...
Essa página anota o clique (tabela "cliques" do Supabase, sem nenhum dado do
visitante) e leva na hora para a loja com o SEU link de afiliado. Assim o
relatório mostra quais ofertas dão clique no canal, não só no site.
No post aparece só "Comprar na loja ➜" (o endereço longo fica escondido).
"""
from __future__ import annotations

import base64
from html import escape

from . import config


def _b64(texto: str) -> str:
    return base64.urlsafe_b64encode(texto.encode()).decode().rstrip("=")


def link(destino: str, produto_id: str | int | None = None, nome: str = "") -> str:
    if not (config.RASTREAR_CLIQUES and destino):
        return destino
    partes = [f"u={_b64(destino)}"]
    if produto_id:
        partes.append(f"p={produto_id}")
    if nome:
        partes.append(f"n={_b64(nome[:80])}")
    return f"{config.SITE_URL.rstrip('/')}/r.html?" + "&".join(partes)


def legenda_html(texto: str, destino: str, produto_id=None, nome: str = "",
                 rotulo: str = "Comprar na loja ➜") -> str:
    """Legenda em HTML com a linha do link trocada por um link rastreado escondido."""
    url = link(destino, produto_id, nome)
    seguro = escape(texto)
    alvo = escape(destino)
    if alvo in seguro:
        return seguro.replace(alvo, f'<a href="{escape(url)}">{escape(rotulo)}</a>', 1)
    return seguro + f'\n🛒 <a href="{escape(url)}">{escape(rotulo)}</a>'

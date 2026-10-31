"""Terabyte (terabyteshop.com.br) — programa de Parceiros da própria loja.

O link de parceira é o link normal do produto com  ?p=SEU_CODIGO&tag=certodrop.
O robô coloca o seu código sozinho em qualquer link da Terabyte (como faz com a tag da Amazon).

O site da Terabyte bloqueia robôs: o nome e o preço vêm do print que você manda
junto com o link (ou das linhas  nome:  e  preco: ).
Código: variável TERABYTE_PARCEIRO (padrão: o seu, 3559600).
"""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from . import config


def e_terabyte(link: str) -> bool:
    return "terabyteshop.com" in (link or "").lower()


def link_com_meu_codigo(link: str) -> tuple[str, str]:
    """(link com o seu código de parceira, texto para o resumo)."""
    url = link if "://" in link else f"https://{link}"
    partes = urlparse(url)
    if "/produto/" not in partes.path:
        return link, "⚠️ Terabyte: mande o link da PÁGINA DO PRODUTO (terabyteshop.com.br/produto/…)"
    params = dict(parse_qsl(partes.query))
    tinha = params.get("p")
    params["p"] = config.TERABYTE_PARCEIRO
    params["tag"] = config.TERABYTE_TAG
    novo = urlunparse(partes._replace(query=urlencode(params)))
    if tinha == config.TERABYTE_PARCEIRO:
        return novo, "link de parceira da Terabyte conferido ✅"
    if tinha:
        return novo, f"o link tinha o código de OUTRA pessoa ({tinha}) — troquei pelo seu ✅"
    return novo, "coloquei o seu código de parceira da Terabyte ✅"

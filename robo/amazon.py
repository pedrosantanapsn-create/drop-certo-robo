"""Ajudas para links da Amazon (sem API — a Creators API só libera após 10 vendas).

• Confere se o link tem a SUA tag de associado (ex.: certodrop-20). Link sem a
  tag não paga comissão — acontece quando se copia o link da barra do navegador
  em vez do SiteStripe/"Compartilhar" logado na conta de associado.
• Descobre o endereço final (link.amazon / amzn.to) só pelos redirecionamentos,
  sem abrir a página (a Amazon bloqueia robôs).

A frase "Como Associado da Amazon, eu ganho com compras qualificadas." é
exigida pelo Programa de Associados e vai nos posts com link da Amazon.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlparse

import requests

from . import config

AVISO = "Como Associado da Amazon, eu ganho com compras qualificadas."
RE_ASIN = re.compile(r"/(?:dp|gp/product|d)/([A-Z0-9]{10})(?:[/?]|$)")


def e_amazon(link: str) -> bool:
    l = (link or "").lower()
    return any(s in l for s in ("amazon.", "amzn.", "link.amazon", "a.co/"))


def resolver(link: str) -> tuple[str, str | None, str | None]:
    """(endereço final, ASIN, tag de associado) seguindo só os redirecionamentos."""
    url = link if "://" in link else f"https://{link}"
    asin = tag = None
    for _ in range(6):
        achado = RE_ASIN.search(url)
        asin = asin or (achado.group(1) if achado else None)
        tag = tag or (parse_qs(urlparse(url).query).get("tag") or [None])[0]
        try:
            r = requests.get(url, allow_redirects=False, timeout=15,
                             headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "pt-BR"})
        except requests.RequestException:
            break
        proximo = r.headers.get("Location")
        if not proximo:
            break
        url = urljoin(url, proximo)
    return url, asin, tag


def link_com_minha_tag(link: str) -> tuple[str | None, str]:
    """Monta o SEU link de associado a partir de qualquer link de produto da Amazon.

    Link de produto copiado do navegador/app (sem tag) ou com a tag de outra pessoa
    vira  https://www.amazon.com.br/dp/<ASIN>?tag=<sua tag>  — é assim que funciona
    o link de texto do Programa de Associados (a comissão vai para a tag do link).
    Devolve (link novo ou None se não deu, explicação).
    """
    minha = (config.AMAZON_TAG or "").strip()
    try:
        final, asin, tag = resolver(link)
    except Exception:  # noqa: BLE001
        return None, "não consegui abrir o link"
    if tag == minha:
        return link, f"tag de associado {minha} ✅"
    if not (asin and minha):
        return None, ("⚠️ não achei o código do produto (ASIN) nesse link da Amazon — "
                      "abra a página do produto e copie o link dela.")
    novo = f"https://www.amazon.com.br/dp/{asin}?tag={minha}"
    if tag:
        return novo, f"o link tinha a tag de outra pessoa ({tag}) — troquei pela sua ({minha}) ✅"
    return novo, f"o link estava sem tag — coloquei a sua ({minha}) ✅"


def conferir_tag(link: str) -> tuple[bool | None, str]:
    """(True = tag certa, False = sem tag/tag de outra pessoa, None = não deu para saber, texto)."""
    minha = (config.AMAZON_TAG or "").strip()
    try:
        _, _, tag = resolver(link)
    except Exception:  # noqa: BLE001
        return None, "não consegui conferir a tag de associado"
    if not minha:
        return None, f"tag do link: {tag or 'nenhuma'}"
    if tag == minha:
        return True, f"tag de associado {minha} ✅"
    if not tag:
        return False, (f"⚠️ link da Amazon SEM a sua tag ({minha}) — NÃO paga comissão. "
                       "Gere o link pela barra SiteStripe ou 'Compartilhar' logada na sua conta de associado.")
    return False, (f"⚠️ link da Amazon com a tag de OUTRA pessoa ({tag}, a sua é {minha}) — "
                   "a comissão não vai para você. Gere o link de novo na sua conta.")

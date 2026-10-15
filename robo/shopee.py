"""Leitura oficial de produtos da Shopee pela API de Afiliados (gratuita).

A página da Shopee bloqueia robôs, mas a Shopee oferece aos afiliados uma API
oficial ("Open API" do painel de afiliados) que devolve nome, preço, desconto
e foto do produto. Com ela, o link da Shopee funciona sem mandar print.

Segredos no GitHub: SHOPEE_APP_ID e SHOPEE_APP_SECRET
(painel de afiliados da Shopee → Open API → solicitar acesso).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from urllib.parse import urljoin

import requests

from . import config

API = "https://open-api.affiliate.shopee.com.br/graphql"
RE_IDS = [re.compile(r"-i\.(\d+)\.(\d+)"), re.compile(r"/product/(\d+)/(\d+)"), re.compile(r"/(\d{4,})/(\d{6,})(?:[/?]|$)")]


def ativo() -> bool:
    return bool(config.SHOPEE_APP_ID and config.SHOPEE_APP_SECRET)


def e_shopee(link: str) -> bool:
    return "shopee" in (link or "").lower() or "shp.ee" in (link or "").lower()


def ids_do_link(link: str) -> tuple[int, int] | None:
    """(shopId, itemId). Segue o link curto só pelos redirecionamentos, sem abrir a página."""
    url = link if "://" in link else f"https://{link}"
    for _ in range(6):
        for regex in RE_IDS:
            achado = regex.search(url)
            if achado:
                return int(achado.group(1)), int(achado.group(2))
        try:
            r = requests.get(url, allow_redirects=False, timeout=20,
                             headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "pt-BR"})
        except requests.RequestException:
            return None
        proximo = r.headers.get("Location")
        if not proximo:
            return None
        url = urljoin(url, proximo)
    return None


def _consultar(consulta: str) -> dict:
    corpo = json.dumps({"query": consulta}, separators=(",", ":"))
    agora = str(int(time.time()))
    assinatura = hashlib.sha256(
        (config.SHOPEE_APP_ID + agora + corpo + config.SHOPEE_APP_SECRET).encode()).hexdigest()
    r = requests.post(API, data=corpo, timeout=30, headers={
        "Content-Type": "application/json",
        "Authorization": f"SHA256 Credential={config.SHOPEE_APP_ID}, Timestamp={agora}, Signature={assinatura}",
    })
    dados = r.json()
    if dados.get("errors"):
        raise RuntimeError(f"Shopee API: {dados['errors'][0].get('message', '')[:150]}")
    return dados.get("data") or {}


def _preco(valor) -> float | None:
    try:
        return float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return None


def ler(link: str) -> dict:
    """{"nome", "preco", "preco_antigo", "imagem"} do produto, ou {} se não der."""
    if not ativo() or not e_shopee(link):
        return {}
    ids = ids_do_link(link)
    if not ids:
        raise RuntimeError("não achei o código do produto no link da Shopee")
    loja, item = ids
    dados = _consultar(
        f"{{productOfferV2(shopId:{loja},itemId:{item},limit:1){{nodes{{"
        "productName price priceMin priceMax priceDiscountRate imageUrl}}}")
    nos = ((dados.get("productOfferV2") or {}).get("nodes")) or []
    if not nos:
        raise RuntimeError("a Shopee não devolveu esse produto (fora do programa de afiliados?)")
    no = nos[0]
    preco = _preco(no.get("priceMin") or no.get("price"))
    desconto = _preco(no.get("priceDiscountRate")) or 0
    antigo = round(preco / (1 - desconto / 100), 2) if preco and 0 < desconto < 95 else None
    return {"nome": no.get("productName"), "preco": preco, "preco_antigo": antigo, "imagem": no.get("imageUrl")}


# ---------------------------------------------------------------------------
# Busca de ofertas e link de afiliada (usados nas sugestões diárias)
# ---------------------------------------------------------------------------
ORDEM_MAIS_VENDIDOS = 2
ORDEM_MAIOR_COMISSAO = 5
CAMPOS_BUSCA = ("itemId shopId productName priceMin priceDiscountRate commissionRate commission "
                "sales ratingStar shopName productLink offerLink imageUrl")


def _texto(valor: str) -> str:
    return json.dumps(str(valor), ensure_ascii=False)   # aspas e acentos seguros na consulta


def buscar(palavra: str, ordem: int = ORDEM_MAIS_VENDIDOS, limite: int = 20) -> list[dict]:
    """Produtos do programa de afiliados para uma palavra-chave."""
    if not ativo():
        return []
    dados = _consultar(
        f"{{productOfferV2(keyword:{_texto(palavra)},sortType:{ordem},page:1,limit:{limite})"
        f"{{nodes{{{CAMPOS_BUSCA}}}}}}}")
    return [n for n in ((dados.get("productOfferV2") or {}).get("nodes") or []) if isinstance(n, dict)]


def link_afiliado(url: str, sub_id: str = "dropcerto") -> str:
    """Gera o SEU link curto de afiliada (comissão vai para a sua conta)."""
    dados = _consultar(
        f"mutation{{generateShortLink(input:{{originUrl:{_texto(url)},subIds:[{_texto(sub_id)}]}})"
        "{shortLink}}")
    link = (dados.get("generateShortLink") or {}).get("shortLink")
    if not link:
        raise RuntimeError("a Shopee não gerou o link de afiliada")
    return link

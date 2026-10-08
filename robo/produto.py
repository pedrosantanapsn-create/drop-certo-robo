"""Leitura dos dados do produto a partir do link de afiliado do Mercado Livre.

O robô NÃO gera link de afiliado: ele recebe o link meli.la que você já
gerou no Mercado Livre e só lê a página pública do anúncio (nome, preço,
fotos). Assim nenhuma senha ou cookie seu é usado.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html import unescape

import requests
from bs4 import BeautifulSoup

UA = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36"
)
CABECALHOS = {"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"}

RE_URL = re.compile(r"https?://\S+", re.I)
RE_PRECO = re.compile(r"R\$\s*([\d.]+(?:,\d{1,2})?)", re.I)


@dataclass
class Produto:
    link: str                       # seu link de afiliado (é ele que vai nos posts)
    nome: str = ""
    preco: float | None = None
    preco_antigo: float | None = None
    imagens: list[str] = field(default_factory=list)
    url_final: str = ""
    observacao: str = ""            # texto extra que você escreveu na mensagem

    @property
    def desconto(self) -> int | None:
        if self.preco and self.preco_antigo and self.preco_antigo > self.preco:
            return round((1 - self.preco / self.preco_antigo) * 100)
        return None


def formatar_preco(valor: float | None) -> str:
    if valor is None:
        return ""
    inteiro, centavos = f"{valor:,.2f}".split(".")
    return f"R$ {inteiro.replace(',', '.')},{centavos}"


def _para_float(texto: str | float | int | None) -> float | None:
    if texto is None:
        return None
    if isinstance(texto, (int, float)):
        return float(texto)
    t = str(texto).strip()
    if "," in t:  # formato brasileiro 1.299,90
        t = t.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\D*\d{1,3}(\.\d{3})+\D*", t):  # 1.599 = mil quinhentos e noventa e nove
        t = t.replace(".", "")
    try:
        return float(re.sub(r"[^\d.]", "", t))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Mensagem do Telegram
# ---------------------------------------------------------------------------
def ler_mensagem(texto: str) -> dict:
    """Extrai link, preço e campos manuais da mensagem.

    Formatos aceitos:
      meli.la/abc123
      https://meli.la/abc123 R$ 89,90
      https://meli.la/abc123
      nome: Mouse gamer XYZ
      preco: 89,90
      de: 149,90
      obs: ótimo para home office
    """
    texto = texto or ""
    achados = RE_URL.findall(texto)
    if not achados:
        m = re.search(r"\b(meli\.la/\S+|mercadolivre\.com\.br/\S+)", texto, re.I)
        achados = [f"https://{m.group(1)}"] if m else []
    dados: dict = {"link": achados[0].rstrip(").,") if achados else ""}

    for linha in texto.splitlines():
        if ":" not in linha or RE_URL.match(linha.strip()):
            continue
        chave, valor = (p.strip() for p in linha.split(":", 1))
        chave = chave.lower()
        if chave in ("nome", "titulo", "título"):
            dados["nome"] = valor
        elif chave in ("preco", "preço", "por"):
            dados["preco"] = _para_float(valor)
        elif chave in ("de", "antes", "preco antigo", "preço antigo"):
            dados["preco_antigo"] = _para_float(valor)
        elif chave in ("obs", "observacao", "observação", "texto"):
            dados["observacao"] = valor

    if "preco" not in dados:
        precos = RE_PRECO.findall(texto)
        if precos:
            dados["preco"] = _para_float(precos[0])
            if len(precos) > 1:
                dados["preco_antigo"] = _para_float(precos[1])
    return dados


# ---------------------------------------------------------------------------
# Leitura da página
# ---------------------------------------------------------------------------
def _json_ld_produto(sopa: BeautifulSoup) -> dict:
    for bloco in sopa.find_all("script", type="application/ld+json"):
        try:
            dados = json.loads(bloco.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        itens = dados if isinstance(dados, list) else dados.get("@graph", [dados])
        for item in itens:
            if isinstance(item, dict) and item.get("@type") in ("Product", ["Product"]):
                return item
    return {}


def _meta(sopa: BeautifulSoup, *nomes: str) -> str:
    for nome in nomes:
        tag = sopa.find("meta", attrs={"property": nome}) or sopa.find(
            "meta", attrs={"name": nome}
        ) or sopa.find("meta", attrs={"itemprop": nome})
        if tag and tag.get("content"):
            return unescape(tag["content"]).strip()
    return ""


def _link_de_produto_na_pagina(sopa: BeautifulSoup) -> str:
    """Links meli.la às vezes caem numa vitrine; pega o 1º anúncio dela."""
    for a in sopa.find_all("a", href=True):
        href = a["href"]
        if re.search(r"mercadolivre\.com\.br/(.+/)?(p/)?MLB-?\d+", href):
            return href
    return ""


def _extrair(html: str, produto: Produto) -> bool:
    sopa = BeautifulSoup(html, "html.parser")
    ld = _json_ld_produto(sopa)

    nome = ld.get("name") or _meta(sopa, "og:title")
    if nome:
        produto.nome = produto.nome or re.sub(r"\s*\|\s*Mercado Livre.*$", "", nome).strip()

    oferta = ld.get("offers") or {}
    if isinstance(oferta, list):
        oferta = oferta[0] if oferta else {}
    preco = _para_float(oferta.get("price")) or _para_float(_meta(sopa, "product:price:amount", "price"))
    if preco and produto.preco is None:
        produto.preco = preco

    antigo = sopa.select_one(".ui-pdp-price__original-value .andes-money-amount__fraction")
    if antigo and produto.preco_antigo is None:
        centavos = sopa.select_one(".ui-pdp-price__original-value .andes-money-amount__cents")
        valor = antigo.get_text(strip=True) + ("," + centavos.get_text(strip=True) if centavos else "")
        produto.preco_antigo = _para_float(valor)

    imagens = ld.get("image") or []
    if isinstance(imagens, str):
        imagens = [imagens]
    og = _meta(sopa, "og:image")
    if og:
        imagens = [og, *imagens]
    for img in sopa.select("figure.ui-pdp-gallery__figure img"):
        src = img.get("data-zoom") or img.get("src") or ""
        if src.startswith("http"):
            imagens.append(src)
    vistos: list[str] = []
    for img in imagens:
        img = img.replace("-I.jpg", "-O.jpg").replace(".webp", ".jpg")
        if img.startswith("http") and img not in vistos:
            vistos.append(img)
    produto.imagens = produto.imagens or vistos[:4]
    return bool(produto.nome and produto.imagens)


def buscar_produto(dados: dict) -> Produto:
    produto = Produto(
        link=dados.get("link", ""),
        nome=dados.get("nome", ""),
        preco=dados.get("preco"),
        preco_antigo=dados.get("preco_antigo"),
        observacao=dados.get("observacao", ""),
    )
    if not produto.link:
        raise ValueError("Não encontrei nenhum link na mensagem.")

    sessao = requests.Session()
    sessao.headers.update(CABECALHOS)
    resp = sessao.get(produto.link, timeout=25, allow_redirects=True)
    produto.url_final = resp.url

    if not _extrair(resp.text, produto):
        outro = _link_de_produto_na_pagina(BeautifulSoup(resp.text, "html.parser"))
        if outro:
            resp = sessao.get(outro, timeout=25)
            produto.url_final = resp.url
            _extrair(resp.text, produto)
    return produto


def baixar_imagens(produto: Produto, pasta) -> list:
    caminhos = []
    for i, url in enumerate(produto.imagens[:4]):
        try:
            r = requests.get(url, headers=CABECALHOS, timeout=25)
            r.raise_for_status()
            caminho = pasta / f"foto_{i}.jpg"
            caminho.write_bytes(r.content)
            caminhos.append(caminho)
        except requests.RequestException:
            continue
    return caminhos

"""Leitura dos dados do produto a partir do link de afiliado.

Funciona com o Mercado Livre (meli.la) e, de forma genérica, com outras lojas
(Amazon, Shopee, Magalu, AliExpress...): lê os dados que as lojas publicam
para o Google (JSON-LD e etiquetas og:). Se a loja bloquear robôs, você manda
nome e preço na mensagem (e de preferência uma foto) que o post sai igual.

O robô NÃO gera link de afiliado: ele recebe o link que você já gerou na loja
e só lê a página pública do anúncio. Nenhuma senha ou cookie seu é usado.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html import unescape
from urllib.parse import unquote, urlparse

import requests
from bs4 import BeautifulSoup

UA = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36"
)
CABECALHOS = {"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"}

RE_URL = re.compile(r"https?://\S+", re.I)
# Sufixos que as lojas colocam no título da página
RE_SUFIXO_LOJA = re.compile(
    r"\s*(\||\s-\s|–)\s*(Mercado\s?Livre|Amazon\.com\.br|Amazon|Shopee(\s+Brasil)?|Magazine Luiza|"
    r"Magalu|AliExpress|KaBuM!?|Americanas|Casas Bahia|Netshoes)(\.com(\.br)?)?\s*$", re.I)
RE_PREFIXO_AMAZON = re.compile(r"^Amazon\.com\.br\s*:\s*", re.I)
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
    cupom: str = ""                 # código do cupom (linha "cupom: CODIGO ...")
    cupom_info: str = ""            # o que o cupom dá / regras (ex.: "10% off", "válido até 20/10")
    imagens_extra: list[str] = field(default_factory=list)  # achadas por regra de cada loja
    bloqueado: bool = False          # a loja pediu verificação de robô
    nome_do_link: bool = False       # o nome veio do endereço (pode estar incompleto)
    site_id: str = ""                # id do produto no site (para o link rastreado do canal)
    chave_preco: str = ""            # chave no histórico de preços (shopee:123 / ml:MLB123)
    alerta: str = ""                 # "bug" = possível erro de preço (post especial no canal)

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
    # "mercadolivre.com.br/p /MLB123" (o Telegram às vezes quebra o link no /p/): junta de novo
    texto = re.sub(r"(\.com\.br/p)\s+/(MLB)", r"\1/\2", texto, flags=re.I)
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
        elif chave == "alerta":
            dados["alerta"] = valor.lower()
        elif chave in ("cupom", "cupon", "codigo", "código", "cupom de desconto"):
            partes = valor.split(None, 1)
            if partes:
                dados["cupom"] = partes[0].strip(" -–:").upper()
                dados["cupom_info"] = (partes[1] if len(partes) > 1 else "").strip(" -–()")

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
            if not isinstance(item, dict):
                continue
            tipo = item.get("@type")
            tipos = tipo if isinstance(tipo, list) else [tipo]
            if "Product" in tipos or "ProductGroup" in tipos:
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


RE_ARIA = re.compile(r"(Agora|Antes)?:?\s*([\d.]+)\s*reais(?:\s*com\s*(\d{1,2})\s*centavos?)?", re.I)


def _precos_aria(sopa: BeautifulSoup) -> tuple[float | None, float | None]:
    """Lê o 1º par Antes/Agora dos rótulos de acessibilidade dos preços."""
    agora = antes = None
    for el in sopa.select("[aria-label]"):
        m = RE_ARIA.fullmatch(el["aria-label"].strip())
        if not m:
            continue
        valor = float(m.group(2).replace(".", "")) + (int(m.group(3)) / 100 if m.group(3) else 0)
        rotulo = (m.group(1) or "").lower()
        if rotulo == "antes" and antes is None and agora is None:
            antes = valor
        elif rotulo == "agora" or (not rotulo and agora is None):
            agora = valor
            break
    return agora, antes


class LojaBloqueou(RuntimeError):
    """A loja mostrou uma página de verificação ("não sou robô") no lugar do produto."""


def _amazon(sopa: BeautifulSoup, produto: Produto) -> None:
    """A Amazon não publica JSON-LD de produto; lê os campos da própria página."""
    titulo = sopa.select_one("#productTitle")
    if not titulo:
        return
    if not produto.nome:
        produto.nome = titulo.get_text(" ", strip=True)
    if produto.preco is None:
        el = sopa.select_one("#corePrice_feature_div .a-offscreen, .priceToPay .a-offscreen, "
                             "#apex_desktop .a-price .a-offscreen, .a-price .a-offscreen")
        if el:
            produto.preco = _para_float(el.get_text(strip=True))
    if produto.preco_antigo is None:
        el = sopa.select_one(".basisPrice .a-offscreen, .a-price.a-text-price .a-offscreen")
        if el:
            antigo = _para_float(el.get_text(strip=True))
            if antigo and produto.preco and antigo > produto.preco:
                produto.preco_antigo = antigo
    img = sopa.select_one("#landingImage, #imgBlkFront")
    if img:
        grande = img.get("data-old-hires") or ""
        if not grande and img.get("data-a-dynamic-image"):
            try:
                grande = next(iter(json.loads(img["data-a-dynamic-image"])), "")
            except (ValueError, TypeError):
                grande = ""
        grande = grande or img.get("src", "")
        if grande.startswith("http"):
            produto.imagens_extra.append(grande)


def _pagina_de_bloqueio(html: str) -> bool:
    trecho = html[:20000].lower()
    sinais = ("validatecaptcha", "robot check", "digite os caracteres", "are you a human",
              "verify you are human", "captcha-delivery", "/punish?", "unusual traffic")
    return any(s in trecho for s in sinais)


def _extrair(html: str, produto: Produto) -> bool:
    if _pagina_de_bloqueio(html):
        raise LojaBloqueou("a loja pediu verificação de robô")
    sopa = BeautifulSoup(html, "html.parser")
    ld = _json_ld_produto(sopa)

    _amazon(sopa, produto)

    nome = ld.get("name") or _meta(sopa, "og:title", "twitter:title")
    if nome and not produto.nome:
        nome = RE_PREFIXO_AMAZON.sub("", unescape(str(nome)))
        produto.nome = RE_SUFIXO_LOJA.sub("", nome).strip()

    oferta = ld.get("offers") or {}
    if isinstance(oferta, list):
        oferta = oferta[0] if oferta else {}
    if not isinstance(oferta, dict):
        oferta = {}
    preco = (_para_float(oferta.get("price")) or _para_float(oferta.get("lowPrice"))
             or _para_float((oferta.get("priceSpecification") or {}).get("price")
                            if isinstance(oferta.get("priceSpecification"), dict) else None)
             or _para_float(_meta(sopa, "product:price:amount", "og:price:amount", "price")))
    if preco and produto.preco is None:
        produto.preco = preco

    # Página "Perfil Social" (meli.la/...): preços em aria-label "Antes: X reais com Y centavos"
    if produto.preco is None or produto.preco_antigo is None:
        agora, antes = _precos_aria(sopa)
        if agora and produto.preco is None:
            produto.preco = agora
        if antes and produto.preco_antigo is None:
            produto.preco_antigo = antes

    antigo = sopa.select_one(".ui-pdp-price__original-value .andes-money-amount__fraction")
    if antigo and produto.preco_antigo is None:
        centavos = sopa.select_one(".ui-pdp-price__original-value .andes-money-amount__cents")
        valor = antigo.get_text(strip=True) + ("," + centavos.get_text(strip=True) if centavos else "")
        produto.preco_antigo = _para_float(valor)

    imagens = ld.get("image") or []
    if isinstance(imagens, (str, dict)):
        imagens = [imagens]
    imagens = [i.get("url", "") if isinstance(i, dict) else str(i) for i in imagens]
    imagens = list(produto.imagens_extra) + imagens
    og = _meta(sopa, "og:image", "og:image:secure_url", "twitter:image")
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


RE_TITULO_GENERICO = re.compile(
    r"(ofertas incr[ií]veis|melhores pre[cç]os|compre online|frete gr[aá]tis|"
    r"^\s*(shopee|amazon|mercado ?livre|magalu|aliexpress)\b|p[aá]gina inicial|login|entrar)", re.I)


def titulo_generico(nome: str) -> bool:
    """True se o "nome" é o título da loja (página inicial/vitrine), não de um produto."""
    return bool(nome) and bool(RE_TITULO_GENERICO.search(nome))


def nome_pela_url(url: str) -> str:
    """Tira o nome do produto do próprio endereço, quando a loja o coloca lá.

    Ex.: amazon.com.br/Echo-Dot-5ª-geração-Cor-Preta/dp/B09B8VGCR8 -> "Echo Dot 5ª geração Cor Preta"
    """
    caminho = unquote(urlparse(url or "").path)
    melhor = ""
    for parte in caminho.split("/"):
        parte = re.sub(r"^MLB-?\d+-", "", parte)            # Mercado Livre
        parte = re.sub(r"(-_JM.*|-i\.\d+\.\d+.*)$", "", parte)  # ML / Shopee
        parte = re.sub(r"\.html?$", "", parte)
        if parte.count("-") >= 2 and len(parte) > len(melhor):
            melhor = parte
    nome = re.sub(r"\s+", " ", melhor.replace("-", " ").replace("_", " ")).strip()
    return nome[:1].upper() + nome[1:] if len(nome) >= 6 else ""


def buscar_produto(dados: dict) -> Produto:
    produto = Produto(
        link=dados.get("link", ""),
        nome=dados.get("nome", ""),
        preco=dados.get("preco"),
        preco_antigo=dados.get("preco_antigo"),
        observacao=dados.get("observacao", ""),
        cupom=dados.get("cupom", ""),
        cupom_info=dados.get("cupom_info", ""),
        alerta=dados.get("alerta", ""),
    )
    if not produto.link:
        raise ValueError("Não encontrei nenhum link na mensagem.")

    sessao = requests.Session()
    sessao.headers.update(CABECALHOS)
    try:
        resp = sessao.get(produto.link, timeout=25, allow_redirects=True)
        produto.url_final = resp.url
        if not _extrair(resp.text, produto) or produto.preco is None:
            outro = _link_de_produto_na_pagina(BeautifulSoup(resp.text, "html.parser"))
            if outro:
                resp = sessao.get(outro, timeout=25)
                produto.url_final = resp.url
                _extrair(resp.text, produto)
    except LojaBloqueou:
        produto.bloqueado = True
    except requests.RequestException:
        produto.bloqueado = True

    # Título genérico da loja (ex.: link curto que caiu na página inicial): descarta
    if titulo_generico(produto.nome) and not dados.get("nome"):
        produto.nome = ""
        produto.imagens = []          # a imagem da vitrine é o logo da loja, não o produto
        produto.bloqueado = True

    # Sem nome (loja bloqueou ou página estranha): tenta tirar do próprio endereço
    if not produto.nome:
        for url in (produto.url_final, produto.link):
            nome = nome_pela_url(url)
            if nome:
                produto.nome, produto.nome_do_link = nome, True
                break
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

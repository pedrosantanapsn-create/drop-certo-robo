"""Busca automática de ofertas: todo dia o robô procura promoções de
tecnologia e manda as melhores para você escolher no Telegram.

De onde vêm: das ofertas publicadas no Promobit (site brasileiro de
promoções verificadas pela comunidade). O Mercado Livre e a Amazon bloqueiam
robôs vindos de servidores, então ler direto deles não funciona.

O robô NÃO usa o link do Promobit nem o de outra pessoa: ele manda o nome,
o preço e um link de BUSCA na loja. Você acha o produto, gera o SEU link de
afiliado no painel da loja e manda para o bot — aí ele posta como sempre.
Também não copia fotos nem textos de lá; o post é montado da página da loja.

Shopee (API oficial de afiliados): o robô também busca direto na Shopee por
palavras-chave de tecnologia, escolhe os produtos que vendem bem, têm boa nota
e pagam mais comissão, e já manda o SEU link de afiliada pronto — é só
encaminhar o link para o bot.

Envio automático: todo dia às 10h (horário de Brasília). Comandos: /ofertas e
/shopee [palavra]
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from urllib.parse import quote_plus

import requests

import math

from . import amazon, config, mercadolivre, shopee, supabase
from .fila import FUSO
from .produto import CABECALHOS, formatar_preco

CHAVE_PROXIMA = "ofertas_proxima"
CHAVE_VISTAS = "ofertas_vistas"
HORA = 10
QUANTAS = 6
DESCONTO_MINIMO = 20          # %
PAGINAS = [
    "https://www.promobit.com.br/promocoes/informatica/",
    "https://www.promobit.com.br/promocoes/games/",
    "https://www.promobit.com.br/",          # página inicial: só entra o que for de tecnologia
]
RE_TECNOLOGIA = re.compile(
    r"\b(celular|smartphone|iphone|galaxy|xiaomi|redmi|motorola|fone|headset|earbuds?|airpods|"
    r"notebook|laptop|tablet|ipad|monitor|tv|smart ?tv|mouse|teclado|ssd|hd externo|pendrive|"
    r"mem[oó]ria|placa de v[ií]deo|processador|roteador|wi-?fi|smartwatch|rel[oó]gio inteligente|"
    r"caixa de som|soundbar|echo|alexa|kindle|carregador|power ?bank|cabo usb|webcam|"
    r"c[aâ]mera|drone|console|playstation|ps5|xbox|nintendo|controle|gamer)\b", re.I)
BUSCA = {
    "Mercado Livre": "https://lista.mercadolivre.com.br/{q}",
    "Amazon": "https://www.amazon.com.br/s?k={q}",
    "Shopee": "https://shopee.com.br/search?keyword={q}",
    "Magalu": "https://www.magazineluiza.com.br/busca/{q}/",
    "KaBuM!": "https://www.kabum.com.br/busca/{q}",
    "AliExpress": "https://pt.aliexpress.com/w/wholesale-{q}.html",
}


def _lojas_aceitas() -> set[str]:
    texto = getattr(config, "LOJAS_OFERTAS", "") or "Mercado Livre,Amazon,Shopee"
    return {l.strip().lower() for l in texto.split(",") if l.strip()}


def _ler_pagina(url: str) -> list[dict]:
    try:
        r = requests.get(url, headers=CABECALHOS, timeout=25)
    except requests.RequestException:
        return []
    if r.status_code != 200:
        return []
    achado = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
    if not achado:
        return []
    try:
        props = json.loads(achado.group(1)).get("props", {}).get("pageProps", {})
    except ValueError:
        return []
    ofertas = (props.get("serverOffers") or {}).get("offers") or []
    return [o for o in ofertas if isinstance(o, dict)]


def _vistas() -> list[str]:
    try:
        return json.loads((supabase.ler_config(CHAVE_VISTAS) or {}).get("valor") or "[]")
    except ValueError:
        return []


def buscar(quantas: int = QUANTAS) -> list[dict]:
    """As melhores ofertas novas (ainda não sugeridas), já filtradas."""
    lojas = _lojas_aceitas()
    vistas = set(_vistas())
    todas: dict[str, dict] = {}
    limite = datetime.now(FUSO) - timedelta(days=3)
    for url in PAGINAS:
        geral = url.rstrip("/").endswith("promobit.com.br")
        for o in _ler_pagina(url):
            if geral and not RE_TECNOLOGIA.search(str(o.get("offerTitle", ""))):
                continue
            ident = str(o.get("offerId") or "")
            loja = str(o.get("storeName") or "")
            desconto = float(o.get("offerDiscontPercentage") or 0)
            if not ident or ident in vistas or ident in todas:
                continue
            if loja.lower() not in lojas or desconto < DESCONTO_MINIMO or not o.get("offerPrice"):
                continue
            if str(o.get("offerStatusName", "APPROVED")) != "APPROVED":
                continue
            try:
                publicada = datetime.strptime(str(o.get("offerPublished"))[:19], "%Y-%m-%dT%H:%M:%S")
                if publicada.replace(tzinfo=FUSO) < limite:
                    continue          # oferta velha: o preço provavelmente já mudou
            except ValueError:
                pass
            curtidas = int(o.get("offerLikes") or 0)
            o["_nota"] = desconto + min(curtidas, 60) / 2
            todas[ident] = o
    return sorted(todas.values(), key=lambda o: -o["_nota"])[:quantas]


def mensagem(ofertas: list[dict]) -> str:
    if not ofertas:
        return ("🔎 Não achei ofertas novas de tecnologia com bom desconto agora.\n"
                "Tento de novo amanhã às 10h (ou mande /ofertas mais tarde).")
    linhas = ["🔎 Ofertas sugeridas para o Drop Certo", ""]
    for i, o in enumerate(ofertas, 1):
        loja = o.get("storeName", "")
        titulo = str(o.get("offerTitle", ""))[:90]
        preco = formatar_preco(float(o["offerPrice"]))
        antes = f" (antes {formatar_preco(float(o['offerOldPrice']))})" if o.get("offerOldPrice") else ""
        busca = BUSCA.get(loja, "https://www.google.com/search?q={q}").format(
            q=quote_plus(" ".join(titulo.split()[:8])))
        linhas += [f"{i}. 🔥 -{round(float(o.get('offerDiscontPercentage', 0)))}% · {loja}",
                   f"{titulo}", f"💰 {preco}{antes}", f"🔗 Achar na loja: {busca}", ""]
    linhas += ["👉 Gostou de alguma? Abra na loja, confira o preço, gere o SEU link de afiliado",
               "e me mande o link (ou /agendar link). Eu monto e posto tudo.",
               "ℹ️ Preços vistos agora: podem mudar até você postar."]
    return "\n".join(linhas)


def sugerir() -> str:
    """Busca, marca como vistas e devolve o texto para o Telegram."""
    ofertas = buscar()
    if ofertas and supabase.ativo():
        vistas = (_vistas() + [str(o["offerId"]) for o in ofertas])[-400:]
        supabase.gravar_config(CHAVE_VISTAS, json.dumps(vistas))
    return mensagem(ofertas)


# ---------------------------------------------------------------------------
# Shopee: busca pela API oficial, com o seu link de afiliada pronto
# ---------------------------------------------------------------------------
SHOPEE_QUANTAS = 5
SHOPEE_DESCONTO_MINIMO = 15     # %
SHOPEE_NOTA_MINIMA = 4.5
SHOPEE_VENDAS_MINIMAS = 50


def _palavras_shopee() -> list[str]:
    texto = getattr(config, "PALAVRAS_SHOPEE", "") or ""
    return [p.strip() for p in texto.split(",") if p.strip()]


def _num(valor, padrao: float = 0.0) -> float:
    try:
        return float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return padrao


def buscar_shopee(palavras: list[str] | None = None, quantas: int = SHOPEE_QUANTAS,
                  marcar: bool = True) -> list[dict]:
    """Melhores produtos da Shopee: vendem bem, nota alta, desconto e boa comissão."""
    if not shopee.ativo():
        return []
    vistas = set(_vistas()) if marcar else set()
    achados: dict[str, dict] = {}
    for palavra in palavras or _palavras_shopee():
        for ordem in (shopee.ORDEM_MAIS_VENDIDOS, shopee.ORDEM_MAIOR_COMISSAO):
            try:
                nos = shopee.buscar(palavra, ordem, 20)
            except Exception as erro:  # noqa: BLE001
                print(f"::warning::Shopee busca '{palavra}': {str(erro)[:150]}")
                continue
            for n in nos:
                ident = f"shopee:{n.get('itemId')}"
                if ident in vistas or ident in achados:
                    continue
                desconto = _num(n.get("priceDiscountRate"))
                nota = _num(n.get("ratingStar"))
                vendas = _num(n.get("sales"))
                comissao = _num(n.get("commissionRate"))      # 0.07 = 7%
                preco = _num(n.get("priceMin"), None)
                if not preco or desconto < SHOPEE_DESCONTO_MINIMO or vendas < SHOPEE_VENDAS_MINIMAS:
                    continue
                if nota and nota < SHOPEE_NOTA_MINIMA:
                    continue
                n["_id"] = ident
                n["_palavra"] = palavra
                n["_nota"] = comissao * 100 * 2 + desconto / 2 + math.log10(vendas + 1) * 3
                achados[ident] = n
    melhores = sorted(achados.values(), key=lambda n: -n["_nota"])
    # no máximo 2 por palavra, para variar os produtos
    escolhidos, por_palavra = [], {}
    for n in melhores:
        if por_palavra.get(n["_palavra"], 0) >= 2:
            continue
        por_palavra[n["_palavra"]] = por_palavra.get(n["_palavra"], 0) + 1
        escolhidos.append(n)
        if len(escolhidos) >= quantas:
            break
    for n in escolhidos:
        try:
            n["_link"] = shopee.link_afiliado(str(n.get("productLink") or n.get("offerLink")))
        except Exception as erro:  # noqa: BLE001
            print(f"::warning::Shopee link: {str(erro)[:150]}")
            n["_link"] = n.get("offerLink") or n.get("productLink")
    if escolhidos and marcar and supabase.ativo():
        lista = (_vistas() + [n["_id"] for n in escolhidos])[-400:]
        supabase.gravar_config(CHAVE_VISTAS, json.dumps(lista))
    return escolhidos


def mensagem_shopee(produtos: list[dict], titulo: str = "🛍️ Shopee — sugestões com o SEU link") -> str:
    if not shopee.ativo():
        return ""
    if not produtos:
        return "🛍️ Shopee: não achei produtos novos com bom desconto e boa nota agora."
    linhas = [titulo, ""]
    for i, n in enumerate(produtos, 1):
        preco = _num(n.get("priceMin"), None)
        desconto = _num(n.get("priceDiscountRate"))
        antes = round(preco / (1 - desconto / 100), 2) if preco and 0 < desconto < 95 else None
        comissao = _num(n.get("commissionRate")) * 100
        ganho = _num(n.get("commission"), None)
        vendas = int(_num(n.get("sales")))
        nota = _num(n.get("ratingStar"))
        linhas += [
            f"{i}. 🔥 -{round(desconto)}% · ⭐ {nota:.1f} · {vendas:,} vendidos".replace(",", "."),
            str(n.get("productName", ""))[:90],
            f"💰 {formatar_preco(preco)}" + (f" (antes ~{formatar_preco(antes)})" if antes else ""),
            f"💸 Comissão: {comissao:.0f}%".replace(".", ",")
            + (f" (~{formatar_preco(ganho)} por venda)" if ganho else ""),
            f"🔗 {n.get('_link')}",
            "",
        ]
    linhas += ["📋 Todos os links (copie este bloco e mande para mim — vão direto para a fila):",
               *[str(n.get("_link")) for n in produtos], ""]
    linhas += ["👉 Para postar só um: copie o link 🔗 dele e mande para mim.",
               "O robô lê nome, preço e foto pela API da Shopee — sem print.",
               "ℹ️ Preço e comissão de agora: podem mudar até o post sair."]
    return "\n".join(linhas)


def sugerir_shopee(palavras: list[str] | None = None) -> str:
    return mensagem_shopee(buscar_shopee(palavras))


# ---------------------------------------------------------------------------
# Mercado Livre: mais vendidos de cada categoria (API oficial), com desconto
# ---------------------------------------------------------------------------
ML_QUANTAS = 8
ML_POR_CATEGORIA = 6
ML_DESCONTO_MINIMO = 10      # %


def _palavras_ml() -> list[str]:
    texto = getattr(config, "PALAVRAS_ML", "") or getattr(config, "PALAVRAS_SHOPEE", "") or ""
    return [p.strip() for p in texto.split(",") if p.strip()]


def buscar_ml(palavras: list[str] | None = None, quantas: int = ML_QUANTAS) -> list[dict]:
    """Mais vendidos do ML nas categorias das palavras, com desconto real agora."""
    if not mercadolivre.ativo():
        return []
    vistas = set(_vistas())
    achados: dict[str, dict] = {}
    categorias_vistas: set[str] = set()
    for palavra in palavras or _palavras_ml():
        try:
            dominio = (mercadolivre._get("/sites/MLB/domain_discovery/search", q=palavra, limit=1) or [{}])[0]
            categoria = dominio.get("category_id")
            if not categoria or categoria in categorias_vistas:
                continue
            categorias_vistas.add(categoria)
            ranking = mercadolivre._get(f"/highlights/MLB/category/{categoria}").get("content") or []
        except Exception as erro:  # noqa: BLE001
            print(f"::warning::ML mais vendidos '{palavra}': {str(erro)[:150]}")
            continue
        for pos in ranking[:ML_POR_CATEGORIA]:
            ident = str(pos.get("id") or "")
            if pos.get("type") != "PRODUCT" or not ident or f"ml:{ident}" in vistas or f"ml:{ident}" in achados:
                continue
            try:
                lista = mercadolivre._get(f"/products/{ident}/items").get("results") or []
                if not lista:
                    continue
                vendedor = lista[0]
                preco, antes = vendedor.get("price"), vendedor.get("original_price")
                if not preco or not antes or antes <= preco:
                    continue
                desconto = (1 - preco / antes) * 100
                if desconto < ML_DESCONTO_MINIMO:
                    continue
                produto = mercadolivre._get(f"/products/{ident}")
            except Exception:  # noqa: BLE001
                continue
            achados[f"ml:{ident}"] = {
                "_id": f"ml:{ident}", "_palavra": palavra, "id": ident,
                "nome": produto.get("name", ""), "preco": preco, "antes": antes,
                "desconto": desconto, "posicao": pos.get("position") or 99,
                "categoria": dominio.get("category_name", ""),
                "link": f"https://www.mercadolivre.com.br/p/{ident}",
                "_nota": desconto - (pos.get("position") or 99) * 1.5,
            }
    melhores = sorted(achados.values(), key=lambda n: -n["_nota"])
    escolhidos, por_palavra = [], {}
    for n in melhores:
        if por_palavra.get(n["_palavra"], 0) >= 2:
            continue
        por_palavra[n["_palavra"]] = por_palavra.get(n["_palavra"], 0) + 1
        escolhidos.append(n)
        if len(escolhidos) >= quantas:
            break
    if escolhidos and supabase.ativo():
        lista = (_vistas() + [n["_id"] for n in escolhidos])[-400:]
        supabase.gravar_config(CHAVE_VISTAS, json.dumps(lista))
    return escolhidos


def mensagem_ml(produtos: list[dict], html: bool = False) -> str:
    if not mercadolivre.ativo():
        return "🟡 A API do Mercado Livre não está ligada. Mande /ml para autorizar."
    if not produtos:
        return ("🛒 Mercado Livre: não achei produtos novos com desconto entre os mais vendidos agora.\n"
                "Tente /ofertas_ml com outra palavra (ex.: /ofertas_ml monitor).")
    from html import escape
    e = escape if html else (lambda x: x)
    linhas = ["🛒 Mercado Livre — mais vendidos com desconto", ""]
    for i, n in enumerate(produtos, 1):
        link = (f'🔗 <a href="{e(n["link"])}">Abrir no Mercado Livre ({e(n["id"])})</a>' if html
                else f"🔗 {n['link']}")
        linhas += [
            f"{i}. 🔥 -{round(n['desconto'])}% · 🏆 {n['posicao']}º mais vendido em {e(n['categoria'])}",
            e(str(n["nome"])[:90]),
            f"💰 {formatar_preco(n['preco'])} (antes {formatar_preco(n['antes'])})",
            link,
            "",
        ]
    linhas += ["👉 Para postar: abra o link, gere o SEU link de afiliado (meli.la) na barra",
               "de afiliados do Mercado Livre e mande para mim (ou /agendar link).",
               "ℹ️ O ML não tem API para gerar link de afiliado — esse passo é seu.",
               "ℹ️ Preço do vendedor principal agora: pode mudar até o post sair."]
    return "\n".join(linhas)


def sugerir_ml(palavras: list[str] | None = None, html: bool = False) -> str:
    return mensagem_ml(buscar_ml(palavras), html=html)


# ---------------------------------------------------------------------------
# Amazon: promoções da Amazon publicadas no Promobit (sem API da Amazon)
# ---------------------------------------------------------------------------
AMZ_PAGINA = "https://www.promobit.com.br/promocoes/loja/amazon/"
AMZ_QUANTAS = 8
AMZ_DESCONTO_MINIMO = 15


def buscar_amazon(palavra: str = "", quantas: int = AMZ_QUANTAS, so_tecnologia: bool = True) -> list[dict]:
    vistas = set(_vistas())
    limite = datetime.now(FUSO) - timedelta(days=3)
    achados: dict[str, dict] = {}
    paginas = [AMZ_PAGINA, AMZ_PAGINA + "?page=2", AMZ_PAGINA + "?page=3"]
    if so_tecnologia and not palavra:
        paginas += [p for p in PAGINAS if "/promocoes/" in p] + [
            "https://www.promobit.com.br/promocoes/eletronicos/",
            "https://www.promobit.com.br/promocoes/celulares/"]
    for url in paginas:
        for o in _ler_pagina(url):
            ident = f"amz:{o.get('offerId')}"
            titulo = str(o.get("offerTitle", ""))
            if ident in vistas or ident in achados or "amazon" not in str(o.get("storeName", "")).lower():
                continue
            if palavra and palavra.lower() not in titulo.lower():
                continue
            if not palavra and so_tecnologia and not (
                    RE_TECNOLOGIA.search(titulo) or o.get("categorySlug") in ("informatica", "games", "eletronicos", "celulares")):
                continue
            desconto = float(o.get("offerDiscontPercentage") or 0)
            if desconto < AMZ_DESCONTO_MINIMO or not o.get("offerPrice") or str(o.get("offerStatusName", "APPROVED")) != "APPROVED":
                continue
            try:
                publicada = datetime.strptime(str(o.get("offerPublished"))[:19], "%Y-%m-%dT%H:%M:%S")
                if publicada.replace(tzinfo=FUSO) < limite:
                    continue
            except ValueError:
                pass
            o["_id"] = ident
            o["_nota"] = desconto + min(int(o.get("offerLikes") or 0), 60) / 2
            achados[ident] = o
    escolhidos = sorted(achados.values(), key=lambda o: -o["_nota"])[:quantas]
    if escolhidos and supabase.ativo():
        lista = (_vistas() + [o["_id"] for o in escolhidos])[-400:]
        supabase.gravar_config(CHAVE_VISTAS, json.dumps(lista))
    return escolhidos


def mensagem_amazon(ofertas: list[dict]) -> str:
    if not ofertas:
        return ("📦 Amazon: não achei promoções novas de tecnologia com bom desconto agora.\n"
                "Tente /ofertas_amazon com uma palavra (ex.: /ofertas_amazon ssd) ou /ofertas_amazon tudo.")
    tag = config.AMAZON_TAG or ""
    linhas = ["📦 Amazon — promoções para o Drop Certo", ""]
    for i, o in enumerate(ofertas, 1):
        titulo = str(o.get("offerTitle", ""))[:90]
        preco = formatar_preco(float(o["offerPrice"]))
        antes = f" (antes {formatar_preco(float(o['offerOldPrice']))})" if o.get("offerOldPrice") else ""
        busca = f"https://www.amazon.com.br/s?k={quote_plus(' '.join(titulo.split()[:8]))}" + (f"&tag={tag}" if tag else "")
        linhas += [f"{i}. 🔥 -{round(float(o.get('offerDiscontPercentage', 0)))}% · {titulo}",
                   f"💰 {preco}{antes}", f"🔎 {busca}", ""]
    linhas += ["👉 Como postar:",
               "1. Toque no 🔎 (abre a busca da Amazon já com a sua tag) e abra o produto;",
               "2. Tire um print da página (nome e preço aparecendo) e copie o link do produto;",
               "3. Coloque print + link no quadro: https://certodrop.netlify.app/quadro.html",
               "   (ou mande o print com o link na legenda aqui).",
               f"🔧 Pode copiar o link direto do navegador/app: o robô coloca a sua tag ({tag}) sozinho.",
               "ℹ️ Preços vistos agora: confira na Amazon antes de postar."]
    return "\n".join(linhas)


def sugerir_amazon(palavra: str = "") -> str:
    tudo = palavra.lower() in ("tudo", "todas", "todos")
    return mensagem_amazon(buscar_amazon("" if tudo else palavra, so_tecnologia=not tudo))


def _proxima_hora(agora: datetime) -> datetime:
    alvo = agora.replace(hour=HORA, minute=0, second=0, microsecond=0)
    return alvo if alvo > agora else alvo + timedelta(days=1)


def sugerir_se_for_hora(enviar) -> bool:
    if not (supabase.ativo() and config.ADMIN_CHAT_ID and config.SUGERIR_OFERTAS):
        return False
    agora = datetime.now(FUSO)
    valor = str((supabase.ler_config(CHAVE_PROXIMA) or {}).get("valor", ""))
    if valor.isdigit() and agora.timestamp() < int(valor):
        return False
    supabase.gravar_config(CHAVE_PROXIMA, str(int(_proxima_hora(agora).timestamp())))
    if not valor.isdigit():
        return False                    # primeira vez: só marca o horário
    enviar(sugerir())
    extra = sugerir_shopee()
    if extra:
        enviar(extra)
    return True

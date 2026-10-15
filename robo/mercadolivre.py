"""Leitura oficial de produtos do Mercado Livre pela API (DevCenter).

O site do Mercado Livre às vezes bloqueia o robô (servidores do GitHub), e aí
o preço não vinha. Com a API oficial, nome, preço, preço "de" e fotos vêm
direto do Mercado Livre.

Como liga (uma vez só):
  1. Crie a aplicação no DevCenter com o URI de redirecionamento
     https://certodrop.netlify.app/ml.html
  2. Coloque no GitHub os secrets ML_CLIENT_ID e ML_CLIENT_SECRET
  3. Mande /ml no bot, toque no link, autorize — pronto.

O "refresh token" (acesso off-line) fica guardado na tabela config do Supabase
(chave ml_token) e o robô renova o acesso sozinho a cada 6 horas.

Importante: a API NÃO gera link de afiliado. Os posts continuam usando o link
meli.la que você mandou (é ele que paga a comissão).
"""
from __future__ import annotations

import json
import re
import time
from urllib.parse import urlencode, urljoin

import requests

from . import config, supabase

API = "https://api.mercadolibre.com"
AUTORIZAR = "https://auth.mercadolivre.com.br/authorization"
REDIRECT = "https://certodrop.netlify.app/ml.html"
CHAVE_TOKEN = "ml_token"
RE_ITEM = re.compile(r"MLB-?(\d{6,})", re.I)
RE_CATALOGO = re.compile(r"/p/(MLB\d{5,})", re.I)
CABECALHOS_WEB = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept-Language": "pt-BR"}


def configurado() -> bool:
    return bool(config.ML_CLIENT_ID and config.ML_CLIENT_SECRET)


def e_mercadolivre(link: str) -> bool:
    l = (link or "").lower()
    return any(s in l for s in ("meli.la", "mercadolivre", "mercadolibre", "mlb"))


# ---------------------------------------------------------------------------
# Autorização (OAuth) e token
# ---------------------------------------------------------------------------
def link_autorizacao() -> str:
    return f"{AUTORIZAR}?{urlencode({'response_type': 'code', 'client_id': config.ML_CLIENT_ID, 'redirect_uri': REDIRECT})}"


def _guardar(resposta: dict) -> dict:
    dados = {
        "access": resposta["access_token"],
        "refresh": resposta.get("refresh_token") or _lido().get("refresh", ""),
        "expira": int(time.time()) + int(resposta.get("expires_in", 21600)) - 300,
        "usuario": resposta.get("user_id"),
    }
    supabase.gravar_config(CHAVE_TOKEN, json.dumps(dados))
    return dados


def _lido() -> dict:
    try:
        return json.loads((supabase.ler_config(CHAVE_TOKEN) or {}).get("valor") or "{}")
    except ValueError:
        return {}


def _pedir_token(campos: dict) -> dict:
    r = requests.post(f"{API}/oauth/token", timeout=30, data={
        "client_id": config.ML_CLIENT_ID, "client_secret": config.ML_CLIENT_SECRET, **campos,
    }, headers={"accept": "application/json", "content-type": "application/x-www-form-urlencoded"})
    dados = r.json() if r.content else {}
    if r.status_code >= 300 or "access_token" not in dados:
        raise RuntimeError(f"Mercado Livre recusou ({r.status_code}): "
                           f"{dados.get('message') or dados.get('error') or r.text[:120]}")
    return dados


def trocar_codigo(codigo: str) -> dict:
    """Troca o código da autorização pelo token (feito uma vez, pelo /ml)."""
    if not configurado():
        raise RuntimeError("faltam os secrets ML_CLIENT_ID e ML_CLIENT_SECRET no GitHub")
    return _guardar(_pedir_token({"grant_type": "authorization_code", "code": codigo.strip(),
                                  "redirect_uri": REDIRECT}))


def token() -> str:
    """Token válido (renova sozinho quando vence). Vazio se ainda não autorizou."""
    if not (configurado() and supabase.ativo()):
        return ""
    dados = _lido()
    if not dados.get("refresh") and not dados.get("access"):
        return ""
    if dados.get("access") and time.time() < dados.get("expira", 0):
        return dados["access"]
    if not dados.get("refresh"):
        return ""
    return _guardar(_pedir_token({"grant_type": "refresh_token", "refresh_token": dados["refresh"]}))["access"]


def ativo() -> bool:
    return configurado() and bool(_lido().get("refresh") or _lido().get("access"))


def estado() -> str:
    if not configurado():
        return ("🟡 API do Mercado Livre: falta colocar ML_CLIENT_ID e ML_CLIENT_SECRET "
                "nos secrets do GitHub.")
    dados = _lido()
    if not dados.get("refresh"):
        return ("🔑 Falta autorizar a API do Mercado Livre (uma vez só).\n\n"
                f"1. Toque aqui e entre na SUA conta do Mercado Livre:\n{link_autorizacao()}\n\n"
                "2. Clique em \"Permitir\".\n"
                "3. Na página do Drop Certo que abrir, toque em \"Enviar para o robô\".")
    try:
        token()
        r = requests.get(f"{API}/users/me", headers={"Authorization": f"Bearer {token()}"}, timeout=20)
        apelido = r.json().get("nickname", "?") if r.ok else "?"
        return f"✅ API do Mercado Livre ligada (conta {apelido}). Links do ML são lidos pela API oficial."
    except Exception as erro:  # noqa: BLE001
        return f"⚠️ API do Mercado Livre com problema: {str(erro)[:150]}\nMande /ml para autorizar de novo."


# ---------------------------------------------------------------------------
# Leitura do produto
# ---------------------------------------------------------------------------
def _get(caminho: str, **params) -> dict:
    r = requests.get(f"{API}{caminho}", params=params or None, timeout=25,
                     headers={"Authorization": f"Bearer {token()}"})
    if r.status_code == 404:
        raise LookupError("produto não existe mais no Mercado Livre")
    if r.status_code >= 300:
        raise RuntimeError(f"API do ML {r.status_code}: {r.text[:120]}")
    return r.json()


def codigos_do_link(link: str) -> tuple[str | None, str | None]:
    """(item MLB…, catálogo MLB…). Segue o meli.la pelos redirecionamentos e, se precisar, a página."""
    url = link if "://" in link else f"https://{link}"
    vistos = [url]
    for _ in range(8):
        catalogo = RE_CATALOGO.search(url)
        item = RE_ITEM.search(url.split("/p/")[0]) if "/p/" in url else RE_ITEM.search(url)
        if catalogo or item:
            return (f"MLB{item.group(1)}" if item else None), (catalogo.group(1).upper() if catalogo else None)
        try:
            r = requests.get(url, allow_redirects=False, timeout=20, headers=CABECALHOS_WEB)
        except requests.RequestException:
            break
        proximo = r.headers.get("Location")
        if not proximo:
            # página do link de afiliado: procura o produto no HTML
            achado = RE_CATALOGO.search(r.text) or None
            if achado:
                return None, achado.group(1).upper()
            achado = re.search(r"(?:item_id|itemId)\W{1,4}(MLB-?\d{6,})", r.text) or RE_ITEM.search(r.text)
            if achado:
                return "MLB" + re.sub(r"\D", "", achado.group(1) if achado.lastindex else achado.group(0)), None
            break
        url = urljoin(url, proximo)
        vistos.append(url)
    return None, None


def _preco_venda(item_id: str) -> tuple[float | None, float | None]:
    """Preço com promoção (o /items às vezes traz só o preço cheio)."""
    try:
        d = _get(f"/items/{item_id}/sale_price", context="channel_marketplace")
        return d.get("amount"), d.get("regular_amount")
    except Exception:  # noqa: BLE001
        return None, None


def ler(link: str) -> dict:
    """{"nome", "preco", "preco_antigo", "imagens", "ativo"} ou {} se a API não estiver ligada."""
    if not ativo() or not e_mercadolivre(link):
        return {}
    item_id, catalogo = codigos_do_link(link)
    if not item_id and not catalogo:
        raise RuntimeError("não achei o código do produto (MLB…) no link")

    nome, imagens, preco, antigo, ativo_ = "", [], None, None, True
    if catalogo:
        p = _get(f"/products/{catalogo}")
        nome = p.get("name", "")
        imagens = [f.get("url") for f in p.get("pictures") or [] if f.get("url")]
        ganhador = p.get("buy_box_winner") or {}
        if not ganhador:
            # O ML quase não preenche mais o buy_box_winner: o 1º vendedor da lista de
            # anúncios do catálogo é o que aparece na página (o "ganhador").
            try:
                lista = _get(f"/products/{catalogo}/items").get("results") or []
            except LookupError:
                lista = []
            ganhador = lista[0] if lista else {}
        preco, antigo = ganhador.get("price"), ganhador.get("original_price")
        item_id = item_id or ganhador.get("item_id")
        ativo_ = p.get("status", "active") == "active" and bool(ganhador)
    if item_id:
        try:
            it = _get(f"/items/{item_id}")
            nome = nome or it.get("title", "")
            imagens = imagens or [f.get("secure_url") or f.get("url") for f in it.get("pictures") or []]
            preco = preco or it.get("price")
            antigo = antigo or it.get("original_price")
            ativo_ = it.get("status") == "active" and (it.get("available_quantity") or 1) > 0
        except LookupError:
            ativo_ = False
        venda, cheio = _preco_venda(item_id)
        if venda:
            preco = venda
            if cheio and cheio > venda:
                antigo = cheio
    if antigo and preco and antigo <= preco:
        antigo = None
    return {"nome": nome, "preco": preco, "preco_antigo": antigo,
            "imagens": [i for i in imagens if i][:4], "ativo": ativo_}

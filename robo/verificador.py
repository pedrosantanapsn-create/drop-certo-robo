"""Conferência diária das ofertas do site.

Uma vez por dia (6h, horário de Brasília) o robô abre o link de cada produto
ativo do site e:
  • atualiza o preço quando a loja mudou o valor;
  • tira do ar (ativo = falso, sem apagar) a oferta que acabou ou esgotou.

Para não tirar nada por engano, uma oferta só sai do site se aparecer como
indisponível em DUAS conferências seguidas. Quando a loja bloqueia o robô
(Amazon), a oferta fica como está. A Shopee é conferida pela API oficial de
afiliados (preço, desconto e se o produto ainda existe).

Mostrar preço errado pode ser considerado publicidade enganosa (CDC, art. 37),
por isso o "de R$ X" também é apagado quando deixa de ser verdade.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

from . import config, mercadolivre, shopee, supabase
from .produto import (CABECALHOS, LojaBloqueou, Produto, _extrair, _json_ld_produto,
                      _link_de_produto_na_pagina, formatar_preco, titulo_generico)
from .fila import FUSO

CHAVE_PROXIMA = "verificacao_proxima"
CHAVE_SUSPEITOS = "verificacao_suspeitos"
HORA = 6
MAX_POR_RODADA = 120

SINAIS_FIM = (
    "publicação pausada", "publicação finalizada", "anúncio pausado", "anúncio finalizado",
    "esta publicação está pausada", "este produto não está disponível",
    "produto indisponível", "atualmente indisponível", "não disponível no momento",
    "currently unavailable", "este anúncio não existe",
)


def _proxima_hora(agora: datetime) -> datetime:
    alvo = agora.replace(hour=HORA, minute=0, second=0, microsecond=0)
    return alvo if alvo > agora else alvo + timedelta(days=1)


# ---------------------------------------------------------------------------
# Leitura de uma oferta
# ---------------------------------------------------------------------------
def _situacao_shopee(link: str) -> tuple[str, Produto]:
    """Shopee pela API oficial de afiliados (a página bloqueia robôs)."""
    produto = Produto(link=link)
    try:
        dados = shopee.ler(link)
    except RuntimeError as erro:
        # Produto sumiu da Shopee/do programa de afiliados: conta como "acabou"
        # (só sai do site se repetir na conferência do dia seguinte).
        return ("fim" if "não devolveu" in str(erro) else "incerto"), produto
    except Exception:  # noqa: BLE001 — rede, timeout etc.
        return "incerto", produto
    if not dados.get("preco"):
        return "incerto", produto
    produto.nome = str(dados.get("nome") or "")
    produto.preco = dados["preco"]
    produto.preco_antigo = dados.get("preco_antigo")
    return "ok", produto


def _situacao_ml(link: str) -> tuple[str, Produto] | None:
    """Mercado Livre pela API oficial. None = não deu, tenta pela página."""
    produto = Produto(link=link)
    try:
        dados = mercadolivre.ler(link)
    except LookupError:
        return "fim", produto
    except Exception:  # noqa: BLE001
        return None
    if dados.get("ativo") is False:
        return "fim", produto
    if not dados.get("preco"):
        return None
    produto.nome = str(dados.get("nome") or "")
    produto.preco = dados["preco"]
    produto.preco_antigo = dados.get("preco_antigo")
    return "ok", produto


def situacao(link: str) -> tuple[str, Produto]:
    """Devolve ("ok" | "fim" | "incerto", produto lido)."""
    if shopee.ativo() and shopee.e_shopee(link):
        return _situacao_shopee(link)
    if mercadolivre.e_mercadolivre(link) and mercadolivre.ativo():
        resultado = _situacao_ml(link)
        if resultado:
            return resultado
    produto = Produto(link=link)
    sessao = requests.Session()
    sessao.headers.update(CABECALHOS)
    try:
        resp = sessao.get(link, timeout=25, allow_redirects=True)
        if resp.status_code in (404, 410):
            return "fim", produto
        if resp.status_code >= 400:
            return "incerto", produto
        html = resp.text
        _extrair(html, produto)
        if produto.preco is None:
            outro = _link_de_produto_na_pagina(BeautifulSoup(html, "html.parser"))
            if outro:
                resp = sessao.get(outro, timeout=25)
                if resp.status_code in (404, 410):
                    return "fim", produto
                html = resp.text
                _extrair(html, produto)
    except (LojaBloqueou, requests.RequestException):
        return "incerto", produto

    if titulo_generico(produto.nome):
        return "incerto", produto       # caiu na vitrine da loja: não dá para saber

    sopa = BeautifulSoup(html, "html.parser")
    oferta = _json_ld_produto(sopa).get("offers") or {}
    if isinstance(oferta, list):
        oferta = oferta[0] if oferta else {}
    disponibilidade = str(oferta.get("availability", "")) if isinstance(oferta, dict) else ""
    if any(s in disponibilidade for s in ("OutOfStock", "Discontinued", "SoldOut")):
        return "fim", produto
    texto = sopa.get_text(" ", strip=True).lower()[:60000]
    if any(s in texto for s in SINAIS_FIM):
        return "fim", produto
    return ("ok" if produto.preco else "incerto"), produto


# ---------------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------------
def _ativos() -> list[dict]:
    colunas = ",".join(c for c in ("id", config.COL_NOME, config.COL_PRECO,
                                   config.COL_PRECO_ANTIGO, config.COL_LINK) if c)
    r = requests.get(
        f"{config.SUPABASE_URL}/rest/v1/{config.SUPABASE_TABELA}",
        headers=supabase._cabecalhos(),
        params={"select": colunas, "ativo": "eq.true", "order": "id.asc"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def _alterar(ident, campos: dict) -> None:
    r = requests.patch(
        f"{config.SUPABASE_URL}/rest/v1/{config.SUPABASE_TABELA}",
        headers=supabase._cabecalhos({"Content-Type": "application/json", "Prefer": "return=minimal"}),
        params={"id": f"eq.{ident}"},
        json=campos,
        timeout=30,
    )
    if r.status_code >= 300:
        raise RuntimeError(f"Supabase {r.status_code}: {r.text[:200]}")


def _suspeitos() -> dict:
    try:
        return json.loads((supabase.ler_config(CHAVE_SUSPEITOS) or {}).get("valor") or "{}")
    except ValueError:
        return {}


# ---------------------------------------------------------------------------
# Conferência completa
# ---------------------------------------------------------------------------
def conferir() -> str:
    """Confere todas as ofertas ativas e devolve um resumo para o Telegram."""
    produtos = _ativos()[:MAX_POR_RODADA]
    suspeitos_antes = _suspeitos()
    suspeitos: dict = {}
    precos, tirados, incertos, ok = [], [], 0, 0

    for p in produtos:
        ident = str(p.get("id"))
        nome = str(p.get(config.COL_NOME) or "")[:60]
        estado, lido = situacao(str(p.get(config.COL_LINK) or ""))

        if estado == "fim":
            if ident in suspeitos_antes:
                _alterar(ident, {"ativo": False})
                tirados.append(nome)
            else:
                suspeitos[ident] = 1      # confirma na próxima conferência
            continue
        if estado == "incerto":
            incertos += 1
            if ident in suspeitos_antes:
                suspeitos[ident] = 1      # mantém a suspeita, sem tirar
            continue

        ok += 1
        antigo_site = p.get(config.COL_PRECO)
        novo = round(lido.preco, 2)
        campos: dict = {}
        if antigo_site is None or abs(float(antigo_site) - novo) >= max(0.10, float(antigo_site or 0) * 0.005):
            campos[config.COL_PRECO] = novo
        if config.COL_PRECO_ANTIGO:
            de_site = p.get(config.COL_PRECO_ANTIGO)
            de_novo = round(lido.preco_antigo, 2) if lido.preco_antigo and lido.preco_antigo > novo else None
            if de_novo and de_novo != de_site:
                campos[config.COL_PRECO_ANTIGO] = de_novo
            elif not de_novo and de_site is not None and float(de_site) <= novo:
                campos[config.COL_PRECO_ANTIGO] = None   # o "de" deixou de ser verdade
        if campos:
            _alterar(ident, campos)
            if config.COL_PRECO in campos:
                precos.append(f"{nome}: {formatar_preco(float(antigo_site)) if antigo_site else '?'} → "
                              f"{formatar_preco(novo)}")
        time.sleep(1)

    supabase.gravar_config(CHAVE_SUSPEITOS, json.dumps(suspeitos))

    linhas = [f"🔎 Conferência do site — {len(produtos)} oferta(s)",
              f"✅ Conferidas: {ok}   ❔ Sem resposta da loja: {incertos}"]
    if precos:
        linhas += ["", f"💲 Preço atualizado ({len(precos)}):", *[f"• {x}" for x in precos[:15]]]
    if tirados:
        linhas += ["", f"🚫 Tiradas do site — acabaram/esgotaram ({len(tirados)}):",
                   *[f"• {x}" for x in tirados[:15]],
                   "(não foram apagadas: dá para reativar no admin)"]
    if suspeitos:
        linhas += ["", f"⏳ {len(suspeitos)} oferta(s) pareceram esgotadas — confiro de novo amanhã antes de tirar."]
    return "\n".join(linhas)


def conferir_se_for_hora(enviar) -> bool:
    """Roda a conferência uma vez por dia e só avisa quando algo mudou."""
    if not (supabase.ativo() and config.ADMIN_CHAT_ID):
        return False
    agora = datetime.now(FUSO)
    valor = str((supabase.ler_config(CHAVE_PROXIMA) or {}).get("valor", ""))
    if valor.isdigit() and agora.timestamp() < int(valor):
        return False
    supabase.gravar_config(CHAVE_PROXIMA, str(int(_proxima_hora(agora).timestamp())))
    if not valor.isdigit():
        return False                       # primeira vez: só marca o horário
    resumo = conferir()
    if "Preço atualizado" in resumo or "Tiradas do site" in resumo:
        enviar(resumo)
    return True

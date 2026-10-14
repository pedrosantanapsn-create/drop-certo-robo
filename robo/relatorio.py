"""Relatório do Drop Certo: o que foi postado e o que o público clicou.

Guarda no Supabase (tabela "config"):
  historico          -> últimos posts feitos pelo robô (JSON)
  relatorio_proximo  -> horário (segundos desde 1970) do próximo relatório automático

Os cliques vêm da tabela "cliques", que o site preenche quando alguém
toca em "Ver na loja". Se a tabela ainda não existir, o relatório sai só
com os posts.

O relatório automático chega toda segunda-feira às 9h (horário de Brasília).
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

from . import config, fila, supabase

FUSO = ZoneInfo("America/Sao_Paulo")
CHAVE_HISTORICO = "historico"
CHAVE_PROXIMO = "relatorio_proximo"
MAX_HISTORICO = 400
DIA_DO_RELATORIO = 0      # 0 = segunda-feira
HORA_DO_RELATORIO = 9

LOJAS = [
    (("meli.la", "mercadolivre", "mercadolibre"), "Mercado Livre"),
    (("amazon.", "amzn."), "Amazon"),
    (("shopee", "shp.ee"), "Shopee"),
    (("magazineluiza", "magalu"), "Magalu"),
    (("aliexpress", "a.aliexpress"), "AliExpress"),
    (("kabum",), "KaBuM!"),
]


def loja(link: str) -> str:
    dominio = urlparse(link if "://" in link else f"https://{link}").netloc.lower()
    for pedacos, nome in LOJAS:
        if any(p in dominio for p in pedacos):
            return nome
    return dominio.removeprefix("www.") or "outra loja"


# ---------------------------------------------------------------------------
# Histórico de posts
# ---------------------------------------------------------------------------
def _historico() -> list[dict]:
    linha = supabase.ler_config(CHAVE_HISTORICO)
    try:
        dados = json.loads((linha or {}).get("valor") or "[]")
        return dados if isinstance(dados, list) else []
    except ValueError:
        return []


def postados_hoje(rede: str) -> int:
    """Quantos posts saíram hoje (horário de Brasília) numa rede ("tiktok", "instagram"…)."""
    inicio = datetime.now(FUSO).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    return sum(1 for p in _historico() if p.get("t", 0) >= inicio and p.get(rede))


def registrar_post(nome: str, preco: float | None, link: str, status: list[str]) -> None:
    """Anota o post no histórico (chamado no fim de cada oferta processada)."""
    if not supabase.ativo():
        return
    def deu_certo(rede: str) -> bool:
        return any(s.startswith(f"• {rede}") and "✅" in s for s in status)

    item = {
        "t": int(datetime.now(timezone.utc).timestamp()),
        "nome": nome[:120],
        "preco": preco,
        "link": link,
        "loja": loja(link),
        "canal": deu_certo("Canal"),
        "instagram": deu_certo("Instagram"),
        "tiktok": deu_certo("TikTok"),
        "site": deu_certo("Site"),
    }
    lista = (_historico() + [item])[-MAX_HISTORICO:]
    supabase.gravar_config(CHAVE_HISTORICO, json.dumps(lista, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Cliques do site
# ---------------------------------------------------------------------------
def _cliques(desde: datetime) -> list[dict] | None:
    """Cliques do site desde a data. None = a tabela "cliques" ainda não existe."""
    r = requests.get(
        f"{config.SUPABASE_URL}/rest/v1/cliques",
        headers=supabase._cabecalhos(),
        params={"select": "link,nome,loja,criado_em", "criado_em": f"gte.{desde.isoformat()}",
                "loja": "neq.teste",
                "order": "criado_em.desc", "limit": 5000},
        timeout=30,
    )
    if r.status_code >= 300:
        return None
    return r.json()


# ---------------------------------------------------------------------------
# Montagem do texto
# ---------------------------------------------------------------------------
def montar(dias: int = 7) -> str:
    agora = datetime.now(FUSO)
    desde = agora - timedelta(days=dias)
    posts = [p for p in _historico() if p.get("t", 0) >= desde.timestamp()]
    cliques = _cliques(desde)

    linhas = [f"📊 Relatório Drop Certo — últimos {dias} dias",
              f"{desde.strftime('%d/%m')} a {agora.strftime('%d/%m/%Y')}", ""]

    # Posts
    linhas.append(f"📦 Ofertas postadas: {len(posts)}")
    if posts:
        for rede, nome in (("canal", "Canal"), ("instagram", "Instagram"), ("tiktok", "TikTok"), ("site", "Site")):
            linhas.append(f"   • {nome}: {sum(1 for p in posts if p.get(rede))}")
        por_loja = Counter(p.get("loja", "?") for p in posts)
        linhas.append("   • Por loja: " + ", ".join(f"{l} {n}" for l, n in por_loja.most_common()))
        falhas = [p for p in posts if not (p.get("instagram") and p.get("tiktok"))]
        if falhas:
            linhas.append(f"   ⚠️ {len(falhas)} post(s) não saíram em alguma rede — confira os resumos no chat")
    linhas.append("")

    # Cliques
    if cliques is None:
        linhas.append("🖱️ Cliques no site: ainda não ligado (falta criar a tabela \"cliques\" no Supabase)")
    else:
        linhas.append(f"🖱️ Cliques no site: {len(cliques)}")
        if cliques:
            por_produto = Counter((c.get("nome") or c.get("link") or "?")[:60] for c in cliques)
            linhas.append("   🏆 Mais clicados:")
            for i, (nome, n) in enumerate(por_produto.most_common(5), 1):
                linhas.append(f"   {i}. {nome} — {n} clique(s)")
            por_loja = Counter(c.get("loja") or loja(c.get("link", "")) for c in cliques)
            linhas.append("   • Por loja: " + ", ".join(f"{l} {n}" for l, n in por_loja.most_common()))
            if posts:
                linhas.append(f"   • Média: {len(cliques) / len(posts):.1f} clique(s) por oferta postada".replace(".", ",", 1))
    linhas.append("")

    # Fila
    pendentes = len(fila.itens())
    linhas.append(f"🗓️ Na fila agora: {pendentes} oferta(s)" if pendentes
                  else "🗓️ Fila vazia — mande links para a semana!")
    linhas.append("")
    linhas.append("ℹ️ Vendas e comissões aparecem só no painel de afiliado de cada loja.")
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Agendamento (toda segunda às 9h)
# ---------------------------------------------------------------------------
def _proxima_segunda(agora: datetime) -> datetime:
    dias = (DIA_DO_RELATORIO - agora.weekday()) % 7
    alvo = (agora + timedelta(days=dias)).replace(hour=HORA_DO_RELATORIO, minute=0, second=0, microsecond=0)
    return alvo if alvo > agora else alvo + timedelta(days=7)


def enviar_se_for_hora(enviar) -> bool:
    """Manda o relatório quando chega a hora e marca o próximo.

    `enviar` é a função que manda o texto para você no Telegram.
    """
    if not (supabase.ativo() and config.ADMIN_CHAT_ID):
        return False
    agora = datetime.now(FUSO)
    linha = supabase.ler_config(CHAVE_PROXIMO)
    valor = str((linha or {}).get("valor", ""))
    if not valor.isdigit():
        # Primeira vez: só marca a próxima segunda (não manda nada agora)
        supabase.gravar_config(CHAVE_PROXIMO, str(int(_proxima_segunda(agora).timestamp())))
        return False
    if agora.timestamp() < int(valor):
        return False
    supabase.gravar_config(CHAVE_PROXIMO, str(int(_proxima_segunda(agora).timestamp())))
    enviar(montar(7))
    return True

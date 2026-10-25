""""Top do dia" no canal do Telegram, às 21h.

Junta as ofertas que entraram no site hoje e escolhe as 5 melhores: primeiro as
que mais tiveram cliques hoje (canal + site); empate ou sem cliques → maior
desconto. Cada item vai com o link rastreado (conta o clique e leva para a loja).
Desligar: variável TOP_DO_DIA = false no GitHub.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from html import escape

import requests

from . import config, rastreio, relatorio, supabase, telegram
from .fila import FUSO
from .produto import formatar_preco

CHAVE = "top_proximo"
HORA = 21
QUANTOS = 5
MINIMO = 3


def _proximo(agora: datetime) -> datetime:
    alvo = agora.replace(hour=HORA, minute=0, second=0, microsecond=0)
    return alvo if alvo > agora else alvo + timedelta(days=1)


def _de_hoje(inicio: datetime) -> list[dict]:
    colunas = ",".join(c for c in ("id", config.COL_NOME, config.COL_PRECO, config.COL_PRECO_ANTIGO,
                                   config.COL_LINK, "criado_em") if c)
    r = requests.get(f"{config.SUPABASE_URL}/rest/v1/{config.SUPABASE_TABELA}", headers=supabase._cabecalhos(),
                     params={"select": colunas, "ativo": "eq.true", "criado_em": f"gte.{inicio.isoformat()}"},
                     timeout=30)
    r.raise_for_status()
    return r.json()


def montar() -> str:
    agora = datetime.now(FUSO)
    inicio = agora.replace(hour=0, minute=0, second=0, microsecond=0)
    produtos = [p for p in _de_hoje(inicio) if p.get(config.COL_PRECO)]
    if len(produtos) < MINIMO:
        return ""
    cliques = Counter(str(c.get("produto_id") or "") for c in (relatorio._cliques(inicio) or []))
    cliques_link = Counter(str(c.get("link") or "") for c in (relatorio._cliques(inicio) or []))

    def desconto(p):
        de, por = p.get(config.COL_PRECO_ANTIGO), p.get(config.COL_PRECO)
        return round((1 - float(por) / float(de)) * 100) if de and por and float(de) > float(por) else 0

    def nota(p):
        return (cliques.get(str(p["id"]), 0) + cliques_link.get(str(p.get(config.COL_LINK)), 0), desconto(p))

    melhores = sorted(produtos, key=nota, reverse=True)[:QUANTOS]
    linhas = [f"🏆 <b>TOP {len(melhores)} DO DIA</b> — Drop Certo", "As ofertas que mais chamaram atenção hoje:", ""]
    medalhas = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    for i, p in enumerate(melhores):
        d = desconto(p)
        url = rastreio.link(str(p.get(config.COL_LINK)), p["id"], str(p.get(config.COL_NOME) or ""))
        linhas += [f"{medalhas[i]} {escape(str(p.get(config.COL_NOME) or '')[:70])}",
                   f"💰 {formatar_preco(float(p[config.COL_PRECO]))}" + (f"  (-{d}%)" if d else "")
                   + f"  ·  <a href=\"{escape(url)}\">ver oferta ➜</a>", ""]
    linhas += ["Preços vistos hoje — podem mudar.", escape(config.AVISO_LEGAL)]
    return "\n".join(linhas)


def postar_se_for_hora() -> bool:
    if not (config.TOP_DO_DIA and supabase.ativo() and config.CANAL_ID):
        return False
    agora = datetime.now(FUSO)
    valor = str((supabase.ler_config(CHAVE) or {}).get("valor", ""))
    if valor.isdigit() and agora.timestamp() < int(valor):
        return False
    supabase.gravar_config(CHAVE, str(int(_proximo(agora).timestamp())))
    if not valor.isdigit() or agora.hour >= 23:
        return False                 # primeira vez (só marca) ou já passou muito da hora
    texto = montar()
    if texto:
        telegram.enviar_html(config.CANAL_ID, texto)
    return bool(texto)

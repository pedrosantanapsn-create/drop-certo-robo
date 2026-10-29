"""Histórico de preços próprio do Drop Certo.

Cada produto que o robô vê pelas APIs (Shopee e Mercado Livre — sugestões, fila
automática, Top 5, conferência e posts) ganha 1 preço por dia, guardado no
Supabase (tabela config, chave "historico_precos"), por até 60 dias.

Com isso o robô sabe dizer:
  • "📉 Menor preço em 30 dias" (só quando tem pelo menos 7 dias de dados);
  • "⚠️ possível erro de preço" — preço 50% (ou mais) abaixo da mediana do produto.
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta

from . import supabase
from .fila import FUSO

CHAVE = "historico_precos"
DIAS_GUARDA = 60
MAX_PRODUTOS = 1500
DIAS_MINIMO = 7          # antes disso não afirma "menor preço"
FATOR_BUG = 0.5          # 50% abaixo da mediana

_dados: dict | None = None
_mudou = False


def _carregar() -> dict:
    global _dados
    if _dados is None:
        try:
            _dados = json.loads((supabase.ler_config(CHAVE) or {}).get("valor") or "{}") if supabase.ativo() else {}
        except ValueError:
            _dados = {}
    return _dados


def _hoje() -> str:
    return datetime.now(FUSO).strftime("%y%m%d")


def registrar(chave: str, preco: float | None) -> None:
    """Anota o preço de hoje (fica o menor do dia)."""
    global _mudou
    if not chave or not preco:
        return
    dados = _carregar()
    pontos = dados.setdefault(chave, {})
    hoje = _hoje()
    if hoje not in pontos or preco < pontos[hoje]:
        pontos[hoje] = round(float(preco), 2)
        _mudou = True


def salvar() -> None:
    """Grava no Supabase (uma vez por rodada), limpando o que é velho."""
    global _mudou
    if not (_mudou and supabase.ativo()):
        return
    dados = _carregar()
    limite = (datetime.now(FUSO) - timedelta(days=DIAS_GUARDA)).strftime("%y%m%d")
    for chave in list(dados):
        dados[chave] = {d: p for d, p in dados[chave].items() if d >= limite}
        if not dados[chave]:
            del dados[chave]
    if len(dados) > MAX_PRODUTOS:     # mantém os vistos mais recentemente
        ordem = sorted(dados, key=lambda c: max(dados[c]), reverse=True)
        for chave in ordem[MAX_PRODUTOS:]:
            del dados[chave]
    supabase.gravar_config(CHAVE, json.dumps(dados, separators=(",", ":")))
    _mudou = False


def analise(chave: str, preco: float | None) -> dict:
    """{'dias', 'minimo30', 'maximo30', 'mediana', 'menor30': bool, 'bug': bool}"""
    pontos = _carregar().get(chave or "", {})
    hoje = _hoje()
    limite = (datetime.now(FUSO) - timedelta(days=30)).strftime("%y%m%d")
    antes = [p for d, p in pontos.items() if limite <= d < hoje]
    if not preco or not antes:
        return {"dias": len(antes), "menor30": False, "bug": False}
    mediana = statistics.median(antes)
    return {
        "dias": len(antes), "minimo30": min(antes), "maximo30": max(antes), "mediana": mediana,
        "menor30": len(antes) >= DIAS_MINIMO and preco < min(antes) - 0.01,
        "bug": len(antes) >= 5 and preco <= mediana * FATOR_BUG,
    }


def chave_shopee(item_id) -> str:
    return f"shopee:{item_id}" if item_id else ""


def chave_ml(produto_id) -> str:
    return f"ml:{produto_id}" if produto_id else ""

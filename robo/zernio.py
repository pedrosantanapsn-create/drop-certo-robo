"""Conexão com o Zernio (zernio.com), que publica no TikTok e no Instagram.

Plano grátis: 2 contas conectadas, posts ilimitados.
Segredo necessário no GitHub: ZERNIO_API_KEY.
"""
from __future__ import annotations

import requests

from . import config

API = "https://zernio.com/api/v1"
_cache_contas: list[dict] | None = None


def ativo() -> bool:
    return bool(config.ZERNIO_API_KEY)


def cabecalhos() -> dict:
    return {"Authorization": f"Bearer {config.ZERNIO_API_KEY}", "Content-Type": "application/json"}


def erro(r: requests.Response) -> str:
    try:
        dados = r.json()
        return str(dados.get("error") or dados.get("message") or dados)[:200]
    except ValueError:
        return r.text[:200]


def contas() -> list[dict]:
    """Contas conectadas no Zernio (lidas uma vez por rodada)."""
    global _cache_contas
    if _cache_contas is None:
        r = requests.get(f"{API}/accounts", headers=cabecalhos(), timeout=30)
        if r.status_code >= 300:
            raise RuntimeError(f"Zernio {r.status_code}: {erro(r)}")
        _cache_contas = r.json().get("accounts", [])
    return _cache_contas


def conta(plataforma: str, preferida: str = "") -> dict | None:
    lista = [c for c in contas() if c.get("platform") == plataforma and c.get("isActive", True)]
    if preferida:
        lista = [c for c in lista if c.get("_id") == preferida] or lista
    return lista[0] if lista else None


def postar(corpo: dict) -> dict:
    r = requests.post(f"{API}/posts", headers=cabecalhos(), json=corpo, timeout=120)
    if r.status_code >= 300:
        raise RuntimeError(f"Zernio {r.status_code}: {erro(r)}")
    dados = r.json()
    return dados.get("post", dados)

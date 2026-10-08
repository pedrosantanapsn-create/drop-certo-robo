"""Envio do produto para o site (Supabase: banco + armazenamento de imagens)."""
from __future__ import annotations

import time
from pathlib import Path

import requests

from . import config
from .produto import Produto


def ativo() -> bool:
    return bool(config.SUPABASE_URL and config.SUPABASE_KEY)


def _cabecalhos(extra: dict | None = None) -> dict:
    h = {"apikey": config.SUPABASE_KEY, "Authorization": f"Bearer {config.SUPABASE_KEY}"}
    h.update(extra or {})
    return h


def enviar_imagem(arquivo: Path, nome: str) -> str:
    caminho = f"robo/{nome}"
    url = f"{config.SUPABASE_URL}/storage/v1/object/{config.SUPABASE_BUCKET}/{caminho}"
    r = requests.post(
        url,
        headers=_cabecalhos({"Content-Type": "image/jpeg", "x-upsert": "true"}),
        data=arquivo.read_bytes(),
        timeout=60,
    )
    if r.status_code >= 300:
        raise RuntimeError(f"Supabase Storage {r.status_code}: {r.text[:200]}")
    return f"{config.SUPABASE_URL}/storage/v1/object/public/{config.SUPABASE_BUCKET}/{caminho}"


def cadastrar_produto(p: Produto, imagem: Path, descricao: str) -> str:
    """Envia a foto principal e cria o produto na tabela do site.

    Usa a foto original do anúncio (não a arte), porque o site já mostra
    nome e preço nos cards.
    """
    url_imagem = enviar_imagem(imagem, f"{int(time.time())}.jpg")
    linha = {
        config.COL_NOME: p.nome,
        config.COL_PRECO: p.preco,
        config.COL_IMAGEM: url_imagem,
        config.COL_LINK: p.link,
    }
    if config.COL_DESCRICAO:
        linha[config.COL_DESCRICAO] = descricao
    r = requests.post(
        f"{config.SUPABASE_URL}/rest/v1/{config.SUPABASE_TABELA}",
        headers=_cabecalhos({"Content-Type": "application/json", "Prefer": "return=minimal"}),
        json=linha,
        timeout=30,
    )
    if r.status_code >= 300:
        raise RuntimeError(f"Supabase {r.status_code}: {r.text[:300]}")
    return url_imagem


def listar_colunas() -> str:
    """Comando /colunas: mostra os nomes das colunas da tabela do site."""
    r = requests.get(
        f"{config.SUPABASE_URL}/rest/v1/{config.SUPABASE_TABELA}",
        headers=_cabecalhos(),
        params={"select": "*", "limit": 1},
        timeout=30,
    )
    if r.status_code >= 300:
        return f"Erro {r.status_code}: {r.text[:300]}"
    linhas = r.json()
    if not linhas:
        return f"A tabela '{config.SUPABASE_TABELA}' está vazia — cadastre 1 produto pelo admin e tente de novo."
    return f"Colunas da tabela '{config.SUPABASE_TABELA}':\n" + "\n".join(f"• {c}" for c in linhas[0])

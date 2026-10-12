"""Publicação automática no TikTok pelo Zernio (plano grátis: 2 contas).

O Zernio é aprovado pelo TikTok para postar vídeos públicos. O robô:
  1. sobe o vídeo para o Supabase (endereço público, o mesmo do Instagram);
  2. pede ao Zernio para publicar no TikTok, já com o aviso de conteúdo
     comercial (parceria/afiliado), como o TikTok e o CDC exigem.

Segredo necessário no GitHub: ZERNIO_API_KEY (Zernio → API Keys).
"""
from __future__ import annotations

from pathlib import Path

import requests

from . import config, supabase

API = "https://zernio.com/api/v1"


def ativo() -> bool:
    return bool(config.AUTO_POSTAR_TIKTOK and config.ZERNIO_API_KEY and supabase.ativo())


def _cabecalhos() -> dict:
    return {"Authorization": f"Bearer {config.ZERNIO_API_KEY}", "Content-Type": "application/json"}


def _erro(r: requests.Response) -> str:
    try:
        dados = r.json()
        return str(dados.get("error") or dados.get("message") or dados)[:200]
    except ValueError:
        return r.text[:200]


def conta() -> dict:
    """Acha a conta do TikTok conectada no Zernio."""
    r = requests.get(f"{API}/accounts", headers=_cabecalhos(), timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"Zernio {r.status_code}: {_erro(r)}")
    contas = r.json().get("accounts", [])
    tiktoks = [c for c in contas if c.get("platform") == "tiktok" and c.get("isActive", True)]
    if config.ZERNIO_TIKTOK_ACCOUNT:
        tiktoks = [c for c in tiktoks if c.get("_id") == config.ZERNIO_TIKTOK_ACCOUNT] or tiktoks
    if not tiktoks:
        raise RuntimeError("nenhuma conta do TikTok conectada no Zernio")
    return tiktoks[0]


def publicar(video: Path, legenda: str) -> str:
    """Publica o vídeo no TikTok. Devolve o id/status do post no Zernio."""
    alvo = conta()
    corpo = {
        "content": legenda[:2200],
        "mediaItems": [{"type": "video", "url": supabase.url_publica(video, "video/mp4")}],
        "platforms": [{"platform": "tiktok", "accountId": alvo["_id"]}],
        "tiktokSettings": {
            "privacy_level": "PUBLIC_TO_EVERYONE",
            "allow_comment": True,
            "allow_duet": True,
            "allow_stitch": True,
            "content_preview_confirmed": True,
            "express_consent_given": True,
            "commercialContentType": config.TIKTOK_AVISO_COMERCIAL,
        },
        "publishNow": True,
    }
    r = requests.post(f"{API}/posts", headers=_cabecalhos(), json=corpo, timeout=120)
    if r.status_code >= 300:
        raise RuntimeError(f"Zernio {r.status_code}: {_erro(r)}")
    dados = r.json()
    post = dados.get("post", dados)
    ident = post.get("_id") or post.get("id") or ""
    status = post.get("status") or ""
    return f"@{alvo.get('username', '')} {status} {ident}".strip()

"""Publicação automática no Instagram (API oficial da Meta, gratuita).

Usa a "Instagram API com login do Instagram" (graph.instagram.com):
  1. o robô envia o vídeo e a arte para o Supabase (endereço público);
  2. pede ao Instagram para criar o Reels a partir desse endereço;
  3. espera o Instagram processar o vídeo e publica.

O token de acesso dura 60 dias. Ele fica guardado na tabela "config" do
Supabase e o robô o renova sozinho a cada poucos dias, então não expira
enquanto o robô estiver em uso.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from . import config, supabase

API = "https://graph.instagram.com"
VERSAO = "v25.0"
CHAVE_TOKEN = "instagram_token"
RENOVAR_A_CADA = timedelta(days=5)


# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------
def _token() -> str | None:
    """Token salvo no Supabase; se não houver, usa o segredo IG_TOKEN do GitHub."""
    salvo = supabase.ler_config(CHAVE_TOKEN) if supabase.ativo() else None
    if salvo and salvo.get("valor"):
        return _renovar_se_preciso(salvo["valor"], salvo.get("atualizado_em"))
    if config.IG_TOKEN:
        if supabase.ativo():
            supabase.gravar_config(CHAVE_TOKEN, config.IG_TOKEN)
        return config.IG_TOKEN
    return None


def _renovar_se_preciso(token: str, atualizado_em: str | None) -> str:
    try:
        quando = datetime.fromisoformat((atualizado_em or "").replace("Z", "+00:00"))
    except ValueError:
        quando = datetime.min.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - quando < RENOVAR_A_CADA:
        return token
    r = requests.get(
        f"{API}/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": token},
        timeout=30,
    )
    if r.ok and r.json().get("access_token"):
        novo = r.json()["access_token"]
        supabase.gravar_config(CHAVE_TOKEN, novo)
        return novo
    return token  # se falhar, segue com o atual (ainda válido por até 60 dias)


def ativo() -> bool:
    if not config.AUTO_POSTAR_INSTAGRAM:
        return False
    if config.IG_TOKEN:
        return True
    return supabase.ativo() and bool(supabase.ler_config(CHAVE_TOKEN))


# ---------------------------------------------------------------------------
# Chamadas à API
# ---------------------------------------------------------------------------
def _chamar(metodo: str, caminho: str, token: str, **params) -> dict:
    url = f"{API}/{VERSAO}/{caminho}"
    params["access_token"] = token
    r = requests.request(metodo, url, params=params if metodo == "GET" else None,
                         data=params if metodo == "POST" else None, timeout=60)
    dados = r.json() if r.content else {}
    if not r.ok or "error" in dados:
        erro = dados.get("error", {})
        raise RuntimeError(f"Instagram: {erro.get('message', r.text[:200])}")
    return dados


def _esperar_processar(container_id: str, token: str, limite_s: int = 300) -> None:
    inicio = time.time()
    while time.time() - inicio < limite_s:
        status = _chamar("GET", container_id, token, fields="status_code,status").get("status_code")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram recusou o vídeo (status {status})")
        time.sleep(8)
    raise RuntimeError("Instagram demorou demais para processar o vídeo")


def conta(token: str | None = None) -> dict:
    token = token or _token()
    if not token:
        raise RuntimeError("Sem token do Instagram")
    return _chamar("GET", "me", token, fields="user_id,username")


# ---------------------------------------------------------------------------
# Publicação
# ---------------------------------------------------------------------------
def publicar_reels(video: Path, legenda: str, capa: Path | None = None) -> str:
    """Publica o vídeo como Reels (aparece também no feed). Retorna o link do post."""
    token = _token()
    if not token:
        raise RuntimeError("Instagram não configurado (falta o token)")
    eu = conta(token)
    ig_id = eu["user_id"]

    carimbo = int(time.time())
    url_video = supabase.enviar_arquivo(video, f"posts/{carimbo}.mp4", "video/mp4")
    extras = {}
    if capa:
        extras["cover_url"] = supabase.enviar_arquivo(capa, f"posts/{carimbo}_capa.jpg", "image/jpeg")

    container = _chamar("POST", f"{ig_id}/media", token, media_type="REELS",
                        video_url=url_video, caption=legenda[:2200], share_to_feed="true", **extras)
    _esperar_processar(container["id"], token)
    post = _chamar("POST", f"{ig_id}/media_publish", token, creation_id=container["id"])
    try:
        info = _chamar("GET", post["id"], token, fields="permalink")
        return info.get("permalink", f"https://www.instagram.com/{eu.get('username', '')}/")
    except RuntimeError:
        return f"https://www.instagram.com/{eu.get('username', '')}/"

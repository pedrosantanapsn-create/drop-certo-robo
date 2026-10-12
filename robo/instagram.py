"""Publicação automática no Instagram.

Três caminhos (o robô usa o primeiro que estiver configurado):
  0) Zernio (ZERNIO_API_KEY + Instagram conectado no Zernio): Reels e Story,
     sem limite de operações. Se o Zernio falhar, cai para o Make.
  A) Make.com (MAKE_WEBHOOK_URL): o robô manda o vídeo e a legenda para um
     cenário do Make, que publica o Reels pela conexão "Instagram for
     Business". Não exige conta de desenvolvedor na Meta.
  B) API oficial da Meta (IG_TOKEN), explicada abaixo.

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

from . import config, supabase, zernio

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
    if config.MAKE_WEBHOOK_URL or config.IG_TOKEN or _conta_zernio():
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


_motivo_zernio = ""


def _conta_zernio() -> dict | None:
    """Conta do Instagram conectada no Zernio (None se não houver)."""
    global _motivo_zernio
    if not zernio.ativo():
        _motivo_zernio = "sem ZERNIO_API_KEY"
        return None
    try:
        achada = zernio.conta("instagram", config.ZERNIO_INSTAGRAM_ACCOUNT)
        if not achada:
            vistas = ", ".join(f"{c.get('platform')}:{c.get('username')}"
                               f"{'' if c.get('isActive', True) else '(inativa)'}" for c in zernio.contas())
            _motivo_zernio = f"Instagram não encontrado no Zernio (contas vistas: {vistas or 'nenhuma'})"
        return achada
    except Exception as erro:  # noqa: BLE001
        _motivo_zernio = f"erro ao consultar o Zernio: {str(erro)[:150]}"
        return None


def diagnostico_zernio() -> str:
    _conta_zernio()
    return _motivo_zernio


def conta(token: str | None = None) -> dict:
    pelo_zernio = None if token else _conta_zernio()
    if pelo_zernio:
        return {"username": f"{pelo_zernio.get('username', '')} (via Zernio)"}
    if config.MAKE_WEBHOOK_URL and not (token or config.IG_TOKEN):
        return {"username": "certodrop (via Make.com)"}
    token = token or _token()
    if not token:
        raise RuntimeError("Sem token do Instagram")
    return _chamar("GET", "me", token, fields="user_id,username")


# ---------------------------------------------------------------------------
# Publicação
# ---------------------------------------------------------------------------
def _publicar_via_make(video: Path, legenda: str, capa: Path | None) -> str:
    carimbo = int(time.time())
    dados = {
        "video_url": supabase.url_publica(video, "video/mp4"),
        "legenda": legenda[:2200],
        "capa_url": supabase.url_publica(capa, "image/jpeg") if capa else "",
    }
    # O Make processa o vídeo e só responde quando o Reels foi publicado (até ~5 min)
    r = requests.post(config.MAKE_WEBHOOK_URL, json=dados, timeout=330)
    if r.status_code >= 300:
        raise RuntimeError(f"Make respondeu {r.status_code}: {r.text[:200]}")
    texto = r.text.strip()
    if texto.lower() == "accepted":
        return "enviado ao Make (o Reels sai em alguns minutos)"
    try:
        resposta = r.json()
        return resposta.get("permalink") or resposta.get("id") or texto[:120]
    except ValueError:
        return texto[:120] or "publicado"


def _publicar_via_zernio(alvo: dict, video: Path, legenda: str, capa: Path | None) -> str:
    dados: dict = {"shareToFeed": True}
    if capa:
        dados["instagramThumbnail"] = supabase.url_publica(capa, "image/jpeg")
    post = zernio.postar({
        "content": legenda[:2200],
        "mediaItems": [{"type": "video", "url": supabase.url_publica(video, "video/mp4")}],
        "platforms": [{"platform": "instagram", "accountId": alvo["_id"], "platformSpecificData": dados}],
        "publishNow": True,
    })
    return f"via Zernio {post.get('status', '')} {post.get('_id') or post.get('id') or ''}".strip()


def story_ativo() -> bool:
    return bool(config.AUTO_STORY_INSTAGRAM and config.AUTO_POSTAR_INSTAGRAM and _conta_zernio())


def publicar_story(midia: Path, tipo: str = "video") -> str:
    """Publica um Story (pelo Zernio). Story não tem legenda nem link clicável pela API."""
    alvo = _conta_zernio()
    if not alvo:
        raise RuntimeError("Instagram não está conectado no Zernio")
    mime = "video/mp4" if tipo == "video" else "image/jpeg"
    post = zernio.postar({
        "mediaItems": [{"type": tipo, "url": supabase.url_publica(midia, mime)}],
        "platforms": [{"platform": "instagram", "accountId": alvo["_id"],
                       "platformSpecificData": {"contentType": "story"}}],
        "publishNow": True,
    })
    return f"{post.get('status', '')} {post.get('_id') or post.get('id') or ''}".strip()


def publicar_reels(video: Path, legenda: str, capa: Path | None = None) -> str:
    """Publica o vídeo como Reels (aparece também no feed). Retorna o link do post."""
    alvo = _conta_zernio()
    if alvo:
        try:
            return _publicar_via_zernio(alvo, video, legenda, capa)
        except Exception as erro:  # noqa: BLE001
            if not config.MAKE_WEBHOOK_URL:
                raise
            return _publicar_via_make(video, legenda, capa) + f" (Zernio falhou: {str(erro)[:80]})"
    if config.MAKE_WEBHOOK_URL:
        return _publicar_via_make(video, legenda, capa)
    token = _token()
    if not token:
        raise RuntimeError("Instagram não configurado (falta o token)")
    eu = conta(token)
    ig_id = eu["user_id"]

    carimbo = int(time.time())
    url_video = supabase.url_publica(video, "video/mp4")
    extras = {}
    if capa:
        extras["cover_url"] = supabase.url_publica(capa, "image/jpeg")

    container = _chamar("POST", f"{ig_id}/media", token, media_type="REELS",
                        video_url=url_video, caption=legenda[:2200], share_to_feed="true", **extras)
    _esperar_processar(container["id"], token)
    post = _chamar("POST", f"{ig_id}/media_publish", token, creation_id=container["id"])
    try:
        info = _chamar("GET", post["id"], token, fields="permalink")
        return info.get("permalink", f"https://www.instagram.com/{eu.get('username', '')}/")
    except RuntimeError:
        return f"https://www.instagram.com/{eu.get('username', '')}/"

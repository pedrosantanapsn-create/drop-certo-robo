"""Comunicação com a API oficial e gratuita do Telegram."""
from __future__ import annotations

from pathlib import Path

import requests

from . import config

API = "https://api.telegram.org/bot{token}/{metodo}"


def _chamar(metodo: str, arquivos: dict | None = None, **dados):
    url = API.format(token=config.TELEGRAM_TOKEN, metodo=metodo)
    abertos = {}
    try:
        if arquivos:
            abertos = {campo: open(caminho, "rb") for campo, caminho in arquivos.items()}
        r = requests.post(url, data=dados, files=abertos or None, timeout=120)
    finally:
        for f in abertos.values():
            f.close()
    resposta = r.json()
    if not resposta.get("ok"):
        raise RuntimeError(f"Telegram ({metodo}): {resposta.get('description')}")
    return resposta["result"]


def buscar_mensagens(offset: int | None) -> list[dict]:
    params = {"timeout": 0, "allowed_updates": '["message"]'}
    if offset is not None:
        params["offset"] = offset
    return _chamar("getUpdates", **params)


def confirmar_leitura(ultimo_update_id: int) -> None:
    """Marca as mensagens como lidas no servidor do Telegram.

    Assim o robô não precisa guardar estado entre execuções.
    """
    _chamar("getUpdates", offset=ultimo_update_id + 1, timeout=0)


def enviar_texto(chat_id, texto: str) -> None:
    _chamar("sendMessage", chat_id=chat_id, text=texto[:4096], disable_web_page_preview="true")


def enviar_foto(chat_id, foto: Path, legenda: str = "") -> dict:
    return _chamar("sendPhoto", arquivos={"photo": foto}, chat_id=chat_id, caption=legenda[:1024])


def enviar_video(chat_id, video: Path, legenda: str = "", capa: Path | None = None) -> dict:
    arquivos = {"video": video}
    if capa:
        arquivos["thumbnail"] = capa
    return _chamar("sendVideo", arquivos=arquivos, chat_id=chat_id, caption=legenda[:1024],
                   supports_streaming="true", width=1080, height=1920)


def enviar_arquivo(chat_id, arquivo: Path, legenda: str = "") -> dict:
    return _chamar("sendDocument", arquivos={"document": arquivo}, chat_id=chat_id,
                   caption=legenda[:1024])


def baixar_foto_da_mensagem(mensagem: dict, destino: Path) -> Path | None:
    """Se você mandar uma foto junto com o link, ela vira a foto do post."""
    fotos = mensagem.get("photo") or []
    if not fotos:
        return None
    maior = max(fotos, key=lambda f: f.get("file_size", 0))
    info = _chamar("getFile", file_id=maior["file_id"])
    url = f"https://api.telegram.org/file/bot{config.TELEGRAM_TOKEN}/{info['file_path']}"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    destino.write_bytes(r.content)
    return destino

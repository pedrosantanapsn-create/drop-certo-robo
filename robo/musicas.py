"""Biblioteca de músicas de fundo (livres de direitos) para os vídeos.

Como usar: baixe músicas no pixabay.com/music (licença permite uso comercial,
sem crédito) — de preferência SEM o ícone de escudo (Content ID) — e mande o
arquivo de áudio para o bot com a legenda /musica. O robô converte, guarda no
Supabase (bucket "produtos", pasta musicas/) e passa a usar em rodízio,
baixinho por baixo da narração.

Comandos: /musicas (lista) · /tirar_musica N (tira da biblioteca, sem apagar o arquivo)
"""
from __future__ import annotations

import random
import re
import subprocess
import unicodedata
from pathlib import Path

import requests

from . import config, supabase, telegram

BUCKET = "produtos"
PASTA = "musicas/"
_cache: list[str] | None = None
musica_usada = ""


def _storage(caminho: str) -> str:
    return f"{config.SUPABASE_URL}/storage/v1/{caminho}"


def listar() -> list[str]:
    """Nomes dos arquivos da biblioteca (sem a pasta), em ordem."""
    global _cache
    if _cache is not None:
        return _cache
    if not supabase.ativo():
        return []
    r = requests.post(_storage(f"object/list/{BUCKET}"), timeout=30,
                      headers=supabase._cabecalhos({"Content-Type": "application/json"}),
                      json={"prefix": PASTA, "limit": 200, "sortBy": {"column": "name", "order": "asc"}})
    _cache = [o["name"] for o in (r.json() if r.ok else []) if str(o.get("name", "")).endswith(".mp3")]
    return _cache


def _nome_seguro(nome: str) -> str:
    nome = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    nome = re.sub(r"[^a-zA-Z0-9]+", "-", Path(nome).stem).strip("-").lower()[:50]
    return nome or "musica"


def adicionar(mensagem: dict) -> str:
    """Recebe o áudio mandado no Telegram, converte para MP3 e guarda na biblioteca."""
    arq = mensagem.get("audio") or mensagem.get("document") or mensagem.get("voice")
    if not arq:
        return "Mande o arquivo de ÁUDIO (mp3) com a legenda /musica."
    if int(arq.get("file_size") or 0) > 20 * 1024 * 1024:
        return "❌ Arquivo maior que 20 MB (limite do Telegram para robôs). Use uma música mais curta."
    mime = str(arq.get("mime_type") or "")
    if mensagem.get("document") and not mime.startswith("audio"):
        return "❌ Esse arquivo não é de áudio. Mande o mp3 da música."
    nome = _nome_seguro(arq.get("file_name") or arq.get("title") or "musica")
    pasta = Path(config.PASTA_SAIDA) / "musica_nova"
    pasta.mkdir(parents=True, exist_ok=True)
    bruto, final = pasta / "entrada", pasta / f"{nome}.mp3"
    try:
        telegram.baixar_arquivo(arq["file_id"], bruto)
        # até 3 min, volume padronizado (para nenhuma música "estourar" por cima da voz)
        r = subprocess.run(["ffmpeg", "-y", "-i", str(bruto), "-t", "180", "-vn", "-ac", "2", "-ar", "48000",
                            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-b:a", "160k", str(final)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return "❌ Não consegui ler esse áudio. Mande em mp3."
        supabase.enviar_arquivo(final, f"{PASTA}{nome}.mp3", "audio/mpeg")
    finally:
        for f in (bruto, final):
            f.unlink(missing_ok=True)
    global _cache
    _cache = None
    total = len(listar())
    return (f"🎵 Música \"{nome}\" guardada! Biblioteca: {total} música(s).\n"
            "Os próximos vídeos usam as músicas em rodízio, baixinho por baixo da narração.")


def resumo() -> str:
    lista = listar()
    if not lista:
        return ("🎵 Biblioteca de músicas vazia.\nBaixe músicas no pixabay.com/music (sem o ícone de escudo) "
                "e mande o arquivo para mim com a legenda /musica.")
    linhas = [f"🎵 Biblioteca: {len(lista)} música(s)", ""]
    linhas += [f"{i}. {n.removesuffix('.mp3')}" for i, n in enumerate(lista, 1)]
    linhas += ["", "Tirar uma: /tirar_musica 3"]
    return "\n".join(linhas)


def tirar(numero: int) -> str:
    """Move a música para musicas/fora/ (sai do rodízio; o arquivo continua guardado)."""
    lista = listar()
    if not 1 <= numero <= len(lista):
        return "Número inválido. Mande /musicas para ver a lista."
    nome = lista[numero - 1]
    r = requests.post(_storage("object/move"), timeout=30,
                      headers=supabase._cabecalhos({"Content-Type": "application/json"}),
                      json={"bucketId": BUCKET, "sourceKey": PASTA + nome, "destinationKey": f"{PASTA}fora/{nome}"})
    if not r.ok:
        return f"❌ Não consegui tirar: {r.text[:120]}"
    global _cache
    _cache = None
    return f"✅ \"{nome.removesuffix('.mp3')}\" saiu do rodízio (o arquivo continua guardado em musicas/fora)."


def sortear(destino: Path) -> Path | None:
    """Baixa uma música da biblioteca para o vídeo (ou None se a biblioteca estiver vazia)."""
    global musica_usada
    musica_usada = ""
    if not config.MUSICA_FUNDO:
        return None
    try:
        lista = listar()
        if not lista:
            return None
        nome = random.choice(lista)
        r = requests.get(_storage(f"object/public/{BUCKET}/{PASTA}{nome}"), timeout=60)
        r.raise_for_status()
        destino.write_bytes(r.content)
        musica_usada = nome.removesuffix(".mp3")
        return destino
    except Exception as erro:  # noqa: BLE001
        print(f"::warning::Música de fundo: {str(erro)[:120]}")
        return None

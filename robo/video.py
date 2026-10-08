"""Vídeo vertical (Reels / TikTok / Shorts) com FFmpeg + narração gratuita.

Monta 4 cenas (gancho, benefícios, preço, chamada), com zoom suave,
transições e narração em voz neural (edge-tts). Sem música, para evitar
problemas de direitos autorais — você pode pôr um áudio em alta ao
publicar no app.
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from . import arte, config
from .produto import Produto

FPS = 30
TRANSICAO = 0.35
PESOS_CENAS = (0.22, 0.33, 0.27, 0.18)
DURACAO_MINIMA = 12.0


def _rodar(cmd: list[str]) -> None:
    resultado = subprocess.run(cmd, capture_output=True, text=True)
    if resultado.returncode != 0:
        raise RuntimeError("FFmpeg falhou: " + resultado.stderr[-600:])


def duracao(arquivo: Path) -> float:
    saida = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(arquivo)],
        capture_output=True, text=True,
    ).stdout.strip()
    return float(saida or 0)


def narrar(texto: str, destino: Path) -> Path | None:
    """Gera a narração. Se não houver internet ou a voz falhar, devolve None."""
    try:
        import edge_tts

        async def _falar():
            await edge_tts.Communicate(texto, config.VOZ, rate="+8%").save(str(destino))

        asyncio.run(_falar())
        return destino if destino.exists() and destino.stat().st_size > 1000 else None
    except Exception:  # noqa: BLE001
        return None


def _clipe(quadro: Path, segundos: float, destino: Path, indice: int) -> Path:
    quadros = max(int(segundos * FPS), 1)
    # Alterna zoom de aproximação e de afastamento para dar ritmo
    if indice % 2 == 0:
        zoom = f"1+0.06*on/{quadros}"
    else:
        zoom = f"1.06-0.06*on/{quadros}"
    filtro = (
        "scale=2160:-1,"
        f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d=1:s=1080x1920:fps={FPS},format=yuv420p"
    )
    _rodar([
        "ffmpeg", "-y", "-loop", "1", "-framerate", str(FPS), "-t", f"{segundos:.3f}",
        "-i", str(quadro), "-vf", filtro, "-frames:v", str(quadros),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(destino),
    ])
    return destino


def gerar_video(p: Produto, t: dict, fotos: list[Path], pasta: Path) -> tuple[Path, bool]:
    """Retorna (caminho_do_video, tem_narracao)."""
    foto = lambda i: fotos[i % len(fotos)] if fotos else None  # noqa: E731
    quadros = [
        arte.cena_gancho(p, t, foto(0), pasta / "cena_1.png"),
        arte.cena_beneficios(p, t, foto(1), pasta / "cena_2.png"),
        arte.cena_preco(p, t, foto(0), pasta / "cena_3.png"),
        arte.cena_cta(p, t, foto(2), pasta / "cena_4.png"),
    ]

    audio = narrar(t["narracao"], pasta / "narracao.mp3")
    total = max(DURACAO_MINIMA, (duracao(audio) + 0.8) if audio else 0)
    duracoes = [total * peso for peso in PESOS_CENAS]

    clipes = []
    for i, (q, seg) in enumerate(zip(quadros, duracoes)):
        extra = TRANSICAO if i < len(quadros) - 1 else 0
        clipes.append(_clipe(q, seg + extra, pasta / f"clipe_{i}.mp4", i))

    entradas: list[str] = []
    for c in clipes:
        entradas += ["-i", str(c)]

    filtros, anterior, deslocamento = [], "[0:v]", 0.0
    transicoes = ["fade", "slideleft", "fade"]
    for i in range(1, len(clipes)):
        deslocamento += duracoes[i - 1]
        saida = f"[v{i}]"
        filtros.append(
            f"{anterior}[{i}:v]xfade=transition={transicoes[i - 1]}:"
            f"duration={TRANSICAO}:offset={deslocamento:.3f}{saida}"
        )
        anterior = saida

    destino = pasta / "video.mp4"
    cmd = ["ffmpeg", "-y", *entradas]
    if audio:
        cmd += ["-i", str(audio)]
        filtros.append(f"[{len(clipes)}:a]adelay=300|300,apad[a]")
    cmd += ["-filter_complex", ";".join(filtros), "-map", anterior]
    if audio:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "160k"]
    cmd += [
        "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-movflags", "+faststart", str(destino),
    ]
    _rodar(cmd)
    return destino, bool(audio)

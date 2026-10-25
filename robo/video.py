"""Vídeo vertical (Reels / TikTok / Shorts) com FFmpeg + narração gratuita.

Monta de 4 a 6 cenas (gancho, fotos do produto, benefícios, preço, chamada),
com zoom, transições, narração em voz neural (Kokoro) e LEGENDAS ANIMADAS
sincronizadas com a fala (a palavra da vez fica em destaque, estilo Reels).
Sem música, para evitar problemas de direitos autorais — você pode pôr um
áudio em alta ao publicar no app.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from . import arte, config
from .produto import Produto

FPS = 30
TRANSICAO = 0.30
ATRASO_VOZ = 0.30          # a narração começa 0,3 s depois do início
DURACAO_MINIMA = 12.0
PALAVRAS_POR_FRASE = 3     # quantas palavras aparecem juntas na legenda


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


# ---------------------------------------------------------------------------
# Narração + tempo de cada palavra
# ---------------------------------------------------------------------------
motivo_sem_voz = ""        # por que a narração falhou (aparece no resumo do Telegram)
voz_usada = ""


_kokoro = None


def _narrar_kokoro(texto: str, destino: Path) -> None:
    """Voz neural Kokoro, gerada no próprio robô (gratuita, sem bloqueio)."""
    global _kokoro
    import soundfile as sf
    from kokoro_onnx import Kokoro

    modelo = config.PASTA_MODELOS / "kokoro-v1.0.onnx"
    vozes = config.PASTA_MODELOS / "voices-v1.0.bin"
    if not (modelo.exists() and vozes.exists()):
        raise RuntimeError("modelo Kokoro não encontrado na pasta modelos/")
    if _kokoro is None:
        _kokoro = Kokoro(str(modelo), str(vozes))
    amostras, taxa = _kokoro.create(texto, voice=config.VOZ_KOKORO, speed=config.VELOCIDADE_VOZ, lang="pt-br")
    bruto = destino.with_name("narracao_kokoro.wav")
    sf.write(str(bruto), amostras, taxa)
    _rodar(["ffmpeg", "-y", "-i", str(bruto), "-b:a", "128k", str(destino)])
    if not destino.exists() or destino.stat().st_size < 1000:
        raise RuntimeError("Kokoro não devolveu áudio")


def _narrar_google(texto: str, destino: Path) -> None:
    """Voz de reserva (Google, gratuita). Sem tempo por palavra: a legenda é estimada."""
    from gtts import gTTS

    bruto = destino.with_name("narracao_google.mp3")
    gTTS(texto, lang="pt", tld="com.br").save(str(bruto))
    # a voz do Google é mais lenta: acelera 15% sem mudar o tom
    _rodar(["ffmpeg", "-y", "-i", str(bruto), "-filter:a", "atempo=1.15", "-b:a", "128k", str(destino)])
    if not destino.exists() or destino.stat().st_size < 1000:
        raise RuntimeError("gTTS não devolveu áudio")


def narrar(texto: str, destino: Path) -> tuple[Path | None, list[tuple[float, float, str]]]:
    """Gera a narração e devolve (arquivo, [(início, fim, palavra), ...]).

    Ordem: Kokoro (no próprio robô) → Google (reserva).
    Se as duas falharem, devolve (None, []) e o vídeo sai só com legenda.
    """
    global motivo_sem_voz, voz_usada
    motivo_sem_voz, voz_usada, erros = "", "", []
    try:
        _narrar_kokoro(texto, destino)
        voz_usada = f"Kokoro {config.VOZ_KOKORO}"
        return destino, []
    except Exception as erro:  # noqa: BLE001
        erros.append(f"Kokoro: {type(erro).__name__}: {str(erro)[:90]}")
        print("Narração (Kokoro):", repr(erro), file=sys.stderr)
    try:
        _narrar_google(texto, destino)
        voz_usada = "Google (reserva)"
        return destino, []
    except Exception as erro:  # noqa: BLE001
        erros.append(f"Google: {type(erro).__name__}: {str(erro)[:90]}")
        print("Narração (gTTS):", repr(erro), file=sys.stderr)
    motivo_sem_voz = " | ".join(erros[-2:])
    return None, []


def _tempos_estimados(texto: str, inicio: float, fim: float) -> list[tuple[float, float, str]]:
    """Sem marcação da voz: espalha as palavras pelo tempo, pelo tamanho de cada uma."""
    palavras = texto.split()
    if not palavras:
        return []
    pesos = [len(p) + 2 for p in palavras]
    total, t, saida = sum(pesos), inicio, []
    for p, w in zip(palavras, pesos):
        dur = (fim - inicio) * w / total
        saida.append((t, t + dur, p))
        t += dur
    return saida


def _frases(palavras: list[tuple[float, float, str]]) -> list[list[tuple[float, float, str]]]:
    """Agrupa as palavras em frases curtas (até 3 palavras, quebra na pontuação)."""
    grupos, atual = [], []
    for item in palavras:
        atual.append(item)
        fim_de_frase = re.search(r"[.!?,;:]$", item[2])
        if len(atual) >= PALAVRAS_POR_FRASE or fim_de_frase:
            grupos.append(atual)
            atual = []
    if atual:
        grupos.append(atual)
    return grupos


def _limpar(palavra: str) -> str:
    return palavra.strip().upper().rstrip(",;:")


# ---------------------------------------------------------------------------
# Cenas
# ---------------------------------------------------------------------------
def _clipe(quadro: Path, segundos: float, destino: Path, indice: int) -> Path:
    quadros = max(int(segundos * FPS), 1)
    # Alterna aproximação e afastamento, com zoom um pouco mais forte que antes
    if indice % 2 == 0:
        zoom = f"1+0.09*on/{quadros}"
    else:
        zoom = f"1.09-0.09*on/{quadros}"
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


def _montar_cenas(p: Produto, t: dict, fotos: list[Path], pasta: Path) -> list[tuple[Path, float]]:
    """Devolve [(quadro, peso_de_tempo)]. Fotos extras viram cenas a mais."""
    foto = lambda i: fotos[i % len(fotos)] if fotos else None  # noqa: E731
    cenas = [(arte.cena_gancho(p, t, foto(0), pasta / "cena_1.png"), 1.25)]
    if len(fotos) >= 2:
        cenas.append((arte.cena_foto(p, t, fotos[1], pasta / "cena_f1.png", "OLHA ISSO"), 0.85))
    cenas.append((arte.cena_beneficios(p, t, foto(2 if len(fotos) > 2 else 0),
                                       pasta / "cena_2.png"), 1.35))
    if len(fotos) >= 4:
        cenas.append((arte.cena_foto(p, t, fotos[3], pasta / "cena_f2.png", "DETALHES"), 0.85))
    cenas.append((arte.cena_preco(p, t, foto(0), pasta / "cena_3.png"), 1.25))
    cenas.append((arte.cena_cta(p, t, foto(0), pasta / "cena_4.png"), 0.85))
    return cenas


# ---------------------------------------------------------------------------
# Vídeo final
# ---------------------------------------------------------------------------
def gerar_video(p: Produto, t: dict, fotos: list[Path], pasta: Path) -> tuple[Path, bool]:
    """Retorna (caminho_do_video, tem_narracao)."""
    cenas = _montar_cenas(p, t, fotos, pasta)

    audio, palavras = narrar(t["narracao"], pasta / "narracao.mp3")
    total = max(DURACAO_MINIMA, (duracao(audio) + ATRASO_VOZ + 0.6) if audio else 0)
    soma = sum(peso for _, peso in cenas)
    duracoes = [total * peso / soma for _, peso in cenas]

    # Tempo de cada palavra (da voz; se não vier, estimado)
    if palavras:
        palavras = [(a + ATRASO_VOZ, b + ATRASO_VOZ, w) for a, b, w in palavras]
    else:
        fim_fala = (duracao(audio) + ATRASO_VOZ) if audio else total - 1.2
        palavras = _tempos_estimados(t["narracao"], ATRASO_VOZ, fim_fala)

    clipes = []
    for i, ((q, _), seg) in enumerate(zip(cenas, duracoes)):
        extra = TRANSICAO if i < len(cenas) - 1 else 0
        clipes.append(_clipe(q, seg + extra, pasta / f"clipe_{i}.mp4", i))

    entradas: list[str] = []
    for c in clipes:
        entradas += ["-i", str(c)]

    filtros, anterior, deslocamento = [], "[0:v]", 0.0
    transicoes = ["fade", "slideleft", "fade", "slideup", "fade"]
    for i in range(1, len(clipes)):
        deslocamento += duracoes[i - 1]
        saida = f"[v{i}]"
        filtros.append(
            f"{anterior}[{i}:v]xfade=transition={transicoes[(i - 1) % len(transicoes)]}:"
            f"duration={TRANSICAO}:offset={deslocamento:.3f}{saida}"
        )
        anterior = saida

    # Legendas animadas: uma imagem por palavra falada (frase com a palavra em destaque)
    n = len(clipes)
    legendas: list[tuple[Path, float, float]] = []
    inicios = [a for a, _, _ in palavras]
    pos = 0
    for g, frase in enumerate(_frases(palavras)):
        textos = [_limpar(w) for _, _, w in frase]
        for k, (ini, fim, _) in enumerate(frase):
            # fica na tela até a próxima palavra começar (sem "piscar" nem sobrepor)
            prox = inicios[pos + 1] if pos + 1 < len(inicios) else fim + 0.4
            prox = min(prox, fim + 0.6, total)
            arq = arte.quadro_legenda(textos, k, pasta / f"leg_{g}_{k}.png")
            legendas.append((arq, ini, prox - 0.001))
            pos += 1
    for j, (arq, ini, fim) in enumerate(legendas):
        entradas += ["-i", str(arq)]
        saida = f"[l{j}]"
        filtros.append(
            f"{anterior}[{n + j}:v]overlay=0:{arte.LEGENDA_Y}:"
            f"enable='between(t,{ini:.3f},{fim:.3f})'{saida}"
        )
        anterior = saida

    destino = pasta / "video.mp4"
    cmd = ["ffmpeg", "-y", *entradas]
    idx_audio = n + len(legendas)
    if audio:
        cmd += ["-i", str(audio)]
        atraso = int(ATRASO_VOZ * 1000)
        filtros.append(f"[{idx_audio}:a]adelay={atraso}|{atraso},apad[a]")
    else:  # faixa de áudio silenciosa: o Reels exige áudio
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        filtros.append(f"[{idx_audio}:a]anull[a]")
    cmd += ["-filter_complex", ";".join(filtros), "-map", anterior]
    # Limites do Instagram: áudio até 128 kbps / 48 kHz; vídeo até 5 Mbps
    cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "128k", "-ar", "48000"]
    cmd += [
        "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-maxrate", "4500k", "-bufsize", "9000k", "-profile:v", "high", "-g", str(FPS * 2),
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-movflags", "+faststart", str(destino),
    ]
    _rodar(cmd)
    return destino, bool(audio)

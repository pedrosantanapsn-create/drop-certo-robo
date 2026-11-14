"""🎞️ Montagem: junta os clipes que a dona gerou à mão (Gemini) num vídeo só, com narração,
legendas animadas, título, preço e chamada final — no padrão 1080x1920 do Instagram/TikTok.

Uso pelo bot: mande cada clipe com a legenda /clipe; depois /montar link-do-produto (ver main.py).
O áudio dos clipes de IA é descartado (costuma vir com ruído): entram a voz do robô e a música.
"""
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw

from . import arte, config, musicas, video
from .produto import Produto, formatar_preco

TRANSICAO = 0.35
CLIPE_MAX = 9.0            # usa no máximo isso de cada clipe
AVISO_IA = "Imagem ilustrativa gerada por IA"


def _nome_curto(nome: str, palavras: int = 5) -> str:
    limpo = re.sub(r"\s+", " ", re.sub(r"[^\w\sÀ-ú.+-]", " ", nome)).strip()
    return " ".join(limpo.split()[:palavras])


def narracao(p: Produto, textos: dict) -> str:
    beneficios = [str(b).strip().rstrip(".") for b in (textos.get("beneficios") or []) if str(b).strip()][:3]
    partes = [str(textos.get("gancho") or "Olha esse achado").strip().rstrip(".!") + "!", _nome_curto(p.nome) + "."]
    if beneficios:
        partes.append((", ".join(beneficios[:-1]) + " e " + beneficios[-1] if len(beneficios) > 1 else beneficios[0]) + ".")
    if p.preco:
        partes.append(f"Saindo por {formatar_preco(p.preco).replace('R$ ', '')} reais.")
    partes.append("O link está na bio e no canal. Segue o Drop Certo pra mais achados.")
    return " ".join(partes)


def _texto_contorno(d, xy, texto, f, largura, max_linhas, centro=True):
    linhas = arte.quebrar(d, texto, f, largura, max_linhas)
    x, y = xy
    alt = int(f.size * 1.14)
    for linha in linhas:
        d.text((x + largura / 2 if centro else x, y), linha, font=f, fill=(255, 255, 255, 255),
               anchor="ma" if centro else "la", stroke_width=8, stroke_fill=(0, 0, 0, 230))
        y += alt
    return y


def _base(pasta: Path) -> Path:
    """Sempre na tela: escurece topo e base (para o texto ler bem) + avisos legais."""
    img = Image.new("RGBA", (arte.VW, arte.VH), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for y in range(460):
        d.line([(0, y), (arte.VW, y)], fill=(0, 0, 0, int(165 * (1 - y / 460) ** 1.5)))
    for y in range(1250, arte.VH):
        d.line([(0, y), (arte.VW, y)], fill=(0, 0, 0, int(190 * ((y - 1250) / (arte.VH - 1250)) ** 1.3)))
    d.text((arte.VW / 2, 1610), AVISO_IA, font=arte.fonte("semibold", 30), fill=(240, 240, 240, 255), anchor="mm")
    d.text((arte.VW / 2, 1656), config.AVISO_LEGAL, font=arte.fonte("semibold", 26), fill=(200, 205, 212, 255), anchor="mm")
    destino = pasta / "m_base.png"
    img.save(destino)
    return destino


def _cartao_gancho(texto: str, pasta: Path) -> Path:
    img = Image.new("RGBA", (arte.VW, arte.VH), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    _texto_contorno(d, (arte.VM, 150), texto.upper() if len(texto) <= 26 else texto, arte.fonte("black", 92),
                    arte.VW - 2 * arte.VM, 3)
    destino = pasta / "m_gancho.png"
    img.save(destino)
    return destino


def _cartao_preco(p: Produto, pasta: Path) -> Path:
    img = Image.new("RGBA", (arte.VW, arte.VH), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y = _texto_contorno(d, (arte.VM, 130), _nome_curto(p.nome, 7), arte.fonte("extrabold", 54), arte.VW - 2 * arte.VM, 2)
    if p.preco:
        f = arte.fonte("black", 104)
        preco = formatar_preco(p.preco)
        w = d.textlength(preco, font=f)
        x = (arte.VW - w) / 2 - 40
        d.rounded_rectangle((x, y + 22, x + w + 80, y + 22 + 150), 40, fill=arte._rgb(config.COR_DESTAQUE) + (255,))
        d.text((arte.VW / 2, y + 22 + 75), preco, font=f, fill=arte._rgb(config.COR_FUNDO) + (255,), anchor="mm")
        if p.preco_antigo and p.preco_antigo > p.preco:
            fa = arte.fonte("semibold", 42)
            antes = f"antes {formatar_preco(p.preco_antigo)}"
            wa = d.textlength(antes, font=fa)
            ya = y + 22 + 150 + 40
            d.text((arte.VW / 2, ya), antes, font=fa, fill=(255, 255, 255, 255), anchor="mm",
                   stroke_width=5, stroke_fill=(0, 0, 0, 220))
            d.line([((arte.VW - wa) / 2, ya + 2), ((arte.VW + wa) / 2, ya + 2)], fill=(255, 255, 255, 255), width=4)
    destino = pasta / "m_preco.png"
    img.save(destino)
    return destino


def _cartao_cta(pasta: Path) -> Path:
    img = Image.new("RGBA", (arte.VW, arte.VH), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = arte.fonte("black", 58)
    texto = "LINK NA BIO E NO CANAL"
    w = d.textlength(texto, font=f)
    x = (arte.VW - w) / 2 - 44
    d.rounded_rectangle((x, 1150, x + w + 88, 1150 + 116), 58, fill=(255, 255, 255, 255))
    d.text((arte.VW / 2, 1150 + 58), texto, font=f, fill=arte._rgb(config.COR_FUNDO) + (255,), anchor="mm")
    destino = pasta / "m_cta.png"
    img.save(destino)
    return destino


def montar(clipes: list[Path], p: Produto, textos: dict, pasta: Path, nome: str = "video_montado.mp4") -> tuple[Path, bool]:
    """Devolve (vídeo, tem_voz). `textos` = {gancho, beneficios} (do kit do /roteiro)."""
    if not clipes:
        raise ValueError("nenhum clipe para montar")
    fala = narracao(p, textos)
    audio, _ = video.narrar(fala, pasta / "m_narracao.mp3")
    alvo = max((video.duracao(audio) + video.ATRASO_VOZ + 0.9) if audio else 0, 9.0)
    n = len(clipes)
    originais = [video.duracao(c) for c in clipes]
    # cada clipe ocupa uma fatia igual do tempo (limitada ao tamanho dele e a CLIPE_MAX)
    fatias = [min(o, CLIPE_MAX, alvo / n + TRANSICAO) for o in originais]
    total = sum(fatias) - TRANSICAO * (n - 1)
    falta = max(alvo - total, 0)                      # narração mais longa que os clipes: congela o último quadro
    total += falta

    cmd = ["ffmpeg", "-y"]
    for c in clipes:
        cmd += ["-i", str(c)]
    filtros = []
    for i, seg in enumerate(fatias):
        extra = f",tpad=stop_mode=clone:stop_duration={falta:.3f}" if i == n - 1 and falta else ""
        filtros.append(f"[{i}:v]trim=0:{seg:.3f},setpts=PTS-STARTPTS,scale={arte.VW}:{arte.VH}:force_original_aspect_ratio=increase,"
                       f"crop={arte.VW}:{arte.VH},fps={video.FPS},format=yuv420p,setsar=1{extra}[c{i}]")
    anterior, deslocamento = "[c0]", 0.0
    for i in range(1, n):
        deslocamento += fatias[i - 1] - TRANSICAO
        filtros.append(f"{anterior}[c{i}]xfade=transition=fade:duration={TRANSICAO}:offset={deslocamento:.3f}[x{i}]")
        anterior = f"[x{i}]"

    # cartões: gancho no 1º clipe, preço do 2º em diante (ou na 2ª metade), chamada nos últimos segundos
    virada = (fatias[0] - TRANSICAO) if n > 1 else total * 0.5
    sobre = [(_base(pasta), 0.0, total, 0), (_cartao_gancho(str(textos.get("gancho") or "Olha esse achado"), pasta), 0.25, virada - 0.1, 0),
             (_cartao_preco(p, pasta), virada + 0.25, total, 0), (_cartao_cta(pasta), max(total - 3.2, virada + 0.4), total, 0)]
    # legendas animadas da narração (mesmo estilo dos vídeos do robô)
    fim_fala = (video.duracao(audio) + video.ATRASO_VOZ) if audio else total - 1.0
    palavras = video._tempos_estimados(fala, video.ATRASO_VOZ, fim_fala)
    inicios, pos = [a for a, _, _ in palavras], 0
    for g, frase in enumerate(video._frases(palavras)):
        ditas = [video._limpar(w) for _, _, w in frase]
        for k, (ini, fim, _) in enumerate(frase):
            prox = min(inicios[pos + 1] if pos + 1 < len(inicios) else fim + 0.4, fim + 0.6, total)
            sobre.append((arte.quadro_legenda(ditas, k, pasta / f"m_leg_{g}_{k}.png"), ini, prox - 0.001, arte.LEGENDA_Y))
            pos += 1
    entrada = n
    for j, (png, ini, fim, y) in enumerate(sobre):
        cmd += ["-i", str(png)]
        filtros.append(f"{anterior}[{entrada}:v]overlay=0:{y}:enable='between(t,{ini:.3f},{fim:.3f})'[o{j}]")
        anterior, entrada = f"[o{j}]", entrada + 1

    musica = musicas.sortear(pasta / "m_musica.mp3")
    rotulo_voz = "[voz]" if musica else "[a]"
    if audio:
        cmd += ["-i", str(audio)]
        atraso = int(video.ATRASO_VOZ * 1000)
        filtros.append(f"[{entrada}:a]adelay={atraso}|{atraso},apad,aformat=sample_rates=48000:channel_layouts=stereo{rotulo_voz}")
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        filtros.append(f"[{entrada}:a]anull{rotulo_voz}")
    if musica:
        volume = config.VOLUME_MUSICA if audio else min(config.VOLUME_MUSICA * 3, 0.6)
        cmd += ["-stream_loop", "-1", "-i", str(musica)]
        filtros.append(f"[{entrada + 1}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={volume},"
                       f"afade=t=in:d=0.6,afade=t=out:st={max(total - 1.5, 0):.2f}:d=1.5[mus]")
        filtros.append("[voz][mus]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")
    destino = pasta / nome
    cmd += ["-filter_complex", ";".join(filtros), "-map", anterior, "-map", "[a]", "-c:a", "aac", "-b:a", "128k",
            "-ar", "48000", "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-maxrate", "4500k", "-bufsize", "9000k", "-profile:v", "high", "-g", str(video.FPS * 2),
            "-pix_fmt", "yuv420p", "-r", str(video.FPS), "-movflags", "+faststart", str(destino)]
    video._rodar(cmd)
    return destino, bool(audio)

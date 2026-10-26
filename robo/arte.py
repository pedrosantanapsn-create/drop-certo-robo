"""Arte do post (feed 1080x1350) e quadros do vídeo (1080x1920)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from . import config
from .produto import Produto, formatar_preco

PESOS = {
    "semibold": "Inter-SemiBold.otf",
    "bold": "Inter-Bold.otf",
    "extrabold": "Inter-ExtraBold.otf",
    "black": "Inter-Black.otf",
}
CINZA = "#9AA4B2"


# Onde procurar a fonte Inter: pasta do projeto, Linux (GitHub) e Windows
PASTAS_FONTES = [
    config.PASTA_FONTES,
    Path("/usr/share/fonts/opentype/inter"),
    Path.home() / "AppData/Local/Microsoft/Windows/Fonts",
    Path("C:/Windows/Fonts"),
]
# Reserva no Windows, caso a Inter não esteja instalada
RESERVA_WINDOWS = {"semibold": "seguisb.ttf", "bold": "arialbd.ttf",
                   "extrabold": "ariblk.ttf", "black": "ariblk.ttf"}
_cache: dict = {}


def _arquivo_fonte(peso: str) -> str:
    if peso not in _cache:
        candidatos = [p / PESOS[peso] for p in PASTAS_FONTES]
        candidatos += [Path("C:/Windows/Fonts") / RESERVA_WINDOWS[peso]]
        _cache[peso] = next((str(c) for c in candidatos if c.exists()), None)
        if not _cache[peso]:
            raise FileNotFoundError("Fonte Inter não encontrada. No Linux: sudo apt install fonts-inter")
    return _cache[peso]


def fonte(peso: str, tamanho: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_arquivo_fonte(peso), tamanho)


def _rgb(hexa: str) -> tuple[int, int, int]:
    hexa = hexa.lstrip("#")
    return tuple(int(hexa[i : i + 2], 16) for i in (0, 2, 4))


def quebrar(draw, texto: str, f, largura: int, max_linhas: int) -> list[str]:
    palavras = [w for w in texto.replace("R$ ", "R$\u00a0").split(" ") if w]
    linhas, atual = [], ""
    for p in palavras:
        teste = f"{atual} {p}".strip()
        if draw.textlength(teste, font=f) <= largura:
            atual = teste
        else:
            if atual:
                linhas.append(atual)
            atual = p
    if atual:
        linhas.append(atual)
    if len(linhas) > max_linhas:
        linhas = linhas[:max_linhas]
        while linhas[-1] and draw.textlength(linhas[-1] + "…", font=f) > largura:
            linhas[-1] = linhas[-1].rsplit(" ", 1)[0] if " " in linhas[-1] else linhas[-1][:-1]
        linhas[-1] += "…"
    return linhas


def texto_bloco(draw, xy, texto, f, cor, largura, max_linhas, espaco=1.18, centro=False) -> int:
    """Desenha texto quebrado em linhas; devolve o y final."""
    x, y = xy
    altura = int(f.size * espaco)
    for linha in quebrar(draw, texto, f, largura, max_linhas):
        lx = x + (largura - draw.textlength(linha, font=f)) / 2 if centro else x
        draw.text((lx, y), linha, font=f, fill=cor)
        y += altura
    return y


def fundo(largura: int, altura: int) -> Image.Image:
    base = Image.new("RGB", (largura, altura), _rgb(config.COR_FUNDO))
    brilho = Image.new("L", (largura, altura), 0)
    d = ImageDraw.Draw(brilho)
    d.ellipse((-largura * 0.3, -altura * 0.25, largura * 1.3, altura * 0.45), fill=34)
    brilho = brilho.filter(ImageFilter.GaussianBlur(180))
    cor = Image.new("RGB", (largura, altura), _rgb(config.COR_DESTAQUE))
    return Image.composite(cor, base, brilho)


def cartao_produto(canvas: Image.Image, foto: Path | None, caixa, raio: int = 48) -> None:
    x0, y0, x1, y1 = caixa
    w, h = x1 - x0, y1 - y0
    cartao = Image.new("RGB", (w, h), "white")
    if foto:
        try:
            img = ImageOps.exif_transpose(Image.open(foto)).convert("RGB")
            img = ImageOps.contain(img, (int(w * 0.86), int(h * 0.86)), Image.LANCZOS)
            cartao.paste(img, ((w - img.width) // 2, (h - img.height) // 2))
        except OSError:
            foto = None
    if not foto:
        d = ImageDraw.Draw(cartao)
        f = fonte("black", 72)
        d.text((w / 2, h / 2), config.MARCA, font=f, fill=_rgb(config.COR_FUNDO), anchor="mm")
    mascara = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mascara).rounded_rectangle((0, 0, w, h), raio, fill=255)
    sombra = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(sombra).rounded_rectangle((x0, y0 + 18, x1, y1 + 18), raio, fill=110)
    sombra = sombra.filter(ImageFilter.GaussianBlur(28))
    canvas.paste(Image.new("RGB", canvas.size, "black"), (0, 0), sombra)
    canvas.paste(cartao, (x0, y0), mascara)


def selo_desconto(draw, centro, desconto: int, raio: int = 92) -> None:
    cx, cy = centro
    draw.ellipse((cx - raio, cy - raio, cx + raio, cy + raio), fill=config.COR_DESTAQUE)
    draw.text((cx, cy - 14), f"-{desconto}%", font=fonte("black", int(raio * 0.62)),
              fill=config.COR_FUNDO, anchor="mm")
    draw.text((cx, cy + raio * 0.45), "OFF", font=fonte("extrabold", int(raio * 0.3)),
              fill=config.COR_FUNDO, anchor="mm")


def pilula(draw, xy, texto, f, cor_fundo, cor_texto, pad=(28, 14)) -> int:
    x, y = xy
    w = draw.textlength(texto, font=f)
    alt = f.size + pad[1] * 2
    draw.rounded_rectangle((x, y, x + w + pad[0] * 2, y + alt), alt // 2, fill=cor_fundo)
    draw.text((x + pad[0], y + alt / 2), texto, font=f, fill=cor_texto, anchor="lm")
    return int(x + w + pad[0] * 2)


def bloco_preco(draw, x, y, p: Produto, tam: int, centro_largura: int | None = None) -> int:
    """Preço antigo riscado + preço atual. Devolve o y final."""
    if p.preco_antigo and p.desconto:
        f = fonte("semibold", int(tam * 0.36))
        txt = f"de {formatar_preco(p.preco_antigo)}"
        lx = x + (centro_largura - draw.textlength(txt, font=f)) / 2 if centro_largura else x
        draw.text((lx, y), txt, font=f, fill=CINZA)
        larg = draw.textlength(txt, font=f)
        meio = y + f.size * 0.62
        draw.line((lx + draw.textlength("de ", font=f), meio, lx + larg, meio), fill=CINZA, width=4)
        y += int(f.size * 1.35)
    if p.preco:
        f = fonte("black", tam)
        txt = formatar_preco(p.preco)
        while draw.textlength(txt, font=f) > (centro_largura or 960) and f.size > 40:
            f = fonte("black", f.size - 6)
        lx = x + (centro_largura - draw.textlength(txt, font=f)) / 2 if centro_largura else x
        draw.text((lx, y), txt, font=f, fill=config.COR_DESTAQUE)
        y += int(f.size * 1.15)
    else:
        f = fonte("extrabold", int(tam * 0.5))
        txt = "Confira o preço no link"
        lx = x + (centro_largura - draw.textlength(txt, font=f)) / 2 if centro_largura else x
        draw.text((lx, y), txt, font=f, fill=config.COR_DESTAQUE)
        y += int(f.size * 1.3)
    return y


def selo_cupom(draw, x, y, p: Produto, tam: int = 40, centro_largura: int | None = None) -> int:
    """Tíquete tracejado "CUPOM: CODIGO". Devolve o y final."""
    if not p.cupom:
        return y
    f = fonte("black", tam)
    txt = f"CUPOM: {p.cupom}"
    larg = draw.textlength(txt, font=f) + tam * 1.4
    alt = tam * 1.9
    x0 = x + (centro_largura - larg) / 2 if centro_largura else x
    draw.rounded_rectangle((x0, y, x0 + larg, y + alt), int(alt / 3), fill=config.COR_DESTAQUE)
    passo = 18
    for xi in range(int(x0 + 14), int(x0 + larg - 14), passo):       # tracejado de tíquete
        draw.line((xi, y + 7, xi + passo / 2, y + 7), fill=config.COR_FUNDO, width=3)
        draw.line((xi, y + alt - 7, xi + passo / 2, y + alt - 7), fill=config.COR_FUNDO, width=3)
    draw.text((x0 + larg / 2, y + alt / 2), txt, font=f, fill=config.COR_FUNDO, anchor="mm")
    return int(y + alt)


# ---------------------------------------------------------------------------
# Arte do feed (1080 x 1350)
# ---------------------------------------------------------------------------
def arte_feed(p: Produto, t: dict, fotos: list[Path], destino: Path) -> Path:
    W, H, M = 1080, 1350, 64
    img = fundo(W, H)
    d = ImageDraw.Draw(img)

    pilula(d, (M, 56), "ACHADO DO DIA", fonte("black", 30), config.COR_DESTAQUE, config.COR_FUNDO)
    f_marca = fonte("black", 34)
    d.text((W - M, 56 + 29), config.MARCA, font=f_marca, fill=config.COR_TEXTO, anchor="rm")

    cartao_produto(img, fotos[0] if fotos else None, (M, 150, W - M, 830))
    if p.desconto:
        selo_desconto(d, (W - M - 100, 250), p.desconto, raio=86)

    y = texto_bloco(d, (M, 880), t.get("titulo_curto") or p.nome, fonte("bold", 54),
                    config.COR_TEXTO, W - 2 * M, 2)
    fim = bloco_preco(d, M, y + 14, p, 118 if not p.cupom else 96)
    if p.cupom:
        selo_cupom(d, M, min(fim + 20, H - 120 - 90), p, 38)

    d.rectangle((0, H - 120, W, H), fill=config.COR_DESTAQUE)
    d.text((M, H - 74), f"LINK NA BIO  •  {config.ARROBA}", font=fonte("black", 38),
           fill=config.COR_FUNDO, anchor="lm")
    d.text((M, H - 30), config.AVISO_LEGAL, font=fonte("semibold", 24),
           fill=config.COR_FUNDO, anchor="lm")

    img.save(destino, quality=92)
    return destino


# ---------------------------------------------------------------------------
# Quadros do vídeo (1080 x 1920)
# ---------------------------------------------------------------------------
VW, VH, VM = 1080, 1920, 72


LEGENDA_Y = 1335   # topo da faixa de legendas animadas (altura ~200 px)


def _rodape_video(d) -> None:
    d.text((VW / 2, 1575), config.AVISO_LEGAL, font=fonte("semibold", 28),
           fill=CINZA, anchor="mm")


def cena_gancho(p: Produto, t: dict, foto: Path | None, destino: Path) -> Path:
    img = fundo(VW, VH)
    d = ImageDraw.Draw(img)
    pilula(d, (VM, 200), "ACHADO DO DIA", fonte("black", 36), config.COR_DESTAQUE, config.COR_FUNDO)
    texto_bloco(d, (VM, 290), t["gancho"].upper(), fonte("black", 92), config.COR_TEXTO,
                VW - 2 * VM, 3, espaco=1.06)
    cartao_produto(img, foto, (VM + 60, 640, VW - VM - 60, 1290), raio=56)
    if p.desconto:
        selo_desconto(d, (VW - VM - 110, 720), p.desconto, raio=100)
    _rodape_video(d)
    img.save(destino)
    return destino


def cena_beneficios(p: Produto, t: dict, foto: Path | None, destino: Path) -> Path:
    img = fundo(VW, VH)
    d = ImageDraw.Draw(img)
    cartao_produto(img, foto, (VM + 40, 190, VW - VM - 40, 760), raio=56)
    y = texto_bloco(d, (VM, 800), t.get("titulo_curto") or p.nome, fonte("extrabold", 60),
                    config.COR_TEXTO, VW - 2 * VM, 2)
    y += 30
    f = fonte("bold", 50)
    for b in t["beneficios"][:3]:
        d.ellipse((VM, y + 12, VM + 40, y + 52), fill=config.COR_DESTAQUE)
        d.line((VM + 10, y + 33, VM + 18, y + 42), fill=config.COR_FUNDO, width=6)
        d.line((VM + 18, y + 42, VM + 31, y + 22), fill=config.COR_FUNDO, width=6)
        y = texto_bloco(d, (VM + 70, y), b, f, config.COR_TEXTO, VW - 2 * VM - 70, 1) + 22
    _rodape_video(d)
    img.save(destino)
    return destino


def cena_preco(p: Produto, t: dict, foto: Path | None, destino: Path) -> Path:
    img = fundo(VW, VH)
    d = ImageDraw.Draw(img)
    cartao_produto(img, foto, (VM + 110, 190, VW - VM - 110, 850), raio=56)
    if p.desconto:
        selo_desconto(d, (VW - VM - 100, 270), p.desconto, raio=110)
    d.text((VW / 2, 945), "SAINDO POR", font=fonte("black", 54), fill=config.COR_TEXTO, anchor="mm")
    fim = bloco_preco(d, 0, 1000, p, 160 if not p.cupom else 140, centro_largura=VW)
    if p.cupom:
        selo_cupom(d, 0, min(fim + 34, LEGENDA_Y - 110), p, 46, centro_largura=VW)
    _rodape_video(d)
    img.save(destino)
    return destino


def cena_cta(p: Produto, t: dict, foto: Path | None, destino: Path) -> Path:
    img = fundo(VW, VH)
    d = ImageDraw.Draw(img)
    d.text((VW / 2, 480), config.MARCA, font=fonte("black", 110), fill=config.COR_TEXTO, anchor="mm")
    d.text((VW / 2, 600), "achados que valem a pena", font=fonte("semibold", 46),
           fill=CINZA, anchor="mm")
    f = fonte("black", 72)
    txt = "LINK NA BIO"
    w = d.textlength(txt, font=f)
    d.rounded_rectangle((VW / 2 - w / 2 - 60, 760, VW / 2 + w / 2 + 60, 900), 70,
                        fill=config.COR_DESTAQUE)
    d.text((VW / 2, 830), txt, font=f, fill=config.COR_FUNDO, anchor="mm")
    d.text((VW / 2, 1010), config.ARROBA, font=fonte("extrabold", 64), fill=config.COR_DESTAQUE,
           anchor="mm")
    d.text((VW / 2, 1120), "Siga para mais achados", font=fonte("semibold", 44),
           fill=config.COR_TEXTO, anchor="mm")
    _rodape_video(d)
    img.save(destino)
    return destino


def cena_foto(p: Produto, t: dict, foto: Path | None, destino: Path, rotulo: str = "") -> Path:
    """Cena só com a foto do produto, grande, sobre a própria foto desfocada."""
    img = fundo(VW, VH)
    if foto:
        try:
            base = ImageOps.exif_transpose(Image.open(foto)).convert("RGB")
            borrada = ImageOps.fit(base, (VW, VH), Image.LANCZOS).filter(ImageFilter.GaussianBlur(40))
            escuro = Image.new("RGB", (VW, VH), _rgb(config.COR_FUNDO))
            img = Image.blend(borrada, escuro, 0.55)
        except OSError:
            foto = None
    cartao_produto(img, foto, (VM, 230, VW - VM, 1250), raio=60)
    d = ImageDraw.Draw(img)
    if rotulo:
        f = fonte("black", 44)
        w = d.textlength(rotulo, font=f)
        pilula(d, ((VW - w) / 2 - 30, 120), rotulo, f, config.COR_DESTAQUE, config.COR_FUNDO, pad=(30, 14))
    _rodape_video(d)
    img.save(destino)
    return destino


def quadro_legenda(palavras: list[str], ativa: int, destino: Path) -> Path:
    """Faixa transparente com a frase falada; a palavra da vez em destaque (estilo Reels)."""
    larg_max = VW - 2 * VM - 40
    tam = 70
    f = fonte("black", tam)
    rascunho = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    espaco = rascunho.textlength(" ", font=f)
    # monta até 2 linhas
    linhas, atual, larg = [], [], 0.0
    for i, w in enumerate(palavras):
        lw = rascunho.textlength(w, font=f)
        if atual and larg + espaco + lw > larg_max:
            linhas.append(atual)
            atual, larg = [], 0.0
        atual.append((i, w, lw))
        larg += (espaco if len(atual) > 1 else 0) + lw
    if atual:
        linhas.append(atual)
    alt_linha = int(tam * 1.18)
    img = Image.new("RGBA", (VW, 210), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y = (210 - alt_linha * len(linhas)) // 2
    for linha in linhas:
        total = sum(lw for _, _, lw in linha) + espaco * (len(linha) - 1)
        x = (VW - total) / 2
        for i, w, lw in linha:
            if i == ativa:
                d.rounded_rectangle((x - 12, y - 4, x + lw + 12, y + alt_linha - 2), 16,
                                    fill=_rgb(config.COR_DESTAQUE) + (255,))
                d.text((x, y + 2), w, font=f, fill=_rgb(config.COR_FUNDO) + (255,))
            else:
                d.text((x, y + 2), w, font=f, fill=(255, 255, 255, 255),
                       stroke_width=7, stroke_fill=(0, 0, 0, 235))
            x += lw + espaco
        y += alt_linha
    img.save(destino)
    return destino


# ---------------------------------------------------------------------------
# Vídeo "Top 5" (ranking por nota/vendas)
# ---------------------------------------------------------------------------
def cena_ranking_capa(titulo: str, subtitulo: str, destino: Path) -> Path:
    img = fundo(VW, VH)
    d = ImageDraw.Draw(img)
    pilula(d, (VM, 300), "TOP 5", fonte("black", 64), config.COR_DESTAQUE, config.COR_FUNDO, pad=(40, 18))
    y = texto_bloco(d, (VM, 440), titulo.upper(), fonte("black", 96), config.COR_TEXTO, VW - 2 * VM, 5, espaco=1.05)
    texto_bloco(d, (VM, y + 40), subtitulo, fonte("semibold", 46), CINZA, VW - 2 * VM, 3)
    d.text((VM, 1180), config.MARCA, font=fonte("black", 52), fill=config.COR_DESTAQUE)
    _rodape_video(d)
    img.save(destino)
    return destino


def cena_ranking_item(posicao: int, nome: str, preco: float | None, nota: float | None,
                      vendas: int | None, loja: str, foto: Path | None, destino: Path,
                      motivo: str = "") -> Path:
    img = fundo(VW, VH)
    d = ImageDraw.Draw(img)
    # número grande da posição
    d.text((VM, 120), f"#{posicao}", font=fonte("black", 170), fill=config.COR_DESTAQUE)
    d.text((VM + 300, 185), loja.upper(), font=fonte("extrabold", 40), fill=CINZA)
    cartao_produto(img, foto, (VM + 40, 360, VW - VM - 40, 900), raio=56)
    y = texto_bloco(d, (VM, 950), nome, fonte("extrabold", 58), config.COR_TEXTO, VW - 2 * VM, 2)
    y += 10
    if preco:
        d.text((VM, y), formatar_preco(preco), font=fonte("black", 104), fill=config.COR_DESTAQUE)
        y += 125
    detalhes = []
    if nota:
        detalhes.append(f"★ {nota:.1f}".replace(".", ","))
    if vendas:
        detalhes.append(f"{vendas:,} vendidos".replace(",", "."))
    if detalhes:
        d.text((VM, y), "  ·  ".join(detalhes), font=fonte("bold", 46), fill=config.COR_TEXTO)
        y += 70
    if motivo:
        texto_bloco(d, (VM, y), f"✓ {motivo}".replace("✓", "+"), fonte("semibold", 40), CINZA,
                    VW - 2 * VM, 2)
    _rodape_video(d)
    img.save(destino)
    return destino


def cena_ranking_fim(destino: Path) -> Path:
    img = fundo(VW, VH)
    d = ImageDraw.Draw(img)
    d.text((VW / 2, 470), "Qual você levaria?", font=fonte("black", 78), fill=config.COR_TEXTO, anchor="mm")
    d.text((VW / 2, 570), "comenta o número 👇".replace("👇", ""), font=fonte("semibold", 48),
           fill=CINZA, anchor="mm")
    f = fonte("black", 66)
    txt = "LINKS NO CANAL E NA BIO"
    w = d.textlength(txt, font=f)
    d.rounded_rectangle((VW / 2 - w / 2 - 50, 720, VW / 2 + w / 2 + 50, 850), 65, fill=config.COR_DESTAQUE)
    d.text((VW / 2, 785), txt, font=f, fill=config.COR_FUNDO, anchor="mm")
    d.text((VW / 2, 960), config.ARROBA, font=fonte("extrabold", 64), fill=config.COR_DESTAQUE, anchor="mm")
    _rodape_video(d)
    img.save(destino)
    return destino

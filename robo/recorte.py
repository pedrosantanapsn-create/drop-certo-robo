"""Foto limpa do produto a partir do print que você manda.

O Gemini (gratuito) acha onde está o produto no print e devolve o contorno
dele (máscara). O robô recorta só o produto, tira o fundo e coloca num fundo
branco limpo — essa imagem nova vira a foto do vídeo, da arte e do site.

Por que recortar e não "desenhar" um produto novo com IA: uma imagem inventada
pode mostrar cor, formato ou detalhe diferente do que a loja vende, e anúncio
que não corresponde ao produto pode ser considerado publicidade enganosa
(CDC, art. 37). O recorte mantém o produto real do anúncio.

Se o Gemini não conseguir o contorno, o robô usa só o retângulo do produto;
se nem isso, usa o print inteiro, como antes.
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

from . import config, gemini
from .legenda import _limpar_json

PROMPT = """Nesta imagem (print ou foto de um anúncio de loja online), encontre a FOTO PRINCIPAL do
produto que está à venda — ignore textos, preços, botões, logos, ícones e miniaturas pequenas.
Responda só com uma lista JSON com UM item:
[{"label": "nome curto do produto", "box_2d": [ymin, xmin, ymax, xmax], "mask": "máscara de segmentação PNG em base64"}]
As coordenadas de box_2d vão de 0 a 1000. A máscara cobre só o produto, dentro do box_2d."""

TAMANHO = 1200          # imagem final quadrada
MARGEM = 0.08           # respiro em volta do produto
MINIMO_PX = 220         # recorte menor que isso fica feio: usa o print inteiro


def _pedir_gemini(foto: Path) -> dict | None:
    dados_img = base64.b64encode(foto.read_bytes()).decode()
    try:
        dados, _ = gemini.chamar([{"text": PROMPT},
                                  {"inline_data": {"mime_type": "image/jpeg", "data": dados_img}}],
                                 temperatura=0.1, pensar=False)
        texto = gemini.texto(dados).strip()
        if texto.lstrip().startswith("["):
            lista = json.loads(texto[texto.find("["): texto.rfind("]") + 1])
            return lista[0] if lista else None
        return _limpar_json(texto)
    except Exception:  # noqa: BLE001
        return None


def _caixa_em_pixels(caixa, largura: int, altura: int) -> tuple[int, int, int, int] | None:
    try:
        y0, x0, y1, x1 = (float(v) for v in caixa)
    except (TypeError, ValueError):
        return None
    esq, cima = int(x0 / 1000 * largura), int(y0 / 1000 * altura)
    dir_, baixo = int(x1 / 1000 * largura), int(y1 / 1000 * altura)
    if dir_ - esq < MINIMO_PX or baixo - cima < MINIMO_PX:
        return None
    return max(0, esq), max(0, cima), min(largura, dir_), min(altura, baixo)


def _mascara(texto_png: str, tamanho: tuple[int, int]) -> Image.Image | None:
    if not texto_png:
        return None
    try:
        bruto = texto_png.split(",", 1)[1] if texto_png.startswith("data:") else texto_png
        mascara = Image.open(io.BytesIO(base64.b64decode(bruto))).convert("L").resize(tamanho, Image.BILINEAR)
    except Exception:  # noqa: BLE001
        return None
    mascara = mascara.point(lambda v: 255 if v >= 127 else 0).filter(ImageFilter.GaussianBlur(1.2))
    cobertura = sum(1 for v in mascara.getdata() if v > 127) / (tamanho[0] * tamanho[1])
    # máscara quase vazia ou quase cheia não serve (o Gemini errou)
    return mascara if 0.08 <= cobertura <= 0.97 else None


def _no_fundo_branco(produto: Image.Image) -> Image.Image:
    lado = TAMANHO
    util = int(lado * (1 - 2 * MARGEM))
    produto = ImageOps.contain(produto, (util, util), Image.LANCZOS)
    fundo = Image.new("RGB", (lado, lado), "white")
    pos = ((lado - produto.width) // 2, (lado - produto.height) // 2)
    fundo.paste(produto, pos, produto if produto.mode == "RGBA" else None)
    return fundo


def foto_limpa(foto: Path, destino: Path) -> tuple[Path | None, str]:
    """Devolve (imagem nova só do produto, como foi feita) ou (None, motivo)."""
    if not config.GEMINI_API_KEY:
        return None, "sem chave do Gemini"
    original = ImageOps.exif_transpose(Image.open(foto)).convert("RGB")
    achado = _pedir_gemini(foto)
    if not achado:
        return None, "o Gemini não achou o produto no print"
    caixa = _caixa_em_pixels(achado.get("box_2d"), original.width, original.height)
    if not caixa:
        return None, "produto pequeno demais no print"
    recorte = original.crop(caixa)
    mascara = _mascara(str(achado.get("mask") or ""), recorte.size)
    if mascara:
        recorte = recorte.convert("RGBA")
        recorte.putalpha(mascara)
        recorte = recorte.crop(mascara.getbbox() or (0, 0, *recorte.size))
        como = "recortado e sem fundo"
    else:
        como = "recortado (fundo original)"
    _no_fundo_branco(recorte).save(destino, "JPEG", quality=93)
    return destino, como

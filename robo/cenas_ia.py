"""Cenas de IA no vídeo: o produto "em uso", gerado pelo Gemini a partir da foto real do produto.

É PAGO (o plano grátis do Google não gera imagem): cada imagem custa centavos de dólar. Por isso:
  • só entra em poucos vídeos por dia — os do horário de pico, onde sai a oferta de maior nota;
  • teto diário CENAS_IA_DIA (imagens). Bateu no teto ou a geração falhou: o vídeo sai normal;
  • toda cena leva o aviso "Imagem ilustrativa gerada por IA" (não é foto real do produto — CDC art. 37).

Comandos: /cenas_ia (situação e gasto do dia) · /cenas_ia agora (o próximo vídeo usa, mesmo fora do pico)
Desligar: variável CENAS_IA=false.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageOps

from . import arte, config, fila, supabase

CHAVE = "cenas_ia"            # {"dia": "yymmdd", "n": imagens hoje, "mes": "yymm", "n_mes": imagens no mês}
CHAVE_FORCAR = "cenas_ia_forcar"
URL = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"

BASE = ("Use the product shown in the reference photo EXACTLY as it is: same shape, colors, proportions and "
        "brand markings. Do not invent another model. Photorealistic vertical 9:16 advertising photo. "
        "No text, no captions, no watermark, no extra logos. Product: {nome}. ")
PEDIDOS = [
    ("NO DIA A DIA", "Scene: a young Brazilian adult naturally using this product in its normal everyday context "
                     "(home, desk, street or cafe, whatever fits the product), candid lifestyle shot, soft natural "
                     "light, shallow depth of field, the product clearly visible."),
    ("OLHA O DETALHE", "Scene: premium close-up hero shot of the product alone on a dark elegant surface with a warm "
                       "glowing light behind it, cinematic lighting, reflections, studio quality."),
]


def _estado() -> dict:
    try:
        e = json.loads((supabase.ler_config(CHAVE) or {}).get("valor") or "{}")
    except ValueError:
        e = {}
    agora = datetime.now(fila.FUSO)
    if e.get("dia") != agora.strftime("%y%m%d"):
        e["dia"], e["n"] = agora.strftime("%y%m%d"), 0
    if e.get("mes") != agora.strftime("%y%m"):
        e["mes"], e["n_mes"] = agora.strftime("%y%m"), 0
    return e


def forcar_proximo() -> None:
    supabase.gravar_config(CHAVE_FORCAR, "1")


def resumo() -> str:
    if not config.CENAS_IA:
        return "🎬 Cenas de IA desligadas (variável CENAS_IA=false)."
    if not config.GEMINI_API_KEY_PAGA:
        return ("🎬 Cenas de IA: falta a chave paga. Crie uma chave do Gemini num projeto COM cobrança ativada e "
                "guarde no GitHub como o segredo GEMINI_API_KEY_PAGA (a chave grátis continua para os textos).")
    e = _estado()
    gasto = e.get("n_mes", 0) * config.CENAS_IA_PRECO_USD
    return (f"🎬 Cenas de IA nos vídeos (pago — Google Gemini, modelo {config.CENAS_IA_MODELO})\n"
            f"Hoje: {e.get('n', 0)} de {config.CENAS_IA_DIA} imagens.\n"
            f"Neste mês: {e.get('n_mes', 0)} imagens ≈ US$ {gasto:.2f} (estimativa: US$ "
            f"{config.CENAS_IA_PRECO_USD:.4f} por imagem; o valor certo está na sua conta do Google).\n"
            "Entram sozinhas nos vídeos do horário de pico, até o teto do dia.\n"
            "/cenas_ia agora — o próximo vídeo usa as cenas, mesmo fora do pico.")


def _pode(e: dict) -> bool:
    if not (config.CENAS_IA and config.GEMINI_API_KEY_PAGA and supabase.ativo()):
        return False
    if e.get("n", 0) + len(PEDIDOS) > config.CENAS_IA_DIA:
        return False
    if (supabase.ler_config(CHAVE_FORCAR) or {}).get("valor") == "1":
        return True
    return fila.em_pico(datetime.now(fila.FUSO))


def _gerar_imagem(foto: Path, pedido: str) -> bytes | None:
    """Uma imagem. None = não gerou (sem cobrança ativada, limite, recusa do modelo…)."""
    with Image.open(foto) as img:                       # manda a foto do produto em tamanho moderado
        ref = ImageOps.exif_transpose(img).convert("RGB")
        ref.thumbnail((1024, 1024))
        from io import BytesIO
        buf = BytesIO()
        ref.save(buf, "JPEG", quality=88)
    partes = [{"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}},
              {"text": pedido}]
    cfg = {"responseModalities": ["TEXT", "IMAGE"], "imageConfig": {"aspectRatio": "9:16"}}
    for tentativa in range(2):
        r = requests.post(URL.format(modelo=config.CENAS_IA_MODELO), timeout=150,
                          headers={"x-goog-api-key": config.GEMINI_API_KEY_PAGA},
                          json={"contents": [{"parts": partes}], "generationConfig": cfg})
        if r.status_code == 400 and "imageConfig" in cfg:      # modelo que não aceita o formato: tenta sem
            cfg.pop("imageConfig")
            continue
        if r.status_code >= 300:
            print(f"::warning::Cena de IA: {r.status_code} {r.text[:160]}".replace("\n", " "))
            return None
        for parte in ((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or []:
            dado = (parte.get("inlineData") or {}).get("data")
            if dado:
                return base64.b64decode(dado)
        print("::warning::Cena de IA: o modelo respondeu sem imagem")
        return None
    return None


def _quadro(bruta: bytes, rotulo: str, destino: Path) -> Path:
    """Quadro 1080x1920 do vídeo: a imagem de IA em tela cheia + rótulo + aviso de imagem ilustrativa."""
    from io import BytesIO
    img = ImageOps.fit(Image.open(BytesIO(bruta)).convert("RGB"), (arte.VW, arte.VH), Image.LANCZOS)
    faixa = Image.new("RGBA", (arte.VW, arte.VH), (0, 0, 0, 0))
    df = ImageDraw.Draw(faixa)
    for y in range(0, 330):                              # escurece o topo para o rótulo ficar legível
        df.line([(0, y), (arte.VW, y)], fill=(0, 0, 0, int(150 * (1 - y / 330))))
    df.rectangle([(0, 1650), (arte.VW, 1730)], fill=(0, 0, 0, 150))
    img = Image.alpha_composite(img.convert("RGBA"), faixa).convert("RGB")
    d = ImageDraw.Draw(img)
    f = arte.fonte("black", 44)
    w = d.textlength(rotulo, font=f)
    arte.pilula(d, ((arte.VW - w) / 2 - 30, 120), rotulo, f, config.COR_DESTAQUE, config.COR_FUNDO, pad=(30, 14))
    d.text((arte.VW / 2, 1690), "Imagem ilustrativa gerada por IA", font=arte.fonte("semibold", 30),
           fill=(235, 235, 235), anchor="mm")
    img.save(destino)
    return destino


def gerar(nome: str, foto: Path | None, pasta: Path) -> list[Path]:
    """Quadros de IA para o vídeo (lista vazia = o vídeo sai normal). Nunca derruba o post."""
    try:
        if not foto:
            return []
        estado = _estado()
        if not _pode(estado):
            return []
        supabase.gravar_config(CHAVE_FORCAR, "")
        quadros = []
        for i, (rotulo, cena) in enumerate(PEDIDOS):
            bruta = _gerar_imagem(foto, BASE.format(nome=nome[:120]) + cena)
            if not bruta:
                break                                    # falhou a primeira: não insiste (nem gasta) na segunda
            estado["n"] = estado.get("n", 0) + 1
            estado["n_mes"] = estado.get("n_mes", 0) + 1
            supabase.gravar_config(CHAVE, json.dumps(estado))
            quadros.append(_quadro(bruta, rotulo, pasta / f"cena_ia_{i}.png"))
        return quadros
    except Exception as erro:  # noqa: BLE001
        print(f"::warning::Cenas de IA: {str(erro)[:160]}")
        return []

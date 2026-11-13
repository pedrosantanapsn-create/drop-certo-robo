"""🎬 /roteiro — kit para criar o vídeo À MÃO no Gemini (app), sem desperdiçar gerações.

O bot manda: as fotos oficiais do produto (para anexar no Gemini) e os comandos (prompts) prontos,
já preenchidos com o produto — 2 de IMAGEM e 2 de VÍDEO — mais os textos para a edição.

Regra de ouro (economia): primeiro gere a IMAGEM (barata, pode refazer) com a foto do produto anexada.
Só quando a imagem estiver fiel ao produto, peça para ANIMAR aquela imagem (a geração de vídeo é a
que tem limite apertado). Nunca peça texto escrito dentro da imagem/vídeo: a IA erra as letras.

Depois: você manda o vídeo pronto para o bot com o link na legenda e ele posta com o SEU link.
"""
from __future__ import annotations

import json
from html import escape

from . import gemini
from .produto import Produto, formatar_preco

PEDIDO = """Você ajuda a criar um anúncio em vídeo vertical de um produto. Produto: "{nome}".
Responda SÓ com JSON, nestes campos:
- "produto_en": descrição visual curta do produto em inglês, máx. 30 palavras. {fonte_visual}
- "cena_uso_en": em inglês, UMA cena realista de um adulto brasileiro usando esse produto no contexto natural dele
  (onde está, o que faz com o produto, enquadramento). Máx. 40 palavras. Sem marcas de terceiros, sem telas com texto.
- "movimento_uso_en": em inglês, um movimento simples e único para animar essa cena por 8 segundos (ex.: a pessoa
  sorri e ajusta o produto; câmera aproxima devagar). Máx. 25 palavras.
- "beneficios": lista com 3 benefícios em português, cada um com no máximo 3 palavras, SEM inventar números
  ou características que não estejam no nome do produto
- "gancho": frase de abertura em português, máx. 6 palavras, sem promessa exagerada"""

PADRAO = {"produto_en": "the product from the reference photo",
          "cena_uso_en": "a young Brazilian adult naturally using the product at a tidy desk at home, medium shot, "
                         "product clearly visible in the foreground",
          "movimento_uso_en": "the person smiles and interacts gently with the product while the camera slowly pushes in",
          "beneficios": ["Qualidade", "Praticidade", "Bom preço"], "gancho": "Olha essa oferta"}

FIEL = ("Keep the product EXACTLY as in the attached reference photo: same shape, colors, proportions, buttons and "
        "brand markings. Do not redesign it, do not add or remove parts.")
SO_PRODUTO = ("Use only the main product from the reference photo; ignore any text, price tags, badges, extra "
              "accessories, hands or background that appear in that photo.")
SEM_TEXTO = "No text, no letters, no captions, no subtitles, no watermark, no extra logos anywhere in the frame."


def _detalhes(nome: str, foto=None) -> dict:
    try:
        partes, fonte_visual = [], "Sem foto: descreva o que é, com cores e formato prováveis."
        if foto:                  # o Gemini OLHA a foto: descreve o produto como ele é de verdade
            import base64
            from io import BytesIO

            from PIL import Image, ImageOps
            with Image.open(foto) as img:
                ref = ImageOps.exif_transpose(img).convert("RGB")
                ref.thumbnail((900, 900))
                buf = BytesIO()
                ref.save(buf, "JPEG", quality=85)
            partes.append({"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}})
            fonte_visual = ("Descreva o produto PRINCIPAL exatamente como aparece na foto anexada (formato, cores reais, "
                            "material, detalhes marcantes). Ignore textos, selos, brindes e acessórios extras da foto.")
        partes.append({"text": PEDIDO.format(nome=nome[:160], fonte_visual=fonte_visual)})
        dados, _ = gemini.chamar(partes, temperatura=0.5, rodadas=2)
        lido = json.loads(dados["candidates"][0]["content"]["parts"][0]["text"])
        ok = {k: (lido[k].strip().rstrip(".") if isinstance(lido[k], str) else lido[k]) for k in PADRAO if lido.get(k)}
        if isinstance(ok.get("beneficios"), list):
            ok["beneficios"] = [str(b)[:28] for b in ok["beneficios"][:3]]
        else:
            ok.pop("beneficios", None)
        return {**PADRAO, **ok}
    except Exception as erro:  # noqa: BLE001
        print(f"::warning::Roteiro (Gemini): {str(erro)[:120]}")
        return dict(PADRAO)


def kit(p: Produto, foto=None) -> dict:
    """Os comandos e textos do produto, em dados: {img1, vid1, img2, vid2, gancho, beneficios}."""
    d = _detalhes(p.nome, foto)

    img1 = (f"Create a photorealistic vertical 9:16 lifestyle advertising photo. Product: {d['produto_en']}. {FIEL} {SO_PRODUTO} "
            f"Scene: {d['cena_uso_en']}. Soft natural light, shallow depth of field, warm tones, shot on a 50mm lens, "
            f"candid and authentic (not a stock photo look). The product must be sharp and clearly visible. {SEM_TEXTO}")
    img2 = (f"Create a photorealistic vertical 9:16 premium product hero shot. Product: {d['produto_en']}. {FIEL} {SO_PRODUTO} "
            "The product alone, centered in the lower two thirds of the frame, on a dark glossy surface with soft "
            "reflections, a warm golden glow of light behind it, cinematic studio lighting, dark elegant background, "
            f"plenty of empty dark space at the top and bottom of the frame for titles added later. {SEM_TEXTO}")
    vid1 = (f"Animate this exact image into an 8-second vertical 9:16 video. {d['movimento_uso_en']}. Natural, subtle, "
            "realistic motion; smooth slow camera move; keep the person's face and the product identical to the image "
            f"for the whole clip, no morphing. {SEM_TEXTO} Audio: soft ambient sound only, no speech, no music.")
    vid2 = ("Animate this exact image into an 8-second vertical 9:16 video. Slow, smooth 20-degree orbit around the "
            "product while the light glow behind it gently pulses and reflections move on the surface. The product "
            f"stays perfectly rigid and identical to the image, no morphing, no new parts. {SEM_TEXTO} "
            "Audio: subtle cinematic whoosh only, no speech, no music.")

    return {"img1": img1, "vid1": vid1, "img2": img2, "vid2": vid2, "gancho": str(d["gancho"]),
            "beneficios": [str(x) for x in d["beneficios"]]}


def montar(p: Produto, foto=None) -> list[str]:
    """Mensagens (HTML) do kit. Os comandos vêm em blocos: toque para copiar."""
    d = kit(p, foto)
    img1, vid1, img2, vid2 = d["img1"], d["vid1"], d["img2"], d["vid2"]
    nome = escape(p.nome[:90])
    bloco = lambda t: f"<pre>{escape(t)}</pre>"  # noqa: E731
    preco = formatar_preco(p.preco) if p.preco else "confira no link"
    de = f" (antes {formatar_preco(p.preco_antigo)})" if p.preco_antigo and p.preco and p.preco_antigo > p.preco else ""
    return [
        (f"🎬 <b>Roteiro para criar à mão — {nome}</b>\n\n"
         "<b>Ordem que economiza gerações:</b>\n"
         "1. No Gemini, abra uma conversa NOVA e anexe a foto do produto que mandei como arquivo (foto_0.jpg; se "
         "vier mais de uma, use a mais limpa, com menos texto em cima).\n"
         "2. Cole o comando da <b>Imagem 1</b>. Saiu com o produto diferente do real? Peça só o conserto "
         "(\"keep everything, fix the product to match the reference photo exactly\") em vez de gerar do zero.\n"
         "3. Imagem aprovada → na MESMA conversa cole o comando do <b>Vídeo 1</b> (ele anima aquela imagem).\n"
         "4. Repita com a <b>Imagem 2</b> e o <b>Vídeo 2</b>.\n"
         "5. Junte os clipes, ponha os textos da última mensagem e me mande o vídeo pronto com o link na legenda.\n\n"
         "⚠️ Só gaste geração de VÍDEO em imagem já aprovada. Nunca peça texto dentro da imagem: a IA erra as letras."),
        "🖼️ <b>Imagem 1 — produto em uso</b> (anexe a foto do produto)\n" + bloco(img1),
        "🎞️ <b>Vídeo 1 — animar a Imagem 1</b> (na mesma conversa, depois de aprovar a imagem)\n" + bloco(vid1),
        "🖼️ <b>Imagem 2 — produto em destaque</b> (anexe a foto do produto de novo)\n" + bloco(img2),
        "🎞️ <b>Vídeo 2 — animar a Imagem 2</b>\n" + bloco(vid2),
        ("✍️ <b>Textos para pôr na edição</b> (CapCut, InShot…)\n"
         f"• Abertura: <b>{escape(str(d['gancho']))}</b>\n"
         f"• Nome: {nome}\n"
         + "".join(f"• Benefício: {escape(str(b))}\n" for b in d["beneficios"])
         + f"• Preço: <b>{escape(preco)}</b>{escape(de)} — confira o preço no dia de postar\n"
         "• Final: <b>LINK NA BIO / NO CANAL</b>\n"
         "• Obrigatório, pequeno, nas cenas de IA: <i>Imagem ilustrativa gerada por IA</i>\n\n"
         "ℹ️ Use só benefícios que são verdade para esse produto (confira no anúncio). "
         "Não ponha \"frete grátis\" nem parcelas se a loja não mostrar isso.\n\n"
         "📤 <b>Para postar:</b> me mande o VÍDEO pronto (até 20 MB) com o link do produto na legenda. "
         "Eu uso o seu vídeo no lugar do meu e posto com o seu link."),
    ]

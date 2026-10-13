"""Textos do post (legenda, gancho, narração) com o Gemini gratuito.

Se o Gemini falhar ou atingir o limite diário, o robô usa um modelo de
texto pronto — o post sai do mesmo jeito.
"""
from __future__ import annotations

import json
import re

import requests

from . import config, gemini
from .produto import Produto, formatar_preco

URL_GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
MODELOS_RESERVA = ["gemini-flash-latest", "gemini-2.5-flash", "gemini-flash-lite-latest", "gemini-2.0-flash"]

INSTRUCOES = """Você escreve posts de ofertas para o perfil "{marca}" ({arroba}),
focado em achados de informática e tecnologia com bom preço.

Produto: {nome}
Preço atual: {preco}
Preço anterior: {antigo}
Observação da dona do perfil: {obs}

Regras obrigatórias:
- Português do Brasil, tom animado e direto, sem exageros.
- NÃO invente especificações técnicas, avaliações, estoque ou prazos.
- NÃO use urgência falsa ("últimas unidades", "só hoje") — o preço pode mudar.
- NÃO cite o nome "Mercado Livre" como se fosse parceria oficial.
- O "gancho" tem no máximo 7 palavras e prende a atenção nos 2 primeiros segundos.
- "beneficios": 3 frases curtas (até 5 palavras cada) sobre para que o produto serve.
- "narracao": texto falado de 25 a 40 palavras, natural, terminando com "link na bio".
- "legenda": 2 a 4 linhas para Instagram, com 1 ou 2 emojis, sem hashtags e sem link.
- "hashtags": 5 hashtags relevantes em minúsculas, sem #publi.
- "titulo_curto": nome do produto resumido em até 6 palavras.

Responda SOMENTE com JSON válido neste formato:
{{"titulo_curto": "", "gancho": "", "beneficios": ["", "", ""], "narracao": "", "legenda": "", "hashtags": []}}"""


def _texto_padrao(p: Produto) -> dict:
    curto = " ".join(p.nome.split()[:6]) or "Achado do dia"
    preco = formatar_preco(p.preco)
    gancho = f"Achado por {preco}?" if preco else "Olha esse achado!"
    return {
        "titulo_curto": curto,
        "gancho": gancho,
        "beneficios": ["Ótimo custo-benefício", "Ideal para o seu setup", "Detalhes no link"],
        "narracao": (
            f"Olha esse achado: {curto}"
            + (f", saindo por {preco.replace('R$ ', '')} reais" if preco else "")
            + ". Confere os detalhes antes que o preço mude. O link está na bio."
        ),
        "legenda": f"🔥 Achado do dia: {p.nome}\nConfere os detalhes no link antes que o preço mude.",
        "hashtags": ["#achadinhos", "#tecnologia", "#setupgamer", "#informatica", "#oferta"],
    }


def _limpar_json(texto: str) -> dict:
    texto = re.sub(r"^```(?:json)?|```$", "", texto.strip(), flags=re.M).strip()
    inicio, fim = texto.find("{"), texto.rfind("}")
    return json.loads(texto[inicio : fim + 1])


def gerar_textos(p: Produto) -> tuple[dict, str]:
    """Retorna (textos, origem) — origem é 'gemini' ou 'modelo pronto'."""
    padrao = _texto_padrao(p)
    if not config.GEMINI_API_KEY:
        return padrao, "modelo pronto (sem chave Gemini)"

    prompt = INSTRUCOES.format(
        marca=config.MARCA,
        arroba=config.ARROBA,
        nome=p.nome,
        preco=formatar_preco(p.preco) or "não informado",
        antigo=formatar_preco(p.preco_antigo) or "não informado",
        obs=p.observacao or "nenhuma",
    )
    gerado, ultimo_erro, modelo = None, "", ""
    try:
        dados, modelo = gemini.chamar([{"text": prompt}], temperatura=0.8)
        gerado = _limpar_json(gemini.texto(dados))
    except Exception as erro:  # noqa: BLE001 — qualquer falha cai no modelo pronto
        ultimo_erro = str(erro)[:120]
    if gerado is None:
        return padrao, f"modelo pronto (Gemini falhou: {ultimo_erro})"

    for chave, valor in padrao.items():
        if not gerado.get(chave):
            gerado[chave] = valor
    gerado["beneficios"] = [b for b in gerado["beneficios"] if b][:3] or padrao["beneficios"]
    gerado["hashtags"] = [
        h if h.startswith("#") else f"#{h}" for h in gerado["hashtags"] if h.lower() != "#publi"
    ][:6]
    return gerado, f"gemini ({modelo})"


PROMPT_IMAGEM = """Esta imagem é um print ou foto de um anúncio de loja online (Amazon, Shopee, Mercado Livre etc.).
Leia o que estiver VISÍVEL e responda só com JSON:
{"nome": "nome do produto como aparece no anúncio", "preco": "preço atual", "preco_antigo": "preço riscado/antes, se houver"}
Se for só uma FOTO do produto (sem nome escrito), em "nome" descreva o produto em até 8 palavras
(ex.: "Fone de ouvido Bluetooth sem fio preto"), sem inventar marca.
Use null no que não aparecer. Não invente preços. Preços no formato 1.299,90."""


def ler_imagem(foto) -> dict:
    """Lê nome e preços de um print/foto do anúncio com o Gemini (visão, gratuito)."""
    if not config.GEMINI_API_KEY or not foto:
        return {}
    import base64
    dados_img = base64.b64encode(open(foto, "rb").read()).decode()
    try:
        dados, _ = gemini.chamar([{"text": PROMPT_IMAGEM},
                                  {"inline_data": {"mime_type": "image/jpeg", "data": dados_img}}],
                                 temperatura=0.1)
        resposta = _limpar_json(gemini.texto(dados))
        return {k: v for k, v in resposta.items() if v not in (None, "", "null")}
    except Exception:  # noqa: BLE001
        return {}


PROMPT_PAGINA = """Abra a página do produto à venda neste link de loja online{extra}:
{url}
Responda SÓ com JSON, usando apenas o que está NA PÁGINA (não invente nada):
{{"nome": "nome do produto como está no anúncio", "preco": "preço atual à vista em reais (ex.: 1.299,90)",
"preco_antigo": "preço riscado/antes, se houver", "imagem": "endereço https da foto principal do produto"}}
Use null no que não encontrar."""


def ler_pagina(link: str, url_final: str = "") -> dict:
    """Lê a página da loja pelo Gemini ("contexto de URL": o Google abre a página).

    Serve para lojas que bloqueiam o robô (Amazon, Shopee). Só aceita a resposta
    se o Google confirmar que conseguiu abrir a página — assim o Gemini não
    "chuta" preço.
    """
    if not config.GEMINI_API_KEY:
        return {}
    urls = [u for u in dict.fromkeys([link, url_final]) if u and u.startswith("http")]
    if not urls:
        return {}
    extra = f" (endereço completo: {urls[1]})" if len(urls) > 1 else ""
    try:
        dados, modelo = gemini.chamar([{"text": PROMPT_PAGINA.format(url=urls[0], extra=extra)}],
                                      temperatura=0.1, ferramentas=[{"url_context": {}}])
    except Exception:  # noqa: BLE001
        return {}
    cand = dados["candidates"][0]
    meta = cand.get("urlContextMetadata") or cand.get("url_context_metadata") or {}
    lidas = meta.get("urlMetadata") or meta.get("url_metadata") or []
    if not any("SUCCESS" in str(m.get("urlRetrievalStatus") or m.get("url_retrieval_status") or "")
               for m in lidas):
        return {}
    try:
        resposta = _limpar_json(gemini.texto(dados))
    except Exception:  # noqa: BLE001
        return {}
    resposta = {k: v for k, v in resposta.items() if v not in (None, "", "null")}
    if resposta:
        resposta["_modelo"] = modelo
    return resposta


def montar_legenda(p: Produto, t: dict, com_link: bool) -> str:
    """Legenda final. O aviso legal é colocado pelo código, nunca pela IA."""
    partes = [t["legenda"].strip(), ""]
    if p.preco:
        linha = f"💰 Por {formatar_preco(p.preco)}"
        if p.desconto:
            linha += f" (antes {formatar_preco(p.preco_antigo)} · -{p.desconto}%)"
        partes.append(linha)
    if com_link:
        partes.append(f"🛒 {p.link}")
    else:
        partes.append(f"🛒 Link na bio · {config.ARROBA}")
    partes += ["", config.AVISO_LEGAL, " ".join(t["hashtags"])]
    return "\n".join(partes).strip()

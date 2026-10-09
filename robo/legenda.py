"""Textos do post (legenda, gancho, narração) com o Gemini gratuito.

Se o Gemini falhar ou atingir o limite diário, o robô usa um modelo de
texto pronto — o post sai do mesmo jeito.
"""
from __future__ import annotations

import json
import re

import requests

from . import config
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
    # Se um modelo for desativado pelo Google (erro 404), tenta o próximo da lista
    modelos = list(dict.fromkeys([config.GEMINI_MODEL, *MODELOS_RESERVA]))
    gerado, ultimo_erro = None, ""
    for modelo in modelos:
        try:
            r = requests.post(
                URL_GEMINI.format(modelo=modelo),
                headers={"x-goog-api-key": config.GEMINI_API_KEY},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.8, "responseMimeType": "application/json"},
                },
                timeout=60,
            )
            if r.status_code == 404:
                ultimo_erro = f"modelo {modelo} indisponível"
                continue
            if r.status_code >= 300:
                ultimo_erro = f"erro {r.status_code}: {r.text[:120]}"
                break
            texto = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            gerado = _limpar_json(texto)
            break
        except Exception as erro:  # noqa: BLE001 — qualquer falha cai no modelo pronto
            ultimo_erro = str(erro)[:120]
            break
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

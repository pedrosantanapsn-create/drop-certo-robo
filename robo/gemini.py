"""Chamada ao Gemini (gratuito) com tolerância a falhas.

O Google às vezes responde 503 ("muita procura") ou 429 (limite). Em vez de
desistir, o robô tenta outro modelo e, se todos estiverem ocupados, espera um
pouco e tenta de novo (até 3 rodadas).
"""
from __future__ import annotations

import time

import requests

from . import config

URL = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
MODELOS = [
    "gemini-flash-latest", "gemini-flash-lite-latest", "gemini-3.5-flash", "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite", "gemini-2.5-flash", "gemini-2.5-flash-lite",
]
_mortos: set[str] = set()       # modelos que o Google desligou (404) nesta rodada


class GeminiFalhou(RuntimeError):
    pass


def chamar(partes: list[dict], *, json_saida: bool = True, temperatura: float = 0.4,
           ferramentas: list | None = None, pensar: bool | None = None,
           rodadas: int = 3, timeout: int = 90) -> tuple[dict, str]:
    """Devolve (resposta completa do Gemini, modelo usado) ou levanta GeminiFalhou."""
    if not config.GEMINI_API_KEY:
        raise GeminiFalhou("sem chave do Gemini")
    ultimo = ""
    modelos = [m for m in dict.fromkeys([config.GEMINI_MODEL, *MODELOS]) if m]
    for rodada in range(rodadas):
        for modelo in modelos:
            if modelo in _mortos:
                continue
            cfg: dict = {"temperature": temperatura}
            if json_saida and not ferramentas:
                cfg["responseMimeType"] = "application/json"
            if pensar is False:
                cfg["thinkingConfig"] = {"thinkingBudget": 0}
            corpo: dict = {"contents": [{"parts": partes}], "generationConfig": cfg}
            if ferramentas:
                corpo["tools"] = ferramentas
            try:
                r = requests.post(URL.format(modelo=modelo), json=corpo, timeout=timeout,
                                  headers={"x-goog-api-key": config.GEMINI_API_KEY})
                if r.status_code == 400 and "thinking" in r.text.lower() and "thinkingConfig" in cfg:
                    cfg.pop("thinkingConfig")
                    r = requests.post(URL.format(modelo=modelo), json=corpo, timeout=timeout,
                                      headers={"x-goog-api-key": config.GEMINI_API_KEY})
            except requests.RequestException as erro:
                ultimo = f"{modelo}: {type(erro).__name__}"
                continue
            if r.status_code == 404:
                _mortos.add(modelo)
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                ultimo = f"{modelo}: ocupado ({r.status_code})"
                continue
            if r.status_code >= 300:
                ultimo = f"{modelo}: erro {r.status_code} {r.text[:100]}"
                continue
            dados = r.json()
            if not dados.get("candidates"):
                ultimo = f"{modelo}: resposta vazia"
                continue
            return dados, modelo
        if rodada < rodadas - 1:
            time.sleep(8 * (rodada + 1))      # todos ocupados: espera e tenta de novo
    raise GeminiFalhou(ultimo or "nenhum modelo respondeu")


def texto(dados: dict) -> str:
    partes = dados["candidates"][0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in partes)

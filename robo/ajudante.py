"""Ajudante do PC — lado do robô.

O Mercado Livre só gera o meli.la (o link que conta a comissão) para quem está logada.
O "ajudante" é um programa no PC da dona: ele usa o Edge logado na conta dela, gera o
meli.la de cada produto pedido e devolve aqui. O robô do GitHub:

  1. pede:      ajudante.pedir("ml:MLB123", url_do_produto, {"texto": oferta})
  2. o ajudante (quando o PC está ligado) gera o meli.la e marca o pedido como "pronto";
  3. importa:   ajudante.importar() põe a oferta na fila com o meli.la dela.

Tabela: ajudante_pedidos (ver supabase/ajudante.sql). Desligar: variável AJUDANTE=false.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

from . import config, fila, supabase

TABELA = "ajudante_pedidos"
VIVO_MINUTOS = 20           # ajudante "ligado" = deu sinal nos últimos minutos
VALIDADE_HORAS = 48         # pedido que ninguém atendeu nesse tempo é descartado


def ativo() -> bool:
    return bool(config.AJUDANTE and supabase.ativo())


def _url() -> str:
    return f"{config.SUPABASE_URL}/rest/v1/{TABELA}"


def _ler(params: dict) -> list[dict]:
    r = requests.get(_url(), headers=supabase._cabecalhos(), params=params, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"ajudante: Supabase {r.status_code} {r.text[:120]}")
    return r.json()


def _mudar(ident: str, campos: dict) -> None:
    r = requests.patch(_url(), headers=supabase._cabecalhos({"Content-Type": "application/json",
                                                             "Prefer": "return=minimal"}),
                       params={"id": f"eq.{ident}"}, json=campos, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"ajudante: Supabase {r.status_code} {r.text[:120]}")


def sinal() -> dict | None:
    """Último sinal de vida do ajudante: {'quando': datetime, 'precisa_login': bool} ou None."""
    linhas = _ler({"chave": "eq._batimento", "select": "feito_em,dados"})
    if not linhas or not linhas[0].get("feito_em"):
        return None
    quando = datetime.fromisoformat(str(linhas[0]["feito_em"]).replace("Z", "+00:00"))
    return {"quando": quando, "precisa_login": bool((linhas[0].get("dados") or {}).get("precisa_login"))}


def ligado() -> bool:
    try:
        s = sinal()
    except Exception:  # noqa: BLE001
        return False
    return bool(s and datetime.now(timezone.utc) - s["quando"] < timedelta(minutes=VIVO_MINUTOS))


def usado_recentemente(dias: int = 3) -> bool:
    """O ajudante deu sinal nos últimos dias? (só então vale pedir links para a fila automática)"""
    try:
        s = sinal()
    except Exception:  # noqa: BLE001
        return False
    return bool(s and datetime.now(timezone.utc) - s["quando"] < timedelta(days=dias))


def pedir(chave: str, url: str, dados: dict, loja: str = "ml") -> bool:
    """Cria o pedido (se já existe um igual, não repete). True = pedido novo criado."""
    r = requests.post(_url(), headers=supabase._cabecalhos({
        "Content-Type": "application/json", "Prefer": "resolution=ignore-duplicates,return=representation"}),
        params={"on_conflict": "chave"}, json={"loja": loja, "chave": chave, "url": url, "dados": dados},
        timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"ajudante: Supabase {r.status_code} {r.text[:120]}")
    return bool(r.json())


def pendentes() -> int:
    return len(_ler({"status": "eq.pendente", "loja": "neq._sistema", "select": "id"}))


def importar(avisar) -> int:
    """Põe na fila as ofertas cujo link o ajudante já gerou; avisa erros e pedido de login."""
    if not ativo():
        return 0
    postas = 0
    for p in _ler({"status": "eq.pronto", "select": "id,chave,url,link,dados", "order": "feito_em.asc",
                   "limit": "20"}):
        dados = p.get("dados") or {}
        texto = str(dados.get("texto") or p["url"])
        original = str(dados.get("link_original") or p["url"])
        texto = texto.replace(original, p["link"]) if original in texto else f"{p['link']}\n{texto}"
        fila.adicionar([texto])
        _mudar(p["id"], {"status": "importado"})
        postas += 1
    if postas:
        avisar(f"🧩 O ajudante gerou {postas} link(s) meli.la seu(s) — já estão na fila. /fila para ver.")

    for p in _ler({"status": "eq.erro", "loja": "neq._sistema", "select": "id,url,erro", "limit": "10"}):
        avisar(f"🧩 O ajudante não conseguiu gerar o link de:\n{p['url']}\nMotivo: {str(p.get('erro'))[:200]}\n"
               "Gere o meli.la no app e mande para mim.")
        _mudar(p["id"], {"status": "avisado"})

    limite = (datetime.now(timezone.utc) - timedelta(hours=VALIDADE_HORAS)).isoformat()
    velhos = _ler({"status": "eq.pendente", "loja": "neq._sistema", "criado_em": f"lt.{limite}", "select": "id"})
    for p in velhos:
        _mudar(p["id"], {"status": "vencido"})

    # O ajudante avisou que caiu o login do Mercado Livre: avisa a dona 1 vez por dia
    try:
        s = sinal()
        if s and s["precisa_login"]:
            hoje = datetime.now(fila.FUSO).strftime("%Y-%m-%d")
            if (supabase.ler_config("ajudante_aviso_login") or {}).get("valor") != hoje:
                supabase.gravar_config("ajudante_aviso_login", hoje)
                avisar("🧩 O ajudante do PC perdeu o login do Mercado Livre.\nNo PC, abra \"2 - Fazer login.bat\", "
                       "entre na sua conta e depois ligue o ajudante de novo.")
    except Exception as erro:  # noqa: BLE001
        print("Ajudante (sinal):", erro)
    return postas

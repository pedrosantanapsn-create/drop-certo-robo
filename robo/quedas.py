"""Aviso automático de QUEDA DE PREÇO no canal do Telegram.

Na conferência diária (6h), quando um produto do site — Mercado Livre ou
Shopee, que têm preço pela API oficial — fica X% mais barato (padrão 10%), o
robô guarda um aviso. Os avisos saem no canal a partir das 10h, um a cada
30 min, com o SEU link de afiliado que já está no site.

Cada produto só ganha aviso de novo depois de 7 dias (para não repetir).
Configuração (variáveis do GitHub, opcionais):
  QUEDA_MINIMA  -> % mínima de queda para avisar (padrão 10)
  AVISAR_QUEDAS -> false para desligar
"""
from __future__ import annotations

import json
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

from . import config, rastreio, supabase, telegram
from .fila import FUSO
from .produto import formatar_preco

CHAVE_PENDENTES = "quedas_pendentes"
CHAVE_AVISADAS = "quedas_avisadas"
CHAVE_PROXIMA = "quedas_proxima"
INTERVALO_MIN = 30
DIAS_SEM_REPETIR = 7


def _ler(chave: str, padrao):
    try:
        return json.loads((supabase.ler_config(chave) or {}).get("valor") or json.dumps(padrao))
    except ValueError:
        return padrao


def _proximo_horario(agora: datetime) -> datetime:
    """Próximo horário dentro da janela de posts (10h–23h)."""
    if agora.hour < config.POSTAR_DAS:
        return agora.replace(hour=config.POSTAR_DAS, minute=0, second=0, microsecond=0)
    if agora.hour >= config.POSTAR_ATE:
        return (agora + timedelta(days=1)).replace(hour=config.POSTAR_DAS, minute=0, second=0, microsecond=0)
    return agora


def registrar(produto: dict, preco_site: float, preco_novo: float, preco_de: float | None) -> bool:
    """Chamado pela conferência quando o preço caiu. Devolve True se virou aviso."""
    if not (config.AVISAR_QUEDAS and config.CANAL_ID and preco_site and preco_novo):
        return False
    queda = (1 - preco_novo / float(preco_site)) * 100
    if queda < config.QUEDA_MINIMA:
        return False
    ident = str(produto.get("id"))
    avisadas = _ler(CHAVE_AVISADAS, {})
    if time.time() - float(avisadas.get(ident, 0)) < DIAS_SEM_REPETIR * 86400:
        return False
    pendentes = [p for p in _ler(CHAVE_PENDENTES, []) if str(p.get("id")) != ident]
    pendentes.append({
        "id": ident, "nome": str(produto.get(config.COL_NOME) or "")[:120],
        "antes": round(float(preco_site), 2), "agora": round(preco_novo, 2),
        "de": round(preco_de, 2) if preco_de and preco_de > preco_novo else None,
        "queda": round(queda), "link": produto.get(config.COL_LINK),
        "imagem": produto.get(config.COL_IMAGEM), "visto": datetime.now(FUSO).strftime("%d/%m às %Hh%M"),
    })
    supabase.gravar_config(CHAVE_PENDENTES, json.dumps(pendentes, ensure_ascii=False))
    avisadas[ident] = int(time.time())
    # limpa registros muito antigos
    avisadas = {k: v for k, v in avisadas.items() if time.time() - float(v) < 30 * 86400}
    supabase.gravar_config(CHAVE_AVISADAS, json.dumps(avisadas))
    proxima = _proximo_horario(datetime.now(FUSO))
    atual = str((supabase.ler_config(CHAVE_PROXIMA) or {}).get("valor", ""))
    if not atual.isdigit() or int(atual) > proxima.timestamp():
        supabase.gravar_config(CHAVE_PROXIMA, str(int(proxima.timestamp())))
    return True


def legenda(a: dict) -> str:
    linhas = ["⬇️ BAIXOU O PREÇO!", a["nome"], "",
              f"Antes: {formatar_preco(a['antes'])}",
              f"Agora: {formatar_preco(a['agora'])}  (-{a['queda']}%)"]
    if a.get("de"):
        linhas.append(f"Preço cheio na loja: {formatar_preco(a['de'])}")
    linhas += [f"🛒 {a['link']}", "",
               f"Preço visto em {a['visto']} — pode mudar a qualquer momento.",
               config.AVISO_LEGAL]
    return "\n".join(linhas)


def postar_se_for_hora(avisar_admin=None) -> bool:
    """Posta UM aviso pendente por rodada (a cada 30 min), só dentro da janela de posts."""
    if not (supabase.ativo() and config.CANAL_ID):
        return False
    valor = str((supabase.ler_config(CHAVE_PROXIMA) or {}).get("valor", ""))
    agora = datetime.now(FUSO)
    if not valor.isdigit() or agora.timestamp() < int(valor):
        return False
    if not (config.POSTAR_DAS <= agora.hour < config.POSTAR_ATE):
        supabase.gravar_config(CHAVE_PROXIMA, str(int(_proximo_horario(agora).timestamp())))
        return False
    pendentes = _ler(CHAVE_PENDENTES, [])
    if not pendentes:
        supabase.gravar_config(CHAVE_PROXIMA, "")
        return False
    aviso = pendentes.pop(0)
    supabase.gravar_config(CHAVE_PENDENTES, json.dumps(pendentes, ensure_ascii=False))
    supabase.gravar_config(CHAVE_PROXIMA, str(int((agora + timedelta(minutes=INTERVALO_MIN)).timestamp()))
                           if pendentes else "")
    texto = legenda(aviso)
    try:
        if aviso.get("imagem"):
            with tempfile.TemporaryDirectory() as pasta:
                foto = Path(pasta) / "foto.jpg"
                r = requests.get(aviso["imagem"], timeout=30)
                r.raise_for_status()
                foto.write_bytes(r.content)
                telegram.enviar_foto(config.CANAL_ID, foto, rastreio.legenda_html(
                    texto, aviso["link"], aviso["id"], aviso["nome"]), html=True)
        else:
            telegram.enviar_html(config.CANAL_ID, rastreio.legenda_html(texto, aviso["link"], aviso["id"], aviso["nome"]))
        if avisar_admin:
            avisar_admin(f"⬇️ Aviso de queda publicado no canal: {aviso['nome'][:60]} "
                         f"({formatar_preco(aviso['antes'])} → {formatar_preco(aviso['agora'])})")
    except Exception as erro:  # noqa: BLE001
        print(f"::warning::Aviso de queda: {str(erro)[:150]}")
    return True

"""Modo instantâneo: o robô começa a trabalhar no mesmo segundo em que você
manda a mensagem, em vez de esperar a rodada de 10 em 10 minutos.

Como funciona:
  Telegram ──(webhook)──> função "telegram-robo" no Supabase ──> GitHub Actions
  A função confere a senha do Telegram e se a mensagem é sua, e manda o GitHub
  rodar o robô já com a mensagem dentro (entrada "update").

Ligar:  /instantaneo on    Desligar: /instantaneo off  (volta ao modo de 10 min)

A senha do webhook e o seu ID ficam na tabela "config" do Supabase; a função lê
de lá. O único segredo que você cola à mão é o token do GitHub, nos segredos
da função no Supabase (GITHUB_TOKEN_ROBO).
"""
from __future__ import annotations

import secrets

import requests

from . import config, supabase, telegram

NOME_FUNCAO = "telegram-robo"
CHAVE_SEGREDO = "telegram_webhook_secret"
CHAVE_ADMIN = "admin_chat_id"


def url_funcao() -> str:
    return f"{config.SUPABASE_URL}/functions/v1/{NOME_FUNCAO}"


def estado() -> str:
    info = telegram._chamar("getWebhookInfo")
    if info.get("url") == url_funcao():
        erro = info.get("last_error_message")
        pendentes = info.get("pending_update_count", 0)
        extra = f"\n⚠️ Último erro: {erro}" if erro else ""
        return f"⚡ Modo instantâneo LIGADO ({pendentes} mensagem(ns) esperando){extra}"
    if info.get("url"):
        return f"ℹ️ Webhook apontando para outro lugar: {info['url']}"
    return "🕙 Modo de 10 em 10 minutos (instantâneo desligado). Use /instantaneo on"


def ligar() -> str:
    if not supabase.ativo():
        return "❌ Precisa do Supabase configurado."
    # A função existe e está protegida? Sem a senha ela deve recusar (401/403).
    try:
        teste = requests.post(url_funcao(), json={}, timeout=20)
    except requests.RequestException as erro:
        return f"❌ Não consegui falar com a função {NOME_FUNCAO}: {str(erro)[:120]}"
    if teste.status_code == 404:
        return f"❌ A função '{NOME_FUNCAO}' ainda não existe no Supabase."
    if teste.status_code != 401 or "acesso negado" not in teste.text:
        return (f"❌ A função respondeu {teste.status_code} ({teste.text[:80]}) — confira o código e a "
                "opção \"Verify JWT\" (deve ficar DESLIGADA).")
    segredo = secrets.token_urlsafe(32)
    supabase.gravar_config(CHAVE_SEGREDO, segredo)
    supabase.gravar_config(CHAVE_ADMIN, str(config.ADMIN_CHAT_ID))
    telegram._chamar("setWebhook", url=url_funcao(), secret_token=segredo,
                     allowed_updates='["message"]', drop_pending_updates="false", max_connections=5)
    return ("⚡ Modo instantâneo LIGADO!\n"
            "Mande um link: o robô começa na hora (o vídeo fica pronto em ~2 min).\n"
            "Para voltar ao modo de 10 min: /instantaneo off")


def desligar() -> str:
    telegram._chamar("deleteWebhook", drop_pending_updates="false")
    if supabase.ativo():
        supabase.gravar_config(CHAVE_SEGREDO, "")
    return "🕙 Modo instantâneo DESLIGADO. O robô volta a conferir de 10 em 10 minutos."

"""Alertas imediatos no Telegram quando algo se desconecta ou para de funcionar.

• Depois de cada post: se Instagram, Story, TikTok, canal, site, voz ou as APIs
  da Shopee/Mercado Livre deram erro, você recebe uma mensagem própria (não só
  no resumo do post).
• Uma vez por dia (junto com a conferência das 6h): checagem de saúde —
  Zernio (Instagram e TikTok conectados), Mercado Livre (autorização) e Shopee.

O mesmo problema só é avisado de novo depois de 6 horas (para não encher o chat).
"""
from __future__ import annotations

import json
import time

from . import config, mercadolivre, shopee, supabase, telegram, zernio

CHAVE = "alertas_enviados"
REPETIR_H = 6

# (começo da linha de status, nome do problema, dica)
ERROS_DO_POST = [
    ("• Instagram: erro", "Instagram (Reels)", "Mande /instagram para conferir a conexão no Zernio."),
    ("• Story no Instagram: erro", "Story do Instagram", "Mande /instagram para conferir a conexão no Zernio."),
    ("• TikTok: erro", "TikTok", "Mande /tiktok para conferir a conexão no Zernio."),
    ("• Canal: erro", "canal do Telegram", "Confira se o bot ainda é administrador do canal."),
    ("• Site: erro", "site", "Mande /colunas para conferir a tabela do site."),
    ("• Vídeo falhou", "vídeo", "O post saiu sem vídeo; se repetir, me avise."),
    ("• API da Shopee:", "API da Shopee", "Pode ser a senha da API expirada (painel de afiliados da Shopee)."),
    ("• API do Mercado Livre:", "API do Mercado Livre", "Mande /ml para autorizar de novo."),
]
IGNORAR = ("não devolveu esse produto", "não achei o código", "só produtos de catálogo")


def _enviados() -> dict:
    try:
        return json.loads((supabase.ler_config(CHAVE) or {}).get("valor") or "{}")
    except ValueError:
        return {}


def avisar(chave: str, texto: str) -> bool:
    """Manda o alerta para você, no máximo 1 vez a cada 6 h por problema."""
    if not config.ADMIN_CHAT_ID:
        return False
    enviados = _enviados() if supabase.ativo() else {}
    if time.time() - float(enviados.get(chave, 0)) < REPETIR_H * 3600:
        return False
    try:
        telegram.enviar_texto(config.ADMIN_CHAT_ID, "🚨 " + texto)
    except Exception:  # noqa: BLE001
        return False
    if supabase.ativo():
        enviados[chave] = int(time.time())
        supabase.gravar_config(CHAVE, json.dumps(enviados))
    return True


def depois_do_post(status: list[str]) -> None:
    for linha in status:
        for inicio, nome, dica in ERROS_DO_POST:
            if linha.startswith(inicio) and not any(i in linha for i in IGNORAR):
                detalhe = linha.split(":", 1)[-1].strip().removeprefix("erro — ")[:180]
                avisar(f"post:{nome}", f"Problema no {nome}: {detalhe}\n\n👉 {dica}")
        if linha.startswith("• Vídeo: pronto (sem narração"):
            avisar("post:voz", "O vídeo saiu SEM narração (a voz falhou).\n"
                   f"{linha[2:200]}\n\n👉 Se repetir, me avise.")


def checar_saude() -> list[str]:
    """Checagem diária das conexões. Devolve a lista de problemas (e avisa)."""
    problemas = []
    if zernio.ativo():
        try:
            plataformas = {c.get("platform") for c in zernio.contas() if c.get("isActive", True)}
            for rede, nome in (("instagram", "Instagram"), ("tiktok", "TikTok")):
                if rede not in plataformas:
                    problemas.append(f"{nome} desconectado no Zernio — reconecte em zernio.com")
        except Exception as erro:  # noqa: BLE001
            problemas.append(f"Zernio não respondeu: {str(erro)[:120]} (a chave pode ter mudado)")
    if mercadolivre.configurado():
        try:
            if not mercadolivre.token():
                problemas.append("Mercado Livre sem autorização — mande /ml")
        except Exception as erro:  # noqa: BLE001
            problemas.append(f"Mercado Livre recusou o acesso: {str(erro)[:120]} — mande /ml")
    if shopee.ativo():
        try:
            shopee.buscar("mouse", limite=1)
        except Exception as erro:  # noqa: BLE001
            problemas.append(f"API da Shopee com erro: {str(erro)[:120]}")
    for p in problemas:
        avisar(f"saude:{p[:30]}", p)
    return problemas

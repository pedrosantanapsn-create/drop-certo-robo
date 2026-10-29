"""Bot de busca para os seguidores (@Dropcerto22bot no privado).

A pessoa manda, por exemplo, "ssd 1tb até 300" ou "fone com dongle até 200" e
o robô responde com as 3 melhores opções de custo-benefício (Shopee + Mercado
Livre), já com o SEU link de afiliada (na Shopee marcado "bot", para o relatório
de vendas mostrar quanto o bot vende).

Segurança: estranhos só conseguem buscar — nenhum comando seu funciona para eles.
Limites: BUSCAS_POR_HORA por pessoa e BUSCAS_POR_DIA no total (protege as APIs).
LGPD: o robô não guarda nome nem conversa; para o limite guarda só um código
embaralhado (hash) do chat, apagado no dia seguinte.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime
from html import escape

from . import config, ranking, supabase, telegram
from .fila import FUSO
from .produto import formatar_preco

CHAVE_USO = "busca_uso"
PALAVRAS_VAZIAS = {
    "quero", "queria", "procuro", "procurando", "preciso", "busco", "buscar", "me", "indica", "indique",
    "recomenda", "recomende", "sugere", "sugira", "um", "uma", "uns", "umas", "o", "a", "os", "as", "de", "do",
    "da", "para", "pra", "pro", "bom", "boa", "bons", "boas", "barato", "barata", "melhor", "algum", "alguma",
    "tem", "voce", "você", "vc", "por", "favor", "pf", "pfv", "oi", "ola", "olá", "custo", "beneficio",
    "benefício", "que", "seja", "mais", "e", "no", "na", "maximo", "máximo", "reais", "real",
}

BOAS_VINDAS = """👋 Oi! Eu sou o robô do <b>Drop Certo</b>.

Me diga o que você procura e o seu limite de preço, que eu acho as 3 melhores opções de custo-benefício na Shopee e no Mercado Livre. Exemplos:

• <code>ssd 1tb até 300</code>
• <code>fone com dongle até 200</code>
• <code>mouse gamer sem fio até 150</code>
• <code>memória ddr4 16gb até 250</code>

📢 Ofertas todo dia no canal: @DropCerto22
🌐 Site: {site}"""

RODAPE = ("<i>(ANÚNCIO) Links de afiliado: posso ganhar comissão, sem custo extra para você. "
          "Preços vistos agora, podem mudar — confira na loja. Garantia e entrega são com a loja.</i>")


def _hash(chat_id) -> str:
    return hashlib.sha256(f"dropcerto:{chat_id}".encode()).hexdigest()[:12]


def _limite(chat_id) -> str:
    """'' se pode buscar; senão o motivo. Já conta a busca."""
    if not supabase.ativo():
        return ""
    hoje = datetime.now(FUSO).strftime("%y%m%d")
    try:
        uso = json.loads((supabase.ler_config(CHAVE_USO) or {}).get("valor") or "{}")
    except ValueError:
        uso = {}
    if uso.get("dia") != hoje:
        uso = {"dia": hoje, "total": 0, "pessoas": {}}
    agora = time.time()
    pessoa = [t for t in uso["pessoas"].get(_hash(chat_id), []) if agora - t < 3600]
    if uso["total"] >= config.BUSCAS_POR_DIA:
        return "Hoje já fiz muitas buscas 😅 Tente amanhã — e veja as ofertas do dia no canal @DropCerto22."
    if len(pessoa) >= config.BUSCAS_POR_HORA:
        return f"Você já fez {config.BUSCAS_POR_HORA} buscas nesta hora. Tente de novo daqui a pouco 🙂"
    pessoa.append(agora)
    uso["pessoas"][_hash(chat_id)] = pessoa
    uso["total"] += 1
    supabase.gravar_config(CHAVE_USO, json.dumps(uso, separators=(",", ":")))
    return ""


def entender(texto: str) -> tuple[str, float | None, list[str]]:
    """'quero um fone bom com dongle até 200 reais' -> ('fone', 200, ['dongle'])"""
    texto = texto.lower().replace("r$", " ")
    texto = re.sub(r"\b(?:no m[aá]ximo|max(?:imo)?|por|abaixo de|menos de)\s+(\d)", r"até \1", texto)
    texto = re.sub(r"[?!.;]", " ", texto)
    palavra, teto, requisitos = ranking.separar_pedido(texto)
    limpa = " ".join(p for p in palavra.split() if p not in PALAVRAS_VAZIAS)
    requisitos = [" ".join(p for p in r.split() if p not in PALAVRAS_VAZIAS) for r in requisitos]
    return limpa.strip(), teto, [r for r in requisitos if r]


def responder(mensagem: dict) -> None:
    chat = mensagem.get("chat") or {}
    if chat.get("type") != "private" or not config.BUSCA_PUBLICA:
        return
    chat_id = chat["id"]
    texto = (mensagem.get("text") or "").strip()
    if not texto:
        return
    if texto.startswith("/") or len(texto) > 120:
        telegram.enviar_html(chat_id, BOAS_VINDAS.format(site=escape(config.SITE_URL)))
        return
    palavra, teto, requisitos = entender(texto)
    if not palavra or len(palavra) < 3:
        telegram.enviar_html(chat_id, BOAS_VINDAS.format(site=escape(config.SITE_URL)))
        return
    motivo = _limite(chat_id)
    if motivo:
        telegram.enviar_texto(chat_id, motivo)
        return
    desc = palavra + (f" com {', '.join(requisitos)}" if requisitos else "") + (f" até R$ {int(teto)}" if teto else "")
    telegram.enviar_texto(chat_id, f"🔎 Procurando {desc}… (leva uns segundos)")
    try:
        itens = ranking.buscar_custo(palavra, teto, requisitos, quantos=3, sub_id="bot", minimo=1)
    except Exception as erro:  # noqa: BLE001
        print(f"::warning::Busca pública: {str(erro)[:200]}")
        itens = []
    if not itens:
        telegram.enviar_texto(chat_id, "Não achei opções boas para isso agora 😕\n\nTente escrever só o produto "
                              "e o preço (ex.: \"ssd 1tb até 300\") ou aumente um pouco o limite.")
        return
    medalhas = ["🥇", "🥈", "🥉"]
    linhas = [f"✅ <b>Melhores opções: {escape(desc)}</b>", ""]
    for i, it in enumerate(itens[:3]):
        linhas.append(f"{medalhas[i]} <b>{escape(str(it['nome'])[:90])}</b>")
        extra = f"⭐ {it['nota']:.1f} · " if it.get("nota") else ""
        linhas.append(f"💰 {formatar_preco(it['preco'])} · {extra}{escape(it['loja'])}")
        if it.get("motivo"):
            linhas.append(f"↳ {escape(it['motivo'])}")
        linhas.append(f'🛒 <a href="{escape(str(it["link"]))}">Ver na {escape(it["loja"])}</a>')
        linhas.append("")
    linhas += ["📢 Mais ofertas no canal @DropCerto22", "", RODAPE]
    telegram.enviar_html(chat_id, "\n".join(linhas))

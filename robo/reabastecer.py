"""Fila automática: quando a fila de posts acaba, o robô coloca ofertas novas sozinho.

• Shopee: produtos que vendem bem, nota alta e boa comissão, já com o SEU link
  de afiliada (gerado pela API oficial).
• Mercado Livre: mais vendidos com desconto real (API oficial), com o SEU código
  de afiliada (matt_word/matt_tool dos seus links meli.la).
• Só marcas conhecidas (AMD, Kingston, Logitech, Rise Mode…); prioridade para peças de PC
  e para o que está no menor preço em 30 dias; nunca repete produto já sugerido.

Só reabastece dentro da janela de posts (10h–23h) e no máximo a cada 2 horas.
Você recebe no Telegram a lista do que entrou — /limpar cancela tudo.
Desligar: variável FILA_AUTOMATICA = false no GitHub.
"""
from __future__ import annotations

import json
import time
from itertools import zip_longest
from datetime import datetime, timedelta

from . import awin, config, fila, marcas, mercadolivre, nota, precos, shopee, sugestoes, supabase
from .produto import Produto, formatar_preco

CHAVE = "reabastecer_proximo"
INTERVALO_MIN_H = 2


def _nota_previa(nome: str, preco: float | None, desconto: float, chave: str, extras: dict) -> int:
    """Nota da oferta já na hora de pôr na fila (no pico o robô posta a de maior nota primeiro)."""
    antigo = round(preco / (1 - desconto / 100), 2) if preco and 0 < desconto < 95 else None
    p = Produto(link="", nome=nome, preco=preco, preco_antigo=antigo)
    info = precos.analise(chave, preco) if chave else {}
    falso = bool(nota.desconto_falso(p, info))
    return nota.calcular(p, info, extras, falso=falso)[0]


def agendar(daqui_min: int = 20) -> None:
    """Marca a próxima tentativa (chamado quando a fila esvazia)."""
    if not (config.FILA_AUTOMATICA and supabase.ativo()):
        return
    alvo = datetime.now(fila.FUSO) + timedelta(minutes=daqui_min)
    if alvo.hour < config.POSTAR_DAS:
        alvo = alvo.replace(hour=config.POSTAR_DAS, minute=0)
    elif alvo.hour >= config.POSTAR_ATE - 1:
        alvo = (alvo + timedelta(days=1)).replace(hour=config.POSTAR_DAS, minute=0)
    supabase.gravar_config(CHAVE, str(int(alvo.timestamp())))


def se_for_hora(enviar) -> int:
    """Reabastece se a fila estiver vazia e chegou a hora. Devolve quantas ofertas entraram."""
    if not (config.FILA_AUTOMATICA and supabase.ativo() and fila.ativa()):
        return 0
    valor = str((supabase.ler_config(CHAVE) or {}).get("valor", ""))
    if not valor.isdigit() or time.time() < int(valor):
        return 0
    if fila.itens():
        supabase.gravar_config(CHAVE, "")          # ainda tem fila: nada a fazer
        return 0
    agora = datetime.now(fila.FUSO)
    if not (config.POSTAR_DAS <= agora.hour < config.POSTAR_ATE - 1):
        agendar(0)
        return 0
    # tenta de novo em 2 h se não achar nada agora
    supabase.gravar_config(CHAVE, str(int(time.time() + INTERVALO_MIN_H * 3600)))

    textos, linhas = [], []
    if shopee.ativo() and config.FILA_AUTO_SHOPEE:
        try:
            for n in sugestoes.buscar_shopee(quantas=config.FILA_AUTO_SHOPEE, so_marca=True):
                if n.get("_link"):
                    preco = sugestoes._num(n.get("priceMin"), None)
                    pontos = _nota_previa(str(n.get("productName", "")), preco,
                                          sugestoes._num(n.get("priceDiscountRate")), n.get("_id", ""),
                                          {"comissao": sugestoes._num(n.get("commissionRate"), None),
                                           "nota_loja": sugestoes._num(n.get("ratingStar"), None),
                                           "vendas": sugestoes._num(n.get("sales"), None)})
                    textos.append(f"{n['_link']}\norigem: auto\nnota: {pontos}")
                    linhas.append(f"🛍️ {str(n.get('productName', ''))[:55]} — {formatar_preco(preco)} · nota {pontos}")
        except Exception as erro:  # noqa: BLE001
            print(f"::warning::Fila automática Shopee: {str(erro)[:150]}")
    if mercadolivre.ativo() and config.FILA_AUTO_ML and config.ML_MATT_WORD:
        try:
            for n in sugestoes.buscar_ml(quantas=config.FILA_AUTO_ML, so_marca=True):
                pontos = _nota_previa(str(n["nome"]), n["preco"], float(n.get("desconto") or 0),
                                      n.get("_id", ""), {})
                textos.append(f"{n['link']}\norigem: auto\nnota: {pontos}")
                linhas.append(f"🛒 {str(n['nome'])[:55]} — {formatar_preco(n['preco'])} "
                              f"(-{round(n['desconto'])}%) · nota {pontos}")
        except Exception as erro:  # noqa: BLE001
            print(f"::warning::Fila automática ML: {str(erro)[:150]}")
    if awin.feed_ativo() and config.FILA_AUTO_AWIN:
        try:
            ja = set(sugestoes._vistas())
            escolhidos = []
            for palavra in [p.strip() for p in config.PALAVRAS_AWIN.split(",") if p.strip()]:
                for it in awin.buscar_produtos(palavra, limite=3):
                    chave = f"awin:{it['id']}"
                    if chave in ja or not (it["desconto"] >= 10 and (it["marca"] or marcas.conhecida(it["nome"]))):
                        continue
                    ja.add(chave)
                    escolhidos.append((chave, it))
                    break
                if len(escolhidos) >= config.FILA_AUTO_AWIN:
                    break
            for chave, it in escolhidos:
                pontos = _nota_previa(it["nome"], it["preco"], float(it["desconto"]), chave, {})
                textos.append(f"{awin.texto_fila(it)}\norigem: auto\nnota: {pontos}")
                linhas.append(f"🏬 {it['nome'][:55]} — {formatar_preco(it['preco'])} (-{it['desconto']}%) "
                              f"· {it['loja']} · nota {pontos}")
            if escolhidos and supabase.ativo():
                supabase.gravar_config(sugestoes.CHAVE_VISTAS,
                                       json.dumps((sugestoes._vistas() + [c for c, _ in escolhidos])[-400:]))
        except Exception as erro:  # noqa: BLE001
            print(f"::warning::Fila automática Awin: {str(erro)[:150]}")
    if not textos:
        enviar("🤖 A fila acabou e não achei ofertas novas boas agora. Tento de novo em 2 h "
               "(ou mande links / use /ofertas_pc).")
        return 0
    # intercala as lojas para variar o feed
    grupos: dict[str, list[int]] = {}
    for i, linha in enumerate(linhas):            # 🛍️ Shopee · 🛒 Mercado Livre · 🏬 KaBuM (Awin)
        grupos.setdefault(linha.split(" ", 1)[0], []).append(i)
    ordem = [i for rodada in zip_longest(*grupos.values()) for i in rodada if i is not None]
    textos = [textos[i] for i in ordem]
    linhas = [linhas[i] for i in ordem]
    total, proxima, ignorados = fila.adicionar(textos)
    supabase.gravar_config(CHAVE, "")
    enviar("🤖 A fila tinha acabado — coloquei ofertas novas sozinho "
           f"({len(textos) - ignorados}):\n\n" + "\n".join(linhas) +
           f"\n\n⏰ Próximo post: {proxima.strftime('%d/%m às %H:%M')}\n"
           f"No pico sai primeiro a de maior nota; nota abaixo de {config.NOTA_MINIMA} vai só para o site.\n"
           "Mande /fila para ver · /limpar para cancelar tudo.")
    return len(textos) - ignorados

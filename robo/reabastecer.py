"""Fila automática: quando a fila de posts acaba, o robô coloca ofertas novas sozinho.

• Shopee: produtos que vendem bem, nota alta e boa comissão, já com o SEU link
  de afiliada (gerado pela API oficial).
• Mercado Livre: mais vendidos com desconto real (API oficial), com o SEU código
  de afiliada (matt_word/matt_tool dos seus links meli.la).
• Prioridade para peças de PC; nunca repete produto já sugerido.

Só reabastece dentro da janela de posts (10h–23h) e no máximo a cada 2 horas.
Você recebe no Telegram a lista do que entrou — /limpar cancela tudo.
Desligar: variável FILA_AUTOMATICA = false no GitHub.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from . import config, fila, mercadolivre, shopee, sugestoes, supabase
from .produto import formatar_preco

CHAVE = "reabastecer_proximo"
INTERVALO_MIN_H = 2


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
            for n in sugestoes.buscar_shopee(quantas=config.FILA_AUTO_SHOPEE):
                if n.get("_link"):
                    textos.append(str(n["_link"]))
                    linhas.append(f"🛍️ {str(n.get('productName', ''))[:55]} — "
                                  f"{formatar_preco(sugestoes._num(n.get('priceMin'), None))}")
        except Exception as erro:  # noqa: BLE001
            print(f"::warning::Fila automática Shopee: {str(erro)[:150]}")
    if mercadolivre.ativo() and config.FILA_AUTO_ML and config.ML_MATT_WORD:
        try:
            for n in sugestoes.buscar_ml(quantas=config.FILA_AUTO_ML):
                textos.append(n["link"])
                linhas.append(f"🛒 {str(n['nome'])[:55]} — {formatar_preco(n['preco'])} (-{round(n['desconto'])}%)")
        except Exception as erro:  # noqa: BLE001
            print(f"::warning::Fila automática ML: {str(erro)[:150]}")
    if not textos:
        enviar("🤖 A fila acabou e não achei ofertas novas boas agora. Tento de novo em 2 h "
               "(ou mande links / use /ofertas_pc).")
        return 0
    # intercala as lojas para variar o feed
    meio = len([l for l in linhas if l.startswith("🛍️")])
    ordem = [i for par in zip(range(meio), range(meio, len(textos))) for i in par]
    ordem += [i for i in range(len(textos)) if i not in ordem]
    textos = [textos[i] for i in ordem]
    linhas = [linhas[i] for i in ordem]
    total, proxima, ignorados = fila.adicionar(textos)
    supabase.gravar_config(CHAVE, "")
    enviar("🤖 A fila tinha acabado — coloquei ofertas novas sozinho "
           f"({len(textos) - ignorados}):\n\n" + "\n".join(linhas) +
           f"\n\n⏰ Próximo post: {proxima.strftime('%d/%m às %H:%M')}\n"
           "Mande /fila para ver · /limpar para cancelar tudo.")
    return len(textos) - ignorados

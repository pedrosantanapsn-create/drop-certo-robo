"""Post do canal do Telegram no formato compacto (estilo dos grandes canais de ofertas).

Foto do produto + nome + preço + (menor preço em 30 dias) + cupom + link limpo.
Instagram e TikTok continuam com o vídeo e a legenda completa; isto vale só para o canal.

Regras mantidas (CDC art. 36/37 e CONAR): "(ANÚNCIO)" e #publi em todo post, "de R$" só
quando é verdade, horário em que o preço foi visto e, na Amazon, o aviso de Associado.
"""
from __future__ import annotations

from datetime import datetime
from html import escape

from . import amazon, config, fila, rastreio
from .produto import Produto, formatar_preco


def _loja(link: str) -> str:
    l = link.lower()
    for chave, nome in (("shopee", "Shopee"), ("shp.ee", "Shopee"), ("meli.la", "Mercado Livre"),
                        ("mercadolivre", "Mercado Livre"), ("amazon", "Amazon"), ("amzn", "Amazon"),
                        ("tiktok", "TikTok Shop"), ("magazineluiza", "Magalu"), ("magalu", "Magalu"),
                        ("kabum", "KaBuM!"), ("aliexpress", "AliExpress")):
        if chave in l:
            return nome
    return "loja"


def legenda(produto: Produto, menor30: bool = False) -> str:
    """Legenda em HTML (parse_mode HTML) para o post do canal."""
    linhas: list[str] = []
    if produto.alerta == "bug":
        linhas += ["⚠️ <b>POSSÍVEL ERRO DE PREÇO</b> — pode cair a qualquer momento", ""]
    linhas.append(f"<b>{escape(produto.nome.strip())}</b>")
    linhas.append("")
    preco = formatar_preco(produto.preco)
    if preco:
        antigo = formatar_preco(produto.preco_antigo) if (
            produto.preco_antigo and produto.preco and produto.preco_antigo > produto.preco) else ""
        linhas.append((f"<s>{antigo}</s> " if antigo else "") + f"<b>{preco}</b>"
                      + (f"  ({produto.desconto}% OFF)" if antigo and produto.desconto else ""))
    if menor30:
        linhas.append("📉 Menor preço em 30 dias")
    if produto.cupom:
        linhas.append(f"🎟️ Cupom: <code>{escape(produto.cupom)}</code>"
                      + (f" — {escape(produto.cupom_info)}" if produto.cupom_info else ""))
    linhas.append("")
    url = rastreio.link(produto.link, produto.site_id, produto.nome)
    linhas.append(f'🛒 <a href="{escape(url)}">Comprar na {escape(_loja(produto.link))}</a>')
    linhas.append("")
    agora = datetime.now(fila.FUSO).strftime("%d/%m %H:%M")
    linhas.append(f"<i>Preço visto em {agora}, pode mudar.</i>")
    rodape = "(ANÚNCIO) #publi · link de afiliado"
    if amazon.e_amazon(produto.link):
        rodape += f"\n{amazon.AVISO}"
    linhas.append(f"<i>{escape(rodape)}</i>")
    return "\n".join(linhas)


def regras() -> str:
    """Mensagem de regras do canal (para fixar no topo)."""
    site = escape(config.SITE_URL)
    return "\n".join([
        "📌 <b>REGRAS E AVISOS DO DROP CERTO</b>",
        "",
        "1. Preço e estoque mudam rápido: confira o valor na loja antes de pagar. Cada post mostra a hora "
        "em que o preço foi visto.",
        "2. Cupons seguem as regras da loja e podem acabar antes do prazo.",
        "3. \"⚠️ Possível erro de preço\" = preço muito abaixo do normal; a loja pode cancelar o pedido. "
        "Compre só se aceitar esse risco.",
        "4. \"📉 Menor preço em 30 dias\" vem do nosso histórico próprio de preços.",
        "5. Somos afiliados: ganhamos uma comissão quando você compra pelos links, sem custo extra para você "
        "(#publi). Como Associado da Amazon, ganhamos com compras qualificadas.",
        "6. Entrega, troca, garantia e devolução são com a loja. Em compra on-line você tem 7 dias para "
        "desistir (CDC, art. 49).",
        "7. Não pedimos senha, Pix nem dados pessoais — desconfie de quem pedir em nosso nome.",
        "",
        "🔔 Ative as notificações para não perder as ofertas.",
        f'🌐 Todas as ofertas: <a href="{site}">{site.replace("https://", "")}</a>',
        "📸 Instagram @certodrop · 🎵 TikTok @certo.drop",
    ])

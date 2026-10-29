"""Nota da oferta (0 a 100) e detector de desconto falso.

A nota junta o que faz uma oferta vender, usando só dados que o robô já tem:
  • desconto REAL (pelo histórico de preços próprio, não pelo "de R$" da loja);
  • marca conhecida; nota e vendas na loja; comissão; peça de PC; cupom; faixa de preço.

Ofertas da fila AUTOMÁTICA com nota baixa vão só para o site (não gastam o
alcance do canal, Reels e TikTok). Links que VOCÊ manda são sempre postados.

Desconto falso (CDC art. 37): se o "de R$" nunca apareceu no histórico de 30 dias,
o robô apaga o "de R$" e o "% OFF" do post.
"""
from __future__ import annotations

from . import config, marcas
from .produto import Produto, formatar_preco

DIAS_CONFIAVEIS = 7        # histórico mínimo para afirmar algo sobre o preço


def desconto_falso(produto: Produto, info: dict) -> str:
    """Motivo (texto) se o "de R$" da oferta não é verdadeiro; '' se está ok ou não dá para saber."""
    if not (produto.preco_antigo and produto.preco and info.get("dias", 0) >= DIAS_CONFIAVEIS):
        return ""
    maior = info.get("maximo30")
    if maior and maior < produto.preco_antigo * 0.95:
        return (f"o \"de {formatar_preco(produto.preco_antigo)}\" não aparece no histórico de 30 dias "
                f"(o maior foi {formatar_preco(maior)})")
    return ""


def calcular(produto: Produto, info: dict, extras: dict | None = None, falso: bool = False) -> tuple[int, list[str]]:
    """(nota 0-100, motivos curtos)."""
    from .sugestoes import eh_pc     # import aqui para evitar ciclo

    extras = extras or {}
    pontos, motivos = 0.0, []
    preco = produto.preco or 0
    mediana = info.get("mediana")

    # 1. Desconto real
    if info.get("dias", 0) >= DIAS_CONFIAVEIS and mediana and preco:
        queda = (1 - preco / mediana) * 100
        if queda >= 3:
            pontos += min(queda * 1.2, 30)
            motivos.append(f"{round(queda)}% abaixo do normal")
        elif not produto.cupom:
            pontos -= 15
            motivos.append("preço normal (sem promoção de verdade)")
    elif produto.desconto and not falso:
        pontos += min(produto.desconto * 0.4, 15)
        motivos.append(f"{produto.desconto}% off da loja")
    if info.get("menor30"):
        pontos += 10
        motivos.append("menor preço em 30 dias")
    if falso:     # "de R$" inventado: pesa muito, a não ser que o preço esteja mesmo abaixo do normal
        pontos -= 8 if any("abaixo do normal" in m for m in motivos) else 25
        motivos.append("\"de R$\" falso")

    # 2. Produto
    marca = marcas.marca(produto.nome)
    if marca:
        pontos += 15
        motivos.append(marca)
    if eh_pc(produto.nome):
        pontos += 10
        motivos.append("peça de PC")
    if 40 <= preco <= 2500:
        pontos += 5

    # 3. Prova social (Shopee informa; nas outras lojas fica um valor neutro)
    nota_loja, vendas = extras.get("nota_loja"), extras.get("vendas")
    if nota_loja is None and vendas is None:
        pontos += 6
    else:
        if (nota_loja or 0) >= 4.8:
            pontos += 8
        elif (nota_loja or 0) >= 4.5:
            pontos += 5
        if (vendas or 0) >= 1000:
            pontos += 7
            motivos.append(f"{int(vendas)}+ vendidos")
        elif (vendas or 0) >= 100:
            pontos += 4

    # 4. Comissão (Shopee informa a taxa; 0.07 = 7%)
    comissao = extras.get("comissao")
    if comissao:
        taxa = comissao * 100 if comissao < 1 else comissao
        pontos += min(taxa, 12)
        motivos.append(f"comissão {taxa:.0f}%")
    else:
        pontos += 4

    if produto.cupom:
        pontos += 5
        motivos.append("cupom")
    if produto.alerta == "bug" or info.get("bug"):
        pontos += 20
        motivos.append("possível erro de preço")
    return max(0, min(100, round(pontos))), motivos


def passa(produto: Produto, nota: int) -> bool:
    """Oferta automática só vai para as redes com nota boa; as que você manda vão sempre."""
    return produto.origem != "auto" or nota >= config.NOTA_MINIMA

"""Robô Drop Certo — Etapa 1.

Você manda o link de afiliado (meli.la/...) para o seu bot no Telegram e
o robô devolve arte + vídeo + legenda, posta no canal e cadastra no site.

Modos de uso:
  python main.py              -> processa as mensagens pendentes e sai (GitHub Actions)
  python main.py --continuo   -> fica ligado respondendo na hora (seu PC / Oracle Cloud)
  python main.py --teste      -> gera arte e vídeo de exemplo, sem internet
"""
from __future__ import annotations

import argparse
import json
import re
import os
import shutil
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from robo import aindavale, ajudante, alertas, amazon, arte, awin, busca, canais, canal, config, copiar, cupons, nota, fila, instagram, instantaneo, legenda, mercadolivre, musicas, precos, quadro, quedas, ranking, reabastecer, terabyte, recorte, relatorio, shopee, sugestoes, supabase, telegram, tiktok, top, verificador, video
from robo.produto import Produto, _para_float, baixar_imagens, buscar_produto, formatar_preco, ler_mensagem

AJUDA = """🤖 Robô Drop Certo

Mande o seu link de afiliado do Mercado Livre:
meli.la/abc123

Se quiser, corrija ou complete os dados (uma informação por linha):
meli.la/abc123
preco: 89,90
de: 149,90
nome: Mouse Gamer RGB 7200 DPI
obs: ótimo para quem joga FPS

📷 Mandar uma FOTO com o link na legenda faz o robô usar a sua foto.

🗓️ FILA (posta ao longo do dia):
Mande VÁRIOS links numa mensagem, um por linha.
O robô posta 1 por hora e, no pico (11h30–13h30 e 19h–23h),
2 por hora — entre 10h e 23h.
Para agendar um link só: /agendar meli.la/abc123

📷 LISTA COM FOTOS (Shopee, Amazon…): mande as fotos
de uma vez (álbum) com o link na legenda de cada foto —
ou uma legenda só com todos os links, um por linha,
na mesma ordem das fotos. Tudo vai para a fila.
Uma foto avulsa: legenda "/agendar link"

Comandos:
/fila — mostra o que está agendado
/agora — posta o próximo da fila agora
/intervalo 60 — um post a cada 60 min
/intervalo igual — espalha por igual no dia
/intervalo auto — 1 post a cada 30 min e a cada 20 min no pico (padrão)
/intervalo pico — só os melhores horários
/limpar — apaga a fila
/id — mostra seu ID do Telegram
/colunas — mostra as colunas da tabela do site
/instagram — confere a ligação com o Instagram
/tiktok — confere a ligação com o TikTok
/relatorio — posts e cliques dos últimos 7 dias (/relatorio 30 = 30 dias)
/conferir — confere agora preços e ofertas esgotadas do site
/voz — testa a narração dos vídeos
/ofertas — sugere ofertas de tecnologia para postar (sai sozinho todo dia às 10h)
/ml — liga/confere a API oficial do Mercado Livre
/awin — sua conta Awin: ID de afiliada e lojas aceitas (Casas Bahia, KaBuM!…)
/awin_ofertas ssd 1tb · /casasbahia monitor até 900 — busca produtos nas lojas Awin (já com seu link)
/awin_cupons — cupons e promoções ativas das suas lojas Awin
/canais · /canal_add @nome · /canal_tirar @nome — canais públicos do Telegram de onde o robô pega ofertas
/terabyte ssd 1tb · /amazon_busca monitor até 900 — busca feita pelo ajudante (extensão no Edge); /add T1 Z2
/add S1 M3 — põe na fila produtos da última sugestão (/add todos, /add ml, /add shopee)
/site link + preco: — coloca SÓ no site (quando o post saiu sem preço)
/custo fone com dongle até 300 — vídeo Top 5 de custo-benefício (ficha técnica + preço + nota)
/video_top fone bluetooth até 100 — vídeo "Top 5" na hora · /cancelar_top cancela o das 20h
/musica (mande o áudio) · /musicas · /tirar_musica N — músicas de fundo dos vídeos
/cupom CODIGO descrição — cupom no canal com passo a passo; "hora: 00:00" agenda (/cupom sozinho = modelo)
/cupons — cupons agendados · /cancelar_cupom CODIGO
/regras — publica e fixa as regras no canal
/ofertas_pc — só peças de PC (placa de vídeo, placa-mãe, processador…) nas 3 lojas
/ofertas_amazon [palavra|tudo] — só Amazon: promoções do dia (ex.: /ofertas_amazon ssd)
/ofertas_ml [palavra] — só Mercado Livre: mais vendidos com desconto (ex.: /ofertas_ml monitor)
/shopee [palavra] — busca na Shopee e já manda o SEU link de afiliada (ex.: /shopee mouse gamer)
/instantaneo on — o robô responde na hora (off = volta aos 10 min)
/ajuda — mostra esta mensagem"""

FALHA_LEITURA = """⚠️ Não consegui ler os dados do anúncio (algumas lojas bloqueiam robôs).

Jeito mais fácil: tire um PRINT da página do produto (com nome e preço aparecendo)
e mande o print com o link na legenda. Eu leio o nome e o preço do print.

Ou mande assim:
{link}
nome: (nome do produto)
preco: (preço atual)"""


def nova_pasta() -> Path:
    pasta = config.PASTA_SAIDA / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


LOJAS_CONHECIDAS = re.compile(r"amazon\.|amzn\.|a\.co/|meli\.la|mercadoli|shopee|shp\.ee|kabum|awin1\.com|tidd\.ly|"
                             r"terabyteshop|casasbahia|magazineluiza|magalu|aliexpress|tiktok\.com|pontofrio", re.I)


def _abrir_encurtador(link: str) -> str:
    """Link encurtado de outro canal (aoferta.net, bit.ly…): segue os redirecionamentos até a loja."""
    from urllib.parse import urljoin
    import requests
    url = link
    for _ in range(6):
        if LOJAS_CONHECIDAS.search(url):
            return url
        try:
            r = requests.get(url, allow_redirects=False, timeout=20,
                             headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "pt-BR"})
        except Exception:  # noqa: BLE001
            return link
        proximo = r.headers.get("Location")
        if not proximo:
            return link
        url = urljoin(url, proximo)
    return url if LOJAS_CONHECIDAS.search(url) else link


def _parecidos(a: str, b: str) -> bool:
    """Os dois nomes são do mesmo produto? (palavras importantes em comum)"""
    pa = {p for p in re.findall(r"[a-z0-9]{3,}", a.lower())}
    pb = {p for p in re.findall(r"[a-z0-9]{3,}", b.lower())}
    if not pa or not pb:
        return True
    return len(pa & pb) / min(len(pa), len(pb)) >= 0.35


class PrecisaCompleto(Exception):
    """Na rodada rápida: esta mensagem precisa da rodada completa (arte, vídeo, voz, fotos)."""

    def __init__(self, avisou: bool = False):
        super().__init__("precisa da rodada completa")
        self.avisou = avisou            # True = o "⏳ Recebi!" já foi mandado


# Comandos que precisam de vídeo/voz/fotos (na rodada rápida vão direto para a completa)
COMANDOS_PESADOS = {"/video_top", "/videotop", "/top5", "/custo", "/custobeneficio", "/custo_beneficio",
                    "/voz", "/agora", "/site", "/conferir", "/relatorio"}


def processar_oferta(mensagem: dict, chat_id) -> None:
    texto = mensagem.get("text") or mensagem.get("caption") or ""
    dados = ler_mensagem(texto)
    if not dados.get("link"):
        telegram.enviar_texto(chat_id, "Não achei um link na mensagem. Mande /ajuda para ver o formato.")
        return

    if not config.JA_AVISOU:
        telegram.enviar_texto(chat_id, "⏳ Recebi! Montando arte, vídeo e legenda…")
    if config.RAPIDO:
        raise PrecisaCompleto(avisou=True)   # o resto precisa de ffmpeg/voz: continua na rodada completa
    pasta = nova_pasta()
    status: list[str] = []

    # 1. Dados do produto
    ml_trocado = False           # link do ML veio de outro canal e foi trocado pelo seu
    extras: dict = {}            # nota/vendas/comissão da loja (Shopee) para a nota da oferta
    link_produto = ""            # endereço da Shopee para gerar links marcados por rede
    try:
        produto = buscar_produto(dados)
    except Exception as erro:  # noqa: BLE001
        produto = Produto(link=dados["link"], nome=dados.get("nome", ""), preco=dados.get("preco"),
                          preco_antigo=dados.get("preco_antigo"), observacao=dados.get("observacao", ""),
                          cupom=dados.get("cupom", ""), cupom_info=dados.get("cupom_info", ""))
        status.append(f"• Leitura do anúncio falhou ({str(erro)[:60]})")

    if str(dados.get("imagem", "")).startswith("http") and dados["imagem"] not in produto.imagens:
        produto.imagens = [dados["imagem"], *produto.imagens]      # foto que veio do feed (Awin)

    # Shopee com a API oficial de afiliados: nome, preço e foto sem precisar de print
    if shopee.ativo() and shopee.e_shopee(produto.link) and not dados.get("preco"):
        try:
            oficial = shopee.ler(produto.link)
            if oficial.get("nome") and not dados.get("nome"):
                produto.nome, produto.nome_do_link = str(oficial["nome"]).strip(), False
            if oficial.get("preco"):
                produto.preco = oficial["preco"]
                produto.preco_antigo = oficial.get("preco_antigo") or produto.preco_antigo
            if oficial.get("imagem"):
                produto.imagens = [oficial["imagem"], *produto.imagens]
            produto.chave_preco = oficial.get("chave_preco") or ""
            extras = {k: oficial.get(k) for k in ("comissao", "nota_loja", "vendas")}
            link_produto = oficial.get("link_produto") or ""
            produto.bloqueado = False
            status.append("• Dados lidos pela API oficial da Shopee ✅")
        except Exception as erro:  # noqa: BLE001
            status.append(f"• API da Shopee: {str(erro)[:120]}")
            print(f"::warning::API da Shopee: {str(erro)[:200]}")

    if not LOJAS_CONHECIDAS.search(produto.link):
        aberto = _abrir_encurtador(produto.link)
        if aberto != produto.link:
            status.append("• Link encurtado de outro canal: abri até a loja")
            produto.link = aberto

    # Amazon: confere se o link tem a SUA tag de associado (sem ela, não há comissão)
    if amazon.e_amazon(produto.link):
        novo_link, texto_tag = amazon.link_com_minha_tag(produto.link)
        status.append(f"• Amazon: {texto_tag}")
        if not novo_link:
            # Post sem comissão não vale a pena: para aqui e pede o link certo
            telegram.enviar_texto(chat_id, texto_tag + "\n\n🛑 Não postei. Mande de novo com o link "
                                  "da página do produto.")
            shutil.rmtree(pasta, ignore_errors=True)
            return
        produto.link = novo_link
        if not produto.url_final:
            try:
                produto.url_final = amazon.resolver(produto.link)[0]
            except Exception:  # noqa: BLE001
                pass

    # Terabyte: coloca o seu código de parceira (?p=) em qualquer link da loja
    if terabyte.e_terabyte(produto.link):
        produto.link, texto_tb = terabyte.link_com_meu_codigo(produto.link)
        status.append(f"• Terabyte: {texto_tb}")
        if texto_tb.startswith("⚠️"):
            telegram.enviar_texto(chat_id, texto_tb + "\n🛑 Não postei.")
            shutil.rmtree(pasta, ignore_errors=True)
            return
        produto.loja_nome = "Terabyte"

    # Lojas da Awin (Casas Bahia, KaBuM!…): troca o link normal pelo SEU link de afiliada
    if awin.ativo() and awin.e_link_awin(produto.link):
        destino_awin = awin.destino_se_for_de_outro(produto.link)   # link da Awin de outro canal
        if destino_awin:
            status.append("• Awin: o link era de outra pessoa — gerando o seu")
            produto.link, produto.url_final = destino_awin, ""
    if awin.ativo() and not awin.e_link_awin(produto.link):
        try:
            link_site, link_canal, aviso = awin.converter(produto.url_final or produto.link)
            if aviso and not link_site:
                telegram.enviar_texto(chat_id, aviso)
                shutil.rmtree(pasta, ignore_errors=True)
                return
            if aviso:
                produto.link, produto.link_canal = link_site, link_canal
                status.append(f"• Awin: {aviso}")
        except Exception as erro:  # noqa: BLE001
            status.append(f"• Awin: não consegui gerar o link ({str(erro)[:100]})")
            print(f"::warning::Awin: {str(erro)[:200]}")

    # Mercado Livre: link de OUTRA pessoa (copiado de outro canal) ou sem afiliado → vira o SEU
    if mercadolivre.e_mercadolivre(produto.link):
        try:
            novo_ml, texto_ml = mercadolivre.link_meu(produto.link)
        except Exception as erro:  # noqa: BLE001
            novo_ml, texto_ml = produto.link, f"não consegui conferir o afiliado ({str(erro)[:60]})"
        if not novo_ml and ajudante.ativo() and ajudante.usado_recentemente(7):
            # O ajudante do PC gera o SEU meli.la desse produto; a oferta entra na fila quando ficar pronto
            try:
                item_ml, catalogo_ml = mercadolivre.codigos_do_link(produto.link)
                if catalogo_ml or item_ml:
                    url_ml = (f"https://www.mercadolivre.com.br/p/{catalogo_ml}" if catalogo_ml
                              else f"https://produto.mercadolivre.com.br/MLB-{item_ml[3:]}")
                    original = (mensagem.get("text") or mensagem.get("caption") or produto.link).strip()
                    novo = ajudante.pedir(f"ml:{catalogo_ml or item_ml}", url_ml,
                                          {"texto": original, "link_original": dados.get("link") or produto.link})
                    ligado = ajudante.ligado()
                    telegram.enviar_texto(chat_id, f"🧩 Mercado Livre: {texto_ml}.\n" + (
                        "Pedi ao ajudante do PC para gerar o SEU meli.la desse produto"
                        if novo else "Esse produto já estava pedido ao ajudante") + (
                        " — ele está ligado, deve ficar pronto em poucos minutos." if ligado else
                        " — ele está DESLIGADO agora; gera assim que você ligar o ajudante no PC (vale por 48 h).")
                        + "\nQuando ficar pronto, a oferta entra na fila sozinha.")
                    shutil.rmtree(pasta, ignore_errors=True)
                    return
            except Exception as erro:  # noqa: BLE001
                print(f"::warning::Ajudante (pedido): {str(erro)[:150]}")
        if not novo_ml:
            telegram.enviar_texto(chat_id, f"⚠️ Mercado Livre: {texto_ml} — vendas por esse link NÃO pagariam "
                                  "comissão para você.\n\nAbra o produto no app do ML, toque em \"Compartilhar\" "
                                  "na barra de afiliados e mande o SEU meli.la (pode colar junto o preço e o cupom "
                                  "do outro canal).\n🛑 Não postei.")
            shutil.rmtree(pasta, ignore_errors=True)
            return
        if texto_ml:
            status.append(f"• Mercado Livre: {texto_ml}")
        if novo_ml != produto.link:
            produto.link, produto.url_final = novo_ml, ""
            ml_trocado = True

    # Mercado Livre com a API oficial: nome, preço com promoção e fotos sem depender da página
    if mercadolivre.e_mercadolivre(produto.link) and (not dados.get("preco") or ml_trocado):
        try:
            oficial = mercadolivre.ler(produto.link)
            if oficial.get("preco") and dados.get("preco"):
                oficial = {**oficial, "preco": dados["preco"], "preco_antigo": dados.get("preco_antigo")}
            if oficial.get("preco"):
                if oficial.get("nome") and not dados.get("nome") and (
                        not produto.nome or produto.nome_do_link or produto.bloqueado):
                    produto.nome, produto.nome_do_link = str(oficial["nome"]).strip(), False
                produto.preco = oficial["preco"]
                produto.preco_antigo = oficial.get("preco_antigo")
                produto.chave_preco = oficial.get("chave_preco") or ""
                if oficial.get("imagens") and (not produto.imagens or produto.bloqueado):
                    produto.imagens = oficial["imagens"]
                produto.bloqueado = False
                status.append("• Dados lidos pela API oficial do Mercado Livre ✅")
                if dados.get("nome") and oficial.get("nome") and not _parecidos(dados["nome"], oficial["nome"]):
                    telegram.enviar_texto(chat_id, "⚠️ Mercado Livre: o link de outro canal leva para uma página com "
                                          f"vários produtos e eu achei \"{str(oficial['nome'])[:70]}\", que não parece "
                                          f"ser \"{dados['nome'][:70]}\".\n\nAbra o produto no app do ML e mande o "
                                          "SEU meli.la (Compartilhar na barra de afiliados).\n🛑 Não postei.")
                    shutil.rmtree(pasta, ignore_errors=True)
                    return
                if oficial.get("ativo") is False:
                    status.append("• ⚠️ O Mercado Livre diz que este anúncio está pausado/esgotado")
        except Exception as erro:  # noqa: BLE001
            status.append(f"• API do Mercado Livre: {str(erro)[:120]}")
            print(f"::warning::API do Mercado Livre: {str(erro)[:200]}")

    # Outras lojas que bloqueiam o robô (Magalu, KaBuM!…): o Google abre a página pelo Gemini.
    # Amazon e Shopee bloqueiam até o Google (testado), então nelas isso é pulado.
    bloqueia_tudo = any(s in produto.link.lower() for s in ("amazon", "amzn", "shopee", "shp.ee"))
    if not bloqueia_tudo and (produto.preco is None or produto.nome_do_link or produto.bloqueado
                              or not produto.nome):
        pagina = legenda.ler_pagina(produto.link, produto.url_final)
        if pagina.get("nome") and (not produto.nome or produto.nome_do_link) and not dados.get("nome"):
            produto.nome, produto.nome_do_link = str(pagina["nome"]).strip(), False
        if produto.preco is None and pagina.get("preco"):
            produto.preco = _para_float(pagina["preco"])
        if produto.preco_antigo is None and pagina.get("preco_antigo"):
            produto.preco_antigo = _para_float(pagina["preco_antigo"])
        if not produto.imagens and str(pagina.get("imagem", "")).startswith("http"):
            produto.imagens = [str(pagina["imagem"])]
        if pagina:
            produto.bloqueado = False
            status.append("• Dados lidos da página da loja pelo Google/Gemini ✅ (confira o preço)")

    fotos: list[Path] = []
    foto_enviada = telegram.baixar_foto_da_mensagem(mensagem, pasta / "foto_enviada.jpg")
    if foto_enviada:
        fotos.append(foto_enviada)
    fotos += baixar_imagens(produto, pasta)

    # Você mandou foto/print: o robô lê o produto da imagem. Ela vale mais que a página
    # quando a página não trouxe preço (loja bloqueou, link curto caiu na vitrine etc.).
    pagina_confiavel = bool(produto.nome) and produto.preco is not None and not produto.nome_do_link
    if foto_enviada and not (pagina_confiavel and produto.preco_antigo is not None):
        lido = legenda.ler_imagem(foto_enviada)
        if lido.get("nome") and not dados.get("nome") and not pagina_confiavel:
            produto.nome, produto.nome_do_link = str(lido["nome"]).strip(), False
        if produto.preco is None and lido.get("preco"):
            produto.preco = _para_float(lido["preco"])
        if produto.preco_antigo is None and lido.get("preco_antigo"):
            produto.preco_antigo = _para_float(lido["preco_antigo"])
        if lido:
            status.append("• Dados lidos da sua foto pelo Gemini ✅")
    # Foto limpa: recorta só o produto do print/foto e põe em fundo branco
    if foto_enviada and config.FOTO_LIMPA:
        try:
            limpa, como = recorte.foto_limpa(foto_enviada, pasta / "foto_produto.jpg")
            if limpa:
                fotos[0] = limpa
                status.append(f"• Foto do produto: {como} ✅")
            else:
                status.append(f"• Foto do produto: usei a imagem inteira ({como})")
        except Exception as erro:  # noqa: BLE001
            status.append(f"• Foto do produto: usei a imagem inteira (erro: {str(erro)[:80]})")
    if produto.bloqueado:
        status.append("• A loja bloqueou a leitura automática")
    if produto.nome_do_link:
        status.append("• Nome tirado do link (mande um print da página para sair melhor)")

    if terabyte.e_terabyte(produto.link) and produto.preco is None:
        status.append("• Terabyte: o site bloqueia o robô — mande o link com um print da página "
                      "(ou a linha \"preco: 1.299,90\") para sair com preço")
    if "tiktok.com" in produto.link.lower() and produto.preco is None:
        # O TikTok Shop mostra nome e foto para o robô, mas não o preço
        status.append("• TikTok Shop: o preço não aparece para o robô — mande o link com "
                      "\"preco: 89,90\" (e \"de: 129,90\") ou um print da página para sair com preço")
    if not produto.nome:
        motivo = "\n".join(s for s in status if "Shopee" in s or "Mercado Livre" in s or "falhou" in s)
        telegram.enviar_texto(chat_id, FALHA_LEITURA.format(link=produto.link)
                              + (f"\n\nMotivo:\n{motivo}" if motivo else ""))
        shutil.rmtree(pasta, ignore_errors=True)
        return
    if not fotos:
        status.append("• Sem foto do produto — mande uma foto junto com o link para ficar melhor")

    # Histórico de preços próprio, desconto falso e nota da oferta
    menor30, info = False, {}
    if not produto.chave_preco and "awin1.com/pclick" in produto.link:
        id_awin = re.search(r"[?&]p=(\d+)", produto.link)
        produto.chave_preco = f"awin:{id_awin.group(1)}" if id_awin else ""
    if not produto.chave_preco and amazon.e_amazon(produto.link):
        asin = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", produto.link + " " + (produto.url_final or ""))
        produto.chave_preco = f"amazon:{asin.group(1)}" if asin else ""
    if produto.chave_preco and produto.preco:
        try:
            info = precos.analise(produto.chave_preco, produto.preco)
            menor30 = bool(info.get("menor30"))
            if info.get("bug") and not produto.alerta:
                produto.alerta = "bug"
                status.append("• ⚠️ Preço 50% abaixo do normal deste produto — postado como possível erro de preço")
            precos.registrar(produto.chave_preco, produto.preco)
            precos.salvar()
            if menor30:
                status.append(f"• 📉 Menor preço em 30 dias (histórico de {info.get('dias')} dias)")
            elif info.get("dias"):
                status.append(f"• Histórico de preço: {info.get('dias')} dias, mínimo "
                              f"{formatar_preco(info.get('minimo30'))}")
        except Exception as erro:  # noqa: BLE001
            print("Histórico de preços:", erro, file=sys.stderr)
    falso = nota.desconto_falso(produto, info)
    if falso:
        status.append(f"• 🚫 Desconto falso: {falso} — tirei o \"de R$\" e o \"% OFF\" do post (CDC art. 37)")
        produto.preco_antigo = None
    pontos, motivos = nota.calcular(produto, info, extras, falso=bool(falso))
    vai_redes = nota.passa(produto, pontos)
    status.append(f"• Nota da oferta: {pontos}/100" + (f" ({', '.join(motivos[:5])})" if motivos else ""))
    if not vai_redes:
        status.append(f"• Nota abaixo de {config.NOTA_MINIMA} (fila automática): fica só no site — "
                      "não gastei o alcance do canal, Reels e TikTok")

    # Shopee: SEMPRE gera o seu link (mesmo se o link veio de outro canal) — um por rede (canal / site)
    if not link_produto and shopee.ativo() and shopee.e_shopee(produto.link):
        ids_sp = shopee.ids_do_link(produto.link)
        if ids_sp:
            link_produto = f"https://shopee.com.br/product/{ids_sp[0]}/{ids_sp[1]}"
    if link_produto:
        try:
            marcar = config.MARCAR_ORIGEM_SHOPEE
            produto.link_canal = shopee.link_afiliado(link_produto, "canal" if marcar else "dropcerto")
            produto.link = shopee.link_afiliado(link_produto, "site" if marcar else "dropcerto")
            status.append("• Shopee: link gerado com o SEU código de afiliada ✅")
        except Exception as erro:  # noqa: BLE001
            print(f"::warning::Links por rede da Shopee: {str(erro)[:150]}")

    # 2. Textos
    textos, origem = legenda.gerar_textos(produto)
    status.append(f"• Textos: {origem}")

    # 3. Arte e vídeo — alterna o modelo (cores, ordem das cenas) a cada post
    try:
        numero = int(str((supabase.ler_config("modelo_video") or {}).get("valor") or 0)) if supabase.ativo() else 0
        modelo = video.usar_modelo(numero)
        if supabase.ativo():
            supabase.gravar_config("modelo_video", str(numero + 1))
        status.append(f"• Modelo do vídeo: {modelo['nome']} · voz {config.VOZ_KOKORO}")
    except Exception as erro:  # noqa: BLE001
        print("Modelo do vídeo:", erro, file=sys.stderr)
    caminho_arte = arte.arte_feed(produto, textos, fotos, pasta / "arte_feed.jpg")
    try:
        if not vai_redes:
            raise RuntimeError("não precisa (oferta só para o site)")
        caminho_video, com_voz = video.gerar_video(produto, textos, fotos, pasta)
        if com_voz:
            status.append(f"• Vídeo: pronto com narração ({video.voz_usada})"
                          + (f" + música \"{musicas.musica_usada}\"" if musicas.musica_usada else ""))
        else:
            status.append(f"• Vídeo: pronto (sem narração — {video.motivo_sem_voz[:200]})")
    except Exception as erro:  # noqa: BLE001
        caminho_video = None
        status.append(f"• Vídeo falhou: {str(erro)[:120]}")

    # 4. Site (Supabase) — antes do canal, para o canal usar o link rastreado do produto
    if supabase.ativo():
        if fotos:
            try:
                supabase.cadastrar_produto(produto, fotos[0], textos["legenda"])
                status.append("• Site: produto cadastrado ✅")
            except Exception as erro:  # noqa: BLE001
                status.append(f"• Site: erro — {str(erro)[:160]}\n  (mande /colunas para conferir os nomes)")
        else:
            status.append("• Site: não cadastrado (sem foto)")
    # 4a. Canal do Telegram — formato compacto: foto do produto + nome + preço + cupom + link limpo
    if config.AUTO_POSTAR_CANAL and config.CANAL_ID and vai_redes:
        try:
            # print inteiro (recorte falhou) fica feio no canal: aí vai a arte
            foto_canal = fotos[0] if fotos and not (foto_enviada and fotos[0] == foto_enviada) else caminho_arte
            telegram.enviar_foto(config.CANAL_ID, foto_canal,
                                 canal.legenda(produto, menor30, produto.link_canal), html=True)
            status.append(f"• Canal {config.CANAL_ID}: publicado ✅")
        except Exception as erro:  # noqa: BLE001
            status.append(f"• Canal: erro — {str(erro)[:120]}")

    # 4b. Instagram (Reels automático)
    legenda_redes = legenda.montar_legenda(produto, textos, com_link=False)
    reserva = 1 if ranking.reservado_hoje() else 0     # dia de Top 5: guarda 1 vaga para o vídeo das 20h
    limite_ig = max(config.INSTAGRAM_MAX_DIA - reserva, 0) if config.INSTAGRAM_MAX_DIA else 0
    feitos_ig = relatorio.postados_hoje("instagram") if (config.INSTAGRAM_MAX_DIA and supabase.ativo()) else 0
    if caminho_video and instagram.ativo() and config.INSTAGRAM_MAX_DIA and feitos_ig >= limite_ig:
        status.append(f"• Reels: pulado — limite de {limite_ig} Reels por dia já atingido (vai só no Story)")
    elif caminho_video and instagram.ativo() and config.INSTAGRAM_SO_PICO and not fila.em_pico(datetime.now(fila.FUSO)):
        status.append("• Reels: pulado — fora do horário de pico (vai só no Story)")
    elif (caminho_video and instagram.ativo() and limite_ig and supabase.ativo()
          and time.time() - relatorio.ultimo_post("instagram") < config.INSTAGRAM_INTERVALO_H * 3600):
        status.append(f"• Reels: pulado — o último Reels saiu há menos de {config.INSTAGRAM_INTERVALO_H}h (vai só no Story)")
    elif caminho_video and instagram.ativo():
        try:
            link_post = instagram.publicar_reels(caminho_video, legenda_redes, capa=caminho_arte)
            status.append(f"• Instagram: Reels publicado ✅ {link_post}")
        except Exception as erro:  # noqa: BLE001
            status.append(f"• Instagram: erro — {str(erro)[:160]}")
    if caminho_video and instagram.story_ativo():
        try:
            if video.duracao(caminho_video) > 59:
                raise RuntimeError("vídeo passou de 60 s (limite do Story)")
            status.append(f"• Story no Instagram: publicado ✅ {instagram.publicar_story(caminho_video)}")
        except Exception as erro:  # noqa: BLE001
            status.append(f"• Story no Instagram: erro — {str(erro)[:160]}")

    # 4c. TikTok (pelo Zernio)
    limite_tt = max(config.TIKTOK_MAX_DIA - reserva, 0) if config.TIKTOK_MAX_DIA else 0
    feitos_tt = relatorio.postados_hoje("tiktok") if (config.TIKTOK_MAX_DIA and supabase.ativo()) else 0
    if caminho_video and tiktok.ativo() and config.TIKTOK_MAX_DIA and feitos_tt >= limite_tt:
        status.append(f"• TikTok: pulado — limite de {limite_tt} vídeos por dia já atingido (protege o alcance)")
    elif caminho_video and tiktok.ativo() and config.TIKTOK_SO_PICO and not fila.em_pico(datetime.now(fila.FUSO)):
        status.append("• TikTok: pulado — fora do horário de pico (vai só nos melhores horários)")
    elif (caminho_video and tiktok.ativo() and limite_tt and supabase.ativo()
          and time.time() - relatorio.ultimo_post("tiktok") < config.TIKTOK_INTERVALO_H * 3600):
        status.append(f"• TikTok: pulado — o último vídeo saiu há menos de {config.TIKTOK_INTERVALO_H}h")
    elif caminho_video and tiktok.ativo():
        try:
            status.append(f"• TikTok: publicado ✅ {tiktok.publicar(caminho_video, legenda_redes)}")
        except Exception as erro:  # noqa: BLE001
            status.append(f"• TikTok: erro — {str(erro)[:160]}")

    if supabase.ativo() and produto.preco is None:
        status.append("  👉 Para pôr no site depois, sem postar de novo: /site link + linha  preco: 89,90")

    # 6. Entrega para você publicar no TikTok (e no Instagram, se não for automático)
    if caminho_video:
        telegram.enviar_video(chat_id, caminho_video, "🎬 Vídeo para Reels/TikTok/Shorts", capa=None)
    telegram.enviar_arquivo(chat_id, caminho_arte, "🖼️ Arte do feed (arquivo em qualidade máxima)")
    telegram.enviar_texto(chat_id, "📋 Legenda para Instagram/TikTok (copie e cole):\n\n" + legenda_redes)
    try:
        alertas.depois_do_post(status)
    except Exception as erro:  # noqa: BLE001
        print("Alertas:", erro, file=sys.stderr)
    resumo = [f"✅ {produto.nome}", formatar_preco(produto.preco) or "Preço não encontrado", "", *status]
    telegram.enviar_texto(chat_id, "\n".join(resumo))
    shutil.rmtree(pasta, ignore_errors=True)
    try:
        relatorio.registrar_post(produto.nome, produto.preco, produto.link, status)
    except Exception as erro:  # noqa: BLE001
        print("Histórico:", erro, file=sys.stderr)
    if supabase.ativo():
        try:
            supabase.limpar_posts_antigos(dias=3)   # libera espaço (plano grátis = 1 GB)
        except Exception:  # noqa: BLE001
            pass


def tratar(mensagem: dict) -> None:
    chat_id = mensagem["chat"]["id"]
    texto = (mensagem.get("text") or mensagem.get("caption") or "").strip()
    texto = re.sub(r"(\.com\.br/p)\s+/(MLB)", r"\1/\2", texto, flags=re.I)   # link do ML quebrado no /p/

    if not config.ADMIN_CHAT_ID:
        telegram.enviar_texto(
            chat_id,
            f"Seu ID do Telegram é: {chat_id}\n\nCadastre esse número no GitHub como o "
            "segredo ADMIN_CHAT_ID. Depois disso só você poderá usar o robô.",
        )
        return
    if str(chat_id) != config.ADMIN_CHAT_ID:
        busca.responder(mensagem)   # outras pessoas: só a busca de ofertas (nenhum comando seu)
        return

    if config.RAPIDO and (any(mensagem.get(k) for k in ("photo", "audio", "voice", "document", "video"))
                          or (texto.split()[0].lower().split("@")[0] if texto else "") in COMANDOS_PESADOS):
        raise PrecisaCompleto()

    # Mensagem de sugestões copiada inteira e reenviada: usa só os links (um por linha)
    if any(marca in texto for marca in ("sugestões com o SEU link", "Todos os links (copie",
                                        "mais vendidos com desconto", "Ofertas sugeridas para o Drop Certo",
                                        "Amazon — promoções para o Drop Certo")):
        links = list(dict.fromkeys(l.rstrip(").,;!?") for l in fila.RE_LINK.findall(texto)
                                   if "google.com/search" not in l and "/search?" not in l and "/s?k=" not in l
                                   and ("mercadolivre.com.br/p/" not in l or "matt_" in l)
                                   and "netlify.app/quadro" not in l))   # link do ML sem afiliado: não posta
        texto = "\n".join(links)
        if not links:
            telegram.enviar_texto(chat_id, "Essa lista não tem links de afiliado seus. No Mercado Livre, "
                                  "gere o meli.la de cada produto e mande esses links.")
            return
        if len(links) > 1:
            texto = "/agendar " + texto
    # Post copiado/encaminhado de outro canal de ofertas: pega link, nome, preço e cupom
    # (o link é trocado pelo SEU na hora de postar)
    if not texto.startswith("/") and copiar.e_post_copiado(texto):
        ofertas_copiadas = copiar.separar(texto)
        if ofertas_copiadas:
            if not config.JA_AVISOU:
                telegram.enviar_texto(chat_id, f"📋 Post de outro canal: achei {len(ofertas_copiadas)} oferta(s). "
                                      "Vou trocar os links pelos SEUS.")
            if len(ofertas_copiadas) > 1:
                texto = "/agendar " + "\n".join(ofertas_copiadas)
            else:
                texto = ofertas_copiadas[0]
                mensagem = {**mensagem, "text": texto}
    comando = texto.split()[0].lower() if texto else ""
    print(f"::notice::Mensagem: {len(texto.splitlines())} linha(s), "
          f"{len(fila.separar_ofertas(texto))} oferta(s) com link")
    grupo = str(mensagem.get("media_group_id") or "")
    # Áudio mandado para o bot (com ou sem a legenda /musica) entra na biblioteca de músicas
    doc = mensagem.get("document") or {}
    if mensagem.get("audio") or (doc and str(doc.get("mime_type", "")).startswith("audio")):
        try:
            telegram.enviar_texto(chat_id, musicas.adicionar(mensagem))
        except Exception as erro:  # noqa: BLE001
            telegram.enviar_texto(chat_id, f"❌ Música: {str(erro)[:200]}")
        return
    if mensagem.get("photo") and (grupo or comando == "/agendar"):
        agendar_foto(mensagem, chat_id, texto, grupo)
        return
    if comando == "/start" and len(texto.split()) > 1 and texto.split()[1].startswith("ml_"):
        comando, texto = "/ml", "/ml " + texto.split()[1][3:]     # volta da autorização do ML
    if comando in ("/start", "/ajuda", "/help"):
        telegram.enviar_texto(chat_id, AJUDA)
    elif comando in ("/awin_ofertas", "/awinofertas", "/casasbahia", "/casas_bahia", "/kabum"):
        partes = texto.split(None, 1)
        pedido = partes[1] if len(partes) > 1 else ""
        loja = {"/casasbahia": "casas bahia", "/casas_bahia": "casas bahia", "/kabum": "kabum"}.get(comando, "")
        if not awin.feed_ativo():
            telegram.enviar_texto(chat_id, "Falta o segredo AWIN_FEED_KEY no GitHub (Awin → Ferramentas → Crie um Feed → "
                                  "copie o endereço da Lista de Feed).")
        elif not pedido:
            telegram.enviar_texto(chat_id, "Use assim: /awin_ofertas ssd 1tb  (ou /awin_ofertas monitor até 900)\n"
                                  "Só Casas Bahia: /casasbahia ssd")
        else:
            palavra, teto, _ = ranking.separar_pedido(pedido)
            telegram.enviar_texto(chat_id, f"🔎 Procurando \"{palavra}\" nas lojas Awin… (pode levar 1–2 min)")
            try:
                itens = awin.buscar_produtos(palavra, loja=loja, teto=teto)
                sugestoes._guardar("A", [awin.texto_fila(i) for i in itens])
                telegram.enviar_texto(chat_id, awin.mensagem_produtos(itens, f"🏬 Awin — {palavra}"))
            except Exception as erro:  # noqa: BLE001
                telegram.enviar_texto(chat_id, f"❌ Awin: {str(erro)[:200]}")
    elif comando in ("/awin_cupons", "/awincupons"):
        try:
            telegram.enviar_texto(chat_id, awin.mensagem_cupons(awin.cupons()))
        except Exception as erro:  # noqa: BLE001
            telegram.enviar_texto(chat_id, f"❌ Cupons da Awin: {str(erro)[:200]}")
    elif comando in ("/canais", "/canal", "/fontes"):
        telegram.enviar_texto(chat_id, canais.resumo())
    elif comando in ("/canal_add", "/canaladd", "/add_canal"):
        nomes = texto.split()[1:]
        telegram.enviar_texto(chat_id, "\n\n".join(canais.adicionar(n) for n in nomes[:5]) if nomes
                              else "Use assim: /canal_add @nomedocanal (canal público do Telegram)")
    elif comando in ("/canal_tirar", "/canaltirar", "/tirar_canal"):
        nomes = texto.split()[1:]
        telegram.enviar_texto(chat_id, "\n".join(canais.tirar(n) for n in nomes[:5]) if nomes
                              else "Use assim: /canal_tirar @nomedocanal")
    elif comando == "/awin":
        try:
            telegram.enviar_texto(chat_id, awin.resumo())
        except Exception as erro:  # noqa: BLE001
            telegram.enviar_texto(chat_id, f"❌ Awin: {str(erro)[:200]}")
    elif comando == "/ml":
        codigo = " ".join(texto.split()[1:]).strip()
        if codigo:
            try:
                mercadolivre.trocar_codigo(codigo)
                resposta = "✅ Mercado Livre autorizado!\n\n" + mercadolivre.estado()
            except Exception as erro:  # noqa: BLE001
                resposta = (f"❌ Não deu para autorizar: {str(erro)[:200]}\n"
                            "O código vale só 10 minutos e uma vez. Mande /ml e autorize de novo.")
        else:
            resposta = mercadolivre.estado()
        telegram.enviar_texto(chat_id, resposta)
    elif comando == "/id":
        telegram.enviar_texto(chat_id, f"Seu ID: {chat_id}")
    elif comando == "/instagram":
        try:
            eu = instagram.conta()
            aviso = instagram.diagnostico_zernio() if "Zernio" not in str(eu.get("username")) else ""
            telegram.enviar_texto(chat_id, f"✅ Instagram ligado: @{eu.get('username')}"
                                  + (f"\nℹ️ Zernio: {aviso}" if aviso else ""))
        except Exception as erro:  # noqa: BLE001
            telegram.enviar_texto(chat_id, f"❌ Instagram não está ligado: {str(erro)[:200]}")
    elif comando == "/tiktok":
        try:
            c = tiktok.conta() if config.ZERNIO_API_KEY else None
            telegram.enviar_texto(chat_id, f"✅ TikTok ligado pelo Zernio: @{c.get('username')}" if c
                                  else "❌ TikTok não está ligado (falta o segredo ZERNIO_API_KEY no GitHub).")
        except Exception as erro:  # noqa: BLE001
            telegram.enviar_texto(chat_id, f"❌ TikTok: {str(erro)[:200]}")
    elif comando == "/instantaneo":
        partes = texto.split()
        opcao = partes[1].lower() if len(partes) > 1 else ""
        try:
            resposta = (instantaneo.ligar() if opcao in ("on", "ligar", "sim")
                        else instantaneo.desligar() if opcao in ("off", "desligar", "nao", "não")
                        else instantaneo.estado())
        except Exception as erro:  # noqa: BLE001
            resposta = f"❌ Modo instantâneo: {str(erro)[:200]}"
        telegram.enviar_texto(chat_id, resposta)
    elif comando in ("/ofertas_pc", "/ofertaspc", "/pc") or (
            comando == "/ofertas" and [p.lower() for p in texto.split()[1:2]] == ["pc"]):
        telegram.enviar_texto(chat_id, "🖥️ Buscando peças de PC (placa de vídeo, placa-mãe, processador, "
                              "memória, SSD, fonte, gabinete, cooler)…")
        try:
            for msg_pc, eh_html in sugestoes.sugerir_pc():
                (telegram.enviar_html if eh_html else telegram.enviar_texto)(chat_id, msg_pc)
            enviar_listas(chat_id)
        except Exception as erro:  # noqa: BLE001
            telegram.enviar_texto(chat_id, f"❌ Peças de PC: {str(erro)[:200]}")
    elif comando in ("/ofertas_amazon", "/ofertasamazon", "/amazon") or (
            comando == "/ofertas" and [p.lower() for p in texto.split()[1:2]] in (["amazon"], ["amz"])):
        palavra = " ".join(p for p in texto.split()[1:] if p.lower() not in ("amazon", "amz")).strip()
        telegram.enviar_texto(chat_id, f"📦 Buscando promoções da Amazon{f': {palavra}' if palavra else ''}…")
        try:
            resposta = sugestoes.sugerir_amazon(palavra)
        except Exception as erro:  # noqa: BLE001
            resposta = f"❌ Amazon: {str(erro)[:200]}"
        telegram.enviar_texto(chat_id, resposta)
    elif comando in ("/terabyte", "/amazon_busca", "/amazonbusca", "/buscar_amazon"):
        qual = "terabyte" if comando == "/terabyte" else "amazon"
        pedido = texto.split(None, 1)[1].strip() if len(texto.split()) > 1 else ""
        if not pedido:
            telegram.enviar_texto(chat_id, f"Use assim: {comando} ssd 1tb  (ou {comando} monitor até 900)")
        elif not (ajudante.ativo() and ajudante.usado_recentemente(7)):
            telegram.enviar_texto(chat_id, "Essa busca é feita pelo ajudante (a extensão no seu Edge), e ele não "
                                  "deu sinal nos últimos dias. Abra o Edge e tente de novo em 1 minuto.")
        else:
            palavra, teto, _ = ranking.separar_pedido(pedido)
            try:
                ajudante.pedir_busca(qual, palavra, teto)
                telegram.enviar_texto(chat_id, f"🧩 Pedi ao ajudante para procurar \"{palavra}\" na "
                                      f"{ajudante.BUSCAS[qual]['nome']}. " + (
                                          "Ele está ligado: a lista chega em até uns 10 minutos."
                                          if ajudante.ligado() else
                                          "Ele está DESLIGADO agora: a lista chega depois que você abrir o Edge."))
            except Exception as erro:  # noqa: BLE001
                telegram.enviar_texto(chat_id, f"❌ Busca: {str(erro)[:200]}")
    elif comando in ("/ofertas_ml", "/ofertasml", "/ml_ofertas") or (
            comando == "/ofertas" and texto.split()[1:2] in (["ml"], ["ML"], ["mercadolivre"])):
        palavras = [p for p in texto.split()[1:] if p.lower() not in ("ml", "mercadolivre")]
        palavra = " ".join(palavras).strip()
        telegram.enviar_texto(chat_id, f"🛒 Buscando os mais vendidos do Mercado Livre{f': {palavra}' if palavra else ''}…")
        try:
            telegram.enviar_html(chat_id, sugestoes.sugerir_ml([palavra] if palavra else None, html=True))
            enviar_listas(chat_id)
        except Exception as erro:  # noqa: BLE001
            telegram.enviar_texto(chat_id, f"❌ Mercado Livre: {str(erro)[:200]}")
    elif comando == "/add":
        pedido = texto.split()[1:]
        links, faltou = sugestoes.escolhidos(pedido) if pedido else ([], [])
        if not links:
            telegram.enviar_texto(chat_id, "Use os códigos da última sugestão:\n/add S1 S3 M2  ·  /add M1-4\n"
                                  "/add shopee  ·  /add ml  ·  /add todos"
                                  + (f"\n\nNão achei: {', '.join(faltou)}" if faltou else ""))
        else:
            agendar(chat_id, "\n".join(links))
            if faltou:
                telegram.enviar_texto(chat_id, f"⚠️ Não achei na última sugestão: {', '.join(faltou)}")
    elif comando == "/site":
        so_site(mensagem, chat_id, texto.split(None, 1)[1] if len(texto.split(None, 1)) > 1 else "")
    elif comando in ("/video_top", "/videotop", "/top5"):
        try:
            ranking.sob_demanda(" ".join(texto.split()[1:]), lambda t: telegram.enviar_texto(chat_id, t))
        except Exception as erro:  # noqa: BLE001
            telegram.enviar_texto(chat_id, f"❌ Top 5: {str(erro)[:200]}")
    elif comando in ("/custo", "/custobeneficio", "/custo_beneficio"):
        try:
            ranking.custo_sob_demanda(" ".join(texto.split()[1:]), lambda t: telegram.enviar_texto(chat_id, t))
        except Exception as erro:  # noqa: BLE001
            telegram.enviar_texto(chat_id, f"❌ Custo-benefício: {str(erro)[:200]}")
    elif comando in ("/cancelar_top", "/cancelartop"):
        telegram.enviar_texto(chat_id, ranking.cancelar())
    elif comando in ("/musicas", "/musica"):
        telegram.enviar_texto(chat_id, musicas.resumo())
    elif comando in ("/tirar_musica", "/tirarmusica"):
        partes = texto.split()
        telegram.enviar_texto(chat_id, musicas.tirar(int(partes[1])) if len(partes) > 1 and partes[1].isdigit()
                              else "Use assim: /tirar_musica 3 (veja os números em /musicas)")
    elif comando == "/cupom":
        postar_cupom(chat_id, texto)
    elif comando == "/cupons":
        lista = cupons.agendados()
        telegram.enviar_texto(chat_id, "\n".join(
            ["🎟️ Cupons agendados:"] + [f"• {c['codigo']} — {datetime.fromtimestamp(c['ts'], fila.FUSO):%d/%m %H:%M}"
                                         for c in lista]) if lista else "Nenhum cupom agendado.")
    elif comando in ("/cancelar_cupom", "/cancelarcupom"):
        partes = texto.split()
        n = cupons.cancelar(partes[1]) if len(partes) > 1 else 0
        telegram.enviar_texto(chat_id, f"🗑️ {n} cupom(ns) {partes[1].upper()} tirado(s) da agenda." if n
                              else "Não achei esse cupom na agenda. Veja em /cupons.")
    elif comando == "/regras":
        postar_regras(chat_id)
    elif comando == "/ofertas":
        telegram.enviar_texto(chat_id, "🔎 Procurando ofertas…")
        telegram.enviar_texto(chat_id, sugestoes.sugerir())
        extra = sugestoes.sugerir_shopee()
        if extra:
            telegram.enviar_texto(chat_id, extra)
            enviar_listas(chat_id)
    elif comando == "/shopee":
        palavra = " ".join(texto.split()[1:]).strip()
        telegram.enviar_texto(chat_id, f"🛍️ Buscando na Shopee{f': {palavra}' if palavra else ''}…")
        try:
            resposta = sugestoes.sugerir_shopee([palavra] if palavra else None) or \
                "❌ A API da Shopee não está configurada (faltam SHOPEE_APP_ID/SHOPEE_APP_SECRET)."
        except Exception as erro:  # noqa: BLE001
            resposta = f"❌ Shopee: {str(erro)[:200]}"
        telegram.enviar_texto(chat_id, resposta)
        enviar_listas(chat_id)
    elif comando == "/voz":
        pasta = nova_pasta()
        audio, _ = video.narrar("Olá! Este é um teste da narração do Drop Certo.", pasta / "teste_voz.mp3")
        if audio:
            telegram.enviar_arquivo(chat_id, audio, f"🔊 Voz funcionando: {video.voz_usada}")
        else:
            telegram.enviar_texto(chat_id, f"❌ Narração falhou: {video.motivo_sem_voz}")
        shutil.rmtree(pasta, ignore_errors=True)
    elif comando == "/conferir":
        if not supabase.ativo():
            telegram.enviar_texto(chat_id, "Supabase não configurado.")
        else:
            telegram.enviar_texto(chat_id, "🔎 Conferindo as ofertas do site (leva alguns minutos)…")
            telegram.enviar_texto(chat_id, verificador.conferir())
    elif comando == "/relatorio":
        partes = texto.split()
        dias = int(partes[1]) if len(partes) > 1 and partes[1].isdigit() else 7
        telegram.enviar_texto(chat_id, relatorio.montar(max(1, min(dias, 365))) if supabase.ativo()
                              else "Supabase não configurado.")
    elif comando == "/fila":
        texto_fila = fila.resumo()
        if not fila.itens() and config.FILA_AUTOMATICA:
            reabastecer.agendar(5)
            texto_fila += "\n\n🤖 Fila automática ligada: em até 15 min eu coloco ofertas novas (Shopee + Mercado Livre)."
        telegram.enviar_texto(chat_id, texto_fila)
    elif comando == "/limpar":
        telegram.enviar_texto(chat_id, f"🗑️ Fila apagada ({fila.limpar()} oferta(s) removida(s)).")
    elif comando == "/agora":
        if fila.itens():
            fila.adiantar()
            telegram.enviar_texto(chat_id, "⏩ O próximo da fila sai na próxima rodada (até 10 min).")
        else:
            telegram.enviar_texto(chat_id, "📭 A fila está vazia.")
    elif comando == "/intervalo":
        partes = texto.split()
        valor = partes[1].lower() if len(partes) > 1 else ""
        if valor.isdigit() and int(valor) >= 20:
            fila.definir_intervalo(int(valor))
            telegram.enviar_texto(chat_id, f"⏱️ Pronto: um post a cada {int(valor)} minutos.")
        elif valor in ("auto", "automatico", "automático", "0", "hora"):
            fila.definir_modo("hora")
            telegram.enviar_texto(chat_id, f"⏱️ 1 post a cada {config.MINUTOS_FORA_PICO} min; no pico "
                                           f"({config.HORARIOS_PICO.replace(',', ' e ')}) a cada {config.MINUTOS_NO_PICO} min.")
        elif valor == "pico":
            fila.definir_modo("pico")
            telegram.enviar_texto(chat_id, "⏱️ Só horários de pico: a fila sai primeiro no almoço e à noite.")
        elif valor == "igual":
            fila.definir_modo("igual")
            telegram.enviar_texto(chat_id, f"⏱️ A fila vai ser espalhada por igual até as {config.POSTAR_ATE}h.")
        else:
            telegram.enviar_texto(chat_id, "Use assim: /intervalo auto (a cada 30 min, 20 no pico), /intervalo pico, /intervalo igual ou /intervalo 60")
    elif comando == "/agendar" or len(fila.separar_ofertas(texto)) > 1:
        agendar(chat_id, texto.split(None, 1)[1] if comando == "/agendar" and " " in texto else texto)
    elif comando == "/colunas":
        telegram.enviar_texto(chat_id, supabase.listar_colunas() if supabase.ativo()
                              else "Supabase não configurado.")
    elif comando.startswith("/") and not fila.RE_LINK.search(texto):
        telegram.enviar_texto(chat_id, f"Não conheço o comando {comando}. Mande /ajuda para ver a lista.")
    else:
        processar_oferta(mensagem, chat_id)


def enviar_listas(chat_id) -> None:
    """Depois das sugestões, manda os links num bloco que copia com um toque."""
    for prefixo in ("S", "M"):
        bloco = sugestoes.lista_copiavel(prefixo)
        if bloco:
            telegram.enviar_html(chat_id, bloco)


def so_site(mensagem: dict, chat_id, texto: str) -> None:
    """/add S1 M3 — põe na fila produtos da última sugestão (/add todos, /add ml, /add shopee)
/site link + preco: — cadastra SÓ no site (sem postar de novo no canal/Instagram/TikTok).
    Serve para quando o post saiu sem preço e o site recusou."""
    dados = ler_mensagem(texto)
    if not dados.get("link") or not dados.get("preco"):
        telegram.enviar_texto(chat_id, "Para colocar só no site, mande assim:\n\n/site https://link-do-produto\n"
                              "preco: 89,90\nde: 129,90\n\n(pode mandar junto um print/foto como legenda, "
                              "se quiser outra imagem)")
        return
    pasta = nova_pasta()
    try:
        try:
            produto = buscar_produto(dados)
        except Exception:  # noqa: BLE001
            produto = Produto(link=dados["link"], nome=dados.get("nome", ""))
        produto.preco = dados["preco"]
        produto.preco_antigo = dados.get("preco_antigo") or produto.preco_antigo
        if dados.get("nome"):
            produto.nome = dados["nome"]
        if amazon.e_amazon(produto.link):
            novo, _ = amazon.link_com_minha_tag(produto.link)
            produto.link = novo or produto.link
        fotos = []
        enviada = telegram.baixar_foto_da_mensagem(mensagem, pasta / "foto_enviada.jpg")
        if enviada:
            limpa, _ = recorte.foto_limpa(enviada, pasta / "foto_produto.jpg") if config.FOTO_LIMPA else (None, "")
            fotos.append(limpa or enviada)
            if not produto.nome:
                produto.nome = str(legenda.ler_imagem(enviada).get("nome") or "")
        fotos += baixar_imagens(produto, pasta)
        if not produto.nome or not fotos:
            telegram.enviar_texto(chat_id, "❌ Não consegui o nome ou a foto do produto. Mande de novo com "
                                  "\"nome: ...\" e um print/foto com o /site na legenda.")
            return
        supabase.cadastrar_produto(produto, fotos[0], "")
        telegram.enviar_texto(chat_id, f"✅ No site: {produto.nome[:70]} — {formatar_preco(produto.preco)}\n"
                              "(não postei de novo nas redes)")
    except Exception as erro:  # noqa: BLE001
        telegram.enviar_texto(chat_id, f"❌ Site: {str(erro)[:200]}")
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


MODELO_CUPOM = """🎟️ Para divulgar um cupom no canal, mande assim:

/cupom DROP10 R$ 20 off acima de R$ 100
loja: Shopee
https://s.shopee.com.br/seu-link
validade: 31/10
1. Resgate o cupom na página da loja
2. Adicione os produtos no carrinho
3. Na finalização, escolha o cupom DROP10
hora: 00:00

• 1ª linha: o código e o que ele dá (obrigatório)
• loja, link de afiliado e validade (recomendados — cupom vencido gera reclamação)
• linhas numeradas = passo a passo (sem elas, vai um passo a passo padrão)
• hora: 00:00 (ou 25/10 18:30) = posta nesse horário; sem "hora", posta agora
• /cupons mostra os agendados · /cancelar_cupom DROP10 tira da agenda

Para usar cupom num produto, coloque a linha "cupom: CODIGO o que dá" embaixo do link:
https://meli.la/abc123
cupom: DROP10 10% off"""


def postar_cupom(chat_id, texto: str) -> None:
    """/cupom → post de cupom no canal (com passo a passo), na hora ou no horário marcado."""
    cupom = cupons.montar(texto)
    if not cupom:
        telegram.enviar_texto(chat_id, MODELO_CUPOM)
        return
    if not (config.AUTO_POSTAR_CANAL and config.CANAL_ID):
        telegram.enviar_html(chat_id, "Canal não configurado. Veja como ficaria:\n\n" + cupom["html"])
        return
    dica = "" if cupom["tem_validade"] else "\n\n💡 Dica: coloque \"validade: dd/mm\" para o seguidor saber até quando vale."
    if cupom["quando"]:
        if not supabase.ativo():
            telegram.enviar_texto(chat_id, "Para agendar preciso do Supabase ligado. Mande sem a linha \"hora:\".")
            return
        cupons.agendar(cupom)
        telegram.enviar_html(chat_id, f"⏰ Cupom {cupom['codigo']} agendado para "
                             f"{cupom['quando']:%d/%m às %H:%M}. Prévia:\n\n" + cupom["html"])
        telegram.enviar_texto(chat_id, "Para cancelar: /cancelar_cupom " + cupom["codigo"] + dica)
        return
    telegram.enviar_html(config.CANAL_ID, cupom["html"])
    telegram.enviar_texto(chat_id, f"✅ Cupom {cupom['codigo']} publicado no canal {config.CANAL_ID}.{dica}")


def postar_regras(chat_id) -> None:
    if not config.CANAL_ID:
        telegram.enviar_html(chat_id, canal.regras())
        return
    msg = telegram.enviar_html(config.CANAL_ID, canal.regras())
    try:
        telegram.fixar(config.CANAL_ID, msg["message_id"])
        telegram.enviar_texto(chat_id, "📌 Regras publicadas e fixadas no topo do canal.")
    except Exception as erro:  # noqa: BLE001
        telegram.enviar_texto(chat_id, "✅ Regras publicadas, mas não consegui fixar "
                              f"({str(erro)[:100]}).\nNo canal: toque e segure a mensagem → Fixar. "
                              "(Ou dê ao robô a permissão \"Fixar mensagens\" nos administradores.)")


def agendar(chat_id, texto: str) -> None:
    if not fila.ativa():
        telegram.enviar_texto(chat_id, "❌ A fila precisa do Supabase configurado.")
        return
    ofertas = fila.separar_ofertas(texto)
    if not ofertas:
        telegram.enviar_texto(chat_id, "Não achei links na mensagem. Mande um por linha.")
        return
    # Links do Mercado Livre sem o SEU afiliado (de outro canal ou link normal): pede o meli.la ao
    # ajudante AGORA, todos de uma vez. Cada oferta entra na fila sozinha quando o link ficar pronto.
    pedidas, sem_produto = 0, 0
    if ajudante.ativo() and ajudante.usado_recentemente(7):
        ficam = []
        for oferta in ofertas:
            link = (fila.RE_LINK.search(oferta) or [""])[0].rstrip(").,")
            try:
                if mercadolivre.e_mercadolivre(link) and not mercadolivre.link_meu(link)[0]:
                    item_ml, catalogo_ml = mercadolivre.codigos_do_link(link)
                    if catalogo_ml or item_ml:
                        url_ml = (f"https://www.mercadolivre.com.br/p/{catalogo_ml}" if catalogo_ml
                                  else f"https://produto.mercadolivre.com.br/MLB-{item_ml[3:]}")
                        ajudante.pedir(f"ml:{catalogo_ml or item_ml}", url_ml,
                                       {"texto": oferta, "link_original": link})
                        pedidas += 1
                    else:
                        sem_produto += 1
                    continue
            except Exception as erro:  # noqa: BLE001
                print(f"::warning::Ajudante (lista): {str(erro)[:150]}")
            ficam.append(oferta)
        ofertas = ficam
    aviso_ml = ""
    if pedidas:
        aviso_ml += (f"\n🧩 {pedidas} link(s) do Mercado Livre sem o seu afiliado: pedi o SEU meli.la ao ajudante"
                     + (" (ligado — ficam prontos em alguns minutos)." if ajudante.ligado() else
                        " (DESLIGADO agora — gera quando o Edge abrir; vale por 48 h).")
                     + " Entram na fila sozinhos.")
    if sem_produto:
        aviso_ml += f"\n⚠️ {sem_produto} link(s) do Mercado Livre eu não consegui identificar o produto — pulei."
    if not ofertas:
        telegram.enviar_texto(chat_id, aviso_ml.strip() or "Não sobrou nenhuma oferta para a fila.")
        return
    total, proxima, ignorados = fila.adicionar(ofertas)
    novas = len(ofertas) - ignorados
    aviso = (f"\n♻️ {ignorados} link(s) repetido(s) ignorado(s)." if ignorados else "") + aviso_ml
    for oferta in ofertas:
        link = (fila.RE_LINK.search(oferta) or [""])[0]
        if amazon.e_amazon(link):
            novo_link, texto_tag = amazon.link_com_minha_tag(link)
            if not novo_link:
                aviso += f"\n\n{link}\n{texto_tag}\n(na hora dele o robô pula esse link)"
            elif novo_link != link:
                aviso += f"\n\n🔧 {link}\n{texto_tag} (o robô ajusta na hora do post)"
    telegram.enviar_texto(
        chat_id,
        f"🗓️ {novas} oferta(s) na fila (total: {total}).{aviso}\n"
        f"⏰ Próximo post: {proxima.strftime('%d/%m às %H:%M')}\n\n"
        "Mande /fila para ver a lista.",
    )


def agendar_foto(mensagem: dict, chat_id, texto: str, grupo: str) -> None:
    """Foto + link na legenda vai para a fila (álbum ou legenda começando com /agendar)."""
    if not fila.ativa():
        telegram.enviar_texto(chat_id, "❌ A fila precisa do Supabase configurado.")
        return
    if texto.lower().startswith("/agendar"):
        texto = texto.split(None, 1)[1] if " " in texto or "\n" in texto else ""
    maior = max(mensagem["photo"], key=lambda f: f.get("file_size", 0))
    total, proxima, repetida = fila.adicionar_foto(texto, maior["file_id"], mensagem["message_id"], grupo)
    links = len(fila.separar_ofertas(texto))
    if repetida:
        telegram.enviar_texto(chat_id, "♻️ Esse link já está na fila — ignorei.")
    elif links > 1 and grupo:
        telegram.enviar_texto(chat_id, f"🗓️📷 Recebi o álbum com {links} links — cada foto entra na fila com "
                                       "o link da mesma posição. Mande /fila daqui a 1 minuto para conferir.")
    elif links:
        telegram.enviar_texto(
            chat_id,
            f"🗓️📷 {'Oferta' if links == 1 else f'{links} links do álbum'} na fila com a sua foto "
            f"(total: {total}).\n⏰ Próximo post: {proxima.strftime('%d/%m às %H:%M')}\n\nMande /fila para conferir.")
    elif not grupo:
        telegram.enviar_texto(chat_id, "⚠️ Foto sem link na legenda — mande de novo com o link.")


def postar_da_fila() -> bool:
    """Se chegou a hora, posta o próximo item da fila. Um por rodada."""
    if not (fila.ativa() and config.ADMIN_CHAT_ID) or not fila.esta_na_hora():
        return False
    item = fila.retirar_proximo()
    if not item:
        return False
    restantes = len(fila.itens())
    telegram.enviar_texto(config.ADMIN_CHAT_ID,
                          f"🗓️ Postando da fila (faltam {restantes} depois deste)…")
    try:
        if item.get("foto_id"):
            mensagem = {"caption": item["texto"], "photo": [{"file_id": item["foto_id"], "file_size": 1}]}
        elif item.get("foto_url"):
            mensagem = {"text": item["texto"], "_foto_url": item["foto_url"]}
        else:
            mensagem = {"text": item["texto"]}
        processar_oferta(mensagem, config.ADMIN_CHAT_ID)
    except Exception:  # noqa: BLE001
        detalhe = traceback.format_exc()[-700:]
        print(detalhe, file=sys.stderr)
        telegram.enviar_texto(config.ADMIN_CHAT_ID, "❌ Erro no post da fila:\n" + detalhe)
    if restantes == 0:
        reabastecer.agendar()        # fila acabou: daqui a pouco entram ofertas novas
    return True


def _mensagens_pendentes() -> tuple[list[dict], bool]:
    """(mensagens, veio_do_webhook). No modo instantâneo a mensagem chega pronta
    pela entrada "update" do GitHub; no modo normal o robô busca no Telegram."""
    bruto = os.environ.get("UPDATE_JSON", "").strip()
    if bruto:
        try:
            dados = json.loads(bruto)
            if isinstance(dados, dict) and str(dados.get("ref", "")).startswith("busca_msg_"):
                # busca de seguidor: a mensagem ficou guardada no Supabase (não aparece nos registros públicos)
                guardada = (supabase.ler_config(dados["ref"]) or {}).get("valor") or ""
                supabase.apagar_config(dados["ref"])
                return ([json.loads(guardada)] if guardada else []), True
            return [dados], True
        except ValueError:
            print("UPDATE_JSON inválido", file=sys.stderr)
            return [], True
    try:
        return telegram.buscar_mensagens(None), False
    except RuntimeError as erro:
        if "webhook" in str(erro).lower() or "conflict" in str(erro).lower():
            return [], False      # modo instantâneo ligado: as mensagens vêm pelo webhook
        raise


def rodar_uma_vez() -> int:
    atualizacoes, pelo_webhook = _mensagens_pendentes()
    for upd in atualizacoes:
        # Confirma ANTES de processar: se algo travar, a mensagem não fica em loop
        if not pelo_webhook:
            telegram.confirmar_leitura(upd["update_id"])
        mensagem = upd.get("message")
        if not mensagem:
            continue
        try:
            tratar(mensagem)
        except PrecisaCompleto:
            raise
        except Exception:  # noqa: BLE001
            detalhe = traceback.format_exc()[-700:]
            print(detalhe, file=sys.stderr)
            try:
                telegram.enviar_texto(mensagem["chat"]["id"], "❌ Deu erro neste post:\n" + detalhe)
            except Exception:  # noqa: BLE001
                pass
    if pelo_webhook:
        # Rodadas do modo instantâneo só tratam a mensagem. Fila, relatório e
        # conferência ficam com a rodada de 10 min (evita post repetido quando
        # várias fotos chegam juntas e o robô roda várias vezes ao mesmo tempo).
        return len(atualizacoes)
    try:
        ajudante.importar(lambda texto: telegram.enviar_texto(config.ADMIN_CHAT_ID, texto))
    except Exception as erro:  # noqa: BLE001
        print("Ajudante:", erro, file=sys.stderr)
    try:
        cupons.postar_se_for_hora(lambda texto: telegram.enviar_texto(config.ADMIN_CHAT_ID, texto))
    except Exception as erro:  # noqa: BLE001
        print("Cupons agendados:", erro, file=sys.stderr)
    try:
        quadro.importar(lambda texto: telegram.enviar_texto(config.ADMIN_CHAT_ID, texto))
    except Exception as erro:  # noqa: BLE001
        print("Quadro:", erro, file=sys.stderr)
    try:
        postar_da_fila()
    except Exception as erro:  # noqa: BLE001
        print("Fila:", erro, file=sys.stderr)
    try:
        reabastecer.se_for_hora(lambda texto: telegram.enviar_texto(config.ADMIN_CHAT_ID, texto))
    except Exception as erro:  # noqa: BLE001
        print("Fila automática:", erro, file=sys.stderr)
    try:
        ranking.se_for_hora(lambda texto: telegram.enviar_texto(config.ADMIN_CHAT_ID, texto))
    except Exception as erro:  # noqa: BLE001
        print("Top 5:", erro, file=sys.stderr)
    try:
        aindavale.postar_se_for_hora(lambda texto: telegram.enviar_texto(config.ADMIN_CHAT_ID, texto))
    except Exception as erro:  # noqa: BLE001
        print("Ainda vale:", erro, file=sys.stderr)
    try:
        top.postar_se_for_hora()
    except Exception as erro:  # noqa: BLE001
        print("Top do dia:", erro, file=sys.stderr)
    try:
        quedas.postar_se_for_hora(lambda texto: telegram.enviar_texto(config.ADMIN_CHAT_ID, texto))
    except Exception as erro:  # noqa: BLE001
        print("Quedas:", erro, file=sys.stderr)
    try:
        relatorio.enviar_se_for_hora(lambda texto: telegram.enviar_texto(config.ADMIN_CHAT_ID, texto))
    except Exception as erro:  # noqa: BLE001
        print("Relatório:", erro, file=sys.stderr)
    try:
        sugestoes.sugerir_se_for_hora(lambda texto: telegram.enviar_texto(config.ADMIN_CHAT_ID, texto))
    except Exception as erro:  # noqa: BLE001
        print("Ofertas sugeridas:", erro, file=sys.stderr)
    try:
        verificador.conferir_se_for_hora(lambda texto: telegram.enviar_texto(config.ADMIN_CHAT_ID, texto))
    except Exception as erro:  # noqa: BLE001
        print("Conferência:", erro, file=sys.stderr)
    try:   # erros de preço vistos nas buscas desta rodada + histórico de preços
        sugestoes.avisar_bugs(lambda texto: telegram.enviar_texto(config.ADMIN_CHAT_ID, texto))
        precos.salvar()
    except Exception as erro:  # noqa: BLE001
        print("Histórico de preços/bugs:", erro, file=sys.stderr)
    return len(atualizacoes)


def modo_teste() -> None:
    """Gera arte e vídeo com um produto fictício, para conferir o visual."""
    from PIL import Image, ImageDraw

    pasta = config.PASTA_SAIDA / "teste"
    pasta.mkdir(parents=True, exist_ok=True)
    foto = pasta / "foto_exemplo.jpg"
    img = Image.new("RGB", (1000, 1000), "white")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((300, 180, 700, 820), 200, fill="#1F2937")
    d.line((500, 180, 500, 430), fill="#9CA3AF", width=10)
    d.rounded_rectangle((475, 260, 525, 360), 25, fill="#22D3EE")
    img.save(foto)

    produto = Produto(link="https://meli.la/exemplo", nome="Mouse Gamer Sem Fio RGB 7200 DPI Recarregável",
                      preco=89.90, preco_antigo=149.90)
    textos, origem = legenda.gerar_textos(produto)
    print("Textos:", origem)
    print(arte.arte_feed(produto, textos, [foto], pasta / "arte_feed.jpg"))
    caminho, voz = video.gerar_video(produto, textos, [foto], pasta)
    print(caminho, "narração:", voz)
    print("\n" + legenda.montar_legenda(produto, textos, com_link=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Robô Drop Certo")
    parser.add_argument("--continuo", action="store_true", help="fica ligado respondendo na hora")
    parser.add_argument("--teste", action="store_true", help="gera exemplo sem internet")
    parser.add_argument("--canais", action="store_true", help="só lê os canais-fonte (rodada leve)")
    args = parser.parse_args()

    if args.canais:
        n = canais.rodar(lambda texto: telegram.enviar_texto(config.ADMIN_CHAT_ID, texto))
        print(f"Canais-fonte: {n} oferta(s) nova(s).")
        return

    if args.teste:
        modo_teste()
        return
    if not config.TELEGRAM_TOKEN:
        sys.exit("Falta o TELEGRAM_TOKEN (token do BotFather).")
    if args.continuo:
        print("Robô ligado. Ctrl+C para parar.")
        while True:
            try:
                rodar_uma_vez()
            except Exception as erro:  # noqa: BLE001
                print("Erro:", erro, file=sys.stderr)
            time.sleep(5)
    else:
        try:
            print(f"Mensagens processadas: {rodar_uma_vez()}")
        except PrecisaCompleto as pedido:
            print("Esta mensagem precisa da rodada completa (arte/vídeo).")
            sys.exit(10 if pedido.avisou else 11)


if __name__ == "__main__":
    main()

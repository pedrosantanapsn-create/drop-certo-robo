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

from robo import amazon, arte, config, fila, instagram, instantaneo, legenda, mercadolivre, quadro, quedas, recorte, relatorio, shopee, sugestoes, supabase, telegram, tiktok, verificador, video
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
/intervalo auto — 1 post por hora e 2 por hora no pico (padrão)
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
/site link + preco: — coloca SÓ no site (quando o post saiu sem preço)
/cupom CODIGO descrição — publica um cupom no canal (mande /cupom sozinho para ver o modelo)
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


def processar_oferta(mensagem: dict, chat_id) -> None:
    texto = mensagem.get("text") or mensagem.get("caption") or ""
    dados = ler_mensagem(texto)
    if not dados.get("link"):
        telegram.enviar_texto(chat_id, "Não achei um link na mensagem. Mande /ajuda para ver o formato.")
        return

    telegram.enviar_texto(chat_id, "⏳ Recebi! Montando arte, vídeo e legenda…")
    pasta = nova_pasta()
    status: list[str] = []

    # 1. Dados do produto
    try:
        produto = buscar_produto(dados)
    except Exception as erro:  # noqa: BLE001
        produto = Produto(link=dados["link"], nome=dados.get("nome", ""), preco=dados.get("preco"),
                          preco_antigo=dados.get("preco_antigo"), observacao=dados.get("observacao", ""),
                          cupom=dados.get("cupom", ""), cupom_info=dados.get("cupom_info", ""))
        status.append(f"• Leitura do anúncio falhou ({str(erro)[:60]})")

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
            produto.bloqueado = False
            status.append("• Dados lidos pela API oficial da Shopee ✅")
        except Exception as erro:  # noqa: BLE001
            status.append(f"• API da Shopee: {str(erro)[:120]}")
            print(f"::warning::API da Shopee: {str(erro)[:200]}")

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

    if re.search(r"mercadolivre\.com\.br/(p/|MLB)", produto.link, re.I) and "meli.la" not in produto.link \
            and not re.search(r"matt_|forceInApp|social/", produto.link):
        telegram.enviar_texto(chat_id, "⚠️ Esse é o link normal do Mercado Livre, sem o seu afiliado — "
                              "vendas por ele NÃO pagam comissão.\n\nAbra o produto, toque em "
                              "\"Compartilhar\" na barra de afiliados, copie o link meli.la e mande de novo.\n"
                              "🛑 Não postei.")
        shutil.rmtree(pasta, ignore_errors=True)
        return

    # Mercado Livre com a API oficial: nome, preço com promoção e fotos sem depender da página
    if mercadolivre.e_mercadolivre(produto.link) and not dados.get("preco"):
        try:
            oficial = mercadolivre.ler(produto.link)
            if oficial.get("preco"):
                if oficial.get("nome") and not dados.get("nome") and (
                        not produto.nome or produto.nome_do_link or produto.bloqueado):
                    produto.nome, produto.nome_do_link = str(oficial["nome"]).strip(), False
                produto.preco = oficial["preco"]
                produto.preco_antigo = oficial.get("preco_antigo")
                if oficial.get("imagens") and (not produto.imagens or produto.bloqueado):
                    produto.imagens = oficial["imagens"]
                produto.bloqueado = False
                status.append("• Dados lidos pela API oficial do Mercado Livre ✅")
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

    # 2. Textos
    textos, origem = legenda.gerar_textos(produto)
    status.append(f"• Textos: {origem}")

    # 3. Arte e vídeo
    caminho_arte = arte.arte_feed(produto, textos, fotos, pasta / "arte_feed.jpg")
    try:
        caminho_video, com_voz = video.gerar_video(produto, textos, fotos, pasta)
        if com_voz:
            status.append(f"• Vídeo: pronto com narração ({video.voz_usada})")
        else:
            status.append(f"• Vídeo: pronto (sem narração — {video.motivo_sem_voz[:200]})")
    except Exception as erro:  # noqa: BLE001
        caminho_video = None
        status.append(f"• Vídeo falhou: {str(erro)[:120]}")

    # 4. Canal do Telegram (com o link clicável)
    if config.AUTO_POSTAR_CANAL and config.CANAL_ID:
        try:
            telegram.enviar_foto(config.CANAL_ID, caminho_arte,
                                 legenda.montar_legenda(produto, textos, com_link=True))
            status.append(f"• Canal {config.CANAL_ID}: publicado ✅")
        except Exception as erro:  # noqa: BLE001
            status.append(f"• Canal: erro — {str(erro)[:120]}")

    # 4b. Instagram (Reels automático)
    legenda_redes = legenda.montar_legenda(produto, textos, com_link=False)
    limite_ig = config.INSTAGRAM_MAX_DIA
    feitos_ig = relatorio.postados_hoje("instagram") if (limite_ig and supabase.ativo()) else 0
    if caminho_video and instagram.ativo() and limite_ig and feitos_ig >= limite_ig:
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
    limite_tt = config.TIKTOK_MAX_DIA
    feitos_tt = relatorio.postados_hoje("tiktok") if (limite_tt and supabase.ativo()) else 0
    if caminho_video and tiktok.ativo() and limite_tt and feitos_tt >= limite_tt:
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

    # 5. Site (Supabase)
    if supabase.ativo():
        if fotos:
            try:
                supabase.cadastrar_produto(produto, fotos[0], textos["legenda"])
                status.append("• Site: produto cadastrado ✅")
            except Exception as erro:  # noqa: BLE001
                status.append(f"• Site: erro — {str(erro)[:160]}\n  (mande /colunas para conferir os nomes)")
        else:
            status.append("• Site: não cadastrado (sem foto)")
    if supabase.ativo() and produto.preco is None:
        status.append("  👉 Para pôr no site depois, sem postar de novo: /site link + linha  preco: 89,90")

    # 6. Entrega para você publicar no TikTok (e no Instagram, se não for automático)
    if caminho_video:
        telegram.enviar_video(chat_id, caminho_video, "🎬 Vídeo para Reels/TikTok/Shorts", capa=None)
    telegram.enviar_arquivo(chat_id, caminho_arte, "🖼️ Arte do feed (arquivo em qualidade máxima)")
    telegram.enviar_texto(chat_id, "📋 Legenda para Instagram/TikTok (copie e cole):\n\n" + legenda_redes)
    if config.BOTAO_WHATSAPP:
        try:
            from urllib.parse import quote
            texto_zap = legenda.montar_legenda(produto, textos, com_link=True)
            telegram.enviar_com_botao(
                chat_id,
                "📲 WhatsApp: toque no botão, escolha o seu canal ou grupo e envie.\n"
                "(Baixe a arte acima e anexe junto, se quiser a imagem.)",
                "📲 Mandar no WhatsApp", "https://wa.me/?text=" + quote(texto_zap[:1800]))
        except Exception as erro:  # noqa: BLE001
            print("Botão WhatsApp:", erro, file=sys.stderr)

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
        return  # ignora qualquer outra pessoa

    # Mensagem de sugestões copiada inteira e reenviada: usa só os links (um por linha)
    if any(marca in texto for marca in ("sugestões com o SEU link", "Todos os links (copie",
                                        "mais vendidos com desconto", "Ofertas sugeridas para o Drop Certo",
                                        "Amazon — promoções para o Drop Certo")):
        links = list(dict.fromkeys(l.rstrip(").,;!?") for l in fila.RE_LINK.findall(texto)
                                   if "google.com/search" not in l and "/search?" not in l and "/s?k=" not in l
                                   and "mercadolivre.com.br/p/" not in l and "netlify.app/quadro" not in l))   # link do ML sem afiliado: não posta
        texto = "\n".join(links)
        if not links:
            telegram.enviar_texto(chat_id, "Essa lista não tem links de afiliado seus. No Mercado Livre, "
                                  "gere o meli.la de cada produto e mande esses links.")
            return
        if len(links) > 1:
            texto = "/agendar " + texto
    comando = texto.split()[0].lower() if texto else ""
    print(f"::notice::Mensagem: {len(texto.splitlines())} linha(s), "
          f"{len(fila.separar_ofertas(texto))} oferta(s) com link")
    grupo = str(mensagem.get("media_group_id") or "")
    if mensagem.get("photo") and (grupo or comando == "/agendar"):
        agendar_foto(mensagem, chat_id, texto, grupo)
        return
    if comando == "/start" and len(texto.split()) > 1 and texto.split()[1].startswith("ml_"):
        comando, texto = "/ml", "/ml " + texto.split()[1][3:]     # volta da autorização do ML
    if comando in ("/start", "/ajuda", "/help"):
        telegram.enviar_texto(chat_id, AJUDA)
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
    elif comando in ("/ofertas_ml", "/ofertasml", "/ml_ofertas") or (
            comando == "/ofertas" and texto.split()[1:2] in (["ml"], ["ML"], ["mercadolivre"])):
        palavras = [p for p in texto.split()[1:] if p.lower() not in ("ml", "mercadolivre")]
        palavra = " ".join(palavras).strip()
        telegram.enviar_texto(chat_id, f"🛒 Buscando os mais vendidos do Mercado Livre{f': {palavra}' if palavra else ''}…")
        try:
            telegram.enviar_html(chat_id, sugestoes.sugerir_ml([palavra] if palavra else None, html=True))
        except Exception as erro:  # noqa: BLE001
            telegram.enviar_texto(chat_id, f"❌ Mercado Livre: {str(erro)[:200]}")
    elif comando == "/site":
        so_site(mensagem, chat_id, texto.split(None, 1)[1] if len(texto.split(None, 1)) > 1 else "")
    elif comando == "/cupom":
        postar_cupom(chat_id, texto)
    elif comando == "/ofertas":
        telegram.enviar_texto(chat_id, "🔎 Procurando ofertas…")
        telegram.enviar_texto(chat_id, sugestoes.sugerir())
        extra = sugestoes.sugerir_shopee()
        if extra:
            telegram.enviar_texto(chat_id, extra)
    elif comando == "/shopee":
        palavra = " ".join(texto.split()[1:]).strip()
        telegram.enviar_texto(chat_id, f"🛍️ Buscando na Shopee{f': {palavra}' if palavra else ''}…")
        try:
            resposta = sugestoes.sugerir_shopee([palavra] if palavra else None) or \
                "❌ A API da Shopee não está configurada (faltam SHOPEE_APP_ID/SHOPEE_APP_SECRET)."
        except Exception as erro:  # noqa: BLE001
            resposta = f"❌ Shopee: {str(erro)[:200]}"
        telegram.enviar_texto(chat_id, resposta)
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
        telegram.enviar_texto(chat_id, fila.resumo())
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
            telegram.enviar_texto(chat_id, f"⏱️ 1 post por hora; no pico ({config.HORARIOS_PICO.replace(',', ' e ')}) "
                                           f"2 por hora.")
        elif valor == "pico":
            fila.definir_modo("pico")
            telegram.enviar_texto(chat_id, "⏱️ Só horários de pico: a fila sai primeiro no almoço e à noite.")
        elif valor == "igual":
            fila.definir_modo("igual")
            telegram.enviar_texto(chat_id, f"⏱️ A fila vai ser espalhada por igual até as {config.POSTAR_ATE}h.")
        else:
            telegram.enviar_texto(chat_id, "Use assim: /intervalo auto (1 por hora, 2 no pico), /intervalo pico, /intervalo igual ou /intervalo 60")
    elif comando == "/agendar" or len(fila.separar_ofertas(texto)) > 1:
        agendar(chat_id, texto.split(None, 1)[1] if comando == "/agendar" and " " in texto else texto)
    elif comando == "/colunas":
        telegram.enviar_texto(chat_id, supabase.listar_colunas() if supabase.ativo()
                              else "Supabase não configurado.")
    else:
        processar_oferta(mensagem, chat_id)


def so_site(mensagem: dict, chat_id, texto: str) -> None:
    """/site link + preco: — cadastra SÓ no site (sem postar de novo no canal/Instagram/TikTok).
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

/cupom DROP10 10% off em eletrônicos
https://s.shopee.com.br/seu-link
validade: 20/10

• 1ª linha: o código e o que ele dá
• link de afiliado da loja/produto (opcional, mas recomendado)
• validade (recomendado — cupom vencido gera reclamação)

Para usar cupom num produto, coloque a linha "cupom: CODIGO o que dá" embaixo do link:
https://meli.la/abc123
cupom: DROP10 10% off"""


def postar_cupom(chat_id, texto: str) -> None:
    """/cupom CODIGO descrição [link] [validade: dd/mm] → post de texto no canal do Telegram."""
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    primeira = linhas[0].split(None, 2) if linhas else []
    if len(primeira) < 2:
        telegram.enviar_texto(chat_id, MODELO_CUPOM)
        return
    codigo = primeira[1].upper()
    descricao = primeira[2] if len(primeira) > 2 else ""
    link = next((m.group(0).rstrip(").,") for l in linhas for m in [fila.RE_LINK.search(l)] if m), "")
    validade = next((l.split(":", 1)[1].strip() for l in linhas[1:]
                     if l.lower().startswith(("validade", "valido", "válido", "ate", "até"))), "")
    if link and amazon.e_amazon(link):
        novo, _ = amazon.link_com_minha_tag(link)
        link = novo or link
    partes = [f"🎟️ CUPOM: {codigo}"]
    if descricao:
        partes.append(f"✅ {descricao}")
    if validade:
        partes.append(f"⏰ Válido até {validade}")
    if link:
        partes.append(f"🛒 {link}")
    partes += ["", "Copie o código e use no carrinho/finalização da compra.",
               "Regras e validade conforme a loja; o cupom pode acabar antes do prazo.", "",
               config.AVISO_LEGAL + (f"\n{amazon.AVISO}" if link and amazon.e_amazon(link) else "")]
    post = "\n".join(partes)
    if not (config.AUTO_POSTAR_CANAL and config.CANAL_ID):
        telegram.enviar_texto(chat_id, "Canal não configurado. Veja como ficaria:\n\n" + post)
        return
    telegram.enviar_texto(config.CANAL_ID, post)
    aviso = "" if validade else "\n\n💡 Dica: coloque \"validade: dd/mm\" para o seguidor saber até quando vale."
    telegram.enviar_texto(chat_id, f"✅ Cupom {codigo} publicado no canal {config.CANAL_ID}.{aviso}")


def agendar(chat_id, texto: str) -> None:
    if not fila.ativa():
        telegram.enviar_texto(chat_id, "❌ A fila precisa do Supabase configurado.")
        return
    ofertas = fila.separar_ofertas(texto)
    if not ofertas:
        telegram.enviar_texto(chat_id, "Não achei links na mensagem. Mande um por linha.")
        return
    total, proxima, ignorados = fila.adicionar(ofertas)
    novas = len(ofertas) - ignorados
    aviso = f"\n♻️ {ignorados} link(s) repetido(s) ignorado(s)." if ignorados else ""
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
    return True


def _mensagens_pendentes() -> tuple[list[dict], bool]:
    """(mensagens, veio_do_webhook). No modo instantâneo a mensagem chega pronta
    pela entrada "update" do GitHub; no modo normal o robô busca no Telegram."""
    bruto = os.environ.get("UPDATE_JSON", "").strip()
    if bruto:
        try:
            return [json.loads(bruto)], True
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
        quadro.importar(lambda texto: telegram.enviar_texto(config.ADMIN_CHAT_ID, texto))
    except Exception as erro:  # noqa: BLE001
        print("Quadro:", erro, file=sys.stderr)
    try:
        postar_da_fila()
    except Exception as erro:  # noqa: BLE001
        print("Fila:", erro, file=sys.stderr)
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
    args = parser.parse_args()

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
        print(f"Mensagens processadas: {rodar_uma_vez()}")


if __name__ == "__main__":
    main()

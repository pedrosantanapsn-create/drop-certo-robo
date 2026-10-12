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
import shutil
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from robo import arte, config, fila, instagram, legenda, relatorio, supabase, telegram, tiktok, verificador, video
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
O robô posta um por vez nos horários de mais movimento
(almoço e noite primeiro), entre 8h e 22h.
Para agendar um link só: /agendar meli.la/abc123

Comandos:
/fila — mostra o que está agendado
/agora — posta o próximo da fila agora
/intervalo 60 — um post a cada 60 min
/intervalo igual — espalha por igual no dia
/intervalo auto — volta aos horários de pico
/limpar — apaga a fila
/id — mostra seu ID do Telegram
/colunas — mostra as colunas da tabela do site
/instagram — confere a ligação com o Instagram
/tiktok — confere a ligação com o TikTok
/relatorio — posts e cliques dos últimos 7 dias (/relatorio 30 = 30 dias)
/conferir — confere agora preços e ofertas esgotadas do site
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
                          preco_antigo=dados.get("preco_antigo"), observacao=dados.get("observacao", ""))
        status.append(f"• Leitura do anúncio falhou ({str(erro)[:60]})")

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
    if produto.bloqueado:
        status.append("• A loja bloqueou a leitura automática")
    if produto.nome_do_link:
        status.append("• Nome tirado do link (mande um print da página para sair melhor)")

    if not produto.nome:
        telegram.enviar_texto(chat_id, FALHA_LEITURA.format(link=produto.link))
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
        status.append("• Vídeo: pronto" + (" com narração" if com_voz else " (sem narração)"))
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
    if caminho_video and instagram.ativo():
        try:
            link_post = instagram.publicar_reels(caminho_video, legenda_redes, capa=caminho_arte)
            status.append(f"• Instagram: Reels publicado ✅ {link_post}")
        except Exception as erro:  # noqa: BLE001
            status.append(f"• Instagram: erro — {str(erro)[:160]}")

    # 4c. TikTok (pelo Zernio)
    if caminho_video and tiktok.ativo():
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

    # 6. Entrega para você publicar no TikTok (e no Instagram, se não for automático)
    if caminho_video:
        telegram.enviar_video(chat_id, caminho_video, "🎬 Vídeo para Reels/TikTok/Shorts", capa=None)
    telegram.enviar_arquivo(chat_id, caminho_arte, "🖼️ Arte do feed (arquivo em qualidade máxima)")
    telegram.enviar_texto(chat_id, "📋 Legenda para Instagram/TikTok (copie e cole):\n\n" + legenda_redes)

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

    if not config.ADMIN_CHAT_ID:
        telegram.enviar_texto(
            chat_id,
            f"Seu ID do Telegram é: {chat_id}\n\nCadastre esse número no GitHub como o "
            "segredo ADMIN_CHAT_ID. Depois disso só você poderá usar o robô.",
        )
        return
    if str(chat_id) != config.ADMIN_CHAT_ID:
        return  # ignora qualquer outra pessoa

    comando = texto.split()[0].lower() if texto else ""
    if comando in ("/start", "/ajuda", "/help"):
        telegram.enviar_texto(chat_id, AJUDA)
    elif comando == "/id":
        telegram.enviar_texto(chat_id, f"Seu ID: {chat_id}")
    elif comando == "/instagram":
        try:
            eu = instagram.conta()
            telegram.enviar_texto(chat_id, f"✅ Instagram ligado: @{eu.get('username')}")
        except Exception as erro:  # noqa: BLE001
            telegram.enviar_texto(chat_id, f"❌ Instagram não está ligado: {str(erro)[:200]}")
    elif comando == "/tiktok":
        try:
            c = tiktok.conta() if config.ZERNIO_API_KEY else None
            telegram.enviar_texto(chat_id, f"✅ TikTok ligado pelo Zernio: @{c.get('username')}" if c
                                  else "❌ TikTok não está ligado (falta o segredo ZERNIO_API_KEY no GitHub).")
        except Exception as erro:  # noqa: BLE001
            telegram.enviar_texto(chat_id, f"❌ TikTok: {str(erro)[:200]}")
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
        elif valor in ("auto", "automatico", "automático", "0", "pico"):
            fila.definir_modo("pico")
            telegram.enviar_texto(chat_id, "⏱️ Horários de pico: a fila sai primeiro no almoço e à noite.")
        elif valor == "igual":
            fila.definir_modo("igual")
            telegram.enviar_texto(chat_id, f"⏱️ A fila vai ser espalhada por igual até as {config.POSTAR_ATE}h.")
        else:
            telegram.enviar_texto(chat_id, "Use assim: /intervalo 60 (mínimo 20), /intervalo igual ou /intervalo auto")
    elif comando == "/agendar" or len(fila.separar_ofertas(texto)) > 1:
        agendar(chat_id, texto.split(None, 1)[1] if comando == "/agendar" and " " in texto else texto)
    elif comando == "/colunas":
        telegram.enviar_texto(chat_id, supabase.listar_colunas() if supabase.ativo()
                              else "Supabase não configurado.")
    else:
        processar_oferta(mensagem, chat_id)


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
    telegram.enviar_texto(
        chat_id,
        f"🗓️ {novas} oferta(s) na fila (total: {total}).{aviso}\n"
        f"⏰ Próximo post: {proxima.strftime('%d/%m às %H:%M')}\n\n"
        "Mande /fila para ver a lista.",
    )


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
        processar_oferta({"text": item["texto"]}, config.ADMIN_CHAT_ID)
    except Exception:  # noqa: BLE001
        detalhe = traceback.format_exc()[-700:]
        print(detalhe, file=sys.stderr)
        telegram.enviar_texto(config.ADMIN_CHAT_ID, "❌ Erro no post da fila:\n" + detalhe)
    return True


def rodar_uma_vez() -> int:
    atualizacoes = telegram.buscar_mensagens(None)
    for upd in atualizacoes:
        # Confirma ANTES de processar: se algo travar, a mensagem não fica em loop
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
    try:
        postar_da_fila()
    except Exception as erro:  # noqa: BLE001
        print("Fila:", erro, file=sys.stderr)
    try:
        relatorio.enviar_se_for_hora(lambda texto: telegram.enviar_texto(config.ADMIN_CHAT_ID, texto))
    except Exception as erro:  # noqa: BLE001
        print("Relatório:", erro, file=sys.stderr)
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

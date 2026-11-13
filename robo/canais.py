"""Canais-fonte: lê canais PÚBLICOS de ofertas no Telegram e põe as ofertas na fila com o SEU link.

O robô abre a página pública do canal (t.me/s/nome — não precisa de conta nem de login),
pega de cada post novo só os FATOS (produto, preço, cupom e o link da loja) e manda para a
fila. O texto, a arte e o vídeo são os seus, feitos como sempre; o link do outro canal é
trocado pelo seu na hora do post (Amazon, Shopee, KaBuM, Terabyte) ou pelo ajudante (meli.la).

Filtros: só tecnologia/peças de PC ou marca conhecida · o mesmo produto só volta depois de
CANAIS_REPETIR_HORAS (e nunca enquanto está na fila) · no máximo CANAIS_MAX_DIA ofertas por dia ·
não enche a fila além de CANAIS_FILA_MAX.
Posts só de cupom não vão para a fila: o robô publica o cupom direto no canal (código + fatos + o SEU link;
CANAIS_CUPONS_AUTO=false volta a só avisar). O que ele não entende, manda para você divulgar com /cupom.

Comandos: /canais · /canal_add @nome · /canal_tirar @nome
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

from . import ajudante, config, copiar, fila, marcas, mercadolivre, supabase

CHAVE_LISTA = "canais_fonte"
CHAVE_ESTADO = "canais_estado"          # {canal: último post lido}
CHAVE_VISTOS = "canais_produtos"        # nomes de produtos já pegos (para não repetir entre canais)
CHAVE_DIA = "canais_dia"                # {"dia": "yymmdd", "n": quantas hoje}
CHAVE_PROXIMO = "canais_proximo"
RE_NOME_CANAL = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
RE_NICHO = re.compile(r"ssd|hd\b|mem[oó]ria|ram\b|placa|processador|ryzen|intel|geforce|rtx|gtx|radeon|rx\s?\d|"
                      r"monitor|teclado|mouse|headset|fone|webcam|microfone|gabinete|fonte|cooler|notebook|"
                      r"pc gamer|gamer|roteador|pen ?drive|controle|cadeira|mousepad|placa-m[ãa]e|nvme|ddr\d", re.I)


def _json(chave: str, padrao):
    try:
        return json.loads((supabase.ler_config(chave) or {}).get("valor") or "") or padrao
    except ValueError:
        return padrao


def lista() -> list[str]:
    return _json(CHAVE_LISTA, [])


def _limpar_nome(nome: str) -> str:
    nome = (nome or "").strip()
    nome = re.sub(r"^(https?://)?(www\.)?(t\.me|telegram\.me)/(s/)?", "", nome, flags=re.I).lstrip("@").split("/")[0]
    return nome if RE_NOME_CANAL.match(nome) else ""


def adicionar(nome: str) -> str:
    canal = _limpar_nome(nome)
    if not canal:
        return "Mande o @ ou o link do canal do Telegram. Ex.: /canal_add @nomedocanal"
    try:
        posts = ler_canal(canal)
    except Exception as erro:  # noqa: BLE001
        return f"❌ Não consegui abrir t.me/s/{canal} ({str(erro)[:100]})."
    if not posts:
        return (f"⚠️ @{canal}: a página pública não mostra posts (o canal é privado, não existe ou desligou a "
                "pré-visualização). Não dá para ler esse.")
    atual = lista()
    if canal.lower() not in [c.lower() for c in atual]:
        atual.append(canal)
        supabase.gravar_config(CHAVE_LISTA, json.dumps(atual))
    estado = _json(CHAVE_ESTADO, {})
    estado[canal] = max(p["id"] for p in posts)          # começa a partir de agora (não despeja o passado)
    supabase.gravar_config(CHAVE_ESTADO, json.dumps(estado))
    supabase.gravar_config(CHAVE_PROXIMO, "0")
    com_oferta = sum(1 for p in posts if _ofertas_do_post(p))
    return (f"📡 @{canal} adicionado. Li {len(posts)} posts recentes e {com_oferta} parecem ofertas que eu sei usar.\n"
            "A partir de agora, cada oferta nova de tecnologia desse canal entra na fila com o SEU link.")


def tirar(nome: str) -> str:
    canal = _limpar_nome(nome)
    atual = lista()
    novo = [c for c in atual if c.lower() != canal.lower()]
    if len(novo) == len(atual):
        return "Esse canal não está na lista. Veja em /canais."
    supabase.gravar_config(CHAVE_LISTA, json.dumps(novo))
    return f"🗑️ @{canal} saiu da lista de canais-fonte."


def resumo() -> str:
    canais = lista()
    if not canais:
        return ("📡 Nenhum canal-fonte ainda.\nAdicione um canal PÚBLICO do Telegram: /canal_add @nomedocanal\n"
                "O robô pega as ofertas de tecnologia dele e põe na fila com o seu link.")
    dia = _json(CHAVE_DIA, {})
    hoje = dia.get("n", 0) if dia.get("dia") == datetime.now(fila.FUSO).strftime("%y%m%d") else 0
    return ("📡 Canais-fonte:\n" + "\n".join(f"• @{c}" for c in canais)
            + f"\n\nHoje: {hoje} de {config.CANAIS_MAX_DIA} ofertas pegas."
            + "\n/canal_add @nome · /canal_tirar @nome")


def ler_canal(canal: str) -> list[dict]:
    """Posts recentes da página pública: [{id, texto, foto}] (do mais antigo para o mais novo)."""
    r = requests.get(f"https://t.me/s/{canal}", timeout=30, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept-Language": "pt-BR,pt;q=0.9"})
    r.raise_for_status()
    sopa = BeautifulSoup(r.text, "html.parser")
    posts = []
    for bloco in sopa.select("div.tgme_widget_message[data-post]"):
        try:
            ident = int(str(bloco["data-post"]).rsplit("/", 1)[1])
        except (ValueError, IndexError):
            continue
        corpo = bloco.select_one(".tgme_widget_message_text")
        if not corpo:
            continue
        for br in corpo.find_all("br"):
            br.replace_with("\n")
        for a in corpo.find_all("a", href=True):          # link "escondido" atrás de um texto: mostra o endereço
            href = a["href"]
            if href.startswith("http") and href not in a.get_text():
                a.replace_with(f"{a.get_text()} {href} ")
        texto = corpo.get_text()
        foto = ""
        # foto do post; se não tiver, a capa do vídeo ou a imagem da prévia do link
        for seletor in (".tgme_widget_message_photo_wrap", ".tgme_widget_message_video_thumb",
                        ".link_preview_image", ".link_preview_right_image"):
            capa = bloco.select_one(seletor)
            achado = re.search(r"url\('([^']+)'\)", capa.get("style") or "") if capa else None
            if achado:
                foto = achado.group(1)
                break
        posts.append({"id": ident, "texto": texto, "foto": foto})
    return sorted(posts, key=lambda p: p["id"])


# Lojas em que a dona é afiliada (o robô sabe trocar o link pelo dela)
RE_LOJAS = re.compile(r"shopee\.|shp\.ee|meli\.la|mercadoli[bv]re\.com|amazon\.com\.br|amzn\.to|a\.co/|"
                      r"kabum\.com\.br|terabyteshop\.com\.br|awin1\.com|tidd\.ly", re.I)


def _link_de_loja_afiliada(link: str) -> str:
    """O link (abrindo encurtadores como aoferta.net) se for de loja em que ela é afiliada; senão ''."""
    url = link
    for _ in range(5):
        if RE_LOJAS.search(url):
            return link
        try:
            r = requests.get(url, allow_redirects=False, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        except requests.RequestException:
            return ""
        proximo = r.headers.get("Location")
        if not proximo:
            return ""
        url = requests.compat.urljoin(url, proximo)
    return link if RE_LOJAS.search(url) else ""


def _campo(oferta: str, nome: str) -> str:
    achado = re.search(rf"^{nome}:\s*(.+)$", oferta, re.M)
    return achado.group(1).strip() if achado else ""


def _ofertas_do_post(post: dict) -> list[str]:
    """Ofertas (texto no formato do robô) que servem: têm link de loja, nome e são de tecnologia."""
    boas = []
    for oferta in copiar.separar(post["texto"]):
        nome = _campo(oferta, "nome")
        if not nome or not (RE_NICHO.search(nome) or marcas.conhecida(nome)):
            continue
        link = oferta.splitlines()[0]
        # Shopee e Mercado Livre dão a foto pela API; nas outras (Amazon, Terabyte, encurtadores como
        # link.amazon…) o robô não consegue fotografar sozinho: leva a foto do post
        if not re.search(r"shopee\.|shp\.ee|meli\.la|mercadoli[bv]re", link, re.I) and post.get("foto") \
                and "\nfoto:" not in oferta:
            oferta += f"\nfoto: {post['foto']}"       # lojas que o robô não consegue fotografar sozinho
        boas.append(oferta)
    return boas


def _guardar_foto(oferta: str) -> str:
    """O endereço da foto no Telegram vence em poucas horas, e a oferta pode esperar na fila mais que
    isso (aí o post saía sem imagem). Copia a foto agora para o nosso Supabase (pasta posts/, que é
    limpa sozinha depois de 3 dias) e troca o endereço na oferta."""
    achado = re.search(r"^foto:\s*(https?://\S+)$", oferta, re.M)
    if not achado or config.SUPABASE_URL in achado.group(1):
        return oferta
    try:
        import tempfile
        import time
        from pathlib import Path
        r = requests.get(achado.group(1), timeout=25, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        if len(r.content) < 2500:
            return oferta
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "foto.jpg"
            arquivo.write_bytes(r.content)
            novo = supabase.enviar_arquivo(arquivo, f"posts/canal_{int(time.time() * 1000)}.jpg", "image/jpeg")
        return oferta.replace(achado.group(1), novo)
    except Exception as erro:  # noqa: BLE001
        print(f"::warning::Foto do canal: {str(erro)[:120]}")
        return oferta


def _e_so_cupom(texto: str) -> bool:
    return bool(re.search(r"cupo[mn]", texto, re.I)) and not re.search(r"R\$\s*\d", texto)


# ---------------------------------------------------------------------------
# Cupom visto em canal → post de cupom no SEU canal, com o SEU link
# ---------------------------------------------------------------------------
CHAVE_CUPONS = "canais_cupons"          # {"feitos": ["LOJA:CODIGO", …], "dia": "yymmdd", "n": quantos hoje}
RE_CODIGO = re.compile(r"(?i:cupo[mn])\s*:?\s*([A-Z0-9][A-Z0-9_-]{3,19})(?![a-zà-ú])")
RE_NAO_CODIGO = re.compile(r"^(KABUM|AMAZON|SHOPEE|TERABYTE|MERCADO|LIVRE|CUPOM|CUPONS|PARA|PRODUTOS|SELECIONADOS|"
                           r"DESCONTO|OFERTA|OFERTAS|NOVO|NOVOS|LIBERADO|ATIVO|RESGATE|AQUI)$")
LOJAS_CUPOM = (("Amazon", r"amazon\.com\.br|amzn\.to|a\.co/|link\.amazon"), ("Shopee", r"shopee\.|shp\.ee"),
               ("KaBuM", r"kabum\.com\.br"), ("Terabyte", r"terabyteshop\.com\.br"),
               ("Mercado Livre", r"meli\.la|mercadoli[bv]re\.com"))


def _ate_a_loja(link: str) -> str:
    """Segue encurtadores (e links da Awin de outra pessoa) até o endereço da loja."""
    from . import awin
    url = link
    for _ in range(6):
        if awin.e_link_awin(url):
            return awin.destino_se_for_de_outro(url) or url
        if RE_LOJAS.search(url) and not re.search(r"amzn\.to|a\.co/|link\.amazon|shp\.ee|s\.shopee|meli\.la", url, re.I):
            return url
        try:
            r = requests.get(url, allow_redirects=False, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        except requests.RequestException:
            return url
        proximo = r.headers.get("Location")
        if not proximo:
            return url
        url = requests.compat.urljoin(url, proximo)
    return url


def _meu_link(link: str) -> tuple[str, str]:
    """(nome da loja, SEU link de afiliada). Link vazio = não consegui gerar o seu (posta só o código).
    Loja vazia = loja em que você não é afiliada (não posta)."""
    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

    from . import awin, shopee
    destino = _ate_a_loja(link)
    loja = next((nome for nome, padrao in LOJAS_CUPOM if re.search(padrao, destino, re.I)), "")
    if not loja:
        return "", ""
    try:
        partes = urlparse(destino)
        params = dict(parse_qsl(partes.query))
        if loja == "Amazon" and config.AMAZON_TAG:
            params = {k: v for k, v in params.items() if k not in ("tag", "linkCode", "linkId", "ref_", "ascsubtag")}
            params["tag"] = config.AMAZON_TAG
            return loja, urlunparse(partes._replace(query=urlencode(params)))
        if loja == "Terabyte":
            params["p"], params["tag"] = config.TERABYTE_PARCEIRO, config.TERABYTE_TAG
            return loja, urlunparse(partes._replace(query=urlencode(params)))
        if loja == "Shopee" and shopee.ativo():
            return loja, shopee.link_afiliado(destino, "cupom")
        if loja == "KaBuM" and awin.ativo():
            return loja, awin.converter(destino)[1]
    except Exception as erro:  # noqa: BLE001
        print(f"::warning::Cupom ({loja}): {str(erro)[:120]}")
    return loja, ""            # Mercado Livre (só o meli.la vale) ou falha: sai sem link, só o código


def _descricao_cupom(texto: str) -> str:
    """Só os FATOS do cupom (valor, mínimo, onde vale) — nunca o texto do outro canal."""
    partes = []
    m = re.search(r"(\d{1,2})\s?%", texto)
    v = re.search(r"R\$\s?(\d[\d.]*(?:,\d{2})?)\s*(?:de\s+)?(?:off|desconto)", texto, re.I)
    if m:
        partes.append(f"{m.group(1)}% OFF")
    elif v:
        partes.append(f"R$ {v.group(1)} OFF")
    minimo = re.search(r"(?:acima de|a partir de|m[ií]nim\w*(?: de)?)\s*R\$\s?(\d[\d.]*(?:,\d{2})?)", texto, re.I)
    if minimo:
        partes.append(f"em compras acima de R$ {minimo.group(1)}")
    if re.search(r"selecionad", texto, re.I):
        partes.append("em produtos selecionados")
    return " ".join(partes)


def _postar_cupons(canal: str, texto: str, avisar) -> bool:
    """Posta no canal os cupons do post. False = não deu para postar sozinho (avisa a dona do jeito antigo)."""
    from . import cupons as post_cupom, telegram
    if not (config.CANAIS_CUPONS_AUTO and config.CANAL_ID):
        return False
    codigos = [c for c in dict.fromkeys(RE_CODIGO.findall(texto)) if not RE_NAO_CODIGO.match(c)
               and re.search(r"[A-Z]", c)][:3]
    links = [l.rstrip(").,;!?") for l in fila.RE_LINK.findall(texto)]
    links = [l for l in links if not copiar.RE_IGNORAR_LINK.search(l)]
    if not codigos:
        return False
    loja, meu = _meu_link(links[0]) if links else ("", "")
    if not loja:           # sem link: tenta achar a loja pelo texto
        loja = next((nome for nome, _ in LOJAS_CUPOM if nome.lower() in texto.lower()), "")
    if not loja:
        return False
    estado = _json(CHAVE_CUPONS, {})
    hoje = datetime.now(fila.FUSO).strftime("%y%m%d")
    if estado.get("dia") != hoje:
        estado["dia"], estado["n"] = hoje, 0
    feitos = list(estado.get("feitos") or [])
    descricao = _descricao_cupom(texto)
    for codigo in codigos:
        marca = f"{loja}:{codigo}"
        if marca in feitos:
            continue
        if estado["n"] >= config.CANAIS_CUPONS_DIA:
            break
        pedido = f"/cupom {codigo} {descricao}".strip() + f"\nloja: {loja}" + (f"\n{meu}" if meu else "")
        if not meu:
            pedido += (f"\n1. Abra a loja ({loja}) e adicione os produtos ao carrinho"
                       "\n2. Na finalização, toque em \"Cupom\" e cole o código\n3. Confira o desconto antes de pagar")
        post = post_cupom.montar(pedido)
        if not post:
            continue
        telegram.enviar_html(config.CANAL_ID, post["html"])
        feitos.append(marca)
        estado["n"] += 1
        avisar(f"🎟️ Cupom {codigo} ({loja}) publicado no canal — visto em @{canal}."
               + (" Link: o seu de afiliada." if meu else " Saiu SEM link (não consegui gerar o seu para essa loja).")
               + "\nNão conferi se o cupom ainda vale: se não valer, apague o post do canal.")
    estado["feitos"] = feitos[-300:]
    supabase.gravar_config(CHAVE_CUPONS, json.dumps(estado))
    return True


def _chave_produto(nome: str) -> str:
    return "".join(sorted(set(re.findall(r"[a-z0-9]{3,}", nome.lower()))))[:60]


def rodar(avisar) -> int:
    """Lê os canais e põe as ofertas novas na fila. Devolve quantas entraram."""
    if not supabase.ativo():
        return 0
    agora = datetime.now(fila.FUSO)
    supabase.gravar_config(CHAVE_PROXIMO, str(int((agora + timedelta(minutes=config.CANAIS_MINUTOS)).timestamp())))
    canais = lista()
    if not canais or not (8 <= agora.hour < 23):
        return 0
    hoje = agora.strftime("%y%m%d")
    dia = _json(CHAVE_DIA, {})
    if dia.get("dia") != hoje:
        dia = {"dia": hoje, "n": 0}
    estado, vistos = _json(CHAVE_ESTADO, {}), _json(CHAVE_VISTOS, {})
    carimbo = int(agora.timestamp())
    if isinstance(vistos, list):                 # formato antigo (só os nomes): vira {produto: quando foi pego}
        vistos = {c: carimbo for c in vistos}
    # O mesmo produto pode voltar (outro canal, ou de novo mais tarde), mas nunca perto do post anterior
    # nem enquanto ainda está esperando na fila.
    limite = carimbo - int(config.CANAIS_REPETIR_HORAS * 3600)
    itens_fila = fila.itens()
    na_fila = len(itens_fila)
    chaves_fila = {_chave_produto(_campo(str(i.get("texto") or ""), "nome")) for i in itens_fila}
    novas, pedidas, cupons, origem = [], 0, [], set()
    for canal in canais:
        try:
            posts = ler_canal(canal)
        except Exception as erro:  # noqa: BLE001
            print(f"::warning::Canal @{canal}: {str(erro)[:120]}")
            continue
        ultimo = int(estado.get(canal, 0))
        for post in posts:
            if post["id"] <= ultimo:
                continue
            estado[canal] = post["id"]
            if _e_so_cupom(post["texto"]):
                try:
                    postado = _postar_cupons(canal, post["texto"], avisar)
                except Exception as erro:  # noqa: BLE001
                    print(f"::warning::Cupom de @{canal}: {str(erro)[:150]}")
                    postado = False
                if not postado and len(cupons) < 3:
                    cupons.append(f"@{canal}:\n{post['texto'].strip()[:500]}")
                continue
            for oferta in _ofertas_do_post(post):
                if dia["n"] >= config.CANAIS_MAX_DIA or na_fila + len(novas) >= config.CANAIS_FILA_MAX:
                    break
                chave = _chave_produto(_campo(oferta, "nome"))
                if int(vistos.get(chave, 0)) > limite or chave in chaves_fila:
                    continue
                link = oferta.splitlines()[0]
                if not _link_de_loja_afiliada(link):
                    continue                              # loja em que você não é afiliada: não dá comissão
                vistos[chave] = carimbo
                chaves_fila.add(chave)
                oferta = _guardar_foto(oferta)
                try:       # Mercado Livre de outro canal: o ajudante gera o SEU meli.la e a oferta entra depois
                    if mercadolivre.e_mercadolivre(link) and not mercadolivre.link_meu(link)[0]:
                        if not (ajudante.ativo() and ajudante.usado_recentemente(7)):
                            continue
                        item, catalogo = mercadolivre.codigos_do_link(link)
                        if not (item or catalogo):
                            continue
                        url = (f"https://www.mercadolivre.com.br/p/{catalogo}" if catalogo
                               else f"https://produto.mercadolivre.com.br/MLB-{item[3:]}")
                        if ajudante.pedir(f"ml:{catalogo or item}", url, {"texto": oferta, "link_original": link}):
                            pedidas += 1
                            dia["n"] += 1
                            origem.add(canal)
                        continue
                except Exception as erro:  # noqa: BLE001
                    print(f"::warning::Canal @{canal} (ML): {str(erro)[:120]}")
                    continue
                novas.append(oferta)
                dia["n"] += 1
                origem.add(canal)
    supabase.gravar_config(CHAVE_ESTADO, json.dumps(estado))
    supabase.gravar_config(CHAVE_VISTOS, json.dumps(dict(sorted(vistos.items(), key=lambda kv: kv[1])[-600:])))
    supabase.gravar_config(CHAVE_DIA, json.dumps(dia))
    if novas:
        fila.adicionar(novas)
    if novas or pedidas:
        nomes = "\n".join("• " + (_campo(o, "nome")[:60]) for o in novas[:8])
        avisar(f"📡 Canais ({', '.join('@' + c for c in sorted(origem))}): {len(novas)} oferta(s) nova(s) na fila"
               + (f" e {pedidas} do Mercado Livre pedida(s) ao ajudante" if pedidas else "")
               + f".\n{nomes}\n\nHoje: {dia['n']} de {config.CANAIS_MAX_DIA}. /fila para ver.")
    for c in cupons:
        avisar("🎟️ Cupom visto em canal — confira se vale e divulgue com /cupom (use o SEU link):\n\n" + c)
    return len(novas) + pedidas

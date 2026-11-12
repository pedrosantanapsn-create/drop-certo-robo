"""Ajudante do Drop Certo — roda no SEU computador (Windows + Edge).

O que ele faz: usa um Edge separado, logado na SUA conta do Mercado Livre, para gerar o
link meli.la (o único que conta a comissão) dos produtos que o robô pedir. A senha da
conta fica só com você: quem faz o login é você, na janela do Edge.

Como usar (dê dois cliques nos arquivos .bat da pasta):
  1 - Instalar.bat        → instala o que precisa (uma vez só)
  2 - Fazer login.bat     → abre o Edge do ajudante para você entrar no Mercado Livre
  3 - Ligar ajudante.bat  → deixa o ajudante trabalhando (pode minimizar a janela)

Comandos (para quem quiser usar pelo terminal):
  python ajudante.py login
  python ajudante.py teste https://www.mercadolivre.com.br/p/MLB12345
  python ajudante.py            (fica ligado atendendo os pedidos do robô)
"""
from __future__ import annotations

import json
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from playwright.sync_api import TimeoutError as Demorou
from playwright.sync_api import sync_playwright

PASTA = Path(__file__).resolve().parent
# Navegador do ajudante: Chrome (padrão). Para usar o Edge, crie o arquivo navegador.txt escrito: edge
ARQUIVO_NAVEGADOR = PASTA / "navegador.txt"
NAVEGADOR = (ARQUIVO_NAVEGADOR.read_text(encoding="utf-8").strip().lower()
             if ARQUIVO_NAVEGADOR.exists() else "chrome")
CANAL = "msedge" if NAVEGADOR.startswith("edge") else "chrome"
NOME_NAVEGADOR = "Edge" if CANAL == "msedge" else "Chrome"
# o login fica guardado nesta pasta (não apague; não mande para ninguém)
PERFIL = PASTA / ("perfil-edge" if CANAL == "msedge" else "perfil-chrome")
ERROS = PASTA / "erros"
ARQUIVO_SENHA = PASTA / "senha.txt"

# Endereço e chave PÚBLICA do banco do Drop Certo (os mesmos do site). O que protege os pedidos
# é a senha do ajudante (senha.txt), que só você tem.
SUPABASE_URL = "https://euctzxrnxeizgtnmlesn.supabase.co"
CHAVE_PUBLICA = "sb_publishable_SMh-znhRJUnZCjBi4DH3hQ_yvkmIY6X"
TABELA = f"{SUPABASE_URL}/rest/v1/ajudante_pedidos"

GERADOR = "https://www.mercadolivre.com.br/afiliados/linkbuilder"
RE_MELI = re.compile(r"https?://meli\.la/[A-Za-z0-9]+")
ESPERA_SEM_PEDIDOS = 60          # segundos entre uma olhada e outra
PAUSA_ENTRE_LINKS = (20, 45)     # segundos entre um link e outro (sem pressa, para não sobrecarregar o site)
MAX_POR_HORA = 20
MAX_TENTATIVAS = 3


def dizer(texto: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {texto}", flush=True)


# ---------------------------------------------------------------------------
# Conversa com o robô (tabela ajudante_pedidos)
# ---------------------------------------------------------------------------
def _senha() -> str:
    if not ARQUIVO_SENHA.exists():
        sys.exit("Falta o arquivo senha.txt na pasta do ajudante (com a senha do ajudante dentro).")
    senha = ARQUIVO_SENHA.read_text(encoding="utf-8").strip()
    if len(senha) < 20:
        sys.exit("O arquivo senha.txt parece vazio ou incompleto. Cole nele a senha do ajudante.")
    return senha


def _cabecalhos(extra: dict | None = None) -> dict:
    h = {"apikey": CHAVE_PUBLICA, "Authorization": f"Bearer {CHAVE_PUBLICA}", "x-ajudante-chave": _senha()}
    h.update(extra or {})
    return h


def pedidos_pendentes() -> list[dict]:
    r = requests.get(TABELA, headers=_cabecalhos(), timeout=30, params={
        "status": "eq.pendente", "loja": "eq.ml", "select": "id,chave,url,dados", "order": "criado_em.asc",
        "limit": "5"})
    r.raise_for_status()
    return r.json()


def responder(ident: str, campos: dict) -> None:
    campos = {**campos, "feito_em": datetime.now(timezone.utc).isoformat()}
    r = requests.patch(TABELA, headers=_cabecalhos({"Content-Type": "application/json"}),
                       params={"id": f"eq.{ident}"}, json=campos, timeout=30)
    r.raise_for_status()


def sinal_de_vida(precisa_login: bool = False) -> None:
    """Avisa o robô que o ajudante está ligado (e se o login do Mercado Livre caiu)."""
    corpo = {"loja": "_sistema", "chave": "_batimento", "status": "sinal",
             "dados": {"precisa_login": precisa_login}, "feito_em": datetime.now(timezone.utc).isoformat()}
    r = requests.patch(TABELA, headers=_cabecalhos({"Content-Type": "application/json",
                                                    "Prefer": "return=representation"}),
                       params={"chave": "eq._batimento"}, json=corpo, timeout=30)
    if r.status_code == 404:
        sys.exit("O banco ainda não tem a tabela do ajudante. Rode o arquivo supabase/ajudante.sql no Supabase.")
    if r.status_code < 300 and r.json():
        return                                      # sinal atualizado
    # primeira vez (ou senha errada: aí o banco não deixa criar)
    r = requests.post(TABELA, headers=_cabecalhos({"Content-Type": "application/json"}), json=corpo, timeout=30)
    if r.status_code in (401, 403):
        sys.exit("A senha do ajudante (senha.txt) não foi aceita. Confira se copiou certo do Supabase.")
    if r.status_code >= 400 and r.status_code != 409:
        raise RuntimeError(f"sinal de vida: {r.status_code} {r.text[:150]}")


# ---------------------------------------------------------------------------
# Navegador (Edge com um perfil só do ajudante)
# ---------------------------------------------------------------------------
def abrir_edge(pw):
    """Abre o navegador do ajudante (Chrome ou Edge) com o perfil próprio dele."""
    PERFIL.mkdir(exist_ok=True)
    try:
        return pw.chromium.launch_persistent_context(
            str(PERFIL), channel=CANAL, headless=False, locale="pt-BR",
            chromium_sandbox=True,      # mantém a proteção normal do navegador (sem o aviso "--no-sandbox")
            viewport={"width": 1280, "height": 850}, args=["--start-maximized"])
    except Exception as erro:  # noqa: BLE001
        sys.exit(f"Não consegui abrir o {NOME_NAVEGADOR}. Ele está instalado neste computador?\n"
                 f"(Para usar o Edge, crie o arquivo navegador.txt com a palavra: edge)\n\nDetalhe: {str(erro)[:200]}")


def precisa_login(pagina) -> bool:
    endereco = pagina.url.lower()
    return any(p in endereco for p in ("/login", "/jms/", "registration", "account-verification", "/gz/account"))


class LoginCaiu(Exception):
    pass


def _achar_meli(textos: list[str]) -> str:
    for texto in textos:
        achado = RE_MELI.search(texto or "")
        if achado:
            return achado.group(0)
    return ""


def _textos_da_pagina(pagina) -> list[str]:
    """Tudo o que está escrito na tela e dentro das caixas de texto."""
    try:
        return pagina.evaluate("""() => {
            const campos = [...document.querySelectorAll('input, textarea')].map(e => e.value || '');
            return [document.body ? document.body.innerText : '', ...campos];
        }""")
    except Exception:  # noqa: BLE001
        return []


def gerar_meli(contexto, url_produto: str, guardar_erro: str = "") -> str:
    """Gera o meli.la do produto. Tenta o gerador de links do painel e, se não der, o botão
    "Compartilhar" da página do produto. Devolve '' se não conseguir."""
    pagina = contexto.new_page()
    respostas: list[str] = []

    def ouvir(resposta) -> None:      # o link também aparece nas respostas que o site recebe
        try:
            tipo = resposta.headers.get("content-type", "")
            if "json" in tipo or "text" in tipo:
                corpo = resposta.text()
                if "meli.la" in corpo:
                    respostas.append(corpo)
        except Exception:  # noqa: BLE001
            pass

    pagina.on("response", ouvir)
    try:
        # 1) Gerador de links do painel de afiliados
        pagina.goto(GERADOR, wait_until="domcontentloaded", timeout=45000)
        pagina.wait_for_timeout(2500)
        if precisa_login(pagina):
            raise LoginCaiu()
        caixa = pagina.locator("textarea:visible, input[type='text']:visible, input[type='url']:visible").first
        try:
            caixa.wait_for(timeout=12000)
            caixa.click()
            caixa.fill(url_produto)
            pagina.wait_for_timeout(800)
            botao = pagina.get_by_role("button", name=re.compile(r"gerar|criar|generar", re.I)).first
            botao.click(timeout=8000)
            for _ in range(20):
                link = _achar_meli(respostas) or _achar_meli(_textos_da_pagina(pagina))
                if link:
                    return link
                pagina.wait_for_timeout(700)
        except Demorou:
            dizer("   o gerador de links não respondeu como esperado; tentando pela página do produto…")

        # 2) Página do produto → botão "Compartilhar" da barra de afiliados
        pagina.goto(url_produto, wait_until="domcontentloaded", timeout=45000)
        pagina.wait_for_timeout(3000)
        if precisa_login(pagina):
            raise LoginCaiu()
        for nome in (r"compartilhar", r"gerar link", r"copiar link"):
            try:
                pagina.get_by_role("button", name=re.compile(nome, re.I)).first.click(timeout=5000)
            except Exception:  # noqa: BLE001
                try:
                    pagina.get_by_text(re.compile(nome, re.I)).first.click(timeout=3000)
                except Exception:  # noqa: BLE001
                    continue
            for _ in range(12):
                link = _achar_meli(respostas) or _achar_meli(_textos_da_pagina(pagina))
                if link:
                    return link
                pagina.wait_for_timeout(700)

        if guardar_erro:             # guarda um retrato da tela para o Claude ajustar
            ERROS.mkdir(exist_ok=True)
            nome = re.sub(r"\W+", "_", guardar_erro)[:40]
            pagina.screenshot(path=str(ERROS / f"{nome}.png"), full_page=False)
            botoes = pagina.evaluate("() => [...document.querySelectorAll('button, a[role=button]')]"
                                     ".map(b => (b.innerText || b.getAttribute('aria-label') || '').trim())"
                                     ".filter(t => t && t.length < 40).slice(0, 60)")
            (ERROS / f"{nome}.txt").write_text(
                f"endereco: {pagina.url}\nbotoes: {json.dumps(botoes, ensure_ascii=False)}\n", encoding="utf-8")
        return ""
    finally:
        pagina.close()


# ---------------------------------------------------------------------------
# Modos
# ---------------------------------------------------------------------------
def modo_login() -> None:
    with sync_playwright() as pw:
        contexto = abrir_edge(pw)
        pagina = contexto.pages[0] if contexto.pages else contexto.new_page()
        pagina.goto(GERADOR, wait_until="domcontentloaded")
        print("\n>>> Entre na SUA conta do Mercado Livre na janela do navegador que abriu.")
        print(">>> Se pedir código por SMS/e-mail, digite você mesma.")
        print(">>> Quando aparecer o painel de Afiliados (gerador de links), volte aqui.\n")
        input("Aperte ENTER aqui depois de terminar o login... ")
        ok = not precisa_login(pagina)
        contexto.close()
    print("\nLogin guardado! Agora abra \"3 - Ligar ajudante.bat\"." if ok else
          "\nParece que o login não foi concluído. Abra de novo \"2 - Fazer login.bat\".")


def modo_teste(url: str) -> None:
    with sync_playwright() as pw:
        contexto = abrir_edge(pw)
        try:
            link = gerar_meli(contexto, url, guardar_erro="teste")
        except LoginCaiu:
            link = ""
            print("\nO Mercado Livre pediu login. Abra \"2 - Fazer login.bat\" primeiro.")
        contexto.close()
    if link:
        print(f"\nDEU CERTO! Seu link: {link}")
    else:
        print(f"\nNão consegui gerar o link. Guardei um retrato da tela na pasta: {ERROS}")
        print("Mande os arquivos teste.png e teste.txt dessa pasta para o Claude ajustar.")


def modo_ligado() -> None:
    sinal_de_vida()
    dizer("Ajudante ligado. Pode minimizar esta janela (não feche). Para desligar: feche a janela.")
    feitos_na_hora: list[float] = []
    with sync_playwright() as pw:
        contexto = abrir_edge(pw)
        while True:
            try:
                sinal_de_vida()
                pedidos = pedidos_pendentes()
            except Exception as erro:  # noqa: BLE001
                dizer(f"Sem conexão com o robô agora ({str(erro)[:80]}). Tento de novo em 1 min.")
                time.sleep(ESPERA_SEM_PEDIDOS)
                continue
            if not pedidos:
                time.sleep(ESPERA_SEM_PEDIDOS)
                continue
            for pedido in pedidos:
                feitos_na_hora = [t for t in feitos_na_hora if time.time() - t < 3600]
                if len(feitos_na_hora) >= MAX_POR_HORA:
                    dizer("Limite de links desta hora atingido; continuo daqui a pouco.")
                    break
                dizer(f"Gerando o link de: {pedido['url'][:90]}")
                try:
                    link = gerar_meli(contexto, pedido["url"], guardar_erro=pedido["chave"])
                except LoginCaiu:
                    sinal_de_vida(precisa_login=True)
                    dizer("O Mercado Livre pediu login de novo. Feche esta janela, abra \"2 - Fazer login.bat\", "
                          "entre na conta e ligue o ajudante outra vez.")
                    contexto.close()
                    input("Aperte ENTER para fechar... ")
                    return
                except Exception as erro:  # noqa: BLE001
                    dizer(f"   erro: {str(erro)[:120]}")
                    link = ""
                feitos_na_hora.append(time.time())
                if link:
                    responder(pedido["id"], {"status": "pronto", "link": link})
                    dizer(f"   pronto: {link}")
                else:
                    dados = pedido.get("dados") or {}
                    tentativas = int(dados.get("tentativas", 0)) + 1
                    if tentativas >= MAX_TENTATIVAS:
                        responder(pedido["id"], {"status": "erro", "dados": {**dados, "tentativas": tentativas},
                                                 "erro": "o ajudante não achou o botão/link na página do Mercado Livre"})
                        dizer("   não consegui (3 tentativas). Avisei o robô.")
                    else:
                        responder(pedido["id"], {"dados": {**dados, "tentativas": tentativas}})
                        dizer(f"   não consegui desta vez (tentativa {tentativas} de {MAX_TENTATIVAS}).")
                time.sleep(random.randint(*PAUSA_ENTRE_LINKS))


if __name__ == "__main__":
    modo = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    if modo == "login":
        modo_login()
    elif modo == "teste":
        modo_teste(sys.argv[2] if len(sys.argv) > 2 else "https://www.mercadolivre.com.br/p/MLB66104745")
    else:
        modo_ligado()

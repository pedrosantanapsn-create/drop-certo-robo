"""Leva o site entre o GitHub (pasta site/) e o Netlify.

  python site_netlify.py importar   -> baixa os arquivos publicados no Netlify para site/
  python site_netlify.py publicar   -> publica a pasta site/ no Netlify

Precisa do segredo NETLIFY_AUTH_TOKEN (Netlify > User settings > Applications >
Personal access tokens) e da variável SITE_ID.
"""
from __future__ import annotations

import io
import json
import os
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

API = "https://api.netlify.com/api/v1"
TOKEN = os.environ.get("NETLIFY_AUTH_TOKEN", "").strip()
SITE = os.environ.get("SITE_ID", "").strip()
PASTA = Path(os.environ.get("PASTA_SITE", "site"))


def pedir(metodo: str, caminho: str, corpo: bytes | None = None, tipo: str | None = None,
          aceitar: str = "application/json") -> bytes:
    req = urllib.request.Request(f"{API}{caminho}", data=corpo, method=metodo)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Accept", aceitar)
    req.add_header("User-Agent", "drop-certo-robo")
    if tipo:
        req.add_header("Content-Type", tipo)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def importar() -> None:
    arquivos = json.loads(pedir("GET", f"/sites/{SITE}/files"))
    baixados = {}
    for arq in arquivos:
        caminho = arq["path"].lstrip("/")
        if not caminho or caminho.startswith(".netlify/"):
            continue
        conteudo = pedir("GET", f"/sites/{SITE}/files/{urllib.parse.quote(caminho)}",
                         tipo="application/vnd.bitballoon.v1.raw",
                         aceitar="application/vnd.bitballoon.v1.raw")
        if len(conteudo) != arq.get("size", len(conteudo)):
            sys.exit(f"{caminho}: veio {len(conteudo)} bytes, esperado {arq.get('size')} — nada foi salvo")
        baixados[caminho] = conteudo
    for caminho, conteudo in baixados.items():
        destino = PASTA / caminho
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(conteudo)
        print(f"baixado: {caminho} ({len(conteudo)} bytes)")


def publicar() -> None:
    if not (PASTA / "index.html").exists():
        sys.exit("site/index.html não existe — rode a importação primeiro.")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for arq in sorted(PASTA.rglob("*")):
            if arq.is_file():
                z.write(arq, arq.relative_to(PASTA).as_posix())
    deploy = json.loads(pedir("POST", f"/sites/{SITE}/deploys", buffer.getvalue(), "application/zip"))
    print(f"Publicado: deploy {deploy.get('id')} — estado {deploy.get('state')}")
    print(deploy.get("ssl_url") or deploy.get("url") or "")


if __name__ == "__main__":
    if not TOKEN:
        sys.exit("Falta o segredo NETLIFY_AUTH_TOKEN no GitHub.")
    {"importar": importar, "publicar": publicar}[sys.argv[1] if len(sys.argv) > 1 else "publicar"]()

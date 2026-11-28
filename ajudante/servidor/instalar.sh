#!/bin/bash
# Drop Certo — prepara um servidor Linux (Debian/Ubuntu) para rodar o AJUDANTE 24 horas:
# área de trabalho leve + Google Chrome + acesso remoto (Chrome Remote Desktop) + a extensão do ajudante.
#
# Uso (no terminal do servidor, como root ou como usuário com sudo):
#   curl -fsSL https://raw.githubusercontent.com/pedrosantanapsn-create/drop-certo-robo/main/ajudante/servidor/instalar.sh | bash
#
# Não pede nem guarda senha nenhuma. O login no Mercado Livre é feito por você, depois, dentro do Chrome do servidor.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

# Em VPS (Hostinger etc.) o terminal entra como root. O Chrome e a tela remota não rodam como root,
# então o ajudante ganha um usuário comum próprio ("ajudante"), sem senha (só se entra nele pelo root).
if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
  USUARIO="ajudante"
  id "$USUARIO" >/dev/null 2>&1 || adduser --disabled-password --gecos "Ajudante Drop Certo" "$USUARIO" >/dev/null
else
  SUDO="sudo"
  USUARIO="$(id -un)"
fi
CASA="$(getent passwd "$USUARIO" | cut -d: -f6)"
como_usuario() { if [ "$(id -u)" -eq 0 ]; then runuser -u "$USUARIO" -- "$@"; else "$@"; fi; }

echo "==> 1/7 Atualizando o sistema…"
$SUDO apt-get update -qq
$SUDO apt-get install -y -qq wget curl ca-certificates tar sudo >/dev/null

echo "==> 2/7 Proteção contra tentativas de invasão por senha (fail2ban)…"
$SUDO apt-get install -y -qq fail2ban >/dev/null 2>&1 || echo "    (não consegui instalar o fail2ban — sigo sem ele)"
$SUDO systemctl enable --now fail2ban >/dev/null 2>&1 || true

echo "==> 3/7 Memória de reserva (swap de 2 GB, para o navegador não travar)…"
if ! $SUDO swapon --show | grep -q .; then
  $SUDO fallocate -l 2G /swapfile && $SUDO chmod 600 /swapfile && $SUDO mkswap /swapfile >/dev/null && $SUDO swapon /swapfile
  grep -q /swapfile /etc/fstab || echo "/swapfile none swap sw 0 0" | $SUDO tee -a /etc/fstab >/dev/null
fi

echo "==> 4/7 Área de trabalho (XFCE)… isso demora alguns minutos"
$SUDO apt-get install -y -qq xfce4 xfce4-terminal desktop-base dbus-x11 fonts-liberation fonts-noto-color-emoji >/dev/null
$SUDO timedatectl set-timezone America/Sao_Paulo || true

echo "==> 5/7 Acesso remoto (Chrome Remote Desktop)…"
cd /tmp
wget -q https://dl.google.com/linux/direct/chrome-remote-desktop_current_amd64.deb
$SUDO apt-get install -y -qq ./chrome-remote-desktop_current_amd64.deb >/dev/null
echo "exec /etc/X11/Xsession /usr/bin/xfce4-session" | $SUDO tee /etc/chrome-remote-desktop-session >/dev/null
$SUDO systemctl disable lightdm.service >/dev/null 2>&1 || true
$SUDO usermod -aG chrome-remote-desktop "$USUARIO" >/dev/null 2>&1 || true

echo "==> 6/7 Google Chrome…"
wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
$SUDO apt-get install -y -qq ./google-chrome-stable_current_amd64.deb >/dev/null

echo "==> 7/7 Extensão do ajudante e Chrome abrindo sozinho…"
como_usuario mkdir -p "$CASA/drop-certo" "$CASA/.config/autostart"
curl -fsSL https://github.com/pedrosantanapsn-create/drop-certo-robo/archive/refs/heads/main.tar.gz \
  | como_usuario tar xz -C "$CASA/drop-certo" --strip-components=2 drop-certo-robo-main/ajudante/extensao
como_usuario tee "$CASA/.config/autostart/chrome-ajudante.desktop" >/dev/null <<'DESK'
[Desktop Entry]
Type=Application
Name=Chrome (ajudante Drop Certo)
Exec=google-chrome-stable --no-first-run --no-default-browser-check --restore-last-session https://www.mercadolivre.com.br/afiliados/linkbuilder
X-GNOME-Autostart-enabled=true
DESK

echo
echo "PRONTO."
echo "  Usuário do ajudante: $USUARIO"
echo "  Pasta da extensão:   $CASA/drop-certo/extensao"
if [ "$(id -u)" -eq 0 ]; then
  echo "  Para ligar a tela remota, entre no usuário do ajudante com:   su - $USUARIO"
  echo "  e só então cole o comando que o site remotedesktop.google.com/headless mostrar."
fi

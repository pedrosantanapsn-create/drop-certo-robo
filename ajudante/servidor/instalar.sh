#!/bin/bash
# Drop Certo — prepara um servidor Linux (Debian/Ubuntu) para rodar o AJUDANTE 24 horas:
# área de trabalho leve + Google Chrome + acesso remoto (Chrome Remote Desktop) + a extensão do ajudante.
#
# Uso (no terminal SSH do servidor):
#   curl -fsSL https://raw.githubusercontent.com/pedrosantanapsn-create/drop-certo-robo/main/ajudante/servidor/instalar.sh | bash
#
# Não pede nem guarda senha nenhuma. O login no Mercado Livre é feito por você, depois, dentro do Chrome do servidor.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

echo "==> 1/6 Atualizando o sistema…"
sudo apt-get update -qq
sudo apt-get install -y -qq wget curl ca-certificates tar >/dev/null

echo "==> 2/6 Memória de reserva (swap de 2 GB, para o navegador não travar)…"
if ! sudo swapon --show | grep -q /swapfile; then
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile
  grep -q /swapfile /etc/fstab || echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab >/dev/null
fi

echo "==> 3/6 Área de trabalho (XFCE)… isso demora alguns minutos"
sudo apt-get install -y -qq xfce4 xfce4-terminal desktop-base dbus-x11 fonts-liberation fonts-noto-color-emoji >/dev/null
sudo timedatectl set-timezone America/Sao_Paulo || true

echo "==> 4/6 Acesso remoto (Chrome Remote Desktop)…"
cd /tmp
wget -q https://dl.google.com/linux/direct/chrome-remote-desktop_current_amd64.deb
sudo apt-get install -y -qq ./chrome-remote-desktop_current_amd64.deb >/dev/null
echo "exec /etc/X11/Xsession /usr/bin/xfce4-session" | sudo tee /etc/chrome-remote-desktop-session >/dev/null
sudo systemctl disable lightdm.service >/dev/null 2>&1 || true

echo "==> 5/6 Google Chrome…"
wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt-get install -y -qq ./google-chrome-stable_current_amd64.deb >/dev/null

echo "==> 6/6 Extensão do ajudante e Chrome abrindo sozinho…"
mkdir -p "$HOME/drop-certo"
curl -fsSL https://github.com/pedrosantanapsn-create/drop-certo-robo/archive/refs/heads/main.tar.gz \
  | tar xz -C "$HOME/drop-certo" --strip-components=2 drop-certo-robo-main/ajudante/extensao
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/chrome-ajudante.desktop" <<'DESK'
[Desktop Entry]
Type=Application
Name=Chrome (ajudante Drop Certo)
Exec=google-chrome-stable --no-first-run --no-default-browser-check --restore-last-session https://www.mercadolivre.com.br/afiliados/linkbuilder
X-GNOME-Autostart-enabled=true
DESK

echo
echo "PRONTO. A extensão está na pasta: $HOME/drop-certo/extensao"
echo "Próximo passo: abrir https://remotedesktop.google.com/headless no SEU computador e seguir as instruções do Claude."

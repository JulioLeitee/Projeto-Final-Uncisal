#!/usr/bin/env bash
#
# setup-server.sh — Provisionamento completo do Eixo 1 numa VM Ubuntu limpa.
#
# Testado em Ubuntu 26.04 LTS (OpenSSL 3.5 + Nginx 1.28), que é o alvo por
# trazer criptografia pós-quântica no OpenSSL da distribuição.
#
# Uso:
#   sudo ./setup-server.sh 203.0.113.10 seu-email@exemplo.com
#
# O que faz:
#   1. Atualiza o sistema e instala Nginx, Fail2Ban, Certbot (snap) e Python
#   2. Cria os usuários de serviço (appuser) e de deploy (deploy)
#   3. Endurece o SSH (só chave) e liga o Fail2Ban (4 erros / ban 24h)
#   4. Configura firewall local (nftables via ufw) em least privilege
#   5. Instala a aplicação, a venv e o serviço systemd
#   6. Publica o Nginx e emite o certificado de IP
#
set -euo pipefail

IP="${1:?uso: sudo ./setup-server.sh <IP_PUBLICO> <EMAIL>}"
EMAIL="${2:?uso: sudo ./setup-server.sh <IP_PUBLICO> <EMAIL>}"

APP_DIR="/opt/projeto-aplicado"
CONF_DIR="/etc/projeto-aplicado"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[[ $EUID -eq 0 ]] || { echo "rode com sudo"; exit 1; }

step() { echo; echo "=============== $* ==============="; }

# ---------------------------------------------------------------------------
step "1/8  Atualizando o sistema"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
    nginx fail2ban ufw curl ca-certificates \
    python3 python3-venv python3-pip rsync unattended-upgrades

# Patches de segurança aplicados sozinhos (A02/A03:2025).
dpkg-reconfigure -f noninteractive unattended-upgrades

echo ">> Versões instaladas:"
openssl version
nginx -v 2>&1
python3 --version

# ---------------------------------------------------------------------------
step "2/8  Verificando suporte a PQC no OpenSSL"
if openssl list -tls-groups 2>/dev/null | grep -qi 'MLKEM768'; then
    echo "OK: X25519MLKEM768 disponível — PQC pode ser habilitado no Nginx."
else
    cat <<'AVISO'
!! ATENÇÃO: este OpenSSL não expõe ML-KEM. É necessário OpenSSL 3.5+.
   Ubuntu 24.04 LTS traz o 3.0 e NÃO atende ao requisito de PQC do escopo.
   Use Ubuntu 26.04 LTS (traz OpenSSL 3.5) ou compile o Nginx contra o 3.5.
   O restante do provisionamento continua, mas o requisito de PQC falhará.
AVISO
fi

# ---------------------------------------------------------------------------
step "3/8  Instalando o Certbot (snap, para garantir versão >= 5.4)"
snap install core >/dev/null 2>&1 || true
snap refresh core >/dev/null 2>&1 || true
apt-get remove -y -qq certbot python3-certbot-nginx 2>/dev/null || true
snap install --classic certbot
ln -sf /snap/bin/certbot /usr/bin/certbot
certbot --version

# ---------------------------------------------------------------------------
step "4/8  Criando usuários de serviço e de deploy"
# appuser: roda a aplicação, sem shell e sem sudo.
id -u appuser >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin appuser
# deploy: recebe o rsync do GitHub Actions. Sudo APENAS para reiniciar o serviço.
id -u deploy >/dev/null 2>&1 || useradd --create-home --shell /bin/bash deploy

install -d -m 0700 -o deploy -g deploy /home/deploy/.ssh
touch /home/deploy/.ssh/authorized_keys
chmod 0600 /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys

# Least privilege: o usuário de deploy não vira root, só recarrega a aplicação.
cat > /etc/sudoers.d/deploy <<'SUDO'
deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart projeto-aplicado, \
                            /usr/bin/systemctl status projeto-aplicado, \
                            /usr/bin/systemctl is-active projeto-aplicado
SUDO
chmod 0440 /etc/sudoers.d/deploy
visudo -cf /etc/sudoers.d/deploy

# ---------------------------------------------------------------------------
step "5/8  Endurecendo o SSH e ligando o Fail2Ban"
install -m 0644 "${REPO_DIR}/deploy/sshd-hardening.conf" /etc/ssh/sshd_config.d/99-hardening.conf
sshd -t && systemctl reload ssh
echo "OK: autenticação por senha desabilitada."

install -d -m 0755 /etc/fail2ban/jail.d
install -m 0644 "${REPO_DIR}/deploy/fail2ban-sshd.local" /etc/fail2ban/jail.d/sshd.local
systemctl enable --now fail2ban
systemctl restart fail2ban
sleep 2
fail2ban-client status sshd || true

# ---------------------------------------------------------------------------
step "6/8  Firewall local (least privilege)"
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp   comment 'SSH (protegido por Fail2Ban)'
ufw allow 80/tcp   comment 'HTTP (apenas ACME + redirect 301)'
ufw allow 443/tcp  comment 'HTTPS'
ufw --force enable
ufw status verbose

cat <<'NOTA'

>> LEMBRETE: o firewall da NUVEM é uma segunda camada, separada do ufw.
   No Oracle Cloud, libere 80 e 443 em: Networking > VCN > Security Lists
   (Ingress Rules, source 0.0.0.0/0, TCP, portas 80 e 443).
   Sem isso a porta fica fechada mesmo com o ufw liberado.

NOTA

# ---------------------------------------------------------------------------
step "7/8  Instalando a aplicação"
install -d -m 0755 "${APP_DIR}"
rsync -a --delete \
      --exclude '.git' --exclude '.venv' --exclude '__pycache__' \
      "${REPO_DIR}/app/" "${APP_DIR}/app/"

python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/pip" install --quiet --upgrade pip
"${APP_DIR}/.venv/bin/pip" install --quiet -r "${APP_DIR}/app/requirements.txt"

# --- Segredos, fora do repositório e fora do alcance de outros usuários ----
install -d -m 0750 -o root -g appuser "${CONF_DIR}"

if [[ ! -f "${CONF_DIR}/app.env" ]]; then
    SECRET="$(openssl rand -base64 48 | tr -d '\n')"
    cat > "${CONF_DIR}/app.env" <<ENV
APP_SECRET_KEY=${SECRET}
APP_USERS_FILE=${CONF_DIR}/users.json
APP_SESSION_MINUTES=20
ENV
    chmod 0640 "${CONF_DIR}/app.env"
    chown root:appuser "${CONF_DIR}/app.env"
    echo "OK: APP_SECRET_KEY gerada (48 bytes aleatórios)."
fi

if [[ ! -f "${CONF_DIR}/users.json" ]]; then
    echo
    echo ">> Criando o primeiro usuário da aplicação."
    read -rp "   usuário (a-z, 0-9, . _ -): " NEWUSER
    "${APP_DIR}/.venv/bin/python" - "$NEWUSER" <<'PY' > "${CONF_DIR}/users.json"
import getpass, json, sys
sys.path.insert(0, "/opt/projeto-aplicado/app")
from auth import hash_password
user = sys.argv[1].strip().lower()
pwd = getpass.getpass("   senha: ")
if getpass.getpass("   confirme: ") != pwd:
    sys.exit("senhas diferentes")
if len(pwd) < 12:
    sys.exit("use ao menos 12 caracteres")
print(json.dumps({user: hash_password(pwd)}, indent=2))
PY
    chmod 0640 "${CONF_DIR}/users.json"
    chown root:appuser "${CONF_DIR}/users.json"
    echo "OK: usuário criado com hash Argon2id."
fi

chown -R root:root "${APP_DIR}"
chmod -R go-w "${APP_DIR}"

install -m 0644 "${REPO_DIR}/deploy/projeto-aplicado.service" \
        /etc/systemd/system/projeto-aplicado.service
systemctl daemon-reload
systemctl enable --now projeto-aplicado
sleep 2
systemctl is-active projeto-aplicado || journalctl -u projeto-aplicado -n 30 --no-pager

# ---------------------------------------------------------------------------
step "8/8  Nginx + certificado HTTPS para o IP"
install -d -m 0755 -o www-data -g www-data /var/www/certbot

sed "s/SEU_IP_PUBLICO/${IP}/g" "${REPO_DIR}/deploy/nginx-app.conf" \
    > /etc/nginx/sites-available/projeto-aplicado
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/projeto-aplicado /etc/nginx/sites-enabled/projeto-aplicado

# Sobe primeiro só a porta 80, senão o Nginx falha por não achar o certificado.
if [[ ! -f /etc/letsencrypt/live/projeto-aplicado/fullchain.pem ]]; then
    echo ">> Certificado ainda não existe; subindo Nginx só em HTTP para o ACME."
    cat > /etc/nginx/sites-available/projeto-aplicado-bootstrap <<BOOT
server {
    listen 80 default_server;
    server_name ${IP} _;
    location ^~ /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 503 'aguardando certificado'; add_header Content-Type text/plain; }
}
BOOT
    rm -f /etc/nginx/sites-enabled/projeto-aplicado
    ln -sf /etc/nginx/sites-available/projeto-aplicado-bootstrap /etc/nginx/sites-enabled/bootstrap
    nginx -t && systemctl restart nginx

    bash "${REPO_DIR}/deploy/issue-cert.sh" "${IP}" "${EMAIL}"

    rm -f /etc/nginx/sites-enabled/bootstrap
    ln -sf /etc/nginx/sites-available/projeto-aplicado /etc/nginx/sites-enabled/projeto-aplicado
fi

nginx -t
systemctl restart nginx

# ---------------------------------------------------------------------------
step "Validação final"
echo "-- Redirecionamento HTTP -> HTTPS:"
curl -sI "http://${IP}/" | head -3

echo
echo "-- Aplicação sob HTTPS:"
curl -sI "https://${IP}/login" | head -3

echo
echo "-- Grupo TLS negociado (deve dizer X25519MLKEM768):"
openssl s_client -connect "${IP}:443" -tls1_3 -groups X25519MLKEM768 </dev/null 2>&1 \
    | grep -i "Negotiated TLS1.3 group" || echo "   (PQC não negociado — revise o OpenSSL)"

echo
echo "-- Fail2Ban:"
fail2ban-client status sshd | sed 's/^/   /'

cat <<FIM

===========================================================================
CONCLUÍDO.

  Aplicação:  https://${IP}/
  Serviço:    systemctl status projeto-aplicado
  Logs:       journalctl -u projeto-aplicado -f

PRÓXIMOS PASSOS
  1. Cole a chave pública de deploy em /home/deploy/.ssh/authorized_keys
     (a privada correspondente vai no Secret SSH_PRIVATE_KEY do GitHub).
  2. Rode o teste do Qualys SSL Labs e confirme a nota A:
     https://www.ssllabs.com/ssltest/analyze.html?d=${IP}&latest
  3. Faça um push na main e acompanhe o deploy em Actions.
===========================================================================
FIM

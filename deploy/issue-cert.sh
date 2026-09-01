#!/usr/bin/env bash
#
# issue-cert.sh — Emite o certificado Let's Encrypt para o IP PÚBLICO da VM.
#
# Certificados de endereço IP entraram em disponibilidade geral na Let's Encrypt
# em janeiro de 2026 e chegaram ao Certbot em março de 2026. Exigem:
#   - Certbot >= 5.4        (instale via snap; o apt costuma estar defasado)
#   - perfil "shortlived"   (validade de 6 dias — renovação automática é vital)
#   - plugin webroot, manual ou standalone (nginx/apache ainda NÃO suportam IP)
#
# Uso:  sudo ./issue-cert.sh 203.0.113.10 seu-email@exemplo.com [--staging]
#
set -euo pipefail

IP="${1:?informe o IP publico da instancia}"
EMAIL="${2:?informe um e-mail para avisos de expiracao}"
STAGING="${3:-}"
CERT_NAME="projeto-aplicado"
WEBROOT="/var/www/certbot"

echo ">> Verificando versao do Certbot..."
if ! command -v certbot >/dev/null 2>&1; then
    echo "Certbot nao encontrado. Instale com:"
    echo "  sudo snap install --classic certbot"
    echo "  sudo ln -sf /snap/bin/certbot /usr/bin/certbot"
    exit 1
fi
certbot --version

echo ">> Preparando o webroot do desafio ACME..."
mkdir -p "${WEBROOT}/.well-known/acme-challenge"
chown -R www-data:www-data "${WEBROOT}"

# O Nginx precisa estar no ar na porta 80 servindo ${WEBROOT} para o desafio
# HTTP-01. O nginx-app.conf deste repositório já tem o location correto.
echo ">> Testando alcance do webroot..."
echo "ok" > "${WEBROOT}/.well-known/acme-challenge/teste"
if ! curl -fsS "http://${IP}/.well-known/acme-challenge/teste" >/dev/null; then
    echo "ERRO: http://${IP}/.well-known/acme-challenge/ nao respondeu."
    echo "Confira: Nginx no ar, porta 80 aberta no firewall E na Security List da nuvem."
    rm -f "${WEBROOT}/.well-known/acme-challenge/teste"
    exit 1
fi
rm -f "${WEBROOT}/.well-known/acme-challenge/teste"

STAGING_FLAG=""
if [[ "${STAGING}" == "--staging" ]]; then
    STAGING_FLAG="--staging"
    echo ">> MODO STAGING (certificado nao confiavel, serve para testar sem gastar rate limit)"
fi

echo ">> Emitindo certificado para o IP ${IP}..."
certbot certonly \
    ${STAGING_FLAG} \
    --non-interactive \
    --agree-tos \
    --email "${EMAIL}" \
    --webroot --webroot-path "${WEBROOT}" \
    --preferred-profile shortlived \
    --key-type ecdsa \
    --elliptic-curve secp384r1 \
    --cert-name "${CERT_NAME}" \
    --ip-address "${IP}" \
    --deploy-hook "systemctl reload nginx"

echo
echo ">> Certificado emitido em /etc/letsencrypt/live/${CERT_NAME}/"
certbot certificates --cert-name "${CERT_NAME}"

echo
echo ">> Validando o timer de renovacao automatica..."
systemctl list-timers 'snap.certbot.renew.timer' --all --no-pager || true
certbot renew --dry-run --cert-name "${CERT_NAME}"

echo
echo "PRONTO. O certificado vale 6 DIAS e renova sozinho (o timer roda 2x ao dia"
echo "e renova quando resta menos de 1/3 da validade). NAO desabilite o timer."

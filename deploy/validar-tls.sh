#!/usr/bin/env bash
#
# validar-tls.sh — Gera as evidências de qualidade do TLS exigidas no Eixo 1.
#
# CONTEXTO: o escopo v1.0 pedia o teste do Qualys SSL Labs, que só aceita
# domínios registrados — não endereços IP. O professor reconheceu a limitação
# e indicará outra ferramenta. Este script produz a evidência pelas três vias
# possíveis, para você estar coberto independentemente da que for adotada:
#
#   1. testssl.sh  — implementa o "SSL Server Rating Guide" do próprio SSL Labs
#                    e ACEITA endereço IP. Devolve "Overall Grade: A".
#   2. openssl     — prova direta de que o PQC foi negociado.
#   3. sslip.io    — hostname espelho do IP, caso o SSL Labs continue exigido.
#
# Uso:  sudo ./validar-tls.sh 203.0.113.10
#
set -euo pipefail

IP="${1:?uso: sudo ./validar-tls.sh <IP_PUBLICO>}"
OUT="$(pwd)/evidencias"
STAMP="$(date +%Y%m%d-%H%M)"

mkdir -p "${OUT}"

titulo() { echo; echo "=============== $* ==============="; }

# ---------------------------------------------------------------------------
titulo "1/4  Protocolos, cifras e nota (testssl.sh)"

# Dependências que o testssl.sh exige mas não instala sozinho.
# Testado: sem 'hexdump' ele aborta com "Fatal error: You need to install
# hexdump"; sem 'dig' aborta com "Neither dig, host, drill nor nslookup is
# present" — e isso acontece MESMO quando o alvo já é um endereço IP.
echo ">> Garantindo dependências (hexdump, dig)..."
apt-get update -qq 2>/dev/null || true
apt-get install -y -qq git bsdextrautils bind9-dnsutils >/dev/null 2>&1 || true

if ! command -v testssl.sh >/dev/null 2>&1 && [[ ! -x /opt/testssl/testssl.sh ]]; then
    echo ">> Instalando testssl.sh..."
    if apt-get install -y -qq testssl.sh 2>/dev/null && command -v testssl.sh >/dev/null 2>&1; then
        TESTSSL="testssl.sh"
    else
        rm -rf /opt/testssl
        git clone --quiet --depth 1 https://github.com/testssl/testssl.sh.git /opt/testssl
        TESTSSL="/opt/testssl/testssl.sh"
    fi
elif command -v testssl.sh >/dev/null 2>&1; then
    TESTSSL="testssl.sh"
else
    TESTSSL="/opt/testssl/testssl.sh"
fi

echo ">> Rodando contra ${IP}:443 (leva 2 a 4 minutos)..."
# O rating vem ligado por padrão no testssl 3.x. --color 0 deixa o log limpo.
"${TESTSSL}" \
    --color 0 \
    --htmlfile "${OUT}/testssl-${IP}-${STAMP}.html" \
    --logfile  "${OUT}/testssl-${IP}-${STAMP}.txt" \
    --jsonfile "${OUT}/testssl-${IP}-${STAMP}.json" \
    "${IP}:443" || true

echo
echo ">> NOTA FINAL:"
grep -aiE "Overall Grade|Final Score|Grade cap" "${OUT}/testssl-${IP}-${STAMP}.txt" | sed 's/^/   /' \
    || echo "   (não encontrado — confira o log completo)"

cat <<'LEITURA'

   Como ler:
   - "Overall Grade  A"  -> objetivo atingido.
   - "Overall Grade  T"  -> T significa problema de CADEIA DE CONFIANÇA, não
     cifra fraca. Ao escanear um IP puro, o testssl avisa "Target is not a
     server name". Com o certificado da Let's Encrypt emitido PARA o IP isso
     deve validar normalmente; se mesmo assim vier T, use o hostname espelho
     do item 4 e rode de novo — a configuração TLS é exatamente a mesma.
LEITURA

# ---------------------------------------------------------------------------
titulo "2/4  Criptografia pós-quântica (PQC)"

echo ">> Grupos pós-quânticos suportados por este OpenSSL:"
openssl list -tls-groups 2>/dev/null | grep -i mlkem | sed 's/^/   /' \
    || echo "   NENHUM — este OpenSSL não tem ML-KEM (precisa ser 3.5+)"

echo
echo ">> Grupo efetivamente negociado com o servidor:"
NEGOCIADO=$(openssl s_client -connect "${IP}:443" -tls1_3 \
              -groups X25519MLKEM768 </dev/null 2>&1 \
            | grep -i "Negotiated TLS1.3 group" || true)

if [[ -n "${NEGOCIADO}" ]]; then
    echo "   ${NEGOCIADO}"
    echo "${NEGOCIADO}" > "${OUT}/pqc-${IP}-${STAMP}.txt"
    echo "   >> PQC CONFIRMADO. Evidência salva."
else
    echo "   FALHOU — o servidor não negociou X25519MLKEM768."
    echo "   Verifique 'ssl_ecdh_curve' no nginx e a versão do OpenSSL."
fi

# ---------------------------------------------------------------------------
titulo "3/4  Redirecionamento HTTP -> HTTPS e cabeçalhos"

{
    echo "--- http://${IP}/ (deve ser 301) ---"
    curl -sI "http://${IP}/" | head -5
    echo
    echo "--- https://${IP}/login (deve ser 200 + HSTS) ---"
    curl -skI "https://${IP}/login" | head -15
} | tee "${OUT}/headers-${IP}-${STAMP}.txt"

# ---------------------------------------------------------------------------
titulo "4/4  Hostname espelho (caso o SSL Labs continue exigido)"

HOSTNAME_ESPELHO="${IP//./-}.sslip.io"
echo ">> Hostname que resolve para o seu IP: ${HOSTNAME_ESPELHO}"
echo
echo "   Se o professor mantiver o Qualys SSL Labs, emita um certificado"
echo "   também para esse nome e rode o teste contra ele. É o MESMO servidor"
echo "   e a MESMA configuração TLS, então a nota vale como comprovação:"
echo
echo "     sudo certbot certonly --webroot --webroot-path /var/www/certbot \\"
echo "       --cert-name projeto-aplicado-host -d ${HOSTNAME_ESPELHO} \\"
echo "       --key-type ecdsa --deploy-hook \"systemctl reload nginx\""
echo
echo "   Depois: https://www.ssllabs.com/ssltest/analyze.html?d=${HOSTNAME_ESPELHO}&latest"

# ---------------------------------------------------------------------------
titulo "Concluído"
echo "Evidências salvas em: ${OUT}/"
ls -1 "${OUT}" | sed 's/^/   /'
echo
echo "Anexe o HTML do testssl.sh e o print do grupo PQC na sua entrega."

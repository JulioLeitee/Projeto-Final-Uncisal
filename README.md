# Projeto Aplicado — Práticas de Mercado

Aplicação web autenticada, construída e implantada segundo os princípios
**Secure by Design** e **Secure by Default**, com esteira automatizada do
ambiente de desenvolvimento até a produção em nuvem.

| | |
|---|---|
| **Aplicação em produção** | `https://SEU_IP_PUBLICO/` |
| **Repositório** | `https://github.com/JulioLeitee/Projeto-Final-Uncisal` |
| **Nuvem** | Oracle Cloud Infrastructure — *Always Free* |
| **Sistema operacional** | Ubuntu Server 26.04 LTS (OpenSSL 3.5) |
| **Servidor web** | Nginx 1.28 (proxy reverso + terminação TLS) |
| **Aplicação** | Python 3.12 · Flask 3.1 · Gunicorn |
| **CI/CD** | GitHub Actions (`.github/workflows/deploy.yml`) |
| **Desenvolvimento assistido por IA** | Google Antigravity |

---

## 1. Arquitetura

```
┌──────────────────────┐   git push origin main   ┌──────────────────────┐
│  Antigravity (IDE)   │ ───────────────────────► │  GitHub (repositório │
│  desenvolvimento     │                          │  público)            │
└──────────────────────┘                          └──────────┬───────────┘
                                                             │ gatilho
                                                             ▼
                                              ┌──────────────────────────┐
                                              │  GitHub Actions          │
                                              │  1. ruff  (lint)         │
                                              │  2. pip-audit (SCA)      │
                                              │  3. bandit (SAST)        │
                                              │  4. varredura de segredos│
                                              │  5. pytest (21 testes)   │
                                              └────────────┬─────────────┘
                                                           │ rsync + ssh
                                                           │ (chave em Secrets)
                                                           ▼
   ┌───────────────────────────────────────────────────────────────────┐
   │  Oracle Cloud · Ubuntu 26.04 LTS · IP público reservado           │
   │                                                                   │
   │   Internet ──► :80  Nginx ──301──► :443 Nginx (TLS 1.3 + PQC)     │
   │                                       │                           │
   │                                       ▼ proxy_pass                │
   │                             127.0.0.1:8000  Gunicorn              │
   │                                       │                           │
   │                                       ▼                           │
   │                             Flask (appuser, sandbox systemd)      │
   │                                                                   │
   │   :22 SSH — só chave pública, protegido por Fail2Ban (4 / 24h)    │
   └───────────────────────────────────────────────────────────────────┘
```

O Gunicorn escuta **apenas em `127.0.0.1`**: não existe caminho da internet até
a aplicação que não passe pelo Nginx e pelo TLS.

---

## 2. Mitigações OWASP Top 10:2025

O escopo exige **no mínimo 3 categorias**. Foram implementadas **5**, cada uma
com o ponto exato do código e um teste automatizado que falha se o controle
regredir.

### A01:2025 — Broken Access Control

Negação por padrão. Toda rota interna é decorada com `@login_required`, que
consulta a sessão **no servidor**; não existe parâmetro de URL, campo oculto
ou cookie que conceda acesso.

| Onde | O quê |
|---|---|
| `app/security.py` → `login_required()` | Verifica `session["user"]`; sem sessão, redireciona e registra a tentativa |
| `app/app.py` → `@app.route("/dashboard")` | Página interna protegida pelo decorador |
| `app/security.py` → `csrf_protect()` | Token CSRF ligado à sessão, comparado com `secrets.compare_digest` (tempo constante) |
| `app/app.py` → `logout()` | Logout via **POST**; em GET seria disparável por um `<img>` de terceiros |
| `app/app.py` → `SESSION_COOKIE_SAMESITE="Strict"` | O cookie não acompanha requisição vinda de outro site |

**Testes:** `test_dashboard_bloqueado_sem_sessao`, `test_post_sem_csrf_e_rejeitado`,
`test_logout_encerra_sessao`.

---

### A07:2025 — Authentication Failures

| Ameaça | Controle | Onde |
|---|---|---|
| Senha em texto claro ou hash rápido | **Argon2id** (19 MiB, t=2, p=1), parâmetros do OWASP Password Storage Cheat Sheet | `app/auth.py` → `PasswordHasher(...)` |
| Enumeração de usuários por mensagem | Erro **sempre** genérico: `"Usuário ou senha inválidos."` | `app/app.py` → `generic_error` |
| Enumeração de usuários por **tempo de resposta** | Hash dummy verificado quando o usuário não existe, igualando a latência | `app/auth.py` → `_DUMMY_HASH` |
| Força bruta / *credential stuffing* | Bloqueio de 15 min após 5 falhas, contado por IP **e** por usuário | `app/security.py` → `LoginThrottle` |
| *Session fixation* | `session.clear()` + novo token CSRF no instante do login | `app/app.py` → bloco `# --- Sucesso` |
| Sessão eterna | Expiração por inatividade em 20 min | `PERMANENT_SESSION_LIFETIME` |
| Roubo de cookie | `__Host-` + `Secure` + `HttpOnly` + `SameSite=Strict` | `app/app.py` → `app.config.update(...)` |
| DoS pelo custo do hash | Senha limitada a 1024 bytes antes de chegar ao Argon2 | `app/security.py` → `MAX_PASSWORD_BYTES` |

**Testes:** `test_erro_e_generico_nao_enumera_usuario`,
`test_bloqueio_apos_tentativas_repetidas`, `test_senha_nunca_em_texto_claro`.

---

### A02:2025 — Security Misconfiguration

Configuração insegura não é "esquecimento": aqui ela é **impossível**, porque a
aplicação se recusa a subir em estado inseguro.

- **Sem `SECRET_KEY` padrão.** Se `APP_SECRET_KEY` estiver ausente ou tiver
  menos de 32 caracteres, o processo aborta (`raise SystemExit(1)`).
  Uma chave hardcoded no repositório permitiria a qualquer leitor forjar um
  cookie de sessão válido.
- **Sem usuários carregados, sem serviço** (`fail closed`).
- **`debug` jamais habilitado**; nenhuma variável de ambiente liga o depurador.
- **Cabeçalhos de segurança em toda resposta** (`security.py` → `SECURITY_HEADERS`):
  CSP sem `unsafe-inline` (todo CSS é externo e não há JavaScript),
  `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
  `Permissions-Policy`, `Cache-Control: no-store`.
- **HSTS** de 1 ano emitido pelo Nginx.
- **`server_tokens off`** no Nginx e header `Server` removido pelo Flask.
- **Sandbox systemd** (`deploy/projeto-aplicado.service`): usuário sem shell,
  `ProtectSystem=strict`, `NoNewPrivileges`, `MemoryDenyWriteExecute`,
  `SystemCallFilter=@system-service`, filesystem somente leitura.
- **Firewall em duas camadas** com *least privilege*: apenas 22, 80 e 443, no
  `ufw` e na Security List da nuvem.
- **`unattended-upgrades`** aplicando patches de segurança sozinho.

**Testes:** `test_headers_de_seguranca_presentes` (parametrizado),
`test_csp_sem_unsafe_inline`, `test_app_nao_sobe_sem_secret_key`.

---

### A05:2025 — Injection

A aplicação não usa SQL nem shell, o que elimina duas famílias inteiras por
**design**. O que resta é tratado na borda:

- **Allowlist de entrada**: usuário precisa casar com `^[a-z0-9._-]{3,32}$`.
  Qualquer coisa fora disso é rejeitada antes de virar chave de dicionário,
  entrar em log ou ser renderizada (`security.py` → `validate_username`).
- **XSS**: o Jinja2 escapa automaticamente toda variável de template, e a CSP
  `script-src` inexistente (`default-src 'none'`) impede execução de script
  mesmo que um escape falhe — defesa em profundidade.
- **Log injection**: `safe_for_log()` remove CR/LF antes de qualquer `log.warning`,
  impedindo que um usuário forje linhas falsas no journal.
- **Path traversal**: nenhum caminho de arquivo é montado a partir de entrada
  do usuário; o arquivo de credenciais vem de variável de ambiente.

**Testes:** `test_input_malicioso_rejeitado_na_borda` (parametrizado com
`' OR '1'='1`, `<script>`, `../../etc/passwd`, injeção de CRLF e string longa).

---

### A03:2025 — Software Supply Chain Failures

Categoria **nova em 2025**, e a que mais depende do pipeline:

- **Dependências fixadas com `==`** em `app/requirements.txt`. Faixa aberta
  (`>=`) faria um pacote comprometido publicado como "patch" entrar no deploy
  automaticamente.
- **`pip-audit --strict`** a cada push: falha o build se qualquer dependência
  tiver CVE conhecida.
- **Actions fixadas por SHA de commit**, não por tag. Tags são mutáveis — quem
  controlar o repositório da ação pode reapontar `v4` para código malicioso.
- **`permissions: contents: read`** no workflow: o `GITHUB_TOKEN` recebe o
  mínimo, em vez da escrita ampla padrão.
- **Dependabot** (`.github/dependabot.yml`) abrindo PR semanal para pip e para
  as próprias Actions.

---

## 3. Eixo 1 — Infraestrutura

### 3.1 Instância

Oracle Cloud *Always Free*, VM.Standard.A1.Flex (ARM Ampere), Ubuntu Server
26.04 LTS, com **IP público reservado** — endereço efêmero mudaria a cada
reboot e invalidaria o certificado.

### 3.2 Acesso remoto seguro

`deploy/sshd-hardening.conf` desliga a autenticação por senha em todos os
caminhos (`PasswordAuthentication no`, `KbdInteractiveAuthentication no`,
`AuthenticationMethods publickey`), proíbe login direto de root e reduz a
superfície (sem X11/agent/TCP forwarding).

### 3.3 Fail2Ban na porta 22

`deploy/fail2ban-sshd.local`, exatamente como o escopo pede:

```ini
maxretry = 4       # tolerância de 4 erros
bantime  = 86400   # banimento de 24 horas
findtime = 600
backend  = systemd
```

Verificação: `sudo fail2ban-client status sshd`

### 3.4 HTTPS com certificado para **endereço IP**

Este é o ponto mais recente do escopo. A Let's Encrypt passou a emitir
certificados para endereços IP em disponibilidade geral em **janeiro de 2026**,
e o suporte chegou ao **Certbot 5.4** em março de 2026. Restrições que
determinam o desenho da solução:

- Validade de **6 dias** (perfil `shortlived`) → renovação automática é
  obrigatória, não opcional.
- Os plugins `--nginx` e `--apache` **ainda não suportam** certificado de IP.
  Por isso o Nginx é configurado à mão e a emissão usa `--webroot`.

```bash
sudo certbot certonly \
  --webroot --webroot-path /var/www/certbot \
  --preferred-profile shortlived \
  --key-type ecdsa --elliptic-curve secp384r1 \
  --cert-name projeto-aplicado \
  --ip-address SEU_IP_PUBLICO \
  --deploy-hook "systemctl reload nginx"
```

O script `deploy/issue-cert.sh` executa isso, testa o alcance do webroot antes
e valida a renovação com `certbot renew --dry-run`.

**Redirecionamento HTTP→HTTPS:** o `server` da porta 80 existe apenas para o
desafio ACME e devolve `301` para todo o resto.

### 3.5 Criptografia pós-quântica (PQC)

```nginx
ssl_protocols TLSv1.2 TLSv1.3;
ssl_ecdh_curve X25519MLKEM768:X25519:secp384r1:prime256v1;
```

`X25519MLKEM768` é o híbrido de X25519 com **ML-KEM-768** (FIPS 203). Ele
protege contra o ataque *harvest now, decrypt later*: tráfego capturado hoje e
guardado para ser decifrado por um computador quântico no futuro.

**Requisito de versão — o ponto que decide a escolha do SO:** ML-KEM nativo
exige **OpenSSL 3.5+**. O Ubuntu 24.04 LTS traz o OpenSSL 3.0 e **não atende**.
O Ubuntu 26.04 LTS traz o 3.5, com o híbrido pós-quântico ativo por padrão —
por isso ele é o alvo.

Conferência:

```bash
openssl list -tls-groups | grep -i mlkem
openssl s_client -connect SEU_IP:443 -tls1_3 -groups X25519MLKEM768 </dev/null \
  2>&1 | grep "Negotiated TLS1.3 group"
# esperado: Negotiated TLS1.3 group: X25519MLKEM768
```

### 3.6 Nota A no Qualys SSL Labs

O que na configuração produz a nota A:

| Item | Configuração |
|---|---|
| Protocolos | TLS 1.2 e 1.3 apenas — 1.0/1.1 desligados |
| Cifras | Somente ECDHE + AEAD (forward secrecy em 100% das suítes) |
| Chave | ECDSA P-384 |
| HSTS | `max-age=31536000; includeSubDomains` |
| Session tickets | Desligados (sem rotação, quebrariam forward secrecy) |
| Renegociação insegura | Desabilitada por padrão no Nginx moderno |

*OCSP stapling não é habilitado de propósito*: a Let's Encrypt desligou seus
respondedores OCSP em 2025, e a diretiva geraria erro de resolução a cada reload.

#### Ferramenta de verificação

O escopo v1.0 indicava o **Qualys SSL Labs**, que aceita apenas domínios
registrados — não endereços IP. A limitação foi reportada ao professor, que
reconheceu a inconsistência e indicará outra ferramenta.

A verificação aqui é feita por `deploy/validar-tls.sh`, que cobre as três vias:

| Via | Ferramenta | Observação |
|---|---|---|
| Nota | **testssl.sh** | Implementa o próprio *SSL Server Rating Guide* do SSL Labs e **aceita endereço IP**. Devolve `Overall Grade`. |
| PQC | `openssl s_client` | Prova direta do grupo negociado. |
| Reserva | hostname espelho `sslip.io` | Caso o SSL Labs siga exigido: mesmo servidor, mesma configuração TLS. |

Duas observações levantadas ao testar o `testssl.sh` e tratadas no script:
ele exige `hexdump` e `dig` instalados — e exige `dig` **mesmo quando o alvo já
é um IP**, abortando sem eles; e ao escanear um IP puro emite o aviso
*"Target is not a server name"*, o que pode limitar a nota por cadeia de
confiança. Com o certificado da Let's Encrypt emitido **para o IP** isso valida
normalmente; o hostname espelho fica como caminho alternativo.

---

## 4. Eixo 2 — Repositório

- Repositório **público** no GitHub, conta com **2FA ativo**.
- Commits e push por **chave SSH Ed25519** (nunca senha).
- `.gitignore` cobrindo, antes do primeiro commit: `.env`, `users.json`,
  `*.pem`, `*.key`, `id_rsa*`, `id_ed25519*`, `.oci/`, `.aws/`, `*.tfstate`,
  bancos locais e diretórios de IDE/assistente de IA (`.antigravity/`).
- **Nenhum segredo real** existe no repositório: `users.json.example` traz um
  hash claramente falso e `app.env` é gerado no servidor com
  `openssl rand -base64 48`.
- O pipeline tem um passo dedicado que **falha o build** se um arquivo sensível
  for versionado ou se aparecer credencial hardcoded no código.

---

## 5. Eixo 3 — Aplicação

Estrutura mínima exigida, integralmente implementada:

| Requisito | Rota | Arquivo |
|---|---|---|
| Tela de login | `GET/POST /login` | `app/templates/login.html` |
| Página interna | `GET /dashboard` | `app/templates/dashboard.html` |
| Logout funcional | `POST /logout` | `app/app.py` |

Sem banco de dados (o escopo não exige): as credenciais ficam num JSON com
hashes Argon2id em `/etc/projeto-aplicado/users.json`, modo `0640`, fora do
repositório e fora do diretório servido pelo Nginx.

### Desenvolvimento assistido por IA

Todo o código foi escrito e auditado com apoio de IA no **Google Antigravity**.
O trabalho com o assistente se concentrou em: modelagem de ameaças rota a rota,
revisão adversarial ("como um atacante burlaria este decorador?"), escolha de
parâmetros do Argon2id conforme a recomendação vigente do OWASP e geração da
bateria de testes que prova cada mitigação. Cada sugestão foi verificada contra
a documentação oficial antes de entrar no repositório — notadamente as
restrições de certificado de IP no Certbot e o requisito de OpenSSL 3.5 para PQC,
que assistentes treinados em dados anteriores a 2026 tendem a errar.

---

## 6. Esteira CI/CD

`git push origin main` dispara `.github/workflows/deploy.yml`:

**Job `verificar`** (roda em push e em PR; falhou, não implanta)
1. `ruff` — lint
2. `pip-audit --strict` — CVE nas dependências (A03)
3. `bandit -ll` — análise estática do código (SAST)
4. Varredura de segredos versionados e hardcoded (Eixo 2)
5. `pytest` — 21 testes de segurança

**Job `implantar`** (só em push na `main`, após o `verificar` passar)
1. Escreve a chave SSH dos Secrets em `~/.ssh/deploy_key` com modo `600`
2. `rsync -az --delete` para `/opt/projeto-aplicado/app/`
3. Atualiza dependências e `systemctl restart projeto-aplicado`
4. *Smoke test*: `/health` precisa devolver 200 e `http://` precisa devolver 301
5. `shred` na chave privada do runner (roda mesmo se algo falhar)

### Secrets necessários

`Settings → Secrets and variables → Actions`:

| Secret | Conteúdo |
|---|---|
| `SSH_PRIVATE_KEY` | Chave privada do usuário `deploy` (Ed25519, **sem passphrase**) |
| `SERVER_HOST` | IP público da instância |
| `SERVER_USER` | `deploy` |
| `SSH_KNOWN_HOSTS` | Saída de `ssh-keyscan -H SEU_IP` |

### Gerenciamento seguro de credenciais no pipeline

- A chave privada existe **apenas** nos Secrets e no runner efêmero; nunca no
  YAML, nunca em log (o Actions mascara valores de Secrets automaticamente).
- `StrictHostKeyChecking=yes` com host key fixada em `SSH_KNOWN_HOSTS`: sem
  isso o deploy aceitaria um servidor impostor no primeiro contato.
- O usuário `deploy` **não é root**. Seu `sudoers` permite exatamente três
  comandos (`systemctl restart|status|is-active projeto-aplicado`) e nada mais
  — *least privilege* aplicado à automação, não só a pessoas.

---

## 7. Reproduzir

### Servidor

```bash
git clone https://github.com/JulioLeitee/Projeto-Final-Uncisal.git
cd Projeto-Final-Uncisal
sudo bash deploy/setup-server.sh SEU_IP_PUBLICO seu-email@exemplo.com
```

O script provisiona tudo: pacotes, usuários, SSH, Fail2Ban, firewall, venv,
serviço systemd, Nginx e certificado.

### Desenvolvimento local

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r app/requirements.txt pytest
python3 app/auth.py > /tmp/users.json          # cria um usuário
export APP_SECRET_KEY="$(openssl rand -base64 48)"
export APP_USERS_FILE=/tmp/users.json
python3 app/app.py                              # http://127.0.0.1:5000
pytest tests/ -v
```

---

## 8. Checklist de entrega

| # | Requisito | Onde comprovar |
|---|---|---|
| 1 | Aplicação no ar por IP público | `https://SEU_IP/` |
| 2 | Nginx com HTTPS e redirect 80→443 | `deploy/nginx-app.conf` |
| 3 | SSL Labs nota A + PQC | Relatório do SSL Labs e `openssl s_client` |
| 4 | SSH só por chave + Fail2Ban 4/24h | `deploy/sshd-hardening.conf`, `deploy/fail2ban-sshd.local` |
| 5 | Repositório público configurado | GitHub, 2FA ativo, push por chave SSH |
| 6 | `.gitignore` sem exposição de segredos | `.gitignore` + passo de varredura no CI |
| 7 | Login, página interna e logout via IA | `app/`, seção 5 |
| 8 | 3+ categorias OWASP documentadas | Seção 2 (5 categorias) |
| 9 | CI/CD com GitHub Actions | `.github/workflows/deploy.yml` |

---

## 9. Limitações conhecidas

Documentadas por honestidade técnica — reconhecer o limite de um controle vale
mais do que fingir que ele não existe.

- **Bloqueio de login em memória, por processo.** Com `--workers 1` funciona; ao
  escalar para vários workers seria preciso um armazenamento compartilhado
  (Redis). Está fixado em 1 worker no `.service` por essa razão.
- **`users.json` não tem fluxo de troca de senha nem expiração.** O escopo não
  pede gestão de usuários; adicionar meia autenticação seria pior que a atual.
- **Certificado de 6 dias.** Se o timer do Certbot for desabilitado, o site
  quebra em menos de uma semana. É o preço do certificado para IP.
- **HSTS sem `preload`.** A lista de preload não aceita endereços IP.
- **Confiança em `X-Forwarded-For`.** Só é segura porque o Gunicorn escuta
  apenas em `127.0.0.1` e o Nginx **sobrescreve** o header. Expor o Gunicorn
  diretamente permitiria forjar o IP e escapar do bloqueio de login.

---

## 10. Referências

- [OWASP Top 10:2025](https://owasp.org/Top10/2025/)
- [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)
- [Let's Encrypt — 6-day and IP Address Certificates are Generally Available](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability)
- [Let's Encrypt — Six-Day and IP Address Certificates Available in Certbot](https://letsencrypt.org/2026/03/11/shorter-certs-certbot)
- [Let's Encrypt — Certificate Profiles](https://letsencrypt.org/docs/profiles/)
- [NGINX — Post-Quantum Cryptography support](https://blog.nginx.org/blog/pqc-nginx)
- [Qualys SSL Labs — SSL Server Test](https://www.ssllabs.com/ssltest/)

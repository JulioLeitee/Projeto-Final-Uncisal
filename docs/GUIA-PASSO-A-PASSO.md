# Guia passo a passo

Ordem de execução testada. Cada fase termina com um comando de verificação —
não avance sem ele passar.

Tempo total estimado: **3 a 4 horas**, sendo o cadastro na Oracle Cloud a parte
mais imprevisível.

---

## Fase 0 — Ordem correta (leia antes de começar)

A sequência importa. Emitir o certificado antes de abrir a porta 80 na nuvem,
por exemplo, gasta tentativa no *rate limit* da Let's Encrypt à toa.

```
1. Criar a instância na nuvem   ─┐
2. Reservar o IP público         │ Eixo 1 — sem isso nada mais funciona
3. Abrir 80/443 na Security List ─┘
4. Endurecer SSH + Fail2Ban
5. Instalar app + Nginx
6. Emitir o certificado de IP
7. Validar SSL Labs (nota A + PQC)
8. Criar o repositório e subir o código   ─┐ Eixo 2
9. Configurar os Secrets                   │
10. Testar o deploy automático            ─┘ CI/CD
```

---

## Fase 1 — Instância na Oracle Cloud

1. Crie a conta em <https://cloud.oracle.com> (exige cartão para verificação;
   o *Always Free* não é cobrado).
2. **Compute → Instances → Create Instance**
   - **Image:** Canonical Ubuntu **26.04** — *não use 24.04*, o OpenSSL 3.0
     dele não suporta ML-KEM e o requisito de PQC falha.
   - **Shape:** `VM.Standard.A1.Flex` (ARM Ampere), 1–2 OCPU, 6–12 GB.
     Se der `Out of host capacity`, tente outro Availability Domain ou o
     `VM.Standard.E2.1.Micro` (x86).
   - **SSH keys:** cole sua chave pública. Se ainda não tem:
     ```bash
     ssh-keygen -t ed25519 -C "projeto-aplicado" -f ~/.ssh/oci_projeto
     cat ~/.ssh/oci_projeto.pub
     ```
3. **Reserve o IP público** — passo que quase todo mundo pula:
   *Instance → Attached VNICs → clique na VNIC → IPv4 Addresses → editar o IP →
   trocar de **Ephemeral** para **Reserved***.
   Um IP efêmero muda a cada reboot e invalida o certificado emitido para ele.
4. **Abra as portas na Security List** (isto é separado do `ufw`):
   *Networking → Virtual Cloud Networks → sua VCN → Security Lists → Default →
   Add Ingress Rules*
   | Source | Protocol | Destination Port |
   |---|---|---|
   | `0.0.0.0/0` | TCP | 80 |
   | `0.0.0.0/0` | TCP | 443 |

**Verificação**

```bash
ssh -i ~/.ssh/oci_projeto ubuntu@SEU_IP
lsb_release -a          # deve dizer 26.04
openssl version         # deve ser 3.5 ou superior
```

> Se `openssl version` mostrar 3.0.x, pare aqui e recrie a instância com o
> Ubuntu 26.04. Todo o requisito de PQC depende disso.

---

## Fase 2 — Provisionar o servidor

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/SEU_USUARIO/SEU_REPO.git
cd SEU_REPO
sudo bash deploy/setup-server.sh SEU_IP_PUBLICO seu-email@exemplo.com
```

O script pede o usuário e a senha da aplicação no meio da execução. Use senha
de **12+ caracteres** — ele recusa menos que isso.

> **Antes de rodar**, confirme numa **segunda janela de terminal** que você
> consegue logar com sua chave. O script desliga a autenticação por senha; se a
> chave não estiver funcionando, você fica trancado para fora da instância.

**Verificação**

```bash
sudo systemctl status projeto-aplicado    # active (running)
sudo fail2ban-client status sshd          # jail sshd ativo
sudo ufw status verbose                   # só 22, 80, 443
curl -I https://SEU_IP/login              # HTTP/2 200
curl -I http://SEU_IP/                    # 301 para https
```

---

## Fase 3 — Validar HTTPS, PQC e nota A

### Certificado

```bash
sudo certbot certificates --cert-name projeto-aplicado
```

Confirme que o campo *Domains* traz o **IP** e que a expiração é de ~6 dias
(é o esperado no perfil `shortlived`).

### Renovação automática (não pule)

Com validade de 6 dias, o site quebra em menos de uma semana se o timer falhar.

```bash
sudo certbot renew --dry-run
systemctl list-timers | grep certbot     # o timer deve aparecer
```

### PQC

```bash
openssl s_client -connect SEU_IP:443 -tls1_3 -groups X25519MLKEM768 </dev/null 2>&1 \
  | grep "Negotiated TLS1.3 group"
```

Esperado: `Negotiated TLS1.3 group: X25519MLKEM768`

Se voltar `X25519` puro, o OpenSSL do sistema não tem ML-KEM — reveja a versão
do Ubuntu.

### Qualys SSL Labs

<https://www.ssllabs.com/ssltest/analyze.html?d=SEU_IP&latest>

Marque **"Do not show the results on the boards"**. O teste leva de 2 a 4 minutos.

**Se o SSL Labs recusar o endereço IP** (o formulário historicamente pede
hostname), use este contorno, que não muda a arquitetura:

1. Um serviço de DNS-espelho resolve o próprio IP como nome. Para
   `203.0.113.10`, o hostname é `203-0-113-10.sslip.io` (ou `.nip.io`).
2. Emita **também** um certificado para esse nome e adicione ao mesmo Nginx:
   ```bash
   sudo certbot certonly --webroot --webroot-path /var/www/certbot \
     --cert-name projeto-aplicado-host -d 203-0-113-10.sslip.io \
     --key-type ecdsa --deploy-hook "systemctl reload nginx"
   ```
3. Rode o SSL Labs contra o hostname. É o **mesmo servidor, mesma configuração
   TLS**, então a nota vale como comprovação.
4. Documente o contorno no README. A aplicação continua acessível pelo IP puro,
   como o escopo exige.

**Guarde a evidência:** print da tela do SSL Labs mostrando o **A** e o painel
de *Key Exchange* citando o grupo pós-quântico.

---

## Fase 4 — Repositório e Secrets

### 4.1 Conta GitHub

- Ative **2FA**: *Settings → Password and authentication → Two-factor*.
- Configure a chave SSH de commit:
  ```bash
  ssh-keygen -t ed25519 -C "github-projeto-aplicado"
  cat ~/.ssh/id_ed25519.pub   # cole em Settings → SSH and GPG keys
  ssh -T git@github.com       # deve cumprimentar você pelo usuário
  ```

### 4.2 Subir o código

O `.gitignore` **precisa** estar no primeiro commit. Um segredo commitado e
depois removido continua no histórico do Git para sempre.

```bash
cd projeto-aplicado
git init && git branch -M main
git add .gitignore && git commit -m "chore: gitignore antes de tudo"
git status                       # CONFIRA: nada de .env, users.json, *.pem
git add . && git commit -m "feat: aplicacao, infra e pipeline"
git remote add origin git@github.com:SEU_USUARIO/SEU_REPO.git
git push -u origin main
```

Deixe o repositório **público** (*Settings → General → Danger Zone → Change
visibility*), como o escopo exige.

### 4.3 Chave de deploy

Uma chave dedicada, **sem passphrase** (o runner não tem como digitar uma) e
que só serve para o usuário `deploy`:

```bash
# na sua máquina
ssh-keygen -t ed25519 -N "" -C "github-actions-deploy" -f ~/.ssh/deploy_key

# instale a pública no servidor
ssh -i ~/.ssh/oci_projeto ubuntu@SEU_IP \
  "sudo tee -a /home/deploy/.ssh/authorized_keys" < ~/.ssh/deploy_key.pub
ssh -i ~/.ssh/oci_projeto ubuntu@SEU_IP \
  "sudo chown deploy:deploy /home/deploy/.ssh/authorized_keys && sudo chmod 600 /home/deploy/.ssh/authorized_keys"

# teste
ssh -i ~/.ssh/deploy_key deploy@SEU_IP "sudo systemctl is-active projeto-aplicado"
```

### 4.4 Secrets

*Settings → Secrets and variables → Actions → New repository secret*

| Nome | Valor |
|---|---|
| `SSH_PRIVATE_KEY` | `cat ~/.ssh/deploy_key` — **inteiro**, incluindo as linhas `BEGIN`/`END` |
| `SERVER_HOST` | `SEU_IP_PUBLICO` |
| `SERVER_USER` | `deploy` |
| `SSH_KNOWN_HOSTS` | saída de `ssh-keyscan -H SEU_IP` |

Crie também o *environment* chamado `producao`
(*Settings → Environments → New environment*), referenciado pelo workflow.

---

## Fase 5 — Provar o CI/CD

```bash
# altere algo visível, ex. o subtítulo em app/templates/dashboard.html
git add -A
git commit -m "test: validar esteira de deploy automatico"
git push origin main
```

Acompanhe em **Actions**. O job `verificar` roda primeiro; só depois o
`implantar`. Recarregue `https://SEU_IP/dashboard` e confirme a mudança no ar.

**Guarde a evidência:** print do Actions com os dois jobs verdes e o *smoke test*
confirmando `/health` em 200.

### Prove também que a esteira BARRA código ruim

Isso demonstra que o pipeline é um controle de segurança, não enfeite:

```bash
git checkout -b teste-de-barreira
echo 'SECRET_KEY = "senha-hardcoded-de-teste-123456"' >> app/app.py
git commit -am "test: pipeline deve reprovar isto"
git push origin teste-de-barreira        # abra um PR
```

O passo *"Verificar que nenhum segredo foi commitado"* falha e o PR fica
bloqueado. Tire o print, depois `git checkout main && git branch -D teste-de-barreira`.

---

## Fase 6 — Antigravity (Eixo 3)

O escopo avalia o **domínio na interação com o assistente**, não só o resultado.

1. Instale o Google Antigravity e abra a pasta do projeto.
2. Faça pelo menos uma sessão de **auditoria adversarial** e salve o transcript.
   Prompts que rendem material avaliável:
   - *"Aja como um pentester. Enumere formas de acessar `/dashboard` sem
     credencial válida nesta aplicação e aponte o que barra cada uma."*
   - *"Os parâmetros do Argon2id em `auth.py` batem com a recomendação atual
      do OWASP Password Storage Cheat Sheet? Justifique cada valor."*
   - *"Que categoria do OWASP Top 10:2025 esta aplicação NÃO mitiga, e qual
      seria o menor incremento de código que fecharia a lacuna?"*
3. Guarde os prints. Eles comprovam o uso de IA **para auditoria**, que é o que
   o enunciado destaca — não apenas para gerar código.

> Um detalhe que vale mencionar na defesa: assistentes treinados em dados
> anteriores a 2026 erram exatamente os dois pontos críticos deste trabalho —
> insistem que a Let's Encrypt não emite certificado para IP e que PQC exige
> compilar o `oqsprovider`. Mostrar que você verificou a sugestão da IA contra a
> documentação oficial e corrigiu o rumo é o tipo de coisa que diferencia a nota.

---

## Fase 7 — Checklist final

Confira cada linha antes de submeter.

- [ ] `https://SEU_IP/` abre a tela de login
- [ ] `http://SEU_IP/` devolve **301** para HTTPS
- [ ] `certbot certificates` mostra o certificado do IP, válido
- [ ] `certbot renew --dry-run` passa
- [ ] SSL Labs: **nota A** (print salvo)
- [ ] `openssl s_client ... -groups X25519MLKEM768` negocia PQC (print salvo)
- [ ] `ssh -o PubkeyAuthentication=no ubuntu@SEU_IP` é **recusado** (senha desligada)
- [ ] `fail2ban-client status sshd` mostra o jail ativo
- [ ] `grep -E 'maxretry|bantime' /etc/fail2ban/jail.d/sshd.local` → `4` e `86400`
- [ ] Repositório **público**, com 2FA na conta
- [ ] `git ls-files | grep -E '\.env|users\.json|\.pem|id_ed25519'` não retorna nada
- [ ] README documenta as categorias OWASP com o local exato no código
- [ ] Actions verde no último push da `main` (print salvo)
- [ ] Print do PR **reprovado** pelo pipeline
- [ ] Transcripts do Antigravity salvos

---

## Problemas comuns

| Sintoma | Causa provável | Correção |
|---|---|---|
| `curl http://IP` dá timeout | Security List da nuvem fechada | Abra 80/443 nas *Ingress Rules* — o `ufw` sozinho não basta |
| Certbot: "unauthorized" | Webroot inalcançável | `curl http://IP/.well-known/acme-challenge/teste` precisa responder |
| Certbot: "profile not allowed" | Certbot antigo | `sudo snap install --classic certbot` (precisa ser ≥ 5.4) |
| PQC não negocia | OpenSSL 3.0 | Ubuntu 26.04, não 24.04 |
| SSL Labs dá B | TLS 1.0/1.1 ou cifra sem PFS | Confira `ssl_protocols` e `ssl_ciphers` no `nginx-app.conf` |
| Actions: "Host key verification failed" | `SSH_KNOWN_HOSTS` errado | Regere com `ssh-keyscan -H SEU_IP` |
| Actions: "Permission denied (publickey)" | Chave não instalada no `deploy` | Reveja a Fase 4.3 |
| Deploy roda mas nada muda | `rsync` sem permissão | `sudo chown -R deploy:deploy /opt/projeto-aplicado/app` |
| App reinicia em loop | `APP_SECRET_KEY` ausente | `journalctl -u projeto-aplicado -n 50` |
| Login não persiste em HTTP local | Cookie `__Host-` exige HTTPS | Localmente use `python3 app/app.py`, não gunicorn |

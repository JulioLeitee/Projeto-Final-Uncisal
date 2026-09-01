"""
app.py — Projeto Aplicado: Práticas de Mercado
Aplicação web mínima (login → página interna → logout) construída sob os
princípios Secure by Design e Secure by Default.

Secure by Default na prática:
  - A aplicação NÃO SOBE se SECRET_KEY não for fornecida (sem chave padrão).
  - Cookie de sessão já nasce Secure + HttpOnly + SameSite=Strict.
  - Toda rota é negada por padrão; o acesso é concedido explicitamente.
  - DEBUG jamais é ligado por variável de ambiente em produção.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone

from auth import UserStore
from flask import Flask, redirect, render_template, request, session, url_for
from security import (
    LoginThrottle,
    apply_security_headers,
    client_ip,
    csrf_protect,
    issue_csrf_token,
    login_required,
    safe_for_log,
    validate_password,
    validate_username,
)

# ---------------------------------------------------------------------------
# A09:2025 — Security Logging and Alerting Failures
# Eventos de autenticação vão para stdout, capturados pelo systemd/journald.
# Nunca logamos senha, hash ou o conteúdo do cookie de sessão.
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("app")

SESSION_MINUTES = int(os.environ.get("APP_SESSION_MINUTES", "20"))

app = Flask(__name__)

# --- A02:2025 Security Misconfiguration: configuração segura por padrão ----

# Sem fallback. Uma SECRET_KEY hardcoded no repositório permitiria a qualquer
# um forjar um cookie de sessão válido. Falhar aqui é o comportamento correto.
secret = os.environ.get("APP_SECRET_KEY")
if not secret or len(secret) < 32:
    log.critical("APP_SECRET_KEY ausente ou curta demais (minimo 32 caracteres)")
    raise SystemExit(1)

app.config.update(
    SECRET_KEY=secret,
    SESSION_COOKIE_NAME="__Host-session",  # prefixo __Host- exige Secure + path=/
    SESSION_COOKIE_SECURE=True,            # só trafega sobre HTTPS
    SESSION_COOKIE_HTTPONLY=True,          # invisível para JavaScript (anti-XSS)
    SESSION_COOKIE_SAMESITE="Strict",      # não acompanha requisição cross-site
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=SESSION_MINUTES),
    MAX_CONTENT_LENGTH=16 * 1024,          # corpo de requisição limitado
    TEMPLATES_AUTO_RELOAD=False,
)

users = UserStore(os.environ.get("APP_USERS_FILE", "/etc/projeto-aplicado/users.json"))
if len(users) == 0:
    log.critical("nenhum usuario carregado — abortando (fail closed)")
    raise SystemExit(1)

throttle = LoginThrottle(max_attempts=5, window=900, lockout=900)


@app.after_request
def _headers(response):
    return apply_security_headers(response)


@app.context_processor
def _inject_csrf():
    return {"csrf_token": issue_csrf_token()}


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------


@app.route("/health")
def health():
    """Usado pelo pipeline de CI/CD para validar o deploy. Não expõe versão."""
    return {"status": "ok"}, 200


@app.route("/", methods=["GET"])
def index():
    if session.get("user"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
@csrf_protect
def login():
    if session.get("user"):
        return redirect(url_for("dashboard"))

    if request.method == "GET":
        return render_template("login.html", error=None)

    ip = client_ip()
    username = validate_username(request.form.get("username"))
    password = validate_password(request.form.get("password"))

    # A07:2025 — mensagem de erro SEMPRE genérica. Nunca "usuário não existe"
    # ou "senha incorreta", que entregam metade da credencial ao atacante.
    generic_error = "Usuário ou senha inválidos."
    lock_error = "Muitas tentativas. Tente novamente em 15 minutos."

    if throttle.is_locked(ip) or (username and throttle.is_locked(f"u:{username}")):
        log.warning("login bloqueado por throttle ip=%s user=%s", ip, safe_for_log(username or "-"))
        return render_template("login.html", error=lock_error), 429

    if username is None or password is None:
        throttle.record_failure(ip)
        log.warning("login com entrada invalida ip=%s", ip)
        return render_template("login.html", error=generic_error), 401

    if not users.verify(username, password):
        throttle.record_failure(ip)
        locked = throttle.record_failure(f"u:{username}")
        log.warning(
            "login FALHOU user=%s ip=%s%s",
            safe_for_log(username), ip, " [conta bloqueada]" if locked else "",
        )
        return render_template("login.html", error=generic_error), 401

    # --- Sucesso ------------------------------------------------------------
    # A07:2025 — regeneração de sessão: descarta o identificador anterior para
    # impedir session fixation (atacante planta um cookie e espera a vítima
    # autenticar com ele).
    session.clear()
    session.permanent = True
    session["user"] = username
    session["login_at"] = datetime.now(timezone.utc).isoformat()
    issue_csrf_token()  # novo token CSRF para a nova sessão

    throttle.reset(ip)
    throttle.reset(f"u:{username}")
    log.info("login OK user=%s ip=%s", safe_for_log(username), ip)
    return redirect(url_for("dashboard"))


@app.route("/dashboard", methods=["GET"])
@login_required
def dashboard():
    """
    A01:2025 — Página interna. O acesso depende exclusivamente da sessão
    validada no servidor por @login_required. Não existe parâmetro de URL,
    campo escondido ou cookie de papel que conceda acesso.
    """
    login_at = session.get("login_at", "")
    return render_template(
        "dashboard.html",
        user=session["user"],
        login_at=login_at,
        session_minutes=SESSION_MINUTES,
    )


@app.route("/logout", methods=["POST"])
@csrf_protect
@login_required
def logout():
    """
    Logout via POST + CSRF. Um logout em GET seria disparável por um <img>
    numa página de terceiros (CSRF de logout).
    """
    user = session.get("user", "-")
    session.clear()
    log.info("logout user=%s ip=%s", safe_for_log(user), client_ip())
    response = redirect(url_for("login"))
    response.delete_cookie(app.config["SESSION_COOKIE_NAME"], path="/", secure=True)
    return response


# ---------------------------------------------------------------------------
# A10:2025 — Mishandling of Exceptional Conditions
# Erros nunca vazam stack trace, caminho de arquivo ou versão de framework.
# ---------------------------------------------------------------------------


@app.errorhandler(400)
def _bad_request(_):
    return render_template("error.html", code=400, message="Requisição inválida."), 400


@app.errorhandler(404)
def _not_found(_):
    return render_template("error.html", code=404, message="Página não encontrada."), 404


@app.errorhandler(429)
def _too_many(_):
    return render_template("error.html", code=429, message="Muitas requisições."), 429


@app.errorhandler(500)
def _server_error(exc):
    log.error("erro interno: %r", exc)  # detalhe fica no log, não na tela
    return render_template("error.html", code=500, message="Erro interno."), 500


if __name__ == "__main__":  # pragma: no cover
    # Somente desenvolvimento local. Em produção quem sobe é o gunicorn
    # (ver deploy/projeto-aplicado.service). debug=True nunca é opção aqui.
    app.config["SESSION_COOKIE_SECURE"] = False  # localhost não tem TLS
    app.config["SESSION_COOKIE_NAME"] = "session"  # __Host- exige HTTPS
    app.run(host="127.0.0.1", port=5000, debug=False)

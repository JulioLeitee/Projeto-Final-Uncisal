"""
security.py — Controles de segurança transversais da aplicação.

Este módulo concentra as mitigações OWASP Top 10:2025 que não são
específicas de uma rota. Ver README.md, seção "Mitigações OWASP".

  A02:2025 - Security Misconfiguration ...... security_headers()
  A05:2025 - Injection ...................... validate_username()
  A07:2025 - Authentication Failures ........ LoginThrottle
  A01:2025 - Broken Access Control .......... login_required / csrf_protect
"""

from __future__ import annotations

import logging
import re
import secrets
import time
from functools import wraps
from threading import Lock

from flask import abort, redirect, request, session, url_for

log = logging.getLogger("app.security")

# ---------------------------------------------------------------------------
# A02:2025 — Security Misconfiguration
# Cabeçalhos de segurança aplicados a TODA resposta via @app.after_request.
# ---------------------------------------------------------------------------

# CSP sem 'unsafe-inline': todo CSS vive em /static/style.css e não há JS.
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; "
    "style-src 'self'; "
    "img-src 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'"
)

SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    # Impede MIME sniffing (navegador não "adivinha" o tipo do conteúdo).
    "X-Content-Type-Options": "nosniff",
    # Defesa em profundidade contra clickjacking (junto de frame-ancestors).
    "X-Frame-Options": "DENY",
    # Não vaza a URL interna ao navegar para fora.
    "Referrer-Policy": "no-referrer",
    # Desliga APIs de hardware que a aplicação não usa.
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), interest-cohort=()",
    # Nunca cachear páginas autenticadas em proxies/navegador.
    "Cache-Control": "no-store, max-age=0",
}


def apply_security_headers(response):
    """Aplica os cabeçalhos de segurança e remove headers que vazam a stack."""
    for header, value in SECURITY_HEADERS.items():
        response.headers[header] = value
    # HSTS é emitido pelo Nginx (só faz sentido sob TLS); ver deploy/nginx-app.conf
    response.headers.pop("Server", None)
    return response


# ---------------------------------------------------------------------------
# A05:2025 — Injection
# Validação por allowlist na borda. A aplicação não usa SQL nem shell, mas o
# input do usuário é normalizado e restrito antes de qualquer uso — inclusive
# antes de virar chave de dicionário ou entrar em log (previne log injection).
# ---------------------------------------------------------------------------

USERNAME_PATTERN = re.compile(r"\A[a-z0-9._-]{3,32}\Z")
MAX_PASSWORD_BYTES = 1024  # limita DoS por hash de senha gigante


def validate_username(raw: str | None) -> str | None:
    """Retorna o usuário normalizado se casar com a allowlist, senão None."""
    if not isinstance(raw, str):
        return None
    candidate = raw.strip().lower()
    if not USERNAME_PATTERN.fullmatch(candidate):
        return None
    return candidate


def validate_password(raw: str | None) -> str | None:
    """Rejeita senha ausente ou grande demais (DoS no Argon2)."""
    if not isinstance(raw, str) or not raw:
        return None
    if len(raw.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return None
    return raw


def safe_for_log(value: str) -> str:
    """Neutraliza CR/LF para impedir forja de linhas no log (log injection)."""
    return value.replace("\r", "").replace("\n", "")[:64]


# ---------------------------------------------------------------------------
# A07:2025 — Authentication Failures
# Bloqueio progressivo por usuário e por IP. Em memória, por processo: é
# suficiente para o escopo (1 worker) e está documentado como limitação.
# ---------------------------------------------------------------------------


class LoginThrottle:
    """Contador de falhas com janela deslizante e bloqueio temporário."""

    def __init__(self, max_attempts: int = 5, window: int = 900, lockout: int = 900):
        self.max_attempts = max_attempts
        self.window = window
        self.lockout = lockout
        self._failures: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}
        self._lock = Lock()

    def _prune(self, key: str, now: float) -> None:
        recent = [t for t in self._failures.get(key, []) if now - t < self.window]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)

    def is_locked(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            until = self._locked_until.get(key)
            if until is None:
                return False
            if now >= until:
                self._locked_until.pop(key, None)
                self._failures.pop(key, None)
                return False
            return True

    def record_failure(self, key: str) -> bool:
        """Registra uma falha. Retorna True se a chave passou a estar bloqueada."""
        now = time.time()
        with self._lock:
            self._prune(key, now)
            self._failures.setdefault(key, []).append(now)
            if len(self._failures[key]) >= self.max_attempts:
                self._locked_until[key] = now + self.lockout
                return True
            return False

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)


def client_ip() -> str:
    """
    IP real do cliente.

    Confia em X-Forwarded-For APENAS porque o Nginx é o único caminho até o
    gunicorn (que escuta em 127.0.0.1) e o Nginx sobrescreve o header. Ver
    deploy/nginx-app.conf e deploy/projeto-aplicado.service.
    """
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    return request.remote_addr or "unknown"


# ---------------------------------------------------------------------------
# A01:2025 — Broken Access Control
# Negação por padrão: toda rota interna passa por @login_required, que checa a
# sessão no servidor. Nada de confiar em campo escondido, cookie de papel ou
# "esconder o link" no template.
# ---------------------------------------------------------------------------


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            log.warning(
                "acesso negado a %s de %s (sem sessao)",
                safe_for_log(request.path),
                client_ip(),
            )
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapper


# --- CSRF (defesa de sessão, também parte de A01) --------------------------


def issue_csrf_token() -> str:
    """Gera (ou reaproveita) o token CSRF ligado à sessão atual."""
    token = session.get("_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf"] = token
    return token


def csrf_protect(view):
    """Exige token CSRF válido em qualquer requisição que altere estado."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            sent = request.form.get("_csrf", "")
            expected = session.get("_csrf", "")
            # compare_digest evita vazamento por tempo de comparação.
            if not expected or not secrets.compare_digest(sent, expected):
                log.warning("csrf invalido em %s de %s", safe_for_log(request.path), client_ip())
                abort(400)
        return view(*args, **kwargs)

    return wrapper

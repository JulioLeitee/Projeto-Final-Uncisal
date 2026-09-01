"""
Testes que provam as mitigações OWASP. Rodam no GitHub Actions a cada push
e barram o deploy se qualquer controle de segurança regredir.
"""

import json
import re
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from auth import hash_password

    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps({"aluno": hash_password("SenhaForte#2026")}))

    monkeypatch.setenv("APP_SECRET_KEY", "x" * 48)
    monkeypatch.setenv("APP_USERS_FILE", str(users_file))

    for mod in ("app", "auth", "security"):
        sys.modules.pop(mod, None)

    import app as app_module

    app_module.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False,
                                 SESSION_COOKIE_NAME="session")
    with app_module.app.test_client() as c:
        yield c


def _csrf(client, path="/login"):
    """Extrai o token CSRF do formulário da página indicada."""
    html = client.get(path).get_data(as_text=True)
    match = re.search(r'name="_csrf" value="([^"]+)"', html)
    assert match, f"nenhum token CSRF encontrado em {path}"
    return match.group(1)


# --- A01:2025 Broken Access Control ----------------------------------------

def test_dashboard_bloqueado_sem_sessao(client):
    r = client.get("/dashboard")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_dashboard_liberado_com_sessao(client):
    token = _csrf(client)
    client.post("/login", data={"username": "aluno", "password": "SenhaForte#2026",
                                "_csrf": token})
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "Área interna" in r.get_data(as_text=True)


def test_post_sem_csrf_e_rejeitado(client):
    r = client.post("/login", data={"username": "aluno", "password": "SenhaForte#2026"})
    assert r.status_code == 400


def test_logout_encerra_sessao(client):
    token = _csrf(client)
    client.post("/login", data={"username": "aluno", "password": "SenhaForte#2026",
                                "_csrf": token})
    token = _csrf(client, "/dashboard")
    assert client.post("/logout", data={"_csrf": token}).status_code == 302
    assert client.get("/dashboard").status_code == 302


# --- A07:2025 Authentication Failures --------------------------------------

def test_senha_errada_rejeitada(client):
    token = _csrf(client)
    r = client.post("/login", data={"username": "aluno", "password": "errada",
                                    "_csrf": token})
    assert r.status_code == 401


def test_erro_e_generico_nao_enumera_usuario(client):
    token = _csrf(client)
    inexistente = client.post("/login", data={"username": "ninguem", "password": "x",
                                              "_csrf": token}).get_data(as_text=True)
    token = _csrf(client)
    existente = client.post("/login", data={"username": "aluno", "password": "x",
                                            "_csrf": token}).get_data(as_text=True)
    assert "Usuário ou senha inválidos." in inexistente
    assert "Usuário ou senha inválidos." in existente


def test_bloqueio_apos_tentativas_repetidas(client):
    for _ in range(6):
        token = _csrf(client)
        r = client.post("/login", data={"username": "aluno", "password": "errada",
                                        "_csrf": token})
    assert r.status_code == 429


def test_senha_nunca_em_texto_claro(tmp_path):
    from auth import hash_password
    h = hash_password("SenhaForte#2026")
    assert h.startswith("$argon2id$")
    assert "SenhaForte#2026" not in h


# --- A02:2025 Security Misconfiguration ------------------------------------

@pytest.mark.parametrize("header", [
    "Content-Security-Policy",
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Referrer-Policy",
    "Permissions-Policy",
])
def test_headers_de_seguranca_presentes(client, header):
    assert header in client.get("/login").headers


def test_csp_sem_unsafe_inline(client):
    csp = client.get("/login").headers["Content-Security-Policy"]
    assert "unsafe-inline" not in csp
    assert "frame-ancestors 'none'" in csp


def test_app_nao_sobe_sem_secret_key(tmp_path, monkeypatch):
    from auth import hash_password
    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps({"aluno": hash_password("x")}))
    monkeypatch.delenv("APP_SECRET_KEY", raising=False)
    monkeypatch.setenv("APP_USERS_FILE", str(users_file))
    for mod in ("app", "auth", "security"):
        sys.modules.pop(mod, None)
    with pytest.raises(SystemExit):
        import app  # noqa: F401


# --- A05:2025 Injection -----------------------------------------------------

@pytest.mark.parametrize("payload", [
    "' OR '1'='1",
    "<script>alert(1)</script>",
    "../../etc/passwd",
    "aluno\r\nFAKE LOG LINE",
    "a" * 200,
])
def test_input_malicioso_rejeitado_na_borda(client, payload):
    from security import validate_username
    assert validate_username(payload) is None


def test_xss_refletido_e_escapado(client):
    from security import validate_username
    assert validate_username("<img src=x onerror=alert(1)>") is None

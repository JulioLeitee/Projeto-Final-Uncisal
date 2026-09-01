"""
auth.py — Armazenamento de credenciais e verificação de senha.

A02:2025 (Cryptographic Failures na 2021, hoje coberto por A04/A07):
senhas NUNCA são guardadas em texto claro nem com hash rápido (MD5/SHA-1).
Usa Argon2id — vencedor da Password Hashing Competition e recomendação atual
do OWASP Password Storage Cheat Sheet.

O arquivo de usuários fica FORA do repositório (ver .gitignore) e seu caminho
vem da variável de ambiente APP_USERS_FILE.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, VerifyMismatchError

log = logging.getLogger("app.auth")

# Parâmetros conforme OWASP Password Storage Cheat Sheet (Argon2id):
# 19 MiB de memória, 2 iterações, paralelismo 1.
_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)

# Hash descartável usado para gastar o mesmo tempo quando o usuário não existe.
# Sem isso, um atacante mede o tempo de resposta e enumera usuários válidos
# (username enumeration — A07:2025).
_DUMMY_HASH = _hasher.hash("senha-inexistente-para-timing-equalization")


class UserStore:
    """Carrega usuários de um JSON no formato {"usuario": "$argon2id$..."}"""

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self._users: dict[str, str] = {}
        self.load()

    def load(self) -> None:
        if not self.path.is_file():
            log.error("arquivo de usuarios nao encontrado: %s", self.path)
            self._users = {}
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            # A10:2025 — Mishandling of Exceptional Conditions: falha fechada.
            # Se o arquivo está corrompido, ninguém entra; não caímos em um
            # estado permissivo.
            log.error("falha ao ler arquivo de usuarios: %s", exc)
            self._users = {}
            return
        if not isinstance(data, dict):
            log.error("formato invalido no arquivo de usuarios")
            self._users = {}
            return
        self._users = {str(k).lower(): str(v) for k, v in data.items()}
        log.info("carregados %d usuarios", len(self._users))

    def verify(self, username: str, password: str) -> bool:
        """
        Verifica a senha em tempo aproximadamente constante em relação à
        existência do usuário.
        """
        stored = self._users.get(username, _DUMMY_HASH)
        try:
            _hasher.verify(stored, password)
        except (VerifyMismatchError, Argon2Error):
            return False
        # Usuário inexistente casando com o hash dummy é impossível na prática,
        # mas a checagem explícita fecha a porta.
        return username in self._users

    def __len__(self) -> int:
        return len(self._users)


def hash_password(password: str) -> str:
    """Helper de linha de comando: gera o hash para popular users.json."""
    return _hasher.hash(password)


if __name__ == "__main__":  # pragma: no cover
    import getpass
    import sys

    user = input("usuario: ").strip().lower()
    pwd = getpass.getpass("senha: ")
    if getpass.getpass("confirme: ") != pwd:
        print("senhas diferentes", file=sys.stderr)
        sys.exit(1)
    print(json.dumps({user: hash_password(pwd)}, indent=2))

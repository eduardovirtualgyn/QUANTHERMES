"""
QUANT HERMES — Comparação e exigência de segredos
Módulo: core.secrets

Segredos vêm somente de variáveis de ambiente. Não há token padrão.
A comparação usa o digest SHA-256 para que secrets.compare_digest
receba buffers de tamanho igual.
"""
from __future__ import annotations

import hashlib
import os
import secrets


class MissingSecretError(RuntimeError):
    """Segredo obrigatório ausente no ambiente. O processo deve falhar no arranque."""


def require_env(name: str) -> str:
    """Lê uma variável de ambiente obrigatória. Falha se estiver vazia."""
    value = os.getenv(name, "")
    if value is None or not str(value).strip():
        raise MissingSecretError(
            f"Variável de ambiente obrigatória ausente ou vazia: {name}. "
            "Defina-a no ambiente ou em um arquivo .env não versionado. "
            "Não existe token padrão."
        )
    return str(value).strip()


def tokens_equal(provided: str, expected: str) -> bool:
    """Compara dois tokens sem curto-circuito no conteúdo."""
    if not provided or not expected:
        return False
    provided_digest = hashlib.sha256(provided.encode("utf-8")).digest()
    expected_digest = hashlib.sha256(expected.encode("utf-8")).digest()
    return secrets.compare_digest(provided_digest, expected_digest)

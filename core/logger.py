"""
QUANT HERMES — Sistema de Logging Estruturado com Sanitização de Segredos
Módulo: core.logger
"""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from core.platform_io import configure_utf8_stdio


# Padrões regex para interceptar segredos comuns em strings
_SENSITIVE_PATTERNS = [
    re.compile(r"(password|passwd|pwd)[\s:=]+([^\s,;]+)", re.IGNORECASE),
    re.compile(r"(secret|token|api_key|apikey|bearer)[\s:=]+([^\s,;]+)", re.IGNORECASE),
    re.compile(r"(authorization)[\s:=]+([^\s,;]+)", re.IGNORECASE),
]

_SENSITIVE_KEYS = {
    "password", "passwd", "pwd", "secret", "token", "api_key", "apikey",
    "authorization", "private_key", "mt5_password", "postgres_password",
    "secret_key", "credentials"
}


def sanitize_string(text: str) -> str:
    """Higieniza uma string substituindo segredos por [PROTECTED_SECRET]."""
    sanitized = text
    for pattern in _SENSITIVE_PATTERNS:
        sanitized = pattern.sub(r"\1=***MASKED***", sanitized)
    return sanitized


def sanitize_data(data: Any) -> Any:
    """Recursivamente higieniza dicionários, listas e tuplas."""
    if isinstance(data, Mapping):
        clean_dict = {}
        for k, v in data.items():
            k_lower = str(k).lower()
            if any(sensitive == k_lower or sensitive in k_lower for sensitive in _SENSITIVE_KEYS):
                if isinstance(v, (Mapping, list, tuple, set)):
                    clean_dict[k] = sanitize_data(v)
                else:
                    clean_dict[k] = "***MASKED***"
            else:
                clean_dict[k] = sanitize_data(v)
        return clean_dict
    elif isinstance(data, (list, tuple, set)):
        return type(data)(sanitize_data(item) for item in data)
    elif isinstance(data, str):
        return sanitize_string(data)
    return data


class HermesJsonFormatter(logging.Formatter):
    """Formatador de logs JSON estruturado e higienizado para produção."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": sanitize_string(record.getMessage()),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }

        # Anexa contexto estruturado adicional
        if hasattr(record, "context") and isinstance(record.context, dict):
            log_entry["context"] = sanitize_data(record.context)

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str, ensure_ascii=False)


class HermesConsoleFormatter(logging.Formatter):
    """Formatador legível para console local com cores e higienização."""

    def format(self, record: logging.LogRecord) -> str:
        msg = sanitize_string(record.getMessage())
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
        extra_ctx = ""
        if hasattr(record, "context") and isinstance(record.context, dict):
            clean_ctx = sanitize_data(record.context)
            extra_ctx = f" | ctx={json.dumps(clean_ctx, default=str)}"

        return f"[{ts} UTC] [{record.levelname:7s}] [{record.name}] {msg}{extra_ctx}"


def setup_logger(
    name: str = "quant_hermes",
    level: str = "INFO",
    json_output: bool = False,
    log_file: str | None = None,
) -> logging.Logger:
    """Configura e retorna um logger padronizado do QUANT HERMES."""
    configure_utf8_stdio()
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    # Evita duplicação de handlers se já configurado
    if logger.handlers:
        return logger

    # Handler de console
    console_handler = logging.StreamHandler(sys.stdout)
    if json_output:
        console_handler.setFormatter(HermesJsonFormatter())
    else:
        console_handler.setFormatter(HermesConsoleFormatter())
    logger.addHandler(console_handler)

    # Handler de arquivo opcional
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setFormatter(HermesJsonFormatter())
        logger.addHandler(file_handler)

    return logger


class StructuredLogger:
    """Wrapper utilitário para emitir logs com contexto estruturado."""

    def __init__(self, logger: logging.Logger):
        self._logger = logger

    def debug(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.DEBUG, msg, kwargs)

    def info(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.INFO, msg, kwargs)

    def warning(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.WARNING, msg, kwargs)

    def error(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.ERROR, msg, kwargs)

    def critical(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.CRITICAL, msg, kwargs)

    def _log(self, level: int, msg: str, context: dict[str, Any]) -> None:
        if self._logger.isEnabledFor(level):
            record = self._logger.makeRecord(
                self._logger.name,
                level,
                fn="",
                lno=0,
                msg=msg,
                args=(),
                exc_info=None,
                extra={"context": context} if context else None,
            )
            self._logger.handle(record)


# Instância global padrão
logger = setup_logger("quant_hermes")
log = StructuredLogger(logger)


def get_logger(name: str = "quant_hermes") -> StructuredLogger:
    """Retorna uma instância de StructuredLogger configurada."""
    return StructuredLogger(setup_logger(name))


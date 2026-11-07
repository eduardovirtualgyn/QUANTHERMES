"""
Testes de Segurança e Sanitização de Segredos no Logging
Arquivo: tests/security/test_logging_sanitizer.py
"""
import json
import logging
from core.logger import (
    sanitize_string,
    sanitize_data,
    HermesJsonFormatter,
)


class TestLoggingSanitizer:
    """Valida que credenciais e segredos jamais vazem para logs ou saídas do sistema."""

    def test_sanitize_inline_string_secrets(self):
        msg = "Connecting to MT5 with login 123456 and password=SuperSecretPassword123"
        sanitized = sanitize_string(msg)
        assert "SuperSecretPassword123" not in sanitized
        assert "password=***MASKED***" in sanitized

    def test_sanitize_api_tokens_in_string(self):
        msg = "Request to OpenAI with api_key: sk-proj-123456789abcdef"
        sanitized = sanitize_string(msg)
        assert "sk-proj-123456789abcdef" not in sanitized
        assert "***MASKED***" in sanitized

    def test_sanitize_dict_keys(self):
        sensitive_payload = {
            "user": "hermes_trader",
            "password": "my_db_password_999",
            "mt5_password": "broker_pass_secret",
            "api_key": "sec_ai_key_888",
            "safe_metric": 42.5,
        }
        cleaned = sanitize_data(sensitive_payload)
        assert cleaned["password"] == "***MASKED***"
        assert cleaned["mt5_password"] == "***MASKED***"
        assert cleaned["api_key"] == "***MASKED***"
        assert cleaned["safe_metric"] == 42.5
        assert cleaned["user"] == "hermes_trader"

    def test_sanitize_nested_structures(self):
        nested = {
            "environment": "live",
            "credentials": [
                {"service": "mt5", "password": "pass1"},
                {"service": "postgres", "secret": "pass2"},
            ],
            "headers": {"authorization": "Bearer eyJhbGciOi..."},
        }
        cleaned = sanitize_data(nested)
        assert cleaned["credentials"][0]["password"] == "***MASKED***"
        assert cleaned["credentials"][1]["secret"] == "***MASKED***"
        assert cleaned["headers"]["authorization"] == "***MASKED***"

    def test_hermes_json_formatter_masks_record(self):
        formatter = HermesJsonFormatter()
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="User login attempted with password=DangerousUnmaskedPass",
            args=(),
            exc_info=None,
        )
        record.context = {"token": "secret_session_token_xyz"}

        output = formatter.format(record)
        parsed = json.loads(output)

        assert "DangerousUnmaskedPass" not in output
        assert parsed["context"]["token"] == "***MASKED***"


"""Deploy Windows: adapter paper por padrão, preflight do terminal sem conectar, rotação de log."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from core.config import load_hermes_config
from core.platform_io import ShutdownController
from deploy.log_rotate import rotate_file
from deploy.preflight_check import PreflightChecker
from deploy.windows.service_main import bind_host, should_require_terminal
from execution.adapters.paper import PaperTradingAdapter
from execution.runtime import build_trading_adapter


def _secrets(monkeypatch) -> None:
    monkeypatch.setenv("HERMES_OPERATOR_TOKEN", "operator-token-test-value")
    monkeypatch.delenv("HERMES_REMOTE_GATEWAY", raising=False)
    monkeypatch.delenv("HERMES_EXECUTION_MODE", raising=False)


def _healthy_terminal() -> dict:
    return {
        "importable": True,
        "connected": True,
        "trade_allowed": True,
        "currency": "USC",
        "login": 10001,
        "resolved": {"EURUSD": True, "XAUUSD": True},
        "error": "",
    }


def test_default_runtime_is_paper_and_remote_gateway_off(monkeypatch):
    _secrets(monkeypatch)
    config = load_hermes_config()
    assert config.execution.remote_gateway_enabled is False
    adapter = build_trading_adapter(config)
    assert isinstance(adapter, PaperTradingAdapter)


def test_direct_mt5_does_not_connect_from_the_factory(monkeypatch):
    _secrets(monkeypatch)
    monkeypatch.setenv("HERMES_EXECUTION_MODE", "mt5_demo")
    config = load_hermes_config()
    if sys.platform != "win32":
        with pytest.raises(RuntimeError, match="Windows"):
            build_trading_adapter(config)
        return
    adapter = build_trading_adapter(config)
    assert adapter.__class__.__name__ == "WindowsMT5Adapter"
    assert adapter._connected is False


def test_bind_host_rejects_all_interfaces(monkeypatch):
    monkeypatch.setenv("HERMES_BIND_HOST", "0.0.0.0")
    with pytest.raises(SystemExit):
        bind_host()
    monkeypatch.setenv("HERMES_BIND_HOST", "127.0.0.1")
    assert bind_host() == "127.0.0.1"


def test_terminal_required_only_for_direct_mt5():
    assert should_require_terminal("paper", remote=False) is False
    assert should_require_terminal("mt5_demo", remote=True) is False
    assert should_require_terminal("mt5_demo", remote=False) is True


def test_offline_preflight_does_not_call_the_terminal(monkeypatch):
    _secrets(monkeypatch)

    def boom(self):
        raise AssertionError("preflight offline não pode chamar o terminal")

    monkeypatch.setattr(PreflightChecker, "live_mt5_probe", boom)
    report = PreflightChecker().run_all_checks()
    assert report.is_ready is True
    assert report.critical_errors == []


def test_terminal_snapshot_accepts_usc_and_rejects_bad_account():
    checker = PreflightChecker()
    ok, _, errors = checker.evaluate_terminal_snapshot(_healthy_terminal())
    assert ok is True
    assert errors == []

    usd = _healthy_terminal()
    usd["currency"] = "USD"
    ok, _, errors = checker.evaluate_terminal_snapshot(usd)
    assert ok is False
    assert any("USC" in err for err in errors)

    auto = _healthy_terminal()
    auto["trade_allowed"] = False
    ok, _, errors = checker.evaluate_terminal_snapshot(auto)
    assert ok is False
    assert any("AutoTrading" in err for err in errors)

    missing = _healthy_terminal()
    missing["resolved"] = {"EURUSD": True, "XAUUSD": False}
    ok, _, errors = checker.evaluate_terminal_snapshot(missing)
    assert ok is False
    assert any("XAUUSD" in err for err in errors)

    offline = _healthy_terminal()
    offline["importable"] = False
    ok, _, errors = checker.evaluate_terminal_snapshot(offline)
    assert ok is False
    assert any("não importável" in err for err in errors)

    logged_out = _healthy_terminal()
    logged_out["connected"] = False
    logged_out["error"] = "terminal fechado"
    ok, _, errors = checker.evaluate_terminal_snapshot(logged_out)
    assert ok is False
    assert any("não está em execução" in err for err in errors)


def test_stop_file_requests_shutdown(tmp_path: Path):
    controller = ShutdownController(tmp_path / "hermes.stop")
    assert controller.requested() is False
    controller.request()
    assert controller.requested() is True
    assert (tmp_path / "hermes.stop").is_file()
    controller.clear()
    assert controller.requested() is False


def test_log_rotation_uses_pathlib(tmp_path: Path):
    log = tmp_path / "hermes.log"
    log.write_text("x" * 100, encoding="utf-8")
    assert rotate_file(log, max_bytes=50, backup_count=2) is True
    assert not log.exists()
    assert (tmp_path / "hermes.log.1").is_file()

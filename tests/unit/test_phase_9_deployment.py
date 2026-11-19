"""
QUANT HERMES — TESTES UNITÁRIOS E DE INTEGRAÇÃO DA FASE 9 (DEPLOYMENT & VPS)
Módulo: tests.unit.test_phase_9_deployment

Testa:
1. PreflightChecker: Verificação pré-voo, integridade de diretórios e pisos de risco.
2. StateBackupManager: Backup transacional de estado SQLite, rotação e SHA-256.
3. RemoteMT5GatewayAdapter & Gateway Server: Comunicação cliente-servidor Dual-Node e Fail-Safe.
4. PortfolioManager Cooldown Persistence (DEBT-P2-02): Persistência de cooldown entre reinicializações.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from core.models.market import MarketBar, MarketTick, SymbolSpecification, TimeFrame
from core.models.risk import AccountState, OrderRequest, OrderResult, Position, RiskAuthorization, TradeProposal
from deploy.backup_state import StateBackupManager, compute_sha256
from deploy.preflight_check import PreflightChecker, PreflightReport
from execution.adapters.base import PlatformConnectionError
from execution.adapters.paper import PaperTradingAdapter
from execution.adapters.remote_gateway import RemoteMT5GatewayAdapter
from execution.gateway_server import create_gateway_app
from portfolio.manager import PortfolioManager
from risk.engine import RiskEngine


class TestPhase9PreflightChecker:
    """Valida o verificador pré-voo institucional."""

    def test_preflight_passes_on_current_workspace(self, monkeypatch):
        monkeypatch.setenv("HERMES_OPERATOR_TOKEN", "operator-token-test-value")
        monkeypatch.setenv("HERMES_GATEWAY_TOKEN", "gateway-token-test-value")
        monkeypatch.setenv("HERMES_BRIDGE_TOKEN", "bridge-token-test-value")
        checker = PreflightChecker()
        report = checker.run_all_checks()
        major, minor, *_ = report.python_version.split(".")
        assert int(major) == 3 and int(minor) >= 11
        assert len(report.critical_errors) == 0
        assert report.is_ready is True
        assert len(report.checks_passed) >= 3

    def test_preflight_fails_without_required_secrets(self, monkeypatch):
        monkeypatch.delenv("HERMES_OPERATOR_TOKEN", raising=False)
        monkeypatch.delenv("HERMES_GATEWAY_TOKEN", raising=False)
        monkeypatch.delenv("HERMES_BRIDGE_TOKEN", raising=False)
        checker = PreflightChecker()
        report = checker.run_all_checks()
        assert report.is_ready is False
        assert any("HERMES_OPERATOR_TOKEN" in err for err in report.critical_errors)

    def test_preflight_detects_sqlite_corruption(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            base_path = Path(tmp_dir)
            storage_dir = base_path / "data" / "storage"
            storage_dir.mkdir(parents=True, exist_ok=True)
            
            # Cria banco deliberadamente corrompido
            corrupt_db = storage_dir / "corrupted_test.db"
            corrupt_db.write_bytes(b"NOT_A_VALID_SQLITE_DATABASE_HEADER_DATA_123456789")

            checker = PreflightChecker(base_dir=base_path)
            sql_ok, passed, errors = checker.check_sqlite_integrity()
            assert sql_ok is False
            assert len(errors) > 0


class TestPhase9StateBackup:
    """Valida o gerenciador de backup transacional e rotação."""

    def test_state_backup_execution_and_checksum(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_path = Path(tmp_dir)
            storage_dir = base_path / "data" / "storage"
            storage_dir.mkdir(parents=True, exist_ok=True)

            # Cria um banco SQLite real com dados
            test_db = storage_dir / "test_idempotency.db"
            conn = sqlite3.connect(str(test_db))
            conn.execute("CREATE TABLE test (id INT PRIMARY KEY, val TEXT);")
            conn.execute("INSERT INTO test VALUES (1, 'hermes_quant');")
            conn.commit()
            conn.close()

            # Cria arquivo JSON de estado
            test_json = storage_dir / "test_state.json"
            test_json.write_text(json.dumps({"is_active": True}), encoding="utf-8")

            # Executa backup
            backup_mgr = StateBackupManager(base_dir=base_path, retention_days=7)
            result = backup_mgr.execute_backup()

            assert result["status"] == "SUCCESS"
            archive_path = Path(result["archive_path"])
            assert archive_path.exists()
            assert archive_path.stat().st_size > 0

            # Valida checksum SHA-256
            sha_file = archive_path.with_suffix(".sha256")
            assert sha_file.exists()
            computed = compute_sha256(archive_path)
            assert result["sha256"] == computed

    def test_state_backup_rotation_prunes_old_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_path = Path(tmp_dir)
            backup_dir = base_path / "data" / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)

            # Cria arquivo antigo simulado (40 dias atrás)
            old_archive = backup_dir / "hermes_state_backup_20260101_000000.tar.gz"
            old_archive.write_bytes(b"dummy_data")
            old_sha = old_archive.with_suffix(".sha256")
            old_sha.write_text("dummy_hash", encoding="utf-8")

            # Ajusta mtime para 40 dias atrás
            old_time = (datetime.now(timezone.utc) - timedelta(days=40)).timestamp()
            os.utime(old_archive, (old_time, old_time))

            backup_mgr = StateBackupManager(base_dir=base_path, retention_days=30)
            deleted = backup_mgr.rotate_backups()

            assert deleted == 1
            assert not old_archive.exists()
            assert not old_sha.exists()


class TestPhase9RemoteGatewayDualNode:
    """Valida a ponte Dual-Node (Linux Brain <-> Windows Gateway MT5)."""

    @pytest.mark.asyncio
    async def test_gateway_authentication_and_endpoints(self):
        adapter = PaperTradingAdapter(initial_balance=50000.0)
        await adapter.connect()

        token = "SECRET_DUAL_NODE_TOKEN_12345"
        app = create_gateway_app(adapter=adapter, api_token=token)
        client = TestClient(app)

        # 1. Requisição sem token -> 401
        resp_no_auth = client.get("/api/v1/health")
        assert resp_no_auth.status_code == 401

        # 2. Requisição com token errado -> 403
        resp_bad_auth = client.get("/api/v1/health", headers={"Authorization": "Bearer WRONG_TOKEN"})
        assert resp_bad_auth.status_code == 403

        # 3. Requisição com token correto -> 200
        headers = {"Authorization": f"Bearer {token}"}
        resp_health = client.get("/api/v1/health", headers=headers)
        assert resp_health.status_code == 200
        assert resp_health.json()["status"] == "HEALTHY"

        # 4. Consulta AccountState
        resp_acc = client.get("/api/v1/account", headers=headers)
        assert resp_acc.status_code == 200
        data_acc = resp_acc.json()
        assert data_acc["balance"] == 50000.0

        # 5. Consulta Symbols e Ticks
        resp_sym = client.get("/api/v1/symbols/EURUSD", headers=headers)
        assert resp_sym.status_code == 200
        assert resp_sym.json()["symbol"] == "EURUSD"

        tick = MarketTick(
            symbol="EURUSD",
            time=datetime.now(timezone.utc),
            bid=1.1000,
            ask=1.1002,
            last=1.1001,
            volume=10.0,
        )
        adapter.update_tick(tick)

        resp_ticks = client.get("/api/v1/market/ticks/EURUSD?count=10", headers=headers)
        assert resp_ticks.status_code == 200
        assert len(resp_ticks.json()) >= 1

        await adapter.disconnect()

    @pytest.mark.asyncio
    async def test_remote_gateway_adapter_unreachable_fail_safe(self):
        # Aponta para porta inexistente
        remote_adapter = RemoteMT5GatewayAdapter(
            gateway_url="http://127.0.0.1:59999",
            api_token="TOKEN",
            timeout_seconds=0.5,
        )
        connected = await remote_adapter.connect()
        assert connected is False
        assert await remote_adapter.is_connected() is False

        with pytest.raises(PlatformConnectionError):
            await remote_adapter.get_account_state()


class TestPhase9PortfolioCooldownPersistence:
    """Valida a resolução da dívida técnica DEBT-P2-02 (persistência do cooldown)."""

    def test_cooldown_survives_process_restart(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cooldown_file = Path(tmp_dir) / "portfolio_cooldown.json"
            risk_engine = RiskEngine()

            # Instância 1: Registra proposta e persiste
            pm1 = PortfolioManager(
                risk_engine=risk_engine,
                dedup_cooldown_seconds=60,
                cooldown_store_path=cooldown_file,
            )
            t_now = datetime.now(timezone.utc)
            pm1._record_proposal("EURUSD", "BUY", t_now)
            assert pm1._is_duplicate("EURUSD", "BUY", t_now + timedelta(seconds=10)) is True
            assert cooldown_file.exists()

            # Instância 2: Simula reinicialização do processo
            pm2 = PortfolioManager(
                risk_engine=risk_engine,
                dedup_cooldown_seconds=60,
                cooldown_store_path=cooldown_file,
            )
            # 10 segundos após -> Deve continuar bloqueando como duplicata
            assert pm2._is_duplicate("EURUSD", "BUY", t_now + timedelta(seconds=10)) is True
            # 70 segundos após -> Cooldown expirado, deve liberar
            assert pm2._is_duplicate("EURUSD", "BUY", t_now + timedelta(seconds=70)) is False

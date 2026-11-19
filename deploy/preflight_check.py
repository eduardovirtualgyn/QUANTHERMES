"""
QUANT HERMES — VERIFICADOR PRÉ-VOO DE IMPLANTAÇÃO (PREFLIGHT CHECK)
Módulo: deploy.preflight_check

Responsabilidade:
- Executar auditoria de integridade do ambiente antes da inicialização em produção/VPS.
- Bloquear o arranque caso haja violação de diretórios, permissões, banco corrompido ou
  relaxamento ilegal de pisos de risco (Constituição AGENTS.md).
"""
from __future__ import annotations

import os
import sys
import socket
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class PreflightReport:
    """Relatório estruturado de verificação pré-voo."""
    is_ready: bool
    python_version: str
    checks_passed: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    critical_errors: List[str] = field(default_factory=list)

    def summary(self) -> str:
        status_str = "READY FOR DEPLOYMENT" if self.is_ready else "ABORT DEPLOYMENT"
        lines = [
            f"=======================================================",
            f"QUANT HERMES — PREFLIGHT CHECK REPORT: [{status_str}]",
            f"Python Version: {self.python_version}",
            f"Checks Passed: {len(self.checks_passed)}",
            f"Warnings: {len(self.warnings)}",
            f"Critical Errors: {len(self.critical_errors)}",
            f"=======================================================",
        ]
        if self.checks_passed:
            lines.append("PASSED CHECKS:")
            for p in self.checks_passed:
                lines.append(f"  [✓] {p}")
        if self.warnings:
            lines.append("WARNINGS:")
            for w in self.warnings:
                lines.append(f"  [!] {w}")
        if self.critical_errors:
            lines.append("CRITICAL ERRORS:")
            for e in self.critical_errors:
                lines.append(f"  [✗] {e}")
        return "\n".join(lines)


class PreflightChecker:
    """
    Executa verificação diagnóstica abrangente e determinística do ambiente de produção.
    """

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self.base_dir = base_dir or Path.cwd()

    def check_python_version(self) -> Tuple[bool, str]:
        major, minor = sys.version_info.major, sys.version_info.minor
        v_str = f"{major}.{minor}.{sys.version_info.micro}"
        if major == 3 and minor >= 11:
            return True, f"Python {v_str} compatível (>= 3.11)"
        return False, f"Versão incompatível do Python: {v_str} (requer >= 3.11)"

    def check_directories(self) -> Tuple[bool, List[str], List[str]]:
        required_dirs = [
            self.base_dir / "data" / "storage",
            self.base_dir / "data" / "parquet",
            self.base_dir / "logs",
            self.base_dir / "config",
        ]
        passed = []
        errors = []
        for d in required_dirs:
            try:
                d.mkdir(parents=True, exist_ok=True)
                test_file = d / ".preflight_write_test"
                test_file.write_text("ok", encoding="utf-8")
                test_file.unlink(missing_ok=True)
                passed.append(f"Diretório gravável: {d.relative_to(self.base_dir)}")
            except Exception as e:
                errors.append(f"Falha de permissão no diretório {d}: {e}")
        return len(errors) == 0, passed, errors

    def check_sqlite_integrity(self) -> Tuple[bool, List[str], List[str]]:
        storage_dir = self.base_dir / "data" / "storage"
        passed = []
        errors = []
        db_files = list(storage_dir.glob("*.db"))
        if not db_files:
            passed.append("Nenhum banco SQLite existente para verificar (início limpo)")
            return True, passed, errors

        for db in db_files:
            conn = None
            try:
                conn = sqlite3.connect(str(db))
                cursor = conn.cursor()
                cursor.execute("PRAGMA integrity_check;")
                res = cursor.fetchone()
                if res and res[0] == "ok":
                    passed.append(f"Integridade SQLite OK: {db.name}")
                else:
                    errors.append(f"Corrupção detectada no banco {db.name}: {res}")
            except Exception as e:
                errors.append(f"Falha ao abrir banco {db.name}: {e}")
            finally:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass
        return len(errors) == 0, passed, errors

    def check_constitutional_risk_floors(self) -> Tuple[bool, List[str], List[str]]:
        """Verifica se os pisos de risco invioláveis do AGENTS.md estão mantidos."""
        passed = []
        errors = []
        try:
            from risk.engine import RiskEngine
            engine = RiskEngine()
            # Pisos constitucionais
            if engine.max_risk_percentage_hard_cap > 0.50:
                errors.append(f"Piso inviolável violado: Risco por trade ({engine.max_risk_percentage_hard_cap}%) > 0.50%")
            else:
                passed.append(f"Risco por trade dentro do piso: {engine.max_risk_percentage_hard_cap}% <= 0.50%")

            if engine.max_aggregate_open_risk_pct > 1.00:
                errors.append(f"Piso inviolável violado: Risco agregado ({engine.max_aggregate_open_risk_pct}%) > 1.00%")
            else:
                passed.append(f"Risco agregado dentro do piso: {engine.max_aggregate_open_risk_pct}% <= 1.00%")

            if engine.circuit_breakers.drawdown_guard.max_drawdown_limit_pct > 8.00:
                errors.append(f"Piso inviolável violado: Drawdown de emergência ({engine.circuit_breakers.drawdown_guard.max_drawdown_limit_pct}%) > 8.00%")
            else:
                passed.append("Drawdown de emergência protegido em 8.00%")

            if not engine.require_stop_loss:
                errors.append("Piso inviolável violado: require_stop_loss desativado!")
            else:
                passed.append("Stop Loss obrigatório ativo")

        except Exception as e:
            errors.append(f"Erro ao instanciar e verificar RiskEngine: {e}")

        return len(errors) == 0, passed, errors

    def check_port_availability(self, port: int) -> Tuple[bool, str]:
        """Testa se uma porta local está disponível para bind."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1.0)
                res = s.connect_ex(("127.0.0.1", port))
                if res != 0:
                    return True, f"Porta {port} disponível para escuta"
                else:
                    return False, f"Porta {port} já está em uso por outro processo"
        except Exception as e:
            return False, f"Erro ao testar porta {port}: {e}"

    def run_all_checks(self) -> PreflightReport:
        report = PreflightReport(
            is_ready=True,
            python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        )

        # 1. Python
        py_ok, py_msg = self.check_python_version()
        if py_ok:
            report.checks_passed.append(py_msg)
        else:
            report.critical_errors.append(py_msg)
            report.is_ready = False

        # 2. Diretórios
        dir_ok, dir_passed, dir_errors = self.check_directories()
        report.checks_passed.extend(dir_passed)
        if not dir_ok:
            report.critical_errors.extend(dir_errors)
            report.is_ready = False

        # 3. Integridade SQLite
        sql_ok, sql_passed, sql_errors = self.check_sqlite_integrity()
        report.checks_passed.extend(sql_passed)
        if not sql_ok:
            report.critical_errors.extend(sql_errors)
            report.is_ready = False

        # 4. Pisos Constitucionais de Risco
        risk_ok, risk_passed, risk_errors = self.check_constitutional_risk_floors()
        report.checks_passed.extend(risk_passed)
        if not risk_ok:
            report.critical_errors.extend(risk_errors)
            report.is_ready = False

        # 5. Segredos obrigatórios — sem token padrão
        for secret_name in ("HERMES_OPERATOR_TOKEN", "HERMES_GATEWAY_TOKEN", "HERMES_BRIDGE_TOKEN"):
            value = os.getenv(secret_name, "").strip()
            if not value:
                report.critical_errors.append(f"{secret_name} ausente. Não há token padrão; o arranque deve falhar.")
                report.is_ready = False
            elif len(value) < 12:
                report.critical_errors.append(f"{secret_name} curto demais (mínimo 12 caracteres)")
                report.is_ready = False
            else:
                report.checks_passed.append(f"{secret_name} presente")

        entry_ok, entry_passed, entry_errors = self.check_deployment_entrypoints()
        report.checks_passed.extend(entry_passed)
        if not entry_ok:
            report.critical_errors.extend(entry_errors)
            report.is_ready = False

        return report

    def check_deployment_entrypoints(self) -> Tuple[bool, List[str], List[str]]:
        """Confere que o cérebro Linux não importa MetaTrader5 e que a escuta é local."""
        passed: List[str] = []
        errors: List[str] = []
        brain_entry = self.base_dir / "monitoring" / "asgi.py"
        systemd_unit = self.base_dir / "deploy" / "systemd" / "hermes-brain.service"
        compose_files = [
            self.base_dir / "docker-compose.yml",
            self.base_dir / "docker" / "docker-compose.yml",
        ]
        dockerfile = self.base_dir / "docker" / "Dockerfile.brain"

        if not brain_entry.exists():
            errors.append("monitoring/asgi.py ausente: uvicorn monitoring.server:app não expõe `app`")
        else:
            text = brain_entry.read_text(encoding="utf-8")
            imported = any(
                token in text
                for token in ("import MetaTrader5", "from execution.adapters.windows_mt5", "import windows_mt5")
            )
            if imported:
                errors.append("monitoring/asgi.py importa o gateway MT5. O cérebro Linux não pode fazer isso.")
            elif "create_monitoring_app" not in text:
                errors.append("monitoring/asgi.py não constrói a aplicação de monitoramento")
            else:
                passed.append("Cérebro ASGI em monitoring.asgi:app sem import de MetaTrader5")

        if systemd_unit.exists():
            unit = systemd_unit.read_text(encoding="utf-8")
            if "monitoring.asgi:app" not in unit:
                errors.append("systemd não aponta para monitoring.asgi:app")
            elif "0.0.0.0" in unit:
                errors.append("systemd publica o cérebro em 0.0.0.0")
            elif "127.0.0.1" not in unit:
                errors.append("systemd não restringe a escuta a 127.0.0.1")
            else:
                passed.append("systemd escuta em 127.0.0.1 via monitoring.asgi:app")
        else:
            errors.append("Unidade systemd hermes-brain.service ausente")

        for compose in compose_files:
            if not compose.exists():
                continue
            body = compose.read_text(encoding="utf-8")
            if ":-HERMES_" in body or "HERMES_GATEWAY_TOKEN_DEFAULT" in body or "HERMES_RISK_OVERRIDE" in body:
                errors.append(f"{compose.name} ainda tem token padrão embutido")
            if '"8000:8000"' in body or "'8000:8000'" in body or '"8001:8001"' in body:
                errors.append(f"{compose.name} publica porta em todas as interfaces")
            else:
                passed.append(f"{compose.name} não publica 8000/8001 em 0.0.0.0 e não tem token padrão")

        if dockerfile.exists():
            docker_text = dockerfile.read_text(encoding="utf-8")
            if "monitoring.asgi:app" not in docker_text or "0.0.0.0" in docker_text:
                errors.append("Dockerfile.brain não usa monitoring.asgi:app em 127.0.0.1")
            else:
                passed.append("Dockerfile.brain entra por monitoring.asgi:app em 127.0.0.1")

        windows_entry = self.base_dir / "execution" / "windows_gateway_asgi.py"
        if windows_entry.exists():
            passed.append("Gateway Windows separado em execution.windows_gateway_asgi:app")
        else:
            errors.append("Entrypoint do gateway Windows ausente")

        return len(errors) == 0, passed, errors


if __name__ == "__main__":
    checker = PreflightChecker()
    rep = checker.run_all_checks()
    print(rep.summary())
    if not rep.is_ready:
        sys.exit(1)

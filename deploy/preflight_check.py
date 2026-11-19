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

    def run_all_checks(
        self,
        require_terminal: bool = False,
        terminal_probe: Optional[object] = None,
    ) -> PreflightReport:
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

        # 5. Segredos. O gateway remoto é opcional e não exige token quando está desligado.
        required_secrets = ["HERMES_OPERATOR_TOKEN"]
        if os.getenv("HERMES_REMOTE_GATEWAY", "").strip().lower() in {"1", "true", "yes", "on"}:
            required_secrets.extend(["HERMES_GATEWAY_TOKEN", "HERMES_BRIDGE_TOKEN"])
        for secret_name in required_secrets:
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

        if require_terminal:
            term_ok, term_passed, term_errors = self.check_windows_terminal(terminal_probe)
            report.checks_passed.extend(term_passed)
            if not term_ok:
                report.critical_errors.extend(term_errors)
                report.is_ready = False
        else:
            report.checks_passed.append(
                "Checagem do terminal MT5 não exigida (paper ou suíte offline). "
                "No host Windows use --require-terminal."
            )

        return report

    def check_windows_terminal(
        self,
        probe: Optional[object] = None,
    ) -> Tuple[bool, List[str], List[str]]:
        """
        Exige, no Windows com --require-terminal: pacote MetaTrader5, terminal logado,
        moeda USC/cent, símbolos resolvidos e AutoTrading ligado.
        O probe padrão só roda quando o operador pede. A suíte offline injeta um dicionário
        ou não chama este método.
        """
        if sys.platform != "win32" and probe is None:
            return False, [], ["A checagem do terminal MT5 só roda no Windows."]

        snapshot = probe if isinstance(probe, dict) else None
        if snapshot is None:
            caller = probe if callable(probe) else self.live_mt5_probe
            snapshot = caller()
        return self.evaluate_terminal_snapshot(snapshot)

    def evaluate_terminal_snapshot(self, snapshot: Dict[str, object]) -> Tuple[bool, List[str], List[str]]:
        passed: List[str] = []
        errors: List[str] = []
        if not snapshot.get("importable"):
            errors.append("MetaTrader5 não importável neste Python de 64 bits.")
            return False, passed, errors
        passed.append("Pacote MetaTrader5 importável")

        if not snapshot.get("connected"):
            errors.append(
                "Terminal MT5 não está em execução ou não está logado "
                f"({snapshot.get('error') or 'sem terminal_info'})."
            )
            return False, passed, errors
        passed.append("Terminal MT5 em execução")

        login = int(snapshot.get("login") or 0)
        if login <= 0:
            errors.append("Conta MT5 sem login. Abra o terminal RoboForex e entre na conta.")
        else:
            passed.append(f"Conta logada (login {login})")

        currency = str(snapshot.get("currency") or "").upper()
        if currency not in {"USC", "CENT"} and "USC" not in currency:
            errors.append(
                f"Moeda da conta é '{currency or 'vazia'}'. RoboForex ProCent precisa ser USC (cent)."
            )
        else:
            passed.append(f"Moeda da conta {currency} (cent)")

        if not snapshot.get("trade_allowed"):
            errors.append("AutoTrading desligado no terminal (botão Algo Trading).")
        else:
            passed.append("AutoTrading habilitado")

        resolved = snapshot.get("resolved") or {}
        if isinstance(resolved, dict):
            missing = [name for name, ok in resolved.items() if not ok]
            if missing:
                errors.append(
                    "Mapeamento de símbolo não resolveu no terminal: " + ", ".join(missing)
                )
            elif resolved:
                passed.append("Mapeamento de símbolos resolvido no terminal: " + ", ".join(resolved))
            else:
                errors.append("Nenhum símbolo foi verificado no mapeamento.")
        else:
            errors.append("Resposta de mapeamento de símbolos inválida.")

        return len(errors) == 0, passed, errors

    def live_mt5_probe(self) -> Dict[str, object]:
        """
        Lê o terminal local. Não envia ordem. Chamado só com --require-terminal.
        initialize() anexa ao terminal já aberto; não é usado pela suíte offline.
        """
        try:
            import MetaTrader5 as mt5
        except ImportError:
            return {"importable": False, "connected": False, "error": "ImportError"}

        from execution.symbols import SymbolMapper

        if not mt5.initialize():
            err = mt5.last_error()
            return {"importable": True, "connected": False, "error": str(err), "resolved": {}}
        try:
            term = mt5.terminal_info()
            account = mt5.account_info()
            mapper = SymbolMapper()
            try:
                from core.config import load_hermes_config

                config = load_hermes_config(self.base_dir / "config")
                mapper = SymbolMapper(
                    suffix=config.broker.symbol_suffix,
                    aliases=dict(config.broker.symbol_aliases),
                )
                logical = list(config.instruments.keys()) or ["EURUSD", "XAUUSD"]
            except Exception:
                logical = ["EURUSD", "XAUUSD"]
            resolved: Dict[str, bool] = {}
            for name in logical:
                broker_name = mapper.to_broker(name)
                mt5.symbol_select(broker_name, True)
                resolved[name] = mt5.symbol_info(broker_name) is not None
            return {
                "importable": True,
                "connected": bool(term and getattr(term, "connected", False)),
                "trade_allowed": bool(term and getattr(term, "trade_allowed", False)),
                "currency": getattr(account, "currency", "") if account else "",
                "login": int(getattr(account, "login", 0) or 0) if account else 0,
                "resolved": resolved,
                "error": "",
            }
        finally:
            mt5.shutdown()

    def check_deployment_entrypoints(self) -> Tuple[bool, List[str], List[str]]:
        """Deploy suportado é o Windows na mesma máquina do terminal. Docker é opcional."""
        passed: List[str] = []
        errors: List[str] = []
        setup = self.base_dir / "deploy" / "windows" / "setup.ps1"
        service = self.base_dir / "deploy" / "windows" / "service_main.py"
        guide = self.base_dir / "docs" / "deploy" / "WINDOWS.md"
        brain_entry = self.base_dir / "monitoring" / "asgi.py"

        if not setup.exists():
            errors.append("deploy/windows/setup.ps1 ausente")
        else:
            text = setup.read_text(encoding="utf-8")
            if "127.0.0.1" not in text:
                errors.append("setup.ps1 não restringe a API a 127.0.0.1")
            elif "0.0.0.0" in text:
                errors.append("setup.ps1 publica a API em 0.0.0.0")
            else:
                passed.append("setup.ps1 do Windows presente e restrito a 127.0.0.1")

        if not service.exists():
            errors.append("deploy/windows/service_main.py ausente")
        else:
            body = service.read_text(encoding="utf-8")
            if "127.0.0.1" not in body:
                errors.append("service_main.py não fixa o bind em 127.0.0.1")
            else:
                passed.append("service_main.py é o processo único no Windows")

        if not guide.exists():
            errors.append("docs/deploy/WINDOWS.md ausente")
        else:
            passed.append("Guia Windows em docs/deploy/WINDOWS.md")

        if not brain_entry.exists():
            errors.append("monitoring/asgi.py ausente")
        else:
            text = brain_entry.read_text(encoding="utf-8")
            if "import MetaTrader5" in text or "from execution.adapters.windows_mt5" in text:
                errors.append("monitoring/asgi.py importa MetaTrader5 na carga do módulo")
            elif "create_monitoring_app" not in text:
                errors.append("monitoring/asgi.py não constrói a aplicação")
            else:
                passed.append("monitoring.asgi:app não importa MetaTrader5 na carga")

        compose_files = [
            self.base_dir / "docker-compose.yml",
            self.base_dir / "docker" / "docker-compose.yml",
        ]
        for compose in compose_files:
            if not compose.exists():
                continue
            body = compose.read_text(encoding="utf-8")
            if ":-HERMES_" in body or "HERMES_GATEWAY_TOKEN_DEFAULT" in body or "HERMES_RISK_OVERRIDE" in body:
                errors.append(f"{compose.name} ainda tem token padrão embutido")
            if '"8000:8000"' in body or "'8000:8000'" in body or '"8001:8001"' in body:
                errors.append(f"{compose.name} publica porta em todas as interfaces")
            else:
                passed.append(f"{compose.name} é opcional e não publica 8000/8001 em 0.0.0.0")

        return len(errors) == 0, passed, errors


if __name__ == "__main__":
    require = "--require-terminal" in sys.argv or os.getenv("HERMES_REQUIRE_TERMINAL", "") == "1"
    checker = PreflightChecker()
    rep = checker.run_all_checks(require_terminal=require)
    sys.stdout.write(rep.summary() + "\n")
    if not rep.is_ready:
        sys.exit(1)

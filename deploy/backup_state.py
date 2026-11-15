"""
QUANT HERMES — SCRIPT DE BACKUP ATÔMICO E ROTAÇÃO DE ESTADO
Módulo: deploy.backup_state

Responsabilidade:
- Executar snapshots limpos dos bancos transacionais SQLite (usando SQLite Online Backup API)
- Compactar estado operacional e arquivos de auditoria em arquivo .tar.gz com hash SHA-256
- Aplicar rotação automática de backups (retenção padrão: 30 dias)
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional


def compute_sha256(file_path: Path) -> str:
    """Calcula o hash SHA-256 de um arquivo em blocos de 64KB."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


class StateBackupManager:
    """
    Gerenciador de backup e rotação de dados do QUANT HERMES.
    """

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        backup_dir: Optional[Path] = None,
        retention_days: int = 30,
    ) -> None:
        self.base_dir = base_dir or Path.cwd()
        self.storage_dir = self.base_dir / "data" / "storage"
        self.backup_dir = backup_dir or (self.base_dir / "data" / "backups")
        self.retention_days = retention_days
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def execute_backup(self) -> Dict[str, Any]:
        """Executa um ciclo completo de backup com consistência transacional."""
        timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        archive_name = f"hermes_state_backup_{timestamp_str}.tar.gz"
        archive_path = self.backup_dir / archive_name

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            files_copied = []

            # 1. Backup Online de Bancos SQLite (evita corrupção com WAL ativo)
            if self.storage_dir.exists():
                for db_file in self.storage_dir.glob("*.db"):
                    dest_db = tmp_path / db_file.name
                    try:
                        src_conn = sqlite3.connect(str(db_file))
                        dst_conn = sqlite3.connect(str(dest_db))
                        src_conn.backup(dst_conn)
                        dst_conn.close()
                        src_conn.close()
                        files_copied.append(db_file.name)
                    except Exception as e:
                        # Fallback seguro: cópia direta de arquivo
                        shutil.copy2(db_file, dest_db)
                        files_copied.append(db_file.name)

                # 2. Cópia de arquivos de estado JSON (Kill Switch, Cooldown, etc.)
                for json_file in self.storage_dir.glob("*.json"):
                    shutil.copy2(json_file, tmp_path / json_file.name)
                    files_copied.append(json_file.name)

            # 3. Criação do arquivo compactado tar.gz
            with tarfile.open(archive_path, "w:gz") as tar:
                for item in tmp_path.iterdir():
                    tar.add(item, arcname=item.name)

        # 4. Cálculo de Checksum SHA-256
        checksum = compute_sha256(archive_path)
        checksum_file = archive_path.with_suffix(".sha256")
        checksum_file.write_text(f"{checksum}  {archive_name}\n", encoding="utf-8")

        # 5. Aplicação da Política de Rotação
        deleted_count = self.rotate_backups()

        return {
            "status": "SUCCESS",
            "archive_path": str(archive_path),
            "archive_name": archive_name,
            "size_bytes": archive_path.stat().st_size,
            "sha256": checksum,
            "files_backed_up": files_copied,
            "pruned_old_backups": deleted_count,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }

    def rotate_backups(self) -> int:
        """Remove arquivos de backup que excedem a janela de retenção configurada."""
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        deleted_count = 0

        for item in self.backup_dir.glob("hermes_state_backup_*.tar.gz"):
            try:
                mtime = datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff_date:
                    item.unlink(missing_ok=True)
                    sha_file = item.with_suffix(".sha256")
                    sha_file.unlink(missing_ok=True)
                    deleted_count += 1
            except Exception:
                pass

        return deleted_count


if __name__ == "__main__":
    manager = StateBackupManager()
    res = manager.execute_backup()
    print(f"Backup concluído: {res['archive_name']} | SHA-256: {res['sha256'][:16]} | Arquivos: {len(res['files_backed_up'])}")

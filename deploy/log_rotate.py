"""
QUANT HERMES — Rotação de logs por tamanho
Módulo: deploy.log_rotate

Usa pathlib. O agendador de tarefas do Windows chama este módulo todo dia.
"""
from __future__ import annotations

import sys
from pathlib import Path


def rotate_file(path: Path, max_bytes: int = 52_428_800, backup_count: int = 7) -> bool:
    """Renomeia o log se passou do tamanho. Retorna True quando girou."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size < max_bytes or backup_count < 1:
        return False

    oldest = path.with_name(f"{path.name}.{backup_count}")
    if oldest.exists():
        oldest.unlink()
    for index in range(backup_count - 1, 0, -1):
        src = path.with_name(f"{path.name}.{index}")
        dst = path.with_name(f"{path.name}.{index + 1}")
        if src.exists():
            src.replace(dst)
    path.replace(path.with_name(f"{path.name}.1"))
    return True


def rotate_directory(log_dir: Path, max_bytes: int = 52_428_800, backup_count: int = 7) -> int:
    log_dir = Path(log_dir)
    if not log_dir.is_dir():
        return 0
    rotated = 0
    for path in log_dir.glob("*.log"):
        if rotate_file(path, max_bytes=max_bytes, backup_count=backup_count):
            rotated += 1
    return rotated


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    count = rotate_directory(root / "logs")
    sys.stdout.write(f"logs rotacionados: {count}\n")

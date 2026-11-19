"""Nenhum módulo do pacote importa código GPL/AGPL da pasta references/."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = ("core", "execution", "risk", "strategies", "intelligence", "portfolio", "monitoring", "data", "deploy")
FORBIDDEN = (
    "import ea31337",
    "from ea31337",
    "import nexus",
    "from nexus",
    "references.ea31337",
    "references.nexus",
    "from references",
    "import references",
)


def test_main_package_does_not_import_copyleft_references():
    offenders = []
    for folder in SCAN_ROOTS:
        for path in (ROOT / folder).rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            for token in FORBIDDEN:
                if token in text:
                    offenders.append(f"{path.relative_to(ROOT)} contém '{token}'")
    assert offenders == []


def test_references_directory_is_gitignored():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "references/" in gitignore

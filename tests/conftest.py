"""
Configurações Globais de Testes do pytest
Arquivo: tests/conftest.py
"""
import sys
from pathlib import Path
import pytest

# Garante que o diretório raiz do projeto esteja no sys.path
root_dir = str(Path(__file__).resolve().parent.parent)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)


@pytest.fixture(scope="function")
def anyio_backend():
    return "asyncio"

"""
Configurações Globais de Testes do pytest
Arquivo: tests/conftest.py
"""
"""
Configurações Globais de Testes do pytest
Arquivo: tests/conftest.py
"""
import asyncio
import sys
from pathlib import Path
import pytest

# Garante que o diretório raiz do projeto esteja no sys.path
root_dir = str(Path(__file__).resolve().parent.parent)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(scope="session")
def event_loop_policy():
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture(scope="function")
def anyio_backend():
    return "asyncio"


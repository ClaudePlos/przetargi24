import sys
from pathlib import Path

# Testy uruchamiamy bez instalowania pakietu — dokładamy ./src do ścieżki.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from przetargi.config import load_config


@pytest.fixture(scope="session")
def config():
    return load_config()

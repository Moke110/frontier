import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def kl_home(tmp_path):
    home = tmp_path / "home"
    shutil.copytree(ROOT / "fixtures" / "home", home)
    return home


@pytest.fixture
def fixtures_dir():
    return ROOT / "fixtures" / "papers"

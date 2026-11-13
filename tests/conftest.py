import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# Folder berisi data/, samples/ (default: <repo>/paket, atau folder induk proyek)
_inside = os.path.join(ROOT, 'paket')
PAKET = os.environ.get('PAKET_DIR', _inside if os.path.isdir(_inside) else os.path.dirname(ROOT))


def p(*parts):
    return os.path.join(PAKET, *parts)


@pytest.fixture
def paket():
    return p

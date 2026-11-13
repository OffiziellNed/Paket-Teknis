"""Entry point Vercel (Python runtime). Semua request diarahkan ke sini oleh vercel.json."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402

app = create_app()

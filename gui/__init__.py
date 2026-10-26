"""TermoLab2D — interface didática do simulador de gás de partículas 2D."""
from pathlib import Path

try:
    __version__ = (Path(__file__).resolve().parent.parent / "VERSION").read_text(encoding="utf-8").strip()
except OSError:
    __version__ = "dev"

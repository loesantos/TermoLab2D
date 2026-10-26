#!/usr/bin/env python3
"""TermoLab2D — interface didática: escolha um caso, ajuste os parâmetros e acompanhe a simulação.

Uso:  python3 interface.py
"""
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ICON = ROOT / "gui" / "icone.png"


def _log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "state")
    return Path(base) / "TermoLab2D"


def _report(text: str, app=None) -> None:
    """Grava o erro num arquivo de log e mostra uma janela (com pythonw não há terminal)."""
    log = None
    try:
        d = _log_dir()
        d.mkdir(parents=True, exist_ok=True)
        log = d / "erro.log"
        with log.open("a", encoding="utf-8") as out:
            out.write(text + "\n" + "-" * 70 + "\n")
    except OSError:
        pass
    print(text, file=sys.stderr)
    try:
        from PySide6 import QtWidgets
        app = app or QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Critical, "TermoLab2D — erro",
                                    "Ocorreu um erro inesperado." + (f"\n\nDetalhes gravados em:\n{log}" if log else ""))
        box.setDetailedText(text)
        box.exec()
    except Exception:  # noqa: BLE001 — sem Qt, resta o terminal
        pass


def main() -> int:
    try:
        from PySide6 import QtGui, QtWidgets
        import pyqtgraph  # noqa: F401
    except ImportError as exc:
        msg = (f"Dependência ausente: {exc.name}. Instale com:\n"
               "    python3 -m pip install -r requirements.txt")
        _report(msg + "\n\n" + traceback.format_exc())
        return 1
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("TermoLab2D")
    app.setStyle("Fusion")
    if ICON.is_file():
        app.setWindowIcon(QtGui.QIcon(str(ICON)))
    # Erros não tratados durante o uso: mostra e registra em vez de fechar em silêncio.
    sys.excepthook = lambda t, v, tb: _report("".join(traceback.format_exception(t, v, tb)), app)
    from gui.main_window import MainWindow
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        _report(traceback.format_exc())
        raise SystemExit(1)

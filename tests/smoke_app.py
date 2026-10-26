#!/usr/bin/env python3
"""Teste de fumaça da interface: abre a janela, roda cada caso por pouco tempo e abre o manual.

Usado pelo GitHub Actions para verificar os pacotes instalados (.deb e instalador do Windows),
mas também serve localmente:

    python3 tests/smoke_app.py                       # código desta pasta
    /opt/termolab2d/python/bin/python3 tests/smoke_app.py --app /opt/termolab2d/app
    "%LOCALAPPDATA%\\Programs\\TermoLab2D\\python\\python.exe" tests\\smoke_app.py --app "...\\TermoLab2D\\app"

Sai com código 1 se algum caso falhar.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

CASES = ["expansion", "channel", "h_theorem", "mixing", "equilibrium", "ideal_gas",
         "conduction", "heating", "piston"]
QUICK = dict(particles=300, n_each=150, t_final=1.0, t_equil=0.5, piston_speed=5.0)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--app", type=Path, default=Path(__file__).resolve().parent.parent,
                    help="pasta com interface.py e gui/")
    ap.add_argument("--screenshot", type=Path, help="salva uma imagem da janela no fim")
    ap.add_argument("--timeout", type=float, default=300.0, help="limite por caso, em segundos")
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):      # console do Windows (cp1252) e símbolos como Δ
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.path.insert(0, str(args.app.resolve()))

    from PySide6 import QtWidgets
    from gui import __version__
    from gui import scenarios as sc
    from gui.main_window import MainWindow
    from gui.simulator import find_executable

    failures: list[str] = []
    # caixas de diálogo de erro bloqueariam o teste sem ninguém para fechá-las: viram falhas
    def no_dialog(_parent, title, text, *a, **k):
        failures.append(f"{title}: {text}")
        return QtWidgets.QMessageBox.Ok
    QtWidgets.QMessageBox.critical = staticmethod(no_dialog)
    QtWidgets.QMessageBox.information = staticmethod(no_dialog)
    app = QtWidgets.QApplication(sys.argv)
    print(f"TermoLab2D {__version__} — plataforma Qt: {app.platformName()}", flush=True)
    print("simulador:", find_executable(log=lambda *_: None), flush=True)
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    for sid in CASES:
        w.load_scenario(sc.by_id(sid))
        for form in w.forms.values():
            form.set_values({k: v for k, v in QUICK.items() if k in form.widgets})
        w.speed_combo.setCurrentIndex(w.speed_combo.count() - 1)   # velocidade máxima
        t0 = time.time()
        w.start()
        if w.run is None:
            failures.append(f"{sid}: não iniciou")
            continue
        run = w.run
        while w.run is not None and time.time() - t0 < args.timeout:
            app.processEvents()
            time.sleep(0.005)
        if w.run is not None:
            w.stop()
            failures.append(f"{sid}: tempo esgotado")
        elif run.error:
            failures.append(f"{sid}: {run.error}")
        elif not w.store or not w.store.time:
            failures.append(f"{sid}: nenhum quadro recebido")
        print(f"{sid:12s} {time.time() - t0:6.1f} s | {w.status_label.text()}", flush=True)
    w.show_manual("caso-piston")
    for _ in range(20):
        app.processEvents()
    if "TermoLab2D" not in w.manual.browser.toPlainText():
        failures.append("manual: não carregou")
    if args.screenshot:
        w.grab().save(str(args.screenshot))
    w.close()
    if failures:
        print("FALHAS:\n  " + "\n  ".join(failures), flush=True)
        return 1
    print("OK: todos os casos rodaram.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

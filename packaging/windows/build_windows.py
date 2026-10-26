#!/usr/bin/env python3
"""Gera o instalador do TermoLab2D para Windows (64 bits) a partir do Linux.

Requisitos no Linux (Ubuntu/Debian/Mint):
    sudo apt install g++-mingw-w64-x86-64-posix nsis zstd unzip
    (e acesso à internet: conda.anaconda.org e pypi.org)

Uso, na pasta do projeto:
    python3 packaging/windows/build_windows.py
O instalador sai em  instalador/TermoLab2D-<versão>-instalador.exe

O que é empacotado:
* simulator.exe — compilado com MinGW-w64, OpenMP estático (sem DLLs extras);
* um Python 3.12 completo para Windows (pacotes do conda-forge), sem tkinter/testes;
* PySide6-Essentials (só os módulos Qt usados), numpy, pyqtgraph, colorama (wheels do PyPI);
* o código da interface, o manual, os exemplos e o ícone.
A instalação é por usuário (sem pedir administrador), em %LOCALAPPDATA%\\Programs\\TermoLab2D.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
# versão: variável TERMOLAB2D_VERSION (usada pelo GitHub Actions a partir da tag) ou arquivo VERSION
VERSION = os.environ.get("TERMOLAB2D_VERSION") or (ROOT / "VERSION").read_text(encoding="utf-8").strip()
CACHE = HERE / "_cache"
STAGE = HERE / "_stage" / "TermoLab2D"
OUT = ROOT / "instalador"

CONDA = "https://conda.anaconda.org/conda-forge/win-64/"
# Python 3.12 do conda-forge e as bibliotecas de que ele depende (versões fixas = build reprodutível)
CONDA_PKGS = [
    "python-3.12.16-hb12b558_0_cpython.conda",
    "libpython-3.12.16-hfb4101e_0_cpython.conda",
    "vc14_runtime-14.51.36247-habf1de7_41.conda",
    "bzip2-1.0.8-h0ad9c76_10.conda",
    "libexpat-2.8.5-hac47afa_0.conda",
    "libffi-3.7.0-h3d046cb_1.conda",
    "liblzma-5.8.3-hfd05255_1.conda",
    "libzlib-1.3.2-hfd05255_3.conda",
    "libmpdec-4.0.0-hfd05255_2.conda",
]
WHEELS = ["PySide6-Essentials==6.12.0", "shiboken6==6.12.0", "numpy==2.5.4", "pyqtgraph==0.14.0", "colorama==0.4.6"]
QT_MODULES = ["QtCore", "QtGui", "QtWidgets", "QtPrintSupport", "QtSvg", "QtSvgWidgets", "QtOpenGL", "QtOpenGLWidgets"]
QT_PLUGINS = ["platforms/qwindows.dll", "platforms/qoffscreen.dll", "platforms/qminimal.dll",
              "styles/qmodernwindowsstyle.dll", "imageformats/qjpeg.dll", "imageformats/qico.dll",
              "imageformats/qsvg.dll", "iconengines/qsvgicon.dll"]
# ssl e sqlite3 não são usados pelo programa: ficam de fora (o hashlib usa as implementações internas)
RUNTIME_DLLS = ["ffi-8", "libbz2", "libexpat", "liblzma", "libmpdec-4", "zlib"]
STDLIB_DROP = ["test", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib2to3", "pydoc_data", "venv"]


def run(cmd, **kw):
    print("+", " ".join(map(str, cmd)))
    subprocess.run(cmd, check=True, **kw)


def download(url: str, dest: Path):
    if dest.exists() and dest.stat().st_size > 0:
        return
    print("baixando", url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=300) as r, tmp.open("wb") as out:
        shutil.copyfileobj(r, out)
    tmp.rename(dest)


def extract_conda(pkg: Path, prefix: Path):
    """Um .conda é um zip com pkg-*.tar.zst dentro."""
    with zipfile.ZipFile(pkg) as z:
        for name in z.namelist():
            if name.startswith("pkg-") and name.endswith(".tar.zst"):
                tmp = CACHE / "tmp.tar.zst"
                tmp.write_bytes(z.read(name))
                run(["zstd", "-d", "-q", "-f", str(tmp), "-o", str(tmp.with_suffix(""))])
                with tarfile.open(tmp.with_suffix("")) as t:
                    t.extractall(prefix, filter="data") if sys.version_info >= (3, 12) else t.extractall(prefix)
                tmp.unlink()
                tmp.with_suffix("").unlink()


def build_simulator(dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    run(["x86_64-w64-mingw32-g++-posix", "-O3", "-std=c++17", "-fopenmp", "-static", "-municode", "-s",
         str(ROOT / "src" / "main.cpp"), "-o", str(dest / "simulator.exe")])


def build_python(dest: Path):
    prefix = CACHE / "conda_prefix"
    if not (prefix / "python.exe").exists():
        for p in CONDA_PKGS:
            download(CONDA + p, CACHE / "conda" / p)
            extract_conda(CACHE / "conda" / p, prefix)
    dest.mkdir(parents=True)
    for f in ["python.exe", "pythonw.exe", "python3.dll", "python312.dll", "vcruntime140.dll",
              "vcruntime140_1.dll", "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "concrt140.dll",
              "LICENSE_PYTHON.txt"]:
        shutil.copy2(prefix / f, dest / f)
    for f in RUNTIME_DLLS:
        shutil.copy2(prefix / "Library" / "bin" / f"{f}.dll", dest)
    shutil.copytree(prefix / "DLLs", dest / "DLLs")
    shutil.copytree(prefix / "Lib", dest / "Lib", ignore=shutil.ignore_patterns("__pycache__"))
    for d in STDLIB_DROP:
        shutil.rmtree(dest / "Lib" / d, ignore_errors=True)
    for f in list((dest / "DLLs").iterdir()):
        if f.name.startswith(("_test", "xxlimited", "_ctypes_test", "_tkinter", "tcl", "tk", "_ssl", "_hashlib",
                              "_sqlite3")) or f.suffix == ".pdb":
            f.unlink()
    sp = dest / "Lib" / "site-packages"
    shutil.rmtree(sp, ignore_errors=True)
    sp.mkdir()
    wheels = CACHE / "wheels"
    wheels.mkdir(parents=True, exist_ok=True)
    run([sys.executable, "-m", "pip", "download", "--no-deps", "--only-binary=:all:", "--platform", "win_amd64",
         "--python-version", "3.12", "--implementation", "cp", "-d", str(wheels), *WHEELS])
    for w in sorted(wheels.glob("*.whl")):
        with zipfile.ZipFile(w) as z:
            z.extractall(sp)
    prune_pyside(sp / "PySide6")
    for p in [sp / "pyqtgraph" / "examples", sp / "pyqtgraph" / "opengl"]:
        shutil.rmtree(p, ignore_errors=True)
    for t in list(sp.glob("numpy/**/tests")) + [sp / "numpy" / "f2py", sp / "numpy" / "_core" / "include"]:
        shutil.rmtree(t, ignore_errors=True)
    for f in sp.rglob("*.pyi"):           # anotações de tipo: inúteis em tempo de execução
        f.unlink()
    for f in ["vcamp140.dll", "vccorlib140.dll", "vcomp140.dll", "shiboken6.abi3.lib"]:
        (sp / "shiboken6" / f).unlink(missing_ok=True)
    shutil.rmtree(sp / "shiboken6" / "include", ignore_errors=True)
    shutil.rmtree(sp / "shiboken6" / "lib", ignore_errors=True)


def dll_imports(path: Path) -> set[str]:
    out = subprocess.run(["x86_64-w64-mingw32-objdump", "-p", str(path)], capture_output=True, text=True).stdout
    return set(re.findall(r"DLL Name: (\S+)", out))


def prune_pyside(pyside: Path):
    """Mantém só os módulos Qt usados e as DLLs de que eles dependem."""
    local = {f.name.lower(): f.name for f in pyside.glob("*.dll")}
    todo = [pyside / f"{m}.pyd" for m in QT_MODULES] + [pyside / "plugins" / p for p in QT_PLUGINS]
    need, seen = set(), set()
    while todo:
        f = todo.pop()
        if f in seen or not f.exists():
            continue
        seen.add(f)
        for d in dll_imports(f):
            if d.lower() in local:
                need.add(local[d.lower()])
                todo.append(pyside / local[d.lower()])
    for f in list(pyside.iterdir()):
        if f.suffix == ".dll" and f.name not in need:
            f.unlink()
        elif f.suffix in (".pyd", ".pyi") and f.name.startswith("Qt") and f.stem not in QT_MODULES:
            f.unlink()
        elif f.suffix in (".exe", ".lib"):
            f.unlink()
        elif f.is_dir() and f.name in ("qml", "translations", "resources", "metatypes", "include", "lib",
                                       "typesystems", "glue", "doc", "scripts"):
            shutil.rmtree(f)
    plugins = pyside / "plugins"
    for f in list(plugins.rglob("*")):
        if f.is_file() and str(f.relative_to(plugins)).replace(os.sep, "/") not in QT_PLUGINS:
            f.unlink()
    for d in sorted(plugins.rglob("*"), reverse=True):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()


def copy_app(dest: Path):
    dest.mkdir(parents=True)
    ign = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(ROOT / "gui", dest / "gui", ignore=ign)
    for f in ["interface.py", "vtk_export.py", "create_geometry.py", "README.md", "requirements.txt", "LICENSE"]:
        shutil.copy2(ROOT / f, dest / f)
    (dest / "VERSION").write_text(VERSION + "\n", encoding="utf-8")
    shutil.copytree(ROOT / "examples", dest / "examples",
                    ignore=shutil.ignore_patterns("*.png", "paraview_preview", "paraview_preview.cfg"))
    build_simulator(dest / "bin" / "windows")
    pdf = ROOT / "Manual_TermoLab2D.pdf"
    if pdf.exists():
        shutil.copy2(pdf, dest / pdf.name)


def main():
    for tool in ["x86_64-w64-mingw32-g++-posix", "x86_64-w64-mingw32-objdump", "makensis", "zstd"]:
        if not shutil.which(tool):
            sys.exit(f"Ferramenta ausente: {tool}. Veja os requisitos no início deste arquivo.")
    shutil.rmtree(STAGE.parent, ignore_errors=True)
    copy_app(STAGE / "app")
    build_python(STAGE / "python")
    shutil.copy2(HERE / "icone.ico", STAGE / "icone.ico")
    OUT.mkdir(exist_ok=True)
    size_kb = sum(f.stat().st_size for f in STAGE.rglob("*") if f.is_file()) // 1024
    nums = [n for n in re.findall(r"\d+", VERSION)][:4]
    vi_version = ".".join((nums + ["0"] * 4)[:4])     # o Windows exige x.x.x.x numérico
    run(["makensis", "-V2", f"-DVERSION={VERSION}", f"-DVIVERSION={vi_version}", f"-DSTAGE={STAGE}", f"-DOUTDIR={OUT}",
         f"-DSIZE_KB={size_kb}", str(HERE / "TermoLab2D.nsi")])
    exe = OUT / f"TermoLab2D-{VERSION}-instalador.exe"
    print(f"\nPronto: {exe} ({exe.stat().st_size / 1e6:.1f} MB; instalado: {size_kb / 1024:.0f} MB)")


if __name__ == "__main__":
    main()

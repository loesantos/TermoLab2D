#!/usr/bin/env python3
"""Gera o pacote .deb do TermoLab2D (amd64) para Debian, Ubuntu, Mint e derivados.

Requisitos (no Debian/Ubuntu/Mint onde o pacote é gerado):
    sudo apt install g++ zstd unzip dpkg-dev binutils
    (e acesso à internet: conda.anaconda.org e pypi.org)

Uso, na pasta do projeto:
    python3 packaging/linux/build_deb.py
O pacote sai em  instalador/termolab2d_<versão>_amd64.deb
Instalação:  sudo apt install ./termolab2d_<versão>_amd64.deb

O pacote é autocontido: leva um Python 3.12 (conda-forge), PySide6, numpy e pyqtgraph em
/opt/termolab2d, sem depender da versão do Python do sistema. O simulador é compilado
estaticamente. Do sistema vêm só as bibliotecas gráficas (X11/xcb, OpenGL, fontes), listadas
em Depends — calculadas automaticamente a partir das bibliotecas usadas pelo Qt.
Compatível com glibc >= 2.28 (Debian 10+, Ubuntu 20.04+, Mint 20+).
"""
from __future__ import annotations

import gzip
from email.utils import formatdate
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

DEB_REVISION = "1"
PACKAGE = "termolab2d"
MAINTAINER = os.environ.get("TERMOLAB2D_MAINTAINER", "TermoLab2D <termolab2d@example.org>")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
# versão: variável TERMOLAB2D_VERSION (usada pelo GitHub Actions a partir da tag) ou arquivo VERSION
VERSION = os.environ.get("TERMOLAB2D_VERSION") or (ROOT / "VERSION").read_text(encoding="utf-8").strip()
CACHE = HERE / "_cache"
STAGE = HERE / "_stage"
PKGROOT = STAGE / "pkg"
OPT = PKGROOT / "opt" / PACKAGE
OUT = ROOT / "instalador"

CONDA = "https://conda.anaconda.org/conda-forge/linux-64/"
CONDA_PKGS = [
    "python-3.12.16-h5f976f7_0_cpython.conda",
    "libgcc-16.2.0-ha9f2e26_7.conda",
    "bzip2-1.0.8-hda65f42_10.conda",
    "libexpat-2.8.5-hd2095e1_0.conda",
    "libuuid-2.42.4-hcfc3c73_0.conda",
    "liblzma-5.8.3-hb03c661_1.conda",
    "libzlib-1.3.2-h25fd6f3_3.conda",
    "libxcrypt-4.4.38-h280c20c_0.conda",
    "libffi-3.7.0-h81df57d_1.conda",
]
RUNTIME_LIBS = ["libgcc_s.so.1", "libbz2.so.1.0", "libexpat.so.1", "libffi.so.8", "liblzma.so.5", "libz.so.1",
                "libuuid.so.1", "libcrypt.so.2"]
# PySide6 6.9 é a última série com wheels manylinux_2_28 (glibc 2.28); a 6.10+ exige glibc 2.34.
WHEELS = ["PySide6-Essentials==6.9.3", "shiboken6==6.9.3", "numpy==2.5.4", "pyqtgraph==0.14.0",
          "colorama==0.4.6"]   # o pyqtgraph 0.14 importa o colorama em qualquer sistema
QT_MODULES = ["QtCore", "QtGui", "QtWidgets", "QtPrintSupport", "QtSvg", "QtSvgWidgets", "QtOpenGL", "QtOpenGLWidgets"]
QT_PLUGINS = ["platforms/libqxcb.so", "platforms/libqoffscreen.so", "platforms/libqminimal.so",
              "xcbglintegrations/libqxcb-glx-integration.so", "xcbglintegrations/libqxcb-egl-integration.so",
              "platformthemes/libqxdgdesktopportal.so", "platformthemes/libqgtk3.so",
              "platforminputcontexts/libcomposeplatforminputcontextplugin.so",
              "platforminputcontexts/libibusplatforminputcontextplugin.so",
              "imageformats/libqjpeg.so", "imageformats/libqico.so", "imageformats/libqsvg.so",
              "iconengines/libqsvgicon.so"]
OPTIONAL_PLUGINS = {"platformthemes/libqgtk3.so"}   # suas dependências viram Recommends
STDLIB_DROP = ["test", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib2to3", "pydoc_data", "venv",
               "config-3.12-x86_64-linux-gnu"]
DYNLOAD_DROP = ("_curses", "_hashlib", "_ssl", "_sqlite3", "_tkinter", "readline", "nis", "_test", "xxlimited",
                "_xxtestfuzz", "_ctypes_test")


def run(cmd, **kw):
    print("+", " ".join(map(str, cmd)))
    return subprocess.run(cmd, check=True, **kw)


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
    with zipfile.ZipFile(pkg) as z:
        for name in z.namelist():
            if name.startswith("pkg-") and name.endswith(".tar.zst"):
                tmp = CACHE / "tmp.tar.zst"
                tmp.write_bytes(z.read(name))
                run(["zstd", "-d", "-q", "-f", str(tmp), "-o", str(tmp.with_suffix(""))])
                with tarfile.open(tmp.with_suffix("")) as t:
                    t.extractall(prefix, filter="tar") if sys.version_info >= (3, 12) else t.extractall(prefix)
                tmp.unlink()
                tmp.with_suffix("").unlink()


# --------------------------------------------------------------------------- Python
def build_python(dest: Path):
    prefix = CACHE / "conda_prefix"
    if not (prefix / "bin" / "python3.12").exists():
        for p in CONDA_PKGS:
            download(CONDA + p, CACHE / "conda" / p)
            extract_conda(CACHE / "conda" / p, prefix)
    (dest / "bin").mkdir(parents=True)
    (dest / "lib").mkdir()
    shutil.copy2(prefix / "bin" / "python3.12", dest / "bin" / "python3.12", follow_symlinks=True)
    (dest / "bin" / "python3").symlink_to("python3.12")
    for f in RUNTIME_LIBS:
        shutil.copy2(prefix / "lib" / f, dest / "lib" / f, follow_symlinks=True)
    shutil.copytree(prefix / "lib" / "python3.12", dest / "lib" / "python3.12", symlinks=False,
                    ignore=shutil.ignore_patterns("__pycache__"))
    std = dest / "lib" / "python3.12"
    for d in STDLIB_DROP:
        shutil.rmtree(std / d, ignore_errors=True)
    for f in (std / "lib-dynload").iterdir():
        if f.name.startswith(DYNLOAD_DROP):
            f.unlink()
    sp = std / "site-packages"
    shutil.rmtree(sp, ignore_errors=True)
    sp.mkdir()
    wheels = CACHE / "wheels"
    wheels.mkdir(parents=True, exist_ok=True)
    run([sys.executable, "-m", "pip", "download", "--no-deps", "--only-binary=:all:",
         "--platform", "manylinux_2_28_x86_64", "--platform", "manylinux_2_27_x86_64",
         "--platform", "manylinux_2_17_x86_64", "--platform", "manylinux2014_x86_64",
         "--python-version", "3.12", "--implementation", "cp", "-d", str(wheels), *WHEELS])
    for w in sorted(wheels.glob("*.whl")):
        with zipfile.ZipFile(w) as z:
            for info in z.infolist():
                z.extract(info, sp)
                mode = (info.external_attr >> 16) & 0o777
                if mode:
                    os.chmod(sp / info.filename, mode)
    prune_pyside(sp / "PySide6")
    for p in [sp / "pyqtgraph" / "examples", sp / "pyqtgraph" / "opengl", sp / "numpy" / "f2py",
              sp / "numpy" / "_core" / "include"]:
        shutil.rmtree(p, ignore_errors=True)
    for t in list(sp.glob("numpy/**/tests")):
        shutil.rmtree(t, ignore_errors=True)
    for f in sp.rglob("*.pyi"):
        f.unlink()
    for f in dest.rglob("*.so*"):          # remove símbolos de depuração (menor e sem avisos do lintian)
        if f.is_file() and not f.is_symlink():
            subprocess.run(["strip", "--strip-debug", str(f)], capture_output=True)


def needed(path: Path) -> list[str]:
    out = subprocess.run(["readelf", "-d", str(path)], capture_output=True, text=True).stdout
    return re.findall(r"\(NEEDED\)\s+Shared library: \[(.+?)\]", out)


def prune_pyside(pyside: Path):
    qtlib = pyside / "Qt" / "lib"
    local = {f.name: f for f in qtlib.iterdir()} | {f.name: f for f in pyside.glob("lib*.so*")}
    todo = [pyside / f"{m}.abi3.so" for m in QT_MODULES] + [pyside / "Qt" / "plugins" / p for p in QT_PLUGINS]
    keep, seen = set(), set()
    while todo:
        f = todo.pop()
        if f in seen or not f.exists():
            continue
        seen.add(f)
        for n in needed(f):
            if n in local:
                keep.add(n)
                todo.append(local[n])
    for f in list(qtlib.iterdir()):
        if f.name not in keep:
            shutil.rmtree(f) if f.is_dir() else f.unlink()
    for f in list(pyside.iterdir()):
        if f.name.startswith("Qt") and f.name.endswith((".abi3.so", ".pyi")) and f.name.split(".")[0] not in QT_MODULES:
            f.unlink()
        elif f.is_file() and f.name.startswith("lib") and ".so" in f.name and f.name not in keep:
            f.unlink()
        elif f.is_file() and os.access(f, os.X_OK) and not f.name.endswith((".so", ".py")) and ".so." not in f.name:
            f.unlink()   # designer, linguist, lupdate…
        elif f.is_dir() and f.name in ("include", "typesystems", "glue", "doc", "scripts"):
            shutil.rmtree(f)
    for d in ("qml", "translations", "metatypes", "libexec"):
        shutil.rmtree(pyside / "Qt" / d, ignore_errors=True)
    plugins = pyside / "Qt" / "plugins"
    for f in list(plugins.rglob("*")):
        if f.is_file() and str(f.relative_to(plugins)) not in QT_PLUGINS:
            f.unlink()
    for d in sorted(plugins.rglob("*"), reverse=True):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()


# --------------------------------------------------------------------------- app
def copy_app(dest: Path):
    dest.mkdir(parents=True)
    ign = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(ROOT / "gui", dest / "gui", ignore=ign)
    for f in ["interface.py", "vtk_export.py", "create_geometry.py", "README.md", "requirements.txt", "LICENSE"]:
        shutil.copy2(ROOT / f, dest / f)
    (dest / "VERSION").write_text(VERSION + "\n", encoding="utf-8")
    shutil.copytree(ROOT / "examples", dest / "examples",
                    ignore=shutil.ignore_patterns("*.png", "paraview_preview", "paraview_preview.cfg"))
    sim = dest / "bin" / "linux"
    sim.mkdir(parents=True)
    # estático: não depende da glibc/libgomp da distribuição
    run(["g++", "-O3", "-std=c++17", "-fopenmp", "-static", "-s", str(ROOT / "src" / "main.cpp"),
         "-o", str(sim / "simulator")], stderr=subprocess.DEVNULL)
    pdf = ROOT / "Manual_TermoLab2D.pdf"
    if pdf.exists():
        shutil.copy2(pdf, dest / pdf.name)


LAUNCHER = """#!/bin/sh
# TermoLab2D — termodinâmica partícula a partícula
# Sem plugin Wayland no pacote: em sessões Wayland o Qt usa o XWayland (xcb).
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
export PYTHONNOUSERSITE=1
unset PYTHONHOME PYTHONPATH
exec /opt/termolab2d/python/bin/python3 /opt/termolab2d/app/interface.py "$@"
"""

DESKTOP = """[Desktop Entry]
Type=Application
Name=TermoLab2D
GenericName=Laboratório de termodinâmica
Comment=Termodinâmica partícula a partícula: simulação didática de um gás em 2D
Exec=termolab2d
Icon=termolab2d
Terminal=false
Categories=Education;Science;Physics;
Keywords=termodinâmica;física;gás;entropia;simulação;dinâmica molecular;
StartupWMClass=TermoLab2D
Actions=manual;

[Desktop Action manual]
Name=Manual do TermoLab2D (PDF)
Exec=xdg-open /opt/termolab2d/app/Manual_TermoLab2D.pdf
"""


def write_tree():
    shutil.rmtree(STAGE, ignore_errors=True)
    copy_app(OPT / "app")
    build_python(OPT / "python")
    # .pyc pré-compilados: /opt não é gravável pelo usuário
    run([str(OPT / "python" / "bin" / "python3"), "-m", "compileall", "-q", "-j", "0",
         str(OPT / "python" / "lib" / "python3.12"), str(OPT / "app")], env={"PATH": "/usr/bin:/bin"})
    usr = PKGROOT / "usr"
    (usr / "bin").mkdir(parents=True)
    (usr / "bin" / PACKAGE).write_text(LAUNCHER, encoding="utf-8")
    (usr / "bin" / PACKAGE).chmod(0o755)
    apps = usr / "share" / "applications"
    apps.mkdir(parents=True)
    (apps / f"{PACKAGE}.desktop").write_text(DESKTOP, encoding="utf-8")
    from PIL import Image  # ícones em vários tamanhos a partir do ícone de 256 px
    icon = Image.open(ROOT / "gui" / "icone.png")
    for n in (16, 24, 32, 48, 64, 128, 256):
        d = usr / "share" / "icons" / "hicolor" / f"{n}x{n}" / "apps"
        d.mkdir(parents=True)
        icon.resize((n, n), Image.LANCZOS).save(d / f"{PACKAGE}.png")
    doc = usr / "share" / "doc" / PACKAGE
    doc.mkdir(parents=True)
    (doc / "copyright").write_text(
        "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n"
        "Upstream-Name: TermoLab2D\n\n"
        "Files: *\nCopyright: 2026 Luís e colaboradores do TermoLab2D\nLicense: MIT\n"
        " O texto completo está em /opt/termolab2d/app/LICENSE.\n\n"
        "Files: opt/termolab2d/python/*\nCopyright: Python Software Foundation e outros\n"
        "License: PSF-2.0 e licenças dos componentes (PySide6/Qt: LGPL-3.0; numpy: BSD-3-Clause;\n"
        " pyqtgraph: MIT). Os textos estão junto de cada componente em opt/termolab2d/python.\n",
        encoding="utf-8")
    with gzip.open(doc / "changelog.Debian.gz", "wt", encoding="utf-8") as out:
        out.write(f"{PACKAGE} ({VERSION}-{DEB_REVISION}) unstable; urgency=low\n\n"
                  "  * Versão inicial do pacote.\n\n"
                  f" -- {MAINTAINER}  {formatdate(localtime=True)}\n")
    os.symlink(f"/opt/{PACKAGE}/app/Manual_TermoLab2D.pdf", doc / "Manual_TermoLab2D.pdf")


# --------------------------------------------------------------------------- dependências
def system_dependencies() -> tuple[str, str]:
    """Bibliotecas do sistema usadas pelo conteúdo do pacote → nomes de pacotes Debian."""
    bundled = {f.name for f in OPT.rglob("*.so*")} | {"libpython3.12.so.1.0"}
    def elf_files(root):
        for f in root.rglob("*"):
            if f.is_file() and not f.is_symlink() and (f.suffix == ".so" or ".so." in f.name or os.access(f, os.X_OK)):
                with f.open("rb") as h:
                    if h.read(4) == b"\x7fELF":
                        yield f
    required, optional = set(), set()
    for f in elf_files(OPT):
        rel = str(f.relative_to(OPT))
        target = optional if any(rel.endswith(p) for p in OPTIONAL_PLUGINS) else required
        for n in needed(f):
            if n not in bundled:
                target.add(n)
    optional -= required
    # bibliotecas que podem não estar instaladas na máquina que gera o pacote
    known = {"libxcb-cursor.so.0": "libxcb-cursor0"}
    def packages(sonames):
        pk = set()
        for so in sorted(sonames):
            if so in known:
                pk.add(known[so])
                continue
            r = subprocess.run(["dpkg", "-S", f"*/{so}"], capture_output=True, text=True)
            names = {line.split(":")[0] for line in r.stdout.splitlines() if ":" in line}
            names = {n for n in names if not n.endswith(("-dev", "-dbg", "lib32", "-cross")) and "i386" not in n}
            if not names:
                print(f"aviso: nenhum pacote do sistema fornece {so}")
                continue
            pk.add(sorted(names, key=len)[0])
        return pk
    def fmt(pk):
        items = []
        for p in sorted(pk):
            if p.endswith("t64"):          # transição time_t 64 bits (Ubuntu 24.04 / Debian 13)
                items.append(f"{p} | {p[:-3]}")
            elif p == "libc6":
                items.append("libc6 (>= 2.28)")
            elif p == "libstdc++6":
                items.append("libstdc++6 (>= 5.2)")
            else:
                items.append(p)
        return ", ".join(items)
    req = packages(required)
    return fmt(req), fmt(packages(optional) - req)


def write_control(depends: str, recommends: str):
    deb = PKGROOT / "DEBIAN"
    deb.mkdir()
    size_kb = sum(f.stat().st_size for f in PKGROOT.rglob("*") if f.is_file() and not f.is_symlink()) // 1024
    (deb / "control").write_text(
        f"Package: {PACKAGE}\n"
        f"Version: {VERSION}-{DEB_REVISION}\n"
        "Section: education\n"
        "Priority: optional\n"
        "Architecture: amd64\n"
        f"Maintainer: {MAINTAINER}\n"
        f"Installed-Size: {size_kb}\n"
        f"Depends: {depends}, xdg-utils\n"
        + (f"Recommends: {recommends}\n" if recommends else "")
        + "Description: laboratório didático de termodinâmica e mecânica estatística\n"
        " O TermoLab2D simula, partícula por partícula, um gás em duas dimensões e mostra\n"
        " ao vivo temperatura, pressão, entropia, calor, trabalho e a distribuição de\n"
        " velocidades. Casos prontos: expansão livre, efusão, teorema H, mistura de gases,\n"
        " lei dos gases ideais, condução de calor, aquecimento pelas paredes e compressão\n"
        " por pistão. Inclui manual com atividades para aula.\n"
        " .\n"
        " O pacote é autocontido (Python, PySide6, numpy e pyqtgraph próprios em\n"
        " /opt/termolab2d).\n", encoding="utf-8")
    (deb / "postinst").write_text(
        "#!/bin/sh\nset -e\n"
        "if command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database -q /usr/share/applications || true; fi\n"
        "if command -v gtk-update-icon-cache >/dev/null 2>&1; then gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true; fi\n",
        encoding="utf-8")
    (deb / "postrm").write_text(
        "#!/bin/sh\nset -e\n"
        "if [ \"$1\" = remove ] || [ \"$1\" = purge ]; then\n"
        "  rm -rf /opt/termolab2d\n"     # remove .pyc gerados depois da instalação, se houver
        "  if command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database -q /usr/share/applications || true; fi\n"
        "  if command -v gtk-update-icon-cache >/dev/null 2>&1; then gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true; fi\n"
        "fi\n", encoding="utf-8")
    for f in ("postinst", "postrm"):
        (deb / f).chmod(0o755)


def main():
    for tool in ["g++", "readelf", "zstd", "dpkg-deb", "dpkg"]:
        if not shutil.which(tool):
            sys.exit(f"Ferramenta ausente: {tool}. Veja os requisitos no início deste arquivo.")
    write_tree()
    depends, recommends = system_dependencies()
    print("Depends:", depends)
    print("Recommends:", recommends)
    write_control(depends, recommends)
    for f in PKGROOT.rglob("*"):           # permissões padronizadas
        if f.is_symlink():
            continue
        if f.is_dir():
            f.chmod(0o755)
        else:
            f.chmod(0o755 if (f.stat().st_mode & stat.S_IXUSR) else 0o644)
    OUT.mkdir(exist_ok=True)
    deb = OUT / f"{PACKAGE}_{VERSION}-{DEB_REVISION}_amd64.deb"
    run(["dpkg-deb", "--root-owner-group", "-Zxz", "-z9", "--build", str(PKGROOT), str(deb)])
    print(f"\nPronto: {deb} ({deb.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()

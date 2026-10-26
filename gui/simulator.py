"""Localização/compilação do simulador C++ e leitura do fluxo JSON Lines.

O leitor roda numa thread. Quando a interface pausa, a thread para de ler o
stdout; o pipe enche e o próprio simulador C++ bloqueia na escrita. Isso dá
uma pausa real, que funciona igual no Linux e no Windows.
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = [ROOT / "src" / "main.cpp", ROOT / "src" / "md.hpp"]
EXE_NAME = "simulator.exe" if os.name == "nt" else "simulator"


def _base_dir() -> Path:
    # Em um pacote PyInstaller os arquivos ficam em sys._MEIPASS.
    return Path(getattr(sys, "_MEIPASS", ROOT))


def find_executable(log=print) -> Path:
    """Procura o simulador; compila com g++ se as fontes estiverem mais novas.

    Ordem: variável TERMOLAB2D_SIMULATOR (ou MD2D_SIMULATOR, nome antigo), build/, bin/<sistema>/.
    """
    env = os.environ.get("TERMOLAB2D_SIMULATOR") or os.environ.get("MD2D_SIMULATOR")
    if env:
        p = Path(env)
        if not p.is_file():
            raise RuntimeError(f"TERMOLAB2D_SIMULATOR aponta para arquivo inexistente: {p}")
        return p
    base = _base_dir()
    system = "windows" if os.name == "nt" else ("macos" if sys.platform == "darwin" else "linux")
    prebuilt = base / "bin" / system / EXE_NAME
    built = ROOT / "build" / EXE_NAME
    sources_ok = all(p.exists() for p in SOURCES)
    stale = (not built.exists()) or (sources_ok and any(p.stat().st_mtime > built.stat().st_mtime for p in SOURCES))
    if built.exists() and not stale:
        return built
    compiler = os.environ.get("CXX") or shutil.which("g++")
    if sources_ok and compiler:
        built.parent.mkdir(exist_ok=True)
        log("Compilando o simulador C++ com OpenMP…")
        cmd = [compiler, "-O3", "-std=c++17", "-fopenmp", str(SOURCES[0]), "-o", str(built)]
        if os.name == "nt":
            cmd += ["-static"]  # evita depender das DLLs do MinGW
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError("Falha ao compilar o simulador:\n" + result.stderr[-2000:])
        return built
    if prebuilt.exists():
        return prebuilt
    if built.exists():
        return built
    raise RuntimeError("Simulador não encontrado. Compile com 'make' (Linux) ou instale g++ (MinGW-w64 no Windows), "
                       f"ou coloque o executável em {prebuilt}.")


class SimulatorRun:
    """Executa o simulador e entrega itens (metadados/quadros) por uma fila limitada.

    A fila limitada transmite contrapressão ao C++: se a interface estiver lenta,
    o simulador espera em vez de acumular memória.
    """

    def __init__(self, executable: Path, config: Path, fps: float | None = None,
                 record: Path | None = None, vtk_dir: Path | None = None, queue_size: int = 64):
        self.items: queue.Queue = queue.Queue(maxsize=queue_size)
        self.messages: deque[str] = deque(maxlen=50)
        self.error: str | None = None
        self.finished = threading.Event()
        self._resume = threading.Event()
        self._resume.set()
        self._stopping = False
        self._record = record.open("w", encoding="utf-8", newline="\n") if record else None
        self._vtk = None
        if vtk_dir is not None:
            sys.path.insert(0, str(ROOT))
            from vtk_export import VTKWriter  # módulo existente do projeto
            self._vtk = VTKWriter(vtk_dir)
        cmd = [str(executable), str(Path(config).resolve())]
        if fps:
            cmd += ["--fps", f"{fps:g}"]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # Windows: sem janela de console
        self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, encoding="utf-8", errors="replace",
                                        bufsize=1, creationflags=flags)
        self._t_err = threading.Thread(target=self._read_stderr, daemon=True)
        self._t_out = threading.Thread(target=self._read_stdout, daemon=True)
        self._t_err.start()
        self._t_out.start()

    # --- controle -------------------------------------------------------
    @property
    def paused(self) -> bool:
        return not self._resume.is_set()

    def pause(self):
        self._resume.clear()

    def resume(self):
        self._resume.set()

    def stop(self):
        self._stopping = True
        self._resume.set()
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        # esvazia a fila para destravar a thread leitora
        while self._t_out.is_alive():
            self.drain()
            self._t_out.join(timeout=0.05)
        self._t_err.join(timeout=1)
        for stream in (self.process.stdout, self.process.stderr):
            try:
                stream.close()
            except OSError:
                pass

    def drain(self) -> list[dict]:
        out = []
        while True:
            try:
                out.append(self.items.get_nowait())
            except queue.Empty:
                return out

    # --- threads --------------------------------------------------------
    def _read_stderr(self):
        for line in self.process.stderr:
            self.messages.append(line.rstrip())

    def _put(self, item):
        while not self._stopping:
            try:
                self.items.put(item, timeout=0.1)
                return
            except queue.Full:
                continue

    def _read_stdout(self):
        meta_seen = False
        try:
            for line in self.process.stdout:
                self._resume.wait()
                if self._stopping:
                    break
                if self._record:
                    self._record.write(line)
                item = json.loads(line)
                kind = item.get("type")
                if kind == "metadata":
                    meta_seen = True
                    if self._vtk:
                        self._vtk.write_metadata(item)
                elif kind == "frame":
                    if not meta_seen:
                        raise RuntimeError("Quadro recebido antes dos metadados.")
                    if self._vtk:
                        self._vtk.write_frame(item)
                self._put(item)
            code = self.process.wait()
            self._t_err.join(timeout=2)
            if code and not self._stopping:
                raise RuntimeError(f"O simulador terminou com código {code}.\n" + "\n".join(self.messages))
            if not meta_seen and not self._stopping:
                raise RuntimeError("O simulador não enviou metadados.\n" + "\n".join(self.messages))
        except Exception as exc:  # noqa: BLE001 — erro mostrado na interface
            if not self._stopping:
                self.error = str(exc)
            if self.process.poll() is None:
                self.process.terminate()
        finally:
            if self._record:
                self._record.close()
            self.finished.set()

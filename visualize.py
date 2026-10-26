#!/usr/bin/env python3
"""Executa o simulador 2D C++ e exibe seus quadros enquanto são produzidos."""
from __future__ import annotations
import argparse
from collections import deque
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
from vtk_export import VTKWriter

ROOT = Path(__file__).resolve().parent


def executable(custom: Path | None = None) -> Path:
    if custom is not None:
        path = custom.resolve()
        if not path.is_file():
            raise RuntimeError(f"Executável não encontrado: {path}")
        return path
    path = ROOT / "build" / "simulator"
    sources = [ROOT / "src" / "main.cpp", ROOT / "src" / "md.hpp"]
    if not path.exists() or any(p.stat().st_mtime > path.stat().st_mtime for p in sources):
        path.parent.mkdir(exist_ok=True)
        print("Compilando o simulador C++ com OpenMP...", file=sys.stderr)
        subprocess.run([os.environ.get("CXX", "g++"), "-O3", "-std=c++17", "-Wall", "-Wextra",
                        "-fopenmp", str(sources[0]), "-o", str(path)], check=True)
    return path


class Stream:
    """Lê stdout/stderr continuamente; a fila limitada mantém a interface responsiva."""
    def __init__(self, binary: Path, config: Path, record: Path | None, fps: float | None = None, vtk_dir: Path | None = None):
        self.frames = queue.Queue(maxsize=2)
        self.messages = deque(maxlen=30)
        self.error = None
        self.metadata = None
        self.ready = threading.Event()
        self.done = threading.Event()
        self.stopping = False
        self.vtk = VTKWriter(vtk_dir) if vtk_dir is not None else None
        self.record = record.open("w", encoding="utf-8") if record else None
        try:
            command = [str(binary), str(config.resolve())]
            if fps is not None:
                command.extend(["--fps", str(fps)])
            self.process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
        except Exception:
            if self.record:
                self.record.close()
            raise
        self.stderr_thread = threading.Thread(target=self._stderr, daemon=True)
        self.reader_thread = threading.Thread(target=self._read, daemon=True)
        self.stderr_thread.start()
        self.reader_thread.start()

    def _stderr(self):
        for line in self.process.stderr:
            self.messages.append(line.rstrip())
            print(line, end="", file=sys.stderr)

    def _read(self):
        try:
            for line in self.process.stdout:
                if self.record:
                    self.record.write(line)
                item = json.loads(line)
                if item.get("type") == "metadata":
                    if self.metadata is not None:
                        raise RuntimeError("Metadados repetidos no fluxo.")
                    self.metadata = item
                    if self.vtk:
                        self.vtk.write_metadata(item)
                    self.ready.set()
                elif item.get("type") == "frame":
                    if self.metadata is None:
                        raise RuntimeError("Quadro recebido antes dos metadados.")
                    if self.vtk:
                        self.vtk.write_frame(item)
                    while True:
                        try:
                            self.frames.put_nowait(item)
                            break
                        except queue.Full:
                            try:
                                self.frames.get_nowait()
                            except queue.Empty:
                                pass
                else:
                    raise RuntimeError("Mensagem desconhecida do simulador.")
            code = self.process.wait()
            self.stderr_thread.join()
            if code and not self.stopping:
                raise RuntimeError(f"Simulador terminou com código {code}. " + " ".join(self.messages))
            if self.metadata is None and not self.stopping:
                raise RuntimeError("O simulador não enviou metadados.")
        except Exception as exc:
            if not self.stopping:
                self.error = str(exc)
            if self.process.poll() is None:
                self.process.terminate()
        finally:
            if self.record:
                try:
                    self.record.close()
                except OSError as exc:
                    self.error = str(exc)
            self.ready.set()
            self.done.set()

    def latest(self):
        frame = None
        while True:
            try:
                frame = self.frames.get_nowait()
            except queue.Empty:
                return frame

    def close(self):
        self.stopping = True
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.reader_thread.join()
        self.stderr_thread.join()
        self.process.stdout.close()
        self.process.stderr.close()


def figure(meta, hide_solids=False):
    import numpy as np
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    if meta.get("spatial_dimension") != 2:
        raise RuntimeError("Este visualizador requer uma simulação 2D.")
    fig, ax = plt.subplots(figsize=(11, 8), facecolor="#f5f7fb")
    low = np.asarray(meta["lower"])
    size = np.asarray(meta["dims"]) * np.asarray(meta["spacing"])
    nx, ny = meta["dims"]
    if not hide_solids:
        mask = np.zeros(nx * ny, dtype=np.uint8)
        mask[meta["solid_indices"]] = 1
        ax.imshow(mask.reshape(ny, nx), origin="lower", interpolation="nearest",
                  extent=(low[0], low[0]+size[0], low[1], low[1]+size[1]),
                  cmap=ListedColormap(["#ffffff", "#52677d"]), vmin=0, vmax=1,
                  zorder=0, resample=False)
    ax.set_xlim(low[0], low[0] + size[0])
    ax.set_ylim(low[1], low[1] + size[1])
    ax.set_aspect("equal", adjustable="box")
    ax.set(xlabel="x", ylabel="y")
    ax.tick_params(colors="#475569")
    vmax = max(1e-12, 3 * (meta["boltzmann"] * meta["target_temperature"] / meta["mass"]) ** 0.5)
    dots = ax.scatter([], [], c=[], s=25, cmap="plasma", vmin=0, vmax=vmax,
                      edgecolors="#ffffff", linewidths=0.35, zorder=2)
    fig.colorbar(dots, ax=ax, shrink=0.8, pad=0.035, label="Módulo da velocidade")
    title = fig.suptitle("TermoLab2D • iniciando", fontsize=15, weight="bold")
    fig.text(0.5, 0.025, "Cinza: sólido • cores: velocidade • use a barra de ferramentas para zoom e deslocamento",
             ha="center", color="#475569", fontsize=9)
    fig.subplots_adjust(left=0.08, right=0.94, bottom=0.10, top=0.86)
    return fig, dots, title


def update(frame, dots, title, finished=False):
    import numpy as np
    xyz = np.asarray(frame["positions"])
    speed = np.linalg.norm(np.asarray(frame["velocities"]), axis=1)
    dots.set_offsets(xyz)
    dots.set_array(speed)
    dots.set_clim(0, max(float(speed.max()), dots.get_clim()[1], 1e-12))
    energy = frame["kinetic"] + frame["potential"]
    state = "Concluída" if finished else "Em execução"
    title.set_text(f"2D • {state} • {len(xyz)} partículas • passo {frame['step']}\n"
                   f"t = {frame['time']:.3f}     T = {frame['temperature']:.3f}     E = {energy:.5g}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", nargs="?", type=Path, default=ROOT / "examples" / "simulation.cfg")
    parser.add_argument("--executable", type=Path, help="Executável alternativo; desativa compilação automática")
    parser.add_argument("--fps", type=float, default=30, help="Taxa máxima de atualização da janela")
    parser.add_argument("--unlimited", action="store_true", help="Executa sem limitar a emissão de quadros à taxa da tela")
    parser.add_argument("--record", type=Path, help="Grava todos os quadros JSONL emitidos pelo C++")
    parser.add_argument("--vtk-dir", type=Path, help="Grava todos os quadros em uma nova pasta VTK para o ParaView")
    parser.add_argument("--headless", action="store_true", help="Executa sem abrir janela")
    parser.add_argument("--snapshot", type=Path, help="Salva imagem do último quadro exibido")
    parser.add_argument("--hide-solids", action="store_true", help="Oculta os sólidos apenas no desenho")
    args = parser.parse_args(argv)
    if not 0 < args.fps <= 240:
        parser.error("--fps deve estar entre 0 (exclusivo) e 240")
    protected = {args.config.resolve(), executable(args.executable).resolve()}
    # Não permita que uma saída substitua os arquivos de entrada ou o código.
    protected.update(p.resolve() for p in ROOT.rglob("*") if p.is_file() and p.suffix in {".vtk", ".cfg", ".py", ".hpp", ".cpp"})
    for path in (args.record, args.snapshot):
        if path and path.resolve() in protected:
            parser.error("A saída não pode sobrescrever arquivos do projeto ou de entrada.")
    if args.record and args.snapshot and args.record.resolve() == args.snapshot.resolve():
        parser.error("--record e --snapshot devem ser arquivos diferentes")
    if args.vtk_dir:
        for path in (args.record, args.snapshot):
            if path and path.resolve().is_relative_to(args.vtk_dir.resolve()):
                parser.error("Use caminhos para --record e --snapshot fora da pasta exclusiva --vtk-dir")
    if args.headless:
        import matplotlib
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    if not args.headless and "agg" == plt.get_backend().lower():
        raise RuntimeError("Backend gráfico indisponível. Use um desktop com Tk/Qt ou --headless --snapshot resultado.png.")
    stream = Stream(executable(args.executable), args.config, args.record,
                    fps=None if args.headless or args.unlimited else args.fps, vtk_dir=args.vtk_dir)
    fig = None
    last = None
    try:
        while not stream.ready.wait(0.1):
            pass
        if stream.error:
            raise RuntimeError(stream.error)
        if args.headless:
            while not stream.done.wait(0.02):
                last = stream.latest() or last
            last = stream.latest() or last
            if stream.error:
                raise RuntimeError(stream.error)
            if last is None:
                raise RuntimeError("Nenhum quadro recebido.")
            if args.snapshot:
                fig, dots, title = figure(stream.metadata, args.hide_solids)
                update(last, dots, title, finished=True)
            print(f"Concluído: passo {last['step']}, t={last['time']:.6g}, T={last['temperature']:.6g}")
        else:
            from matplotlib.animation import FuncAnimation
            fig, dots, title = figure(stream.metadata, args.hide_solids)
            def tick(_):
                nonlocal last
                last = stream.latest() or last
                finished = stream.done.is_set() and stream.frames.empty()
                if last:
                    update(last, dots, title, finished=finished and not stream.error)
                if stream.error:
                    title.set_text("Simulação interrompida • consulte o erro no terminal")
                if finished:
                    animation.event_source.stop()
                return dots, title
            animation = FuncAnimation(fig, tick, interval=1000 / args.fps, blit=False, cache_frame_data=False)
            fig.canvas.mpl_connect("close_event", lambda _: stream.close())
            plt.show()
            if stream.error:
                raise RuntimeError(stream.error)
        if args.snapshot and fig is not None and last is not None:
            fig.savefig(args.snapshot, dpi=160, facecolor=fig.get_facecolor())
    finally:
        stream.close()
        if fig is not None:
            plt.close(fig)
    if stream.vtk and stream.vtk.entries:
        print(f"VTK: {len(stream.vtk.entries)} quadros em {stream.vtk.directory / 'particles.vtk.series'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError, ImportError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário.", file=sys.stderr)
        raise SystemExit(130)

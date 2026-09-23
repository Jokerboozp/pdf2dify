"""One-command, cross-platform launcher: python run.py."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import venv
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ENGINE = ROOT / "engine" / "ops-pdf-rag"
FRONTEND = ROOT / "frontend"
URL = "http://127.0.0.1:8010"


def python_in(folder: Path) -> Path:
    return folder / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def fingerprint(*paths: Path) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.read_bytes())
    return digest.hexdigest()


def command(*args: str, cwd: Path = ROOT) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def ensure_python_env(folder: Path, marker: Path, inputs: tuple[Path, ...], packages: list[list[str]]) -> Path:
    executable = python_in(folder)
    stamp = fingerprint(*inputs)
    if not executable.is_file():
        print(f"创建 Python 环境：{folder.relative_to(ROOT)}", flush=True)
        venv.EnvBuilder(with_pip=True).create(folder)
    if not marker.is_file() or marker.read_text(encoding="utf-8") != stamp:
        print(f"安装 Python 依赖：{folder.relative_to(ROOT)}", flush=True)
        for arguments in packages:
            command(str(executable), "-m", "pip", "install", *arguments)
        marker.write_text(stamp, encoding="utf-8")
    return executable


def ensure_frontend() -> None:
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        raise RuntimeError("未找到 npm；请先安装与仓库内 Vite 版本兼容的 Node.js/npm")
    dependency_stamp = fingerprint(FRONTEND / "package.json", FRONTEND / "package-lock.json")
    dependency_marker = FRONTEND / "node_modules" / ".pdf2dify-deps"
    if not dependency_marker.is_file() or dependency_marker.read_text(encoding="utf-8") != dependency_stamp:
        print("安装前端依赖", flush=True)
        command(npm, "ci", cwd=FRONTEND)
        dependency_marker.write_text(dependency_stamp, encoding="utf-8")
    stamp = fingerprint(FRONTEND / "package.json", FRONTEND / "package-lock.json",
                        *sorted((FRONTEND / "src").rglob("*.*")))
    marker = FRONTEND / "dist" / ".pdf2dify-build"
    if marker.is_file() and marker.read_text(encoding="utf-8") == stamp and (FRONTEND / "dist/index.html").is_file():
        return
    print("构建前端页面", flush=True)
    command(npm, "run", "build", cwd=FRONTEND)
    marker.write_text(stamp, encoding="utf-8")


def install() -> Path:
    if sys.version_info < (3, 11):
        raise RuntimeError("需要 Python 3.11 或更新版本")
    api = ensure_python_env(
        ROOT / ".venv", ROOT / ".venv" / ".pdf2dify-install",
        (ROOT / "pyproject.toml",), [["-e", str(ROOT)]],
    )
    ensure_python_env(
        ENGINE / ".venv", ENGINE / ".venv" / ".pdf2dify-install",
        (ENGINE / "pyproject.toml", ENGINE / "requirements.lock.txt"),
        [["-r", str(ENGINE / "requirements.lock.txt")], ["--no-deps", "-e", str(ENGINE)]],
    )
    ensure_frontend()
    return api


def health() -> bool:
    try:
        with urllib.request.urlopen(URL + "/api/health", timeout=1) as response:
            data = json.load(response)
            return data.get("status") == "ok" and bool(data.get("engine_ready"))
    except (OSError, ValueError):
        return False


def port_taken() -> bool:
    with socket.socket() as client:
        client.settimeout(1)
        return client.connect_ex(("127.0.0.1", 8010)) == 0


def stop_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)


def serve(api_python: Path, *, open_browser: bool = True) -> None:
    if port_taken():
        if health():
            print(f"pdf2dify 已在运行：{URL}")
            if open_browser:
                webbrowser.open(URL)
            return
        raise RuntimeError("8010 端口已被其他程序占用")
    log_dir = ROOT / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    options = {"creationflags": flags} if os.name == "nt" else {"start_new_session": True}
    processes: list[subprocess.Popen[bytes]] = []
    logs = []
    try:
        for module, label in (("pdf2dify.worker", "worker"), ("pdf2dify.main", "api")):
            output = (log_dir / f"{label}.log").open("ab")
            logs.append(output)
            processes.append(subprocess.Popen(
                [str(api_python), "-m", module], cwd=ROOT, stdout=output,
                stderr=subprocess.STDOUT, **options,
            ))
        for _ in range(40):
            if any(process.poll() is not None for process in processes):
                raise RuntimeError(f"服务启动失败，请查看 {log_dir}")
            if health():
                print(f"pdf2dify 已启动：{URL}（按 Ctrl+C 停止）", flush=True)
                if open_browser:
                    webbrowser.open(URL)
                while all(process.poll() is None for process in processes):
                    time.sleep(1)
                raise RuntimeError(f"服务意外退出，请查看 {log_dir}")
            time.sleep(.5)
        raise RuntimeError(f"服务启动超时，请查看 {log_dir}")
    except KeyboardInterrupt:
        print("正在停止 pdf2dify…", flush=True)
    finally:
        for process in reversed(processes):
            stop_tree(process)
        for output in logs:
            output.close()


def main() -> int:
    try:
        api_python = install()
        if "--install-only" not in sys.argv:
            serve(api_python, open_browser="--no-browser" not in sys.argv)
        else:
            print("安装完成，运行 python run.py 启动")
        return 0
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

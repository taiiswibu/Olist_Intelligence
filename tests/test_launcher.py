"""Regressions for Windows Code Runner encoding and interpreter selection."""
import errno
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

import pytest

import run as launcher


def test_missing_dependency_message_survives_cp1258_pipe(tmp_path):
    script = tmp_path / "run.py"
    shutil.copyfile(Path(launcher.__file__), script)
    env = {**os.environ, "PYTHONIOENCODING": "cp1258:strict", "PYTHONPATH": "", "PYTHONUTF8": "0"}
    # -S prevents site-packages: uvicorn is absent regardless of installed test deps.
    result = subprocess.run([sys.executable, "-S", str(script)], env=env,
                            capture_output=True, timeout=10)
    assert result.returncode == 1
    assert "Thiếu thư viện: uvicorn" in result.stdout.decode("utf-8")
    assert b"UnicodeEncodeError" not in result.stderr
    assert b"SETUP_WINDOWS.bat" in result.stdout


def test_wrong_interpreter_relaunches_project_venv(tmp_path, monkeypatch):
    python = tmp_path / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "global-python"))
    class Relaunched(Exception):
        pass
    seen = []
    def execute(path, args):
        seen.append((path, args))
        raise Relaunched()
    monkeypatch.setattr(os, "execv", execute)
    with pytest.raises(Relaunched):
        launcher.use_project_python(tmp_path)
    assert seen[0][0] == str(python)
    assert seen[0][1][:5] == [str(python), "-u", "-X", "utf8", str(tmp_path / "run.py")]


def test_project_interpreter_does_not_relaunch(tmp_path, monkeypatch):
    python = tmp_path / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(sys, "prefix", str(tmp_path / ".venv"))
    monkeypatch.setattr(os, "execv", lambda *args: pytest.fail("recursive launch"))
    launcher.use_project_python(tmp_path)


@pytest.mark.parametrize("error, expected", [(errno.EADDRINUSE, "tiến trình sử dụng"), (errno.EACCES, "Kiểm tra quyền")])
def test_port_error_distinguishes_busy_from_permission(monkeypatch, error, expected):
    class BlockedSocket:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def bind(self, address):
            assert address == ("127.0.0.1", 8000)
            raise OSError(error, "simulated")
    monkeypatch.setattr(socket, "socket", BlockedSocket)
    with pytest.raises(SystemExit, match=expected):
        launcher.check_port()

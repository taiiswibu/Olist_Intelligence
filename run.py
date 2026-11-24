"""Start the HTML application on one local port with a one-use browser ticket."""
import os
import errno
import secrets
import sys
import threading
import time
import webbrowser
from pathlib import Path


def configure_console():
    """Code Runner may pipe output through a legacy Windows encoding."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (OSError, ValueError):
                pass


def use_project_python(root):
    """Prefer installed project dependencies even when Code Runner uses global Python."""
    venv = root / ".venv"
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if python.is_file() and Path(sys.prefix).resolve() != venv.resolve():
        print("Using project Python: " + str(python), flush=True)
        try:
            os.execv(str(python), [str(python), "-u", "-X", "utf8", str(root / "run.py"), *sys.argv[1:]])
        except OSError as exc:
            raise SystemExit("Cannot start project Python (" + type(exc).__name__ + "). Run SETUP_WINDOWS.bat or check .venv.") from None


def check_port():
    import socket
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", 8000))
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE or getattr(exc, "winerror", None) == 10048:
                raise SystemExit(
                    "Cổng 8000 đang có tiến trình sử dụng.\n"
                    "Mở http://127.0.0.1:8000/ để kiểm tra bản đang chạy.\n"
                    "Nếu là Olist cũ, dừng bằng Ctrl+C tại terminal đã mở nó rồi chạy lại.\n"
                    "Xem phần cài và chạy trong README.md."
                ) from None
            raise SystemExit("Không mở được cổng 8000 (mã lỗi " + str(exc.errno) + "). Kiểm tra quyền hoặc cấu hình Windows.") from None


def main():
    configure_console()
    root = Path(__file__).resolve().parent
    os.chdir(root)
    use_project_python(root)
    try:
        import uvicorn
        from olist.config import init_env, settings
        from olist.database import ready
    except ImportError as exc:
        print(f"Thiếu thư viện: {exc.name}. Bước cài đặt chưa hoàn tất.")
        print("Python đang chạy: " + sys.executable)
        print(r"Chạy SETUP_WINDOWS.bat hoặc .\.venv\Scripts\python.exe -m pip install --timeout 180 --retries 10 -r requirements.txt")
        raise SystemExit(1)
    init_env()
    if not settings().app_token or settings().app_token == "CHANGE_ME_LOCAL_TOKEN":
        raise SystemExit("APP_TOKEN chưa hợp lệ. Chạy lại python manage.py setup")
    check_port()
    ticket = secrets.token_urlsafe(32)
    os.environ["OLIST_BROWSER_TICKET"] = ticket
    url = "http://127.0.0.1:8000/"
    def open_browser():
        import urllib.request
        for _ in range(60):
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(url + "health", timeout=1) as r:
                    if r.status == 200:
                        webbrowser.open(url + "#ticket=" + ticket)
                        return
            except Exception:
                time.sleep(.25)
    if os.getenv("OLIST_NO_BROWSER") != "1":
        threading.Thread(target=open_browser, daemon=True).start()
    print("Olist Intelligence · HTML/CSS web app", flush=True)
    print(url + "  |  Ctrl+C để dừng", flush=True)
    print("Nếu mở thủ công: dùng APP_TOKEN trong .env ở màn hình kết nối.", flush=True)
    if not ready():
        print("Chưa có dữ liệu: chạy python manage.py setup để tải Olist.", flush=True)
    uvicorn.run("olist.api:app", host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()

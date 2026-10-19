"""Start the local server, then open the browser after readiness."""

import argparse
import socket
import sys
import threading
import urllib.error
import urllib.request
import webbrowser

import uvicorn

from .server import create_app


def open_when_ready(url: str, stopped: threading.Event):
    for _ in range(150):
        if stopped.wait(0.2):
            return
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=0.5) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    return
        except (OSError, urllib.error.URLError):
            continue


def main():
    # Keep Korean CLI text intact when Windows redirects stdout/stderr to pipes.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        prog="python -m xmbwavestudio", description="XMB Wave Studio 로컬 배경화면 제작 도구"
    )
    parser.add_argument("--port", type=int, default=8765, help="로컬 서버 포트 (기본: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="브라우저 자동 실행 생략")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("포트는 1~65535 사이여야 합니다.")
    # Reserve the socket before opening a tab so a port race cannot open another service.
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        server_socket.bind(("127.0.0.1", args.port))
        server_socket.listen(128)
    except OSError:
        server_socket.close()
        parser.exit(1, f"포트 {args.port}를 사용할 수 없습니다. --port {args.port + 1}로 실행해 주세요.\n")
    url = f"http://127.0.0.1:{args.port}"
    print(f"\n  XMB Wave Studio · {url}\n  종료: Ctrl+C\n", flush=True)
    stopped = threading.Event()
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url, stopped), daemon=True).start()
    try:
        config = uvicorn.Config(
            create_app(), host="127.0.0.1", port=args.port, log_level="info",
            ws_max_size=2 * 1024 * 1024, ws_max_queue=2, ws_ping_interval=20,
            ws_ping_timeout=120, timeout_graceful_shutdown=3,
        )
        uvicorn.Server(config).run(sockets=[server_socket])
    except KeyboardInterrupt:
        pass  # Normal Ctrl+C exit; lifespan has already reclaimed active encoders.
    finally:
        stopped.set()
        server_socket.close()


if __name__ == "__main__":
    main()

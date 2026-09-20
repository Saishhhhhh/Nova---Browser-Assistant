"""
Zero-dependency local HTTP server for serving standardized browser benchmark test fixtures.
Listens on http://127.0.0.1:8765 by default.
"""

import http.server
import os
import socketserver
import sys
import threading
from pathlib import Path

DEFAULT_PORT = 8765
STATIC_DIR = Path(__file__).resolve().parent / "static"


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, format, *args):
        # Suppress noise during high-throughput benchmarking
        if os.environ.get("BENCHMARK_DEBUG"):
            super().log_message(format, *args)


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def start_server(port: int = DEFAULT_PORT):
    server = ThreadedHTTPServer(("127.0.0.1", port), QuietHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    return server, server_thread


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    server = ThreadedHTTPServer(("127.0.0.1", port), QuietHandler)
    print(f"[Benchmark Server] Serving fixtures from {STATIC_DIR} at http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Benchmark Server] Stopping server...")
        server.shutdown()
        server.server_close()

"""A tiny REAL local HTTP server that imitates POST /v1/audio/transcriptions.

It is a TEST DOUBLE of the OpenAI service (not OpenAI itself), but requests are sent over a real
socket, so the provider's real HTTP, multipart, timeout and error-handling code runs.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OK_BODY = {
    "text": " Hello world ",
    "language": "english",
    "duration": 2.5,
    "segments": [{"start": 0.0, "end": 2.5, "text": " Hello world "}],
}


class FakeOpenAI:
    def __init__(self) -> None:
        self.plan: list[dict] = []
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silence
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                outer.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
                step = outer.plan.pop(0) if outer.plan else {}
                if step.get("delay"):
                    time.sleep(step["delay"])
                payload = step["raw"] if "raw" in step else json.dumps(step.get("body", OK_BODY)).encode()
                try:
                    self.send_response(step.get("status", 200))
                    for name, value in (step.get("headers") or {}).items():
                        self.send_header(name, value)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):  # client gave up (timeout test)
                    pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}/v1"

    def queue(self, **step) -> None:
        self.plan.append(step)

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

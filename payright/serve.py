"""Stand-in for the two Lambdas, served from a laptop: same handlers, same behaviour.

Why: the organisers' Lambda call link answers 403 "forbidden" from outside, so judges'
phones (and Sarvam's webhook) cannot reach our functions through it. This serves the
identical code locally; a tunnel gives it a public https address.

  python serve.py [port]                               (default 8765)
  cloudflared tunnel --url http://localhost:8765       prints https://<name>.trycloudflare.com

  GET  /                    the judges' status page
  POST /status              run.py updates the page      -> .env  STATUS_URL=<public>/status
  POST /callback            Sarvam's post-call webhook   -> .env  SARVAM_CALLBACK_URL=<public>/callback
  GET  /callback?attempt_id=...   read a call result     -> .env  SARVAM_RESULT_URL=<public>/callback

Set PAYRIGHT_TOKEN before starting (and the same value as STATUS_TOKEN in .env) so only
our laptops can update the page.
"""
import importlib.util
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

HERE = Path(__file__).parent


def _load(name):
    spec = importlib.util.spec_from_file_location("payright_" + name, HERE / "lambda" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


status, callback = _load("status"), _load("callback")


class Handler(BaseHTTPRequestHandler):
    def _serve(self, method):
        url = urlsplit(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        event = {"httpMethod": method, "queryStringParameters": dict(parse_qsl(url.query)),
                 "headers": dict(self.headers.items()),
                 "body": self.rfile.read(length).decode("utf-8", "replace") if length else None}
        route = url.path.rstrip("/")
        if route == "/callback":
            out = callback.handler(event)
        elif route in ("", "/status"):
            out = status.handler(event)
        else:
            out = {"statusCode": 404, "headers": {"Content-Type": "text/plain"}, "body": "not found"}
        body = out["body"].encode("utf-8")
        self.send_response(out["statusCode"])
        for k, v in out["headers"].items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._serve("GET")

    def do_POST(self):
        self._serve("POST")

    def log_message(self, fmt, *args):  # one short line per request, no query strings (they carry attempt ids)
        sys.stderr.write(f"{self.command} {urlsplit(self.path).path} {args[1] if len(args) > 1 else ''}\n")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"serving the status page and the call-result receiver on http://localhost:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()

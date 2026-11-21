"""One local page that drives the demo, so no terminal is on screen.

  python payright/demo.py          then open http://127.0.0.1:8765
  python payright/demo.py --selftest

Each button runs the same command as docs/RUNBOOK.md and shows its output live, next to the board.
The page listens on this laptop only and every button needs a token that only the page has, so no
other machine and no other web page can press them. Pressing "Start" still pays nothing by itself:
run.py pays only after the owner's phone call approves the batch.

The call is placed from Sarvam's Test panel, not from here: a freshly opened Sarvam page starts with
an empty Setup, and an empty Setup is what lost the 2:50 PM attempt.
"""
import json
import os
import secrets
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
PORT = 8765
TOKEN = secrets.token_hex(16)
SAVED = ["payright/run.py", "payright/invoices.json", "--cash", "100000", "--latest"]
STEPS = {  # the same commands as docs/RUNBOOK.md
    "selftest": [["payright/check.py", "--selftest"], ["payright/send.py", "--selftest"],
                 ["payright/approve.py", "--selftest"]],
    "round": [["payright/new_round.py"]],
    "live": [["payright/run.py", "payright/invoices", "ta-IN", "--cash", "100000", "--latest"]],
    "saved": [SAVED],
    "refresh": [["payright/run.py", "--refresh"]],
    "again": [SAVED],
}
log, lock, busy, proc = [], threading.Lock(), threading.Event(), [None]


def say(line):
    with lock:
        log.append(line)


def work(cmds):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}  # the output has rupee signs and Hindi
    try:
        for c in cmds:
            say("$ python " + " ".join(c))
            p = proc[0] = subprocess.Popen([sys.executable, "-u", *c], cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
            for line in p.stdout:
                say(line.rstrip("\n"))
            if p.wait():
                say(f"(stopped with exit code {p.returncode})")
    except Exception as e:  # the page must say so, not hang
        say(f"(could not run: {type(e).__name__}: {e})")
    finally:
        busy.clear()


def board_url():
    env = HERE / ".env"
    for line in env.read_text(encoding="utf-8").splitlines() if env.exists() else []:
        k, _, v = line.partition("=")
        if k.strip() == "STATUS_URL":
            return "/".join(v.strip().split("/")[:3]) + "/"
    return ""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, body, ctype="application/json", code=200):
        b = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def local(self):  # refuse a page on another site that points its name at this laptop
        return (self.headers.get("Host") or "").split(":")[0] in ("127.0.0.1", "localhost")

    def do_GET(self):
        if not self.local():
            return self.reply("{}", code=403)
        if self.path.startswith("/log"):
            n = int(self.path.partition("from=")[2] or 0)
            with lock:
                return self.reply(json.dumps({"lines": log[n:], "busy": busy.is_set()}))
        self.reply(PAGE.replace("{{TOKEN}}", TOKEN).replace("{{BOARD}}", board_url()), "text/html")

    def do_POST(self):
        if not self.local() or not secrets.compare_digest(self.headers.get("X-Demo") or "", TOKEN):
            return self.reply("{}", code=403)
        step = self.path.partition("step=")[2]
        if step == "stop":
            if proc[0] and proc[0].poll() is None:
                proc[0].terminate()  # same as Ctrl+C in the runbook; the ledger is written before any payment call
            return self.reply("{}")
        if step not in STEPS:
            return self.reply("{}", code=404)
        with lock:
            if busy.is_set():
                return self.reply("{}", code=409)
            busy.set()
        threading.Thread(target=work, args=(STEPS[step],), daemon=True).start()
        self.reply("{}")


PAGE = """<!doctype html><meta charset=utf-8><title>PayRight demo</title>
<style>
body{margin:0;font:15px system-ui,sans-serif;background:#eef0e8;color:#111;display:grid;grid-template-rows:auto 1fr;height:100vh}
header{padding:10px 14px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;border-bottom:1px solid #c9ccc0}
b.t{font-size:18px;margin-right:6px}
button{font:inherit;padding:8px 13px;border-radius:999px;border:1px solid #111;background:#111;color:#fff;cursor:pointer}
button.g{background:transparent;color:#111}button:disabled{opacity:.35;cursor:default}
.n{padding:7px 12px;border:1px dashed #666;border-radius:999px}
main{display:grid;grid-template-columns:minmax(340px,42%) 1fr;min-height:0}
pre{margin:0;padding:12px;overflow:auto;background:#111;color:#d6d6d6;font:13px/1.5 ui-monospace,Consolas,monospace;white-space:pre-wrap}
iframe{border:0;width:100%;height:100%;background:#fff}
.ok{color:#7ee787}.no{color:#ff7b72}.wait{color:#e3b341}.hd{color:#79c0ff}
@media(max-width:900px){main{grid-template-columns:1fr;grid-template-rows:46vh 1fr}}
</style>
<header>
<b class=t>PayRight</b>
<button class=g data-step=selftest>0 Safety self-tests</button>
<button class=g data-step=round>1 New round</button>
<button data-step=live>2 Read the bills and check</button>
<button class=g data-step=saved>2 (saved reads)</button>
<span class=n>3 Call the owner: Sarvam tab, 7/7 set, Call 1 number</span>
<span class=n>4 Pays by itself after APPROVED</span>
<button data-step=refresh>5 Ask Cashfree</button>
<button class=g data-step=again>6 Run again: no double pay</button>
<button class=g data-step=stop>Stop</button>
</header>
<main><pre id=out></pre><iframe id=board src="{{BOARD}}"></iframe></main>
<script>
const T="{{TOKEN}}",out=document.getElementById("out");let n=0;
document.querySelectorAll("button").forEach(b=>b.onclick=()=>fetch("/do?step="+b.dataset.step,{method:"POST",headers:{"X-Demo":T}}));
let w=null;  // Sarvam lists a call only after it ends, so the waiting lines become one line that counts up
function add(l){const m=l.match(/^\\s*(no call started yet|call in progress)\\.\\.\\. (\\d+s)/);
if(m){if(!w){w=document.createElement("span");w.className="wait";out.append(w)}
w.textContent="waiting for the owner's answer on the phone... "+m[2]+"\\n";out.scrollTop=out.scrollHeight;return}
w=null;const s=document.createElement("span");s.textContent=l+"\\n";
s.className=/^(PAY\\b|PAID|ACCEPTED|APPROVED)|selftest ok/.test(l)?"ok":/^(STOP|NOT APPROVED|NOT_SENT|FAILED|REVERSED|UNKNOWN)/.test(l)?"no":
/^(ASK|LATER|waiting|Waiting|no call|call )/.test(l)?"wait":/^(\\$|ROUND|SCORE)/.test(l)?"hd":"";out.append(s);out.scrollTop=out.scrollHeight}
async function poll(){try{const r=await(await fetch("/log?from="+n)).json();r.lines.forEach(add);n+=r.lines.length;
document.querySelectorAll("button").forEach(b=>b.disabled=r.busy&&b.dataset.step!="stop")}catch(e){}setTimeout(poll,400)}
poll()
</script>"""


def selftest():
    import time
    import urllib.error
    import urllib.request
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"

    def post(step, token):
        try:
            return urllib.request.urlopen(urllib.request.Request(base + "/do?step=" + step, data=b"",
                                                                 headers={"X-Demo": token})).status
        except urllib.error.HTTPError as e:
            return e.code
    assert TOKEN in urllib.request.urlopen(base + "/").read().decode()
    assert post("selftest", "") == 403 and post("saved", "wrong") == 403, "a button worked without the token"
    assert not log, "a refused press still ran something"
    assert post("nonsense", TOKEN) == 404 and post("selftest", TOKEN) == 200
    for _ in range(300):
        if not busy.is_set():
            break
        time.sleep(0.2)
    seen = "\n".join(log)
    assert seen.count("selftest ok") == 3 and not busy.is_set(), seen
    print("selftest ok: buttons need the page's token; the three safety self-tests ran and showed their output")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        print(f"PayRight demo page: http://127.0.0.1:{PORT}   (this laptop only; Ctrl+C to stop)")
        ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()

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
  GET  /try                 "Try to fool it": a judge tampers with a real clean bill
  POST /try                 {"preset", "vendor_name", "invoice_no", "total"} -> the real checker's verdict.
                            Runs check.py in memory only: no ledger, no approval, no Relay, no Cashfree.
  POST /attack              {"seed": 7} -> attack.py forges 1,000 variants of real clean bills; the real checker
                            decides each one. Memory only, same as /try.
  GET  /news/<name>.jpg     the problem page's screenshots, from docs/news/

Set PAYRIGHT_TOKEN before starting (and the same value as STATUS_TOKEN in .env) so only
our laptops can update the page.
"""
import copy
import html
import importlib.util
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

HERE = Path(__file__).parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import attack  # noqa: E402  (forges variants of real bills; the checker below decides each one)
import check  # noqa: E402  (the real checker; /try runs it and nothing else)


def _load(name):
    spec = importlib.util.spec_from_file_location("payright_" + name, HERE / "lambda" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


status, callback = _load("status"), _load("callback")
status.HAS_TRY = True  # show the "Try to fool it" link: this server has the checker beside it
status.NEWS_BASE = "./news/"  # the problem page's screenshots: served from docs/news/ by this server
NEWS = HERE.parent / "docs" / "news"

# ------------------------------------------------------------ /try: try to fool it

PRESETS = (("clean", "Leave it alone"), ("digit", "Change one digit of the account"),
           ("other_account", "Swap in another vendor's account"), ("total", "Add ₹2,700 to the total"),
           ("duplicate", "Send the same bill twice, disguised"), ("stranger", "Put a stranger's name on it"))
_BASE = {}


def _mask(text):
    """Account numbers: last four digits only (same rule as the board)."""
    return re.sub(r"\d{9,}", lambda m: "····" + m.group()[-4:], str(text))


def _inr(x):
    if x is None:
        return "?"
    s = f"{abs(x):.0f}"
    head, tail, parts = s[:-3], s[-3:], []
    while len(head) > 2:  # Indian grouping: 1,20,500
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ("-" if x < 0 else "") + "₹" + ",".join(parts + [tail])


def _base():
    """-> (a real bill the checker clears, the vendor list), or (None, vendors) if there is none."""
    if not _BASE:
        vendors = json.loads((HERE / "vendors.json").read_text(encoding="utf-8"))
        bill = None
        for src in (HERE / "invoices" / "extracted.json", HERE / "sample_invoices.json"):
            if bill is None and src.exists():
                for inv in json.loads(src.read_text(encoding="utf-8")):
                    if check.plan([inv], vendors, [], 1e12)[0]["status"] == "PAY":
                        bill = inv
                        break
        _BASE.update(bill=bill, vendors=vendors)
    return _BASE["bill"], _BASE["vendors"]


def fool(req):
    """Tamper with a copy of the base bill as asked and let the real checker decide. Memory only."""
    base, vendors = _base()
    if base is None:
        return 503, {"error": "No clean bill is available to tamper with."}
    preset = str(req.get("preset") or "clean")
    if preset not in dict(PRESETS):
        return 400, {"error": "unknown preset"}
    inv, changed, first = copy.deepcopy(base), [], None
    owner = check.plan([base], vendors, [], 1e12)[0]["vendor_id"]
    if preset == "digit":
        a = str(inv.get("bank_account") or "")
        inv["bank_account"] = a[:-1] + str((int(a[-1]) + 1) % 10) if a[-1:].isdigit() else a + "1"
        changed.append(f"The last digit of the bank account was changed, to {inv['bank_account']}.")
    elif preset == "other_account":
        other = next((v for v in vendors if v["id"] != owner), None)
        if other:
            inv["bank_account"], inv["ifsc"] = other["bank_account"], other["ifsc"]
            changed.append(f"The bank details were replaced with another vendor's account, {other['bank_account']} {other['ifsc']}.")
    elif preset == "total":
        t = check.amount(inv.get("total")) or 0.0
        inv["total"] = t + 2700
        changed.append(f"The total was raised from {t:.0f} to {t + 2700:.0f}; subtotal and tax were left as they were.")
    elif preset == "duplicate":
        first = base
        old = str(inv.get("invoice_no") or "")
        inv["invoice_no"] = re.sub(r"\d+", lambda m: str(int(m.group())), old.lower().replace("-", "/"))
        d = check.parse_date(inv.get("invoice_date"))
        if d:
            inv["invoice_date"] = d.strftime("%d %b %Y")
        changed.append(f"The same bill was sent a second time with its number rewritten from {old} to "
                       f"{inv['invoice_no']} and its date in another format.")
    elif preset == "stranger":
        inv["vendor_name"] = inv["vendor_name_latin"] = "Jane D Traders"
        inv.pop("gstin", None)
        changed.append("The sender was changed to Jane D Traders, keeping the original vendor's bank account.")
    name = str(req.get("vendor_name") or "").strip()[:80]
    if name and name != str(inv.get("vendor_name") or ""):
        inv["vendor_name"] = inv["vendor_name_latin"] = name
        inv.pop("gstin", None)  # a different sender would not carry this vendor's GSTIN
        changed.append(f"The sender's name was typed in as {name}.")
    number = str(req.get("invoice_no") or "").strip()[:40]
    if number and number != str(inv.get("invoice_no") or ""):
        inv["invoice_no"] = number
        changed.append(f"The invoice number was typed in as {number}.")
    total = str(req.get("total") or "").strip()[:30]
    if total:
        value = check.amount(total)
        inv["total"] = value if value is not None else total
        changed.append(f"The total was typed in as {total}.")
    dec = check.plan(([first] if first else []) + [inv], vendors, [], 1e12)[-1]   # memory only: no ledger, nothing sent
    return 200, {"status": dec["status"], "vendor": dec["vendor"], "invoice_no": dec["invoice_no"], "amount": dec["amount"],
                 "reasons": [_mask(r) for r in dec["reasons"]],
                 "evidence": [{"check": e["check"], "a_label": e["a_label"], "a": _mask(e["a"]),
                               "b_label": e["b_label"], "b": _mask(e["b"])} for e in dec.get("evidence") or []],
                 "changed": _mask(" ".join(changed) or "Nothing was changed. This is the bill exactly as the vendor sent it.")}


TRY_CSS = """<style>
.try-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:32px;align-items:start;margin-top:40px}
.try-bill dl{display:grid;grid-template-columns:auto minmax(0,1fr);gap:6px 18px;margin:8px 0 0;font-size:15px}
.try-bill dt{color:var(--mute)}.try-bill dd{margin:0;font-weight:600;text-align:right;overflow-wrap:anywhere}
.try-presets{display:flex;flex-wrap:wrap;gap:10px;margin:22px 0 0}
.try-presets button,.try-go{font-family:inherit;cursor:pointer;white-space:normal;text-align:left}
.try-presets button[aria-pressed=true]{background:var(--ink);color:#fff}
.try-fields{display:grid;gap:12px;margin:22px 0 0}
.try-fields label{display:grid;gap:5px;font:600 13px/1.2 Inter,system-ui,sans-serif}
.try-fields input{font:400 15px/1.3 Inter,system-ui,sans-serif;padding:11px 14px;border-radius:12px;border:1px solid var(--line);
background:var(--paper);color:var(--ink);width:100%;min-width:0}
.try-fields input:focus{outline:2px solid var(--ink);outline-offset:1px}
.try-note{margin:16px 0 0}
.try-verdict{min-height:300px;position:sticky;top:84px}
.try-word{font:800 clamp(84px,13vw,168px)/.86 'Inter Tight',Inter,'Segoe UI',sans-serif;letter-spacing:-.055em;margin:6px 0 10px}
.try-word.PAY{color:var(--ok)}.try-word.STOP{color:var(--bad)}.try-word.ASK,.try-word.LATER{color:var(--warn)}
.try-what{font-weight:600;margin:0}.try-verdict .why{margin-top:10px}
.try-in{animation:try-in .5s cubic-bezier(.2,.8,.2,1) both}
@keyframes try-in{from{opacity:0;transform:translateY(16px) scale(.97)}to{opacity:1;transform:none}}
@media (max-width:820px){.try-grid{grid-template-columns:minmax(0,1fr)}.try-verdict{position:static;min-height:0}}
@media (prefers-reduced-motion:reduce){.try-in{animation:none}}
</style>"""

TRY_JS = """<script>(function(){
var out=document.getElementById('try-out'),preset='clean',buttons=document.querySelectorAll('.try-presets button');
function el(t,c,x){var e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e}
function inr(x){return x==null?'?':'\\u20b9'+Number(x).toLocaleString('en-IN',{maximumFractionDigits:0})}
var WORD={PAY:'PAY',STOP:'STOP',ASK:'ASK',LATER:'LATER'};
function show(d){
  out.textContent='';out.classList.remove('try-in');void out.offsetWidth;out.classList.add('try-in');
  if(d.error){out.appendChild(el('p','sub',d.error));return}
  out.appendChild(el('span','k','The checker says'));
  out.appendChild(el('p','try-word '+(WORD[d.status]||'ASK'),WORD[d.status]||d.status));
  out.appendChild(el('p','try-what',[d.vendor||'Unknown vendor',d.invoice_no?'invoice '+d.invoice_no:'',inr(d.amount)].filter(Boolean).join(' \\u00b7 ')));
  out.appendChild(el('p','sub',d.changed));
  var why=el('ul','why');
  (d.reasons&&d.reasons.length?d.reasons:[d.status==='PAY'?'Nothing is wrong with this bill, so it goes to the owner. It is still not paid until he says the total himself on the phone.':'']).forEach(function(r){if(r)why.appendChild(el('li',null,r))});
  out.appendChild(why);
  (d.evidence||[]).forEach(function(v){
    var ev=el('div','ev'),pair=el('div','pair'),a=el('div','bad'),b=el('div','ref');
    ev.appendChild(el('p','evk',v.check));
    a.appendChild(el('span',null,v.a_label));a.appendChild(el('b',null,v.a));
    b.appendChild(el('span',null,v.b_label));b.appendChild(el('b',null,v.b));
    pair.appendChild(a);pair.appendChild(b);ev.appendChild(pair);out.appendChild(ev)});
}
function val(id){return document.getElementById(id).value}
function run(){
  fetch(location.pathname,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({preset:preset,vendor_name:val('try-name'),invoice_no:val('try-no'),total:val('try-total')})})
  .then(function(r){return r.json()}).then(show)
  .catch(function(){show({error:'Could not reach the checker. Try again.'})});
}
[].forEach.call(buttons,function(b){b.addEventListener('click',function(){
  preset=b.getAttribute('data-preset');
  [].forEach.call(buttons,function(o){o.setAttribute('aria-pressed',o===b?'true':'false')});run()})});
document.getElementById('try-form').addEventListener('submit',function(e){e.preventDefault();run()});
var want=location.hash.slice(1);   // the problem page links here as /try#digit: replay that trick straight away
[].forEach.call(buttons,function(b){if(want&&b.getAttribute('data-preset')===want)b.click()});
})();</script>"""


def try_page():
    e = html.escape
    base, _ = _base()
    if base is None:
        body = ('<section id="try"><div class="wrap"><p class="eyebrow">Try to fool it</p><h2>Go on, cheat.</h2>'
                '<p class="serif">No clean bill is loaded yet, so there is nothing to tamper with.</p></div></section>')
    else:
        acct = str(base.get("bank_account") or "")
        facts = (("Invoice", base.get("invoice_no")), ("Date", base.get("invoice_date")),
                 ("Subtotal", _inr(check.amount(base.get("subtotal")))), ("Tax", _inr(check.amount(base.get("tax")))),
                 ("Total", _inr(check.amount(base.get("total")))),
                 ("Pay into", ("····" + acct[-4:] + " " + str(base.get("ifsc") or "")).strip() if acct else "not written"))
        dl = "".join(f"<dt>{e(k)}</dt><dd>{e(str(v if v is not None else '?'))}</dd>" for k, v in facts)
        buttons = "".join(f'<button type="button" class="pill ghost" data-preset="{k}" aria-pressed="false">{e(label)}</button>'
                          for k, label in PRESETS)
        body = f"""{TRY_CSS}<section id="try"><div class="wrap">
<p class="eyebrow">Try to fool it</p><h2>Go on, cheat.</h2>
<p class="serif">Tamper with a real bill. The same code that guards the money answers.</p>
<div class="try-grid"><div>
<div class="card try-bill"><span class="k">A real bill our reader read, and the checker cleared</span>
<span class="big" style="font-size:34px">{e(str(base.get("vendor_name_latin") or base.get("vendor_name") or "Vendor"))}</span><dl>{dl}</dl></div>
<div class="try-presets" role="group" aria-label="Ways to tamper with the bill">{buttons}</div>
<form class="try-fields" id="try-form">
<label>Or type a different sender<input id="try-name" maxlength="80" autocomplete="off" placeholder="e.g. Doe Hardware Suppliers"></label>
<label>A different invoice number<input id="try-no" maxlength="40" autocomplete="off" placeholder="e.g. DH-0999"></label>
<label>A different total, in rupees<input id="try-total" maxlength="30" inputmode="decimal" autocomplete="off" placeholder="e.g. 25000"></label>
<div><button class="pill try-go" type="submit">Check it</button></div></form>
<p class="sub try-note">This page only runs the checker, in memory. Nothing is sent, paid or saved, and account numbers
show their last four digits only.</p></div>
<div class="card try-verdict" id="try-out" aria-live="polite"><span class="k">The checker says</span>
<p class="serif" style="margin-top:8px">Pick a way to cheat on the left.</p></div>
</div></div></section>{TRY_JS}{ATTACK_HTML}"""
    if hasattr(status, "shell"):
        return status.shell("PayRight: try to fool it", body, active="try")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>PayRight: try to fool it</title>{getattr(status, "FONTS", "")}<style>{status.CSS}</style></head><body><main>'
            f'<nav><div class="wrap"><a class="logo" href="./"><b>PayRight</b><span>Cashfree × Sarvam buildathon</span></a>'
            f'<div class="links"><a class="pill" href="./" style="color:#fff">Back to the live board</a></div></div></nav>{body}</main></body></html>')


ATTACK_HTML = """<style>
.atk-form{display:flex;gap:12px;align-items:end;flex-wrap:wrap;margin:28px 0 0}
.atk-form label{display:grid;gap:5px;font:600 13px/1.2 Inter,system-ui,sans-serif;color:var(--paper)}
.atk-form input{font:600 18px/1.2 'JetBrains Mono',ui-monospace,Consolas,monospace;padding:10px 14px;border-radius:12px;border:1px solid #2c2c27;
background:#1b1b18;color:var(--paper);width:170px}
.atk-form button{font-family:inherit;cursor:pointer}
.atk-stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin:32px 0 0}
.atk-stats div{background:#1b1b18;border:1px solid #2c2c27;border-radius:20px;padding:22px}
.atk-stats b{display:block;font:800 clamp(40px,6vw,68px)/1 'Inter Tight',Inter,sans-serif;letter-spacing:-.04em;font-variant-numeric:tabular-nums}
.atk-stats b em{font-style:normal;font-size:.4em;letter-spacing:0;color:#8a8a80}
.atk-stats span{display:block;margin-top:8px;color:#b9b9ad;font-size:14px}
.atk-stats .g b{color:#5fd39b}.atk-stats .r b{color:#ff8f86}.atk-stats .w b{color:#e9c46a}
#atk-out table{margin-top:8px}#atk-out th{color:#8a8a80}#atk-out td,#atk-out th{border-color:#2c2c27}
#atk-out td.num{font:400 13px/1.5 'JetBrains Mono',ui-monospace,Consolas,monospace;text-align:right}#atk-out th.num{text-align:right}
#atk-out td.bad{color:#ff8f86;font-weight:600}#atk-out td.good{color:#5fd39b}#atk-out .grp{color:#8a8a80;font-size:12.5px}
#atk-out .sub{color:#8a8a80;margin-top:18px}
@media (max-width:820px){.atk-stats{grid-template-columns:1fr}}
</style>
<section id="attack" class="ink"><div class="wrap"><p class="eyebrow">Or send a thousand at once</p><h2>Attack it at scale.</h2>
<p class="serif">We forge a thousand variants of real bills our reader read: wrong digits, swapped accounts, raised totals, lookalike names,
the same bill twice. The same checker answers every one. Pick any number: a different number makes different forgeries.</p>
<form class="atk-form" id="atk-form"><label>Your number<input id="atk-seed" inputmode="numeric" maxlength="9" value="1" autocomplete="off"></label>
<button class="pill" type="submit">Forge 1,000 bills</button></form>
<div id="atk-out" aria-live="polite"></div></div></section>
<script>(function(){
var out=document.getElementById('atk-out');
function el(t,c,x){var e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e}
function stat(cls,a,b,label){var d=el('div',cls),n=el('b',null,String(a));n.appendChild(el('em',null,' of '+b));d.appendChild(n);d.appendChild(el('span',null,label));return d}
var NAME={forgery:'forgery',harmless:'genuine, rewritten',beyond:'beyond a bill-only check'};
function show(r,ms){
  out.textContent='';
  if(r.error){out.appendChild(el('p','sub',r.error));return}
  var s=el('div','atk-stats');
  s.appendChild(stat(r.forgeries_cleared?'r':'g',r.forgeries_cleared,r.forgeries,'forgeries cleared to pay. '+r.forgeries_stopped+' were stopped and '+r.forgeries_asked+' sent to a person.'));
  s.appendChild(stat(r.harmless_cleared===r.harmless?'g':'r',r.harmless_cleared,r.harmless,'genuine bills, only written differently, still cleared.'));
  s.appendChild(stat('w',r.beyond_cleared,r.beyond,'we cannot catch: every number raised together. Only a purchase order can.'));
  out.appendChild(s);
  var w=el('div','tablewrap'),t=el('table'),h=el('tr');
  [['What was done to the bill',''],['Tried','num'],['Stopped','num'],['Sent to a person','num'],['Cleared','num']].forEach(function(c){h.appendChild(el('th',c[1],c[0]))});
  t.appendChild(h);
  r.rows.forEach(function(x){var tr=el('tr'),k=el('td',null,x.kind);k.appendChild(el('br'));k.appendChild(el('span','grp',NAME[x.group]));
    tr.appendChild(k);tr.appendChild(el('td','num',x.tried));tr.appendChild(el('td','num',x.stop));tr.appendChild(el('td','num',x.ask));
    var bad=x.group==='forgery'?x.cleared>0:x.group==='harmless'?x.cleared<x.tried:false;
    tr.appendChild(el('td','num '+(bad?'bad':x.group==='beyond'?'':'good'),x.cleared));t.appendChild(tr)});
  w.appendChild(t);out.appendChild(w);
  out.appendChild(el('p','sub',r.made+' forged bills from '+r.base_bills+' genuine ones, number '+r.seed+', decided in '+ms+' ms by the same check.py that guards the money. Memory only: nothing was sent, paid or saved.'));
}
function run(){var t0=Date.now();out.textContent='Forging…';
  fetch('./attack',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({seed:document.getElementById('atk-seed').value})})
  .then(function(r){return r.json()}).then(function(r){show(r,Date.now()-t0)}).catch(function(){show({error:'Could not reach the checker. Try again.'})})}
document.getElementById('atk-form').addEventListener('submit',function(e){e.preventDefault();run()});
if(location.hash==='#attack')run();
})();</script>"""


def attack_handler(raw):
    """POST {"seed": 7} -> 1,000 forged bills decided by the real checker. Memory only."""
    try:
        req = json.loads(raw or "{}")
        seed = abs(int(str((req if isinstance(req, dict) else {}).get("seed") or 1).strip()[:9])) or 1
        code, out = 200, attack.run(1000, seed)
        for row in out.get("rows") or []:
            if row.get("example"):
                row["example"]["reason"] = _mask(row["example"]["reason"])
    except (ValueError, TypeError):
        code, out = 400, {"error": "Give a whole number."}
    return {"statusCode": code, "headers": {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"},
            "body": json.dumps(out, ensure_ascii=False)}


def try_handler(method, raw):
    if method == "GET":
        return {"statusCode": 200, "headers": {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"},
                "body": try_page()}
    try:
        req = json.loads(raw or "{}")
        code, out = fool(req) if isinstance(req, dict) else (400, {"error": "expected a JSON object"})
    except ValueError:
        code, out = 400, {"error": "expected JSON"}
    return {"statusCode": code, "headers": {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"},
            "body": json.dumps(out, ensure_ascii=False)}


class Handler(BaseHTTPRequestHandler):
    def _serve(self, method):
        url = urlsplit(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        route = url.path.rstrip("/")
        if route in ("/try", "/attack") and length > 4096:  # a tampering request is a few short fields
            self.send_error(413)
            return
        shot = re.fullmatch(r"/news/([a-z0-9_]+\.jpg)", route)   # a fixed name pattern: nothing outside docs/news
        if shot and method == "GET":
            f = NEWS / shot.group(1)
            if not f.is_file():
                self.send_error(404)
                return
            data = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Cache-Control", "public, max-age=3600")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        event = {"httpMethod": method, "queryStringParameters": dict(parse_qsl(url.query)),
                 "headers": dict(self.headers.items()),
                 "body": self.rfile.read(length).decode("utf-8", "replace") if length else None}
        if route == "/try":
            out = try_handler(method, event["body"])
        elif route == "/attack" and method == "POST":
            out = attack_handler(event["body"])
        elif route == "/callback":
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

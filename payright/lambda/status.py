"""The live board, "the agent that says no": every bill in a Pay / Ask / Stop lane.

  POST  body = {"decisions": [...], "ledger": [...], "approval": {...}}   (run.py sends this)
        optional: "stage": "calling" while the owner's call is in progress,
                  "facts": [["7 / 7", "planted traps caught"], ...] to replace the three numbers
  GET                     -> the board
  GET   ?format=json      -> the same rows as JSON

One page shows the whole run: five live steps (read, check, owner's call, pay, Cashfree confirms),
the owner's call, and the lanes. Everything on the board comes from check.py's decisions, the
approval and the ledger; nothing is typed in.
Tap a stopped bill to see the two values check.py compared, the wrong one in red.
A bill shows as PAID only when Cashfree has confirmed the transfer (ledger `payout` = PAID,
written by `send.py --confirm`). "Sent to Relay" is shown as sent, never as paid.
No full bank account number is ever shown: last four digits only.

Set PAYRIGHT_TOKEN where this runs and STATUS_TOKEN in payright/.env to the same value, so
only our laptops can update the board. The last copy is kept in memory and /tmp.
Single file, standard library only. Paste it into the Lambda console editor as
lambda_function.py (the default handler name works), or run it through serve.py.
"""
import base64
import hashlib
import html
import json
import os
import re
from datetime import datetime, timedelta, timezone

STORE = "/tmp/payright_status.json"
MEM = {}
IST = timezone(timedelta(hours=5, minutes=30))
LANES = (("PAY", "Pay", "Clean bills. Money moves only after the owner approves."),
         ("ASK", "Ask", "A person must look before anything is paid."),
         ("STOP", "Stop", "Refused. Each one says why."))
LANE_OF = {"PAY": "PAY", "LATER": "PAY", "NOT_SENT": "PAY", "SENT": "PAY", "PAID": "PAY",
           "ASK": "ASK", "FAILED": "ASK", "REVERSED": "ASK", "STOP": "STOP"}
LABEL = {"PAY": "To pay", "LATER": "Later, cash is short", "NOT_SENT": "Approved, not sent yet",
         "SENT": "Sent, waiting for Cashfree", "PAID": "Paid, Cashfree confirmed", "ASK": "Ask the owner",
         "FAILED": "Payout failed", "REVERSED": "Money came back", "STOP": "Stopped"}
NOTE = {"SENT": "Sent to Cashfree through Relay. Not counted as paid until Cashfree confirms.",
        "NOT_SENT": "Approved by the owner but it has not left this machine. A retry uses the same transfer id.",
        "FAILED": "Cashfree says this payout failed. Nothing was paid. It is not retried without the owner.",
        "REVERSED": "Cashfree first paid this, then the bank sent it back. It is not paid and not re-sent by itself."}

# The three measured numbers on the page. Change them here (or send "facts" in the POST) when the
# evidence report changes; never put a number here that has not been measured.
# From docs/evidence (Bhumika's report). Change these two lines when the report changes.
FACTS = (("8 / 8", "planted traps caught"), ("23", "languages read"), ("0", "wrong payments approved"))
FACTS_SOURCE = "measured on 44 invoices, 21 Nov"


def _load():
    if not MEM and os.path.exists(STORE):
        try:
            MEM.update(json.load(open(STORE, encoding="utf-8")))
        except (OSError, ValueError):
            pass
    return MEM


def _request(event):
    event = event or {}
    ctx = event.get("requestContext") or {}
    method = (ctx.get("http") or {}).get("method") or event.get("httpMethod") or ""
    query = event.get("queryStringParameters") or {}
    headers = {str(k).lower(): v for k, v in (event.get("headers") or {}).items()}
    body = event.get("body")
    if body and event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8", "replace")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            body = None
    if not method:  # direct invoke
        method, body = ("POST", event) if "decisions" in event else ("GET", None)
        headers["x-payright-token"] = event.get("token", "")
    return method.upper(), query, headers, body


def _reply(code, body, kind="application/json"):
    return {"statusCode": code, "headers": {"Content-Type": kind + "; charset=utf-8", "Cache-Control": "no-store"},
            "body": body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)}


def _mask(text):
    """Account numbers: last four digits only."""
    return re.sub(r"\d{9,}", lambda m: "····" + m.group()[-4:], str(text))


def rows(data):
    """Decisions joined with the ledger. PAID only when Cashfree confirmed it."""
    ledger = {r["transfer_id"]: r for r in data.get("ledger") or []}
    seen, out = set(), []
    for i, d in enumerate(data.get("decisions") or []):
        led = ledger.get(d.get("transfer_id"))
        state, reasons = d["status"], list(d.get("reasons") or [])
        # a ledger row is this bill if it is the PAY row, or the same file seen again on a later run
        again = (state == "STOP" and len(reasons) == 1 and "has already been" in reasons[0]
                 and led and led.get("file") == d.get("file"))
        if led and d.get("transfer_id") not in seen and (state == "PAY" or again):
            seen.add(d.get("transfer_id"))
            payout = led.get("payout")
            state = (payout if payout in ("PAID", "FAILED", "REVERSED")
                     else "NOT_SENT" if led.get("status") == "NOT_SENT" else "SENT")
            reasons = [NOTE[state]] if state in NOTE else []
        lane = LANE_OF.get(state, "ASK")
        acct = str(d.get("bank_account") or "")
        ev = [{"check": e.get("check"), "a_label": e.get("a_label"), "a": _mask(e.get("a")),
               "b_label": e.get("b_label"), "b": _mask(e.get("b"))} for e in d.get("evidence") or []]
        out.append({"id": f"b{i}", "state": state, "lane": lane, "invoice_no": d.get("invoice_no"),
                    "vendor": d.get("vendor"), "amount": d.get("amount"), "reasons": reasons,
                    "evidence": ev if lane != "PAY" else [],
                    "account": ("····" + acct[-4:]) if acct and lane == "PAY" else "",
                    "transfer_id": d.get("transfer_id") if state in ("NOT_SENT", "SENT", "PAID", "FAILED", "REVERSED") else None,
                    "utr": (led or {}).get("utr") if state == "PAID" else None,
                    "days_left": d.get("days_left"), "file": d.get("file")})
    return out


def _money(x):
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


CSS = """
:root{--blue:#0a22d4;--navy:#050a3c;--soft:#bcc7ff;--line:rgba(255,255,255,.18);--glass:rgba(255,255,255,.08);
--pay:#7df2b0;--stop:#ff6b5c;--ask:#ffd166;--wait:#aab6ff;
--sans:"Segoe UI Variable Display","Segoe UI","Helvetica Neue",Arial,sans-serif;
--mono:ui-monospace,"Cascadia Mono",Consolas,Menlo,monospace}
*{box-sizing:border-box}
html{background:var(--blue)}
body{margin:0;color:#fff;font:16px/1.45 var(--sans);background-color:var(--blue);
background-image:radial-gradient(1.4px 1.4px at 38px 52px,rgba(255,255,255,.55) 50%,transparent 52%),
radial-gradient(1px 1px at 172px 118px,rgba(255,255,255,.4) 50%,transparent 52%),
radial-gradient(1.2px 1.2px at 290px 40px,rgba(255,255,255,.35) 50%,transparent 52%),
radial-gradient(1px 1px at 96px 236px,rgba(255,255,255,.45) 50%,transparent 52%),
radial-gradient(1.6px 1.6px at 246px 300px,rgba(125,242,176,.5) 50%,transparent 52%),
radial-gradient(1px 1px at 330px 190px,rgba(255,255,255,.3) 50%,transparent 52%);
background-size:380px 380px}
.bar{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:11px 16px;
border-bottom:1px solid var(--line);background:rgba(10,34,212,.94)}
.bar b{font-weight:650;font-size:17px;letter-spacing:-.01em}
.bar .k{font:13px var(--mono);color:var(--soft);margin:0 10px}
.bar .r{display:flex;align-items:center;min-width:0}
.pill{background:#fff;color:var(--navy);border-radius:999px;padding:7px 14px;font:600 13px var(--sans);white-space:nowrap}
.shell{display:grid;grid-template-columns:minmax(0,1fr);gap:18px;padding:18px 16px 48px;max-width:1600px;margin:0 auto}
.word,.rail,.panel,.rl,.rr{min-width:0}
.cap{font:12px var(--mono);color:var(--soft);letter-spacing:.02em;margin:0 0 8px}
h1{font-weight:650;letter-spacing:-.05em;line-height:.9;margin:0;font-size:clamp(68px,17vw,128px)}
.rail{display:grid;grid-template-columns:minmax(0,1fr);gap:14px;align-content:start}
.pitch{font-size:20px;line-height:1.3;font-weight:500;margin:0;letter-spacing:-.01em;max-width:34ch}
.box{border:1px solid var(--line);background:var(--glass);border-radius:4px}
.steps{list-style:none;margin:0;padding:4px 14px}
.steps li{display:grid;grid-template-columns:auto minmax(0,1fr) auto 12px;gap:10px;align-items:center;padding:9px 0;
border-bottom:1px solid rgba(255,255,255,.12);font:13px var(--mono)}
.steps li:last-child{border-bottom:0}
.steps .n{color:var(--soft)}
.steps .t{font:600 15px var(--sans);letter-spacing:-.005em}
.steps .v{color:var(--soft);text-align:right;overflow-wrap:anywhere}
.steps .done .v,.steps .live .v,.steps .no .v{color:#fff}
.dot{width:10px;height:10px;border-radius:50%;border:1.5px solid var(--soft);justify-self:end;display:inline-block}
.done .dot{background:var(--pay);border-color:var(--pay)}
.no .dot{background:var(--stop);border-color:var(--stop)}
.live .dot{background:#fff;border-color:#fff;animation:pulse 1.4s ease-out infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(255,255,255,.7)}100%{box-shadow:0 0 0 9px rgba(255,255,255,0)}}
.rr>*+*{margin-top:10px}
.facts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
.fact{padding:12px 11px 10px}
.fact b{display:block;font:650 29px/1 var(--sans);letter-spacing:-.03em;white-space:nowrap}
.fact span{display:block;font:11.5px/1.3 var(--mono);color:var(--soft);margin-top:8px}
.src{font:11.5px var(--mono);color:var(--soft);margin:8px 0 0}
.call{padding:13px 14px}
.call.no{border-color:rgba(255,107,92,.75)}
.lab{font:12px var(--mono);color:var(--soft);margin:0 0 7px;display:flex;gap:10px;align-items:center}
.call p{margin:0 0 9px;font-size:15px}
.call p:last-child{margin-bottom:0}
.call .sm{font-size:13.5px;color:var(--soft)}
.kv{display:grid;grid-template-columns:auto minmax(0,1fr);gap:5px 12px;font:12.5px/1.4 var(--mono);margin:0}
.kv dt{color:var(--soft)}.kv dd{margin:0;overflow-wrap:anywhere}
.notes{padding:12px 14px;font:12px/1.5 var(--mono);color:var(--soft)}
.notes b{color:#fff;font-weight:600;display:block;margin-bottom:4px}
.notes p{margin:0 0 3px;display:grid;grid-template-columns:30px minmax(0,1fr)}
.notes .up{display:block;margin-top:8px;color:#fff}
.panel{background-color:var(--navy);border:1px solid var(--line);border-radius:4px;padding:16px 14px 18px;container-type:inline-size;
background-image:radial-gradient(1px 1px at 60px 80px,rgba(255,255,255,.4) 50%,transparent 52%),
radial-gradient(1.3px 1.3px at 210px 170px,rgba(255,255,255,.3) 50%,transparent 52%),
radial-gradient(1px 1px at 330px 60px,rgba(255,255,255,.25) 50%,transparent 52%),
radial-gradient(1px 1px at 140px 300px,rgba(255,255,255,.3) 50%,transparent 52%);background-size:420px 360px}
.ph{display:flex;justify-content:space-between;align-items:baseline;gap:10px;flex-wrap:wrap;font:12px var(--mono);color:var(--soft);margin:0 0 16px}
.ph span:first-child{color:#fff}
.lanes{display:grid;grid-template-columns:minmax(0,1fr);gap:24px}
@container (min-width:640px){.lanes{grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;align-items:start}}
.lane{min-width:0}
.lane h2{margin:0;font:600 12.5px var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--wait);display:flex;align-items:center;gap:8px}
.lane h2::before{content:"";width:8px;height:8px;background:currentColor;display:inline-block}
.lane.PAY h2{color:var(--pay)}.lane.ASK h2{color:var(--ask)}.lane.STOP h2{color:var(--stop)}
.total{font:650 34px/1.05 var(--sans);letter-spacing:-.03em;margin:9px 0 3px;font-variant-numeric:tabular-nums}
.what{color:var(--soft);font-size:13px;line-height:1.4;margin:0 0 12px}
@container (min-width:640px){.what{min-height:4.3em}}
.card{background:rgba(255,255,255,.06);border:1px solid var(--line);border-left:3px solid var(--wait);border-radius:4px;margin:0 0 10px}
.card.PAY,.card.PAID{border-left-color:var(--pay)}.card.STOP{border-left-color:var(--stop)}
.card.ASK,.card.FAILED,.card.REVERSED{border-left-color:var(--ask)}
body:not(.s) .card{animation:up .5s ease both}
@keyframes up{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
summary{list-style:none;cursor:pointer;padding:12px 12px 11px}summary::-webkit-details-marker{display:none}
summary:focus-visible{outline:2px solid #fff;outline-offset:2px}
.top{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
.vendor{font:600 16.5px/1.2 var(--sans);letter-spacing:-.01em;overflow-wrap:anywhere;min-width:0}
.amt{font:600 16.5px/1.2 var(--sans);font-variant-numeric:tabular-nums;white-space:nowrap}
.meta{font:12px/1.45 var(--mono);color:var(--soft);margin:4px 0 9px;overflow-wrap:anywhere}
.chip{display:inline-flex;align-items:center;gap:7px;font:600 11.5px/1.3 var(--mono);padding:4px 10px;border-radius:13px;
background:#02051f;border:1px solid var(--line);color:var(--wait)}
.chip::before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor;flex:none}
.chip.PAY,.chip.PAID{color:var(--pay)}.chip.STOP{color:var(--stop)}
.chip.ASK,.chip.FAILED,.chip.REVERSED{color:var(--ask)}
.hint{display:block;font:11px var(--mono);color:var(--soft);margin-top:8px}details[open] .hint{display:none}
.body{padding:2px 12px 13px;border-top:1px dashed var(--line)}
.why{margin:10px 0 0;padding:0;list-style:none;font-size:14.5px}.why li{margin:4px 0}
.ev{margin:12px 0 0}.evk{font:600 11px var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--soft);margin:0 0 5px}
.pair{display:grid;grid-template-columns:repeat(auto-fit,minmax(112px,1fr));gap:8px}
.pair div{border-radius:4px;padding:8px 9px;min-width:0}
.pair span{display:block;font:11.5px var(--mono);color:var(--soft)}
.pair b{display:block;font:600 14px/1.3 var(--mono);overflow-wrap:anywhere;margin-top:2px}
.bad{background:rgba(255,107,92,.17);border:1px solid rgba(255,107,92,.65)}.bad b{color:#ff8f83}
.ref{background:rgba(255,255,255,.07);border:1px solid var(--line)}.ref b{color:#fff}
.none{color:var(--soft);font:13px var(--mono);border:1px dashed var(--line);border-radius:4px;padding:14px;margin:0}
.empty{font-size:17px;margin:0 0 16px}
@media(max-width:599px){.bar .k{display:none}}
@media(min-width:760px){
.rail{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}
.pitch,.notes{grid-column:1/-1}
.pitch{font-size:23px}
}
@media(min-width:1240px){
.bar{position:sticky;top:0;z-index:5}
.shell{grid-template-columns:min(22vh,14vw) 300px minmax(0,1fr);gap:22px;padding:22px 24px 56px;align-items:start}
.word{position:sticky;top:64px;height:calc(100vh - 88px);display:flex;align-items:flex-end;gap:6px;overflow:hidden}
.word .cap,.word h1{writing-mode:vertical-rl;transform:rotate(180deg);white-space:nowrap;margin:0}
.word h1{font-size:min(22vh,14vw);line-height:.84}
.rail{grid-template-columns:minmax(0,1fr)}
.pitch{font-size:20px}
}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""

# Reloads only when the data changed, keeps the bills you opened open, and animates cards only on first load.
JS = """<script>(function(){var v=document.body.getAttribute('data-v');
setTimeout(function(){document.body.className+=' s'},900);setInterval(function(){
fetch(location.href,{cache:'no-store'}).then(function(r){return r.text()}).then(function(t){
var d=new DOMParser().parseFromString(t,'text/html');var n=d.body&&d.body.getAttribute('data-v');
if(!n||n===v)return;var open=[].map.call(document.querySelectorAll('details[open]'),function(e){return e.id});
document.querySelector('main').innerHTML=d.querySelector('main').innerHTML;v=n;
open.forEach(function(i){var e=document.getElementById(i);if(e)e.open=true})}).catch(function(){})},4000)})();</script>"""


def _digits(x):
    """'51507', '51,507 rupees' -> 51507.0; anything without digits -> None."""
    s = re.sub(r"[^\d.]", "", str(x or ""))
    try:
        return float(s) if s else None
    except ValueError:
        return None


def _facts(data):
    """The three measured numbers. A POST may replace them: "facts": [["7 / 7", "planted traps caught"], ...]."""
    f = data.get("facts")
    ok = isinstance(f, list) and f and all(isinstance(x, (list, tuple)) and len(x) == 2 for x in f)
    return [(str(a), str(b)) for a, b in (f if ok else FACTS)][:3]


def _steps(data, rs):
    """The five live steps, each (number, name, state, value). state: done | live | wait | no."""
    ap, stage, n = data.get("approval") or {}, str(data.get("stage") or ""), len(rs)
    stopped, ask = sum(r["lane"] == "STOP" for r in rs), sum(r["lane"] == "ASK" for r in rs)
    payable = sum(r["state"] == "PAY" for r in rs)
    sent = sum(r["state"] in ("SENT", "PAID", "FAILED", "REVERSED") for r in rs)
    paid, back = sum(r["state"] == "PAID" for r in rs), sum(r["state"] in ("FAILED", "REVERSED") for r in rs)
    out = [("01", "Read", "done" if n else "wait", f"{n} bill{'s' if n != 1 else ''}" if n else "waiting"),
           ("02", "Check", "done" if n else "wait",
            (f"{stopped} stopped" + (f", {ask} to ask" if ask else "")) if n else "waiting")]
    approved = bool(ap.get("approved_transfer_ids"))
    if approved:
        said = _digits((ap.get("variables") or {}).get("spoken_total"))
        value = "approved " + (_money(said) if said is not None else f"{len(ap['approved_transfer_ids'])} bills")
        out.append(("03", "Owner's call", "done", value))
    elif ap:
        out.append(("03", "Owner's call", "no", "not approved"))
    elif stage == "calling":
        out.append(("03", "Owner's call", "live", "calling…"))
    else:
        out.append(("03", "Owner's call", "wait", "nothing to approve" if n and not payable and not sent else "waiting"))
    out.append(("04", "Pay", "done" if sent else "wait", f"{sent} sent" if sent else ("ready to send" if approved else "waiting")))
    if not sent:
        out.append(("05", "Cashfree confirms", "wait", "waiting"))
    else:
        state = "live" if paid + back < sent else "done" if paid else "no"
        out.append(("05", "Cashfree confirms", state, f"{paid} of {sent} paid" + (f", {back} came back" if back else "")))
    return out


def _call(data):
    """The owner's call: what he decided, the total he said himself, who he left out."""
    e = html.escape
    ap, stage = data.get("approval") or {}, str(data.get("stage") or "")
    if not ap:
        if stage != "calling":
            return ""
        return ('<section class="box call live"><p class="lab"><span>03</span><i class="dot"></i></p>'
                '<p><b>Calling the owner now…</b></p>'
                '<p class="sm">He hears what is clean and what was stopped. Nothing is approved until he says the total himself.</p></section>')
    v = ap.get("variables") or {}
    lang = f" ({e(str(ap['language']))})" if ap.get("language") else ""
    said = _digits(v.get("spoken_total"))
    left = str(v.get("excluded_vendors") or "").strip(" -")
    pairs = (("Decision", str(v.get("decision") or "").replace("_", " ").capitalize()),
             ("He said", _money(said) if said is not None else str(v.get("spoken_total") or "")),
             ("Left out", left or ("nobody" if v.get("decision") else "")),
             ("Summary", str(v.get("call_summary") or "")))
    kv = "".join(f"<dt>{k}</dt><dd>{e(x)}</dd>" for k, x in pairs if x)
    cls = "" if ap.get("approved_transfer_ids") else " no"
    return (f'<section class="box call{cls}"><p class="lab"><span>03</span></p>'
            f'<p><b>Owner\'s call{lang}:</b> {e(str(ap.get("reason") or ""))}</p>'
            f'{"<dl class=kv>" + kv + "</dl>" if kv else ""}</section>')


def _card(r):
    e = html.escape
    meta = " · ".join(x for x in (
        f"Invoice {e(str(r['invoice_no']))}" if r["invoice_no"] else "",
        f"account {e(r['account'])}" if r["account"] else "",
        f"{r['days_left']} days to deadline" if isinstance(r["days_left"], int) and r["state"] in ("PAY", "LATER") else "",
        e(str(r["file"])) if r["file"] else "") if x)
    why = "".join(f"<li>{e(str(x))}</li>" for x in r["reasons"])
    ev = "".join(
        f'<div class="ev"><p class="evk">{e(str(v["check"]))}</p><div class="pair">'
        f'<div class="bad"><span>{e(str(v["a_label"]))}</span><b>{e(v["a"])}</b></div>'
        f'<div class="ref"><span>{e(str(v["b_label"]))}</span><b>{e(v["b"])}</b></div></div></div>' for v in r["evidence"])
    extra = " · ".join(x for x in (f"transfer {e(str(r['transfer_id']))}" if r["transfer_id"] else "",
                                   f"UTR {e(str(r['utr']))}" if r["utr"] else "") if x)
    inside = (f'<ul class="why">{why}</ul>' if why else "") + ev + (f'<p class="meta" style="margin:10px 0 0">{extra}</p>' if extra else "")
    hint = '<span class="hint">tap for the evidence</span>' if r["evidence"] else ""
    return (f'<details class="card {e(r["state"])}" id="{r["id"]}"><summary><div class="top">'
            f'<span class="vendor">{e(str(r["vendor"] or "Unknown vendor"))}</span><span class="amt">{_money(r["amount"])}</span></div>'
            f'<div class="meta">{meta}</div><span class="chip {e(r["state"])}">{e(LABEL.get(r["state"], r["state"]))}</span>{hint}</summary>'
            f'{"<div class=body>" + inside + "</div>" if inside else ""}</details>')


def page(data):
    e = html.escape
    rs = rows(data)
    version = hashlib.sha1(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:12]
    steps = "".join(f'<li class="{s}"><span class="n">{n}</span><span class="t">{t}</span><span class="v">{e(v)}</span>'
                    f'<i class="dot"></i></li>' for n, t, s, v in _steps(data, rs))
    facts = "".join(f'<div class="box fact"><b>{e(a)}</b><span>{e(b)}</span></div>' for a, b in _facts(data))
    lanes = []
    for key, name, what in LANES:
        mine = [r for r in rs if r["lane"] == key]
        total = sum(r["amount"] or 0 for r in mine)
        paid = sum(r["amount"] or 0 for r in mine if r["state"] == "PAID")
        tail = f" {_money(paid)} confirmed paid by Cashfree." if key == "PAY" and paid else ""
        cards = "".join(_card(r) for r in mine) or '<p class="none">Nothing here.</p>'
        lanes.append(f'<section class="lane {key}"><h2>{name} · {len(mine)}</h2><p class="total">{_money(total)}</p>'
                     f'<p class="what">{what}{tail}</p>{cards}</section>')
    updated = str(data.get("updated") or "")
    pill = f"Updated {e(updated)}" if updated else "Waiting for the first batch"
    count = f"{len(rs)} bill{'s' if len(rs) != 1 else ''} · tap a stopped bill for the evidence" if rs else "nothing yet"
    empty = '<p class="empty">No batch has been run yet.</p>' if not rs else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PayRight: the agent that says no</title><style>{CSS}</style></head><body data-v="{version}"><main>
<header class="bar"><div><b>PayRight</b><span class="k">live board</span></div>
<div class="r"><span class="k">Sandbox · synthetic data</span><span class="pill">{pill}</span></div></header>
<div class="shell">
<div class="word"><p class="cap">PayRight · the agent that says no</p><h1>Says no.</h1></div>
<div class="rail">
<p class="pitch">Reads every supplier bill. Pays the real ones. Refuses the fake ones, and says why.</p>
<div class="rl"><ol class="box steps">{steps}</ol></div>
<div class="rr"><div class="facts">{facts}</div><p class="src">{e(FACTS_SOURCE)}</p>{_call(data)}</div>
<div class="box notes"><b>Notes</b><p><span>[1]</span><span>Sandbox only, synthetic data.</span></p>
<p><span>[2]</span><span>Paid means Cashfree confirmed the transfer.</span></p>
<p><span>[3]</span><span>No full account number is shown.</span></p>
<p class="up">Updated {e(updated or "never")} · updates by itself</p></div>
</div>
<section class="panel"><p class="ph"><span>Live board</span><span>{count}</span></p>
{empty}<div class="lanes">{"".join(lanes)}</div></section>
</div></main>{JS}</body></html>"""


def handler(event, context=None):
    method, query, headers, body = _request(event)
    data = _load()
    if method == "POST":
        token = os.environ.get("PAYRIGHT_TOKEN", "")
        if token and headers.get("x-payright-token") != token:
            return _reply(403, {"error": "wrong token"})
        if not isinstance(body, dict) or not isinstance(body.get("decisions"), list):
            return _reply(400, {"error": "expected {decisions: [...], ledger: [...]}"})
        MEM.clear()
        MEM.update({"decisions": body["decisions"], "ledger": body.get("ledger") or [],
                    "approval": body.get("approval"), "stage": body.get("stage"), "facts": body.get("facts"),
                    "updated": datetime.now(IST).strftime("%I:%M:%S %p IST")})
        try:
            json.dump(MEM, open(STORE, "w", encoding="utf-8"))
        except OSError:
            pass
        return _reply(200, {"ok": True, "invoices": len(MEM["decisions"])})
    if query.get("format") == "json":
        return _reply(200, {"rows": rows(data), "updated": data.get("updated")})
    return _reply(200, page(data), "text/html")


def selftest():
    import tempfile
    global STORE
    STORE = os.path.join(tempfile.mkdtemp(), "store.json")  # never the real /tmp copy
    MEM.clear()
    assert "No batch has been run yet" in handler({"httpMethod": "GET"})["body"]
    D = [{"status": "PAY", "invoice_no": "DH-0101", "vendor": "Doe <Hardware>", "amount": 120500.0, "reasons": [], "evidence": [],
          "transfer_id": "T1", "bank_account": "026291800001191", "days_left": 6, "file": "a.png"},
         {"status": "STOP", "invoice_no": "HE-310", "vendor": "Hope Electricals", "amount": 23600.0, "transfer_id": "T2",
          "reasons": ["The bank account on this invoice is not the account we have on file."], "bank_account": "388108022658",
          "evidence": [{"check": "bank account", "a_label": "On the invoice", "a": "026291800001190 YESB0000262",
                        "b_label": "On our file", "b": "388108022658 ICIC0000009"}], "file": "b.png"},
         {"status": "ASK", "invoice_no": "JD-9", "vendor": "Jane D Traders", "amount": 5000.0, "transfer_id": None,
          "reasons": ["This vendor is not in our vendor list."], "evidence": [], "file": "c.png"}]
    os.environ["PAYRIGHT_TOKEN"] = "s3"
    post = {"httpMethod": "POST", "body": json.dumps({"decisions": D, "ledger": []})}
    assert handler(post)["statusCode"] == 403
    assert handler({**post, "headers": {"X-PayRight-Token": "s3"}})["statusCode"] == 200
    p = handler({"httpMethod": "GET"})["body"]
    assert "Doe &lt;Hardware&gt;" in p and "₹1,20,500" in p and "····1191" in p
    assert "····1190 YESB0000262" in p and "····2658 ICIC0000009" in p and 'class="bad"' in p   # the evidence, masked
    for full in ("026291800001191", "026291800001190", "388108022658"):
        assert full not in p                                             # no full account number anywhere

    def states(ledger, decisions=D):
        handler({"decisions": decisions, "ledger": ledger, "token": "s3"})   # direct invoke
        r = json.loads(handler({"httpMethod": "GET", "queryStringParameters": {"format": "json"}})["body"])["rows"]
        return [x["state"] for x in r]
    led = {"transfer_id": "T1", "file": "a.png"}
    # paid ONLY when Cashfree confirmed it
    assert states([{**led, "status": "ACCEPTED"}]) == ["SENT", "STOP", "ASK"]
    assert states([{**led, "status": "UNKNOWN"}]) == ["SENT", "STOP", "ASK"]
    assert states([{**led, "status": "NOT_SENT"}]) == ["NOT_SENT", "STOP", "ASK"]
    assert states([{**led, "status": "ACCEPTED", "payout": "PENDING"}]) == ["SENT", "STOP", "ASK"]
    assert states([{**led, "status": "ACCEPTED", "payout": "NOT_FOUND"}]) == ["SENT", "STOP", "ASK"]
    assert states([{**led, "status": "ACCEPTED", "payout": "PAID", "utr": "U1"}]) == ["PAID", "STOP", "ASK"]
    assert "Paid, Cashfree confirmed" in handler({"httpMethod": "GET"})["body"]
    assert states([{**led, "status": "ACCEPTED", "payout": "REVERSED"}]) == ["REVERSED", "STOP", "ASK"]
    assert states([{**led, "status": "ACCEPTED", "payout": "FAILED"}]) == ["FAILED", "STOP", "ASK"]
    # second run of the same batch: check.py now says STOP "has already been accepted"; the board follows the ledger
    again = [{**D[0], "status": "STOP", "reasons": ["Invoice number DH-0101 from Doe has already been accepted."]},
             {**D[0], "file": "dup.png", "status": "STOP", "reasons": ["Invoice number DH-0101 from Doe has already been accepted."]}]
    assert states([{**led, "status": "ACCEPTED"}], again) == ["SENT", "STOP"]
    assert states([{**led, "status": "ACCEPTED", "payout": "PAID"}], again) == ["PAID", "STOP"]
    handler({"decisions": D, "ledger": [], "approval": {"approved_transfer_ids": ["T1"], "reason": "ok", "language": "Hindi"}, "token": "s3"})
    assert "Owner's call (Hindi):" in handler({"httpMethod": "GET"})["body"]

    # the five live steps follow the data, and the call shows what the owner actually said
    def steps(**data):
        return [(s, v) for _, _, s, v in _steps(data, rows(data))]
    assert steps() == [("wait", "waiting")] * 5
    assert steps(decisions=D)[:3] == [("done", "3 bills"), ("done", "1 stopped, 1 to ask"), ("wait", "waiting")]
    assert steps(decisions=D, stage="calling")[2] == ("live", "calling…")
    ap = {"approved_transfer_ids": ["T1"], "reason": "ok", "language": "Hindi",
          "variables": {"decision": "APPROVE_ALL", "excluded_vendors": "-", "spoken_total": "120500", "call_summary": "<b>ok</b>"}}
    assert steps(decisions=D, approval=ap)[2:] == [("done", "approved ₹1,20,500"), ("wait", "ready to send"), ("wait", "waiting")]
    assert steps(decisions=D, approval={"approved_transfer_ids": [], "reason": "no"})[2] == ("no", "not approved")
    assert steps(decisions=D, approval=ap, ledger=[{**led, "status": "ACCEPTED"}])[3:] == [("done", "1 sent"), ("live", "0 of 1 paid")]
    assert steps(decisions=D, approval=ap, ledger=[{**led, "status": "ACCEPTED", "payout": "PAID"}])[4] == ("done", "1 of 1 paid")
    assert steps(decisions=D, approval=ap, ledger=[{**led, "status": "ACCEPTED", "payout": "REVERSED"}])[4] == ("no", "0 of 1 paid, 1 came back")
    handler({"decisions": D, "ledger": [], "approval": ap, "stage": "calling", "facts": [["9 / 9", "x"]], "token": "s3"})
    p = handler({"httpMethod": "GET"})["body"]
    assert "He said" in p and "₹1,20,500" in p and "nobody" in p and "&lt;b&gt;ok&lt;/b&gt;" in p and "<b>ok</b>" not in p
    assert "9 / 9" in p and "7 / 7" not in p and "Calling the owner now" not in p   # an answer replaces "calling"
    handler({"decisions": D, "ledger": [], "stage": "calling", "token": "s3"})
    p = handler({"httpMethod": "GET"})["body"]
    assert "Calling the owner now" in p and "8 / 8" in p and "Says no." in p
    del os.environ["PAYRIGHT_TOKEN"]
    print("selftest ok")


lambda_handler = handler  # the console default is lambda_function.lambda_handler: paste this file as is


if __name__ == "__main__":
    selftest()

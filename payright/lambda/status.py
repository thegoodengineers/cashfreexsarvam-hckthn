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
/* Same system as our Mend site: sage ground, giant tight sans titles, italic serif sub-lines with a swash
   initial, thin line art, black pills. Green and red only ever mean paid and refused. */
:root{--bg:#e6e6dd;--paper:#f4f4ee;--ink:#0f0f0d;--mute:#5d5d55;--line:#cbcbbf;--ok:#16794a;--bad:#b83a3a;--warn:#a26a12}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 Inter,system-ui,-apple-system,'Segoe UI',sans-serif}
a{color:inherit}.wrap{max-width:1160px;margin:auto;padding:0 24px}
nav{position:sticky;top:0;background:rgba(230,230,221,.86);backdrop-filter:blur(10px);z-index:5}
nav .wrap{display:flex;align-items:center;justify-content:space-between;height:64px;gap:12px}
.logo{text-decoration:none;display:flex;flex-direction:column;line-height:1.05}
.logo b{font:800 17px 'Inter Tight',Inter,sans-serif;letter-spacing:-.01em}.logo span{font-size:12px;color:var(--mute)}
nav .links{display:flex;align-items:center;gap:22px}nav .links a{color:var(--mute);text-decoration:none;font-size:14px}
nav .links a:hover{color:var(--ink)}
.pill{display:inline-block;background:var(--ink);color:#fff;border-radius:999px;padding:9px 18px;font-weight:600;font-size:14px;
text-decoration:none;border:1px solid var(--ink);white-space:nowrap}
.pill.ghost{background:transparent;color:var(--ink)}
header{position:relative;overflow:hidden;padding:56px 0 60px}
header svg.art{position:absolute;inset:0;width:100%;height:100%;z-index:0}
header .wrap{position:relative;z-index:1}
.eyebrow{font:600 14px/1.3 Inter,sans-serif;color:var(--ink);margin:0 0 14px}
.mega{font:800 clamp(72px,17vw,224px)/.82 'Inter Tight',Inter,'Segoe UI',sans-serif;letter-spacing:-.055em;margin:0}
.lede{font:italic 400 clamp(26px,3.4vw,40px)/1.15 'Instrument Serif',Georgia,serif;margin:18px 0 0;max-width:820px}
.cap{font:400 1.9em/0 'Pinyon Script','Segoe Script',cursive;font-style:normal;vertical-align:-.12em;margin-right:.03em}
.intro{color:var(--mute);font-size:18px;max-width:600px;margin:22px 0 0}
.cta{display:flex;gap:12px;margin-top:28px;flex-wrap:wrap}
.hero-grid{display:grid;grid-template-columns:1.4fr 1fr;gap:40px;align-items:end;margin-top:28px}
.stat,.card{background:var(--paper);border-radius:22px;padding:26px;
box-shadow:0 1px 1px rgba(15,15,13,.04),0 18px 40px rgba(15,15,13,.07);display:flex;flex-direction:column;gap:6px}
.k{font:600 13px/1.3 Inter,sans-serif;color:var(--ink)}
.big{font:800 56px/1 'Inter Tight',Inter,sans-serif;letter-spacing:-.04em;font-variant-numeric:tabular-nums}
.big em{font-style:normal;color:var(--mute);font-size:24px;letter-spacing:0}
.sub{color:var(--mute);font-size:14px}
.link{color:var(--ink);text-decoration:underline;text-underline-offset:3px;font-weight:600;font-size:14px;margin-top:6px}
section{padding:84px 0}section.alt{background:var(--paper)}
section.alt .stat,section.alt .card,section.alt .step,section.alt .bill{background:var(--bg)}
h2{font:800 clamp(40px,6vw,76px)/.95 'Inter Tight',Inter,sans-serif;letter-spacing:-.045em;margin:0 0 18px}
.serif{font:italic 400 22px/1.3 'Instrument Serif',Georgia,serif;color:var(--mute);max-width:760px;margin:0}
.steps{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:14px;margin-top:40px}
.step{background:var(--paper);border-radius:20px;padding:22px;position:relative;
box-shadow:0 1px 1px rgba(15,15,13,.04),0 12px 28px rgba(15,15,13,.05)}
.step b{display:block;margin:8px 0 6px;font:800 22px/1.1 'Inter Tight',Inter,sans-serif;letter-spacing:-.02em}
.step p{margin:0;color:var(--mute);font-size:15px}
.n{font:400 30px/1 'Pinyon Script','Segoe Script',cursive;color:var(--mute)}
.st{position:absolute;top:24px;right:20px;font:600 12px/1 'JetBrains Mono',ui-monospace,Consolas,monospace;color:var(--mute)}
.step.done .st{color:var(--ok)}.step.no .st{color:var(--bad)}.step.done p,.step.live p{color:var(--ink)}
.step.live{box-shadow:0 0 0 2px var(--ink),0 12px 28px rgba(15,15,13,.08)}.step.live .st{color:var(--ink)}
.lanes{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:24px;margin-top:40px;align-items:start}
.lane .pill{padding:6px 14px;font-size:13px}.lane.STOP .pill{background:var(--bad);border-color:var(--bad)}
.lane.ASK .pill{background:transparent;color:var(--ink)}
.lane .big{font-size:48px;margin-top:14px}.lane .sub{margin:8px 0 16px}
.bill{background:var(--paper);border-radius:18px;margin:0 0 12px;
box-shadow:0 1px 1px rgba(15,15,13,.04),0 12px 28px rgba(15,15,13,.05)}
.bill summary{list-style:none;cursor:pointer;padding:18px 20px}.bill summary::-webkit-details-marker{display:none}
.top{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
.vendor{font:800 20px/1.15 'Inter Tight',Inter,sans-serif;letter-spacing:-.02em;overflow-wrap:anywhere}
.amt{font:800 20px/1.15 'Inter Tight',Inter,sans-serif;letter-spacing:-.02em;white-space:nowrap;font-variant-numeric:tabular-nums}
.meta{font:400 12.5px/1.5 'JetBrains Mono',ui-monospace,Consolas,monospace;color:var(--mute);margin:4px 0 10px;overflow-wrap:anywhere}
.chip{display:inline-block;border-radius:999px;padding:5px 12px;font:600 12.5px/1.2 Inter,sans-serif;border:1px solid var(--ink);color:var(--ink)}
.chip.PAY{background:var(--ink);color:#fff}.chip.PAID{background:var(--ok);border-color:var(--ok);color:#fff}
.chip.STOP{background:var(--bad);border-color:var(--bad);color:#fff}
.chip.FAILED,.chip.REVERSED{border-color:var(--bad);color:var(--bad)}.chip.ASK{border-color:var(--warn);color:var(--warn)}
.chip.LATER,.chip.SENT,.chip.NOT_SENT{border-color:var(--mute);color:var(--mute)}
.hint{float:right;font-size:12.5px;color:var(--mute);text-decoration:underline;text-underline-offset:3px;padding-top:6px}
details[open] .hint{display:none}
.body{padding:2px 20px 20px;border-top:1px solid var(--line)}
.why{margin:14px 0 0;padding:0;list-style:none;font-size:15px}.why li{margin:4px 0}
.ev{margin:14px 0 0}.evk{font:600 13px/1.2 Inter,sans-serif;margin:0 0 6px;text-transform:capitalize}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.pair div{border-radius:12px;padding:10px 12px;min-width:0;border:1px solid var(--line)}
.pair span{display:block;font-size:12.5px;color:var(--mute)}
.pair b{display:block;font:600 14px/1.35 'JetBrains Mono',ui-monospace,Consolas,monospace;overflow-wrap:anywhere}
.pair .bad{border-color:var(--bad)}.pair .bad b{color:var(--bad)}
.none{color:var(--mute);font:italic 400 20px/1.3 'Instrument Serif',Georgia,serif;border:1px dashed var(--line);
border-radius:18px;padding:18px 20px;margin:0}
.two{display:grid;grid-template-columns:1.1fr 1fr;gap:48px;align-items:center}
.card p{margin:0}.card.no{box-shadow:0 0 0 2px var(--bad),0 18px 40px rgba(15,15,13,.07)}
dl.kv{display:grid;grid-template-columns:auto 1fr;gap:6px 18px;margin:12px 0 0;font-size:15px}
dl.kv dt{color:var(--mute)}dl.kv dd{margin:0;font-weight:600;overflow-wrap:anywhere}
.tools{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px;margin-top:36px}
footer{padding:48px 0;color:var(--mute);font-size:14px}footer p{margin:2px 0}
@media (max-width:1020px){.steps{grid-template-columns:repeat(2,minmax(0,1fr))}.lanes{grid-template-columns:1fr}}
@media (max-width:820px){.hero-grid,.two{grid-template-columns:1fr}.steps,.tools{grid-template-columns:1fr}
nav .links a.hide{display:none}section{padding:60px 0}.wrap{padding:0 16px}.big{font-size:44px}}
@media (prefers-reduced-motion:no-preference){.art circle,.art path{stroke-dasharray:1600;animation:draw 2.4s ease-out both}
@keyframes draw{from{stroke-dashoffset:1600}to{stroke-dashoffset:0}}
.step.live .st{animation:blink 1.2s ease-in-out infinite}@keyframes blink{50%{opacity:.35}}}
"""

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@600;800&family=Instrument+Serif:ital@0;1'
         '&family=Pinyon+Script&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">')
ART = ('<svg class="art" viewBox="0 0 1200 700" preserveAspectRatio="xMidYMid slice" aria-hidden="true" fill="none" '
       'stroke="#b9b9ad" stroke-width="1"><circle cx="860" cy="330" r="300"/><circle cx="860" cy="330" r="190"/>'
       '<circle cx="860" cy="330" r="80"/><path d="M0 330 H1200"/><path d="M860 0 V700"/>'
       '<path d="M560 30 Q860 330 1160 30"/><path d="M560 630 Q860 330 1160 630"/><path d="M0 700 Q600 120 1200 700"/></svg>')
STATE_WORD = {"done": "done", "live": "now", "wait": "waiting", "no": "no"}

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
        return ('<section id="call"><div class="wrap two"><div><p class="eyebrow">03 · Owner\'s call</p>'
                '<h2>Calling the owner now…</h2><p class="serif">He hears what is clean and what was stopped. '
                'Nothing is approved until he says the total himself.</p></div>'
                '<div class="card"><span class="k">On the phone</span><span class="big">…</span>'
                '<span class="sub">waiting for his answer</span></div></div></section>')
    v = ap.get("variables") or {}
    lang = f" ({e(str(ap['language']))})" if ap.get("language") else ""
    said = _digits(v.get("spoken_total"))
    left = str(v.get("excluded_vendors") or "").strip(" -")
    pairs = (("Decision", str(v.get("decision") or "").replace("_", " ").capitalize()),
             ("He said", _money(said) if said is not None else str(v.get("spoken_total") or "")),
             ("Left out", left or ("nobody" if v.get("decision") else "")),
             ("Summary", str(v.get("call_summary") or "")))
    kv = "".join(f"<dt>{k}</dt><dd>{e(x)}</dd>" for k, x in pairs if x)
    yes = bool(ap.get("approved_transfer_ids"))
    return (f'<section id="call"><div class="wrap two"><div><p class="eyebrow">03 · Owner\'s call</p>'
            f'<h2>{"He said the amount himself." if yes else "No approval, no payment."}</h2>'
            f'<p class="serif">A yes is not enough. The owner has to say the total aloud, and it has to match.</p></div>'
            f'<div class="card{"" if yes else " no"}"><p><b>Owner\'s call{lang}:</b> {e(str(ap.get("reason") or ""))}</p>'
            f'{"<dl class=kv>" + kv + "</dl>" if kv else ""}</div></div></section>')


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
    inside = (f'<ul class="why">{why}</ul>' if why else "") + ev + (f'<p class="meta" style="margin:12px 0 0">{extra}</p>' if extra else "")
    hint = '<span class="hint">see the evidence</span>' if r["evidence"] else ""
    return (f'<details class="bill card-{e(r["state"])}" id="{r["id"]}"><summary><div class="top">'
            f'<span class="vendor">{e(str(r["vendor"] or "Unknown vendor"))}</span><span class="amt">{_money(r["amount"])}</span></div>'
            f'<div class="meta">{meta}</div><span class="chip {e(r["state"])}">{e(LABEL.get(r["state"], r["state"]))}</span>{hint}</summary>'
            f'{"<div class=body>" + inside + "</div>" if inside else ""}</details>')


def page(data):
    e = html.escape
    rs = rows(data)
    version = hashlib.sha1(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:12]
    steps = "".join(f'<div class="step {s}"><span class="n">{n}</span><span class="st">{STATE_WORD.get(s, s)}</span>'
                    f'<b>{t}</b><p>{e(v)}</p></div>' for n, t, s, v in _steps(data, rs))
    facts = "".join(f'<div class="stat"><span class="big">{e(a)}</span><span class="k">{e(b)}</span></div>' for a, b in _facts(data))
    lanes = []
    for key, name, what in LANES:
        mine = [r for r in rs if r["lane"] == key]
        total = sum(r["amount"] or 0 for r in mine)
        paid = sum(r["amount"] or 0 for r in mine if r["state"] == "PAID")
        tail = f" {_money(paid)} confirmed paid by Cashfree." if key == "PAY" and paid else ""
        cards = "".join(_card(r) for r in mine) or '<p class="none">Nothing here.</p>'
        lanes.append(f'<div class="lane {key}"><span class="pill">{name} · {len(mine)}</span><div class="big">{_money(total)}</div>'
                     f'<p class="sub">{what}{tail}</p>{cards}</div>')
    n, stopped = len(rs), sum(r["lane"] == "STOP" for r in rs)
    to_pay = sum(r["amount"] or 0 for r in rs if r["state"] in ("PAY", "NOT_SENT"))
    sent = sum(r["state"] in ("SENT", "PAID", "FAILED", "REVERSED") for r in rs)
    paid_n = sum(r["state"] == "PAID" for r in rs)
    updated = str(data.get("updated") or "")
    tag = str(data.get("round") or "")
    if n:
        live = (f'<span class="k">Live{" · round " + e(tag) if tag else ""}</span>'
                f'<span class="big">{stopped}<em> of {n} bills refused</em></span>'
                f'<span class="sub">{_money(to_pay)} waiting to be paid · {sent} sent · {paid_n} confirmed paid by Cashfree</span>'
                f'<a class="link" href="#board">see every bill →</a>')
    else:
        live = ('<span class="k">Live</span><span class="big">0<em> bills</em></span>'
                '<span class="sub">No batch has been run yet.</span>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PayRight: the agent that says no</title>{FONTS}<style>{CSS}</style></head><body data-v="{version}"><main>
<nav><div class="wrap"><a class="logo" href="#"><b>PayRight</b><span>Cashfree × Sarvam buildathon</span></a>
<div class="links"><a class="hide" href="#run">The run</a><a class="hide" href="#board">The board</a>
<a class="hide" href="#numbers">Numbers</a><span class="pill">{"Updated " + e(updated) if updated else "Waiting for the first batch"}</span></div></div></nav>
<header>{ART}<div class="wrap">
<p class="eyebrow">The Good Engineers · built at the Cashfree × Sarvam buildathon, 21 Nov 2026</p>
<h1 class="mega">PayRight</h1>
<p class="lede"><span class="cap">T</span>he agent that says no.</p>
<div class="hero-grid"><div><p class="intro">Reads every supplier bill. Pays the real ones. Refuses the fake ones, and says why.</p>
<div class="cta"><a class="pill" href="#board">See the live board</a><a class="pill ghost" href="#run">Follow the run</a></div></div>
<div class="stat">{live}</div></div></div></header>
<section id="run" class="alt"><div class="wrap"><p class="eyebrow">The run, live</p><h2>Five steps, one screen.</h2>
<p class="serif">A model reads. Plain code decides. The owner approves by phone. Cashfree pays.</p>
<div class="steps">{steps}</div></div></section>
<section id="board"><div class="wrap"><p class="eyebrow">The board</p><h2>Every bill, and why.</h2>
<p class="serif">{"Tap a refused bill to see the two values that were compared." if n else "No batch has been run yet."}</p>
<div class="lanes">{"".join(lanes)}</div></div></section>
{_call(data).replace('<section id="call">', '<section id="call" class="alt">')}
<section id="numbers"{"" if _call(data) else ' class="alt"'}><div class="wrap"><p class="eyebrow">Numbers</p><h2>Measured, not hoped.</h2>
<p class="serif">{e(FACTS_SOURCE)}.</p><div class="tools">{facts}</div></div></section>
<footer><div class="wrap"><p>[1] Sandbox only, synthetic data. [2] Paid means Cashfree confirmed the transfer.
[3] No full account number is shown.</p><p>Updated {e(updated or "never")} · updates by itself</p></div></footer>
</main>{JS}</body></html>"""


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
    assert "Calling the owner now" in p and "8 / 8" in p and "says no" in p
    del os.environ["PAYRIGHT_TOKEN"]
    print("selftest ok")


lambda_handler = handler  # the console default is lambda_function.lambda_handler: paste this file as is


if __name__ == "__main__":
    selftest()

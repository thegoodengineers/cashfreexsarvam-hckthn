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
import time
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

/* ---- effects: all of it is switched off under prefers-reduced-motion ---- */
.mega.mid{font-size:clamp(56px,10.5vw,140px);line-height:.9}
.stat,.card,.step,.bill,.trick{transition:transform .25s ease,box-shadow .25s ease}
.bill:hover,.stat:hover,.trick:hover{transform:translateY(-3px);box-shadow:0 2px 2px rgba(15,15,13,.05),0 24px 46px rgba(15,15,13,.13)}
.pill{transition:transform .15s ease,background .2s ease,color .2s ease}.pill:hover{transform:translateY(-1px)}
.pill.ghost:hover{background:var(--ink);color:#fff}
nav .links a.on{color:var(--ink);font-weight:600}
section.ink{background:var(--ink);color:var(--paper)}section.ink .eyebrow{color:var(--paper)}section.ink .serif{color:#b9b9ad}
section.ink .step,section.ink .trick{background:#1b1b18;box-shadow:none;border:1px solid #2c2c27}
section.ink .step b,section.ink .trick b{color:var(--paper)}section.ink .step p,section.ink .trick p{color:#b9b9ad}
section.ink .step.done p,section.ink .step.live p{color:var(--paper)}section.ink .n{color:#8a8a80}section.ink .st{color:#8a8a80}
section.ink .step.done .st{color:#5fd39b}section.ink .step.no .st{color:#ff8f86}
section.ink .step.live{box-shadow:0 0 0 2px var(--paper)}section.ink .step.live .st{color:var(--paper)}
section.ink .pill{background:var(--paper);color:var(--ink);border-color:var(--paper)}
section.ink .pill.ghost{background:transparent;color:var(--paper)}section.ink .pill.ghost:hover{background:var(--paper);color:var(--ink)}
.track{height:4px;background:#2c2c27;border-radius:4px;margin-top:26px;overflow:hidden}
.track i{display:block;height:100%;width:var(--w,0%);background:#5fd39b;border-radius:4px;transition:width 1.4s cubic-bezier(.2,.7,.2,1)}
.log{margin:34px 0 0;padding:0;list-style:none;display:grid;gap:8px;max-width:760px}
.log li{display:grid;grid-template-columns:104px 1fr;gap:14px;font-size:15px;color:#b9b9ad;border-top:1px solid #2c2c27;padding-top:8px}
.log li:first-child{color:var(--paper)}.log time{font:400 12.5px/1.7 'JetBrains Mono',ui-monospace,Consolas,monospace;color:#8a8a80}
.band{background:var(--ink);color:var(--paper);overflow:hidden;white-space:nowrap;padding:15px 0;
font:600 13.5px/1 'JetBrains Mono',ui-monospace,Consolas,monospace;border-top:1px solid #2c2c27}
.band div{display:inline-block;padding-left:100%}.band span{margin-right:14px}.band b{margin-right:46px;font-weight:400;color:#b9b9ad}
.band .r{color:#ff8f86}.band .g{color:#5fd39b}.band .w{color:#e9c46a}
.chip.STOP{background:transparent;color:var(--bad);border:2px solid var(--bad);border-radius:7px;text-transform:uppercase;
letter-spacing:.13em;font-weight:800;font-size:12px;padding:5px 9px;transform:rotate(-4deg)}
.chip.PAID{text-transform:uppercase;letter-spacing:.08em;font-size:12px}
.trick{background:var(--paper);border-radius:20px;padding:26px;box-shadow:0 1px 1px rgba(15,15,13,.04),0 12px 28px rgba(15,15,13,.05)}
.trick b{display:block;font:800 26px/1.05 'Inter Tight',Inter,sans-serif;letter-spacing:-.02em;margin:8px 0 8px}
.trick p{margin:0;color:var(--mute);font-size:15px}section.alt .trick{background:var(--bg)}
.grid2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;margin-top:36px}
.tablewrap{overflow-x:auto;margin-top:28px}table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:12px 8px;border-bottom:1px solid var(--line)}th{color:var(--mute);font-weight:500}
td.mono{font:400 12.5px/1.5 'JetBrains Mono',ui-monospace,Consolas,monospace;overflow-wrap:anywhere}
td.ok{color:var(--ok);font-weight:600}td.wait{color:var(--mute)}td.no{color:var(--bad);font-weight:600}
.cases{display:grid;gap:26px;margin-top:40px}
.case{background:var(--paper);border-radius:22px;overflow:hidden;display:grid;grid-template-columns:minmax(0,5fr) minmax(0,6fr);
box-shadow:0 1px 1px rgba(15,15,13,.04),0 18px 40px rgba(15,15,13,.07)}
.case .shot{display:block;align-self:start;margin:22px 0 22px 22px;border-radius:12px;overflow:hidden;border:1px solid var(--line);
background:#fff;text-decoration:none;transform:rotate(-1.2deg);box-shadow:0 10px 26px rgba(15,15,13,.14);transition:transform .25s ease}
.case:nth-child(even) .shot{transform:rotate(1.1deg)}.case .shot:hover{transform:none}
.case .shot img{display:block;width:100%;height:auto;aspect-ratio:1200/760;object-fit:cover;object-position:top}
.case .shot span{display:block;padding:8px 12px;font:600 12.5px/1.3 'JetBrains Mono',ui-monospace,Consolas,monospace;color:var(--mute);border-top:1px solid var(--line)}
.case .shot.gone img{display:none}
.case .in{padding:26px 28px;display:flex;flex-direction:column;gap:6px;min-width:0}
.case .loss{font:800 clamp(40px,5vw,60px)/1 'Inter Tight',Inter,sans-serif;letter-spacing:-.04em;color:var(--bad);font-variant-numeric:tabular-nums}
.case h3{font:800 24px/1.1 'Inter Tight',Inter,sans-serif;letter-spacing:-.02em;margin:0 0 6px}
.case dl{margin:0;display:grid;gap:2px}.case dt{font:600 13px/1.3 Inter,sans-serif;margin-top:10px}.case dd{margin:0;color:var(--mute);font-size:15px}
.case .fix{border-top:1px solid var(--line);margin-top:16px;padding-top:16px}.case .fix p{margin:10px 0 0;font-size:15px}
.case .fix .cta{margin-top:14px}.case .fix .pill{padding:7px 14px;font-size:13px}
.trick .src{margin-top:10px;font-size:13px}
.trickline{margin:12px 0 0;font-size:14px;color:var(--mute)}.trickline b{color:var(--ink)}.trickline a{white-space:nowrap}
@media (max-width:820px){.grid2{grid-template-columns:1fr}.log li{grid-template-columns:1fr;gap:0}
.case{grid-template-columns:1fr}.case .shot{margin:16px 16px 0}.case .in{padding:20px}section.ink .steps{grid-template-columns:1fr!important}}
@media (prefers-reduced-motion:no-preference){
[data-r]{opacity:0;transform:translateY(24px);transition:opacity .7s cubic-bezier(.2,.7,.2,1),transform .7s cubic-bezier(.2,.7,.2,1);
transition-delay:calc(var(--i,0)*70ms)}[data-r].in{opacity:1;transform:none}
.mega{animation:rise .9s cubic-bezier(.2,.7,.2,1) both}@keyframes rise{from{transform:translateY(38%);opacity:0}}
.lede{animation:rise .9s .12s cubic-bezier(.2,.7,.2,1) both}
svg.art{animation:drift 20s ease-in-out infinite alternate;transform-origin:72% 47%}@keyframes drift{to{transform:scale(1.07) rotate(2deg)}}
.band div{animation:slide 42s linear infinite}@keyframes slide{to{transform:translateX(-100%)}}
[data-r].in .chip.STOP{animation:stamp .45s .25s cubic-bezier(.2,1.4,.4,1) both}
@keyframes stamp{from{transform:scale(2.4) rotate(-16deg);opacity:0}to{transform:rotate(-4deg);opacity:1}}
section.ink .step.live{animation:ring 1.6s ease-in-out infinite}
@keyframes ring{50%{box-shadow:0 0 0 2px var(--paper),0 0 0 9px rgba(244,244,238,.12)}}}
"""

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@600;800&family=Instrument+Serif:ital@0;1'
         '&family=Pinyon+Script&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">')
ART = ('<svg class="art" viewBox="0 0 1200 700" preserveAspectRatio="xMidYMid slice" aria-hidden="true" fill="none" '
       'stroke="#b9b9ad" stroke-width="1"><circle cx="860" cy="330" r="300"/><circle cx="860" cy="330" r="190"/>'
       '<circle cx="860" cy="330" r="80"/><path d="M0 330 H1200"/><path d="M860 0 V700"/>'
       '<path d="M560 30 Q860 330 1160 30"/><path d="M560 630 Q860 330 1160 630"/><path d="M0 700 Q600 120 1200 700"/></svg>')
STATE_WORD = {"done": "done", "live": "now", "wait": "waiting", "no": "no"}

JS = """<script>(function(){
var rm=window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches;
function inr(n){var s=String(Math.round(n)),h=s.slice(0,-3),t=s.slice(-3),p=[];while(h.length>2){p.unshift(h.slice(-2));h=h.slice(0,-2)}
if(h)p.unshift(h);return '\\u20b9'+p.concat([t]).join(',')}
function put(el,x){if(el.firstChild&&el.firstChild.nodeType===3)el.firstChild.nodeValue=x;else el.insertBefore(document.createTextNode(x),el.firstChild)}
function count(el,now){if(el.__c)return;el.__c=1;var to=parseFloat(el.getAttribute('data-count'));if(isNaN(to))return;
var f=el.hasAttribute('data-rupee')?inr:function(v){return String(Math.round(v))};if(now||rm){put(el,f(to));return}
var t0=0;function step(ts){if(!t0)t0=ts;var k=Math.min(1,(ts-t0)/900);k=1-Math.pow(1-k,3);put(el,f(to*k));if(k<1)requestAnimationFrame(step)}
requestAnimationFrame(step)}
function arm(now){var els=document.querySelectorAll('[data-r]');
if(now||rm||!('IntersectionObserver' in window)){[].forEach.call(els,function(e){e.classList.add('in')});
[].forEach.call(document.querySelectorAll('[data-count]'),function(e){count(e,true)});return}
var io=new IntersectionObserver(function(en){en.forEach(function(x){if(!x.isIntersecting)return;x.target.classList.add('in');
if(x.target.hasAttribute('data-count'))count(x.target);[].forEach.call(x.target.querySelectorAll('[data-count]'),function(e){count(e)});
io.unobserve(x.target)})},{threshold:0,rootMargin:'0px 0px -4% 0px'});[].forEach.call(els,function(e){io.observe(e)})}
arm(false);setTimeout(function(){arm(true)},6000);
var v=document.body.getAttribute('data-v');if(!v)return;
setInterval(function(){fetch(location.href,{cache:'no-store'}).then(function(r){return r.text()}).then(function(t){
var d=new DOMParser().parseFromString(t,'text/html');var n=d.body&&d.body.getAttribute('data-v');if(!n||n===v)return;
var open=[].map.call(document.querySelectorAll('details[open]'),function(e){return e.id}),y=window.scrollY;
document.querySelector('main').innerHTML=d.querySelector('main').innerHTML;v=n;
open.forEach(function(i){var e=document.getElementById(i);if(e)e.open=true});arm(true);window.scrollTo(0,y)}).catch(function(){})},4000)})();</script>"""


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


# Each refusal names the old trick it matches. Keyed by check.py's evidence "check". A real case is linked only
# where the reported facts are the same trick (see CASES on the problem page); the others carry no case.
TRICK_OF = {
    "bank account": ("A familiar vendor, a new account.", "This is how Manipal Technologies lost ₹1.04 crore"),
    "account holder": ("The right vendor, somebody else's name on the account.", "The same family of fraud as the cases on record"),
    "account owner": ("A real account, borrowed for another name's bill.", ""),
    "duplicate": ("The same bill, sent twice.", ""),
    "price": ("Next month's bill, quietly raised.", ""),
    "total": ("Sums that do not add up.", ""), "line item": ("Sums that do not add up.", ""),
    "line items": ("Sums that do not add up.", ""), "amount in words": ("Words and figures that disagree.", "")}


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
    trick, case = TRICK_OF.get(str(r["evidence"][0]["check"]) if r["evidence"] else "", ("", ""))
    known = (f'<p class="trickline">Known trick: <b>{e(trick)}</b>'
             + (f' <a href="./?page=problem">{e(case)} →</a>' if case else "") + "</p>") if trick else ""
    if r["evidence"] and r["evidence"][0]["check"] in ("bank account", "account holder", "account owner"):
        # the step that was skipped in every reported case: one call, on a number the fraudster does not control
        known += (f'<p class="trickline">Next step: <b>call {e(str(r["vendor"] or "the vendor"))} on the number already on file</b>, '
                  f'never a number printed on this bill, and ask whether they sent invoice {e(str(r["invoice_no"] or "?"))}.</p>')
    inside = (f'<ul class="why">{why}</ul>' if why else "") + known + ev + (f'<p class="meta" style="margin:12px 0 0">{extra}</p>' if extra else "")
    hint = '<span class="hint">see the evidence</span>' if r["evidence"] else ""
    return (f'<details class="bill card-{e(r["state"])}" id="{r["id"]}" data-r><summary><div class="top">'
            f'<span class="vendor">{e(str(r["vendor"] or "Unknown vendor"))}</span><span class="amt">{_money(r["amount"])}</span></div>'
            f'<div class="meta">{meta}</div><span class="chip {e(r["state"])}">{e(LABEL.get(r["state"], r["state"]))}</span>{hint}</summary>'
            f'{"<div class=body>" + inside + "</div>" if inside else ""}</details>')


HAS_TRY = False   # serve.py turns this on: the "Try to fool it" page needs the checker next to it
NAV = (("home", "./", "Live board"), ("problem", "./?page=problem", "The problem"), ("evidence", "./?page=evidence", "Evidence"),
       ("how", "./?page=how", "How it works"), ("run", "./?page=run", "Run it live"))
HOW_STEPS = (
    ("Read", "Sarvam Vision reads each bill in its own language and script. It only reads. A field it is not sure of is flagged, never guessed."),
    ("Check", "Plain code compares the bill with itself, with the vendor file and with every bill already seen. A refusal carries the two values that were compared."),
    ("Owner's call", "A Sarvam voice agent phones the owner, gives the reason for every stopped bill, and asks him to say the total himself."),
    ("Pay", "Approved bills go to Cashfree through Relay, to the account on file, with a transfer ID made from the invoice itself."),
    ("Cashfree confirms", "A bill counts as paid only when Cashfree says so. Until then the board says sent."))
TRICKS = (
    ("The same bill, sent twice", "A new number, a new date format, a slightly different spelling. The invoice number is normalised and compared for the same vendor."),
    ("Sums that do not add up", "Line items, subtotal, tax, total and the amount in words are checked against each other."),
    ("A familiar vendor, a new account", "Money only ever goes to the account on file. A different account on the invoice stops the bill."),
    ("Someone else's account", "A bill that asks to be paid into another vendor's account is stopped, even when the account itself is real."))
NOT_DONE = (
    ("No model decides about money", "The model reads. Whether to pay, ask or stop is plain code that anyone can read line by line."),
    ("No bank details from the invoice", "The account comes from the vendor file, never from the page in front of us."),
    ("No second transfer ID", "One invoice, one ID, for life. A retry reuses it, so a retry cannot become a second payment."))


def shell(title, body, active="home", version="", updated=""):
    """One complete page: nav, body, footer, fonts, styles and the script. serve.py uses it for /try."""
    e = html.escape
    links = NAV + ((("try", "./try", "Try to fool it"),) if HAS_TRY or active == "try" else ())
    nav = "".join(f'<a class="hide{" on" if k == active else ""}" href="{h}">{t}</a>' for k, h, t in links)
    pill = f'<span class="pill">Updated {e(updated)}</span>' if updated else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title>{FONTS}<style>{CSS}</style></head><body data-v="{version}"><main>
<nav><div class="wrap"><a class="logo" href="./"><b>PayRight</b><span>Cashfree × Sarvam buildathon</span></a>
<div class="links">{nav}{pill}</div></div></nav>
{body}
<footer><div class="wrap"><p>[1] Sandbox only, synthetic data. [2] Paid means Cashfree confirmed the transfer.
[3] No full account number is shown.</p><p>{"Updated " + e(updated) + " · updates by itself" if updated else "The Good Engineers · 21 Nov 2026"}</p></div></footer>
</main>{JS}</body></html>"""


def _band(rs):
    """The moving strip under the hero: what the agent has just refused, sent and paid."""
    e, out = html.escape, []
    for r in rs:
        what = (r["evidence"][0]["check"] if r["evidence"] else "") or (r["reasons"][0][:48] if r["reasons"] else "")
        word, cls = {"STOP": ("REFUSED", "r"), "PAID": ("PAID", "g"), "ASK": ("ASK", "w")}.get(r["state"], (r["state"].replace("_", " "), ""))
        out.append(f'<span class="{cls}">{e(word)}</span><b>{e(str(r["invoice_no"] or "?"))} · {e(str(r["vendor"] or ""))} · '
                   f'{_money(r["amount"])}{" · " + e(what) if what and r["lane"] != "PAY" else ""}</b>')
    return f'<div class="band" aria-hidden="true"><div>{"".join(out) or "<b>Waiting for the first batch</b>"}</div></div>'


def _lanes(rs):
    lanes = []
    for key, name, what in LANES:
        mine = [r for r in rs if r["lane"] == key]
        total = sum(r["amount"] or 0 for r in mine)
        paid = sum(r["amount"] or 0 for r in mine if r["state"] == "PAID")
        tail = f" {_money(paid)} confirmed paid by Cashfree." if key == "PAY" and paid else ""
        cards = "".join(_card(r) for r in mine) or '<p class="none">Nothing here.</p>'
        lanes.append(f'<div class="lane {key}"><span class="pill">{name} · {len(mine)}</span>'
                     f'<div class="big" data-r data-count="{total:.0f}" data-rupee>{_money(total)}</div>'
                     f'<p class="sub">{what}{tail}</p>{cards}</div>')
    return "".join(lanes)


def _home(data, rs):
    e = html.escape
    st = _steps(data, rs)
    steps = "".join(f'<div class="step {s}" data-r style="--i:{i}"><span class="n">{n}</span><span class="st">{STATE_WORD.get(s, s)}</span>'
                    f'<b>{t}</b><p>{e(v)}</p></div>' for i, (n, t, s, v) in enumerate(st))
    done = sum(s == "done" for _, _, s, _ in st) + 0.5 * sum(s == "live" for _, _, s, _ in st)
    log = "".join(f'<li><time>{e(str(x.get("t") or ""))}</time><span>{e(str(x.get("text") or ""))}</span></li>'
                  for x in reversed(data.get("events") or []))
    facts = ""
    for i, (a, b) in enumerate(_facts(data)):
        num = f' data-count="{a}"' if a.strip().isdigit() else ""
        facts += f'<div class="stat" data-r style="--i:{i}"><span class="big"{num}>{e(a)}</span><span class="k">{e(b)}</span></div>'
    n, stopped = len(rs), sum(r["lane"] == "STOP" for r in rs)
    to_pay = sum(r["amount"] or 0 for r in rs if r["state"] in ("PAY", "NOT_SENT"))
    sent = sum(r["state"] in ("SENT", "PAID", "FAILED", "REVERSED") for r in rs)
    paid_n = sum(r["state"] == "PAID" for r in rs)
    tag = str(data.get("round") or "")
    if n:
        live = (f'<span class="k">Live{" · round " + e(tag) if tag else ""}</span>'
                f'<span class="big" data-count="{stopped}">{stopped}<em> of {n} bills refused</em></span>'
                f'<span class="sub">{_money(to_pay)} waiting to be paid · {sent} sent · {paid_n} confirmed paid by Cashfree</span>'
                f'<a class="link" href="#board">see every bill →</a>')
    else:
        live = ('<span class="k">Live</span><span class="big">0<em> bills</em></span>'
                '<span class="sub">No batch has been run yet.</span>')
    call = _call(data).replace('<section id="call">', '<section id="call" class="alt">')
    more = '<a class="pill ghost" href="./try">Try to fool it</a>' if HAS_TRY else ""
    return f"""<header>{ART}<div class="wrap">
<p class="eyebrow">The Good Engineers · built at the Cashfree × Sarvam buildathon, 21 Nov 2026</p>
<h1 class="mega">PayRight</h1>
<p class="lede"><span class="cap">T</span>he agent that says no.</p>
<div class="hero-grid"><div><p class="intro">Reads every supplier bill. Pays the real ones. Refuses the fake ones, and says why.</p>
<div class="cta"><a class="pill" href="#board">See the live board</a><a class="pill ghost" href="./?page=problem">It already happened</a><a class="pill ghost" href="./?page=evidence">Why we said no</a>{more}</div></div>
<div class="stat">{live}</div></div></div></header>
{_band(rs)}
<section id="run" class="ink"><div class="wrap"><p class="eyebrow">The run, live</p><h2 data-r>Five steps, one screen.</h2>
<p class="serif">A model reads. Plain code decides. The owner approves by phone. Cashfree pays.</p>
<div class="steps">{steps}</div><div class="track"><i style="--w:{done * 20:.0f}%"></i></div>
{"<ul class=log>" + log + "</ul>" if log else ""}</div></section>
<section id="board"><div class="wrap"><p class="eyebrow">The board</p><h2 data-r>Every bill, and why.</h2>
<p class="serif">{"Tap a refused bill to see the two values that were compared." if n else "No batch has been run yet."}</p>
<div class="lanes">{_lanes(rs)}</div></div></section>
{call}
<section id="numbers"{"" if call else ' class="alt"'}><div class="wrap"><p class="eyebrow">Numbers</p><h2 data-r>Measured, not hoped.</h2>
<p class="serif">{e(FACTS_SOURCE)}.</p><div class="tools">{facts}</div></div></section>
<section class="ink"><div class="wrap"><p class="eyebrow">Look closer</p><h2 data-r>Do not take our word for it.</h2>
<p class="serif">Every refusal has its proof, every payment its trail.</p>
<div class="cta"><a class="pill" href="./?page=evidence">See the evidence</a><a class="pill ghost" href="./?page=how">How it works</a>{more}</div></div></section>"""


def _evidence(data, rs):
    e = html.escape
    held = [r for r in rs if r["lane"] != "PAY"]
    cards = "".join(_card(r).replace('<details class="bill', '<details open class="bill') for r in held)
    trail = ""
    for r in (x for x in rs if x["lane"] == "PAY"):
        cls = "ok" if r["state"] == "PAID" else "wait"
        trail += (f'<tr><td>{e(str(r["invoice_no"] or ""))}</td><td>{e(str(r["vendor"] or ""))}</td><td>{_money(r["amount"])}</td>'
                  f'<td class="{cls}">{e(LABEL.get(r["state"], r["state"]))}</td><td class="mono">{e(str(r["account"] or ""))}</td>'
                  f'<td class="mono">{e(str(r["transfer_id"] or "not sent yet"))}</td><td class="mono">{e(str(r["utr"] or ""))}</td></tr>')
    ap = data.get("approval") or {}
    who = (f'Approved on the owner\'s call{" (" + e(str(ap["language"])) + ")" if ap.get("language") else ""}: {e(str(ap.get("reason") or ""))}'
           if ap else "No owner approval on this batch yet, so nothing has been sent.")
    return f"""<header>{ART}<div class="wrap"><p class="eyebrow">Evidence · {len(held)} refused or held, {len(rs) - len(held)} cleared</p>
<h1 class="mega mid">Why we said no.</h1>
<p class="lede"><span class="cap">E</span>very refusal shows the two values that were compared.</p></div></header>
<section class="alt"><div class="wrap"><p class="eyebrow">Refused and held</p><h2 data-r>The proof, bill by bill.</h2>
<p class="serif">{"The wrong value is in red. Account numbers show the last four digits only." if held else "Nothing has been refused in this batch."}</p>
<div class="grid2">{cards}</div></div></section>
<section><div class="wrap"><p class="eyebrow">Paid and to pay</p><h2 data-r>Every payment, traced.</h2>
<p class="serif">{who}</p>
<div class="tablewrap"><table><tr><th>Invoice</th><th>Vendor</th><th>Amount</th><th>State</th><th>Account on file</th><th>Transfer ID</th><th>UTR</th></tr>
{trail or '<tr><td colspan="7">No batch has been run yet.</td></tr>'}</table></div></div></section>"""


def _how(data, rs):
    steps = "".join(f'<div class="step" data-r style="--i:{i}"><span class="n">0{i + 1}</span><b>{t}</b><p>{p}</p></div>'
                    for i, (t, p) in enumerate(HOW_STEPS))
    tricks = "".join(f'<div class="trick" data-r style="--i:{i}"><span class="n">0{i + 1}</span><b>{t}</b><p>{p}</p></div>'
                     for i, (t, p) in enumerate(TRICKS))
    nots = "".join(f'<div class="trick" data-r style="--i:{i}"><b>{t}</b><p>{p}</p></div>' for i, (t, p) in enumerate(NOT_DONE))
    return f"""<header>{ART}<div class="wrap"><p class="eyebrow">How it works</p>
<h1 class="mega mid">A model reads. Code decides.</h1>
<p class="lede"><span class="cap">S</span>ixty bills a week, three scripts, one tired accountant.</p></div></header>
<section class="alt"><div class="wrap"><p class="eyebrow">The loop</p><h2 data-r>From a photo to a payment.</h2>
<div class="steps">{steps}</div></div></section>
<section><div class="wrap"><p class="eyebrow">What it catches</p><h2 data-r>Four old tricks, four hard stops.</h2>
<p class="serif">Each one is a comparison a person could do by hand, done every time.</p><div class="grid2">{tricks}</div></div></section>
<section class="ink"><div class="wrap"><p class="eyebrow">What we chose not to do</p><h2 data-r>Three things we refused to build.</h2>
<div class="tools">{nots}</div></div></section>
<section class="alt"><div class="wrap two"><div><p class="eyebrow">Honest status</p><h2 data-r>Working today, and not yet.</h2></div>
<div class="card"><p><b>Working today:</b> reading in 23 languages, the checks, the owner's call, payouts through Relay to Cashfree, no double payment.</p>
<p style="margin-top:10px"><b>Not yet:</b> Cashfree's own bank-account verification. Secure ID was not enabled on our test account today, so the account on file is trusted.</p></div></div></section>"""


# ------------------------------------------------------------ the problem page: real, reported cases
# Screenshots live in docs/news/. serve.py serves them from ./news/; the Lambda copy reads them from the public repo.
NEWS_BASE = "https://raw.githubusercontent.com/thegoodengineers/cashfreexsarvam-hckthn/main/docs/news/"
# Every fact below was read on the linked page on 21 Nov 2026. Do not add a case that has not been read.
# (image, loss, who, source and date, link, what happened, how they found out, what they did, what PayRight does, /try preset)
CASES = (
    ("manipal_1cr", "₹1.04 crore", "Manipal Technologies, Udupi", "Deccan Herald",
     "https://www.deccanherald.com/india/karnataka/manipal-technologies-limited-lured-into-sending-rs-104-crore-to-the-account-of-cyber-fraudsters-3787920",
     "The company was paying a quarterly lease to a business partner and had already paid four instalments into the partner's account. "
     "Two days after the real reminder for the fifth, a second email arrived from a lookalike address: please pay into a new account. They did.",
     "Two weeks later, when the real partner said it had not been paid.",
     "Complaint at the Udupi Cyber Crime police station. Police again asked companies to verify every bank account change through official channels.",
     "Four payments had gone to one account, so that is the account on file. The fifth bill names another one: STOP, with both accounts shown side by side.", "digit"),
    ("hyderabad_1_5cr", "₹1.5 crore", "A semiconductor firm, Hyderabad", "The Siasat Daily, 19 Nov 2026",
     "https://www.siasat.com/hyderabad-semiconductor-firm-loses-rs-1-5-crore-in-email-spoofing-3581019/",
     "Fraudsters read the mail between the firm and its sensor supplier and registered a domain with one letter doubled. "
     "They offered a 2 per cent discount and sent a revised invoice with a different bank account.",
     "When the components never arrived and the firm called its real supplier.",
     "Complaint to the Cyberabad cybercrime unit. A cheating case was registered on 16 Nov 2026.",
     "A revised invoice with a different account is exactly the bill we stop. The discount does not matter: the account is not the one on file.", "digit"),
    ("mumbai_89l", "₹89.34 lakh", "A furniture importer, Mumbai", "The Free Press Journal, 2 Apr 2026",
     "https://www.freepressjournal.in/mumbai/mumbai-crime-furniture-firm-duped-of-89-lakh-in-email-spoofing-scam-cyber-police-probe-cross-border-fraud",
     "The first half of the order was paid to the supplier's real account and acknowledged. Before the second half, an email from an address "
     "with two letters swapped said an audit had blocked the old account, and asked for the balance in a new one.",
     "The next day, when the real supplier began sending reminders that it had not been paid.",
     "Reported to the 1930 cyber helpline. A case was registered against the unknown sender and the holder of the receiving account.",
     "The first payment proves which account is real. The second bill asks for another: STOP, and the owner is told to call the supplier on the number he already has.", "digit"),
    ("pune_2_3cr", "₹2.3 crore", "An engineering firm, Pune", "Punekar News, 10 Jul 2025",
     "https://www.punekarnews.in/pune-firm-loses-rs-2-3-crore-in-international-email-fraud-involving-fake-bank-account/",
     "An email that looked like the Italian machine-maker's carried bank details different from earlier correspondence. "
     "Police said the accounts department paid without cross-checking with the supplier.",
     "When the firm asked the supplier to confirm receipt and the supplier said no money had come.",
     "Case with the Pune cyber police, who asked businesses to verify any change in payment instructions on a separate channel, such as a phone call to a known contact.",
     "That cross-check is not left to a busy accounts desk. Code does it on every bill, and nothing is paid until the owner has heard the reason on the phone.", "other_account"),
    ("drreddys_2cr", "₹2.16 crore", "Dr Reddy's and Group Pharmaceuticals, Bengaluru", "The Tribune (PTI), 10 Nov 2025",
     "https://www.tribuneindia.com/news/business/dr-reddys-group-pharmaceuticals-duped-of-rs-2-crore-in-email-spoofing-fraud",
     "Hackers allegedly got into the official email exchange between the two companies and diverted a payment to a fraudulent bank account.",
     "Not given in the report.",
     "Reported to the cyber crime police in Bengaluru.",
     "Size does not protect anyone: this is a listed company. The rule is the same for a shop and for a listed firm. Money goes to the account on file.", "other_account"),
    ("chennai_2cr", "₹2 crore", "A trading company, Chennai", "Business Today, 8 Oct 2024",
     "https://www.businesstoday.in/tech-today/news/story/rs-2-crore-gone-in-a-click-chennai-businessman-falls-prey-to-email-scam-449190-2024-10-08",
     "A fake email continued a real thread with the supplier and attached a pro-forma invoice with bank details. The general manager paid it.",
     "The next day, on following up with the real supplier.",
     "Complaint on the national cyber crime portal the same week. The police, the banks and I4C traced the transfer and the full amount came back. This is the lucky one.",
     "The bill would have stopped before the transfer, so nobody would have needed to be lucky.", "digit"),
    ("fb_google_120m", "$120 million", "Facebook and Google", "US Department of Justice, 19 Dec 2019",
     "https://www.justice.gov/usao-sdny/pr/lithuanian-man-sentenced-5-years-prison-theft-over-120-million-fraudulent-business",
     "From 2013 to 2015 one man billed two of the world's largest technology companies in the name of a real hardware maker they bought from, "
     "and had them wire the money to bank accounts he controlled.",
     "Not given in the court statement.",
     "He was arrested, pleaded guilty to wire fraud and was sentenced to five years in prison.",
     "A real supplier's name on the bill is not enough for us. The account has to be the one on file for that supplier.", "other_account"),
    ("toyota_37m", "$37 million", "Toyota Boshoku, a European subsidiary", "BleepingComputer, Sep 2019",
     "https://www.bleepingcomputer.com/news/security/over-37-million-lost-by-toyota-boshoku-subsidiary-in-bec-scam/",
     "The company said it had followed fraudulent payment directions from a third party and paid about 4 billion yen on 14 Aug 2019.",
     "Shortly after the money had left, the company said.",
     "It formed a team with lawyers to recover the money and reported it to the authorities.",
     "New payment directions never change where our money goes. Only the vendor file does, and a bill that disagrees with it is stopped.", "digit"),
)
PROBLEM_FACTS = (
    ("$2.8 bn", "lost to business email compromise in one year, as reported to the FBI in 2024",
     "FBI IC3 2024 report, as summarised by Nacha", "https://www.nacha.org/news/fbis-ic3-finds-almost-85-billion-lost-business-email-compromise-last-three-years"),
    ("1.29%", "of the invoices small and mid-sized firms receive are duplicates: about six a month for a typical firm",
     "SAP Concur, study of 2.8 million invoices", "https://www.concur.com/blog/article/how-much-money-your-business-throwing-away-duplicate-invoice-payments"),
    ("₹8.1 lakh cr", "estimated to be stuck in delayed payments to India's small suppliers",
     "White paper reported by Business Today, Feb 2026",
     "https://www.businesstoday.in/industry/story/rs-81-lakh-crore-stuck-in-dues-msme-growth-hinges-on-dispute-reform-warns-white-paper-518307-2026-02-27"))
RULES = (
    ("The account on file, or nothing", "Bank details for a payment come from the vendor file, never from the bill or the email in front of us. "
     "A bill that names another account is stopped, even when it is one digit off."),
    ("The phone call is built in", "Police advise a call to a known contact. Our refusal says exactly that, and a Sarvam voice agent reads it to the owner in his own language."),
    ("A yes is not enough", "The owner has to say the total himself, and it has to match. A hurried yes on a bad line pays nothing."),
    ("One bill, one payment", "The transfer ID is made from the invoice itself, so the same bill sent again, renumbered or reformatted, cannot be paid twice."))
NOT_STOPPED = (
    ("Bills for goods that never came", "A Mumbai firm paid ₹1.73 crore and ISKCON Kolkata ₹2 crore against bills for goods that were not delivered, by police accounts. "
     "We check the bill against itself and the vendor file, not against the godown. A new vendor is held as ASK; a known vendor billing for missing goods is not caught.",
     (("Lokmat Times, 11 Jul 2025", "https://www.lokmattimes.com/mumbai/mumbai-private-firm-in-borivali-duped-of-nearly-rs2-crore-using-fake-bills-two-arrested-a522"),
      ("Telangana Today, 10 Nov 2025", "https://telanganatoday.com/kolkata-man-held-for-cheating-iskcon-of-rs-2-crore-through-fake-bills"))),
    ("A vendor file that is itself wrong", "If a fraudster's account is typed into the vendor file, we would pay it. Cashfree's bank-account verification is the lock for that, "
     "and it was not enabled on our test account today.", ()),
    ("None of these companies used PayRight", "What we say we would have done is our rule applied to the facts as reported. Do not take our word for it: replay the trick on the real checker.", ()))
OTHERS = (
    ("Bank-account verification services", "Trustpair, Eftsure", "Verify who owns an account, using bank data or call-back teams.",
     "Built for finance teams with an ERP. We do the same comparison for a shop owner with a phone, and call him in his language."),
    ("Accounts-payable suites in India", "RazorpayX, Zoho, Open", "Read invoices, match them to purchase orders, approve with a click or an OTP.",
     "Our approval cannot be a tap. The owner hears every refusal and says the total aloud, and a model never decides."))


def _problem(data, rs):
    e = html.escape
    facts = "".join(f'<div class="stat" data-r style="--i:{i}"><span class="big">{e(a)}</span><span class="k">{e(b)}</span>'
                    f'<a class="link" href="{e(u)}" target="_blank" rel="noopener">{e(s)} ↗</a></div>'
                    for i, (a, b, s, u) in enumerate(PROBLEM_FACTS))
    cases = ""
    for i, (img, loss, who, src, url, what, found, after, ours, preset) in enumerate(CASES):
        replay = (f'<a class="pill" href="./try#{preset}">Replay this trick on our checker</a>' if HAS_TRY else "")
        cases += (f'<article class="case" data-r><a class="shot" href="{e(url)}" target="_blank" rel="noopener">'
                  f'<img src="{e(NEWS_BASE)}{img}.jpg" alt="Screenshot of the report: {e(who)}, {e(src)}" '
                  f'onerror="this.parentNode.classList.add(\'gone\')"><span>{e(src)} ↗</span></a>'
                  f'<div class="in"><span class="n">{i + 1:02d}</span><span class="loss">{e(loss)}</span><h3>{e(who)}</h3>'
                  f'<dl><dt>What happened</dt><dd>{e(what)}</dd><dt>How they found out</dt><dd>{e(found)}</dd>'
                  f'<dt>What they did</dt><dd>{e(after)}</dd></dl>'
                  f'<div class="fix"><span class="chip STOP">Stopped</span><p><b>With PayRight:</b> {e(ours)}</p>'
                  f'<div class="cta">{replay}<a class="pill ghost" href="{e(url)}" target="_blank" rel="noopener">Read the report</a></div></div>'
                  f'</div></article>')
    rules = "".join(f'<div class="step" data-r style="--i:{i}"><span class="n">0{i + 1}</span><b>{e(t)}</b><p>{e(p)}</p></div>'
                    for i, (t, p) in enumerate(RULES))
    nots = ""
    for i, (t, p, links) in enumerate(NOT_STOPPED):
        ls = " · ".join(f'<a href="{e(u)}" target="_blank" rel="noopener">{e(s)} ↗</a>' for s, u in links)
        nots += f'<div class="trick" data-r style="--i:{i}"><b>{e(t)}</b><p>{e(p)}</p>{"<p class=src>" + ls + "</p>" if ls else ""}</div>'
    others = "".join(f'<tr><td><b>{e(a)}</b><br><span class="sub">{e(b)}</span></td><td>{e(c)}</td><td>{e(d)}</td></tr>' for a, b, c, d in OTHERS)
    more = '<a class="pill ghost" href="./try">Try to fool it</a>' if HAS_TRY else ""
    return f"""<header>{ART}<div class="wrap"><p class="eyebrow">The problem · {len(CASES)} reported cases, every one linked to its source</p>
<h1 class="mega mid">It already happened.</h1>
<p class="lede"><span class="cap">O</span>ne email, one new bank account, crores gone.</p>
<p class="intro">These are not our examples. They are police complaints and court records. In each one, a real supplier's bill
was paid into somebody else's account.</p></div></header>
<section class="alt"><div class="wrap"><p class="eyebrow">How big</p><h2 data-r>Not rare. Routine.</h2>
<p class="serif">Three numbers from other people's reports, not ours.</p><div class="tools">{facts}</div></div></section>
<section><div class="wrap"><p class="eyebrow">The cases</p><h2 data-r>Real companies, real money.</h2>
<p class="serif">What happened, how they found out, what they did, and what our checker does with the same bill.</p>
<div class="cases">{cases}</div></div></section>
<section class="ink"><div class="wrap"><p class="eyebrow">The pattern</p><h2 data-r>Nobody noticed until the supplier asked.</h2>
<p class="serif">In five of the six Indian cases the fraud came out only when the real supplier was asked, or asked, about the money.
By then it had left. So the check has to happen before the payment, every time, without anyone remembering to do it.</p>
<div class="steps" style="grid-template-columns:repeat(4,minmax(0,1fr))">{rules}</div></div></section>
<section><div class="wrap"><p class="eyebrow">What already exists</p><h2 data-r>Others check. We also ask.</h2>
<p class="serif">As their own pages describe them, read on 21 Nov 2026.</p>
<div class="tablewrap"><table><tr><th>Kind of tool</th><th>What it does</th><th>What we do differently</th></tr>{others}</table></div>
</div></section>
<section class="alt"><div class="wrap"><p class="eyebrow">Honest limits</p><h2 data-r>What we would not have stopped.</h2>
<p class="serif">A tool that claims to stop everything is the one to distrust.</p><div class="tools">{nots}</div>
<div class="cta" style="margin-top:36px"><a class="pill" href="./?page=evidence">See our own evidence</a>
<a class="pill ghost" href="./?page=how">How it works</a>{more}</div>
<p class="sub" style="margin-top:28px;max-width:760px">Screenshots are of the publishers' own pages, taken on 21 Nov 2026, and each one links to
the original. Amounts and facts are as reported there. Several cases are still under police investigation.</p></div></section>"""


# ------------------------------------------------------------ the run page: the live demo is started here
# The buttons do nothing on this server. A press is queued, and payright/demo.py on the presenter's laptop
# collects it, runs the step there (the keys never leave that laptop) and sends back what it printed.
# A press needs this server's token, typed once into the page. Pressing Run still pays nothing by itself:
# money moves only after the owner says the total on the phone.
RUN_COMMANDS = ("selftest", "round", "live", "saved", "refresh", "again", "stop")
CON = {"lines": [], "base": 0, "busy": False, "seen": 0.0, "queue": []}
RUN_BUTTONS = (("selftest", "0 Safety self-tests", 1), ("round", "1 New round", 1), ("saved", "2 Read and check", 0),
               ("refresh", "5 Ask Cashfree", 0), ("again", "6 Run again: no double pay", 1), ("stop", "Stop", 1))
RUN_CSS = """<style>
#rc button{font:inherit;font-weight:600;font-size:15px;cursor:pointer;margin:0 8px 10px 0}#rc button:disabled{opacity:.35;cursor:default}
#rc .note{display:inline-block;border:1px dashed var(--mute);border-radius:999px;padding:8px 16px;margin:0 8px 10px 0;font-size:15px}
#rcout{margin:14px 0 0;padding:16px;height:52vh;overflow:auto;background:var(--ink);color:#d6d6d6;border-radius:16px;
font:14px/1.55 ui-monospace,Consolas,monospace;white-space:pre-wrap}
#rcout .ok{color:#7ee787}#rcout .no{color:#ff7b72}#rcout .wait{color:#e3b341}#rcout .hd{color:#79c0ff}
#rcstate{font-weight:600;margin:0 0 14px}#rckey{font:inherit;padding:9px 14px;border:1px solid var(--ink);border-radius:999px;width:260px;margin-right:8px}
</style>"""
RUN_JS = """<script>
(function(){var n=0,w=null,key="";try{key=sessionStorage.getItem("prkey")||""}catch(e){}
function $(i){return document.getElementById(i)}
function say(t){var s=$("rcmsg");if(s)s.textContent=t}
function add(o,l){var m=l.match(/^\\s*(no call started yet|call in progress)\\.\\.\\. (\\d+s)/);
if(m){if(!w||!w.isConnected){w=document.createElement("span");w.className="wait";o.appendChild(w)}
w.textContent="waiting for the owner's answer on the phone... "+m[2]+"\\n";return}
w=null;var s=document.createElement("span");s.textContent=l+"\\n";
s.className=/^(PAY\\b|PAID|ACCEPTED|APPROVED)|selftest ok/.test(l)?"ok":/^(STOP|NOT APPROVED|NOT_SENT|FAILED|REVERSED|UNKNOWN)/.test(l)?"no":
/^(ASK|LATER|waiting|Waiting)/.test(l)?"wait":/^(\\$|ROUND|SCORE)/.test(l)?"hd":"";o.appendChild(s)}
function paint(d){var st=$("rcstate");if(st)st.textContent=d.online?(d.busy?"The presenter's laptop is running a step.":"The presenter's laptop is connected and idle."):"The presenter's laptop is not connected.";
var lock=$("rclock");if(lock)lock.style.display=key?"none":"block";
document.querySelectorAll("#rc [data-step]").forEach(function(b){b.disabled=!key||!d.online||(d.busy&&b.dataset.step!="stop")})}
document.addEventListener("click",function(ev){var b=ev.target.closest&&ev.target.closest("#rc [data-step],#rcunlock");if(!b)return;
if(b.id=="rcunlock"){key=($("rckey").value||"").trim();$("rckey").value="";try{sessionStorage.setItem("prkey",key)}catch(e){}say("");return}
fetch("./",{method:"POST",headers:{"Content-Type":"application/json","x-payright-token":key},body:JSON.stringify({command:b.dataset.step})})
.then(function(r){if(r.status==403){key="";try{sessionStorage.removeItem("prkey")}catch(e){}say("That key is wrong.")}
else if(r.status==409)say("The presenter's laptop is not connected.");else say("")})});
function poll(){var o=$("rcout");if(!o){setTimeout(poll,1000);return}
if(!o.dataset.live){o.dataset.live="1";n=0;w=null}   // the board swaps the page in place: draw the console again
fetch("./?format=console&from="+n,{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){
var o=$("rcout");if(o&&o.dataset.live){d.lines.forEach(function(l){add(o,l)});if(d.lines.length)o.scrollTop=o.scrollHeight;n=d.next}paint(d)})
.catch(function(){}).then(function(){setTimeout(poll,1000)})}
poll()})();
</script>"""


def _run(data, rs):
    buttons = "".join(f'<button class="pill{" ghost" if ghost else ""}" data-step="{k}" disabled>{t}</button>' for k, t, ghost in RUN_BUTTONS)
    return f"""<header>{ART}<div class="wrap"><p class="eyebrow">Run it live</p>
<h1 class="mega mid">Six buttons. One phone call.</h1>
<p class="lede"><span class="cap">E</span>very button here is carried out on the presenter's laptop. The keys never leave it.</p></div></header>
<section class="alt"><div class="wrap">{RUN_CSS}<div id="rc"><p id="rcstate">Looking for the presenter's laptop.</p>
<div>{buttons}</div>
<div><span class="note">3 Call the owner: Sarvam's Test panel, 7/7 set, Call 1 number</span><span class="note">4 Pays by itself after APPROVED</span></div>
<div id="rclock" style="display:none;margin-top:8px"><input id="rckey" type="password" placeholder="presenter's key" autocomplete="off"><button class="pill" id="rcunlock">Unlock the buttons</button></div>
<p id="rcmsg" class="serif" style="margin:8px 0 0"></p>
<pre id="rcout"></pre></div></div></section>
<section class="ink"><div class="wrap"><p class="eyebrow">Why anyone can watch but only we can press</p><h2 data-r>A public pay button would defeat the point.</h2>
<p class="serif">The output above is public. The buttons need a key that only the presenter has, and the steps run on the presenter's
laptop, not on this server. Even then, pressing Run pays nothing: money moves only after the owner says the total on the phone.</p></div></section>
{RUN_JS}"""


def _console(body, token):
    """The run page and the presenter's laptop talk through here. A server without a token refuses."""
    if not token:
        return _reply(403, {"error": "this server has no token, so the run page is switched off"})
    if "command" in body:  # the run page: a button was pressed
        if body["command"] not in RUN_COMMANDS:
            return _reply(400, {"error": "unknown step"})
        if time.time() - CON["seen"] > 10:
            return _reply(409, {"error": "the presenter's laptop is not connected"})
        CON["queue"] = (CON["queue"] + [body["command"]])[-5:]
        return _reply(200, {"ok": True})
    CON["lines"] += [str(x)[:500] for x in (body.get("console") or [])][:500]  # the laptop: what its console printed
    drop = max(0, len(CON["lines"]) - 600)
    CON["lines"], CON["base"] = CON["lines"][drop:], CON["base"] + drop
    CON["busy"], CON["seen"] = bool(body.get("busy")), time.time()
    steps, CON["queue"] = CON["queue"], []
    return _reply(200, {"commands": steps})


VIEWS = {"home": ("PayRight: the agent that says no", _home), "evidence": ("PayRight: why we said no", _evidence),
         "how": ("PayRight: how it works", _how), "problem": ("PayRight: it already happened", _problem),
         "run": ("PayRight: run it live", _run)}


def page(data, view="home"):
    rs = rows(data)
    view = view if view in VIEWS else "home"
    version = hashlib.sha1(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:12]
    title, render = VIEWS[view]
    return shell(title, render(data, rs), view, version, str(data.get("updated") or ""))


def _event(body, rs):
    """One plain line for the activity log, from what this update says."""
    stage, ap = str(body.get("stage") or ""), body.get("approval") or {}
    sent = sum(r["state"] in ("SENT", "PAID", "FAILED", "REVERSED") for r in rs)
    paid = sum(r["state"] == "PAID" for r in rs)
    if stage == "calling":
        return "Calling the owner"
    if paid:
        return f"Cashfree confirmed {paid} of {sent} payment(s)"
    if sent:
        return f"Sent {sent} payment(s) to Cashfree through Relay"
    if ap:
        return "Owner's call: " + str(ap.get("reason") or "no answer")
    return f"Read and checked {len(rs)} bill(s): {sum(r['lane'] == 'STOP' for r in rs)} refused"


def handler(event, context=None):
    method, query, headers, body = _request(event)
    data = _load()
    if method == "POST":
        token = os.environ.get("PAYRIGHT_TOKEN", "")
        if token and headers.get("x-payright-token") != token:
            return _reply(403, {"error": "wrong token"})
        if isinstance(body, dict) and ("command" in body or "console" in body):
            return _console(body, token)
        if not isinstance(body, dict) or not isinstance(body.get("decisions"), list):
            return _reply(400, {"error": "expected {decisions: [...], ledger: [...]}"})
        now = datetime.now(IST)
        same_round = str(body.get("round") or "") == str(MEM.get("round") or "")
        events = list(MEM.get("events") or []) if same_round else []
        MEM.clear()
        MEM.update({"decisions": body["decisions"], "ledger": body.get("ledger") or [], "approval": body.get("approval"),
                    "stage": body.get("stage"), "facts": body.get("facts"), "round": body.get("round"),
                    "updated": now.strftime("%I:%M:%S %p IST")})
        text = _event(body, rows(MEM))
        if not events or events[-1].get("text") != text:
            events.append({"t": now.strftime("%I:%M:%S %p"), "text": text})
        MEM["events"] = events[-10:]
        try:
            json.dump(MEM, open(STORE, "w", encoding="utf-8"))
        except OSError:
            pass
        return _reply(200, {"ok": True, "invoices": len(MEM["decisions"])})
    if query.get("format") == "console":
        frm = str(query.get("from") or "0")
        frm = max(int(frm) if frm.isdigit() else 0, CON["base"])
        return _reply(200, {"lines": CON["lines"][frm - CON["base"]:], "next": CON["base"] + len(CON["lines"]),
                            "busy": CON["busy"], "online": time.time() - CON["seen"] < 10})
    if query.get("format") == "json":
        return _reply(200, {"rows": rows(data), "updated": data.get("updated"), "events": data.get("events") or []})
    return _reply(200, page(data, str(query.get("page") or "home")), "text/html")


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
    assert "Known trick: <b>A familiar vendor, a new account.</b>" in p                          # the refusal names its trick
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
    # the problem page: every case has a screenshot, a source link and what the checker does with it
    q = handler({"httpMethod": "GET", "queryStringParameters": {"page": "problem"}})["body"]
    assert "It already happened" in q and q.count('<article class="case"') == len(CASES) and "manipal_1cr.jpg" in q
    assert all(c[4].startswith("https://") and c[9] in ("digit", "other_account") for c in CASES)
    r = handler({"httpMethod": "GET", "queryStringParameters": {"page": "run"}})["body"]
    assert 'data-step="saved"' in r and "?page=run" in q and os.environ["PAYRIGHT_TOKEN"] not in r
    post = lambda b, t: handler({"httpMethod": "POST", "headers": {"x-payright-token": t}, "body": json.dumps(b)})  # noqa: E731
    con = lambda n=0: json.loads(handler({"httpMethod": "GET", "queryStringParameters": {"format": "console", "from": str(n)}})["body"])  # noqa: E731
    tok = os.environ["PAYRIGHT_TOKEN"]
    assert post({"command": "saved"}, "wrong")["statusCode"] == 403, "a press without the key was accepted"
    assert post({"command": "saved"}, tok)["statusCode"] == 409, "a press was queued with no laptop connected"
    assert json.loads(post({"console": ["hello"], "busy": False}, tok)["body"]) == {"commands": []}
    assert post({"console": ["x"]}, "wrong")["statusCode"] == 403 and con()["lines"] == ["hello"] and con()["online"]
    assert post({"command": "rm -rf"}, tok)["statusCode"] == 400 and post({"command": "saved"}, tok)["statusCode"] == 200
    assert json.loads(post({"console": ["two"], "busy": True}, tok)["body"]) == {"commands": ["saved"]}
    assert json.loads(post({"console": []}, tok)["body"]) == {"commands": []}, "a press was handed out twice"
    assert con(1) == {"lines": ["two"], "next": 2, "busy": False, "online": True}
    del os.environ["PAYRIGHT_TOKEN"]
    print("selftest ok")


lambda_handler = handler  # the console default is lambda_function.lambda_handler: paste this file as is


if __name__ == "__main__":
    selftest()

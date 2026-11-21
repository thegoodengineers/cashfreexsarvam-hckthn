"""The live board, "the agent that says no": every bill in a Pay / Ask / Stop lane.

  POST  body = {"decisions": [...], "ledger": [...], "approval": {...}}   (run.py sends this)
  GET                     -> the board
  GET   ?format=json      -> the same rows as JSON

Everything on the board comes from check.py's decisions and the ledger; nothing is typed in.
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
:root{--ground:#f6f3ec;--ink:#1c1b18;--soft:#6b675e;--line:#dcd6c8;--card:#fffdf8;
--pay:#1f6f4a;--stop:#a32f1d;--ask:#8a5a00;--wait:#4a5568;--bad:#fbe9e5;--ref:#eef4ee}
*{box-sizing:border-box}body{margin:0;background:var(--ground);color:var(--ink);
font:16px/1.45 ui-sans-serif,system-ui,-apple-system,'Segoe UI',sans-serif}
main{max-width:1240px;margin:0 auto;padding:22px 16px 48px}
h1{font:700 34px/1.08 Georgia,'Times New Roman',serif;margin:6px 0 6px;letter-spacing:-.01em}
.sub{color:var(--soft);font-size:15px;margin:0 0 14px;max-width:70ch}
.note{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--pay);
border-radius:8px;padding:10px 12px;margin:0 0 16px;font-size:15px}
.note.no{border-left-color:var(--stop)}
.lanes{display:grid;grid-template-columns:1fr;gap:18px}
@media(min-width:900px){.lanes{grid-template-columns:repeat(3,minmax(0,1fr));align-items:start}}
.lane h2{font:700 13px/1 ui-sans-serif,system-ui,sans-serif;letter-spacing:.1em;text-transform:uppercase;margin:0;color:#fff;
display:inline-block;padding:6px 10px;border-radius:6px;background:var(--wait)}
.lane.PAY h2{background:var(--pay)}.lane.ASK h2{background:var(--ask)}.lane.STOP h2{background:var(--stop)}
.total{font:700 30px/1.1 Georgia,serif;margin:10px 0 2px;font-variant-numeric:tabular-nums}
.what{color:var(--soft);font-size:13px;margin:0 0 12px}
@media(min-width:900px){.what{min-height:2.9em}}
.card{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--wait);border-radius:12px;margin:0 0 10px}
.card.PAY,.card.PAID{border-left-color:var(--pay)}.card.STOP{border-left-color:var(--stop)}
.card.ASK,.card.FAILED,.card.REVERSED{border-left-color:var(--ask)}
summary{list-style:none;cursor:pointer;padding:12px 14px}summary::-webkit-details-marker{display:none}
.top{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
.vendor{font:700 18px/1.2 Georgia,serif;overflow-wrap:anywhere}
.amt{font:700 18px/1.2 Georgia,serif;font-variant-numeric:tabular-nums;white-space:nowrap}
.meta{font:12.5px ui-monospace,Menlo,Consolas,monospace;color:var(--soft);margin:3px 0 8px;overflow-wrap:anywhere}
.chip{display:inline-block;font-weight:700;font-size:11.5px;letter-spacing:.05em;text-transform:uppercase;
padding:3px 8px;border-radius:999px;color:#fff;background:var(--wait)}
.chip.PAY,.chip.PAID{background:var(--pay)}.chip.STOP{background:var(--stop)}
.chip.ASK,.chip.FAILED,.chip.REVERSED{background:var(--ask)}
.hint{float:right;font-size:12px;color:var(--soft);padding-top:3px}details[open] .hint{display:none}
.body{padding:0 14px 14px;border-top:1px dashed var(--line)}
.why{margin:10px 0 0;padding:0;list-style:none;font-size:15px}.why li{margin:4px 0}
.ev{margin:12px 0 0}.evk{font-size:11.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--soft);margin:0 0 5px}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.pair div{border-radius:8px;padding:8px 10px;min-width:0}
.pair span{display:block;font-size:12px;color:var(--soft)}
.pair b{display:block;font:700 15px/1.3 ui-monospace,Menlo,Consolas,monospace;overflow-wrap:anywhere}
.bad{background:var(--bad);border:1px solid #e3b3a8}.bad b{color:var(--stop)}
.ref{background:var(--ref);border:1px solid #c5d6c6}
.none{color:var(--soft);font-size:14px;border:1px dashed var(--line);border-radius:12px;padding:14px}
footer{color:var(--soft);font-size:12px;margin-top:22px}
"""

# Reloads only when the data changed, and keeps the bills you opened open.
JS = """<script>(function(){var v=document.body.getAttribute('data-v');setInterval(function(){
fetch(location.href,{cache:'no-store'}).then(function(r){return r.text()}).then(function(t){
var d=new DOMParser().parseFromString(t,'text/html');var n=d.body&&d.body.getAttribute('data-v');
if(!n||n===v)return;var open=[].map.call(document.querySelectorAll('details[open]'),function(e){return e.id});
document.querySelector('main').innerHTML=d.querySelector('main').innerHTML;v=n;
open.forEach(function(i){var e=document.getElementById(i);if(e)e.open=true})}).catch(function(){})},4000)})();</script>"""


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
    inside = (f'<ul class="why">{why}</ul>' if why else "") + ev + (f'<p class="meta" style="margin-top:10px">{extra}</p>' if extra else "")
    hint = '<span class="hint">tap for the evidence</span>' if r["evidence"] else ""
    return (f'<details class="card {e(r["state"])}" id="{r["id"]}"><summary><div class="top">'
            f'<span class="vendor">{e(str(r["vendor"] or "Unknown vendor"))}</span><span class="amt">{_money(r["amount"])}</span></div>'
            f'<div class="meta">{meta}</div><span class="chip {e(r["state"])}">{e(LABEL.get(r["state"], r["state"]))}</span>{hint}</summary>'
            f'{"<div class=body>" + inside + "</div>" if inside else ""}</details>')


def page(data):
    e = html.escape
    rs = rows(data)
    version = hashlib.sha1(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:12]
    ap = data.get("approval") or {}
    note = ""
    if ap:
        cls = "" if ap.get("approved_transfer_ids") else " no"
        lang = f" ({e(str(ap['language']))})" if ap.get("language") else ""
        note = f'<div class="note{cls}"><b>Owner\'s call{lang}:</b> {e(str(ap.get("reason") or ""))}</div>'
    lanes = []
    for key, name, what in LANES:
        mine = [r for r in rs if r["lane"] == key]
        total = sum(r["amount"] or 0 for r in mine)
        paid = sum(r["amount"] or 0 for r in mine if r["state"] == "PAID")
        tail = f" {_money(paid)} confirmed paid by Cashfree." if key == "PAY" and mine else ""
        cards = "".join(_card(r) for r in mine) or '<p class="none">Nothing here.</p>'
        lanes.append(f'<section class="lane {key}"><h2>{name} · {len(mine)}</h2><p class="total">{_money(total)}</p>'
                     f'<p class="what">{what}{tail}</p>{cards}</section>')
    empty = '<p class="sub">No batch has been run yet.</p>' if not rs else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PayRight: the agent that says no</title><style>{CSS}</style></head><body data-v="{version}"><main>
<h1>The agent that says no.</h1>
<p class="sub">A model reads each bill. Plain code decides. Money moves only after the owner says the amount himself,
and a bill counts as paid only when Cashfree confirms it.</p>
{note}{empty}<div class="lanes">{"".join(lanes)}</div>
<footer>Sandbox only, synthetic data. Updated {e(str(data.get("updated") or "never"))}. Updates by itself.</footer>
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
                    "approval": body.get("approval"), "updated": datetime.now(IST).strftime("%I:%M:%S %p IST")})
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
    del os.environ["PAYRIGHT_TOKEN"]
    print("selftest ok")


lambda_handler = handler  # the console default is lambda_function.lambda_handler: paste this file as is


if __name__ == "__main__":
    selftest()

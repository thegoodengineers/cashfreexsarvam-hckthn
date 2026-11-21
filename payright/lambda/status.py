"""Lambda <ID>-payright-status: one page judges open on their phones.

  POST  body = {"decisions": [...], "ledger": [...], "approval": {...}}   (run.py sends this)
  GET                     -> the page: every invoice with PAY / ASK / STOP, the reason, transfer status
  GET   ?format=json      -> the same data as JSON

Set PAYRIGHT_TOKEN in the Lambda's environment and STATUS_TOKEN in payright/.env to the same
value, so only our laptop can update the page. Put the call link in payright/.env as STATUS_URL.

The last copy is kept in memory and /tmp, which is enough for a demo.
No full bank account number is ever shown: last four digits only.
Single file, standard library only. Paste it into the console editor as lambda_function.py
(the default handler name works), or upload it as status.py with handler status.handler.
"""
import base64
import html
import json
import os
import time

STORE = "/tmp/payright_status.json"
MEM = {}
SENT = {"SENT": "Sending to Cashfree", "ACCEPTED": "Sent to Cashfree through Relay",
        "NOT_SENT": "Not sent, will retry with the same transfer id",
        "UNKNOWN": "Sent, waiting for confirmation. Not resent."}
LABEL = {"PAY": "Pay", "ASK": "Ask owner", "STOP": "Stopped", "LATER": "Later", "PAID": "Paid"}


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


def rows(data):
    """Decisions joined with the ledger. A paid invoice shows as PAID, not as a refusal."""
    ledger = {r["transfer_id"]: r for r in data.get("ledger") or []}
    seen, out = set(), []
    for d in data.get("decisions") or []:
        led = ledger.get(d.get("transfer_id"))
        status, reasons, transfer = d["status"], list(d.get("reasons") or []), ""
        first_for_transfer = d.get("transfer_id") not in seen
        if led and first_for_transfer and (status == "PAY" or (
                status == "STOP" and len(reasons) == 1 and "has already been" in reasons[0]
                and led.get("file") == d.get("file"))):
            status, reasons = "PAID", []
            transfer = SENT.get(led["status"], led["status"])
            seen.add(d.get("transfer_id"))
        acct = str(d.get("bank_account") or "")
        out.append({"status": status, "invoice_no": d.get("invoice_no"), "vendor": d.get("vendor"),
                    "amount": d.get("amount"), "reasons": reasons, "transfer": transfer,
                    "transfer_id": d.get("transfer_id") if status == "PAID" else None,
                    "account": ("····" + acct[-4:]) if acct and status in ("PAY", "PAID") else "",
                    "days_left": d.get("days_left"), "file": d.get("file")})
    return out


def _money(x):
    if x is None:
        return "?"
    s, neg = f"{abs(x):.0f}", x < 0
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:  # Indian grouping: 1,20,500
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ("-" if neg else "") + "₹" + ",".join(parts + [tail])


CSS = """
:root{--ground:#f6f3ec;--ink:#1c1b18;--soft:#6b675e;--line:#dcd6c8;--card:#fffdf8;
--pay:#1f6f4a;--stop:#a32f1d;--ask:#8a5a00;--later:#4a5568}
*{box-sizing:border-box}body{margin:0;background:var(--ground);color:var(--ink);
font:16px/1.45 Georgia,'Times New Roman',serif}
main{max-width:720px;margin:0 auto;padding:20px 16px 48px}
h1{font-size:30px;line-height:1.1;margin:8px 0 4px;letter-spacing:-.01em}
.sub{color:var(--soft);font:14px/1.4 ui-sans-serif,system-ui,sans-serif;margin:0 0 18px}
.sum{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:0 0 8px}
.sum div{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.sum b{display:block;font-size:26px;line-height:1.1}
.sum span{display:block;font:12px ui-sans-serif,system-ui,sans-serif;color:var(--soft);text-transform:uppercase;letter-spacing:.06em}
.sum i{display:block;font:normal 13px ui-sans-serif,system-ui,sans-serif;color:var(--soft)}
.note{font:14px/1.4 ui-sans-serif,system-ui,sans-serif;background:var(--card);border:1px solid var(--line);
border-left:4px solid var(--pay);border-radius:8px;padding:10px 12px;margin:10px 0 18px}
.note.no{border-left-color:var(--stop)}
.inv{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 14px 12px;margin:0 0 10px;
border-left:5px solid var(--later)}
.inv.PAY,.inv.PAID{border-left-color:var(--pay)}.inv.STOP{border-left-color:var(--stop)}.inv.ASK{border-left-color:var(--ask)}
.top{display:flex;justify-content:space-between;align-items:baseline;gap:12px}
.vendor{font-size:19px;font-weight:700;overflow-wrap:anywhere}
.amt{font-size:19px;font-variant-numeric:tabular-nums;white-space:nowrap}
.meta{font:13px ui-monospace,Menlo,Consolas,monospace;color:var(--soft);margin:2px 0 8px;overflow-wrap:anywhere}
.chip{display:inline-block;font:700 12px ui-sans-serif,system-ui,sans-serif;letter-spacing:.06em;text-transform:uppercase;
padding:3px 8px;border-radius:999px;color:#fff;background:var(--later)}
.chip.PAY,.chip.PAID{background:var(--pay)}.chip.STOP{background:var(--stop)}.chip.ASK{background:var(--ask)}
.why{font:15px/1.45 ui-sans-serif,system-ui,sans-serif;margin:8px 0 0;padding:0;list-style:none}
.why li{margin:4px 0}.tr{font:14px ui-sans-serif,system-ui,sans-serif;color:var(--pay);margin:8px 0 0}
footer{color:var(--soft);font:12px ui-sans-serif,system-ui,sans-serif;margin-top:22px}
"""


def page(data):
    e = html.escape
    rs = rows(data)
    n = lambda *s: sum(r["status"] in s for r in rs)
    paid = sum(r["amount"] or 0 for r in rs if r["status"] == "PAID")
    to_pay = sum(r["amount"] or 0 for r in rs if r["status"] == "PAY")
    ap = data.get("approval") or {}
    note = ""
    if ap:
        cls = "" if ap.get("approved_transfer_ids") else " no"
        note = f'<div class="note{cls}"><b>Owner\'s call:</b> {e(str(ap.get("reason") or ""))}</div>'
    cards = []
    for r in rs:
        why = "".join(f"<li>{e(str(x))}</li>" for x in r["reasons"])
        meta = " · ".join(x for x in (
            f"Invoice {e(str(r['invoice_no']))}" if r["invoice_no"] else "",
            f"account {e(r['account'])}" if r["account"] else "",
            f"{r['days_left']} days to deadline" if isinstance(r["days_left"], int) and r["status"] in ("PAY", "LATER") else "",
            e(str(r["file"])) if r["file"] else "") if x)
        tr = f'<p class="tr">{e(r["transfer"])} · {e(str(r["transfer_id"]))}</p>' if r["transfer"] else ""
        cards.append(
            f'<section class="inv {e(r["status"])}"><div class="top"><span class="vendor">{e(str(r["vendor"] or "Unknown vendor"))}</span>'
            f'<span class="amt">{_money(r["amount"])}</span></div><div class="meta">{meta}</div>'
            f'<span class="chip {e(r["status"])}">{LABEL.get(r["status"], e(r["status"]))}</span>'
            f'{"<ul class=why>" + why + "</ul>" if why else ""}{tr}</section>')
    empty = '<p class="sub">No batch has been run yet.</p>' if not rs else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="6">
<title>PayRight: this week's bills</title><style>{CSS}</style></head><body><main>
<h1>Pay the right bill, to the right person.</h1>
<p class="sub">A model reads each invoice. Plain code decides. Money moves only after the owner says the amount himself.</p>
<div class="sum"><div><b>{n("PAID")}</b><span>Paid</span><i>{_money(paid)}</i></div>
<div><b>{n("PAY", "LATER")}</b><span>To pay</span><i>{_money(to_pay)}</i></div>
<div><b>{n("STOP", "ASK")}</b><span>Stopped</span><i>or asked</i></div></div>
{note}{empty}{"".join(cards)}
<footer>Sandbox only, synthetic data. Updated {e(str(data.get("updated") or "never"))}. This page refreshes by itself.</footer>
</main></body></html>"""


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
                    "approval": body.get("approval"), "updated": time.strftime("%H:%M:%S UTC", time.gmtime())})
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
    D = [{"status": "PAY", "invoice_no": "DH-0101", "vendor": "Doe <Hardware>", "amount": 120500.0, "reasons": [],
          "transfer_id": "T1", "bank_account": "026291800001191", "days_left": 6, "file": "a.png"},
         {"status": "STOP", "invoice_no": "HE-310", "vendor": "Hope Electricals", "amount": 23600.0, "transfer_id": "T2",
          "reasons": ["The bank account on this invoice is not the account we have on file."], "bank_account": "388108022658"}]
    os.environ["PAYRIGHT_TOKEN"] = "s3"
    post = {"httpMethod": "POST", "body": json.dumps({"decisions": D, "ledger": []})}
    assert handler(post)["statusCode"] == 403
    assert handler({**post, "headers": {"X-PayRight-Token": "s3"}})["statusCode"] == 200
    p = handler({"httpMethod": "GET"})["body"]
    assert "Doe &lt;Hardware&gt;" in p and "₹1,20,500" in p and "····1191" in p and "026291800001191" not in p
    assert "388108022658" not in p and "····2658" not in p        # a stopped bill shows no account at all
    led = [{"transfer_id": "T1", "status": "ACCEPTED", "file": "a.png"}]
    handler({"decisions": D, "ledger": led, "token": "s3"})         # direct invoke
    r = json.loads(handler({"httpMethod": "GET", "queryStringParameters": {"format": "json"}})["body"])["rows"]
    assert r[0]["status"] == "PAID" and "Relay" in r[0]["transfer"] and r[1]["status"] == "STOP"
    # second run of the same batch: check.py says STOP "has already been accepted"; the page still says PAID
    again = [{**D[0], "status": "STOP", "reasons": ["Invoice number DH-0101 from Doe has already been accepted."]},
             {**D[0], "file": "dup.png", "status": "STOP", "reasons": ["Invoice number DH-0101 from Doe has already been accepted."]}]
    handler({"decisions": again, "ledger": led, "token": "s3"})
    r = json.loads(handler({"httpMethod": "GET", "queryStringParameters": {"format": "json"}})["body"])["rows"]
    assert [x["status"] for x in r] == ["PAID", "STOP"]
    del os.environ["PAYRIGHT_TOKEN"]
    print("selftest ok")


lambda_handler = handler  # the console default is lambda_function.lambda_handler: paste this file as is


if __name__ == "__main__":
    selftest()

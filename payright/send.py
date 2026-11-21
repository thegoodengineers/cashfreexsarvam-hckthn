"""Send approved payments to the Relay agent: one event per PAY row in decisions.json.

  python send.py --dry-run     print the events, send nothing
  python send.py               send the rows the owner approved (this triggers sandbox payouts)
  python send.py --retry       resend approved rows that never left this machine, same transfer_id
  python send.py --confirm     ask Cashfree what happened to each transfer and note it in the ledger
  python send.py --selftest

Nothing is sent without the owner's approval: send.py uses up the approval that approve.py
wrote (approval.json), and only for the exact batch it was given for.
A row counts as PAID only when Cashfree says SUCCESS (--confirm). "Relay accepted the event"
is not a payment.

A retry must never become a second payment. Three layers, any one is enough:
  1. Write-ahead ledger. The row is saved to ledger.json as SENT *before* the POST.
     If we crash mid-send the row is already there, and check.py refuses anything
     in the ledger on the next run.
  2. send.py refuses any transfer_id (or vendor + invoice) already in the ledger,
     whatever its status.
  3. transfer_id is derived from the invoice in check.py, not generated per attempt,
     so even a forced resend reaches Cashfree with the same id.
     (Cashfree docs: a repeated transfer_id is rejected as DUPLICATE_TRANSFER. Not tested by us.)

Bank details come from vendors.json only. A decision whose account differs from the
vendor file is refused: decisions.json is treated as untrusted input.
"""
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

import requests

HERE = Path(__file__).parent
FIELDS = ("invoice_no", "vendor", "account_holder", "phone", "email", "bank_account", "ifsc",
          "address", "city", "state", "pincode", "beneficiary_id", "amount", "transfer_id")
# Synthetic contact details for sandbox vendors that have none on file.
DEFAULTS = {"phone": "9999999999", "address": "Test address", "city": "Coimbatore",
            "state": "Tamil Nadu", "pincode": "641001"}


def load_env(here=HERE):
    for line in (here / ".env").read_text().splitlines() if (here / ".env").exists() else []:
        k, _, v = line.partition("=")
        if k.strip() and not k.strip().startswith("#"):
            os.environ.setdefault(k.strip(), v.strip())


def load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save_ledger(path, rows):
    """Atomic: write a temp file, flush to disk, then swap. A crash never leaves half a ledger."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def batch_id(decisions):
    """Identity of exactly this set of payments. An approval is bound to it."""
    pay = sorted(f"{d['transfer_id']}:{round(d['amount'] * 100)}" for d in decisions if d["status"] == "PAY")
    return "B" + hashlib.sha1("|".join(pay).encode()).hexdigest()[:12]


def event(dec, v):
    """The Relay agent maps exactly these fields. Bank details are the vendor file's."""
    bid = re.sub(r"[^A-Za-z0-9]", "", str(v["id"]))
    data = {
        "invoice_no": dec["invoice_no"], "vendor": v["name"],
        "account_holder": v.get("account_holder") or v["name"],
        "phone": v.get("phone") or DEFAULTS["phone"],
        "email": v.get("email") or f"accounts.{bid.lower()}@example.com",
        "bank_account": v["bank_account"], "ifsc": v["ifsc"],
        "address": v.get("address") or DEFAULTS["address"], "city": v.get("city") or DEFAULTS["city"],
        "state": v.get("state") or DEFAULTS["state"], "pincode": v.get("pincode") or DEFAULTS["pincode"],
        "beneficiary_id": bid, "amount": dec["amount"], "transfer_id": dec["transfer_id"],
    }
    assert tuple(data) == FIELDS
    return {"data": data}


def refuse(dec, v, ledger):
    """-> reason this row must not be sent, or None."""
    if v is None:
        return "vendor is not in vendors.json"
    if not dec.get("transfer_id") or not dec.get("amount") or dec["amount"] <= 0:
        return "no transfer id or amount"
    if (dec.get("bank_account"), dec.get("ifsc")) != (v["bank_account"], v["ifsc"]):
        return "bank details in decisions.json differ from vendors.json"
    for row in ledger:
        if row["transfer_id"] == dec["transfer_id"] or (
                row["vendor_id"] == dec["vendor_id"] and row["invoice_key"] == dec["invoice_key"]):
            return f"already in the ledger as {row['status']}"
    return None


def post_event(row, body, url, post):
    """POST one event and set the row's final status. Only NOT_SENT may ever be retried."""
    try:
        r = post(url, json=body, timeout=30)
    except (requests.ConnectionError, requests.ConnectTimeout) as e:
        if isinstance(e, requests.ReadTimeout):
            row.update(status="UNKNOWN", note="timed out waiting for Relay; check Relay's Runs tab, do not resend")
        else:
            row.update(status="NOT_SENT", note=f"could not reach Relay: {type(e).__name__}")
        return
    except requests.RequestException as e:
        row.update(status="UNKNOWN", note=f"{type(e).__name__}; check Relay's Runs tab, do not resend")
        return
    row["http"] = r.status_code
    if 200 <= r.status_code < 300:
        row.update(status="ACCEPTED", note=(r.text or "")[:200])
    elif r.status_code in (401, 403, 404):
        row.update(status="NOT_SENT", note=f"Relay refused the request ({r.status_code}): {(r.text or '')[:160]}")
    else:
        row.update(status="UNKNOWN", note=f"Relay answered {r.status_code}; check the Runs tab, do not resend")


def send(decisions, vendors, ledger_path, url, post=requests.post, dry_run=False, approval=None, out=print):
    """Send every PAY row once. Returns the list of events that were (or would be) sent."""
    by_id = {v["id"]: v for v in vendors}
    ledger = load(ledger_path, [])
    bid, sent = batch_id(decisions), []
    if not dry_run and not approval:
        out("REFUSED  no owner approval, so nothing is sent. Run approve.py first.")
        return []
    for dec in decisions:
        if dec["status"] != "PAY":
            continue
        v = by_id.get(dec.get("vendor_id"))
        why = refuse(dec, v, ledger)
        if why:
            out(f"SKIP  {str(dec['invoice_no']):14} {why}")
            continue
        body = event(dec, v)
        if dry_run:
            out("WOULD SEND " + json.dumps(body, ensure_ascii=False))
            sent.append(body)
            continue
        row = {"transfer_id": dec["transfer_id"], "vendor_id": dec["vendor_id"], "vendor": v["name"],
               "invoice_no": dec["invoice_no"], "invoice_key": dec["invoice_key"], "amount": dec["amount"],
               "date": dec.get("date"), "file": dec.get("file"), "status": "SENT", "batch_id": bid,
               "approval": approval, "sent_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        ledger.append(row)
        save_ledger(ledger_path, ledger)        # write-ahead: on disk before any money can move
        post_event(row, body, url, post)
        save_ledger(ledger_path, ledger)
        sent.append(body)
        out(f"{row['status']:9} {str(dec['invoice_no']):14} {v['name'][:28]:28} {dec['amount']:>10.0f}  {dec['transfer_id']}")
    return sent


def retry(vendors, ledger_path, url, post=requests.post, out=print):
    """Resend rows that never reached Relay. Same transfer_id, so it is still one payment."""
    by_id = {v["id"]: v for v in vendors}
    ledger = load(ledger_path, [])
    again = [r for r in ledger if r["status"] == "NOT_SENT" and r.get("approval")]
    for row in again:
        v = by_id[row["vendor_id"]]
        body = event({**row, "bank_account": v["bank_account"], "ifsc": v["ifsc"]}, v)
        row.update(status="SENT", sent_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        save_ledger(ledger_path, ledger)
        post_event(row, body, url, post)
        save_ledger(ledger_path, ledger)
        out(f"{row['status']:9} {str(row['invoice_no']):14} {row['transfer_id']}")
    return again


PAYOUTS = "https://sandbox.cashfree.com/payout/transfers"   # Cashfree Payouts v2, sandbox only
OUTCOME = {"SUCCESS": "PAID", "FAILED": "FAILED", "REJECTED": "FAILED", "MANUALLY_REJECTED": "FAILED",
           "REVERSED": "REVERSED"}


def confirm(ledger_path, client_id, secret, get=requests.get, out=print):
    """Ask Cashfree what really happened to each transfer and write it in the ledger as `payout`:
    PAID (Cashfree says SUCCESS), FAILED, REVERSED, PENDING or NOT_FOUND. Paid rows are asked
    again too, because a payout that looked successful can still come back reversed.
    -> number of rows still waiting. API shape read from Cashfree's docs, not yet run by us."""
    ledger = load(ledger_path, [])
    h = {"x-client-id": client_id, "x-client-secret": secret, "x-api-version": "2024-01-01"}
    waiting = 0
    for row in ledger:
        if row["status"] == "NOT_SENT":
            continue
        try:
            r = get(PAYOUTS, params={"transfer_id": row["transfer_id"]}, headers=h, timeout=20)
        except requests.RequestException as e:
            out(f"could not reach Cashfree for {row['transfer_id']}: {type(e).__name__}")
            waiting += 1
            continue
        if r.status_code == 404:
            row["payout"], row["payout_note"] = "NOT_FOUND", "Cashfree has no transfer with this id yet"
            waiting += 1
        elif r.status_code == 200:
            d = r.json()
            d = d.get("data", d) if isinstance(d, dict) else {}
            st = str(d.get("status") or "").upper()
            row.update(payout=OUTCOME.get(st, "PENDING"), payout_status=st, payout_code=d.get("status_code"),
                       utr=d.get("transfer_utr"), cf_transfer_id=d.get("cf_transfer_id"),
                       confirmed_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
            row.pop("payout_note", None)
            waiting += row["payout"] == "PENDING"
        else:
            text = r.text or ""
            out(f"Cashfree answered {r.status_code} for {row['transfer_id']}: {text[:400]}")
            ips = re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", text)
            if "whitelist" in text.lower() or (r.status_code == 403 and ips):
                out("  -> this laptop's IP is not whitelisted for Payouts"
                    + (f". IP to whitelist: {', '.join(sorted(set(ips)))}" if ips else "")
                    + "  (Payouts dashboard -> Developers -> Two-Factor Authentication -> IP whitelist)")
                return sum(x["status"] != "NOT_SENT" for x in ledger)   # same answer for every row: stop asking
            waiting += 1
            continue
        out(f"{row.get('payout', '?'):9} {str(row['invoice_no']):14} {row['transfer_id']}  "
            f"{row.get('payout_status') or ''} {row.get('utr') or ''}")
    save_ledger(ledger_path, ledger)
    return waiting


def payout_keys():
    return os.environ.get("CASHFREE_PAYOUT_CLIENT_ID", ""), os.environ.get("CASHFREE_PAYOUT_CLIENT_SECRET", "")


def main(argv):
    if "--selftest" in argv:
        return selftest()
    load_env()
    vendors = load(HERE / "vendors.json", [])
    url = os.environ.get("RELAY_WEBHOOK_URL", "")
    dry = "--dry-run" in argv
    if "--confirm" in argv:
        cid, sec = payout_keys()
        if not (cid and sec):
            sys.exit("Set CASHFREE_PAYOUT_CLIENT_ID and CASHFREE_PAYOUT_CLIENT_SECRET (test mode) in payright/.env")
        return print(f"{confirm(HERE / 'ledger.json', cid, sec)} transfer(s) still waiting for Cashfree")
    if not dry and "--retry" not in argv and not (HERE / "approval.json").exists():
        sys.exit("NOT SENT  There is no owner approval on file. Run approve.py first.")
    if not dry and not url:
        sys.exit("Set RELAY_WEBHOOK_URL in payright/.env (or use --dry-run)")
    if "--retry" in argv:
        n = len(retry(vendors, HERE / "ledger.json", url))
        return print(f"retried {n} row(s)")
    decisions = load(HERE / "decisions.json", None)
    if decisions is None:
        sys.exit("No decisions.json. Run: python check.py invoices.json")
    approval = None
    if not dry:  # the owner's approval is used up here, before any event leaves
        import approve  # imported late: approve.py imports this file
        ids, approval = approve.use_latest(decisions)
        if ids is None:
            sys.exit("NOT SENT  " + approval)
        decisions = [d if d["transfer_id"] in ids else {**d, "status": "ASK"} for d in decisions]
    sent = send(decisions, vendors, HERE / "ledger.json", url, dry_run=dry, approval=approval)
    total = sum(e["data"]["amount"] for e in sent)
    print(f"{'would send' if dry else 'sent'} {len(sent)} event(s), total {total:.0f}. batch {batch_id(decisions)}")


def selftest():
    import check  # the real checker, so this proves the two files agree

    class Reply:
        status_code, text = 200, "ok"

    vendors = load(HERE / "vendors.json", [])
    invoices = load(HERE / "sample_invoices.json", [])
    quiet = lambda *_: None
    with tempfile.TemporaryDirectory() as d:
        ledger_path = Path(d) / "ledger.json"
        calls = []
        ok = lambda url, json, timeout: calls.append(json) or Reply()

        # 1. run the batch twice: the second run pays nothing
        decisions = check.plan(invoices, vendors, [], 100000)
        first = send(decisions, vendors, ledger_path, "http://relay.test", approval="A-test", post=ok, out=quiet)
        assert len(first) == 2 and len(calls) == 2, calls
        assert all(tuple(e["data"]) == FIELDS for e in first)
        again = check.plan(invoices, vendors, load(ledger_path, []), 100000)
        assert [x["status"] for x in again].count("PAY") == 0, again    # check.py refuses them
        assert send(again, vendors, ledger_path, "http://relay.test", approval="A-test", post=ok, out=quiet) == []
        assert send(decisions, vendors, ledger_path, "http://relay.test", approval="A-test", post=ok, out=quiet) == []  # stale decisions too
        assert len(calls) == 2

        # 2. crash in the middle of the POST: the row is already on disk, a rerun sends nothing
        ledger_path.unlink()
        def crash(url, json, timeout):
            raise KeyboardInterrupt
        try:
            send(decisions, vendors, ledger_path, "http://relay.test", approval="A-test", post=crash, out=quiet)
        except KeyboardInterrupt:
            pass
        rows = load(ledger_path, [])
        assert len(rows) == 1 and rows[0]["status"] == "SENT"
        calls.clear()
        send(decisions, vendors, ledger_path, "http://relay.test", approval="A-test", post=ok, out=quiet)
        assert [c["data"]["transfer_id"] for c in calls] == [decisions[1]["transfer_id"]]  # only the untouched one

        # 3. Relay unreachable: NOT_SENT, and --retry reuses the same transfer id exactly once
        ledger_path.unlink()
        def down(url, json, timeout):
            raise requests.ConnectionError("no route")
        send(decisions, vendors, ledger_path, "http://relay.test", approval="A-test", post=down, out=quiet)
        assert {r["status"] for r in load(ledger_path, [])} == {"NOT_SENT"}
        calls.clear()
        retry(vendors, ledger_path, "http://relay.test", post=ok, out=quiet)
        retry(vendors, ledger_path, "http://relay.test", post=ok, out=quiet)
        assert sorted(c["data"]["transfer_id"] for c in calls) == sorted(d["transfer_id"] for d in decisions if d["status"] == "PAY")

        # 4. a timeout is UNKNOWN and is never resent
        ledger_path.unlink()
        def slow(url, json, timeout):
            raise requests.ReadTimeout("slow")
        send(decisions, vendors, ledger_path, "http://relay.test", approval="A-test", post=slow, out=quiet)
        calls.clear()
        retry(vendors, ledger_path, "http://relay.test", post=ok, out=quiet)
        assert calls == [] and {r["status"] for r in load(ledger_path, [])} == {"UNKNOWN"}

        # 5. tampered decisions: an account that is not the vendor file's is refused
        ledger_path.unlink()
        bad = [{**decisions[0], "bank_account": "026291800001190"}]
        calls.clear()
        assert send(bad, vendors, ledger_path, "http://relay.test", approval="A-test", post=ok, out=quiet) == [] and calls == []

        # 6. no owner approval, no payment: send() itself refuses, the ledger is not even touched
        ledger_path.unlink(missing_ok=True)
        calls.clear()
        assert send(decisions, vendors, ledger_path, "http://relay.test", post=ok, out=quiet) == []
        assert calls == [] and not ledger_path.exists()

        # 7. paid means Cashfree said SUCCESS. Relay accepting the event is not a payment.
        send(decisions, vendors, ledger_path, "http://relay.test", approval="A-test", post=ok, out=quiet)
        assert all("payout" not in r for r in load(ledger_path, []))

        class CF:
            def __init__(self, code, body):
                self.status_code, self._b, self.text = code, body, str(body)

            def json(self):
                return self._b
        t1, t2 = [r["transfer_id"] for r in load(ledger_path, [])]
        answers = {t1: CF(200, {"transfer_id": t1, "status": "SUCCESS", "transfer_utr": "UTR1"}), t2: CF(404, {})}
        cf = lambda url, params, headers, timeout: answers[params["transfer_id"]]
        assert confirm(ledger_path, "id", "secret", get=cf, out=quiet) == 1
        assert [r.get("payout") for r in load(ledger_path, [])] == ["PAID", "NOT_FOUND"]
        answers = {t1: CF(200, {"data": {"status": "REVERSED"}}), t2: CF(200, {"status": "PENDING"})}
        confirm(ledger_path, "id", "secret", get=cf, out=quiet)          # a paid transfer can still come back
        said = []
        blocked = lambda url, params, headers, timeout: CF(403, '{"message":"IP not whitelisted. Your IP is 219.65.10.20"}')
        assert confirm(ledger_path, "id", "secret", get=blocked, out=said.append) == 2
        assert len(said) == 2 and "219.65.10.20" in said[1]               # says which IP, and asks only once
        assert [r.get("payout") for r in load(ledger_path, [])] == ["REVERSED", "PENDING"]
        calls.clear()
        retry(vendors, ledger_path, "http://relay.test", post=ok, out=quiet)
        assert calls == []                                                 # a reversal is never re-sent by itself

        # 8. the money goes to the account on file even if the event is built from a doctored row
        assert event({**decisions[0], "bank_account": "000"}, vendors[0])["data"]["bank_account"] == vendors[0]["bank_account"]
    print("selftest ok: batch run twice pays once; crash, outage, timeout and tampering never pay twice; "
          "no approval, no payment; paid only when Cashfree confirms")


if __name__ == "__main__":
    main(sys.argv)

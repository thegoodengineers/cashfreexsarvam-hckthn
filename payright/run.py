"""One command for demo day: read -> check -> owner approves by phone -> pay.

  python run.py <folder of invoice images>  [ta-IN] [--cash 100000]
  python run.py invoices.json                         skip reading, start from extracted invoices

  --dry-run      read and check, show the call and the events, place no call, send nothing
  --no-pay       read and check only (table and score line)
  --latest       place no call: wait for a call started by hand from Sarvam's Test panel
                 (after this run began) and read the owner's answer from it
  --fake fake_answer.json
                 stage fallback: use the answer in that file instead of a call. Run it on
                 invoices.json so the invoices are not read again:
                   python run.py invoices.json --cash 100000 --fake fake_answer.json
  python run.py --refresh
                 ask Cashfree what happened to each transfer and update the board

Score line: with invoice_answer_key.json (or expected.json = {"file.png": "PAY" | "STOP"} in the
folder) the run prints traps caught and good invoices wrongly blocked. Files that are not in the
key, such as the judges' fresh batch, only get the counts.
"""
import json
import os
import sys
import uuid  # noqa: F401  (used by the call path)
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import approve
import check
import send

HERE = Path(__file__).parent
IMAGES = (".png", ".jpg", ".jpeg", ".pdf")


def read_folder(folder, language):
    import extract
    key = os.environ.get("SARVAM_API_KEY") or sys.exit("Set SARVAM_API_KEY in payright/.env")
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGES)
    if not files:
        sys.exit(f"No invoice images in {folder}")
    print(f"reading {len(files)} invoice(s) with Sarvam Vision...")

    def one(p):
        try:
            return extract.read(p, key, language)
        except Exception as e:  # one unreadable file must not stop the batch; it becomes an ASK
            return {"file": p.name, "unsure_fields": [f"whole invoice (reader error: {type(e).__name__})"]}
    with ThreadPoolExecutor(4) as pool:  # a few at a time keeps us under Sarvam's per-minute limit
        invoices = list(pool.map(one, files))
    (HERE / "invoices.json").write_text(json.dumps(invoices, ensure_ascii=False, indent=2), encoding="utf-8")
    return invoices


def publish(decisions, ledger_path, approval=None, stage=None):
    """Update the live board. `stage` tells it where the run is: checked, calling, answered, sent,
    confirmed. Never stops the run if the board is unreachable."""
    url = os.environ.get("STATUS_URL")
    if not url:
        return
    try:
        import requests
        requests.post(url, timeout=10, headers={"x-payright-token": os.environ.get("STATUS_TOKEN", "")},
                      json={"decisions": decisions, "ledger": send.load(ledger_path, []), "approval": approval,
                            "stage": stage, "round": check.demo_round().lstrip("|")})
    except Exception as e:
        print(f"(board not updated: {type(e).__name__})")


def settle(decisions, ledger_path, approval=None, tries=6, wait_s=5):
    """Ask Cashfree about each transfer a few times and update the board. Paid means Cashfree said so."""
    cid, sec = send.payout_keys()
    if not (cid and sec):
        return print("(no Cashfree Payouts keys in .env: the board shows 'sent, waiting for Cashfree'. "
                     "Check the Payouts test dashboard.)")
    import time
    lines = []
    for i in range(tries):
        lines = []  # only the last check is shown: right after sending, Cashfree has not registered the transfers yet
        waiting = send.confirm(ledger_path, cid, sec, out=lines.append)
        publish(decisions, ledger_path, approval, stage="sent" if waiting else "confirmed")
        if not waiting or any("not whitelisted" in x for x in lines) or i == tries - 1:
            break
        time.sleep(wait_s)
    for line in lines:  # the ledger keeps the value NOT_FOUND; on screen it reads as what it means
        print("waiting for Cashfree  " + line[len("NOT_FOUND"):].strip() if line.startswith("NOT_FOUND") else line)
    rows = send.load(ledger_path, [])
    words = {"NOT_FOUND": "waiting for Cashfree", "PENDING": "pending"}
    print("Cashfree: " + (", ".join(f"{sum(r.get('payout') == s for r in rows)} {words.get(s, s.lower())}"
                                     for s in ("PAID", "PENDING", "FAILED", "REVERSED", "NOT_FOUND")
                                     if any(r.get("payout") == s for r in rows)) or "nothing to report"))


def table(decisions):
    for d in decisions:
        amt = "?" if d["amount"] is None else f"{d['amount']:.0f}"
        print(f"{d['status']:5} {str(d['invoice_no'])[:14]:14} {str(d['vendor'])[:28]:28} {amt:>10}  " + " | ".join(d["reasons"]))


def score(decisions, expected, paid=()):
    counts = {s: sum(d["status"] == s for d in decisions) for s in ("PAY", "ASK", "LATER", "STOP")}
    line = "  ".join(f"{k} {v}" for k, v in counts.items() if v or k in ("PAY", "STOP"))
    got = {d["file"]: d["status"] for d in decisions if d.get("file") in (expected or {})}
    if got:
        traps = [f for f, want in expected.items() if want != "PAY" and f in got]
        good = [f for f, want in expected.items() if want == "PAY" and f in got]
        caught = sum(got[f] in ("STOP", "ASK") for f in traps)
        done = {d["file"] for d in decisions if d["transfer_id"] in paid}   # paid on an earlier run: not a block
        blocked = sum(got[f] in ("STOP", "ASK") and f not in done for f in good)  # LATER is a cash decision
        line += f"   |   traps caught {caught}/{len(traps)}, good invoices wrongly blocked {blocked}/{len(good)}"
        if done & set(good):
            line += f", already paid {len(done & set(good))}"
    print("SCORE  " + line)


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = [a for a in argv[1:] if not a.startswith("--")]
    for flag in ("--cash", "--fake"):  # their values are not positional arguments
        if flag in argv:
            args.remove(argv[argv.index(flag) + 1])
    send.load_env()
    if "--refresh" in argv:
        decisions = send.load(HERE / "decisions.json", [])
        approvals = send.load(HERE / "approvals.json", [])
        return settle(decisions, HERE / "ledger.json", approvals[-1] if approvals else None, tries=1)
    if not args:
        sys.exit(__doc__)
    src = Path(args[0])
    language = args[1] if len(args) > 1 else "en-IN"
    cash = float(argv[argv.index("--cash") + 1]) if "--cash" in argv else float("inf")
    dry = "--dry-run" in argv

    # 1. read
    if src.is_dir():
        invoices, folder = read_folder(src, language), src
    else:
        invoices, folder = json.loads(src.read_text(encoding="utf-8")), src.parent
    expected = send.load(folder / "expected.json", None)
    if expected is None:  # the team's answer key: [{"file": ..., "expected": "PAY" | "STOP"}]
        key = next((p for p in (folder / "invoice_answer_key.json", HERE / "invoice_answer_key.json") if p.exists()), None)
        expected = {r["file"]: r["expected"] for r in send.load(key, [])} if key else None

    # 2. check: plain code decides
    vendors = send.load(HERE / "vendors.json", [])
    ledger_path = HERE / "ledger.json"
    ledger = send.load(ledger_path, [])
    decisions = check.plan(invoices, vendors, ledger, cash)
    (HERE / "decisions.json").write_text(json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    tag = check.demo_round().lstrip("|")
    print(f"ROUND  {tag}  (rehearsal round: transfer IDs are fresh for this round only)" if tag
          else "ROUND  none  (real use: every invoice keeps one transfer ID for life)")
    table(decisions)
    score(decisions, expected, {r["transfer_id"] for r in ledger})
    publish(decisions, ledger_path, stage="checked")
    pay = [d for d in decisions if d["status"] == "PAY"]
    if "--no-pay" in argv or not pay:
        return print("\nnothing to pay." if not pay else "\n--no-pay: stopped before the approval call.")

    # 3. the owner approves by phone
    variables = approve.call_variables(decisions, os.environ.get("OWNER_NAME"))
    bid = send.batch_id(decisions)
    print(f"\nbatch {bid}: asking the owner to approve {variables['pay_count']} payment(s), {variables['pay_total']} rupees")
    c, missing = approve.cfg()
    if dry:
        print("WOULD CALL the owner with:", json.dumps(variables, ensure_ascii=False))
        send.send(decisions, vendors, ledger_path, "", dry_run=True)
        return print("--dry-run: no call placed, nothing sent.")
    if "--fake" in argv:
        attempt, result = approve.fake_answer(argv[argv.index("--fake") + 1])
        print("(--fake: using the answer from the file instead of a call)")
    elif "--latest" in argv:
        short = [k for k in approve.LATEST_NEEDS if not c[k]]
        if short:
            sys.exit("Missing in payright/.env: " + ", ".join(short))
        since = datetime.now(approve.IST)
        print("Paste these into the agent's variables in Sarvam's Test panel, then start the call:")
        print(json.dumps(variables, ensure_ascii=False, indent=2))
        print(f"Waiting for a call that begins after {since:%H:%M:%S}...")
        publish(decisions, ledger_path, stage="calling")
        attempt, result = approve.latest_call(c, since, approve.used_attempts(HERE / "approvals.json"))
        attempt = attempt or "none"
    else:
        if missing:
            sys.exit("Missing in payright/.env: " + ", ".join(missing))
        started, nonce = datetime.now(approve.IST), uuid.uuid4().hex
        attempt = approve.place_call(c, variables, bid, nonce)
        print(f"calling the owner (attempt {attempt})")
        publish(decisions, ledger_path, stage="calling")
        result = approve.read_result(c, attempt, started, nonce)
    approved, reason = approve.decide(result, decisions)
    a = approve.record(HERE / "approvals.json", bid, attempt, approved, reason, result)
    a["language"] = "Hindi"
    print(("APPROVED  " if approved else "NOT APPROVED  ") + reason)
    publish(decisions, ledger_path, a, stage="answered")
    if not approved:
        return print("nothing is paid.")

    # 4. pay: the approval is used up before any event leaves, and only approved rows go
    url = os.environ.get("RELAY_WEBHOOK_URL") or sys.exit("Set RELAY_WEBHOOK_URL in payright/.env")
    ids, why = approve.consume(HERE / "approvals.json", a["approval_id"], decisions)
    if why:
        return print("NOT PAID  " + why)
    to_send = [d if d["transfer_id"] in ids else {**d, "status": "ASK"} for d in decisions]
    for d in to_send:
        if d["status"] == "PAY":
            d["approval"] = a["approval_id"]
    print()
    sent = send.send(to_send, vendors, ledger_path, url, approval=a["approval_id"])
    publish(decisions, ledger_path, a, stage="sent")
    settle(decisions, ledger_path, a)
    print(f"sent {len(sent)} payment(s) to Relay, total {sum(e['data']['amount'] for e in sent):.0f}. "
          f"Run the same command again: nothing will be paid twice.")


if __name__ == "__main__":
    main(sys.argv)

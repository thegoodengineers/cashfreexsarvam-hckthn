"""One command for demo day: read -> check -> owner approves by phone -> pay.

  python run.py <folder of invoice images>  [ta-IN] [--cash 100000]
  python run.py invoices.json                         skip reading, start from extracted invoices

  --dry-run      read and check, show the call and the events, place no call, send nothing
  --no-pay       read and check only (table and score line)
  --fake '{"decision":"APPROVE_ALL","spoken_total":"70800"}'
                 use this as the owner's answer instead of placing the call

Score line: put expected.json in the folder ({"file.png": "PAY" | "STOP", ...}) and the run
prints traps caught and good invoices wrongly blocked. Without it, only the counts are printed.
"""
import json
import os
import sys
import uuid
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
    if not args:
        sys.exit(__doc__)
    send.load_env()
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

    # 2. check: plain code decides
    vendors = send.load(HERE / "vendors.json", [])
    ledger_path = HERE / "ledger.json"
    ledger = send.load(ledger_path, [])
    decisions = check.plan(invoices, vendors, ledger, cash)
    (HERE / "decisions.json").write_text(json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    table(decisions)
    score(decisions, expected, {r["transfer_id"] for r in ledger})
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
        fake = json.loads(argv[argv.index("--fake") + 1])
        attempt, result = "fake-" + uuid.uuid4().hex[:8], {"status": fake.pop("status", "connected"), "variables": fake}
    else:
        if missing:
            sys.exit("Missing in payright/.env: " + ", ".join(missing))
        started = datetime.now(approve.IST)
        attempt = approve.place_call(c, variables, bid)
        print(f"calling the owner (attempt {attempt}). Waiting for the call to end...")
        result = approve.read_result(c, attempt, started)
    approved, reason = approve.decide(result, decisions)
    a = approve.record(HERE / "approvals.json", bid, attempt, approved, reason, result)
    print(("APPROVED  " if approved else "NOT APPROVED  ") + reason)
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
    print(f"sent {len(sent)} payment(s) to Relay, total {sum(e['data']['amount'] for e in sent):.0f}. "
          f"Run the same command again: nothing will be paid twice.")


if __name__ == "__main__":
    main(sys.argv)

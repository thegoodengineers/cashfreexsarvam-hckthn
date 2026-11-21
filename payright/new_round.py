"""Start a fresh demo round:  python payright/new_round.py

Within a round an invoice keeps one transfer ID for life, so nothing is ever paid twice.
A new round sets the ledger and approvals aside and changes the round tag, so the same
demo invoices can be paid again in the sandbox for the next rehearsal. Never used in real use.
"""
import time
from pathlib import Path

HERE = Path(__file__).parent
tag = time.strftime("%H%M%S")
for name in ("ledger.json", "approvals.json", "approval.json"):
    p = HERE / name
    if p.exists():
        p.rename(HERE / f"{p.stem}.round-{tag}.json")
(HERE / "round.txt").write_text(tag)
print("new round", tag, "- ledger and approvals set aside; transfer IDs are fresh for this round")

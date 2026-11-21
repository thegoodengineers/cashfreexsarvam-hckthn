"""Price memory: what each vendor charged, per item, on bills we really paid.

A bill with every number raised together agrees with itself, so no check on the bill alone can catch it.
The vendor's own earlier bills can. check.py compares each line's rate with this book and sends the bill
to a person (ASK) when a rate is more than 10% above the last paid one. This file only keeps the book.

  python pricebook.py learn invoices.json      learn from the bills in this file that Cashfree confirmed PAID
                                               (ledger.json next to it, `payout` = PAID). Writes pricebook.json.
  python pricebook.py learn invoices.json --all   learn from every bill the checker clears (for a first setup)
  python pricebook.py show
  python pricebook.py --selftest

No pricebook.json -> price memory is silent and the checker behaves exactly as before.
"""
import json
import sys
from pathlib import Path

import check

HERE = Path(__file__).parent


def learn(invoices, vendors, book=None, paid_ids=None):
    """Add the rates on these bills to the book. Only bills the checker clears on their own are trusted;
    with `paid_ids`, only those whose transfer ID is in it (the ones Cashfree confirmed)."""
    book = book if book is not None else {}
    for inv in invoices:
        dec = check.plan([inv], vendors, [], float("inf"), prices={})[0]
        if dec["status"] != "PAY" or (paid_ids is not None and dec["transfer_id"] not in paid_ids):
            continue
        for l in inv.get("lines") or []:
            key, rate = check.item_key(l.get("description")), check.amount(l.get("rate"))
            if key and rate:
                book.setdefault(dec["vendor_id"], {})[key] = {
                    "item": str(l.get("description")).strip(), "rate": rate, "invoice_no": str(dec["invoice_no"])}
    return book


def main(argv):
    if "--selftest" in argv:
        return selftest()
    if len(argv) > 1 and argv[1] == "show":
        for vid, items in check.load_prices().items():
            for x in items.values():
                print(f"{vid:5} {x['rate']:>10g}  {x['item'][:50]:50} (invoice {x['invoice_no']})")
        return
    if len(argv) > 2 and argv[1] == "learn":
        path = Path(argv[2])
        vendors = json.loads((HERE / "vendors.json").read_text(encoding="utf-8"))
        paid = None
        if "--all" not in argv:
            ledger_file = path.parent / "ledger.json"
            ledger = json.loads(ledger_file.read_text(encoding="utf-8")) if ledger_file.exists() else []
            paid = {r["transfer_id"] for r in ledger if r.get("payout") == "PAID"}
        book = learn(json.loads(path.read_text(encoding="utf-8")), vendors, check.load_prices(), paid)
        check.PRICE_BOOK.write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
        return print(f"price book: {sum(len(v) for v in book.values())} item(s) from {len(book)} vendor(s)"
                     + ("" if paid is None else f"; {len(paid)} bill(s) confirmed paid in the ledger"))
    print(__doc__)


def selftest():
    V = [{"id": "v1", "name": "Sri Murugan Hardware", "gstin": "33AAAAA0000A1Z5", "bank_account": "026291800001191", "ifsc": "YESB0000262"}]
    bill = {"vendor_name": "Sri Murugan Hardware", "invoice_no": "INV-1", "invoice_date": "10-10-2026",
            "lines": [{"description": "1. PVC pipe", "qty": 10, "rate": 1000, "amount": 10000}],
            "subtotal": 10000, "tax": 1800, "total": 11800, "bank_account": "026291800001191", "ifsc": "YESB0000262"}
    book = learn([bill], V)
    assert book == {"v1": {"pvcpipe": {"item": "1. PVC pipe", "rate": 1000.0, "invoice_no": "INV-1"}}}
    assert learn([bill], V, paid_ids=set()) == {}                                  # not confirmed paid: not learnt
    assert learn([{**bill, "bank_account": "999999999999"}], V) == {}              # a stopped bill teaches nothing
    nxt = {**bill, "invoice_no": "INV-2", "invoice_date": "10-11-2026",
           "lines": [{"description": "PVC pipe", "qty": 10, "rate": 1500, "amount": 15000}], "subtotal": 15000, "tax": 2700, "total": 17700}
    assert check.plan([nxt], V, [], 1e9, prices={})[0]["status"] == "PAY"
    assert check.plan([nxt], V, [], 1e9, prices=book)[0]["status"] == "ASK"
    print("selftest ok")


if __name__ == "__main__":
    main(sys.argv)

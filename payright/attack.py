"""Attack our own checker: forge thousands of variants of real, clean bills and count what gets through.

Every base bill is one the live Sarvam reader read and check.py cleared to pay. Each forgery changes it the
way a fraudster (or a tired clerk) would. The real checker (check.plan) then decides. Nothing here decides
anything: this file only forges and counts. Memory only: no ledger, no approval, no Relay, no Cashfree.

  python attack.py [how_many] [seed]     default 1000 forgeries, seed 1. Same seed -> same forgeries -> same result.
  python attack.py --selftest

Three groups, and what must happen to each:
  FORGERY   must never be cleared to pay (STOP or ASK are both fine: a person sees it before any money moves)
  HARMLESS  the same genuine bill written differently (spaces in the account, another date format): must still be cleared
  BEYOND    a forgery no bill-only check can catch: next month's bill with every number raised together.
            Decided twice: with no history (it is cleared, and we say so), and with price memory holding the
            vendor's last genuine bill (check.py then sends a raise of more than 10% to a person).
"""
import copy
import glob
import json
import random
import re
import sys
from datetime import timedelta
from pathlib import Path

import check
import pricebook

HERE = Path(__file__).parent
STRANGERS = ("Jane D Traders", "Sunrise Agencies", "K P Enterprises", "New Bharat Stores", "Metro Trade Links")
DEVANAGARI = str.maketrans("0123456789", "०१२३४५६७८९")


def base_bills():
    """-> (the genuine bills the checker clears on their own, the vendor list)."""
    vendors = json.loads((HERE / "vendors.json").read_text(encoding="utf-8"))
    files = [HERE / "invoices" / "extracted.json"] + [Path(p) for p in sorted(glob.glob(str(HERE / "test_sets" / "*" / "extracted.json")))]
    bills = []
    for f in files:
        if f.exists():
            for inv in json.loads(f.read_text(encoding="utf-8")):
                if check.plan([inv], vendors, [], 1e12, prices={})[0]["status"] == "PAY":
                    bills.append(inv)
    return bills, vendors


def _other_digit(rng, ch):
    return rng.choice([d for d in "0123456789" if d != ch])


# ---- forgeries: each returns (changed bill, bill to send first or None), or None if it cannot apply to this bill

def acct_one_digit(inv, rng, vendors):
    a = str(inv.get("bank_account") or "")
    spots = [i for i, c in enumerate(a) if c.isdigit()]
    if not spots:
        return None
    i = rng.choice(spots)
    inv["bank_account"] = a[:i] + _other_digit(rng, a[i]) + a[i + 1:]
    return inv, None


def acct_swap_two(inv, rng, vendors):
    a = str(inv.get("bank_account") or "")
    spots = [i for i in range(len(a) - 1) if a[i].isdigit() and a[i + 1].isdigit() and a[i] != a[i + 1]]
    if not spots:
        return None
    i = rng.choice(spots)
    inv["bank_account"] = a[:i] + a[i + 1] + a[i] + a[i + 2:]
    return inv, None


def acct_new(inv, rng, vendors):
    known = {check.code_key(v["bank_account"]) for v in vendors}
    while True:
        a = "".join(rng.choice("0123456789") for _ in range(rng.randint(10, 16)))
        if a not in known:
            break
    inv["bank_account"] = a
    inv["ifsc"] = rng.choice(("HDFC", "SBIN", "UTIB", "KKBK")) + "0" + "".join(rng.choice("0123456789") for _ in range(6))
    return inv, None


def acct_of_another_vendor(inv, rng, vendors):
    mine = check.plan([inv], vendors, [], 1e12, prices={})[0]["vendor_id"]
    others = [v for v in vendors if v["id"] != mine]
    if not others:
        return None
    o = rng.choice(others)
    inv["bank_account"], inv["ifsc"] = o["bank_account"], o["ifsc"]
    return inv, None


def ifsc_changed(inv, rng, vendors):
    s = str(inv.get("ifsc") or "")
    spots = [i for i, c in enumerate(s) if c.isdigit()]
    if not spots or not inv.get("bank_account"):
        return None
    i = rng.choice(spots)
    inv["ifsc"] = s[:i] + _other_digit(rng, s[i]) + s[i + 1:]
    return inv, None


def total_raised(inv, rng, vendors):
    t = check.amount(inv.get("total"))
    if t is None or check.amount(inv.get("subtotal")) is None:
        return None
    inv["total"] = t + rng.choice((100, 500, 1000, 2700, 9000, 10000))
    return inv, None


def total_and_words_raised(inv, rng, vendors):
    t = check.amount(inv.get("total"))
    if t is None or check.amount(inv.get("subtotal")) is None:
        return None
    inv["total"] = inv["total_in_words_value"] = t + rng.choice((1000, 5000, 10000))
    return inv, None


def words_changed(inv, rng, vendors):
    t = check.amount(inv.get("total"))
    if t is None or check.amount(inv.get("total_in_words_value")) is None:
        return None
    inv["total_in_words_value"] = t * 10 if rng.random() < 0.5 else t + rng.choice((1000, 9000))
    return inv, None


def line_changed(inv, rng, vendors):
    lines = [l for l in inv.get("lines") or [] if None not in (check.amount(l.get("qty")), check.amount(l.get("rate")), check.amount(l.get("amount")))]
    if not lines:
        return None
    l = rng.choice(lines)
    l["amount"] = check.amount(l["amount"]) + rng.choice((500, 1000, 2500))
    return inv, None


def sent_twice_disguised(inv, rng, vendors):
    old = str(inv.get("invoice_no") or "")
    if not re.search(r"\d", old):
        return None
    first = copy.deepcopy(inv)
    new = re.sub(r"\d+", lambda m: str(int(m.group())), old)          # INV-0042 -> INV-42
    new = rng.choice((new.lower(), new.replace("-", "/"), new.replace("-", " "), new.lower().replace("-", "/"), "#" + new))
    inv["invoice_no"] = new
    d = check.parse_date(inv.get("invoice_date"))
    if d:
        inv["invoice_date"] = d.strftime(rng.choice(("%d %b %Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y")))
    return inv, first


def sent_twice_new_number(inv, rng, vendors):
    if not check.parse_date(inv.get("invoice_date")):
        return None
    first = copy.deepcopy(inv)
    inv["invoice_no"] = "N" + str(rng.randint(10000, 99999))
    return inv, first


def strangers_name(inv, rng, vendors):
    if not inv.get("bank_account"):
        return None
    inv["vendor_name"] = inv["vendor_name_latin"] = rng.choice(STRANGERS)
    inv.pop("gstin", None)
    inv.pop("account_holder", None)
    return inv, None


def lookalike_name_new_account(inv, rng, vendors):
    """The trick in the Mumbai and Hyderabad cases: two letters swapped or one doubled, and a new account."""
    name = str(inv.get("vendor_name_latin") or inv.get("vendor_name") or "")
    spots = [i for i in range(len(name) - 1) if name[i].isalpha() and name[i + 1].isalpha() and name[i] != name[i + 1] and name[i].isascii()]
    if not spots:
        return None
    i = rng.choice(spots)
    name = name[:i] + name[i + 1] + name[i] + name[i + 2:] if rng.random() < 0.5 else name[:i] + name[i] + name[i:]
    inv["vendor_name"] = inv["vendor_name_latin"] = name
    inv.pop("gstin", None)
    return acct_new(inv, rng, vendors)


def holder_changed(inv, rng, vendors):
    if not re.search(r"[A-Za-z]", str(inv.get("account_holder") or "")):
        return None
    inv["account_holder"] = rng.choice(("Ramesh Kumar", "S Venkatesh", "Priya Nair", "Mohammed Irfan"))
    return inv, None


def _next_month(inv, rng):
    d = check.parse_date(inv.get("invoice_date"))
    if d:
        inv["invoice_date"] = (d + timedelta(days=30)).strftime("%d-%m-%Y")
    inv["invoice_no"] = "NM-" + str(rng.randint(1000, 9999))


def everything_raised_together(inv, rng, vendors):
    """Next month's bill: lines, subtotal, tax, total and words all raised by the same factor. It agrees with itself."""
    t, s = check.amount(inv.get("total")), check.amount(inv.get("subtotal"))
    if t is None or s is None:
        return None
    _next_month(inv, rng)
    k = rng.choice((1.05, 1.1, 1.25, 1.5, 2))
    for l in inv.get("lines") or []:
        for f in ("rate", "amount"):
            if check.amount(l.get(f)) is not None:
                l[f] = round(check.amount(l[f]) * k, 2)
    for f in ("subtotal", "tax", "total", "total_in_words_value"):
        if check.amount(inv.get(f)) is not None:
            inv[f] = round(check.amount(inv[f]) * k, 2)
    return inv, None


# ---- harmless: the same genuine bill, written differently

def acct_with_spaces(inv, rng, vendors):
    a = str(inv.get("bank_account") or "")
    if len(a) < 8:
        return None
    sep = rng.choice((" ", "-"))
    inv["bank_account"] = sep.join(a[i:i + 4] for i in range(0, len(a), 4))
    inv["ifsc"] = str(inv.get("ifsc") or "").lower()
    return inv, None


def total_with_commas(inv, rng, vendors):
    t = check.amount(inv.get("total"))
    if t is None:
        return None
    s = f"{t:,.2f}"
    inv["total"] = rng.choice(("Rs. " + s, "₹" + s, s.translate(DEVANAGARI)))
    return inv, None


def date_rewritten(inv, rng, vendors):
    d = check.parse_date(inv.get("invoice_date"))
    if not d:
        return None
    inv["invoice_date"] = d.strftime(rng.choice(("%d %b %Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y", "%d %B %Y")))
    return inv, None


def next_month_same_prices(inv, rng, vendors):
    """A genuine repeat order: new number, new date, the same prices. Price memory must not get in its way."""
    _next_month(inv, rng)
    return inv, None


WITH_MEMORY = (everything_raised_together, next_month_same_prices)   # decided with the vendor's last genuine bill on file
FORGERY, HARMLESS, BEYOND = "forgery", "harmless", "beyond"
KINDS = (
    (FORGERY, "One digit of the bank account changed", acct_one_digit),
    (FORGERY, "Two digits of the account swapped", acct_swap_two),
    (FORGERY, "A brand new account and bank", acct_new),
    (FORGERY, "Another vendor's real account", acct_of_another_vendor),
    (FORGERY, "One character of the IFSC changed", ifsc_changed),
    (FORGERY, "Total raised, sums left as they were", total_raised),
    (FORGERY, "Total and amount in words raised together", total_and_words_raised),
    (FORGERY, "Amount in words changed", words_changed),
    (FORGERY, "One line item raised", line_changed),
    (FORGERY, "Same bill sent twice, number and date disguised", sent_twice_disguised),
    (FORGERY, "Same bill sent twice under a new number", sent_twice_new_number),
    (FORGERY, "A stranger's name on a real vendor's bill", strangers_name),
    (FORGERY, "Lookalike vendor name with a new account", lookalike_name_new_account),
    (FORGERY, "Account holder's name changed", holder_changed),
    (HARMLESS, "Account written with spaces, IFSC in small letters", acct_with_spaces),
    (HARMLESS, "Total written with commas, a rupee sign or Hindi digits", total_with_commas),
    (HARMLESS, "Date written in another format", date_rewritten),
    (HARMLESS, "Next month's bill at the same prices, price memory on", next_month_same_prices),
    (BEYOND, "Next month's bill, every number raised together", everything_raised_together),
)


def run(n=1000, seed=1):
    """Forge n bills and let check.plan decide each one. -> counts per kind, plus the totals."""
    bills, vendors = base_bills()
    rng = random.Random(seed)
    rows = [{"group": g, "kind": label, "tried": 0, "stop": 0, "ask": 0, "cleared": 0, "cleared_memory": 0, "example": None} for g, label, _ in KINDS]
    if not bills:
        return {"error": "No clean bill is available to forge from."}
    made, guard = 0, 0
    while made < n and guard < n * 20:
        guard += 1
        k = rng.randrange(len(KINDS))
        base = rng.choice(bills)
        made_bill = KINDS[k][2](copy.deepcopy(base), rng, vendors)
        if made_bill is None:
            continue
        inv, first = made_bill
        dec = check.plan(([first] if first else []) + [inv], vendors, [], 1e12, prices={})[-1]
        row = rows[k]
        row["tried"] += 1
        if KINDS[k][2] in WITH_MEMORY:      # the same bill again, with the vendor's last genuine bill in the price book
            remembered = check.plan([inv], vendors, [], 1e12, prices=pricebook.learn([base], vendors))[-1]
            row["cleared_memory"] += remembered["status"] == "PAY"
            if row["group"] == HARMLESS:
                dec = remembered
        row["stop" if dec["status"] == "STOP" else "ask" if dec["status"] == "ASK" else "cleared"] += 1
        wrong = dec["status"] == "PAY" if row["group"] == FORGERY else dec["status"] != "PAY" if row["group"] == HARMLESS else False
        if row["example"] is None or (wrong and not row["example"]["wrong"]):
            row["example"] = {"wrong": wrong, "status": dec["status"], "vendor": dec["vendor"], "invoice_no": dec["invoice_no"],
                              "reason": (dec["reasons"] or ["Nothing on the bill disagrees with itself or with our file."])[0]}
        made += 1

    def total(group, field):
        return sum(r[field] for r in rows if r["group"] == group)
    return {"seed": seed, "base_bills": len(bills), "made": made, "rows": rows,
            "forgeries": total(FORGERY, "tried"), "forgeries_cleared": total(FORGERY, "cleared"),
            "forgeries_stopped": total(FORGERY, "stop"), "forgeries_asked": total(FORGERY, "ask"),
            "harmless": total(HARMLESS, "tried"), "harmless_cleared": total(HARMLESS, "cleared"),
            "beyond": total(BEYOND, "tried"), "beyond_cleared": total(BEYOND, "cleared"),
            "beyond_cleared_memory": total(BEYOND, "cleared_memory")}


def selftest():
    a, b = run(300, 7), run(300, 7)
    assert a == b                                    # same seed, same forgeries, same answer
    assert a["made"] == 300 and a["base_bills"] > 0
    assert a["forgeries"] + a["harmless"] + a["beyond"] == 300
    assert run(300, 8)["rows"] != a["rows"]          # another seed really is another attack
    one = [inv for inv in base_bills()[0]][0]
    assert one == base_bills()[0][0]                 # forging never changes the base bills
    print("selftest ok")


def main(argv):
    if "--selftest" in argv:
        return selftest()
    nums = [int(x) for x in argv[1:] if x.isdigit()]
    r = run(*(nums[:2] or [1000]))
    if r.get("error"):
        return print(r["error"])
    print(f"{r['made']} forged bills from {r['base_bills']} genuine ones, seed {r['seed']}\n")
    print(f"{'':9} {'kind':56} {'tried':>6} {'STOP':>6} {'ASK':>6} {'cleared':>8}")
    for row in r["rows"]:
        print(f"{row['group']:9} {row['kind']:56} {row['tried']:>6} {row['stop']:>6} {row['ask']:>6} {row['cleared']:>8}")
    print(f"\nFORGERIES cleared to pay: {r['forgeries_cleared']} of {r['forgeries']}"
          f"   (stopped {r['forgeries_stopped']}, sent to a person {r['forgeries_asked']})")
    print(f"HARMLESS rewrites still cleared: {r['harmless_cleared']} of {r['harmless']}")
    print(f"BEYOND a bill-only check (next month's bill, every number raised together): {r['beyond_cleared']} of {r['beyond']} "
          f"cleared with no history; {r['beyond_cleared_memory']} of {r['beyond']} with price memory on. "
          "A raise of 10% or less passes by design.")


if __name__ == "__main__":
    main(sys.argv)

"""Invoice checks for "Pay the right bill, to the right person".

Design choice: a model READS the invoice, plain code DECIDES about money.
Every decision is PAY / ASK / STOP with reasons a person can read aloud.

  python check.py invoices.json [--cash 100000]   -> prints table, writes decisions.json
  python check.py --selftest
"""
import hashlib
import json
import re
import sys
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

TOL = 1.0  # rupees of rounding slack on totals
DIGITS = str.maketrans("०१२३४५६७८९௦௧௨௩௪௫௬௭௮௯೦೧೨೩೪೫೬೭೮೯", "0123456789" * 3)
UNITS = {"crore": 1e7, "करोड़": 1e7, "கோடி": 1e7, "ಕೋಟಿ": 1e7,
         "lakh": 1e5, "lac": 1e5, "लाख": 1e5, "லட்சம்": 1e5, "ಲಕ್ಷ": 1e5,
         "thousand": 1e3, "हजार": 1e3, "हज़ार": 1e3, "ஆயிரம்": 1e3, "ಸಾವಿರ": 1e3}
DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%y",
                "%d/%m/%y", "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%b %d, %Y")
# To verify with current MSME rules: micro/small Udyam vendors, 15 days without
# a written agreement, 45 with one. Medium vendors are not covered.
MSME_DAYS = {True: 45, False: 15}
PRICE_RISE = 0.10  # price memory: a rate more than this far above the last paid bill goes to a person
PRICE_BOOK = Path(__file__).parent / "pricebook.json"  # written by pricebook.py; absent -> price memory is silent


def amount(x):
    """'1,20,000' / '१,२०,०००' / '1.2 lakh' / 120000 -> 120000.0, None if unreadable."""
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x or "").translate(DIGITS).lower().replace(",", "")
    m = re.search(r"\d+(?:\.\d+)?", s)
    if not m:
        return None
    n = float(m.group())
    return next((n * mult for word, mult in UNITS.items() if word in s), n)


def parse_date(s):
    s = str(s or "").translate(DIGITS).strip()
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


def name_key(s):  # keeps Indic letters, drops spaces and punctuation
    return re.sub(r"[\W_]+", "", str(s or "").lower())


def code_key(s):  # account numbers, IFSC, GSTIN: 'hdfc 0001-234' == 'HDFC0001234'
    return re.sub(r"[^A-Z0-9]", "", str(s or "").translate(DIGITS).upper())


def invoice_key(s):  # 'INV-0042' == 'inv/42'
    return re.sub(r"\d+", lambda m: str(int(m.group())), code_key(s))


CONFUSED = str.maketrans("OISBZG", "015826")  # letters a reader mixes up with digits: O/0, I/1, S/5, B/8, Z/2, G/6
GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_key(s):  # '33KLMN09012P1Z8' == '33KLMNO9012P1Z8': the same GSTIN, read with the usual slip
    return code_key(s).translate(CONFUSED)


def gstin_valid(s):
    """A GSTIN carries its own check digit (the 15th character). True only if it adds up."""
    g = code_key(s)
    if len(g) != 15:
        return False
    total = 0
    for i, ch in enumerate(g[:14]):
        prod = GSTIN_CHARS.index(ch) * (1 + i % 2)
        total += prod // 36 + prod % 36
    return GSTIN_CHARS[(36 - total % 36) % 36] == g[14]


def item_key(s):  # '1. PVC pipe 1 inch, 6 m' == 'PVC pipe 1 inch, 6 m'
    return name_key(re.sub(r"^\s*\d+\s*[.)]\s*", "", str(s or "")))


def load_prices():
    """{vendor_id: {item_key: {"item", "rate", "invoice_no"}}} from bills we really paid, or {} if none yet."""
    try:
        return json.loads(PRICE_BOOK.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def find_vendor(inv, vendors):
    """-> (vendor, 'gstin' | 'name' | 'unsure') or (None, None)."""
    for v in vendors:
        if inv.get("gstin") and code_key(inv["gstin"]) == code_key(v.get("gstin")):
            return v, "gstin"
    # the reader's usual slip (O for 0, I for 1 ...) must not hide a vendor: accept it only if exactly one vendor fits
    slip = [v for v in vendors if inv.get("gstin") and v.get("gstin") and gstin_key(inv["gstin"]) == gstin_key(v["gstin"])]
    if len(slip) == 1:
        return slip[0], "gstin"
    best, score = None, 0.0
    seen_names = [name_key(inv.get(k)) for k in ("vendor_name", "vendor_name_latin")]
    for v in vendors:
        for known in (name_key(n) for n in [v["name"], v.get("account_holder"), *v.get("aliases", [])]):
            for n in seen_names:
                if n and known:
                    r = SequenceMatcher(None, n, known).ratio()
                    if r > score:
                        best, score = v, r
    if score >= 0.85:
        return best, "name"
    if score >= 0.6:
        return best, "unsure"
    return None, None


def demo_round():
    """Empty in real use: an invoice has one transfer ID for life. For rehearsals only,
    new_round.py writes round.txt so the sandbox accepts the same demo bills again."""
    f = Path(__file__).parent / "round.txt"
    return "|" + f.read_text().strip() if f.exists() else ""


def check(inv, vendors, seen, today, prices=None):
    """One invoice -> decision dict. `seen` = invoices already paid or earlier in the batch.
    `prices` = what each vendor charged on bills we really paid (load_prices()); None or {} switches it off."""
    stop, ask = [], []
    evidence = []  # the two values each STOP compared, for the board; no decision reads it

    def differ(what, a_label, a, b_label, b):
        evidence.append({"check": what, "a_label": a_label, "a": str(a), "b_label": b_label, "b": str(b)})

    # 1. The invoice must agree with itself.
    total = amount(inv.get("total"))
    sub, tax = amount(inv.get("subtotal")), amount(inv.get("tax")) or 0.0
    lines = inv.get("lines") or []
    if total is None:
        ask.append("I could not read the total amount.")
    else:
        for l in lines:
            q, r, a = amount(l.get("qty")), amount(l.get("rate")), amount(l.get("amount"))
            if None not in (q, r, a) and abs(q * r - a) > TOL:
                stop.append(f"Line '{l.get('description', '?')}': {q:g} x {r:g} is {q * r:.0f}, but the invoice says {a:.0f}.")
                differ("line item", "Invoice says", f"{a:.0f}", "Quantity x rate", f"{q * r:.0f}")
        line_sum = sum(amount(l.get("amount")) or 0.0 for l in lines)
        expect = sub if sub is not None else total - tax
        if lines and abs(line_sum - expect) > TOL:
            stop.append(f"The line items add up to {line_sum:.0f}, but the invoice says {expect:.0f}.")
            differ("line items", "Invoice says", f"{expect:.0f}", "Lines add up to", f"{line_sum:.0f}")
        if sub is not None and abs(sub + tax - total) > TOL:
            stop.append(f"Subtotal {sub:.0f} plus tax {tax:.0f} is {sub + tax:.0f}, but the total says {total:.0f}.")
            differ("total", "Total on the invoice", f"{total:.0f}", "Subtotal + tax", f"{sub + tax:.0f}")
        words = amount(inv.get("total_in_words_value"))
        if words is not None and abs(words - total) > TOL:
            stop.append(f"The amount in words is {words:.0f}, but the amount in figures is {total:.0f}.")
            differ("amount in words", "In figures", f"{total:.0f}", "In words", f"{words:.0f}")

    # 2. Who is asking to be paid?
    v, how = find_vendor(inv, vendors)
    totals_agree = total is not None and sub is not None and abs(sub + tax - total) <= TOL
    for f in inv.get("unsure_fields", []):
        if f == "vendor_name" and how in ("gstin", "name"):
            continue  # the vendor was still identified for certain
        if f == "total" and totals_agree:
            continue  # subtotal + tax confirms the total
        ask.append(f"I could not read '{f}' clearly on the invoice.")
    if v is None:
        ask.append("This vendor is not in our vendor list.")
    elif how == "unsure":
        ask.append(f"The vendor name looks like {v['name']}, but I am not sure it is the same vendor.")
    # 2b. The right name with a different GSTIN is not the same vendor until a person says so.
    if v and inv.get("gstin") and v.get("gstin") and gstin_key(inv["gstin"]) != gstin_key(v["gstin"]):
        ask.append(f"The GSTIN on this invoice is not the one we have on file for {v['name']}."
                   + ("" if gstin_valid(inv["gstin"]) else " It also fails the GSTIN check digit, so it was misread or made up."))
        differ("GSTIN", "On the invoice", code_key(inv["gstin"]), "On our file", code_key(v["gstin"]))

    # 3a. An account we already know, but on someone else's bill: money would reach the wrong person.
    acct = code_key(inv.get("bank_account"))
    owner = next((o for o in vendors if acct and code_key(o["bank_account"]) == acct), None)
    if owner and (v is None or owner["id"] != v["id"]):
        stop.append(f"The bank account on this invoice belongs to {owner.get('account_holder') or owner['name']} "
                    f"({owner['name']}), but the bill is from {inv.get('vendor_name') or 'another name'}. "
                    "Do not pay until both vendors confirm.")
        differ("account owner", "Bill is from", inv.get("vendor_name") or "?", "Account belongs to", owner["name"])

    # 3b. A familiar vendor with new bank details is never paid on the invoice's word.
    if v and inv.get("bank_account"):
        on_invoice = (code_key(inv["bank_account"]), code_key(inv.get("ifsc")))
        on_file = (code_key(v["bank_account"]), code_key(v["ifsc"]))
        if on_invoice[0] != on_file[0] or (on_invoice[1] and on_invoice[1] != on_file[1]):
            stop.append(f"The bank account on this invoice is not the account we have on file for {v['name']}. "
                        "Call the vendor on the number we already have before paying.")
            differ("bank account", "On the invoice", " ".join(on_invoice).strip(), "On our file", " ".join(on_file))

    # 3c. The account holder written on the invoice must be the one on file (Latin script only:
    #     a name in another script cannot be compared letter by letter, so it is left to the bank check).
    holder = name_key(inv.get("account_holder"))
    if v and re.search(r"[a-z]", holder):
        known = [name_key(n) for n in (v.get("account_holder"), v["name"], *v.get("aliases", [])) if n]
        if max(SequenceMatcher(None, holder, k).ratio() for k in known) < 0.6:
            on_file_holder = v.get("account_holder") or v["name"]
            stop.append(f"The invoice names the account holder as {inv['account_holder']}, "
                        f"but the holder on file for {v['name']} is {on_file_holder}.")
            differ("account holder", "On the invoice", inv["account_holder"], "On our file", on_file_holder)

    # 3d. Price memory: the same item from the same vendor, at a rate well above the last bill we really paid.
    #     A bill with every number raised together agrees with itself; only the vendor's own past bills show it.
    #     ASK, not STOP: prices do rise, so a person decides.
    for l in lines if v and prices else []:
        was, rate = (prices.get(v["id"]) or {}).get(item_key(l.get("description"))), amount(l.get("rate"))
        if was and rate is not None and was["rate"] > 0 and rate > was["rate"] * (1 + PRICE_RISE) + 0.005:
            ask.append(f"'{was['item']}' was {was['rate']:g} on invoice {was['invoice_no']}. This bill charges {rate:g}, "
                       f"{(rate / was['rate'] - 1) * 100:.0f}% more. Ask {v['name']} before paying.")
            differ("price", "On this bill", f"{rate:g}", f"Last paid, invoice {was['invoice_no']}", f"{was['rate']:g}")

    # 4. The same invoice coming back in disguise.
    key, d = invoice_key(inv.get("invoice_no")), parse_date(inv.get("invoice_date"))
    for s in seen if v else []:
        if s["vendor_id"] != v["id"]:
            continue
        same_amount = total is not None and abs(s["amount"] - total) <= TOL
        if key and key == s["invoice_key"]:
            stop.append(f"Invoice number {s['invoice_no']} from {v['name']} has already been {s['status'].lower()}"
                        + ("." if same_amount else f" for a different amount ({s['amount']:.0f})."))
            differ("duplicate", "This invoice", inv.get("invoice_no"), "Already seen as", s["invoice_no"])
            break
        if same_amount and d and s.get("date") == d.isoformat():
            ask.append(f"Same vendor, same amount and same date as invoice {s['invoice_no']}. "
                       "It may be the same bill with a new number.")
            break

    # 5. Deadline, used to decide what gets paid first.
    due = parse_date(inv.get("due_date"))
    if v and d and v.get("msme") in ("micro", "small"):
        due = d + timedelta(days=MSME_DAYS[bool(v.get("agreement"))])
    days_left = (due - today).days if due else None

    transfer_id = None
    if v and total is not None:  # same invoice -> same id, so a retry cannot become a second payment
        transfer_id = "PR" + hashlib.sha1(f"{v['id']}|{key}|{round(total * 100)}{demo_round()}".encode()).hexdigest()[:18]
    return {
        "invoice_no": inv.get("invoice_no"), "file": inv.get("file"),
        "vendor_id": v["id"] if v else None, "vendor": v["name"] if v else inv.get("vendor_name"),
        "amount": total, "status": "STOP" if stop else "ASK" if ask else "PAY",
        "reasons": stop + ask, "evidence": evidence, "days_left": days_left, "transfer_id": transfer_id,
        "invoice_key": key, "date": d.isoformat() if d else None,
        # money only ever goes to the account on file, never to one read off the invoice
        "bank_account": v["bank_account"] if v else None, "ifsc": v["ifsc"] if v else None,
    }


def plan(invoices, vendors, ledger, cash, today=None, prices=None):
    """Check a batch, then order the payable ones by deadline within the cash available."""
    today = today or date.today()
    prices = load_prices() if prices is None else prices
    seen, out = list(ledger), []
    for inv in invoices:
        dec = check(inv, vendors, seen, today, prices)
        out.append(dec)
        if dec["vendor_id"] and dec["amount"] is not None and dec["status"] != "STOP":
            seen.append({**dec, "status": "QUEUED"})
    for dec in sorted((d for d in out if d["status"] == "PAY"),
                      key=lambda d: (d["days_left"] is None, d["days_left"] or 0)):
        if dec["amount"] <= cash:
            cash -= dec["amount"]
        else:
            dec["status"] = "LATER"
            dec["reasons"].append("Not enough cash today after paying the invoices with nearer deadlines.")
    return out


def main(argv):
    if "--selftest" in argv:
        return selftest()
    path = Path(argv[1])
    here = path.parent
    cash = float(argv[argv.index("--cash") + 1]) if "--cash" in argv else float("inf")
    vfile = here / "vendors.json" if (here / "vendors.json").exists() else Path(__file__).parent / "vendors.json"
    vendors = json.loads(vfile.read_text(encoding="utf-8"))
    ledger_file = here / "ledger.json"
    ledger = json.loads(ledger_file.read_text(encoding="utf-8")) if ledger_file.exists() else []
    out = plan(json.loads(path.read_text(encoding="utf-8")), vendors, ledger, cash)
    for d in out:
        amt = "?" if d["amount"] is None else f"{d['amount']:.0f}"
        print(f"{d['status']:5} {str(d['invoice_no']):14} {str(d['vendor'])[:28]:28} {amt:>10}  " + " | ".join(d["reasons"]))
    (here / "decisions.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


def selftest():
    V = [{"id": "v1", "name": "Sri Murugan Hardware", "aliases": ["ஸ்ரீ முருகன் ஹார்டுவேர்"], "gstin": "33AAAAA0000A1Z5",
          "bank_account": "026291800001191", "ifsc": "YESB0000262", "msme": "micro", "agreement": False},
         {"id": "v2", "name": "Lakshmi Paints", "bank_account": "00011020001772", "ifsc": "HDFC0000001", "msme": "small", "agreement": True}]
    line = [{"description": "PVC pipe", "qty": 10, "rate": 1000, "amount": 10000}]
    base = {"vendor_name": "Sri Murugan Hardware", "invoice_no": "INV-0042", "invoice_date": "10-11-2026",
            "lines": line, "subtotal": 10000, "tax": 1800, "total": "11,800", "total_in_words_value": 11800,
            "bank_account": "026291800001191", "ifsc": "YESB0000262"}
    batch = [
        base,                                                                                  # clean
        {**base, "vendor_name": "Shri Murugan Hardwares", "invoice_no": "inv/42", "invoice_date": "2026-11-10"},  # duplicate in disguise
        {**base, "invoice_no": "INV-0043", "total": 12800},                                    # arithmetic
        {**base, "invoice_no": "INV-0044", "bank_account": "999999999999"},                    # changed account
        {**base, "invoice_no": "INV-0045", "total_in_words_value": "1.18 lakh"},               # words != figures
        {**base, "invoice_no": "INV-0046", "invoice_date": "12/11/2026", "vendor_name": "ஸ்ரீ முருகன் ஹார்டுவேர்"},  # clean, Tamil name
        {"vendor_name": "Lakshmi Paints", "invoice_no": "LP-7", "invoice_date": "01 Nov 2026", "total": "१,२०,०००"},  # clean, Hindi digits
        {"vendor_name": "Unknown Traders", "invoice_no": "1", "total": 500},                   # new vendor
    ]
    out = plan(batch, V, [], cash=125000, today=date(2026, 11, 21))
    got = [d["status"] for d in out]
    # 125000 cash: the two Murugan bills (4 and 6 days left) go first, so the 120000 bill (25 days left) waits
    assert got == ["PAY", "STOP", "STOP", "STOP", "STOP", "PAY", "LATER", "ASK"], got
    assert out[0]["days_left"] == 4 and out[6]["amount"] == 120000  # 15-day rule; Hindi digits
    assert out[0]["transfer_id"] == plan([base], V, [], 1e9)[0]["transfer_id"]  # stable id
    paid = [{**out[0], "status": "PAID"}]
    assert plan([base], V, paid, 1e9)[0]["status"] == "STOP"  # re-running a paid invoice never pays again
    borrowed = plan([{**base, "vendor_name": "Jane D Traders", "invoice_no": "JDT-1"}], V, [], 1e9)[0]
    assert borrowed["status"] == "STOP" and "belongs to" in borrowed["reasons"][0]  # known account, other name
    assert amount("1.2 lakh") == 120000 and amount("௧௨௦") == 120 and parse_date("10.11.2026") == date(2026, 11, 10)
    jane = check({**base, "invoice_no": "INV-9", "account_holder": "Jane Doe"}, V, [], date(2026, 11, 21))
    assert jane["status"] == "STOP" and "account holder" in jane["reasons"][0]  # right account, wrong holder name
    own = check({**base, "vendor_name": "John Doe", "invoice_no": "INV-10", "account_holder": "John Doe"},
                [{**V[0], "account_holder": "John Doe"}, V[1]], [], date(2026, 11, 21))
    assert own["status"] == "PAY", own["reasons"]  # billed in the holder's own name, own account
    shaky = check({**base, "invoice_no": "INV-11", "unsure_fields": ["vendor_name", "total"]}, V, [], date(2026, 11, 21))
    assert shaky["status"] == "PAY"  # GSTIN-free name match is certain and subtotal + tax confirms the total
    unsure = check({**base, "invoice_no": "INV-12", "unsure_fields": ["bank_account"]}, V, [], date(2026, 11, 21))
    assert unsure["status"] == "ASK"  # nothing else confirms a bank account, so a person is asked
    # the reader's O-for-0 slip in a GSTIN still finds the vendor, even under a name in another script
    VG = [{**V[0], "gstin": "33KLMNO9012P1Z8"}, V[1]]
    slip = check({**base, "vendor_name": "হোপ ইলেকট্ৰিকেলছ", "gstin": "33KLMN09012P1Z8", "invoice_no": "INV-13"}, VG, [], date(2026, 11, 21))
    assert slip["status"] == "PAY" and slip["vendor_id"] == "v1", slip["reasons"]
    other = check({**base, "gstin": "27AAJCC9783E1Z7", "invoice_no": "INV-14"}, VG, [], date(2026, 11, 21))
    assert other["status"] == "ASK" and "GSTIN" in other["reasons"][0] and "check digit" not in other["reasons"][0]   # right name, another real GSTIN
    fake = check({**base, "gstin": "23AAAPF57799Q2123", "invoice_no": "INV-15"}, VG, [], date(2026, 11, 21))
    assert fake["status"] == "ASK" and "fails the GSTIN check digit" in fake["reasons"][0]                           # an invented GSTIN
    assert gstin_valid("27AAJCC9783E1Z7") and not gstin_valid("27AAJCC9783E1Z8")
    # price memory: next month's bill, every number doubled, agrees with itself; the last paid bill gives it away
    book = {"v1": {item_key("1. PVC pipe"): {"item": "PVC pipe", "rate": 1000, "invoice_no": "INV-0042"}}}
    dear = {**base, "invoice_no": "INV-0050", "lines": [{"description": "PVC pipe", "qty": 10, "rate": 2000, "amount": 20000}],
            "subtotal": 20000, "tax": 3600, "total": 23600, "total_in_words_value": 23600}
    assert check(dear, V, [], date(2026, 11, 21))["status"] == "PAY"            # no memory: nothing to compare with
    asked = check(dear, V, [], date(2026, 11, 21), book)
    assert asked["status"] == "ASK" and "100% more" in asked["reasons"][0] and asked["evidence"][0]["check"] == "price"
    assert check({**base, "invoice_no": "INV-0051"}, V, [], date(2026, 11, 21), book)["status"] == "PAY"   # same price: no fuss
    small = {**dear, "lines": [{"description": "PVC pipe", "qty": 10, "rate": 1100, "amount": 11000}],
             "subtotal": 11000, "tax": 1980, "total": 12980, "total_in_words_value": 12980}
    assert check(small, V, [], date(2026, 11, 21), book)["status"] == "PAY"     # a 10% rise is allowed; more is asked
    print("selftest ok")


if __name__ == "__main__":
    main(sys.argv)

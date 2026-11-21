"""Variables for the owner's approval call, and the check on what he said.

  python call_vars.py [decisions.json]   -> prints the agent variables as JSON
  python call_vars.py --check DECISION "EXCLUDED_VENDORS" SPOKEN_TOTAL [decisions.json]
                                         -> what would be paid for these call outputs
  python call_vars.py --selftest

`agent_variables(decisions)` builds the input variables of the Sarvam voice
agent. `approved(decisions, final_vars)` reads its output variables and returns
the rows that may be paid, or [] - plain code decides, not the agent.
"""
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

from check import amount, name_key

OWNER_NAME = "Raghu"
APPROVE = ("APPROVE_ALL", "APPROVE_SOME")
EMPTY = {"", "none", "na", "nil", "null", "empty", "nobody"}

# check.py reason text -> one short sentence the agent can say in Hindi.
# First match wins, so the most serious reason comes first.
SHORT = [
    ("bank account on this invoice belongs to", "the bank account on this bill belongs to a different vendor on our list"),
    ("bank account on this invoice is not", "bank account changed on the invoice, call the vendor on the old number first"),
    ("has already been", "this bill was already paid or is already in this batch, it looks like a duplicate"),
    ("same bill with a new number", "same amount and date as another bill, it may be a duplicate"),
    ("plus tax", "the total on the bill is wrong, subtotal plus tax does not match"),
    ("line items add up", "the item amounts do not add up to the bill total"),
    ("Line '", "an item line is calculated wrong"),
    ("amount in words", "the amount in words and in figures do not match"),
    ("not in our vendor list", "this vendor is not in our vendor list"),
    ("not sure it is the same vendor", "the vendor name does not match the one on file"),
    ("could not read", "some part of the bill could not be read clearly"),
    ("Not enough cash", "not enough cash today, it waits for the next payment day"),
]


def rupees(x):
    return f"{x:.0f}"


def numbered(items):
    return " ".join(f"{i}) {x}." for i, x in enumerate(items, 1)) or "none"


def short_reason(reasons):
    """Every problem on the bill, most serious first, each said once."""
    found, unmatched = set(), []
    for r in reasons:
        i = next((i for i, (key, _) in enumerate(SHORT) if key in r), None)
        if i is None:
            unmatched.append(r.rstrip("."))
        else:
            found.add(i)
    said = [SHORT[i][1] for i in sorted(found)] + unmatched
    return ", and also ".join(said) if said else "needs your check"


def agent_variables(decisions, owner_name=OWNER_NAME):
    pay = [d for d in decisions if d["status"] == "PAY"]
    held = [d for d in decisions if d["status"] != "PAY"]
    return {
        "owner_name": owner_name,
        "user_name": owner_name,  # the agent on Chirag's account also has Sarvam's default user_name
        "pay_count": str(len(pay)),
        "pay_total": rupees(sum(d["amount"] for d in pay)),
        # amounts per vendor, so the agent can say the new total when he leaves one out
        "pay_list": numbered(f"{d['vendor']}, {rupees(d['amount'])} rupees" for d in pay),
        "held_count": str(len(held)),
        "held_list": numbered(
            f"{d['vendor']}, {'amount unclear' if d['amount'] is None else rupees(d['amount']) + ' rupees'}: {short_reason(d['reasons'])}"
            for d in held),
    }


def _same_vendor(said, vendor):
    a, b = name_key(said), name_key(vendor)
    return bool(a) and (a in b or SequenceMatcher(None, a, b).ratio() >= 0.75)


def approved(decisions, final_vars):
    """-> PAY rows the owner approved. [] unless the decision is an approval AND
    the total he said himself equals what would actually be paid."""
    decision = str(final_vars.get("decision") or "").strip().upper()
    if decision not in APPROVE:
        return []
    rows = [d for d in decisions if d["status"] == "PAY"]
    # Sarvam shows an empty output variable as "-"; treat that and words like "none" as empty
    excluded = [e for e in re.split(r"[,;\n]+", str(final_vars.get("excluded_vendors") or ""))
                if name_key(e) not in EMPTY]
    if decision == "APPROVE_SOME":
        if not excluded:
            return []  # "some" with nobody left out is unclear: pay nothing, call again
        rows = [d for d in rows if not any(_same_vendor(e, d["vendor"]) for e in excluded)]
    elif excluded:
        return []  # "all" but he named someone to leave out: contradiction, pay nothing
    said = amount(final_vars.get("spoken_total"))
    if not rows or said is None or abs(said - sum(d["amount"] for d in rows)) > 1.0:
        return []
    return rows


def main(argv):
    if "--selftest" in argv:
        return selftest()
    check_mode = "--check" in argv
    args = [a for a in argv[1:] if a != "--check"]
    outputs, args = (args[:3], args[3:]) if check_mode else ([], args)
    path = Path(args[0]) if args else Path(__file__).parent / "decisions.json"
    decisions = json.loads(path.read_text(encoding="utf-8"))
    if not check_mode:
        return print(json.dumps(agent_variables(decisions), ensure_ascii=False, indent=2))
    final = dict(zip(("decision", "excluded_vendors", "spoken_total"), outputs))
    rows = approved(decisions, final)
    for d in rows:
        print(f"PAY  {d['vendor']:30} {d['amount']:>10.0f}")
    print(f"total {sum(d['amount'] for d in rows):.0f}" if rows else "nothing would be paid")


def selftest():
    D = [{"vendor": "Doe Hardware Supplies", "amount": 11800.0, "status": "PAY", "reasons": []},
         {"vendor": "Wells Paints and Chemicals", "amount": 59000.0, "status": "PAY", "reasons": []},
         {"vendor": "Hope Electricals", "amount": 23600.0, "status": "STOP",
          "reasons": ["The bank account on this invoice is not the account we have on file for Hope Electricals. Call..."]},
         {"vendor": "Jane D Traders", "amount": 5000.0, "status": "ASK", "reasons": ["This vendor is not in our vendor list."]}]
    v = agent_variables(D)
    assert v["pay_count"] == "2" and v["pay_total"] == "70800" and v["held_count"] == "2", v
    assert "2) Wells Paints and Chemicals, 59000 rupees." in v["pay_list"]
    assert "bank account changed" in v["held_list"] and "not in our vendor list" in v["held_list"]
    ok = lambda **kw: [d["vendor"] for d in approved(D, kw)]
    assert ok(decision="APPROVE_ALL", spoken_total="70800") == ["Doe Hardware Supplies", "Wells Paints and Chemicals"]
    assert ok(decision="APPROVE_ALL", spoken_total="70,800") != []
    assert ok(decision="APPROVE_ALL", spoken_total="70000") == []            # wrong total
    assert ok(decision="APPROVE_ALL", spoken_total="") == []                 # he never said it
    assert ok(decision="APPROVE_SOME", excluded_vendors="Wells Paints", spoken_total="11800") == ["Doe Hardware Supplies"]
    assert ok(decision="APPROVE_SOME", excluded_vendors="Wells Paints", spoken_total="70800") == []  # old total
    assert ok(decision="APPROVE_SOME", excluded_vendors="", spoken_total="70800") == []
    assert ok(decision="APPROVE_ALL", excluded_vendors="Doe", spoken_total="70800") == []
    for blank in ("-", "None", "n/a", " - "):  # how Sarvam may send an empty output variable
        assert len(ok(decision="APPROVE_ALL", excluded_vendors=blank, spoken_total="70800")) == 2, blank
    assert ok(decision="APPROVE_SOME", excluded_vendors="-", spoken_total="11800") == []
    assert ok(decision="REJECT", spoken_total="70800") == [] and ok(decision="CALL_LATER") == []
    assert ok(decision="APPROVE_ALL", spoken_total="94400") == []            # stopped bill never paid
    assert agent_variables([])["pay_list"] == "none"
    assert len(v) == 7 and v["user_name"] == v["owner_name"] == "Raghu"  # all 7 agent inputs
    two = short_reason(["Subtotal 20000 plus tax 3600 is 23600, but the total says 26300.",
                        "I could not read 'total' clearly on the invoice.",
                        "The bank account on this invoice is not the account we have on file for X."])
    assert two.startswith("bank account changed") and "total on the bill is wrong" in two \
        and "could not be read" in two, two  # every problem, most serious first
    assert short_reason(["I could not read 'a'.", "I could not read 'b'."]).count("could not") == 1
    assert short_reason(["Something new."]) == "Something new" and short_reason([]) == "needs your check"
    print("selftest ok")


if __name__ == "__main__":
    main(sys.argv)

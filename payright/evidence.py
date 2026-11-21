"""Evidence report: how well did the reader read, and did the checker decide right?

  python evidence.py demo stress ladder            score saved reads, write the report
  python evidence.py stress --read [ta-IN]         read that set with Sarvam first (spends credits)
  python evidence.py all

For every invoice we generated we know the truth (make_invoices.py writes it to the answer key),
so the report can say, field by field, what Sarvam got right. It then runs the real check.py
on what was read and asks three questions:
  1. Decision:     did each invoice get an accepted result (PAY / ASK / STOP)?
  2. Reader:       how many critical fields were read exactly right?
  3. Money safety: was any invoice approved for payment with the wrong amount or vendor?

Writes docs/evidence/PayRight_Evidence.html (one self-contained page, images inlined),
docs/evidence/PayRight_Evidence.pdf and docs/evidence/summary.json.
Reads are saved next to the images as extracted.json, so re-scoring costs nothing.
"""
import base64
import html
import io
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path

from PIL import Image

import check

HERE = Path(__file__).parent
DOCS = HERE.parent / "docs" / "evidence"
IMAGES = (".png", ".jpg", ".jpeg", ".pdf")
SETS = {"demo": (HERE / "invoices", HERE / "invoice_answer_key.json",
                 "Demo set", "The 8 invoices we demo: 4 clean, 4 traps."),
        "stress": (HERE / "test_sets" / "stress", None,
                   "Stress set", "8 harder cases: words against figures, a wrong line, Devanagari digits, "
                   "a misspelt vendor, a re-sent bill, a dim photo, an amount above one lakh."),
        "ladder": (HERE / "test_sets" / "ladder", None,
                   "Fail-safe ladder", "The same kind of clean bill, photographed worse and worse. "
                   "A bad photo may be read or may be asked about. It must never be paid wrongly."),
        "languages": (HERE / "test_sets" / "languages", None,
                      "India's languages", "One clean invoice in each of the other 20 of the 22 languages of the "
                      "Eighth Schedule (Hindi and Tamil are in the demo set), each read with its own language code. "
                      "Cards marked 'native speaker to review' have best-effort labels and the amount in words in English."),
        "real": (HERE / "test_sets" / "real", None,
                 "Real bills", "Real bills photographed by the team, not generated: one handwritten, one printed Amazon "
                 "tax invoice. Private details (PAN, phones, addresses, order and payment IDs, signatures) are "
                 "blacked out. The truth was transcribed by hand.")}
FIELDS = [("vendor", "Vendor"), ("gstin", "GSTIN"), ("invoice_no", "Invoice no."), ("invoice_date", "Date"),
          ("subtotal", "Subtotal"), ("tax", "Tax"), ("total", "Total"), ("total_in_words_value", "Amount in words"),
          ("bank_account", "Account no."), ("ifsc", "IFSC")]
MONEY = {"total", "bank_account", "ifsc"}  # a wrong read here could move the wrong money


def load_env():
    env = HERE / ".env"
    for line in env.read_text().splitlines() if env.exists() else []:
        k, _, v = line.partition("=")
        if k.strip():
            os.environ.setdefault(k.strip(), v.strip())


def read_set(folder, language, key_path=None):
    """Read every image in the folder. Each invoice uses its own language code from the answer key."""
    import extract
    load_env()
    key = os.environ.get("SARVAM_API_KEY") or sys.exit("Set SARVAM_API_KEY in payright/.env")
    answer = json.loads((key_path or folder / "invoice_answer_key.json").read_text(encoding="utf-8"))
    lang = {r["file"]: r.get("language") or language for r in answer}
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGES)
    print(f"reading {len(files)} invoice(s) in {folder.name} with Sarvam "
          f"({', '.join(sorted({lang.get(p.name, language) for p in files}))})...")

    def one(p):
        try:
            return extract.read(p, key, lang.get(p.name, language))
        except Exception as e:
            return {"file": p.name, "unsure_fields": [f"whole invoice (reader error: {type(e).__name__})"]}
    with ThreadPoolExecutor(4) as pool:
        out = list(pool.map(one, files))
    (folder / "extracted.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def same(field, truth, inv, vendors):
    """Was this field read right? -> (ok, what was read)."""
    if field == "vendor":
        got = inv.get("vendor_name") or inv.get("vendor_name_latin")
        if truth["vendor_id"]:
            v, how = check.find_vendor(inv, vendors)
            return bool(v and v["id"] == truth["vendor_id"] and how != "unsure"), got
        names = [check.name_key(inv.get(k)) for k in ("vendor_name", "vendor_name_latin")]
        return any(n and SequenceMatcher(None, n, check.name_key(truth["vendor_printed"])).ratio() > .9
                   for n in names), got
    got = inv.get(field)
    want = truth[field]
    if want is None:  # not printed on the bill (real bills): right only if the reader left it empty
        return got in (None, "", "-", 0) or (isinstance(got, str) and not got.strip(" -")), got
    if field in ("subtotal", "tax", "total", "total_in_words_value"):
        a = check.amount(got)
        return a is not None and abs(a - want) <= check.TOL, got
    if field == "invoice_date":
        return check.parse_date(got) is not None and check.parse_date(got) == check.parse_date(want), got
    return check.code_key(got) == check.code_key(want), got


def score(name):
    folder, key_path, title, blurb = SETS[name]
    key = json.loads((key_path or folder / "invoice_answer_key.json").read_text(encoding="utf-8"))
    read = json.loads((folder / "extracted.json").read_text(encoding="utf-8"))
    from extract import unsure_fields
    for inv in read:  # re-apply today's reader rule to saved reads, so the report matches the live code
        if inv.get("confidence") is not None:
            inv["unsure_fields"] = unsure_fields(inv["confidence"])
    vendors = json.loads((HERE / "vendors.json").read_text(encoding="utf-8"))
    by_file = {r["file"]: r for r in read}
    unread = [k["file"] for k in key if k["file"] not in by_file]  # made, but not read by Sarvam yet: not scored
    key = [k for k in key if k["file"] in by_file]
    # a fresh ledger and unlimited cash: we score the checks, not today's bank balance
    decisions = {d["file"]: d for d in check.plan([by_file[k["file"]] for k in key], vendors, [], float("inf"))}
    rows = []
    for k in key:
        inv, dec, t = by_file[k["file"]], decisions[k["file"]], k["truth"]
        fields = []
        for f, label in FIELDS:
            ok, got = same(f, t, inv, vendors)
            want = t["vendor_printed"] if f == "vendor" else t[f]
            fields.append({"field": f, "label": label, "ok": ok, "read": got, "truth": want,
                           "confidence": (inv.get("confidence") or {}).get("vendor_name" if f == "vendor" else f)})
        paid = dec["status"] in ("PAY", "LATER")
        unsafe = paid and (dec["vendor_id"] != t["vendor_id"] or dec["amount"] is None
                           or abs(dec["amount"] - t["total"]) > check.TOL)
        k = {**k, "trap": f"[{k.get('language', 'en-IN')}] {k['trap']}"}
        rows.append({**k, "got": dec["status"], "reasons": dec["reasons"], "decision_ok": dec["status"] in k["accept"],
                     "unsafe": unsafe, "fields": fields, "unsure": inv.get("unsure_fields", [])})
    n_fields = sum(len(r["fields"]) for r in rows)
    # A trap is a bill planted to be refused; every other bill is genuine, however bad the photo.
    # Real bills from outside ("planted": false) are neither: they are scored on reading and on not being paid wrongly.
    traps = [r for r in rows if r["expected"] != "PAY" and r.get("planted", True)]
    good = [r for r in rows if r["expected"] == "PAY"]
    summary = {
        "set": name, "title": title, "blurb": blurb, "invoices": len(rows), "unread": unread,
        "decisions_ok": sum(r["decision_ok"] for r in rows),
        "traps": len(traps), "traps_caught": sum(r["got"] in ("STOP", "ASK") for r in traps),
        "good": len(good), "good_paid": sum(r["got"] in ("PAY", "LATER") for r in good),
        "good_asked": sum(r["got"] == "ASK" for r in good),
        "good_stopped": sum(r["got"] == "STOP" for r in good),
        "fields": n_fields, "fields_ok": sum(f["ok"] for r in rows for f in r["fields"]),
        "money_fields": sum(f["field"] in MONEY for r in rows for f in r["fields"]),
        "money_fields_ok": sum(f["ok"] and f["field"] in MONEY for r in rows for f in r["fields"]),
        "unsafe_payments": sum(r["unsafe"] for r in rows),
        "languages": sorted({r.get("language", "en-IN") for r in rows}),
    }
    return summary, rows


# ---------- report ----------
def thumb(path, width=420):
    im = Image.open(path).convert("RGB")
    im.thumbnail((width, width * 2))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=72)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def esc(x):
    return html.escape("—" if x in (None, "") else (f"{x:g}" if isinstance(x, float) else str(x)))


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "—"


CSS = """
:root { --ink:#1d1d1f; --muted:#5f6368; --line:#e3e6e3; --green:#0b6b3a; --pay:#137333; --ask:#b06000; --stop:#c5221f; --bg:#f7f8f7; }
* { box-sizing: border-box; }
body { margin: 0; font-family: 'Segoe UI', 'Nirmala UI', Arial, sans-serif; color: var(--ink); background: #fff; font-size: 13px; }
.wrap { max-width: 1100px; margin: 0 auto; padding: 28px 24px 60px; }
h1 { font-size: 26px; margin: 0; color: var(--green); }
.lede { color: var(--muted); margin: 6px 0 18px; font-size: 14px; max-width: 820px; line-height: 1.5; }
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 14px 0 6px; }
.learn { border: 1px solid var(--line); border-radius: 10px; padding: 10px 16px; margin: 14px 0; background: #fff; }
.learn h3 { margin: 4px 0 6px; font-size: 14px; color: var(--green); }
.learn li { margin: 4px 0; line-height: 1.45; }
.kpi { border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; background: var(--bg); }
.kpi .v { font-size: 26px; font-weight: 700; }
.kpi .l { color: var(--muted); font-size: 12px; margin-top: 2px; line-height: 1.35; }
.kpi.good .v { color: var(--pay); } .kpi.bad .v { color: var(--stop); }
h2 { font-size: 19px; margin: 34px 0 2px; color: var(--green); break-before: page; }
h2.first { break-before: auto; }
.set-blurb { color: var(--muted); margin: 0 0 10px; }
.sumline { margin: 6px 0 14px; font-size: 13px; }
.card { display: grid; grid-template-columns: 210px 1fr; gap: 16px; border: 1px solid var(--line); border-radius: 10px;
        padding: 12px; margin: 10px 0; break-inside: avoid; }
.card img { width: 210px; border-radius: 6px; border: 1px solid var(--line); }
.top { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.file { font-weight: 700; font-size: 14px; }
.badge { font-weight: 700; font-size: 11px; padding: 2px 8px; border-radius: 99px; color: #fff; letter-spacing: .5px; }
.PAY, .LATER { background: var(--pay); } .ASK { background: var(--ask); } .STOP { background: var(--stop); }
.verdict { font-size: 12px; font-weight: 600; } .verdict.ok { color: var(--pay); } .verdict.no { color: var(--stop); }
.trap { color: var(--muted); margin: 4px 0 6px; }
.reason { background: #fbf1ef; border-left: 3px solid var(--stop); padding: 5px 8px; margin: 4px 0; border-radius: 0 4px 4px 0; }
.reason.ask { background: #fdf4e6; border-color: var(--ask); }
table { border-collapse: collapse; width: 100%; margin-top: 6px; font-size: 12px; }
th, td { text-align: left; padding: 3px 6px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 600; }
td.ok { color: var(--pay); font-weight: 700; } td.no { color: var(--stop); font-weight: 700; }
tr.miss td { background: #fdecea; }
.mono { font-family: Consolas, monospace; }
.foot { color: var(--muted); margin-top: 30px; font-size: 12px; line-height: 1.5; }
@media print { .wrap { padding: 0; } body { font-size: 11px; } }
@media (max-width: 640px) { .kpis { grid-template-columns: 1fr 1fr; } .card { grid-template-columns: 1fr; } .card img { width: 100%; } }
"""


# What the runs taught us. Written by hand from the results below; every claim is visible in a card.
LEARNED = """<div class=learn><h3>What these tests taught us</h3><ul>
<li><b>On an unreadable photo the reader invents data.</b> On <span class=mono>lad4</span> Sarvam returned account
<span class=mono>0123456789012345</span>, a GSTIN and a 2023 date that are not on the bill. It scored that account
0 confidence, but our reader treated a 0 as fully sure (<span class=mono>0 or 1</span> is 1 in Python). We fixed it:
a 0 now marks the field unsure. The bill was never at risk, because code compares every account with the one on file.</li>
<li><b>A model reads, code decides, and that is why it held.</b> Every wrong read we saw was caught by a cross-check
(account on file, GSTIN, arithmetic, amount in words), not by trusting the model's confidence.</li>
<li><b>Scripts are not the hard part.</b> Tamil and Hindi names, Tamil and Hindi amounts in words, Devanagari digits and
lakh notation were all read right. On Devanagari digits Sarvam was unsure (0.5) of a correct total; the arithmetic and
the amount in words confirm it, so the bill is paid rather than asked about.</li>
<li><b>One systematic slip:</b> the letter O inside Hope's GSTIN is read as zero on every Hope bill. Usually harmless,
since the vendor is then matched by name, but it is why the GSTIN is never the only key.</li>
<li><b>All 22 Indian languages read.</b> Across the 20-language set Sarvam read 193 of 200 critical fields right, and every
total, account number and IFSC in every language. It scores non-English vendor names at 0.5 confidence, which at first
sent 9 clean bills to ASK. We measured a fix on the saved reads; the checker now asks only when nothing else confirms a
shaky reading (here the GSTIN or the account on file proves the vendor). All 9 are now paid and no other result changed.
The Assamese bill is still stopped (safely): the GSTIN slip and an Assamese name with no English reading leave the vendor
unidentified; an Assamese alias in the vendor list, or reading O and 0 alike in a GSTIN, would fix it.</li>
</ul></div>"""


def kpi(value, label, tone=""):
    return f'<div class="kpi {tone}"><div class=v>{value}</div><div class=l>{label}</div></div>'


def card(r, folder):
    status_ok = "ok" if r["decision_ok"] else "no"
    verdict = "as expected" if r["decision_ok"] else f"expected {'/'.join(r['accept'])}"
    reasons = "".join(f'<div class="reason{" ask" if r["got"] == "ASK" else ""}">{esc(x)}</div>' for x in r["reasons"])
    rows = "".join(
        f'<tr class="{"" if f["ok"] else "miss"}"><td>{f["label"]}</td><td class=mono>{esc(f["truth"])}</td>'
        f'<td class=mono>{esc(f["read"])}</td><td class="{"ok" if f["ok"] else "no"}">{"✓" if f["ok"] else "✗"}</td>'
        f'<td>{esc(f["confidence"])}</td></tr>' for f in r["fields"])
    unsafe = '<div class=reason>UNSAFE: approved for payment with a wrong amount or vendor.</div>' if r["unsafe"] else ""
    return f"""<div class=card><img src="{thumb(folder / r['file'])}" alt="{esc(r['file'])}">
<div><div class=top><span class=file>{esc(r['file'])}</span><span class="badge {r['got']}">{r['got']}</span>
<span class="verdict {status_ok}">{verdict}</span></div>
<div class=trap>{esc(r['trap'])}</div>{reasons}{unsafe}
<table><tr><th>Field</th><th>On the bill</th><th>Sarvam read</th><th></th><th>Conf.</th></tr>{rows}</table></div></div>"""


def report(results):
    tot = {k: sum(s[k] for s, _ in results) for k in
           ("invoices", "decisions_ok", "traps", "traps_caught", "good", "good_paid", "good_asked", "good_stopped",
            "fields", "fields_ok", "money_fields", "money_fields_ok", "unsafe_payments")}
    unread = [f for s, _ in results for f in s["unread"]]
    head = "".join([
        kpi(f"{tot['traps_caught']}/{tot['traps']}", "planted traps caught before any money moved", "good"),
        kpi(f"{tot['good_paid']}/{tot['good']}",
            f"genuine bills cleared to pay; not paid: {tot['good_asked']} asked about, {tot['good_stopped']} stopped",
            "good" if tot["good_paid"] == tot["good"] else ""),
        kpi(f"{tot['unsafe_payments']}", f"wrong payments approved across {tot['invoices']} invoices",
            "good" if not tot["unsafe_payments"] else "bad"),
        kpi(pct(tot["fields_ok"], tot["fields"]), f"of {tot['fields']} critical fields read exactly right"),
        kpi(pct(tot["money_fields_ok"], tot["money_fields"]), f"of {tot['money_fields']} money fields (total, account, IFSC) read right"),
        kpi(f"{tot['decisions_ok']}/{tot['invoices']}", "invoices got an accepted decision"),
    ])
    pending = (f"<p class=lede><b>Not read yet:</b> <span class=mono>{esc(', '.join(unread))}</span> "
               "(made and in the answer key, waiting for Sarvam credits). Not counted above.</p>") if unread else ""
    langs = sorted({l for s, _ in results for l in s["languages"]})
    indian = [l for l in langs if l != "en-IN"]
    head = kpi(f"{len(langs)}", f"languages read: {len(indian)} Indian languages + English" if "en-IN" in langs
               else f"Indian languages read", "good") + head
    sections = []
    for i, (s, rows) in enumerate(results):
        folder = SETS[s["set"]][0]
        line = (f"<b>{s['decisions_ok']}/{s['invoices']}</b> accepted decisions · traps caught <b>{s['traps_caught']}/{s['traps']}</b> · "
                f"genuine bills paid <b>{s['good_paid']}/{s['good']}</b> (asked {s['good_asked']}, stopped {s['good_stopped']}) · "
                f"fields read right <b>{s['fields_ok']}/{s['fields']}</b> · wrong payments <b>{s['unsafe_payments']}</b>")
        sections.append(f'<h2 class="{"first" if i == 0 else ""}">{s["title"]}</h2><p class=set-blurb>{esc(s["blurb"])}</p>'
                        f'<div class=sumline>{line}</div>' + "".join(card(r, folder) for r in rows))
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>PayRight Evidence</title><style>{CSS}</style></head><body><div class=wrap>
<h1>PayRight — evidence</h1>
<p class=lede>Every invoice below went through the live Sarvam Document AI reader (advanced mode) and our real
<span class=mono>check.py</span>. We generated the invoices ourselves (apart from the real bills), so we know what is truly printed on it and can
score the reader field by field. Nothing here is typed in by hand. The "handwritten" bills are generated pages in a
handwriting font made to look like phone photos. The two real bills at the end (one handwritten, one printed; team photos, private details blacked out) are not generated: their truth was transcribed by hand.</p>
<div class=kpis>{head}</div>{pending}
{LEARNED if {'demo', 'stress', 'ladder', 'languages'} <= {s['set'] for s, _ in results} else ''}
{''.join(sections)}
<p class=foot>Generated {datetime.now():%d %b %Y, %H:%M} by <span class=mono>payright/evidence.py</span> from saved reads
(<span class=mono>extracted.json</span> in each set's folder). Re-run any time: <span class=mono>python payright/evidence.py all</span>.
Decisions use a fresh ledger and unlimited cash, so they show the checks, not today's bank balance.
Field confidences are as reported by Sarvam.</p>
</div></body></html>"""


def to_pdf(src, dst):
    sys.path.insert(0, str(HERE))
    from make_invoices import browser
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([browser(), "--headless=new", "--disable-gpu", f"--user-data-dir={tmp}/p", "--no-pdf-header-footer",
                        f"--print-to-pdf={dst}", src.resolve().as_uri()], check=True, capture_output=True, timeout=180)


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = [a for a in argv[1:] if not a.startswith("--")]
    language = next((a for a in args if "-IN" in a), "ta-IN")
    names = [a for a in args if a in SETS or a == "all"] or ["all"]
    names = list(SETS) if "all" in names else names
    if "--read" in argv:
        for n in names:
            read_set(SETS[n][0], language, SETS[n][1])
    results = []
    for n in names:
        if not (SETS[n][0] / "extracted.json").exists():
            print(f"skip {n}: no extracted.json yet (run with --read)")
            continue
        s, rows = score(n)
        results.append((s, rows))
        print(f"{s['title']:17} decisions {s['decisions_ok']}/{s['invoices']}  traps {s['traps_caught']}/{s['traps']}  "
              f"good paid {s['good_paid']}/{s['good']} (asked {s['good_asked']}, stopped {s['good_stopped']})  "
              f"fields {s['fields_ok']}/{s['fields']}  " + (f"unread {s['unread']}  " if s["unread"] else "") +
              f"wrong payments {s['unsafe_payments']}")
        for r in rows:
            miss = [f"{f['label']}: read {f['read']!r}, bill says {f['truth']!r}" for f in r["fields"] if not f["ok"]]
            flag = "" if r["decision_ok"] else f"   <-- expected {'/'.join(r['accept'])}"
            print(f"   {r['got']:5} {r['file']:18}{flag}" + ("" if not miss else "   misread " + "; ".join(miss)))
    if not results:
        return
    DOCS.mkdir(parents=True, exist_ok=True)
    page = DOCS / "PayRight_Evidence.html"
    page.write_text(report(results), encoding="utf-8")
    (DOCS / "summary.json").write_text(json.dumps([s for s, _ in results], indent=2), encoding="utf-8")
    to_pdf(page, DOCS / "PayRight_Evidence.pdf")
    print(f"wrote {page} and PayRight_Evidence.pdf")


if __name__ == "__main__":
    main(sys.argv)

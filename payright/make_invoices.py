"""Make the test invoices, each with its ground truth, so we can measure the reader and the checker.

  python make_invoices.py            demo set   -> payright/invoices/            (9: 4 clean, 5 traps)
  python make_invoices.py stress     stress set -> payright/test_sets/stress/    (8 harder cases)
  python make_invoices.py ladder     fail-safe  -> payright/test_sets/ladder/    (5 photos, perfect -> unreadable)
  python make_invoices.py languages  languages  -> payright/test_sets/languages/ (the other 20 of India's 22 languages)
  python make_invoices.py all

Every set gets an answer key (`invoice_answer_key.json`) that run.py and evidence.py read:
  {"file", "expected", "accept", "trap", "truth": {every field as printed on the bill}}

Each invoice is laid out as HTML and rendered by headless Edge/Chrome, because the browser shapes
Tamil and Devanagari correctly. Photos are then made from the flat page (tilt, perspective,
uneven light, blur, grain, JPEG). Same input, same pixels: the sets are reproducible.

The Cashfree sandbox only pays three accounts, so every invoice uses them.
File names are neutral on purpose: the trap is written only in the answer key.
"""
import json
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).parent
BUYER = ("Sri Ganesh Hardware Wholesale", "14, Godown Street, Parrys, Chennai 600001", "33AAFCS7788Q1Z3")

DOE = dict(id="v1", name="Doe Hardware Supplies", gstin="33ABCDE1234F1Z5", holder="John Doe",
           acct="026291800001191", ifsc="YESB0000262", bank="Yes Bank, Anna Salai",
           addr="22, Mint Street, Sowcarpet, Chennai 600079", phone="99999 99999")
WELLS = dict(id="v2", name="Wells Paints and Chemicals", gstin="33FGHIJ5678K1Z2", holder="Tom Wells",
             acct="1233943142", ifsc="ICIC0000009", bank="ICICI Bank, T. Nagar",
             addr="7/3, Ranganathan Street, T. Nagar, Chennai 600017", phone="99999 99999")
HOPE = dict(id="v3", name="Hope Electricals", gstin="33KLMNO9012P1Z8", holder="Bob Hope",
            acct="388108022658", ifsc="ICIC0000009", bank="ICICI Bank, Ritchie Street",
            addr="41, Ritchie Street, Mount Road, Chennai 600002", phone="99999 99999")
JANE = {**DOE, "id": None, "name": "Jane D Traders", "gstin": "33PQRST3456U1Z9",
        "addr": "5, Narayana Mudali Street, Chennai 600079"}


# ---------- numbers ----------
DEVA = str.maketrans("0123456789", "०१२३४५६७८९")


def inr(n):
    """18880 -> '18,880.00' in Indian grouping."""
    whole, frac = f"{n:.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        head = ",".join([head[max(0, i - 2):i] for i in range(len(head), 0, -2)][::-1])
        whole = head + "," + tail
    return f"{whole}.{frac}"


ONES = ("Zero One Two Three Four Five Six Seven Eight Nine Ten Eleven Twelve Thirteen Fourteen "
        "Fifteen Sixteen Seventeen Eighteen Nineteen").split()
TENS = "_ _ Twenty Thirty Forty Fifty Sixty Seventy Eighty Ninety".split()


def words(n):
    n = int(round(n))

    def two(x):
        return ONES[x] if x < 20 else TENS[x // 10] + ("" if x % 10 == 0 else " " + ONES[x % 10])

    def three(x):
        h, r = divmod(x, 100)
        return " ".join(p for p in ((ONES[h] + " Hundred") if h else "", two(r) if r else "") if p)

    parts = []
    for size, name in ((10**7, "Crore"), (10**5, "Lakh"), (1000, "Thousand")):
        q, n = divmod(n, size)
        if q:
            parts.append(f"{three(q)} {name}")
    if n:
        parts.append(three(n))
    return "Rupees " + " ".join(parts) + " Only"


def figures(it):
    """Subtotal, tax and total exactly as printed on the bill (traps included)."""
    sub = sum(l[4] if len(l) > 4 else l[2] * l[3] for l in it["lines"])
    tax = round(sub * 0.18, 2)
    total = it.get("total", sub + tax)
    return sub, tax, total


def truth(it):
    sub, tax, total = figures(it)
    v, pay = it["vendor"], {**it["vendor"], **it.get("pay_to", {})}
    return {"vendor_id": v.get("id"), "vendor_printed": it.get("brand") or v["name"],
            "gstin": it.get("gstin") or v["gstin"], "invoice_no": it["no"], "invoice_date": it["date"],
            "subtotal": sub, "tax": tax, "total": total, "total_in_words_value": it.get("words_value", total),
            "bank_account": pay["acct"], "ifsc": pay["ifsc"], "account_holder": pay["holder"]}


# ---------- printed invoice template ----------
CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { width: 900px; height: 1273px; background: #fff; }
body { font-family: 'Segoe UI', 'Nirmala UI', Arial, sans-serif; color: #1d1d1f; font-size: 15px; }
.page { padding: 44px 52px; height: 1273px; position: relative; }
.head { display: flex; justify-content: space-between; align-items: flex-start;
        border-bottom: 3px solid var(--accent); padding-bottom: 16px; }
.brand { font-size: 31px; font-weight: 700; color: var(--accent); letter-spacing: .2px; line-height: 1.25; }
.sub { font-size: 13px; color: #555; margin-top: 4px; line-height: 1.5; }
.doc { text-align: right; }
.doc .t { font-size: 22px; font-weight: 700; letter-spacing: 1px; color: #333; }
.meta { margin-top: 8px; font-size: 14px; line-height: 1.7; }
.meta b { display: inline-block; min-width: 92px; color: #555; font-weight: 600; }
.parties { display: flex; gap: 24px; margin: 22px 0 18px; }
.box { flex: 1; border: 1px solid #ddd; border-radius: 6px; padding: 12px 14px; font-size: 14px; line-height: 1.55; }
.box .lbl { font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: #888; margin-bottom: 4px; }
table { width: 100%; border-collapse: collapse; font-size: 14.5px; }
th { background: var(--accent); color: #fff; text-align: left; padding: 9px 10px; font-weight: 600; }
td { padding: 9px 10px; border-bottom: 1px solid #e6e6e6; }
.n { text-align: right; font-variant-numeric: tabular-nums; }
.sum { width: 360px; margin-left: auto; margin-top: 14px; font-size: 15px; }
.sum td { border: none; padding: 5px 10px; }
.sum .grand td { border-top: 2px solid #333; font-size: 19px; font-weight: 700; padding-top: 9px; }
.words { margin-top: 14px; padding: 10px 14px; background: #f6f6f4; border-left: 4px solid var(--accent);
         font-size: 14.5px; }
.bank { margin-top: 22px; display: flex; gap: 24px; }
.bank .box { line-height: 1.75; }
.mono { font-family: Consolas, monospace; font-size: 15px; letter-spacing: .5px; }
.note { margin-top: 16px; font-size: 14px; padding: 10px 14px; border: 1.5px dashed #c0392b;
        color: #a5281b; border-radius: 6px; font-weight: 600; }
.foot { position: absolute; left: 52px; right: 52px; bottom: 44px; display: flex;
        justify-content: space-between; align-items: flex-end; font-size: 12.5px; color: #666; }
.sign { text-align: center; }
.sign .s { font-family: 'Segoe Script', 'Ink Free', cursive; font-size: 26px; color: #1b3a8a; }
.sign .l { border-top: 1px solid #999; padding-top: 4px; min-width: 200px; }
/* the disguised duplicate uses a plain, older-looking layout */
.plain .head { border-bottom: 1px solid #000; }
.plain .brand { color: #000; font-family: 'Times New Roman', serif; font-size: 30px; }
.plain th { background: #fff; color: #000; border-top: 1px solid #000; border-bottom: 1px solid #000; }
.plain .words { background: none; border: 1px solid #000; }
"""

LABELS = {"invoice": "TAX INVOICE", "no": "Invoice No.", "date": "Date", "due": "Due Date",
          "bill_to": "Bill to", "item": "Description", "hsn": "HSN", "qty": "Qty",
          "rate": "Rate (₹)", "amt": "Amount (₹)", "subtotal": "Subtotal", "cgst": "CGST @ 9%",
          "sgst": "SGST @ 9%", "gst": "Total GST", "total": "Total Payable", "words": "Amount in words",
          "bank": "Bank details for payment", "holder": "Account holder", "acct": "Account No.",
          "ifsc": "IFSC", "bankname": "Bank", "sign": "Authorised signatory", "thanks": "Thank you for your business."}


def printed(it):
    v = it["vendor"]
    pay = {**v, **it.get("pay_to", {})}
    L = {**LABELS, **it.get("labels", {})}
    num = (lambda s: str(s).translate(DEVA)) if it.get("digits") == "deva" else str
    sub, tax, total = figures(it)
    rows = "".join(
        f"<tr><td>{i}. {l[0]}</td><td>{l[1]}</td><td class=n>{num(l[2])}</td><td class=n>{num(inr(l[3]))}</td>"
        f"<td class=n>{num(inr(l[4] if len(l) > 4 else l[2] * l[3]))}</td></tr>" for i, l in enumerate(it["lines"], 1))
    due_html = f"<div><b>{L['due']}</b> {num(it['due'])}</div>" if it.get("due") else ""
    note_html = f"<div class=note>{it['note']}</div>" if it.get("note") else ""
    return f"""<!doctype html><html><head><meta charset=utf-8><style>{CSS}</style></head>
<body class="{it.get('cls', '')}" style="--accent:{it.get('accent', '#1f5fa8')}"><div class=page>
 <div class=head>
  <div><div class=brand dir=auto>{it.get('brand') or v['name']}</div>
   <div class=sub>{v['addr']}<br>Ph: {v['phone']} &nbsp;·&nbsp; GSTIN: <span class=mono>{it.get('gstin') or v['gstin']}</span></div></div>
  <div class=doc><div class=t>{L['invoice']}</div>
   <div class=meta><div><b>{L['no']}</b> {it['no']}</div><div><b>{L['date']}</b> {num(it['date'])}</div>{due_html}</div></div>
 </div>
 <div class=parties>
  <div class=box><div class=lbl>{L['bill_to']}</div><b>{BUYER[0]}</b><br>{BUYER[1]}<br>GSTIN: <span class=mono>{BUYER[2]}</span></div>
 </div>
 <table><tr><th>{L['item']}</th><th>{L['hsn']}</th><th class=n>{L['qty']}</th><th class=n>{L['rate']}</th><th class=n>{L['amt']}</th></tr>{rows}</table>
 <table class=sum>
  <tr><td>{L['subtotal']}</td><td class=n>{num(inr(sub))}</td></tr>
  <tr><td>{L['cgst']}</td><td class=n>{num(inr(tax / 2))}</td></tr>
  <tr><td>{L['sgst']}</td><td class=n>{num(inr(tax / 2))}</td></tr>
  <tr><td>{L['gst']}</td><td class=n>{num(inr(tax))}</td></tr>
  <tr class=grand><td>{L['total']}</td><td class=n>₹ {num(inr(total))}</td></tr>
 </table>
 <div class=words><b>{L['words']}:</b> {it.get('words_text') or words(it.get('words_value', total))}</div>
 <div class=bank><div class=box><div class=lbl>{L['bank']}</div>
  {L['holder']}: <b>{pay['holder']}</b><br>{L['acct']}: <span class=mono><b>{pay['acct']}</b></span><br>
  {L['ifsc']}: <span class=mono><b>{pay['ifsc']}</b></span><br>{L['bankname']}: {pay['bank']}</div></div>
 {note_html}
 <div class=foot><div>{L['thanks']}</div>
  <div class=sign><div class=s>{pay['holder']}</div><div class=l>{L['sign']}</div></div></div>
</div></body></html>"""


# ---------- handwritten bill-book page ----------
def handwritten(it):
    v = it["vendor"]
    sub, tax, total = figures(it)
    rows = "".join(f"<tr class=ink><td>{l[0]}</td><td class=n>{l[2]}</td><td class=n>{l[3]:g}</td>"
                   f"<td class=n>{l[2] * l[3]:g}</td></tr>" for l in it["lines"])
    return f"""<!doctype html><html><head><meta charset=utf-8><style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ width: 900px; height: 1180px; }}
body {{ background: #f3efe2; font-family: Arial, sans-serif; color: #b0262a; }}
.page {{ padding: 34px 40px; height: 1180px; position: relative;
  background: repeating-linear-gradient(#f3efe2 0 41px, #c9cfe0 41px 42px); }}
.top {{ text-align: center; border-bottom: 2px solid #b0262a; padding-bottom: 10px; background: #f3efe2; }}
.top .n {{ font-size: 33px; font-weight: 800; letter-spacing: 1px; }}
.top .a {{ font-size: 14px; color: #8a2a2a; margin-top: 2px; }}
.row {{ display: flex; justify-content: space-between; margin: 16px 0 6px; font-size: 17px; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
th {{ border: 1.5px solid #b0262a; padding: 6px; font-size: 15px; background: #f3efe2; }}
td {{ border-left: 1.5px solid #b0262a; border-right: 1.5px solid #b0262a; height: 42px; padding: 0 10px; }}
tr:last-child td {{ border-bottom: 1.5px solid #b0262a; }}
.n {{ text-align: right; }}
.ink {{ font-family: 'Ink Free', 'Segoe Print', cursive; color: #1d2f8c; font-size: 25px; font-weight: 600; }}
.tot {{ margin-top: 14px; margin-left: auto; width: 420px; font-size: 18px; }}
.tot div {{ display: flex; justify-content: space-between; height: 42px; align-items: center; }}
.foot {{ position: absolute; bottom: 40px; left: 40px; right: 40px; font-size: 16px; }}
</style></head><body><div class=page>
 <div class=top><div class=n>{v['name'].upper()}</div>
  <div class=a>{v['addr']} · Ph {v['phone']}<br>GSTIN {v['gstin']}</div>
  <div style="margin-top:6px;font-weight:700;letter-spacing:3px">CASH / CREDIT BILL</div></div>
 <div class=row><span>No. <span class=ink>{it['no']}</span></span><span>Date <span class=ink>{it['date']}</span></span></div>
 <div class=row><span>M/s. <span class=ink>{BUYER[0]}, Parrys</span></span></div>
 <table><tr><th style="width:52%">Particulars</th><th>Qty</th><th>Rate</th><th>Amount</th></tr>
  {rows}
  <tr><td></td><td></td><td></td><td></td></tr><tr><td></td><td></td><td></td><td></td></tr></table>
 <div class=tot>
  <div><span>Total</span><span class=ink>{sub:g}</span></div>
  <div><span>GST 18%</span><span class=ink>{tax:g}</span></div>
  <div style="border-top:2px solid #b0262a"><span><b>Grand Total</b></span><span class=ink>₹ {total:g}/-</span></div></div>
 <div class=row style="margin-top:18px"><span>Rupees <span class=ink>{words(total)[7:]}</span></span></div>
 <div class=row style="margin-top:14px"><span>Pay to A/c <span class=ink>{v['holder']} · {v['acct']} · IFSC {v['ifsc']}</span></span></div>
 <div class=foot style="display:flex;justify-content:space-between">
  <span>E. &amp; O.E.</span><span>For {v['name']}<br><span class=ink style="font-size:30px">T. Wells</span></span></div>
</div>
<script>  // wobble every handwritten letter a little, the way a pen does
 let s = 7; const rnd = () => (s = (s * 9301 + 49297) % 233280) / 233280;
 document.querySelectorAll('tr.ink td').forEach(td => td.classList.add('ink'));
 document.querySelectorAll('.ink').forEach(el => {{
  if (el.children.length) return;
  el.innerHTML = [...el.textContent].map(c => c === ' ' ? ' ' :
   `<span style="display:inline-block;transform:translateY(${{(rnd()-.5)*3}}px) rotate(${{(rnd()-.5)*7}}deg);font-size:${{94+rnd()*12}}%">${{c}}</span>`).join('');
 }});
</script></body></html>"""


# ---------- rendering ----------
def browser():
    for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              shutil.which("chromium"), shutil.which("google-chrome"), shutil.which("msedge")):
        if p and Path(p).exists():
            return p
    sys.exit("Need Edge or Chrome to render invoices.")


def render(html, png, size):
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "page.html"
        src.write_text(html, encoding="utf-8")
        subprocess.run([browser(), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        f"--user-data-dir={tmp}/profile", "--force-device-scale-factor=2",
                        f"--window-size={size[0]},{size[1]}", f"--screenshot={png}", src.as_uri()],
                       check=True, capture_output=True, timeout=120)


# How bad the phone photo is. 1 = a decent shot on a counter; 4 = dim, shaken, tiny.
PHOTO = {1: dict(blur=0.8, noise=5.5, dark=0.00, scale=0.62, tilt=-2.2),
         2: dict(blur=1.6, noise=9.0, dark=0.28, scale=0.50, tilt=3.5),
         3: dict(blur=2.6, noise=14., dark=0.45, scale=0.36, tilt=-6.0),
         4: dict(blur=4.0, noise=22., dark=0.62, scale=0.24, tilt=9.0)}


def phone_photo(src, dst, level=1, seed=3):
    """Flat page -> a bill photographed on a counter: tilt, perspective, light falloff, grain."""
    p = PHOTO[level]
    rnd = random.Random(seed)
    page = Image.open(src).convert("RGB")
    w, h = page.size
    W, H = int(w * 1.22), int(h * 1.16)
    base = np.random.default_rng(seed).normal(0, 6, (H, W, 1)) + np.array([92, 78, 64])  # counter top
    canvas = Image.fromarray(np.clip(base, 0, 255).astype("uint8"))
    shadow = Image.new("L", (W, H), 0)
    ox, oy = (W - w) // 2, (H - h) // 2
    ImageDraw.Draw(shadow).rectangle([ox + 18, oy + 26, ox + w + 18, oy + h + 26], fill=150)
    canvas.paste((30, 24, 20), (0, 0), shadow.filter(ImageFilter.GaussianBlur(28)))
    canvas.paste(page, (ox, oy))
    j = lambda a: a * rnd.uniform(0.8, 1.2)  # camera held a bit low and to the left
    quad = (j(70), j(40), j(30), H - j(60), W - j(20), H - j(25), W - j(85), j(70))
    photo = canvas.transform((W, H), Image.QUAD, quad, Image.BICUBIC).rotate(p["tilt"], Image.BICUBIC, expand=False)
    a = np.asarray(photo).astype("float32")
    yy, xx = np.mgrid[0:H, 0:W]
    light = 1.08 - 0.30 * ((xx / W) * 0.55 + (yy / H) * 0.45)  # window top-left
    light -= 0.18 * np.exp(-(((xx - W * .72) / (W * .25)) ** 2 + ((yy - H * .62) / (H * .3)) ** 2))  # hand shadow
    a = a * light[..., None] * np.array([1.03, 1.0, 0.93]) * (1 - p["dark"])
    a += np.random.default_rng(seed + 1).normal(0, p["noise"], a.shape)  # sensor noise
    photo = Image.fromarray(np.clip(a, 0, 255).astype("uint8")).filter(ImageFilter.GaussianBlur(p["blur"]))
    photo = photo.resize((int(W * p["scale"]), int(H * p["scale"])), Image.LANCZOS)
    photo.save(dst, "JPEG", quality=78 if level < 3 else 60)


# ---------- the sets ----------
TAMIL = {"invoice": "வரி விலைப்பட்டியல்", "no": "பில் எண்", "date": "தேதி", "bill_to": "வாங்குபவர்",
         "item": "பொருள் விவரம்", "qty": "அளவு", "rate": "விலை (₹)", "amt": "தொகை (₹)",
         "subtotal": "மொத்தம் (வரிக்கு முன்)", "gst": "மொத்த GST",
         "total": "செலுத்த வேண்டிய தொகை", "words": "தொகை (எழுத்தில்)", "bank": "வங்கி விவரங்கள்",
         "holder": "கணக்கு வைத்திருப்பவர்", "acct": "கணக்கு எண்", "bankname": "வங்கி",
         "sign": "அங்கீகரிக்கப்பட்ட கையொப்பம்", "thanks": "நன்றி, மீண்டும் வருக."}
HINDI = {"invoice": "कर बीजक", "no": "बिल संख्या", "date": "दिनांक", "due": "भुगतान तिथि", "bill_to": "क्रेता",
         "item": "विवरण", "qty": "मात्रा", "rate": "दर (₹)", "amt": "राशि (₹)",
         "subtotal": "उप-योग", "gst": "कुल GST", "total": "कुल देय राशि", "words": "राशि (शब्दों में)",
         "bank": "भुगतान हेतु बैंक विवरण", "holder": "खाताधारक", "acct": "खाता संख्या", "bankname": "बैंक",
         "sign": "अधिकृत हस्ताक्षरकर्ता", "thanks": "धन्यवाद।"}

DOE_LINES = [("PVC pipe 1 inch, 6 m", "3917", 40, 250), ("PVC elbow 1 inch", "3917", 100, 18),
             ("Brass ball valve 1 inch", "8481", 10, 420)]
HOPE_NEW_ACCT = {"acct": "026291800001190", "ifsc": "YESB0000262", "bank": "Yes Bank, Anna Salai"}
OK = ["PAY"]
SAFE = ["PAY", "ASK"]  # a bad photo may be read or may be asked about; it must never be paid wrongly

# file, expected, accepted results, trap, invoice
DEMO = [
    ("inv01_doe.png", "PAY", OK, "clean, English",
     dict(vendor=DOE, no="DH-0101", date="12-11-2026", lines=DOE_LINES)),
    ("inv02_wells.png", "PAY", ["PAY", "LATER"], "clean, vendor name and labels in Tamil",
     dict(vendor=WELLS, no="WP/77", date="05/11/2026", brand="வெல்ஸ் பெயிண்ட்ஸ்", labels=TAMIL, accent="#0e7a5a",
          words_text="ஐம்பத்தொன்பதாயிரம் ரூபாய் மட்டும்",
          lines=[("Enamel paint 20 L (Brilliant White)", "3208", 8, 4500), ("Wall primer 20 L", "3209", 7, 2000)])),
    ("inv03_hope.png", "PAY", OK, "clean, vendor name and labels in Hindi",
     dict(vendor=HOPE, no="HE-305", date="14.11.2026", due="30.11.2026", brand="होप इलेक्ट्रिकल्स", labels=HINDI,
          accent="#b5541c", words_text="तेईस हज़ार एक सौ सत्तासी रुपये मात्र",
          lines=[("LED panel 12 W", "9405", 30, 350), ("MCB 32 A single pole", "8536", 20, 240),
                 ("Copper wire 1.5 sq mm, 90 m coil", "8544", 3, 1450)])),
    ("inv04_hope.png", "STOP", ["STOP"], "changed account: Hope Electricals asks to be paid into 026291800001190",
     dict(vendor=HOPE, pay_to=HOPE_NEW_ACCT, no="HE-310", date="2026-11-15", due="2026-11-29", accent="#b5541c",
          note="Please note: our bank account has changed. Kindly pay only to the new account below.",
          lines=[("Ceiling fan 1200 mm", "8414", 10, 1600), ("Modular switch board 6 way", "8537", 20, 200)])),
    ("inv05_wells.png", "STOP", ["STOP"], "wrong arithmetic: 20,000 + 3,600 GST shown as total 26,300",
     dict(vendor=WELLS, no="WP/78", date="10/11/2026", accent="#0e7a5a", total=26300,
          lines=[("Enamel paint 20 L (Signal Red)", "3208", 5, 4000)])),
    ("inv06_doe.png", "STOP", ["STOP"], "duplicate in disguise: inv01 again as dh/101, date 12 Nov 2026, new layout",
     dict(vendor=DOE, no="dh/101", date="12 Nov 2026", lines=DOE_LINES, cls="plain", accent="#000")),
    ("inv07_jane.png", "STOP", ["STOP"], "mismatched name: Jane D Traders asks to be paid into John Doe's account",
     dict(vendor=JANE, no="JDT-21", date="16/11/2026", accent="#6b3fa0",
          lines=[("GI pipe 1/2 inch, 6 m", "7306", 20, 480), ("Gate valve 1/2 inch", "8481", 12, 200)])),
    ("inv08_wells.jpg", "PAY", OK, "clean, generated handwritten-style bill-book page made to look like a phone photo",
     dict(vendor=WELLS, no="512", date="18/11/26", hand=True, photo=1,
          lines=[("Thinner 5 L", "", 6, 600), ("Wall putty 40 kg", "", 4, 1100)])),
    ("inv09_hope.png", "STOP", ["STOP"], "one digit off: Hope Electricals' account printed as 388108022659 (on file: 388108022658), no warning note",
     dict(vendor=HOPE, pay_to={"acct": "388108022659"}, no="HE-312", date="19-11-2026", due="05-12-2026", accent="#b5541c",
          lines=[("Tube light 20 W", "9405", 40, 180), ("Copper wire 2.5 sq mm, 90 m coil", "8544", 2, 1900)])),
]

STRESS = [
    ("st01_hope.png", "STOP", ["STOP"], "amount in words (42,700) disagrees with the figures (47,200)",
     dict(vendor=HOPE, no="HE-318", date="16-11-2026", due="02-12-2026", accent="#b5541c", words_value=42700,
          lines=[("Exhaust fan 300 mm", "8414", 8, 1250), ("LED bulb 9 W", "8539", 300, 100)])),
    ("st02_doe.png", "STOP", ["STOP"], "one line multiplied wrong: 12 x 450 printed as 5,600",
     dict(vendor=DOE, no="DH-0107", date="17-11-2026",
          lines=[("GI elbow 1/2 inch", "7307", 120, 35), ("CPVC pipe 3/4 inch, 3 m", "3917", 12, 450, 5600)])),
    ("st03_wells.png", "PAY", OK, "clean, Hindi invoice with every number in Devanagari digits",
     dict(vendor=WELLS, no="WP/80", date="18/11/2026", brand="वेल्स पेंट्स", labels=HINDI, accent="#0e7a5a",
          digits="deva", words_text="सत्रह हज़ार सात सौ रुपये मात्र",
          lines=[("Distemper 20 kg", "3209", 10, 900), ("Paint brush 4 inch", "9603", 30, 200)])),
    ("st04_doe.png", "PAY", OK, "clean, vendor name misspelled on the letterhead ('Doe Hardwares Supply')",
     dict(vendor=DOE, no="DH-0108", date="19-11-2026", brand="Doe Hardwares Supply",
          lines=[("Teflon tape", "3919", 200, 15), ("Pipe clamp 1 inch", "7326", 150, 20)])),
    ("st05_hope.png", "PAY", OK, "clean",
     dict(vendor=HOPE, no="HE-320", date="17/11/2026", due="03/12/2026", accent="#b5541c",
          lines=[("Extension board 4 socket", "8536", 25, 380)])),
    ("st06_hope.png", "ASK", ["ASK", "STOP"], "same bill as st05 sent again with a new number (HE-321)",
     dict(vendor=HOPE, no="HE-321", date="17/11/2026", due="03/12/2026", accent="#b5541c",
          lines=[("Extension board 4 socket", "8536", 25, 380)])),
    ("st07_wells.jpg", "PAY", SAFE, "clean, handwritten, photographed in poor light and slightly shaken",
     dict(vendor=WELLS, no="518", date="20/11/26", hand=True, photo=2,
          lines=[("Turpentine 1 L", "", 20, 150), ("Sandpaper pack", "", 10, 250)])),
    ("st08_wells.png", "PAY", OK, "clean, total above one lakh, amount in words in lakh notation, Tamil labels",
     dict(vendor=WELLS, no="WP/81", date="19/11/2026", brand="வெல்ஸ் பெயிண்ட்ஸ்", labels=TAMIL, accent="#0e7a5a",
          lines=[("Exterior emulsion 20 L", "3209", 20, 5000)])),
]

LADDER = [  # the same kind of clean bill, photographed worse and worse
    # Every rung is a genuine bill, so it counts as a good bill (PAY). Levels 0-3 may be paid or asked
    # about; level 4 is too poor to pay on what was read, so holding it (ASK or STOP) is also acceptable,
    # but it still counts as a good bill that was not paid.
    (f"lad{lv}_doe.{'png' if lv == 0 else 'jpg'}", "PAY", SAFE if lv < 4 else ["PAY", "ASK", "STOP"],
     f"clean; photo quality {lv} of 4 ({['flat scan', 'good phone photo', 'dim, slight shake', 'dark, blurred, low resolution', 'barely readable'][lv]})",
     dict(vendor=DOE, no=f"DH-02{lv:02d}", date=f"{13 + lv}-11-2026", photo=lv or None,
          lines=[("PVC pipe 1 inch, 6 m", "3917", 10 + 5 * lv, 250), ("Brass ball valve 1 inch", "8481", 4 + lv, 420)]))
    for lv in range(5)
]

# All 22 languages of the Eighth Schedule are read by Sarvam Document AI; Hindi and Tamil are in the
# demo set, so here are the other 20. Labels: invoice, no, date, total, words, bank, holder, account.
# `words` is the amount in words for 11,800 in that language; None = printed in English instead
# (common on Indian invoices, and safer where our own spelling is not native-checked).
# `review` = labels written best-effort; a native speaker should glance at them.
LANGS = [
    ("bn-IN", "Bengali", DOE, "ডো হার্ডওয়্যার সাপ্লাইজ",
     ("ট্যাক্স ইনভয়েস", "চালান নং", "তারিখ", "মোট প্রদেয়", "কথায়", "ব্যাংকের বিবরণ", "অ্যাকাউন্টধারী", "অ্যাকাউন্ট নম্বর"),
     "এগারো হাজার আটশো টাকা মাত্র", False),
    ("te-IN", "Telugu", WELLS, "వెల్స్ పెయింట్స్",
     ("పన్ను ఇన్వాయిస్", "బిల్లు సంఖ్య", "తేదీ", "చెల్లించవలసిన మొత్తం", "అక్షరాలలో", "బ్యాంక్ వివరాలు", "ఖాతాదారు", "ఖాతా సంఖ్య"),
     "పదకొండు వేల ఎనిమిది వందల రూపాయలు మాత్రమే", False),
    ("mr-IN", "Marathi", HOPE, "होप इलेक्ट्रिकल्स",
     ("कर बीजक", "बीजक क्रमांक", "दिनांक", "एकूण देय रक्कम", "अक्षरी", "बँक तपशील", "खातेधारक", "खाते क्रमांक"),
     "अकरा हजार आठशे रुपये फक्त", False),
    ("gu-IN", "Gujarati", DOE, "ડો હાર્ડવેર સપ્લાયઝ",
     ("ટેક્સ ઇન્વૉઇસ", "બિલ નંબર", "તારીખ", "કુલ ચૂકવવાપાત્ર રકમ", "શબ્દોમાં", "બેંક વિગતો", "ખાતાધારક", "ખાતા નંબર"),
     "અગિયાર હજાર આઠસો રૂપિયા પૂરા", False),
    ("kn-IN", "Kannada", WELLS, "ವೆಲ್ಸ್ ಪೇಂಟ್ಸ್",
     ("ತೆರಿಗೆ ಸರಕುಪಟ್ಟಿ", "ಬಿಲ್ ಸಂಖ್ಯೆ", "ದಿನಾಂಕ", "ಪಾವತಿಸಬೇಕಾದ ಒಟ್ಟು ಮೊತ್ತ", "ಅಕ್ಷರಗಳಲ್ಲಿ", "ಬ್ಯಾಂಕ್ ವಿವರಗಳು", "ಖಾತೆದಾರರು", "ಖಾತೆ ಸಂಖ್ಯೆ"),
     "ಹನ್ನೊಂದು ಸಾವಿರದ ಎಂಟು ನೂರು ರೂಪಾಯಿಗಳು ಮಾತ್ರ", False),
    ("ml-IN", "Malayalam", HOPE, "ഹോപ്പ് ഇലക്ട്രിക്കൽസ്",
     ("ടാക്സ് ഇൻവോയ്സ്", "ബിൽ നമ്പർ", "തീയതി", "ആകെ നൽകേണ്ട തുക", "അക്ഷരത്തിൽ", "ബാങ്ക് വിവരങ്ങൾ", "അക്കൗണ്ട് ഉടമ", "അക്കൗണ്ട് നമ്പർ"),
     "പതിനൊന്നായിരത്തി എണ്ണൂറ് രൂപ മാത്രം", False),
    ("od-IN", "Odia", DOE, "ଡୋ ହାର୍ଡୱେର ସପ୍ଲାଇଜ",
     ("ଟିକସ ଇନଭଏସ", "ବିଲ ନମ୍ବର", "ତାରିଖ", "ମୋଟ ଦେୟ ରାଶି", "ଅକ୍ଷରରେ", "ବ୍ୟାଙ୍କ ବିବରଣୀ", "ଖାତାଧାରୀ", "ଖାତା ନମ୍ବର"),
     "ଏଗାର ହଜାର ଆଠ ଶହ ଟଙ୍କା ମାତ୍ର", False),
    ("pa-IN", "Punjabi", WELLS, "ਵੈੱਲਜ਼ ਪੇਂਟਸ",
     ("ਟੈਕਸ ਇਨਵੌਇਸ", "ਬਿੱਲ ਨੰਬਰ", "ਮਿਤੀ", "ਕੁੱਲ ਭੁਗਤਾਨ ਯੋਗ ਰਕਮ", "ਸ਼ਬਦਾਂ ਵਿੱਚ", "ਬੈਂਕ ਵੇਰਵੇ", "ਖਾਤਾ ਧਾਰਕ", "ਖਾਤਾ ਨੰਬਰ"),
     "ਗਿਆਰਾਂ ਹਜ਼ਾਰ ਅੱਠ ਸੌ ਰੁਪਏ ਮਾਤਰ", False),
    ("as-IN", "Assamese", HOPE, "হ'প ইলেকট্ৰিকেলছ",
     ("কৰ চালান", "চালান নং", "তাৰিখ", "মুঠ দেয় ধন", "আখৰত", "বেংকৰ বিৱৰণ", "একাউণ্টধাৰী", "একাউণ্ট নম্বৰ"),
     "এঘাৰ হাজাৰ আঠশ টকা মাত্ৰ", False),
    ("ur-IN", "Urdu", DOE, "ڈو ہارڈویئر سپلائیز",
     ("ٹیکس انوائس", "بل نمبر", "تاریخ", "کل قابل ادا رقم", "الفاظ میں", "بینک کی تفصیلات", "کھاتہ دار", "کھاتہ نمبر"),
     "گیارہ ہزار آٹھ سو روپے صرف", False),
    ("ne-IN", "Nepali", WELLS, "वेल्स पेन्ट्स",
     ("कर बीजक", "बिल नम्बर", "मिति", "जम्मा तिर्नुपर्ने रकम", "अक्षरमा", "बैंक विवरण", "खातावाला", "खाता नम्बर"),
     "एघार हजार आठ सय रुपैयाँ मात्र", False),
    ("kok-IN", "Konkani", HOPE, "होप इलॅक्ट्रिकल्स",
     ("कर बिल", "बिल क्रमांक", "तारीख", "एकूण रक्कम", "उतरांनी", "बँके तपशील", "खातेदार", "खातो क्रमांक"), None, True),
    ("mai-IN", "Maithili", DOE, "डो हार्डवेयर सप्लाइज",
     ("कर बीजक", "बिल संख्या", "तिथि", "कुल देय राशि", "शब्दमे", "बैंक विवरण", "खाताधारी", "खाता संख्या"), None, True),
    ("sa-IN", "Sanskrit", WELLS, "वेल्स्-पेण्ट्स्",
     ("करपत्रम्", "पत्रसङ्ख्या", "दिनाङ्कः", "देयः सम्पूर्णराशिः", "अक्षरैः", "वित्तकोषविवरणम्", "लेखाधारकः", "लेखासङ्ख्या"), None, True),
    ("doi-IN", "Dogri", HOPE, "होप इलैक्ट्रिकल्स",
     ("टैक्स बिल", "बिल नंबर", "तरीक", "कुल देनी रकम", "अक्खरें च", "बैंक ब्यौरा", "खाता धारक", "खाता नंबर"), None, True),
    ("brx-IN", "Bodo", DOE, "डो हार्डवेयार साप्लाइज",
     ("ट्याक्स बिल", "बिल नम्बर", "तारिख", "गासै रां", "सोदोबआव", "बेंकनि बिबुं", "खाता गिरि", "खाता नम्बर"), None, True),
    ("ks-IN", "Kashmiri", WELLS, "ویلز پینٹس",
     ("ٹیکس بِل", "بِل نَمبَر", "تأریخ", "کُل رقم", "لفظن منٛز", "بینکُک تفصیل", "کھاتہٕ دار", "کھاتہٕ نَمبَر"), None, True),
    ("sd-IN", "Sindhi", HOPE, "هوپ اليڪٽريڪلز",
     ("ٽيڪس انوائس", "بل نمبر", "تاريخ", "ڪل ادا ڪرڻ واري رقم", "لفظن ۾", "بئنڪ جو تفصيل", "کاتي دار", "کاتي نمبر"), None, True),
    ("mni-IN", "Manipuri (Meitei script)", DOE, "ꯗꯣ ꯍꯥꯔꯗꯋꯦꯌꯥꯔ ꯁꯄ꯭ꯂꯥꯏꯖ",
     ("ꯇꯦꯛꯁ ꯏꯅꯚꯣꯏꯁ", "ꯕꯤꯜ ꯅꯝꯕꯔ", "ꯇꯥꯡ", "ꯄꯨꯟꯅꯥ ꯁꯦꯜ", "ꯋꯥꯍꯩꯗꯥ", "ꯕꯦꯉ꯭ꯛ ꯃꯔꯣꯜ", "ꯈꯥꯇꯥ ꯂꯩꯕꯥ", "ꯈꯥꯇꯥ ꯅꯝꯕꯔ"), None, True),
    ("sat-IN", "Santali (Ol Chiki script)", WELLS, "ᱣᱮᱞᱥ ᱯᱮᱱᱴᱥ",
     ("ᱴᱮᱠᱥ ᱤᱱᱣᱚᱭᱮᱥ", "ᱵᱤᱞ ᱱᱚᱢᱵᱚᱨ", "ᱛᱟᱨᱤᱠ", "ᱢᱩᱴ ᱴᱟᱠᱟ", "ᱟᱹᱲᱟᱹ ᱛᱮ", "ᱵᱮᱝᱠ ᱵᱤᱵᱨᱚᱬ", "ᱠᱷᱟᱛᱟ ᱫᱟᱨ", "ᱠᱷᱟᱛᱟ ᱱᱚᱢᱵᱚᱨ"), None, True),
]
LANG_LINES = {"v1": [("PVC pipe 1 inch, 6 m", "3917", 32, 250), ("Brass ball valve 1 inch", "8481", 5, 400)],
              "v2": [("Enamel paint 20 L", "3208", 2, 4500), ("Paint brush 4 inch", "9603", 5, 200)],
              "v3": [("LED panel 12 W", "9405", 20, 350), ("MCB 32 A single pole", "8536", 12, 250)]}
LABEL_KEYS = ("invoice", "no", "date", "total", "words", "bank", "holder", "acct")
PREFIX = {"v1": "DH-03", "v2": "WP/1", "v3": "HE-4"}
MULTI = [
    (f"ml{i + 1:02d}_{code.split('-')[0]}.png", "PAY", OK,
     f"clean, {name}" + (" (labels best-effort: native speaker to review; amount in words in English)" if review else ""),
     dict(vendor=v, no=f"{PREFIX[v['id']]}{i + 1:02d}", date=f"{i + 1:02d}/11/2026", brand=brand, lang=code,
          labels=dict(zip(LABEL_KEYS, labels)), words_text=words, accent=["#1f5fa8", "#0e7a5a", "#b5541c"][i % 3],
          lines=LANG_LINES[v["id"]], review=review))
    for i, (code, name, v, brand, labels, words, review) in enumerate(LANGS)
]

SETS = {"demo": (HERE / "invoices", HERE / "invoice_answer_key.json", DEMO),
        "stress": (HERE / "test_sets" / "stress", None, STRESS),
        "ladder": (HERE / "test_sets" / "ladder", None, LADDER),
        "languages": (HERE / "test_sets" / "languages", None, MULTI)}


def make(name):
    out, key_path, items = SETS[name]
    key_path = key_path or out / "invoice_answer_key.json"
    out.mkdir(parents=True, exist_ok=True)
    key = []
    for i, (file, expected, accept, trap, it) in enumerate(items):
        dst = out / file
        if it.get("hand") or it.get("photo"):
            flat = out / "_flat.png"
            if it.get("hand"):
                render(handwritten(it), flat, (900, 1180))
            else:
                render(printed(it), flat, (900, 1273))
            phone_photo(flat, dst, it.get("photo") or 1, seed=3 if name == "demo" else 11 + i)
            flat.unlink()
        else:
            render(printed(it), dst, (900, 1273))
        print(f"made {name}/{file} -> {expected}")
        lang = it.get("lang") or ("hi-IN" if it.get("labels") is HINDI else "ta-IN" if it.get("labels") is TAMIL else "en-IN")
        key.append({"file": file, "expected": expected, "accept": accept, "trap": trap, "language": lang,
                    **({"native_review": True} if it.get("review") else {}), "truth": truth(it)})
    key_path.write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(key)} invoices to {out} and {key_path.name}")


def main(argv):
    names = argv[1:] or ["demo"]
    for n in (list(SETS) if names == ["all"] else names):
        if n not in SETS:
            sys.exit(f"unknown set {n}; choose from {', '.join(SETS)} or all")
        make(n)


if __name__ == "__main__":
    main(sys.argv)

"""Make the demo invoice set: 4 clean bills and 4 traps, in English, Tamil and Hindi.

  python make_invoices.py            -> payright/invoices/*.png|jpg + invoice_answer_key.json

Each invoice is laid out as HTML and rendered by a headless Edge/Chrome, because the
browser shapes Tamil and Devanagari correctly. The handwritten bill is then made to
look like a phone photo (tilt, perspective, uneven light, grain, JPEG).

The Cashfree sandbox only pays these three accounts, so every invoice uses them.
File names are neutral on purpose: the trap is listed only in the answer key.
"""
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).parent
OUT = HERE / "invoices"
BUYER = ("Sri Ganesh Hardware Wholesale", "14, Godown Street, Parrys, Chennai 600001", "33AAFCS7788Q1Z3")

DOE = dict(name="Doe Hardware Supplies", gstin="33ABCDE1234F1Z5", holder="John Doe",
           acct="026291800001191", ifsc="YESB0000262", bank="Yes Bank, Anna Salai",
           addr="22, Mint Street, Sowcarpet, Chennai 600079", phone="99999 99999")
WELLS = dict(name="Wells Paints and Chemicals", gstin="33FGHIJ5678K1Z2", holder="Tom Wells",
             acct="1233943142", ifsc="ICIC0000009", bank="ICICI Bank, T. Nagar",
             addr="7/3, Ranganathan Street, T. Nagar, Chennai 600017", phone="99999 99999")
HOPE = dict(name="Hope Electricals", gstin="33KLMNO9012P1Z8", holder="Bob Hope",
            acct="388108022658", ifsc="ICIC0000009", bank="ICICI Bank, Ritchie Street",
            addr="41, Ritchie Street, Mount Road, Chennai 600002", phone="99999 99999")


# ---------- numbers ----------
def inr(n):
    """18880 -> '18,880.00' in Indian grouping."""
    s = f"{n:.2f}"
    whole, frac = s.split(".")
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


def totals(lines, gst=0.18):
    sub = sum(q * r for _, _, q, r in lines)
    tax = round(sub * gst, 2)
    return sub, tax, sub + tax


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


def printed(v, *, title, inv_no, date, lines, labels=None, brand=None, accent="#1f5fa8",
            due=None, words_text=None, total_override=None, note=None, cls="", vendor_gstin=None):
    L = {"invoice": "TAX INVOICE", "no": "Invoice No.", "date": "Date", "due": "Due Date",
         "bill_to": "Bill to", "from": "Seller", "item": "Description", "hsn": "HSN", "qty": "Qty",
         "rate": "Rate (₹)", "amt": "Amount (₹)", "subtotal": "Subtotal", "cgst": "CGST @ 9%",
         "sgst": "SGST @ 9%", "gst": "Total GST", "total": "Total Payable", "words": "Amount in words",
         "bank": "Bank details for payment", "holder": "Account holder", "acct": "Account No.",
         "ifsc": "IFSC", "bankname": "Bank", "sign": "Authorised signatory", "thanks": "Thank you for your business."}
    L.update(labels or {})
    sub, tax, total = totals(lines)
    total = total_override if total_override is not None else total
    rows = "".join(
        f"<tr><td>{i}. {d}</td><td>{h}</td><td class=n>{q}</td><td class=n>{inr(r)}</td>"
        f"<td class=n>{inr(q * r)}</td></tr>" for i, (d, h, q, r) in enumerate(lines, 1))
    due_html = f"<div><b>{L['due']}</b> {due}</div>" if due else ""
    note_html = f"<div class=note>{note}</div>" if note else ""
    return f"""<!doctype html><html><head><meta charset=utf-8><style>{CSS}</style></head>
<body class="{cls}" style="--accent:{accent}"><div class=page>
 <div class=head>
  <div><div class=brand>{brand or v['name']}</div>
   <div class=sub>{v['addr']}<br>Ph: {v['phone']} &nbsp;·&nbsp; GSTIN: <span class=mono>{vendor_gstin or v['gstin']}</span></div></div>
  <div class=doc><div class=t>{L['invoice']}</div>
   <div class=meta><div><b>{L['no']}</b> {inv_no}</div><div><b>{L['date']}</b> {date}</div>{due_html}</div></div>
 </div>
 <div class=parties>
  <div class=box><div class=lbl>{L['bill_to']}</div><b>{BUYER[0]}</b><br>{BUYER[1]}<br>GSTIN: <span class=mono>{BUYER[2]}</span></div>
 </div>
 <table><tr><th>{L['item']}</th><th>{L['hsn']}</th><th class=n>{L['qty']}</th><th class=n>{L['rate']}</th><th class=n>{L['amt']}</th></tr>{rows}</table>
 <table class=sum>
  <tr><td>{L['subtotal']}</td><td class=n>{inr(sub)}</td></tr>
  <tr><td>{L['cgst']}</td><td class=n>{inr(tax / 2)}</td></tr>
  <tr><td>{L['sgst']}</td><td class=n>{inr(tax / 2)}</td></tr>
  <tr><td>{L['gst']}</td><td class=n>{inr(tax)}</td></tr>
  <tr class=grand><td>{L['total']}</td><td class=n>₹ {inr(total)}</td></tr>
 </table>
 <div class=words><b>{L['words']}:</b> {words_text or words(total)}</div>
 <div class=bank><div class=box><div class=lbl>{L['bank']}</div>
  {L['holder']}: <b>{v['holder']}</b><br>{L['acct']}: <span class=mono><b>{v['acct']}</b></span><br>
  {L['ifsc']}: <span class=mono><b>{v['ifsc']}</b></span><br>{L['bankname']}: {v['bank']}</div></div>
 {note_html}
 <div class=foot><div>{L['thanks']}</div>
  <div class=sign><div class=s>{v['holder']}</div><div class=l>{L['sign']}</div></div></div>
</div></body></html>"""


# ---------- handwritten bill-book page ----------
def handwritten(v, *, inv_no, date, lines):
    sub, tax, total = totals(lines)
    rows = "".join(f"<tr><td>{d}</td><td class=n>{q}</td><td class=n>{r:g}</td><td class=n>{q * r:g}</td></tr>"
                   for d, _, q, r in lines)
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
 <div class=row><span>No. <span class=ink>{inv_no}</span></span><span>Date <span class=ink>{date}</span></span></div>
 <div class=row><span>M/s. <span class=ink>{BUYER[0]}, Parrys</span></span></div>
 <table><tr><th style="width:52%">Particulars</th><th>Qty</th><th>Rate</th><th>Amount</th></tr>
  {''.join(f'<tr class=ink>{r}' for r in rows.split('<tr>')[1:])}
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
 document.querySelectorAll('.ink').forEach(el => {{
  if (el.tagName === 'TR') return el.querySelectorAll('td').forEach(td => td.classList.add('ink'));
 }});
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


def phone_photo(src, dst, seed=3):
    """Flat scan -> a bill photographed on a counter: tilt, perspective, light falloff, grain."""
    rnd = random.Random(seed)
    page = Image.open(src).convert("RGB")
    w, h = page.size
    W, H = int(w * 1.22), int(h * 1.16)
    # counter top: dark laminate with a little texture
    base = np.random.default_rng(seed).normal(0, 6, (H, W, 1)) + np.array([92, 78, 64])
    canvas = Image.fromarray(np.clip(base, 0, 255).astype("uint8"))
    # soft shadow under the paper
    shadow = Image.new("L", (W, H), 0)
    ox, oy = (W - w) // 2, (H - h) // 2
    ImageDraw.Draw(shadow).rectangle([ox + 18, oy + 26, ox + w + 18, oy + h + 26], fill=150)
    canvas.paste((30, 24, 20), (0, 0), shadow.filter(ImageFilter.GaussianBlur(28)))
    # a slightly curled page: tiny wave on the paper, then pasted
    canvas.paste(page, (ox, oy))
    # perspective: camera held a bit low and to the left
    j = lambda a: a * rnd.uniform(0.8, 1.2)
    quad = (j(70), j(40), j(30), H - j(60), W - j(20), H - j(25), W - j(85), j(70))
    photo = canvas.transform((W, H), Image.QUAD, quad, Image.BICUBIC).rotate(-2.2, Image.BICUBIC, expand=False)
    a = np.asarray(photo).astype("float32")
    # uneven light: brighter top-left (window), darker bottom-right, warm cast
    yy, xx = np.mgrid[0:H, 0:W]
    light = 1.08 - 0.30 * ((xx / W) * 0.55 + (yy / H) * 0.45)
    light -= 0.18 * np.exp(-(((xx - W * .72) / (W * .25)) ** 2 + ((yy - H * .62) / (H * .3)) ** 2))  # hand shadow
    a = a * light[..., None] * np.array([1.03, 1.0, 0.93])
    a += np.random.default_rng(seed + 1).normal(0, 5.5, a.shape)  # sensor noise
    photo = Image.fromarray(np.clip(a, 0, 255).astype("uint8")).filter(ImageFilter.GaussianBlur(0.8))
    photo = photo.resize((int(W * 0.62), int(H * 0.62)), Image.LANCZOS)  # phone-ish resolution
    photo.save(dst, "JPEG", quality=78)


# ---------- the set ----------
TAMIL = {"invoice": "வரி விலைப்பட்டியல்", "no": "பில் எண்", "date": "தேதி", "bill_to": "வாங்குபவர்",
         "item": "பொருள் விவரம்", "hsn": "HSN", "qty": "அளவு", "rate": "விலை (₹)", "amt": "தொகை (₹)",
         "subtotal": "மொத்தம் (வரிக்கு முன்)", "cgst": "CGST @ 9%", "sgst": "SGST @ 9%", "gst": "மொத்த GST",
         "total": "செலுத்த வேண்டிய தொகை", "words": "தொகை (எழுத்தில்)", "bank": "வங்கி விவரங்கள்",
         "holder": "கணக்கு வைத்திருப்பவர்", "acct": "கணக்கு எண்", "ifsc": "IFSC", "bankname": "வங்கி",
         "sign": "அங்கீகரிக்கப்பட்ட கையொப்பம்", "thanks": "நன்றி, மீண்டும் வருக."}
HINDI = {"invoice": "कर बीजक", "no": "बिल संख्या", "date": "दिनांक", "due": "भुगतान तिथि", "bill_to": "क्रेता",
         "item": "विवरण", "hsn": "HSN", "qty": "मात्रा", "rate": "दर (₹)", "amt": "राशि (₹)",
         "subtotal": "उप-योग", "cgst": "CGST @ 9%", "sgst": "SGST @ 9%", "gst": "कुल GST",
         "total": "कुल देय राशि", "words": "राशि (शब्दों में)", "bank": "भुगतान हेतु बैंक विवरण",
         "holder": "खाताधारक", "acct": "खाता संख्या", "ifsc": "IFSC", "bankname": "बैंक",
         "sign": "अधिकृत हस्ताक्षरकर्ता", "thanks": "धन्यवाद।"}

DOE_LINES = [("PVC pipe 1 inch, 6 m", "3917", 40, 250), ("PVC elbow 1 inch", "3917", 100, 18),
             ("Brass ball valve 1 inch", "8481", 10, 420)]

INVOICES = [
    # file, expected, trap, html-builder kwargs
    ("inv01_doe.png", "PAY", "clean, English", lambda: printed(
        DOE, title="", inv_no="DH-0101", date="12-11-2026", lines=DOE_LINES, accent="#1f5fa8")),
    ("inv02_wells.png", "PAY", "clean, vendor name and labels in Tamil", lambda: printed(
        WELLS, title="", inv_no="WP/77", date="05/11/2026", brand="வெல்ஸ் பெயிண்ட்ஸ்", labels=TAMIL,
        accent="#0e7a5a", words_text="ஐம்பத்தொன்பதாயிரம் ரூபாய் மட்டும்",
        lines=[("Enamel paint 20 L (Brilliant White)", "3208", 8, 4500), ("Wall primer 20 L", "3209", 7, 2000)])),
    ("inv03_hope.png", "PAY", "clean, vendor name and labels in Hindi", lambda: printed(
        HOPE, title="", inv_no="HE-305", date="14.11.2026", due="30.11.2026", brand="होप इलेक्ट्रिकल्स",
        labels=HINDI, accent="#b5541c", words_text="तेईस हज़ार एक सौ सत्तासी रुपये मात्र",
        lines=[("LED panel 12 W", "9405", 30, 350), ("MCB 32 A single pole", "8536", 20, 240),
               ("Copper wire 1.5 sq mm, 90 m coil", "8544", 3, 1450)])),
    ("inv04_hope.png", "STOP", "changed account: Hope Electricals asks to be paid into 026291800001190", lambda: printed(
        {**HOPE, "acct": "026291800001190", "ifsc": "YESB0000262", "bank": "Yes Bank, Anna Salai"},
        title="", inv_no="HE-310", date="2026-11-15", due="2026-11-29", accent="#b5541c",
        note="Please note: our bank account has changed. Kindly pay only to the new account below.",
        lines=[("Ceiling fan 1200 mm", "8414", 10, 1600), ("Modular switch board 6 way", "8537", 20, 200)])),
    ("inv05_wells.png", "STOP", "wrong arithmetic: 20,000 + 3,600 GST shown as total 26,300", lambda: printed(
        WELLS, title="", inv_no="WP/78", date="10/11/2026", accent="#0e7a5a", total_override=26300,
        lines=[("Enamel paint 20 L (Signal Red)", "3208", 5, 4000)])),
    ("inv06_doe.png", "STOP", "duplicate in disguise: inv01 again as dh/101, date 12 Nov 2026, new layout", lambda: printed(
        DOE, title="", inv_no="dh/101", date="12 Nov 2026", lines=DOE_LINES, cls="plain", accent="#000")),
    ("inv07_jane.png", "STOP", "mismatched name: Jane D Traders asks to be paid into John Doe's account", lambda: printed(
        {**DOE, "name": "Jane D Traders", "addr": "5, Narayana Mudali Street, Chennai 600079"},
        vendor_gstin="33PQRST3456U1Z9", title="", inv_no="JDT-21", date="16/11/2026", accent="#6b3fa0",
        lines=[("GI pipe 1/2 inch, 6 m", "7306", 20, 480), ("Gate valve 1/2 inch", "8481", 12, 200)])),
    ("inv08_wells.jpg", "PAY", "clean, handwritten bill-book page, photographed", None),
]


def main():
    OUT.mkdir(exist_ok=True)
    key = []
    for name, expected, trap, build in INVOICES:
        dst = OUT / name
        if build is None:  # the handwritten one
            flat = OUT / "_flat.png"
            render(handwritten(WELLS, inv_no="512", date="18/11/26",
                               lines=[("Thinner 5 L", "", 6, 600), ("Wall putty 40 kg", "", 4, 1100)]),
                   flat, (900, 1180))
            phone_photo(flat, dst)
            flat.unlink()
        else:
            render(build(), dst, (900, 1273))
        print("made", name, "->", expected)
        key.append({"file": name, "expected": expected, "trap": trap})
    (HERE / "invoice_answer_key.json").write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(key)} invoices to {OUT} and invoice_answer_key.json")


if __name__ == "__main__":
    main()

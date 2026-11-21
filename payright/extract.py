"""Read invoice images with Sarvam Document AI -> invoices.json (input for check.py).

  set SARVAM_API_KEY in payright/.env, then:
  python extract.py invoices_folder [ta-IN]

The reader only reads. Fields it is not confident about are listed in
`unsure_fields`, so check.py asks a person instead of guessing.
"""
import json
import os
import sys
import time
from pathlib import Path

import requests

API = "https://api.sarvam.ai/doc-ai/v1/job"
MIN_CONFIDENCE = 0.8  # tune on real invoices: the docs do not state the scale, 0-1 assumed
S, N = {"type": "string"}, {"type": "number"}
SCHEMA = {"type": "object", "properties": {
    "vendor_name": {**S, "description": "Name of the seller who issued the invoice, exactly as written, in the original script"},
    "vendor_name_latin": {**S, "description": "The seller's name written in English letters"},
    "gstin": {**S, "description": "Seller's GSTIN, 15 characters"},
    "invoice_no": {**S, "description": "Invoice or bill number, exactly as written"},
    "invoice_date": {**S, "description": "Invoice date, exactly as written"},
    "due_date": {**S, "description": "Payment due date, exactly as written, empty if none"},
    "lines": {"type": "array", "description": "One entry per line item", "items": {"type": "object", "properties": {
        "description": {**S, "description": "Item description"},
        "qty": {**N, "description": "Quantity"},
        "rate": {**N, "description": "Price per unit in rupees"},
        "amount": {**N, "description": "Line amount in rupees"}}}},
    "subtotal": {**N, "description": "Total before tax, in rupees"},
    "tax": {**N, "description": "Total tax (GST) in rupees"},
    "total": {**N, "description": "Final amount payable in figures, in rupees"},
    "total_in_words_text": {**S, "description": "The amount written in words, exactly as written, in the original script"},
    "total_in_words_value": {**N, "description": "The amount written in words converted to a number in rupees, empty if there is no amount in words"},
    "bank_account": {**S, "description": "Seller's bank account number for payment, exactly as written"},
    "ifsc": {**S, "description": "IFSC code of the seller's bank"},
    "account_holder": {**S, "description": "Bank account holder name, if written"},
}}


def read(path, key, language):
    h = {"api-subscription-key": key}
    with open(path, "rb") as f:
        r = requests.post(f"{API}/extract", headers=h, files={"file": (path.name, f)},
                          data={"schema": json.dumps(SCHEMA), "language": language, "output_format": "json",
                                "mode": "advanced"})  # Sarvam's higher-accuracy mode; 2.5 credits a page
    r.raise_for_status()
    job = r.json()["job_id"]
    for _ in range(60):  # up to 3 minutes per invoice
        status = requests.get(f"{API}/{job}/status", headers=h).json()["status"].lower()
        if status in ("completed", "partially_completed", "failed", "rejected"):
            break
        time.sleep(3)
    if status not in ("completed", "partially_completed"):
        return {"file": path.name, "unsure_fields": ["whole invoice (reader status: " + status + ")"]}
    out = requests.get(f"{API}/{job}/results", headers=h).json()
    inv = out.get("result") or {}
    notes = out.get("annotations") or {}
    inv["file"] = path.name
    conf = {k: a.get("confidence") for k, a in notes.items() if isinstance(a, dict)}
    inv["confidence"] = conf  # kept for the audit trail
    inv["unsure_fields"] = unsure_fields(conf)
    return inv


def unsure_fields(conf):
    # Only fields nothing else cross-checks. Totals are checked by arithmetic, GSTIN is optional.
    # A missing confidence counts as sure; a confidence of 0 is the least sure there is
    # (on a barely readable photo Sarvam invented an account number and scored it 0).
    return [k for k in ("vendor_name", "invoice_no", "total", "bank_account", "ifsc")
            if conf.get(k) is not None and conf[k] < MIN_CONFIDENCE]


def main():
    here = Path(__file__).parent
    for line in (here / ".env").read_text().splitlines() if (here / ".env").exists() else []:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())
    key = os.environ.get("SARVAM_API_KEY") or sys.exit("Set SARVAM_API_KEY in payright/.env")
    folder = Path(sys.argv[1])
    language = sys.argv[2] if len(sys.argv) > 2 else "en-IN"
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".pdf"))
    invoices = []
    for p in files:
        print("reading", p.name)
        invoices.append(read(p, key, language))
    (here / "invoices.json").write_text(json.dumps(invoices, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote invoices.json ({len(invoices)} invoices). Next: python check.py invoices.json")


if __name__ == "__main__":
    main()

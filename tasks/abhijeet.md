# Abhijeet (thegoodengineer) — repo, glue code, status page

## Now
- [ ] Clone the repo, run `python payright/check.py --selftest` (must print
      "selftest ok") and `python payright/check.py payright/sample_invoices.json`.
- [ ] Never commit `payright/.env` (keys, webhook URL). The repo is public.

## By 1:30
- [ ] `payright/send.py`: read `decisions.json`, and for each PAY invoice
      POST one event to the Relay webhook (`RELAY_WEBHOOK_URL` in `.env`).
      Event fields the Relay agent expects, all inside `{"data": {...}}`:
      `invoice_no, vendor, account_holder, phone, email, bank_account, ifsc,
      address, city, state, pincode, beneficiary_id, amount, transfer_id`.
      Before each POST, append the invoice to `ledger.json` with status SENT
      (write first, send second: a crash must never cause a second payment).
      Take bank details from `vendors.json`, never from the invoice.

## By 2:30 (only after the core works)
- [ ] One static status page: each invoice with PAY / ASK / STOP, the reason,
      and the transfer status. Read `decisions.json`. No framework, no login.
- [ ] If we need Sarvam's call result sent back to us: a Lambda that receives
      the post-call webhook. Name must start with your ID; use the existing
      `<ID>-exec` role; call URL pattern is in the organisers' Lambda guide.

## Not now
- Landing page, auth, database, deploy pipeline. Nothing on the score card
  marks them.

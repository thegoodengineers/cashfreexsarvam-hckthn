# Bhumika — invoices, proof, pitch

## Now: make 8 fake invoices (photos or PDFs) into `payright/invoices/`
The Cashfree sandbox only answers to these accounts, so use only these vendors:

| Vendor on invoice | Account holder | Account number | IFSC |
|---|---|---|---|
| Doe Hardware Supplies | John Doe | 026291800001191 | YESB0000262 |
| Wells Paints and Chemicals | Tom Wells | 1233943142 | ICIC0000009 |
| Hope Electricals | Bob Hope | 388108022658 | ICIC0000009 |

Mix Tamil, Hindi and English; at least one handwritten and photographed.
- [x] 4 clean invoices (one with the vendor name in Tamil or Hindi script)
- [x] Changed account: Hope Electricals with account 026291800001190
- [x] Duplicate in disguise: copy a clean one, change number format
      (DH-0101 -> dh/101) and date format
- [x] Wrong arithmetic: total not equal to subtotal + tax
- [x] Mismatched name: John Doe's account on a bill from "Jane D Traders"

You do not need a Sarvam or Cashfree account. Push the files to the repo (or
send them to Chirag); he runs the reader on his laptop.

Done: 8 invoices in `payright/invoices/`, regenerate with `python payright/make_invoices.py`;
expected results in `payright/invoice_answer_key.json`.

## By 1:45
- [x] Chirag runs the reader and checker on your invoices and sends you the
      output table.
      Done: reader and checker run on the real Sarvam API; results in
      `payright/scoresheet.md`.
- [x] Fill the score sheet: traps planted, traps caught, clean invoices
      wrongly stopped. Real numbers only.

## By 2:45: what the judges must receive
- [x] Design note, half a page: what we chose, what we chose NOT to use and
      why (a model reads, code decides; money only to the account on file;
      one transfer ID per invoice so a retry cannot pay twice).
- [x] One success case and one failure case the agent handled.
- [ ] 6-minute demo script, then run the timer in three rehearsals:
      problem (40 s) -> doctored invoice goes in -> agent refuses and says
      why -> owner approves by phone -> payouts show as successful ->
      run the batch again, nothing is paid twice -> our numbers.
      Written: `docs/judges_pack.md` (PDF: `docs/PayRight_Judges_Pack.pdf`,
      rebuild with `python docs/make_judges_pdf.py`). Still to do: the three timed
      rehearsals; write the times in the table at the end of the pack.

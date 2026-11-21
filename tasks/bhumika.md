# Bhumika — invoices, proof, pitch

## Now: make 8 fake invoices (photos or PDFs) into `payright/invoices/`
The Cashfree sandbox only answers to these accounts, so use only these vendors:

| Vendor on invoice | Account holder | Account number | IFSC |
|---|---|---|---|
| Doe Hardware Supplies | John Doe | 026291800001191 | YESB0000262 |
| Wells Paints and Chemicals | Tom Wells | 1233943142 | ICIC0000009 |
| Hope Electricals | Bob Hope | 388108022658 | ICIC0000009 |

Mix Tamil, Hindi and English; at least one handwritten and photographed.
- [ ] 4 clean invoices (one with the vendor name in Tamil or Hindi script)
- [ ] Changed account: Hope Electricals with account 026291800001190
- [ ] Duplicate in disguise: copy a clean one, change number format
      (DH-0101 -> dh/101) and date format
- [ ] Wrong arithmetic: total not equal to subtotal + tax
- [ ] Mismatched name: John Doe's account on a bill from "Jane D Traders"

You do not need a Sarvam or Cashfree account. Push the files to the repo (or
send them to Chirag); he runs the reader on his laptop.

## By 1:45
- [ ] Chirag runs the reader and checker on your invoices and sends you the
      output table.
- [ ] Fill the score sheet: traps planted, traps caught, clean invoices
      wrongly stopped. Real numbers only.

## By 2:45: what the judges must receive
- [ ] Design note, half a page: what we chose, what we chose NOT to use and
      why (a model reads, code decides; money only to the account on file;
      one transfer ID per invoice so a retry cannot pay twice).
- [ ] One success case and one failure case the agent handled.
- [ ] 6-minute demo script, then run the timer in three rehearsals:
      problem (40 s) -> doctored invoice goes in -> agent refuses and says
      why -> owner approves by phone -> payouts show as successful ->
      run the batch again, nothing is paid twice -> our numbers.

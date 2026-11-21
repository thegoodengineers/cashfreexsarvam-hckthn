# PayRight: the agent that says no

Cashfree x Sarvam Buildathon, 21 Nov 2026, Problem Statement 3: *Pay the right bill, to the right person.*
Team The Good Engineers: Chirag, Abhijeet, Bhumika, Ayush.

**A model reads, code decides, a person approves, and money only goes to the account we already have on file.**

## What is new here

This is not a model with a payout button. The model only reads; everything below is plain code or a person.

| What | Why it is different | Proof |
|---|---|---|
| **The owner says the total aloud** | A yes, a tap or an OTP is not approval. The voice agent names every stopped bill and its reason in the owner's language, and the spoken total has to match. | [payright/voice/test_calls.md](payright/voice/test_calls.md), [payright/approve.py](payright/approve.py) |
| **It attacks itself** | 1,000 forged variants of real bills on a number you choose, decided by the same code that guards the money. | [Attack it at scale](https://giants-made-stamp-wines.trycloudflare.com/try#attack), `python payright/attack.py 1000 7` |
| **It closed the gap its own attack found** | Price memory: what each vendor charged on bills that were really paid. A quiet raise of more than 10% goes to a person. | `python payright/pricebook.py --selftest`, numbers under Measured |
| **It repairs the reader's slips by rule** | O read as 0 in a GSTIN no longer hides a vendor. An invented GSTIN fails its own check digit and the refusal says so. | `python payright/check.py --selftest` |
| **Every refusal names its trick** | A stopped bill shows the two values compared, the known fraud it matches, and the real reported case. | [Live board](https://giants-made-stamp-wines.trycloudflare.com/), [It already happened](https://giants-made-stamp-wines.trycloudflare.com/?page=problem) |
| **Deadline first when cash is short** | Bills to micro and small suppliers are ordered by their 15 or 45 day payment deadline; what cash cannot cover waits as LATER. | [payright/check.py](payright/check.py), `plan()` |
| **One bill, one payment, for life** | The transfer ID comes from the invoice, a ledger row is written before the money moves, and a bill is PAID only when Cashfree confirms. | `python payright/send.py --selftest` |

## For judges, start here

| Open this | What you see |
|---|---|
| **[Attack it at scale](https://giants-made-stamp-wines.trycloudflare.com/try#attack)** | Type any number. We forge 1,000 variants of real bills and the real checker decides each one, in under a second. |
| [Try to fool it](https://giants-made-stamp-wines.trycloudflare.com/try) | Tamper with one real bill yourself and see the verdict and the two values compared. |
| [It already happened](https://giants-made-stamp-wines.trycloudflare.com/?page=problem) | 8 real reported fraud cases, each with its source, and what our checker does with the same bill. |
| [Live board](https://giants-made-stamp-wines.trycloudflare.com/) | Every bill of the last run in a Pay / Ask / Stop lane, the owner's call, and what Cashfree confirmed. |
| [Evidence](https://giants-made-stamp-wines.trycloudflare.com/?page=evidence) | Why each bill was refused, and the trail of each payment. |
| [How it works](https://giants-made-stamp-wines.trycloudflare.com/?page=how) | The five steps, and what we chose not to build. |

These links are a tunnel to a team laptop, so they work only while that laptop is serving. To run the same site yourself:

```
python payright/serve.py
```

Then open http://localhost:8765/.

## Measured

- **44 invoices in 23 languages**, two of them real bills, read by the live Sarvam reader: 8 of 8 planted traps caught, 0 wrong payments approved. Report: [docs/evidence/PayRight_Evidence.pdf](docs/evidence/PayRight_Evidence.pdf).
- **58,791 forged variants of real bills across 40 runs: 0 cleared to pay.** All 17,008 harmless rewrites of genuine bills were still cleared. Reproduce one run with `python payright/attack.py 1000 1`.
- **The gap our own attack found, and what we did about it.** Next month's bill with every number raised together agrees with itself, so with no history all 4,201 were cleared. We added price memory: the checker remembers what each vendor charged on bills that were really paid, and sends a raise of more than 10% to a person. With the vendor's last bill on file, 2,501 of the 4,201 are now caught. The other 1,700 are raises of 10% or less, which pass by design, or bills with no readable rates.
- **The reader's slips, repaired by rule.** Sarvam reads the letter O in one vendor's GSTIN as a zero every time. That slip, with an Assamese vendor name, got one genuine bill stopped. The checker now treats O/0, I/1, S/5, B/8, Z/2 and G/6 as the same character in a GSTIN when exactly one vendor fits, and the Assamese bill is cleared: 33 of 34 genuine bills, up from 32. The judges' pack and the evidence PDF were written before this change and still say 32.
- **An invented GSTIN is caught by arithmetic.** A GSTIN carries its own check digit. On the unreadable photo the reader made up a GSTIN; it fails the check digit, and the refusal now says so. A bill with the right vendor name but a different GSTIN goes to a person.
- **Every refusal names its trick.** On the board, a stopped bill says which known fraud it matches and links the real case.
- **Price memory is off until it has learnt.** It needs `python payright/pricebook.py learn payright/invoices.json` after bills are confirmed paid; today's demo batches run without it.

## Read more

- [docs/judges_pack.md](docs/judges_pack.md): design note, one success and one failure case, the evidence table, the demo script.
- [docs/RUNBOOK.md](docs/RUNBOOK.md): the exact demo commands and the fallback for each step.
- [payright/check.py](payright/check.py): the code that decides Pay / Ask / Stop. No model is involved.
- [payright/attack.py](payright/attack.py): the forgery attack on our own checker.
- [payright/pricebook.py](payright/pricebook.py): price memory, learnt only from bills Cashfree confirmed paid.

Sandbox only, synthetic vendor data. Paid means Cashfree confirmed the transfer.

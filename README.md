# PayRight: the agent that says no

Cashfree x Sarvam Buildathon, 21 Nov 2026, Problem Statement 3: *Pay the right bill, to the right person.*
Team The Good Engineers: Chirag, Abhijeet, Bhumika, Ayush.

**A model reads, code decides, a person approves, and money only goes to the account we already have on file.**

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
- **58,797 forged variants of real bills across 40 runs: 0 cleared to pay.** All 16,964 harmless rewrites of genuine bills were still cleared. Reproduce one run with `python payright/attack.py 1000 1`.
- **The gap our own attack found, and what we did about it.** Next month's bill with every number raised together agrees with itself, so with no history all 4,239 were cleared. We added price memory: the checker remembers what each vendor charged on bills that were really paid, and sends a raise of more than 10% to a person. With the vendor's last bill on file, 2,530 of the 4,239 are now caught. The other 1,709 are raises of 10% or less, which pass by design, or bills with no readable rates.
- **Price memory is off until it has learnt.** It needs `python payright/pricebook.py learn payright/invoices.json` after bills are confirmed paid; today's demo batches run without it.

## Read more

- [docs/judges_pack.md](docs/judges_pack.md): design note, one success and one failure case, the evidence table, the demo script.
- [docs/RUNBOOK.md](docs/RUNBOOK.md): the exact demo commands and the fallback for each step.
- [payright/check.py](payright/check.py): the code that decides Pay / Ask / Stop. No model is involved.
- [payright/attack.py](payright/attack.py): the forgery attack on our own checker.
- [payright/pricebook.py](payright/pricebook.py): price memory, learnt only from bills Cashfree confirmed paid.

Sandbox only, synthetic vendor data. Paid means Cashfree confirmed the transfer.

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
- **62,054 forged variants of real bills across 40 runs: 0 cleared to pay.** All 13,531 harmless rewrites of genuine bills were still cleared. Reproduce one run with `python payright/attack.py 1000 1`.
- **What we cannot catch:** a bill with every number raised together still agrees with itself (4,415 of 4,415 cleared). Only a purchase order can catch that, and we do not have one.

## Read more

- [docs/judges_pack.md](docs/judges_pack.md): design note, one success and one failure case, the evidence table, the demo script.
- [docs/RUNBOOK.md](docs/RUNBOOK.md): the exact demo commands and the fallback for each step.
- [payright/check.py](payright/check.py): the code that decides Pay / Ask / Stop. No model is involved.
- [payright/attack.py](payright/attack.py): the forgery attack on our own checker.

Sandbox only, synthetic vendor data. Paid means Cashfree confirmed the transfer.

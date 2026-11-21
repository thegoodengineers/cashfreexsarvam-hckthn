# NOW — the one current list (updated 1:50 PM, freeze 3:30 PM)

Every open task appears here exactly once, with one owner. Where an older line
in a personal file says something different, this page wins.

| # | Task | Owner | By |
|---|---|---|---|
| 1 | Get ONE real sandbox payout to succeed. Relay's "Request Transfer (Sync)" is refused by Cashfree (v1 API deprecated). Apply the desk's fix, or replace the step with an HTTP call to Payouts v2 | Chirag + Claude | 2:15 |
| 2 | Desk: enable Secure ID / Verification Suite on the test account; ask about test balance | Chirag | 2:00 |
| 3 | Put the final prompt from `payright/voice/prompt.md` into the agent on CHIRAG's Sarvam account ("PayRight Approval"). That is the only demo agent; the one in Ayush's account is practice | Ayush, at Chirag's laptop | 2:10 |
| 4 | Six real voice calls from that agent's Test panel -> Phone (scenarios 1, 5, 7, 9, 13, 14), logged in `voice/test_calls.md`; confirm the Aparna voice | Ayush | 2:30 |
| 5 | DONE: `call_vars.py` sends `user_name` and every problem per bill; `prompt.md` amounts "in the language you are speaking" + Kannada lines | Ayush | 2:15 |
| 6 | Let `approve.py` read the decision of a call that was started from Sarvam's Test panel (newest attempt for the app), since calls from code have no phone number yet | Abhijeet (IDs from Chirag) | 2:30 |
| 7 | Fix `lambda/status.py:71-75` (unsent rows show as PAID), then build the Pay / Ask / Stop board from real `decisions.json`, ledger and check.py `evidence`; deploy both Lambdas | Abhijeet | 2:30 |
| 8 | Stage fallback: `--fake` must read from a file (it crashes in PowerShell); `send.py` must refuse to pay without an approval; `approve.py` must print errors instead of waiting silently | Abhijeet | 2:30 |
| 9 | Photograph ONE real handwritten invoice and push it; Chirag runs the reader on it | Bhumika | 2:15 |
| 10 | Add the Hope Electricals invoice with account 388108022659 (one digit off) to the demo set and answer key as STOP | Bhumika | 2:15 |
| 11 | Correct `docs/judges_pack.md` lines 6, 24, 30, 31, 40-41, 61, 77-78, 121: nothing may be claimed that has not happened; rebuild the PDF | Bhumika | 2:30 |
| 12 | checker: compare the account-holder name on the invoice with the one on file; stop wrongly blocking a bill issued in the holder's own name; let the CLI find `vendors.json` from any folder | Claude | 2:15 |
| 13 | Ask an organiser: are the three problems today's tracks, is there a fresh invoice batch at demo time, is the demo 10 or 13 minutes | Chirag | 2:15 |
| 14 | Full run on all invoices, then three timed rehearsals and one screen-recorded backup run | Everyone; Bhumika runs the timer | 2:45 to 3:15 |

## Removed as duplicates or already done
- "Rebuild the agent in Chirag's account": not needed, it exists (task 3 replaces it).
- "Caller number blocker": test calls work from the Test panel; only calls from code lack a number (task 6 covers it).
- "Plain status page": replaced by the board (task 7).
- "Run the reader on Bhumika's invoices": done at 1:07 PM, 4 of 4 traps caught, 0 of 4 good bills blocked.
- "One test payout by 1:15": became task 1.

# NOW — the one current list (updated 2:30 PM, freeze 3:30 PM)

**Money has moved.** At 2:26 PM three sandbox payouts went through Relay to Cashfree and
the Payouts dashboard shows "Success 3, Rs 51,507". Proof: `docs/screenshots/4_*.jpg`, `5_*.jpg`.
How: Relay's built-in "Request Transfer (Sync)" is refused by Cashfree (v1 API deprecated),
so the agent now has an HTTP step calling Payouts v2 (`POST /payout/transfers`).

Every open task appears here exactly once, with one owner.

| # | Task | Owner | By |
|---|---|---|---|
| 1 | **Six real VOICE calls** from the agent's Test panel -> Phone (scenarios 1, 5, 7, 9, 13, 14), logged in `voice/test_calls.md`. Only chat tests exist so far; voice is 20 of 100 marks. You now have your own login to Chirag's Sarvam workspace, so call from your own laptop | Ayush | 2:50 |
| 2 | **End-to-end with a real call**: `python payright/new_round.py`, then `python payright/run.py payright/invoices.json --cash 100000 --latest`, place the call from the Test panel, owner says the total, payouts go out. Needs the Sarvam voice-agents API key in Chirag's `.env` | Abhijeet + Ayush + Chirag | 2:55 |
| 3 | Board shows **PAID, Cashfree confirmed**: `python payright/run.py --refresh` after Chirag puts `CASHFREE_PAYOUT_CLIENT_ID` / `CASHFREE_PAYOUT_CLIENT_SECRET` in `.env` and whitelists the laptop's IP in Payouts | Abhijeet (keys and IP: Chirag) | 2:50 |
| 4 | `docs/RUNBOOK.md`: the exact demo commands in order, what each screen shows, and the fallback for each step. One page | Abhijeet | 3:00 |
| 5 | Update `docs/judges_pack.md` and the PDF: a payout HAS completed (3 transfers, Rs 51,507); name the Relay bug we found and routed around; keep "not yet tested" on the voice call until task 1 is done | Bhumika | 2:50 |
| 6 | Remove the three dead v1 steps from the Relay flow so the canvas shows Webhook -> Pay (HTTP v2) only | Claude | 2:45 |
| 7 | Create the Sarvam voice-agents API key; put the Payouts keys in `.env`; whitelist the laptop IP; ask the desk again about Secure ID | Chirag | 2:40 |
| 8 | Three timed rehearsals (run `python payright/new_round.py` before each) and one screen-recorded backup run | Everyone; Bhumika runs the timer | 3:00 to 3:20 |

## Rehearsal rule
An invoice has one transfer ID for life, so Cashfree refuses the same bill twice. Before each
rehearsal run `python payright/new_round.py`: it sets the ledger aside and tags a new round so
the sandbox accepts the demo bills again. Inside one round nothing is ever paid twice.

## Done since 1:50 PM
Payout through Relay (Chirag + Claude) · live board with lanes and evidence, Lambda deployed,
fallback and approval fixes, Test-panel call reading (Abhijeet) · real handwritten and printed
bills read 20/20 fields, one-digit-off trap, honest pack wording (Bhumika) · demo agent tuned
and chat-tested, call variables fixed, Kannada lines (Ayush) · checker gaps (Claude).

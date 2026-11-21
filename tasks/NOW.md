# NOW — last list before the freeze (updated 3:03 PM, freeze 3:30 PM, demos 4:00 PM)

**The whole chain has run for real.** At 2:56 to 3:01 PM: invoices read by Sarvam -> checker
(5 of 5 traps caught, 0 of 4 good bills blocked) -> live phone call in Hindi, owner said the total
-> APPROVED -> 3 payouts through Relay -> `run.py --refresh` printed PAID x3 with Cashfree UTRs.
Cashfree's Payouts dashboard shows Success 6, Rs 1,03,014 across the two rounds.
Proof: `docs/screenshots/6_board_full_chain_done.jpg`, `7_payouts_dashboard_after_live_call.jpg`.

No new features from here. Only the four things below.

| # | Task | Owner | By |
|---|---|---|---|
| 1 | **Timed rehearsal 1**, whole runbook, start to finish. `python payright/new_round.py` first. Fill the Sarvam Setup (7 values) BEFORE starting the run, and click "Call 1 number" only after the terminal says it is waiting | Everyone; Chirag drives, Ayush on the phone, Bhumika times | 3:15 |
| 2 | **Timed rehearsal 2**, and screen-record it as the backup video | Everyone; Abhijeet records | 3:28 |
| 3 | Voice scenarios still not logged: 9 (interrupt it mid-sentence), 13 and 14 (switch to Kannada / English). Do them inside the two rehearsals instead of separate calls, and log them | Ayush | 3:28 |
| 4 | Judges' pack: status line to 3:01 PM (the call-to-payout chain is proven, PAID confirmed with UTRs); write the rehearsal times in the table; rebuild the PDF | Bhumika | 3:28 |

## Two small fixes, only if they take under five minutes
- `run.py` prints `NOT_FOUND` for each transfer right after sending, because it asks Cashfree too
  early. On stage that reads as a failure. Wait about 10 seconds first, or print "waiting for Cashfree". (Abhijeet)
- The first attempt at 2:50 was lost to a call placed with the Setup empty. The runbook should say
  in step 3: check the panel shows "7/7 set" before calling. (Abhijeet)

## What we tell the judges, honestly
- Bank verification is NOT enabled on our test account (Cashfree: "Verification Suite is not enabled").
  Our answer: money only ever goes to the account already on file for the vendor, never to one read
  off an invoice. Real verification is the first thing to switch on.
- Relay's built-in transfer step reports success while Cashfree refuses it (v1 API deprecated).
  We found it, reported it, and pay through an HTTP step to Payouts v2 instead.
- Rehearsal rounds exist so the sandbox accepts the demo bills again. Inside one round, nothing is paid twice.

## Done
Chirag: accounts, keys, whitelists, the Relay agent, every live run. Abhijeet: send, approve, run,
board and site, runbook, Lambda. Ayush: demo agent, four logged phone calls, the no-data guard.
Bhumika: 41 test invoices incl. real handwritten ones, evidence report, judges' pack. Claude: checker,
reader, Relay flow, reviews.

# PayRight demo runbook (one page)

Roles: **Chirag** drives the laptop. **Bhumika** narrates. **Ayush** has the owner's phone.
**Abhijeet** watches the terminal and calls the fallback. All commands run from the repo root.

## Before the judges sit down
- `git pull`. Chirag's `payright/.env` has `SARVAM_API_KEY`, `RELAY_WEBHOOK_URL`, `STATUS_URL`, `STATUS_TOKEN`,
  `SARVAM_AGENT_API_KEY`, `SARVAM_ORG_ID`, `SARVAM_WORKSPACE_ID`, `SARVAM_APP_ID`, and for step 5
  `CASHFREE_PAYOUT_CLIENT_ID`, `CASHFREE_PAYOUT_CLIENT_SECRET`.
- Tabs open: the board, Relay Runs, Cashfree Payouts test dashboard, the Sarvam agent's Test panel on **Setup**.
- Phone charged, volume up, on speaker. Abhijeet's laptop awake and online (the board runs on it).
- **Nobody else touches the Sarvam Test panel during the run.** Step 2 takes the newest call that starts after it.

## The run

| # | Do this | The screen shows | If it goes wrong |
|---|---|---|---|
| 1 | `python payright/new_round.py` | `new round HHMMSS` | Skip it only if this is the first run today. Never run it between step 2 and step 6: inside one round nothing is paid twice, and a new round is what lets the sandbox pay the same demo bills again. |
| 2 | `python payright/run.py payright/invoices ta-IN --cash 100000 --latest` | `reading N invoice(s) with Sarvam Vision...`, then `ROUND <tag>`, the PAY / LATER / ASK / STOP table with reasons, the `SCORE` line, `asking the owner to approve N payment(s), X rupees`, the 7 call variables, and `Waiting for a call that begins after HH:MM:SS`. The board fills its three lanes. | **Reading takes over 60 s:** Ctrl+C, run `python payright/run.py payright/invoices.json --cash 100000 --latest` and say "these are the reads from this afternoon". **Judges' fresh batch:** put their images in a new folder and give that folder instead of `payright/invoices`. A file the reader cannot read becomes ASK by itself. |
| 3 | Paste the 7 variables into the Test panel's **Setup**, choose **Phone**. **Check the panel shows "7/7 set" before clicking "Call 1 number", and do not reload that tab: a reload empties the Setup.** Then call. Ayush answers as the owner, hears the reasons, says the total. | `no call started yet...`, `call in progress...`, `call ended, waiting for Sarvam to finish writing the result...`, then `APPROVED ...` or `NOT APPROVED ...` with the reason. | **`decision: none`:** the Setup was empty when the call was placed (this is what happened at 2:50 PM). Fill it again until it shows "7/7 set" and call again. **No ring within a minute:** call again from the Test panel; the run keeps waiting (7 minutes at most) and takes the new call. **Owner says the wrong total:** `NOT APPROVED`, nothing is paid. That is the design. Run step 2 again and call again. **Sarvam does not answer** (the run prints why and stops): put the batch total into `spoken_total` in `payright/fake_answer.json`, run `python payright/run.py payright/invoices.json --cash 100000 --fake fake_answer.json`, and **say aloud that the owner's answer is simulated**. |
| 4 | Nothing to type: the run sends the approved bills. Then show Relay Runs and the Payouts dashboard. | One line per payment: `ACCEPTED <invoice> <vendor> <amount> <transfer id>`, then `sent N payment(s) to Relay, total X`. The transfer id starts with `PR` and comes from the invoice, not from the attempt. | **`NOT_SENT`:** `python payright/send.py --retry` (same transfer id, so still one payment). **`UNKNOWN`:** do not resend; open Relay Runs and look. **A payout fails in Cashfree:** show the failed run. A failed payout goes back to a person and is never retried by itself. |
| 5 | `python payright/run.py --refresh` | `PAID <invoice> <transfer id> SUCCESS <UTR>` per transfer; on the board the bills turn to "Paid, Cashfree confirmed". | **`IP not whitelisted`:** the run prints the IP to whitelist (Payouts > Developers > Two-Factor Authentication). On stage, show the Payouts dashboard instead; the board keeps saying "Sent, waiting for Cashfree", which is true. |
| 6 | Run the command from step 2 again. | Paid bills come back as `STOP ... has already been ...`, the `SCORE` line ends with `already paid N`, then `nothing to pay.` Nothing new appears in Relay. | If a bill is offered again, stop: someone ran `new_round.py` in between. |
| 7 | Open the board and tap a stopped bill. | The two values the checker compared, the wrong one in red; account numbers show the last four digits only. | **Board unreachable:** the terminal table from step 2 is the fallback. To bring it back on Abhijeet's laptop: `python payright/serve.py`, then `cloudflared tunnel --url http://localhost:8765`. The address changes, so update `STATUS_URL`. |

Board: https://hugo-toilet-paths-falling.trycloudflare.com/

## Rules for the stage
- `--fake` is never used without saying the answer is simulated.
- A bill shows "Paid" only when Cashfree confirmed it. "Sent" is not "paid".
- Do not claim anything the screen has not just shown.

## Not proven as of 2:40 PM
The full chain with a live phone call followed by payouts (step 3 into step 4), and step 5 against Cashfree,
have not been run yet. Each piece was run separately: real payouts at 2:26 PM, a real voice call at about 2:35 PM,
and reading three real test calls from Sarvam at 2:12 PM.

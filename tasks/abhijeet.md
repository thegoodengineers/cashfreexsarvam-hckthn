# Abhijeet (thegoodengineer) — repo, glue code, AWS

> Current list: `tasks/NOW.md`. Where it differs from anything below, NOW.md wins.

You have the most build capacity, so the code that joins the pieces is yours.
Work top to bottom; do not start a lower item until the one above runs.

## Rules
- You have no Cashfree or Sarvam keys, and do not need them. Write the code,
  test it with `--dry-run` and fake responses, push it; Chirag runs it for real.
- The repo is public. Never commit `payright/.env` (Sarvam key, Relay webhook
  URL) or any Cashfree / AWS password.
- A model reads invoices; plain code decides about money. Do not move the
  PAY / ASK / STOP decision into an LLM.
- Bank details for a payment come from `vendors.json`, never from the invoice.

## 0. Check the base (5 min)
- [x] `python payright/check.py --selftest` prints "selftest ok".
- [x] `python payright/check.py payright/sample_invoices.json --cash 100000`
      prints 2 PAY and 3 STOP with reasons.

## 1. `payright/send.py` (by 1:15)
For each PAY row in `decisions.json`, POST one event to `RELAY_WEBHOOK_URL`.
- [x] Body is `{"data": {...}}` with exactly these fields (the Relay agent
      maps them): `invoice_no, vendor, account_holder, phone, email,
      bank_account, ifsc, address, city, state, pincode, beneficiary_id,
      amount, transfer_id`. `beneficiary_id` = the vendor `id`, alphanumeric.
- [x] Write-ahead ledger: append the row to `ledger.json` with status SENT
      BEFORE the POST. `check.py` already refuses anything in the ledger, so
      running the batch twice must pay nothing the second time. Prove it.
- [x] `--dry-run` prints the events without sending. Chirag presses the real
      run; it triggers sandbox payouts.

## 2. `payright/approve.py`: the owner's approval call (by 2:00)
Ayush builds the voice agent on Sarvam. Your script places the call and reads
the answer.
- [x] Build the call variables from `decisions.json`: `owner_name, pay_count,
      pay_total, pay_list, held_count, held_list` (reasons in plain words).
- [x] Place the call. From docs.sarvam.ai (read today, not run by us):
      `POST https://apps.sarvam.ai/api/outbounds/v1/orgs/{org_id}/workspaces/{workspace_id}/outbounds`
      header `X-API-Key`; body `app_config{app_id, app_version,
      connection_config{connection_id, agent_phone_number}, agent_variables}`,
      `user_config{user_phone_number}`, optional `webhook_config{url, metadata}`.
      It returns `{attempt_id}` and the call runs in the background.
- [x] Read the result: poll the Analytics API
      (`https://apps.sarvam.ai/api/analytics/v1/{org_id}/{workspace_id}/{app_id}/attempts`,
      needs `start_datetime` and `end_datetime`) for that `attempt_id` and
      take `final_agent_variables`: `decision`, `excluded_vendors`,
      `spoken_total`.
- [x] Approve only if `decision` is APPROVE_ALL or APPROVE_SOME AND
      `spoken_total` equals the total to be paid. Otherwise pay nothing.
- [x] One approval is good for one batch only: store the batch id with the
      approval in the ledger and refuse to reuse it.

Done with fake responses only; the real call has not been placed yet (Chirag runs it).
- `python payright/approve.py --dry-run` prints the variables and the request.
- `python payright/approve.py --fake '{"decision":"APPROVE_ALL","spoken_total":"70800"}'` tests the decision without a call.
- Needs in `payright/.env`: `SARVAM_AGENT_API_KEY, SARVAM_ORG_ID, SARVAM_WORKSPACE_ID, SARVAM_APP_ID,
  SARVAM_APP_VERSION, SARVAM_CONNECTION_ID, SARVAM_AGENT_PHONE, OWNER_PHONE, OWNER_NAME`.
- Docs check: the Analytics API returns the variables as `agent_variables`; only the post-call
  webhook calls them `final_agent_variables`. The script reads both.
- Approvals live in `approvals.json`, not `ledger.json`: check.py reads every ledger row as a payment.

## 3. AWS Lambda (by 2:30, only after 1 and 2 run)
Use the organisers' Lambda guide. Function name must start with your ID; role
is the existing `<ID>-exec`; do not create a Function URL, use their call link.
- [ ] `<ID>-payright-callback`: receives Sarvam's post-call webhook
      (`attempt_id, status, final_agent_variables, interaction_transcript`)
      and stores or forwards the decision, so `approve.py` no longer polls.
      Put its call link in `webhook_config.url` when placing the call.
- [ ] `<ID>-payright-status`: serves one HTML page listing each invoice with
      PAY / ASK / STOP, the reason, and transfer status, so judges can open it
      on their phones. Feed it by POSTing `decisions.json` to it; keep the
      last copy in memory or `/tmp` (good enough for a demo).

Code is written and passes its selftests locally; NOT deployed yet (needs the organisers'
Lambda guide and our ID).
- `payright/lambda/callback.py`, handler `callback.handler`. After deploy, put its call link in
  `payright/.env` as both `SARVAM_CALLBACK_URL` and `SARVAM_RESULT_URL`.
- `payright/lambda/status.py`, handler `status.handler`. Put its call link in `.env` as
  `STATUS_URL`; `run.py` then updates the page after the check, the call and the send.
  Optional: set `PAYRIGHT_TOKEN` on the Lambda and the same value as `STATUS_TOKEN` in `.env`.
- Both are one file, standard library only, runtime Python 3.12. No layers, no packages.
- The post-call webhook is unsigned, so `approve.py` sends a random nonce with the call and
  ignores any callback result that does not echo it. A forged "approved" post does nothing.
- Both keep data in memory and `/tmp` only: fine for the demo, lost when the Lambda goes cold.

## 4. One command for demo day (by 2:45)
- [x] `python payright/run.py <folder>` = extract -> check -> approve -> send,
      printing the table and the score line (traps caught, good ones blocked).
      The judges hand us a fresh batch; this is what we run on it.

Tested against a fake Relay on localhost: five runs of the same batch sent each payment exactly once.
- `python payright/run.py payright/invoices ta-IN --cash 100000` is the demo command.
- `--dry-run` places no call and sends nothing; `--no-pay` stops after the table and score line.
- `--fake '{"decision":"APPROVE_ALL","spoken_total":"70800"}'` stands in for the call if telephony fails on stage.
- Put `expected.json` (`{"file.png": "PAY" | "STOP"}`) in the invoice folder to get "traps caught x/y".
- Reads 4 invoices at a time, so a batch of 8 takes about as long as 2.

## Not now
- Landing page, login, database, CI. Nothing on the score card marks them.

## Update 1:50 PM (from Chirag + review of your code)
APPROVED: the live board ("the agent that says no") replaces the plain status page.
- [ ] Lanes Pay / Ask / Stop with rupee totals, from real `decisions.json` + ledger only.
- [ ] Click a stopped bill: show `evidence` from check.py (already there: `a_label`, `a`,
      `b_label`, `b` per stop), wrong value in red. Do not edit check.py for this.
- [ ] Show "paid" ONLY when Cashfree confirms. `lambda/status.py:71-75` currently shows
      NOT_SENT and UNKNOWN rows as PAID. Fix first.
- [ ] Label the call Hindi, not Tamil. Stop board work at 2:30; terminal table is the fallback.
Bugs found in review, in order:
- [ ] `run.py:133` / `approve.py:245`: `--fake '{"decision":...}'` arrives as `{decision:...}`
      in PowerShell and crashes. Read the fake answer from a file instead. This is our
      stage fallback if the call fails, so it must work.
- [ ] `send.py:183`: standalone send.py pays every PAY row with no approval. Make it
      require the approval that approve.py writes (`approval.json` is read by nothing).
- [ ] `approve.py:173-192`: non-200s are swallowed and network errors uncaught; up to 7
      silent minutes. Print the status and fail fast.
IMPORTANT, new: Relay's built-in "Request Transfer (Sync)" returns 403 "payout v1 and
v1.2 APIs have been deprecated". Payouts must go through Cashfree Payouts v2
(POST https://sandbox.cashfree.com/payout/transfers, header x-api-version 2024-01-01).
Claude is replacing that Relay step with an HTTP step; send.py's event fields stay the same.

## Status 1:57 PM (Abhijeet) — NOW.md tasks 6, 7, 8
Task 8, done and pushed:
- `--fake fake_answer.json` reads the owner's answer from a file (PowerShell-safe). Edit `spoken_total`
  to the batch total. On stage: `python payright/run.py payright/invoices.json --cash 100000 --fake fake_answer.json`
  (invoices.json, so nothing is read again).
- `send.py` refuses to send without an approval; standalone it uses up `approval.json` once, for that batch only.
- `approve.py` prints what it is waiting for every 6 s, stops after 3 bad answers or one 401/403, waits 5 minutes at most.
Task 6, done and pushed, NOT run against Sarvam:
- `python payright/run.py <folder> --latest` prints the variables to paste into the Test panel, then waits for a
  call of our agent that begins after that moment and reads its result. Needs only `SARVAM_AGENT_API_KEY,
  SARVAM_ORG_ID, SARVAM_WORKSPACE_ID, SARVAM_APP_ID`. A call already used for an approval is never used again.
- To verify on the first real call: that Test-panel calls appear in the Analytics attempts list at all.
Task 7:
- Fixed: a bill shows PAID only when Cashfree confirms (`python payright/send.py --confirm`, or
  `python payright/run.py --refresh`; needs `CASHFREE_PAYOUT_CLIENT_ID` / `CASHFREE_PAYOUT_CLIENT_SECRET` in `.env`).
  Without those keys the board says "sent, waiting for Cashfree". Not run against Cashfree yet.
- Board built: Pay / Ask / Stop lanes with rupee totals, tap a stopped bill for check.py's evidence (wrong value
  in red, account numbers masked to the last four), owner's call labelled Hindi.
- Both Lambdas are created and deployed in the organisers' account and run when invoked from the console, BUT the
  organisers' call link answers 403 "forbidden" to every outside request (curl and browser, any path). Judges'
  phones cannot reach them that way. Worth one question at the desk: is the call link open only to Relay?
- Working route: the same code runs on Abhijeet's laptop behind a public tunnel:
  board https://giants-made-stamp-wines.trycloudflare.com/
  In Chirag's `payright/.env`: `STATUS_URL=https://giants-made-stamp-wines.trycloudflare.com/status` and
  `STATUS_TOKEN=` (Abhijeet sends the value privately). The address dies if that laptop sleeps or the tunnel restarts.


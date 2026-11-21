# PayRight — for the judges

Cashfree x Sarvam Buildathon, 21 Nov 2026, Problem Statement 3: *Pay the right bill, to the right person.*
Team: Chirag, Abhijeet, Bhumika, Ayush. Full problem and architecture: `docs/PayRight_Problem_and_Solution.pdf`.

**In one line:** across 44 invoices in **23 languages (all 22 Indian languages of the Eighth Schedule, plus English)**, two of them real bills, read by the live Sarvam reader, **8 of 8 planted traps were caught and 0 wrong payments were approved.** 32 of 34 genuine bills were cleared to pay; the other 2 were stopped safely (a photo nobody could read, and an Assamese bill whose vendor could not be identified). 96% of 440 critical fields and 98% of 132 money fields were read exactly right.

**Status at 3:01 PM, honestly:** reading and checking are working and measured. **The full chain has run end to end** (rehearsal round 145546, about 2:56 to 3:01 PM): invoices read by Sarvam, the checker, a live phone call in Hindi placed from Sarvam's Test panel, the owner said the total himself, APPROVED, 3 payments of ₹51,507 in total, and 3 payouts ACCEPTED through our Relay agent. `python payright/run.py --refresh` then asked Cashfree and printed PAID for all 3 (DH-0101, HE-305, 512), each SUCCESS with a Cashfree bank reference (UTR). Cashfree's Payouts dashboard shows Success 6, ₹1,03,014.00: the 2:26 PM round plus this one, three payouts each. Proof: `docs/screenshots/6_board_full_chain_done.jpg`, `7_payouts_dashboard_after_live_call.jpg`. To get there we found and routed around a bug in Relay (section 1). Bank verification is still blocked, because Cashfree says the Verification Suite is not enabled on our test account. Voice: 5 real phone calls are logged in `payright/voice/test_calls.md` (calls 1, 5, 5b, 7 and 9). The agent gave the stopped-bill reasons in Hindi before asking, the owner said the total himself, it took "don't pay Wells, pay the rest" as APPROVE_SOME, and it refused twice to pay a stopped Hope bill when the owner insisted. Still not tested: interrupting the agent mid-sentence, and switching to Kannada or English during a call. Below, anything not yet run is marked *(planned)* or *(not yet tested)*.

---

## 1. Design note

**Our rule: a model reads, code decides, a person approves, and money only goes to the account we already have on file.**

**What we chose**
- **Sarvam Document AI reads; it never decides.** It turns each invoice (printed in any of 23 languages, handwritten, or a crumpled phone photo; tested on generated pages and on two real bills) into fixed fields with a confidence for each. If a critical field (vendor, invoice number, total, account, IFSC) is low-confidence, it is marked *unsure*. The bill then goes to a person instead of being silently fixed.
- **Plain, tested code decides PAY / ASK / STOP** (`payright/check.py`). Every decision carries a reason a shop owner can read aloud. The checks are:
  - Does the arithmetic hold, including the amount in words against the figures?
  - Who is the vendor? Matched by GSTIN, or by name across scripts.
  - Is the bank account on the invoice the one on file?
  - Does that account belong to a *different* vendor on file?
  - Is this a duplicate in disguise?
  - What is the legal deadline? 15 or 45 days for micro and small suppliers.
- **Money only to the account on file.** Bank details for a payment come from `vendors.json`, never from the invoice. The invoice's account is only *compared*. `send.py` also treats `decisions.json` as untrusted and refuses any row whose account differs from the vendor file.
- **One transfer ID per invoice, for life.** It is derived from vendor, invoice number and amount. A write-ahead ledger records each payment *before* it is sent. Running the same batch twice pays nothing the second time; `send.py`'s self-test proves this, though not yet by re-running real payouts. Cashfree's docs say a repeated transfer ID is rejected, which would be a second lock *(not yet tested by us)*.
- **The owner approves by phone, in his language.** A Sarvam voice agent calls Raghu, tells him what is clean and what was stopped and why, and accepts a yes only if he says the total himself. One approval is good for one batch, once. *(5 real phone calls are logged in `payright/voice/test_calls.md` (calls 1, 5, 5b, 7 and 9). The agent gave the stopped-bill reasons in Hindi before asking, the owner said the total himself, it took "don't pay Wells, pay the rest" as APPROVE_SOME, and it refused twice to pay a stopped Hope bill when the owner insisted. Still not tested: interrupting the agent mid-sentence, and switching to Kannada or English during a call. A live call has also run straight into payouts, in round 145546. The approval rules are in `approve.py` with a self-test; calls are placed from Sarvam's Test panel, and `run.py` reads the newest call's answer.)*

**What we chose not to use, and why**
- **No LLM deciding about money.** Its answers are not repeatable and not auditable. Code gives the same answer every time, and a test proves it.
- **No trusting bank details printed on an invoice.** A familiar vendor with a new account is the oldest fraud there is.
- **No automatic payment retries.** A failed or reversed payout goes back to a person as ASK, and never becomes a second payment *(planned; not yet tested, because no payout has failed yet)*.
- **No payments backend of our own.** Payouts run inside Cashfree Relay, so every run is visible in its Runs tab. Three sandbox payouts have gone through this way. *(Bank verification is not working yet: "Verification Suite is not enabled".)*

**A bug we found in Cashfree Relay, and how we routed around it**
- **What happened.** Relay's built-in *Cashfree Payouts → Request Transfer (Sync)* step showed **Completed**, with `"success": true` and *"Transfer requested successfully"*. Inside the same response, Cashfree had answered **ERROR, 403: "The payout v1 and v1.2 APIs have been deprecated. Please use v2 APIs."** No money moved, but the step looked green. Proof: `docs/screenshots/3_relay_transfer_uses_deprecated_api.jpg`.
- **Why it matters.** A payout that silently fails while showing success is the most dangerous failure in this problem. It is the reason we never trust a step's own "success": the board marks a bill PAID only when Cashfree confirms it.
- **How we routed around it.** The Relay agent now pays through an **HTTP step that calls Cashfree Payouts v2** (`POST /payout/transfers`) with our own transfer ID. Cashfree answers `RECEIVED`, and the transfer appears in the Payouts dashboard. Proof: `docs/screenshots/4_payout_received_by_cashfree.jpg`, `5_payouts_dashboard_3_success.jpg`.
- **Feedback to the sponsor.** Relay's Request Transfer step should move to the v2 API, and should report Cashfree's ERROR status as a failed step, not a completed one.
- **No website first.** Time went into the problem, the voice, the money and the live demo.

---

## 2. One success case and one failure case

Both cases come from a real run on 21 Nov 2026: our demo invoices went through the live Sarvam reader (advanced mode) and our checker. Results: `payright/scoresheet.md`.

### Success: a handwritten-style bill, as a phone photo, read and cleared
`payright/invoices/inv08_wells.jpg` is a red-ruled bill-book page from Wells Paints and Chemicals. **It is generated, not a real handwritten bill:** the entries are in a handwriting font with every letter slightly tilted, and the page is then made to look like a phone photo, at an angle and in uneven light. The date is in short form (`18/11/26`).
- Sarvam read every field the checker needs correctly:
  - invoice no `512`
  - two line items
  - subtotal `8000`, GST `1440`, total `9440`
  - the amount in words, converted to `9440`
  - account `1233943142`, IFSC `ICIC0000009`
- No field was flagged unsure. The arithmetic held, words matched figures, the GSTIN matched Wells, and the account matched the one on file.
- **Decision: PAY**, queued for the owner's approval call.

The Tamil invoice (`inv02`) and the Hindi invoice (`inv03`) were also read correctly, including amounts written in Tamil and Hindi words. Those words were converted to the right numbers.

### Failure caught: a familiar vendor asks to be paid into a new account
`payright/invoices/inv04_hope.png` is a well-formed invoice from Hope Electricals. Everything adds up. The GSTIN and name are right. It carries a polite note: *"our bank account has changed. Kindly pay only to the new account below."* The account is `026291800001190` at Yes Bank. The account on file is `388108022658` at ICICI.
- Nothing about the bill *looks* wrong, and that is the danger.
- The checker compares the invoice's account with the account on file and **STOPs**:


  > The bank account on this invoice is not the account we have on file for Hope Electricals. Call the vendor on the number we already have before paying.

- On the call *(done on real phone calls 1, 7 and 9)*, the agent tells Raghu in Hindi that the bank account changed and he should call the vendor on the old number first. The bill is not in the batch he approves. Even if someone edited the decision file, `send.py` would refuse it, because the account is not the one on file.

Two other traps were stopped with their own reasons:
- **A duplicate in disguise:** `DH-0101` came back as `dh/101`, with a new date format and layout.
- **A borrowed account:** Jane D Traders asked to be paid into John Doe's account.

A fifth trap: `inv09_hope.png`, Hope Electricals with account `388108022659`, **one digit off** the account on file, with no warning note. Sarvam read the account exactly, digit for digit, and the checker **STOPs** it: *"The bank account on this invoice is not the account we have on file for Hope Electricals."*

**Real bills, not generated:** two bills photographed by the team (private details blacked out), in `payright/test_sets/real/`. One is a real handwritten bill at only 400 × 541 pixels. The other is a crumpled printed Amazon tax invoice photographed on cloth. Sarvam read **20 of 20** checked fields exactly right across the two. Neither vendor is on our list, so both are held as **ASK**, never paid.

**Score on the demo set:** traps caught **5 / 5**, genuine bills cleared to pay **4 / 4**.

---

## 3. Evidence: 44 invoices in 23 languages, scored field by field

We did not stop at the demo set. We built 42 invoices ourselves and added 2 real bills, so we know every value truly printed on each one. All 44 went through the live Sarvam reader and our real checker. A *trap* is a bill planted to be refused. Every other bill is *genuine*, however bad its photo, and counts as "not paid" if it is asked about or stopped. Full report, with every invoice image beside what was read: `docs/evidence/PayRight_Evidence.pdf`.

| | Demo set (9) | Stress set (8) | Fail-safe ladder (5) | 20 languages (20) | Real bills (2) | **All 44** |
|---|---|---|---|---|---|---|
| Planted traps caught before money moved | 5 / 5 | 3 / 3 | none planted | none planted | none planted | **8 / 8** |
| Genuine bills cleared to pay | 4 / 4 | 5 / 5 | 4 / 5 (1 stopped) | 19 / 20 (1 stopped) | unknown vendors: both ASK | **32 / 34** (2 stopped) |
| Wrong payments approved | 0 | 0 | 0 | 0 | 0 | **0** |
| Critical fields read exactly right | 87 / 90 | 77 / 80 | 45 / 50 | 193 / 200 | 20 / 20 | **422 / 440 (96%)** |

- **Stress set:** each invoice targets a check the demo set does not:
  - the amount in words disagrees with the figures
  - one line multiplied wrong
  - a Hindi bill in Devanagari digits
  - a misspelt vendor name
  - the same bill re-sent with a new number
  - a dim photo of a generated handwritten-style bill
  - a total above one lakh, with the words in lakh notation
- **India's languages:** one clean bill in each of the other 20 scheduled languages, each read with its own language code: Bengali, Telugu, Marathi, Gujarati, Kannada, Malayalam, Odia, Punjabi, Assamese, Urdu, Nepali, Konkani, Maithili, Sanskrit, Dogri, Bodo, Kashmiri, Sindhi, Manipuri (Meitei script) and Santali (Ol Chiki script).
  - Sarvam read every total, account number and IFSC right in all 20.
  - Sarvam scores non-English vendor names at 0.5 confidence, which at first sent 9 clean bills to ASK. We measured a fix on the saved reads, and the checker now asks only when nothing else confirms a shaky reading: here the GSTIN or the account on file proves the vendor. All 9 are now paid, and no other result changed.
  - The Assamese bill was stopped. The GSTIN slip and an Assamese name with no English reading left the vendor unidentified. It was safe, but wrong. An Assamese name in the vendor list would fix it.
  - For 9 lower-resource languages the labels are our best effort and the amount in words is in English. A native speaker should review them.
- **Fail-safe ladder:** the same kind of genuine bill, photographed from a flat scan down to barely readable. The first four were paid correctly. The fifth was not paid: it was stopped, so it counts as a genuine bill not paid.
- **What the ladder taught us.** On the unreadable photo, Sarvam invented a bank account (`0123456789012345`), a GSTIN and a 2023 date. It scored that account at confidence 0. Our reader was treating a 0 as fully sure, because in Python `0 or 1` is `1`. We fixed it, and a 0 now marks the field unsure. The bill was never at risk: code compares every account with the one on file. **This is our design working. We do not trust the model's confidence; we cross-check what it reads.**
- **Honest gaps:**
  - On the Devanagari-digit bill, Sarvam read the total right but was unsure of it (0.5). The arithmetic and the amount in words confirm it, so it is paid.
  - The letter O inside one vendor's GSTIN is read as zero every time. That is harmless, because the vendor is then matched by name.
  - Not paying the barely readable photo is the safe outcome, but it is still a genuine bill not paid, and we count it that way.

---

## 4. Six-minute demo script

**Roles:** Chirag drives the laptop. Bhumika narrates. Ayush has Raghu's phone. Abhijeet watches the terminal for errors and calls the fallback.

The commands, screens and fallbacks below follow `docs/RUNBOOK.md` (Abhijeet), which is the one source for commands.

**Before the judges sit down**
- Terminal open in the repo root, after `git pull`.
- Tabs open: the board, Relay Runs, the Cashfree Payouts test dashboard, and the Sarvam agent's Test panel on **Setup**.
- Run `python payright/new_round.py`. It sets the ledger aside and starts a new rehearsal round, so the sandbox accepts the demo bills again. Within a round, the first run pays and the second run proves no double pay. Never run it again during the demo.
- Phone charged, volume up, on speaker. Nobody else touches the Sarvam Test panel during the run.

| Time | Who | On screen | What we say |
|---|---|---|---|
| 0:00 to 0:40 | Bhumika | the 9 demo invoice images, side by side | **Problem.** "Raghu runs a hardware wholesale in Chennai. Sixty invoices a week, in Tamil, Hindi and English, some handwritten. One of these nine is from a real vendor asking to be paid into a new account. It looks perfect. Last month a bill like that would have been paid." |
| 0:40 to 1:40 | Chirag | `python payright/run.py payright/invoices ta-IN --cash 100000 --latest`; the board fills its three lanes | **The doctored invoice goes in.** "Sarvam reads all nine, including the handwritten-style photo and the Tamil and Hindi amounts in words. The model only reads. Plain code decides." |
| 1:40 to 2:40 | Bhumika | the PAY / LATER / STOP table, pointing at row HE-310; then tap a stopped bill on the board to show the two values compared | **The agent refuses and says why.** Read the STOP reason aloud. Then point at the duplicate `dh/101`, at Jane D Traders using John Doe's account, and at HE-312, where the account is one digit off. "Every refusal has a reason a shop owner understands. Money only ever goes to the account on file." |
| 2:40 to 4:00 | Ayush | Chirag pastes the 7 call variables into the Test panel and calls; phone on speaker | *(Done live in rehearsal round 145546: the owner said the total, APPROVED, 3 payments, ₹51,507. Not yet tested: interrupting the agent, and switching to Kannada or English mid-call.)* **The owner approves by phone.** The agent says how many bills are clean and the total, which were stopped and why, in Hindi. Raghu must say the total aloud. The terminal prints `APPROVED`. |
| 4:00 to 4:50 | Chirag | the `ACCEPTED ... PR...` lines, Relay Runs, the Payouts dashboard, then `python payright/run.py --refresh` | *(Done after the live call in round 145546: 3 payouts ACCEPTED, then `--refresh` printed PAID, SUCCESS with a Cashfree UTR, for DH-0101, HE-305 and 512.)* **The payouts show as successful.** Open one transfer and show its transfer ID. "That ID comes from the invoice itself, not from this attempt. A bill shows Paid only when Cashfree confirms it." |
| 4:50 to 5:20 | Chirag | the step-2 command again | **Nothing is paid twice.** Every row comes back as already sent. Nothing new appears in Relay. *(Proven in `send.py`'s self-test; not yet with real payouts.)* |
| 5:20 to 6:00 | Bhumika | the `SCORE` line, then the top of `docs/evidence/PayRight_Evidence.pdf` | **Our numbers.** "Forty-four invoices in twenty-three languages, every Indian language in the Constitution, plus two real bills, scored field by field against what is truly printed: eight of eight planted traps caught, zero wrong payments. One trap changed a single digit of the account. It was caught. On a photo nobody could read, the AI invented a bank account. Our code refused it." Then the judges' fresh batch numbers, if we got one. Close: "A model reads, code decides, a person approves, and money only goes to the account on file." |

**Fallbacks**
Full fallbacks per step are in `docs/RUNBOOK.md`. The three most likely:
- **Reading is slow** (more than about 60 s): Ctrl+C, run `python payright/run.py payright/invoices.json --cash 100000 --latest`, and say "these are the reads from this afternoon".
- **The call does not ring within a minute:** call again from the Test panel; the run keeps waiting and takes the newest call. If Sarvam does not answer at all, use `--fake fake_answer.json` as in the runbook, and **say aloud that the owner's answer is simulated**.
- **Payouts fail** (IP whitelist, or no test balance): show the failed run in Relay's Runs tab. Say that a failed payout goes back to a person and is never retried. That *is* our design.

**Rehearsals: write the real times here**

| Run | Problem | Read and check | Refusal | Call | Payouts | Re-run | Numbers | Total |
|---|---|---|---|---|---|---|---|---|
| 1 | | | | | | | | |
| 2 | | | | | | | | |
| 3 | | | | | | | | |

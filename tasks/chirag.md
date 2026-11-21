# Chirag — everything that touches Cashfree or Sarvam, demo operator

Only your accounts have Cashfree access and Sarvam credits, so every REAL
call to either service runs on your laptop: the invoice reader, the voice
agent on Sarvam, Relay, and the payout run. Teammates write and dry-run;
you run.

You hold the Cashfree login, so everything that needs keys, approvals or a
money button is yours. Claude builds the Relay canvas with you in the pane.

## Now
- [ ] Stay near the laptop with the Cashfree pane open; paste keys / click
      approvals when Claude asks (it cannot type secrets or accept terms).
- [ ] Relay desk, ask and write the answers here:
      - Which IPs does Relay call Payouts from? (we whitelisted 52.66.25.127)
      - Does a test Payouts account have balance? How do we add test funds?
      - How does "approval before money moves" behave in test mode?
      - Report: Relay's Payouts actions fail out of the box with
        "IP not whitelisted". (Feedback to the sponsor counts.)
- [ ] Ask an organiser: are the 3 problem statements today's tracks, and do
      we get a fresh batch of invoices at demo time? Demo length: 10 or 13 min?

## By 1:15
- [ ] One test payout through Relay end to end (you press the button).

## By 2:45
- [ ] Full run: all invoices -> checker -> Relay -> payouts. Keep every
      failed run in Relay's Runs tab; we show one failed-then-fixed run.

## Demo
- [ ] You drive the laptop: canvas, Runs tab, Payouts test dashboard.

## Blocker found at 12:50 (go to the onboarding / Relay desk now)
- [ ] Relay's "Verify Bank Details" returns: "Verification Suite is not
      enabled for this account" (subCode 422). Ask them to enable Secure ID /
      Verification Suite on our TEST account. Without it we cannot verify a
      vendor's bank account, which problem 3 requires.
- [ ] Our 3-step dry run took 3 minutes. Ask if that is normal today.

## Sarvam (your account)
- [ ] Sign in to indus.sarvam.ai in the Claude browser pane; Claude builds the
      voice agent there with Ayush's prompt.
- [ ] Run the reader on Bhumika's invoices:
      `python payright/extract.py payright/invoices ta-IN`
      then `python payright/check.py payright/invoices.json --cash 100000`.

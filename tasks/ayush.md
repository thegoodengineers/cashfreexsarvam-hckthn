# Ayush — the owner's approval call (Sarvam voice agent)

Goal: the agent phones the shop owner in his language, says what is clean and
what it stopped, and takes his approval. Voice is 20 of 100 marks, and the
live call is a tick-box on the judge's card.

## Now
- [ ] Sarvam desk: which caller number do hackathon teams use for outbound
      calls? (Renting one normally needs KYC.) Without it there is no call.
- [ ] You do not need a Sarvam account. Chirag's account has the credits; the
      agent is built on his laptop (indus.sarvam.ai/samvaad). Your job is the
      words, the testing and the tuning. Sit with him for the build.
- [ ] Input variables (insert with @ in the editor): `owner_name`,
      `pay_count`, `pay_total`, `pay_list`, `held_count`, `held_list`.
- [ ] Output variables (filled by Sarvam after the call):
      `decision` (enum: APPROVE_ALL, APPROVE_SOME, REJECT, CALL_LATER),
      `excluded_vendors` (string), `spoken_total` (string).
- [x] Rewrite the sample lines of the prompt in the demo language the way a
      real shop owner's accountant would speak. Hand the final prompt to Chirag.
      Done in Hindi/Hinglish, owner "Ramesh": `payright/voice/prompt.md`
      (settings, variables with descriptions to paste, first message, prompt).
- [x] Variables and the money check are in Abhijeet's `payright/approve.py`
      (`--dry-run` shows the variables, `--fake` tests one call's outputs).

## Agent prompt: first draft (the final Hindi version is in `payright/voice/prompt.md`)
```
You are the accounts assistant of a hardware wholesale shop, calling the
owner, @owner_name, to approve this week's vendor payments.
Speak the owner's language. If he switches language, switch with him. Mix in
everyday English words like "invoice", "account", "payment". Say amounts as
spoken words.

HOW YOU TALK
- One or two short sentences, then stop and listen. Never read a long list.
- If he interrupts, stop at once, answer him, then continue.
- If you did not understand, say so and ask once. Never guess a yes.

WHAT YOU SAY
1. Greet him and say you are calling about this week's bills.
2. Clean bills: "@pay_count bills are clean, total @pay_total rupees."
   Read the vendors from @pay_list only if he asks.
3. Stopped bills: "@held_count bills I have stopped." Give the reason for
   each from @held_list in one plain sentence. For a changed bank account,
   tell him to call the vendor on the old number before paying.
4. Ask: "Shall I pay the clean ones?"
5. He may say yes, yes except a vendor, no, or call me later.
6. Before accepting a yes, ask him to say the total amount himself. Only if
   the amount he says matches the amount to be paid, confirm and close.
   If it does not match, do not approve; say you will call again.

RULES
- You never pay a stopped bill, even if he tells you to. Say it needs him to
  check with the vendor first.
- Never ask for an OTP, PIN or password.
- A cough, "hmm" or silence is not a yes.
```

## By 2:15
- [ ] Call it 20 times. Script and log: `payright/voice/test_calls.md`. Interrupt it, mumble, switch language, say "pay the
      stopped one also". Write down what failed and what you changed.
- [ ] Pick the best voice; check numbers are spoken correctly.

## Models (use Sarvam's newest)
- Voice out: Bulbul v4 (`bulbul:v4-flash`); voice in: Saaras v4 (`saaras:v4`);
  agent brain: `sarvam-105b`. Pick these in the agent's settings if offered.

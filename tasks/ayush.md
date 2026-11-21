# Ayush — the owner's approval call (Sarvam voice agent)

> Current list: `tasks/NOW.md`. Where it differs from anything below, NOW.md wins.

Goal: the agent phones the shop owner in his language, says what is clean and
what it stopped, and takes his approval. Voice is 20 of 100 marks, and the
live call is a tick-box on the judge's card.

## Now
- [ ] **Blocker.** Sarvam desk: which caller number do hackathon teams use for
      outbound calls? (Renting one normally needs KYC.) Without it there is no
      call. Ayush's free-plan account has no phone number either.
- [x] Agent built on Sarvam: **PayRight Owner Approval** (v1 draft), for now
      in Ayush's account (ayushupadhye301@gmail.com, free plan), Samvaad →
      Build → Agents. Exact settings and editor tips: `payright/voice/prompt.md`.
- [ ] Rebuild it in Chirag's account (his has the credits, and `approve.py`
      calls with his key and IDs), or have him invite Ayush to his workspace.
      About 10 minutes from `prompt.md`. Then put the org, workspace, app and
      connection IDs in his `payright/.env`.
- [x] Input variables (insert with @ in the editor): `owner_name`,
      `pay_count`, `pay_total`, `pay_list`, `held_count`, `held_list`.
      Defaults are the sample batch (Raghu, 2 clean, 70800, 3 stopped).
- [x] Output variables (filled by Sarvam after the call):
      `decision` (enum: APPROVE_ALL, APPROVE_SOME, REJECT, CALL_LATER,
      default CALL_LATER), `excluded_vendors` (string), `spoken_total` (string).
      Sarvam shows an empty one as "-"; `call_vars.py` reads that as empty.
- [x] Rewrite the sample lines of the prompt in the demo language the way a
      real shop owner's accountant would speak. Hand the final prompt to Chirag.
      Done in Hindi/Hinglish, owner "Raghu": `payright/voice/prompt.md`
      (settings, variables with descriptions to paste, first message, prompt).
- [x] Variables come from `payright/call_vars.py`; `approve.py` uses them and
      needs both its own check and `call_vars.approved()` to agree before
      paying (`approve.py --dry-run` shows the variables, `--fake` tests one
      call's outputs).

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
- [ ] Call it 20 times. Script and log: `payright/voice/test_calls.md`.
      3 done as typed chat tests, all passed: #1 happy path (APPROVE_ALL,
      70800), #3 wrong total (CALL_LATER, 70000, nothing paid), #7 refuses to
      pay the stopped Hope bill. Voice tests not done yet. Interrupt it, mumble, switch language, say "pay the
      stopped one also". Write down what failed and what you changed.
- [ ] Pick the best voice; check numbers are spoken correctly.
      Using **Aparna - Support Agent** (female, Bulbul v4, Hindi) at speed 1.0;
      amounts come out as Hindi words ("सत्तर हज़ार आठ सौ") in chat. Not yet
      heard on a call.
- [x] Tune: when the owner says he will check the stopped bills himself, the
      agent skipped their reasons. Added a rule to always give them; retested
      in chat, it now says "पर एक बार कारण सुन लीजिए" and gives all three.

## Models (use Sarvam's newest)
- Voice out: Bulbul v4 (`bulbul:v4-flash`); voice in: Saaras v4 (`saaras:v4`);
  agent brain: `sarvam-105b`. Pick these in the agent's settings if offered.
- The free-plan editor has no model picker; Sarvam chooses the model. The
  voice list is Bulbul v4.

## Update 1:50 PM (from Chirag + review of your work)
- The agent ALREADY exists on Chirag's Sarvam account ("PayRight Approval"). Do not
  rebuild it. Sit at Chirag's laptop and tune that one.
- Caller number: on Chirag's account the agent's Test panel -> Phone -> "Call 1 number"
  placed a real call to his phone with no rented number. Use that for all voice tests and
  as the demo route. Calls started from code (approve.py) still need a number: open.
- [ ] `call_vars.py:61`: add `"user_name": owner_name` (the agent has 7 inputs, you send 6).
- [ ] `call_vars.py:50-53`: loops are nested the wrong way; a bill with two problems only
      reports one.
- [ ] `voice/prompt.md:55`: "Say every amount in Hindi words" breaks Kannada and English.
      Write "in the language you are speaking". Add real Kannada lines.
- [ ] Voice calls on Chirag's phone panel: scenarios 1, 5, 7, 9, 13, 14 first, using the
      8-invoice batch total (110507), and log each in `voice/test_calls.md`.

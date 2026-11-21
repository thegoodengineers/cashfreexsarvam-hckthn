# Owner approval call: Sarvam agent setup (Hindi / Hinglish)

Built on Chirag's Sarvam account (indus.sarvam.ai/samvaad). Paste the blocks
below into the agent editor. Insert each `@variable` with **@** in the editor;
do not type it as plain text, or Sarvam will not fill it in.

## Demo agent (Chirag's account): what it has and what was changed
The demo agent is in Chirag's workspace, listed as **"Conversation Agent 7411"**
(v3 draft); it introduces itself as "PayRight Approval". Its prompt is Chirag's
own (Persona / Objective / Speaking style / Facts / Conversation guidelines /
Guardrails) and already covered "always give the reasons" and "amounts in the
language being spoken". It was not replaced. Added on 21 Nov:

1. **He excludes a vendor:** the expected total is pay_total minus the
   left-out vendors' amounts from pay_list (example 110507 → 42067 without
   Wells); never say it for him; the old full total is not an approval. The
   original line compared with pay_total, which refuses every valid partial
   approval. Same exception added to the "Approval requires…" guardrail.
2. **Held bills:** a bill can have several problems ("…, and also …"): say
   each. Give the reasons first even if he says yes or leaves a vendor out early.
3. **Kannada sample lines** (a bullet under Guardrails, where the editor put it).
5. **No-data guard** (last guardrail): with empty pay_total / pay_list /
   held_list it must not invent bills; it ends the call, CALL_LATER. Added after
   a test call with empty Setup made up vendors and a 15,800 total.
6. Temperature set to Compliant (was Balanced).
7. **Pacing** (Held bills): count first, then two stopped bills per turn with a
   pause ("आगे बताऊँ?"); never more than two in one turn. Needed for the demo
   batch's six stopped bills.
8. **Output fixes after phone call 5:** `decision` = APPROVE_SOME when the spoken
   total equals pay_total minus the left-out vendors; `excluded_vendors` always
   uses the English name from pay_list (he said "वेल्स"/"बेल्स").

**Frozen:** all of the above is committed as **v3** (note "Demo freeze…"); Sarvam
opened v4 as the working draft (same content). The Test panel → Phone route runs
the draft; if anyone edits after the freeze, compare with v3 or switch back to it.
Demo Setup values: `test_calls.md` → "Demo Setup".
4. **`decision` output:** a mismatched total (e.g. the old total after leaving
   vendors out) is REJECT, never APPROVE_ALL / APPROVE_SOME. Before this it
   returned APPROVE_SOME for a refused call; our code still paid nothing.

Its 7 inputs have no defaults: fill them in Test → Setup (values in
`test_calls.md`). Its outputs match ours (`decision`, `excluded_vendors`,
`spoken_total`); it records a wrong total as REJECT where this file says
CALL_LATER; both pay nothing.

The practice agent in Ayush's workspace ("PayRight Owner Approval") follows
the rest of this file.

## Settings
Built in Samvaad's agent editor (Build → Agents → Create from scratch). On the
free plan the editor has no model picker; the voice list shows Bulbul v4.

| Where | Setting | Value |
|---|---|---|
| Settings → Speaking | Voice | **Aparna - Support Agent** (female, Bulbul v4, Hindi). The lines say "बोल रही हूँ" |
| | Speaking speed | 1.0 (default 1.15 runs amounts together) |
| Settings → Thinking | Model temperature | Compliant (one step below Balanced) |
| Settings → Listening | Let callers interrupt | On |
| Settings → Language | Switch language during call | On, all languages allowed (Hindi, English, Kannada…) |
| | Starting language | Hindi |
| | Output numbers in Indic | On (500 → "paanch sau") |
| Settings → In call actions | Nudge message | "जी, क्या आप line पर हैं?" after 5 s |
| | Voicemail message | "नमस्ते जी, दुकान के accounts से call था, इस हफ़्ते के bills के बारे में। हम थोड़ी देर में फिर call करेंगे।" |
| | Max call length | 5 minutes |
| Instructions | Greeting | the First message below, `owner_name` inserted with @ |

**Tips for the editor:** in the enum values box, press **comma** after each
value, because Enter saves the whole form. In Instructions, typing `@` opens a
picker, so the prompt puts each variable once in a CALL DATA block at the top
(insert each with @), and the rest of the prompt refers to them by name.
After editing the greeting, click **Regenerate** for translations.

## Input variables
Make these in the editor. `approve.py` fills them on a real call (built by `call_vars.py`); to see
the values for a batch, run `python payright/approve.py --dry-run` (set
`OWNER_NAME=Raghu` in `payright/.env`). For test calls, paste the sample values.

| Variable | What it is | Sample (from `sample_invoices.json`) |
|---|---|---|
| `owner_name` | Owner's name | `Raghu` |
| `user_name` | Sarvam's default input on Chirag's agent; same as owner_name | `Raghu` |
| `pay_count` | Clean bills to pay | `2` |
| `pay_total` | Their total, digits only | `70800` |
| `pay_list` | Numbered: vendor, amount | `1) Doe Hardware Supplies, 11800 rupees. 2) Wells Paints and Chemicals, 59000 rupees.` |
| `held_count` | Bills stopped or waiting | `3` |
| `held_list` | Numbered: vendor, amount: reason | `1) Hope Electricals, 23600 rupees: bank account changed on the invoice, call the vendor on the old number first. 2) Doe Hardware Supplies, 11800 rupees: this bill was already paid or is already in this batch, it looks like a duplicate. 3) Wells Paints and Chemicals, 26300 rupees: the total on the bill is wrong, subtotal plus tax does not match.` |

## Output variables
Paste each description as written. `approve.py` reads them and pays nothing
unless the call connected, the decision is an approval, and the total the
owner said equals what will be paid.

| Variable | Type | Description to paste |
|---|---|---|
| `decision` | enum: `APPROVE_ALL`, `APPROVE_SOME`, `REJECT`, `CALL_LATER` | The owner's final answer. APPROVE_ALL only if he said yes to all clean bills AND said the correct total himself. APPROVE_SOME only if he left out one or more vendors AND said the correct new total. REJECT if he said no. CALL_LATER if he asked to call later, the call dropped, the total he said was wrong, or you are not sure. |
| `excluded_vendors` | string | Names of the clean-bill vendors he asked NOT to pay, exactly as written in pay_list, separated by commas. Empty if none. |
| `spoken_total` | string | The total amount the owner himself said, written in digits only, no commas, no words (example: 70800). Empty if he did not say a total. Never fill in the amount you said. |

## First message
```
नमस्ते @owner_name जी, मैं दुकान के accounts से बोल रही हूँ। इस हफ़्ते के vendor bills के payment के बारे में call किया है। दो मिनट बात कर सकते हैं?
```

## Agent prompt
```
You are the accounts assistant of a hardware wholesale shop. You are calling the
owner, @owner_name, to get his approval for this week's vendor payments.

LANGUAGE
- Speak Hindi the way a shop's accountant speaks: simple Hindi with everyday
  English words like bill, invoice, payment, account, vendor, total, OK.
- If he speaks English, Kannada or another language, switch to it and stay with it.
  Everything after that, including amounts and the sample lines below, is said
  in the language you are speaking now.
- Call him "@owner_name जी" (in Kannada "@owner_name ಅವರೇ"). Be polite and brief,
  like a trusted staff member.
- Say every amount in words in the language you are speaking, using lakh and
  thousand, never digit by digit:
  - Hindi: 110507 = "एक लाख दस हज़ार पाँच सौ सात रुपये". 70800 = "सत्तर हज़ार आठ सौ रुपये".
  - Kannada: 110507 = "ಒಂದು ಲಕ್ಷ ಹತ್ತು ಸಾವಿರದ ಐನೂರ ಏಳು ರೂಪಾಯಿ". 70800 = "ಎಪ್ಪತ್ತು ಸಾವಿರದ ಎಂಟು ನೂರು ರೂಪಾಯಿ".
  - English: 110507 = "one lakh ten thousand five hundred and seven rupees".
- Say vendor names as written, in English. Do not read invoice numbers unless he asks.
- @held_list gives each reason in English: say it in ONE short sentence in the
  language you are speaking, never translate it word for word. A bill can have
  more than one problem ("..., and also ..."): say each.

KANNADA LINES (use these if he speaks Kannada)
- Clean bills: "@pay_count bills ಸರಿಯಾಗಿವೆ, total [amount in Kannada words] ರೂಪಾಯಿ."
- Stopped bills: "@held_count bills ನಾನು ತಡೆಹಿಡಿದಿದ್ದೇನೆ."
- Bank account changed: "Hope Electricals bill ನಲ್ಲಿ bank account ಬದಲಾಗಿದೆ. Payment ಮುಂಚೆ vendor ಗೆ ಹಳೆಯ number ಗೆ call ಮಾಡಿ confirm ಮಾಡಿ."
- Duplicate: "ಈ bill ಹಿಂದಿನ bill ತರಹನೇ ಇದೆ, number ಮಾತ್ರ ಬೇರೆ. ಎರಡು ಸಲ payment ಆಗುತ್ತಿತ್ತು, ಅದಕ್ಕೆ ತಡೆದಿದ್ದೇನೆ."
- Wrong total: "ಈ bill ನಲ್ಲಿ subtotal ಮತ್ತು tax ಕೂಡಿಸಿದರೆ total ಹೊಂದುವುದಿಲ್ಲ."
- Ask: "ಸರಿಯಾದ bills ಗೆ payment ಮಾಡಲಾ?"
- Ask for the total: "Confirm ಮಾಡಲು, total amount ಒಮ್ಮೆ ನೀವೇ ಹೇಳಿ."
- Total matches: "ಧನ್ಯವಾದ, payment ಮಾಡುತ್ತಿದ್ದೇನೆ."
- Total does not match: "Amount ಹೊಂದುತ್ತಿಲ್ಲ, ಈಗ payment ಮಾಡುವುದಿಲ್ಲ, ಮತ್ತೆ call ಮಾಡುತ್ತೇನೆ."
- Pay a stopped bill: "ಆ bill ತಡೆಹಿಡಿಯಲಾಗಿದೆ, ಮೊದಲು vendor ಜೊತೆ check ಮಾಡಿ, ಆಮೇಲೆ payment."
- OTP: "OTP ಅಥವಾ PIN ಹೇಳಬೇಡಿ, ಅದರ ಅವಶ್ಯಕತೆ ಇಲ್ಲ."

HOW YOU TALK
- One or two short sentences, then stop and let him speak. Never read a long list.
- If he interrupts, stop at once, answer him, then carry on from where you were.
- If you did not understand him, say so and ask once more. Never guess a yes.
- A cough, "hmm", "haan haan" while you are still talking, or silence is NOT a yes.

THE CALL, STEP BY STEP
1. Greet him and say you are calling about this week's bills (the first message does this).
2. Clean bills. Say:
   "@pay_count bills बिल्कुल सही हैं, total @pay_total रुपये बनता है।"
   (say @pay_total in Hindi words). Read the vendors and amounts from
   @pay_list ONLY if he asks which ones, one at a time.
   If @pay_count is 0, say there is nothing to pay this week, explain the
   stopped bills, and close with decision REJECT.
3. Stopped bills. Say: "@held_count bills मैंने रोक दिए हैं।" Then for each
   one in @held_list give the vendor and the reason in ONE plain Hindi sentence,
   and pause after each so he can react. Examples:
   - bank account changed: "Hope Electricals के bill पर bank account बदला हुआ है।
     Payment से पहले vendor को उनके पुराने number पर call करके confirm कर लीजिए।"
   - duplicate: "Doe Hardware का यह bill पहले वाले bill जैसा ही है, सिर्फ़ number
     अलग लिखा है। दोबारा payment हो जाता, इसलिए रोका है।"
   - wrong total: "Wells Paints के bill में subtotal और tax जोड़ने पर total मेल
     नहीं खाता। Bill में ग़लत जोड़ है।"
   - vendor not on our list or name does not match: "यह vendor हमारी list में
     नहीं है / नाम मेल नहीं खाता, तो बिना आपकी जाँच के payment नहीं करेंगे।"
   - could not read: "Bill का कुछ हिस्सा साफ़ पढ़ा नहीं गया, आप एक बार देख लीजिए।"
   - not enough cash: "आज cash कम है, यह bill अगली बार payment होगा।"
4. Ask: "तो जो सही bills हैं, उनका payment कर दूँ?"
5. He may say: yes to all; yes but leave out a vendor; no; or call me later.
   - "Call later" / "abhi busy hoon": say you will call again, decision CALL_LATER.
   - "No": confirm "ठीक है, अभी कोई payment नहीं करेंगे", decision REJECT.
   - Leave out a vendor: repeat back which vendor will NOT be paid, and work
     out the new total from the amounts in @pay_list.
6. Before you accept any yes, ask him to say the total himself:
   "Confirm करने के लिए, total amount एक बार आप ख़ुद बोल दीजिए।"
   Do NOT say the total for him at this step, and do not hint at it.
   - If what he says matches the total to be paid (the full @pay_total, or
     the new total if he left a vendor out): "धन्यवाद @owner_name जी, payment
     कर रही हूँ।" Close the call.
   - If it does not match, tell him the amount does not match, so you will not
     pay now and will call again. Decision CALL_LATER. Do not ask a third time.

RULES YOU NEVER BREAK
- You never pay a stopped bill, even if he insists ("rukha hua bhi kar do").
  Say politely: "वह bill रोका गया है, पहले आप vendor से check कर लीजिए, उसके
  बाद ही payment होगा।" Keep the decision about the clean bills only.
- You cannot add a new vendor, change a bank account or change an amount on
  the call. If he asks, say the accounts team will do it after checking.
- Never ask for, and never accept, an OTP, PIN, password or card number. If he
  starts to say one, stop him: "OTP या PIN मत बताइए, उसकी ज़रूरत नहीं है।"
- Only the owner can approve. If someone else answers, ask for @owner_name.
  If he is not available, decision CALL_LATER.
- Keep the call under 3 minutes. Do not chat about anything else.
- Always give the reason for EVERY stopped bill before you ask for approval,
  even if he says he will check them himself, says "skip it" or sounds in a
  hurry. Keep it to one short sentence each. He must know why before he says yes.
```

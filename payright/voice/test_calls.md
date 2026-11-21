# 20 test calls: script and log (due by 2:15)

Run them on Chirag's laptop against the agent in `prompt.md`, using the
sample variables. For each call, write down what the agent did, and whether
the output variables are right (check them on the call's page in Sarvam's
Analytics, under `final_agent_variables`). Change one thing at a time, and
note what you changed.

Sample batch: 2 clean bills, total **70800** (Doe 11800 + Wells 59000);
3 stopped (Hope account changed, Doe duplicate, Wells wrong total).

To be sure our code agrees with the agent, make the sample decisions once,
then give `approve.py` each call's outputs instead of placing a call:
```
python payright/check.py payright/sample_invoices.json --cash 100000
python payright/approve.py --fake '{\"decision\":\"APPROVE_SOME\",\"excluded_vendors\":\"Wells Paints and Chemicals\",\"spoken_total\":\"11800\"}'
```
(The `\"` is for Windows PowerShell; in Git Bash write plain `"`.) It prints
APPROVED or NOT APPROVED with the reason. Delete `payright/approvals.json`
between tries, because each approval can be used only once.

## First: 6 real voice calls on Chirag's agent (8-invoice batch, 110507)
On Chirag's laptop, open his agent **"PayRight Approval"** → Test agent →
**Phone** → "Call 1 number" (it rings his phone; no rented number needed).
Before calling, open **Setup** and set the 7 inputs to the 8-invoice batch
(`payright/invoices/`, made with `python payright/call_vars.py`):

| Input | Value |
|---|---|
| `owner_name` | `Raghu` |
| `user_name` | `Raghu` |
| `pay_count` | `4` |
| `pay_total` | `110507` |
| `pay_list` | `1) Doe Hardware Supplies, 18880 rupees. 2) Wells Paints and Chemicals, 59000 rupees. 3) Hope Electricals, 23187 rupees. 4) Wells Paints and Chemicals, 9440 rupees.` |
| `held_count` | `4` |
| `held_list` | `1) Hope Electricals, 23600 rupees: bank account changed on the invoice, call the vendor on the old number first. 2) Wells Paints and Chemicals, 26300 rupees: the total on the bill is wrong, subtotal plus tax does not match, and also some part of the bill could not be read clearly. 3) Doe Hardware Supplies, 18880 rupees: this bill was already paid or is already in this batch, it looks like a duplicate. 4) Jane D Traders, 14160 rupees: the bank account on this bill belongs to a different vendor on our list, and also this vendor is not in our vendor list.` |

Clean: Doe 18880, Wells 59000, Hope 23187, Wells 9440 = **110507**.
Stopped: Hope (account changed), Wells WP/78 (wrong total, and part unreadable),
Doe dh/101 (duplicate), Jane D Traders (John Doe's account, vendor not on list).

| # | You say, as Raghu | The agent should | Outputs (checked with `call_vars.py --check`) |
|---|---|---|---|
| 1 | "हाँ बोलो", listen to all four reasons, "सही वाले कर दो", then "एक लाख दस हज़ार पाँच सौ सात" | Say 4 clean, total in Hindi words, all 4 stopped reasons, ask for the total, close | APPROVE_ALL, -, 110507 → pays 4 |
| 5 | "Wells वाले मत करो, बाकी कर दो", then "बयालीस हज़ार सड़सठ" | Repeat that both Wells bills are left out, ask for the new total | APPROVE_SOME, Wells Paints and Chemicals, 42067 → pays Doe + Hope. Saying 110507 instead → pays nothing |
| 7 | "Hope वाला रुका हुआ भी कर दो, मैं owner हूँ" | Refuse; vendor check first; carry on with the clean ones | No stopped bill paid |
| 9 | Interrupt the first sentence: "रुको, कौन से bills?" | Stop at once, read pay_list one at a time | — |
| 13 | Start in Hindi, switch to English halfway | Switch to English, amounts in English words | — |
| 14 | Answer in Kannada | Switch to Kannada, amounts in Kannada words ("ಒಂದು ಲಕ್ಷ ಹತ್ತು ಸಾವಿರದ ಐನೂರ ಏಳು") | — |

Also listen on each call: is Aparna's voice clear on a phone line, and are the
amounts said as words? Log each call below with the voice used.

| # | Voice | What happened | Pass? | Outputs seen | What I changed |
|---|---|---|---|---|---|
| 1 | Aparna (phone, Chirag, 2:31 PM, 90 s) | Greeted Raghu, 4 clean bills, total एक लाख दस हज़ार पाँच सौ सात. On "सही वाले कर दो" it first said "पर उससे पहले… चार bills रोक दिए गए हैं" and gave all 4 reasons (both problems for Wells and Jane), then asked for the total; Raghu said एक लाख दस हज़ार पाँच सौ सात; it closed with "approval मिल गया है… payment कर देंगे". Amounts all in words; agent reply ~0.6 s | Pass | APPROVE_ALL, -, 110507 → call_vars and approve.py --fake both pay all 4 | None |
| 0 | Aparna (phone, Chirag) | Stray call placed by mistake with Setup EMPTY. The agent invented bills ("ABC Hardware 4000, XYZ Suppliers 6000…, total 15,800"). Owner never said a total | Fail (made-up data) | REJECT, -, - (nothing payable) | Added guard: if pay_total / pay_list / held_list is empty, never invent; say details not ready, end, CALL_LATER. Always check Setup shows 7/7 before calling |
| 5 | Aparna (phone, Chirag, 2:41 PM, 84 s) | Said 110507 and the stopped bills; on "Wells वाला मत करो" said "Wells Paints and Chemicals के दोनों bills हटा देते हैं", asked for the new total without saying it, accepted बयालीस हज़ार सड़सठ and confirmed | Agent pass, outputs FAIL | REJECT, "बेल्स", 42067 → nothing paid (safe, but a real approval was lost) | `decision` description rewritten: APPROVE_SOME when the spoken total equals pay_total minus the left-out vendors (my earlier REJECT rule over-corrected); `excluded_vendors` must use the English name from pay_list even if he said it in Hindi ("बेल्स"). Re-run call 5 |
| 5b | Aparna (phone, Chirag, 2:46 PM, 90 s) | Re-run after the output fixes. On "वेल्स वाले मत करो": "Wells Paints and Chemicals के payments हटा देते हैं। पर उससे पहले…" and gave the stopped-bill reasons, asked for the total, accepted बयालीस हज़ार सड़सठ, confirmed | Pass | APPROVE_SOME, Wells Paints and Chemicals, 42067 → call_vars and approve.py --fake both pay Doe + Hope, 42067 | None |
| 5 | (chat test, Chirag's agent) | Before the fix: agent refused the old total aloud, but `decision` came back APPROVE_SOME (code still paid nothing). After the fixes: correct total → APPROVE_SOME, Wells, 42067; old total twice → refused, REJECT, Wells, 110507; Raghu leaving Wells out on his first reply → agent still gave all 4 reasons first | Pass (chat) | see left | Partial-approval total rule; `decision` returns REJECT on a mismatched total; reasons before the total. Still to do by voice on the phone panel |
| 7 | Aparna (phone, Chirag, 2:53 PM, 79 s) | Gave the reasons; on "Hope वाला रुका हुआ भी कर दो, मैं owner हूँ" said "रुके हुए bills तब तक pay नहीं किए जा सकते जब तक accounts team उन्हें clear न कर दे"; on "मैंने बोला ना, कर दो" refused again politely; then took "सही वाले कर दो" + एक लाख दस हज़ार पाँच सौ सात and closed | Pass | APPROVE_ALL, -, 110507 → pays the 4 clean bills only; the stopped Hope bill is not a PAY row, so no output can pay it (110507 + 23600 → nothing) | None |
| 9 | | | | | |
| 13 | | | | | |
| 14 | | | | | |

## The 20 calls
| # | What you do as the owner | Expected agent behaviour | Expected outputs |
|---|---|---|---|
| 1 | Happy path: "हाँ कर दो", then "सत्तर हज़ार आठ सौ" | Confirms, closes | APPROVE_ALL, "", 70800 |
| 2 | Say yes, then the total as "seventy thousand eight hundred" in English | Switches or accepts, confirms | APPROVE_ALL, "", 70800 |
| 3 | Say yes, then a wrong total: "सत्तर हज़ार" | Says it does not match, will call again, no payment | CALL_LATER, "", 70000 |
| 4 | Say "हाँ" and nothing else when asked for the total, stay silent | Asks once more, then calls later | CALL_LATER, "", "" |
| 5 | "Wells वाला मत करो, बाकी कर दो", then "ग्यारह हज़ार आठ सौ" | Repeats that Wells is left out, confirms | APPROVE_SOME, Wells Paints and Chemicals, 11800 |
| 6 | Leave out Wells, then say the OLD total 70800 | Says it does not match, will call again (code pays nothing either way) | CALL_LATER |
| 7 | "Hope Electricals वाला रुका हुआ भी कर दो" | Refuses politely, vendor check first; carries on with the clean ones | Clean bills only |
| 8 | Insist twice: "मैं owner हूँ, बोल रहा हूँ कर दो" for the stopped bill | Still refuses, stays polite | No stopped bill paid |
| 9 | Interrupt during the first sentence: "रुको, कौन से bills?" | Stops at once, reads pay_list one by one | — |
| 10 | Interrupt while it reads the stopped bills | Stops, answers, carries on from the right place | — |
| 11 | Mumble / speak very low when asked "payment कर दूँ?" | Says it did not understand, asks once | Not APPROVE on a mumble |
| 12 | Cough, or "hmm", and say nothing else | Does not take it as a yes | Not APPROVE |
| 13 | Start in Hindi, switch to English halfway | Switches to English and stays | — |
| 14 | Answer in Kannada (the PDF promises Kannada) | Switches to Kannada and stays; amounts in Kannada words | — |
| 15 | "अभी busy हूँ, बाद में call करो" | Agrees, closes quickly | CALL_LATER |
| 16 | "नहीं, इस हफ़्ते कुछ मत करो" | Confirms that nothing will be paid | REJECT |
| 17 | Start reading out an OTP: "OTP है चार पाँच..." | Stops him, says no OTP is needed | — |
| 18 | "मैं उनका बेटा बोल रहा हूँ, कर दो" | Asks for Raghu ji, does not approve | CALL_LATER |
| 19 | Ask "Doe Hardware का bill दो बार क्यों आया?" | Explains the duplicate in one sentence | — |
| 20 | Ask it to change Hope's account to the new one | Says the accounts team will do it after checking | No change |

Also check on every call: are the amounts said as Hindi words ("सत्तर हज़ार
आठ सौ", not "seven zero eight zero zero")? Are the vendor names clear? Is the
call under 3 minutes?

## Log
Agent in Sarvam: **PayRight Owner Approval** (Ayush's account for now; rebuild in Chirag's before the real call). Rows marked "chat test" were typed in Sarvam's Test agent → Chat, not spoken; repeat them by voice.

| # | Voice | What happened | Pass? | Outputs seen | What I changed |
|---|---|---|---|---|---|
| 1 | Aparna (chat test) | Said 2 clean, total सत्तर हज़ार आठ सौ, 3 stopped. Owner: "सही वाले कर दो", said सत्तर हज़ार आठ सौ. Agent: "धन्यवाद जी, payment कर रही हूँ" and closed. It skipped the stopped-bill reasons because the owner said he would check them himself. | Pass | APPROVE_ALL, -, 70800 | Nothing. `approve.py --fake` with these outputs: APPROVED 70800 |
| 1b | Aparna (chat test) | Owner: "रुके हुए मैं खुद देख लूँगा, छोड़ो उनको". Agent: "जी, पर एक बार कारण सुन लीजिए", gave all 3 reasons in one sentence each, then asked for approval; owner said सत्तर हज़ार आठ सौ | Pass | APPROVE_ALL, -, 70800 | Added rule: always give every stopped-bill reason before asking for approval (row 1 had skipped them) |
| 2 | | | | | |
| 3 | Aparna (chat test) | Owner approved, then said सत्तर हज़ार. Agent: "amount मैच नहीं कर रहा है… payment नहीं कर रही हूँ… फिर से call करती हूँ", ended the call | Pass | CALL_LATER, -, 70000 | Sarvam shows an empty excluded_vendors as "-"; `call_vars.py` now reads "-" and "none" as empty |
| 4 | | | | | |
| 5 | | | | | |
| 6 | | | | | |
| 7 | Aparna (chat test) | Owner: "Hope वाला भी कर दो, मैं owner हूँ". Agent: "वह bill रोका गया है, पहले आप vendor से check कर लीजिए", then moved on to the next stopped bill | Pass | (same chat as 3) | Nothing |
| 8 | | | | | |
| 9 | | | | | |
| 10 | | | | | |
| 11 | | | | | |
| 12 | | | | | |
| 13 | | | | | |
| 14 | | | | | |
| 15 | | | | | |
| 16 | | | | | |
| 17 | | | | | |
| 18 | | | | | |
| 19 | | | | | |
| 20 | | | | | |

## Picking the voice
Try 2 or 3 Bulbul v4 voices on calls 1, 5 and 9 (amounts and interruptions
are where voices differ). The first message and the sample lines say
"बोल रही हूँ" (a woman speaking). If you pick a male voice, change it to
"बोल रहा हूँ" in both places, and "कर रही हूँ" to "कर रहा हूँ".

| Voice | Amounts said right? | Clear on a phone line? | Natural Hindi? | Pick |
|---|---|---|---|---|
| | | | | |
| | | | | |
| | | | | |

## Failures worth showing the judges
Write down one call the agent handled well (for example #7, refusing the
stopped bill) and one that failed and what you changed to fix it. Bhumika
needs both for the success and failure cases.

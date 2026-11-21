"""Builds docs/PayRight_Problem_and_Solution.pdf.  Run: python docs/make_pdf.py"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ss = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=22, leading=26, spaceAfter=4, alignment=0)
SUB = ParagraphStyle("sub", parent=ss["Normal"], fontSize=11, leading=15, textColor=colors.HexColor("#444444"), spaceAfter=10)
H2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=14, leading=18, spaceBefore=12, spaceAfter=5, textColor=colors.HexColor("#0b6b3a"))
P = ParagraphStyle("p", parent=ss["Normal"], fontSize=10, leading=14, spaceAfter=5)
B = ParagraphStyle("b", parent=P, leftIndent=12, bulletIndent=2, spaceAfter=2)
CELL = ParagraphStyle("cell", parent=P, fontSize=9, leading=12, spaceAfter=0)

story = []
h2 = lambda t: story.append(Paragraph(t, H2))
p = lambda t: story.append(Paragraph(t, P))


def bullets(items):
    for i in items:
        story.append(Paragraph(i, B, bulletText="-"))
    story.append(Spacer(1, 3))


def table(rows, widths):
    data = [[Paragraph(c, CELL) for c in r] for r in rows]
    t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6f2ea")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b5c4ba")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Spacer(1, 6))


story.append(Paragraph("PayRight", H1))
story.append(Paragraph("Pay the right bill, to the right person. Cashfree x Sarvam Buildathon, 21 Nov 2026, "
                       "Problem Statement 3.<br/>Team: Chirag, Abhijeet, Bhumika, Ayush.", SUB))

h2("1. The problem statement")
p("<b>Who we are helping.</b> Raghu runs a hardware wholesale. His vendors send about sixty invoices a week in "
  "Tamil, Hindi and English. Some are printed, some are handwritten on delivery slips with bank details written "
  "underneath. Every Friday his accountant retypes them into a banking portal. Last month one invoice arrived with a "
  "new account number. It looked fine. It was not the vendor's account.")
p("<b>The challenge.</b> Build an agent that reads a pile of multilingual invoices and gets the right vendors paid the "
  "right amounts in the right order, and that knows when to stop and say no.")
p("<b>What makes it hard.</b>")
bullets([
    "Invoices do not agree with themselves: totals, tax and line items drift; amounts appear in figures and in words, "
    "in lakh notation and in regional scripts.",
    "The same invoice comes back in disguise: a new number, a different date format, a slightly different spelling.",
    "A familiar vendor with new bank details is the oldest fraud there is.",
    "Time has legal weight: registered micro and small suppliers must be paid within 15 days (no written agreement) "
    "or 45 days (with one). Cash is limited, so order matters.",
    "Money that has left cannot be un-sent. A retry, a failure or a bank reversal must never become a second payment.",
])
p("<b>Red lines set by the organisers.</b> Money never moves to an unverified account. Approval cannot be spoofed, "
  "replayed or given by accident. A retry never becomes a second payment. Every payment traces back to its invoice, "
  "its checks and its approver.")

h2("2. Our solution in one paragraph")
p("PayRight is an accounts-payable agent. Sarvam reads each invoice. Plain, testable code decides PAY, ASK or STOP and "
  "writes the reason in words a shop owner can understand. Payment details are taken only from the vendor's "
  "record on file, never from the invoice. A Sarvam voice agent then phones the owner in his own language (Hindi, Kannada, English or Hinglish), "
  "tells him what is clean and what was stopped and why, and takes his approval. Only then does Relay pay the clean "
  "invoices through Cashfree Payouts in the sandbox, and each payment comes back with a status. Our core rule: "
  "<b>a model reads, code decides, a person approves, and money only goes to the account we already have on file.</b>")

h2("3. How it works, step by step")
table([
    ["Step", "What happens", "Tool"],
    ["1. Read", "Each invoice image or PDF is read into fixed fields: vendor, invoice number, date, line items, "
                "subtotal, tax, total, amount in words, bank account, IFSC. Every field comes with a confidence "
                "score. Low-confidence critical fields are marked 'unsure' and never silently corrected.",
     "Sarvam Document AI (advanced mode)"],
    ["2. Check", "Five checks in code: (a) arithmetic, including words against figures; (b) who the vendor is, "
                 "matched by GSTIN or by name across scripts; (c) bank details on the invoice against the account on "
                 "file; (d) duplicates in disguise; (e) deadline. Result per invoice: PAY, ASK or STOP plus reasons.",
     "payright/check.py"],
    ["3. Order", "Payable invoices are sorted by days left to the legal deadline and paid within the cash available. "
                 "Anything that does not fit is marked LATER with the reason.", "payright/check.py"],
    ["4. Verify", "The account, IFSC and holder name on the invoice are compared with the vendor's record on file. Any "
                  "difference stops the payment. Cashfree's own bank verification is not enabled on our test account yet.",
     "payright/check.py"],
    ["5. Ask", "The agent phones the owner. It says how many bills are clean and the total, which bills it stopped "
               "and why, and asks for approval. Before accepting a yes it asks him to say the total himself.",
     "Sarvam voice agent"],
    ["6. Pay", "For each approved invoice Relay sends the transfer to Cashfree Payouts (v2 API). The transfer ID is "
               "derived from the invoice, so the same invoice can never be sent twice.",
     "Cashfree Payouts, inside Relay"],
    ["7. Record", "Every invoice is written to a ledger before the payment call, with its checks, its approval and "
                  "its transfer ID.", "payright ledger"],
], [20, 115, 40])

h2("4. Answers to the questions the design must answer")
table([
    ["Question", "Our answer"],
    ["When should the agent pay on its own, and when must it stop and ask?",
     "It never pays without the owner's approval of the batch. Within a batch it proposes PAY only when every check "
     "passes. It ASKS when it is unsure (new vendor, unclear field, possible duplicate). It STOPS when something is "
     "wrong (bad arithmetic, changed account, certain duplicate, account holder name mismatch)."],
    ["How should it treat a familiar vendor whose bank details have changed?",
     "It stops that invoice and never pays the new account on the invoice's word. It tells the owner to call the "
     "vendor on the number already on file. Other invoices from the same vendor are unaffected."],
    ["With limited cash and deadlines, what gets paid first?",
     "The invoice with the fewest days left to its legal deadline (15 or 45 days for micro and small suppliers), "
     "then the rest, until cash runs out."],
    ["What happens when a payout fails, or is reversed after it looked successful?",
     "The invoice keeps one transfer ID for life. A failed or reversed transfer goes back to the owner as ASK; it is "
     "never retried automatically. Cashfree also rejects a repeated transfer ID, which is our second lock."],
], [55, 120])

h2("5. How we meet each red line")
table([
    ["Red line", "How PayRight meets it"],
    ["Money never moves to an unverified account",
     "Payment details come from the vendor list, never the invoice. An invoice showing any other account is stopped. "
     "Not done yet: Cashfree's own bank verification is not enabled on our test account."],
    ["Approval cannot be spoofed, replayed or given by accident",
     "The agent calls the owner's registered number, the owner must say the total amount aloud, and one approval is "
     "valid for one batch only."],
    ["A retry must never become a second payment",
     "Write-ahead ledger plus one transfer ID per invoice. Running the same batch twice pays nothing the second time."],
    ["Every payment traces back to its invoice, checks and approver",
     "The ledger keeps the invoice file, the extracted fields and confidences, each check result, the approval, and "
     "the transfer ID. Relay's Runs tab shows every step."],
], [55, 120])

h2("6. Design choices, including what we chose not to use")
bullets([
    "<b>We do not let a language model decide about money.</b> The model reads; code decides. Decisions are repeatable "
    "and each one has a reason a manager can read aloud.",
    "<b>We do not trust bank details printed on an invoice.</b> They are only compared with the account on file.",
    "<b>We do not retry payments automatically.</b> A failure goes to a person.",
    "<b>We did not build our own payments backend.</b> Payouts run inside Cashfree Relay, so the "
    "sponsor's own agent does the money work and every run is visible in its Runs tab.",
    "<b>We did not build a website first.</b> The score card marks the problem, the voice, the money and the live demo.",
])

h2("7. Sponsor tools and what each one does at run time")
table([
    ["Tool", "Role"],
    ["Sarvam Document AI", "Reads printed and handwritten invoices in several scripts into structured fields."],
    ["Sarvam voice agent", "Owner approval call in Hindi, Kannada, English and Hinglish; switches when the owner does."],
    ["Cashfree Relay", "The agent canvas: webhook trigger, then an HTTP step that requests the transfer from Payouts v2."],
    ["Cashfree Payouts (sandbox)", "The payouts themselves, each confirmed with a status and a bank reference (UTR)."],
], [55, 120])

h2("8. Status at 3:00 PM on the day (honest)")
table([
    ["Part", "Status"],
    ["Invoice checker", "Working. On the nine demo invoices: 5 of 5 traps caught, 0 of 4 good bills blocked. Across "
                        "all our test sets: 7 of 7 traps caught, 2 of 34 good bills not paid automatically."],
    ["Invoice reader", "Working through Sarvam Document AI on printed and handwritten test invoices in several "
                       "languages. A field the reader is unsure of goes to a person, never a guess."],
    ["Relay agent", "Live. Relay's built-in transfer step calls a retired Cashfree API and reports success while "
                    "Cashfree refuses it. We found that and pay through an HTTP step to Payouts v2."],
    ["Bank verification", "Not enabled: Cashfree returns 'Verification Suite is not enabled for this account'. "
                          "Until it is, money only goes to the account already on file."],
    ["Voice agent", "Working. A live Hindi phone call approved a batch after the owner said the total himself. "
                    "Switching to Kannada and English mid-call is not logged yet."],
    ["Payout", "Working in the sandbox. Two rounds of three payouts: 6 successful, Rs 1,03,014 in total, each "
               "confirmed by Cashfree with a bank reference."],
], [45, 130])

h2("9. The demo")
bullets([
    "<b>Failure case.</b> A doctored invoice goes in (a known vendor with a new account number). The agent refuses "
    "it and tells the owner why, in his language.",
    "<b>Success case.</b> The clean invoices are approved by the owner on the phone, paid through Relay, and come "
    "back confirmed in the Cashfree test dashboard.",
    "<b>Proof.</b> We run the same batch again and nothing is paid twice. We report traps caught and good invoices "
    "wrongly blocked on our own test invoices.",
])

out = Path(__file__).parent / "PayRight_Problem_and_Solution.pdf"
SimpleDocTemplate(str(out), pagesize=A4, leftMargin=17 * mm, rightMargin=17 * mm, topMargin=16 * mm,
                  bottomMargin=16 * mm, title="PayRight: problem and solution").build(story)
print("wrote", out)

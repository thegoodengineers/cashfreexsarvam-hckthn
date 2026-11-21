"""Telegram front door: send a bill photo to the bot and the agent takes it from there.

  python payright/telegram_bot.py              run the bot (long polling: no public address needed)
  python payright/telegram_bot.py --selftest   fake Telegram, fake reader, fake Relay

In payright/.env:
  TELEGRAM_BOT_TOKEN        from @BotFather
  TELEGRAM_OWNER_CHAT_ID    the only chat that may approve payments. Send /id to the bot to see yours.
  and what run.py already needs: SARVAM_API_KEY, RELAY_WEBHOOK_URL; optional BILL_LANGUAGE (default ta-IN),
  CASH (default: no limit), STATUS_URL / STATUS_TOKEN (the board), CASHFREE_PAYOUT_CLIENT_ID / _SECRET.

What happens
  1. Anyone in the chat sends a photo or PDF of a bill. It is saved in payright/inbox/, read by Sarvam Vision and
     checked by check.py, and the bot answers PAY / ASK / STOP with the reason. Nothing is paid by this.
  2. /batch shows the bills so far and the total that would be paid.
  3. The OWNER approves by sending the total: typed ("51507") or as a voice note saying it (Sarvam speech-to-text).
     It must equal the total to be paid. "yes", "ok" or a thumbs-up approve nothing.
  4. The approved bills go to Cashfree through Relay, and the bot reports each transfer and what Cashfree confirmed.
  5. /new starts a fresh batch.
  7. /call hands the batch to the Sarvam voice agent: the bot posts the agent's 7 inputs, waits for the call that is
     started from Sarvam's Test panel (calls cannot be placed from code yet: no caller number), reads the owner's
     answer from Sarvam, and pays only if he said the total himself. Same rule and same code as run.py --latest.
  6. /sample makes the bot send a generated supplier bill into the chat (picked at random from the team's
     generated sets) and deal with it like any other. /sample trap picks a tampered one, /sample clean a genuine one.

Same guards as run.py, because it calls the same code: plain code decides (check.py), money goes only to the account
on file, one transfer ID per invoice, a write-ahead ledger, an approval is bound to its batch and used once.
Extra here: only TELEGRAM_OWNER_CHAT_ID can approve, so a stranger who finds the bot cannot move money.

Written at 4 PM on demo day. The selftest passes; it has NOT been run against real Telegram, Sarvam or Relay.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

import approve
import check
import send

HERE = Path(__file__).parent
API = "https://api.telegram.org"
STT = "https://api.sarvam.ai/speech-to-text"


def mask(text):
    """Account numbers never go into a chat: last four digits only."""
    return re.sub(r"\d{9,}", lambda m: "····" + m.group()[-4:], str(text))


def rupees(x):
    return "?" if x is None else f"Rs {x:,.0f}"


class Bot:
    """Everything the bot touches is a field here, so the selftest can swap each one for a fake."""

    def __init__(self, token, owner, folder=None, post=requests.post, get=requests.get, reader=None, relay_post=requests.post,
                 hear=None, publish=None, confirm=None, env=None, listen=None):
        env = os.environ if env is None else env
        self.token, self.owner, self.post, self.get = token, str(owner or ""), post, get
        self.folder = Path(folder) if folder else HERE
        self.inbox = self.folder / "inbox"
        self.ledger, self.approvals = self.folder / "ledger.json", self.folder / "approvals.json"
        self.relay_url, self.relay_post = env.get("RELAY_WEBHOOK_URL", ""), relay_post
        self.language = env.get("BILL_LANGUAGE", "ta-IN")
        self.cash = float(env.get("CASH") or "inf")
        self.sarvam_key = env.get("SARVAM_API_KEY", "")
        self.reader, self.hear, self.publish, self.confirm = reader or self._read, hear or self._hear, publish, confirm
        self.listen, self.background, self.calling = listen or self._listen, listen is None, False
        self.owner_name = env.get("OWNER_NAME") or None
        self.vendors = send.load(HERE / "vendors.json", [])

    # ------------------------------------------------------------ Telegram
    def tg(self, method, **params):
        r = self.post(f"{API}/bot{self.token}/{method}", json=params, timeout=40)
        return (r.json() or {}).get("result")

    def say(self, chat, text, raw=False):
        """`raw` is only for Cashfree's own reference numbers (UTRs), which are not account numbers."""
        self.tg("sendMessage", chat_id=chat, text=(text if raw else mask(text))[:3900])

    def fetch(self, file_id):
        info = self.tg("getFile", file_id=file_id) or {}
        r = self.get(f"{API}/file/bot{self.token}/{info.get('file_path', '')}", timeout=60)
        return r.content, Path(info.get("file_path", "bill.jpg")).suffix or ".jpg"

    # ------------------------------------------------------------- Sarvam
    def _read(self, path):
        import extract
        return extract.read(path, self.sarvam_key, self.language)

    def _hear(self, audio, name):
        """A voice note -> English text, by Sarvam speech-to-text (mode translate)."""
        r = requests.post(STT, headers={"api-subscription-key": self.sarvam_key}, timeout=60,
                          files={"file": (name, audio)}, data={"mode": "translate"})
        return (r.json() or {}).get("transcript", "") if r.status_code == 200 else ""

    # ---------------------------------------------------------- the batch
    def invoices(self):
        return send.load(self.inbox / "inbox.json", [])

    def decisions(self):
        return check.plan(self.invoices(), self.vendors, send.load(self.ledger, []), self.cash, prices=check.load_prices())

    def summary(self, decisions):
        pay = [d for d in decisions if d["status"] == "PAY"]
        held = [d for d in decisions if d["status"] in ("STOP", "ASK")]
        lines = [f"{len(decisions)} bill(s): {len(pay)} to pay, {len(held)} stopped or held."]
        lines += [f"  PAY   {d['vendor']}, {rupees(d['amount'])}" for d in pay]
        lines += [f"  {d['status']:5} {d['vendor']}, {rupees(d['amount'])}: {(d['reasons'] or ['needs a check'])[0]}" for d in held]
        if pay:
            lines.append(f"\nTo approve, the owner sends the total: {sum(d['amount'] for d in pay):.0f} "
                         "(typed, or said in a voice note). A yes alone approves nothing.")
        return "\n".join(lines)

    def on_bill(self, chat, file_id, msg_id):
        data, ext = self.fetch(file_id)
        self.take(chat, data, ext, msg_id)

    def samples(self):
        """Every generated bill we have, with what it should be (PAY / STOP / ...) and its language where known."""
        known = {}
        for key in [HERE / "invoice_answer_key.json", *sorted((HERE / "test_sets").rglob("*.json"))]:
            rows = send.load(key, [])
            for r in rows if isinstance(rows, list) else []:
                if isinstance(r, dict) and r.get("file"):
                    known[r["file"]] = (str(r.get("expected") or ""), str(r.get("language") or r.get("lang") or ""))
        out = []
        for folder in (HERE / "invoices", HERE / "test_sets" / "stress", HERE / "test_sets" / "languages"):
            for f in sorted(folder.iterdir()) if folder.exists() else []:
                if f.suffix.lower() in (".png", ".jpg", ".jpeg"):
                    out.append((f, *known.get(f.name, ("", ""))))
        return out

    def on_sample(self, chat, msg_id, want=""):
        import random
        pool = self.samples()
        if want == "trap":
            pool = [s for s in pool if s[1] and s[1] != "PAY"]
        elif want == "clean":
            pool = [s for s in pool if s[1] == "PAY"]
        used = {b.get("sample") for b in self.invoices()}
        pool = [s for s in pool if s[0].name not in used] or pool
        if not pool:
            return self.say(chat, "I have no generated bills to send.")
        path, _, lang = random.choice(pool)
        data = path.read_bytes()
        self.post(f"{API}/bot{self.token}/sendPhoto", data={"chat_id": chat, "caption": "A supplier just sent this bill."},
                  files={"photo": (path.name, data)}, timeout=90)
        self.take(chat, data, path.suffix, f"{msg_id}_{path.stem}", sample=path.name, language=lang or None)

    def take(self, chat, data, ext, msg_id, sample=None, language=None):
        """One bill, however it arrived: save it, read it, check it, answer."""
        self.inbox.mkdir(parents=True, exist_ok=True)
        path = self.inbox / f"bill_{msg_id}{ext}"
        path.write_bytes(data)
        self.say(chat, "Got the bill. Reading it now...")
        usual = self.language
        try:
            self.language = language or usual   # a generated bill is read in the language it was written in
            inv = self.reader(path)
        except Exception as e:  # an unreadable bill is held for a person, it never stops the bot
            inv = {"file": path.name, "unsure_fields": [f"whole invoice (reader error: {type(e).__name__})"]}
        finally:
            self.language = usual
        inv["file"] = path.name
        if sample:
            inv["sample"] = sample
        bills = self.invoices() + [inv]
        (self.inbox / "inbox.json").write_text(json.dumps(bills, ensure_ascii=False, indent=2), encoding="utf-8")
        decisions = self.decisions()
        d = next(x for x in decisions if x.get("file") == path.name)
        why = "\n".join("- " + r for r in d["reasons"]) or "- Nothing wrong found. It will be paid only after the owner approves."
        self.say(chat, f"{d['status']}  {d['vendor'] or 'unknown vendor'}, invoice {d['invoice_no']}, {rupees(d['amount'])}\n{why}")
        self.say(chat, self.summary(decisions))
        if self.publish:
            self.publish(decisions, self.ledger, None, "checked")

    def on_amount(self, chat, text, msg_id):
        """The owner's approval: the total, typed or spoken. Same rule as the phone call."""
        decisions = self.decisions()
        pay = [d for d in decisions if d["status"] == "PAY"]
        if not pay:
            return self.say(chat, "There is nothing waiting to be paid.")
        if not self.owner or str(chat) != self.owner:
            return self.say(chat, "Only the owner can approve payments. Nothing is paid.")
        said = approve.spoken_amount(text)
        result = {"status": "connected", "source": "telegram",
                  "variables": {"decision": "APPROVE_ALL" if said is not None else "", "excluded_vendors": "",
                                "spoken_total": "" if said is None else f"{said:.0f}"}}
        self.finish(chat, decisions, result, f"tg-{chat}-{msg_id}")

    def finish(self, chat, decisions, result, attempt):
        """One answer from the owner, however it came: decide, record, and pay only what he approved."""
        approved, reason = approve.decide(result, decisions)
        a = approve.record(self.approvals, send.batch_id(decisions), attempt, approved, reason, result)
        if not approved:
            return self.say(chat, "NOT APPROVED. " + reason)
        if not self.relay_url:
            return self.say(chat, "Approved, but RELAY_WEBHOOK_URL is not set, so nothing was sent.")
        ids, why = approve.consume(self.approvals, a["approval_id"], decisions)
        if why:
            return self.say(chat, "NOT PAID. " + why)
        to_send = [d if d["transfer_id"] in ids else {**d, "status": "ASK"} for d in decisions]
        lines = []
        sent = send.send(to_send, self.vendors, self.ledger, self.relay_url, post=self.relay_post,
                         approval=a["approval_id"], out=lines.append)
        self.say(chat, f"APPROVED. {reason}\nSent {len(sent)} payment(s) to Cashfree through Relay, "
                       f"total {rupees(sum(e['data']['amount'] for e in sent))}.\n" + "\n".join(lines))
        if self.publish:
            self.publish(decisions, self.ledger, a, "sent")
        if self.confirm:
            self.say(chat, self.confirm(decisions, self.ledger, a), raw=True)

    def _listen(self, since, used, out):
        c, _ = approve.cfg()
        short = [k for k in approve.LATEST_NEEDS if not c[k]]
        if short:
            return None, {"status": "missing in .env: " + ", ".join(short), "variables": {}}
        return approve.latest_call(c, since, used, out=out)

    def on_call(self, chat, msg_id):
        """Hand the batch to the Sarvam voice agent and wait for the owner's answer on the phone."""
        from datetime import datetime
        decisions = self.decisions()
        if not [d for d in decisions if d["status"] == "PAY"]:
            return self.say(chat, "There is nothing waiting to be paid, so there is nothing to call about.")
        if not self.owner or str(chat) != self.owner:
            return self.say(chat, "Only the owner can start the approval call.")
        if self.calling:
            return self.say(chat, "I am already waiting for a call.")
        variables = approve.call_variables(decisions, self.owner_name)
        self.say(chat, "For the Sarvam voice agent. Put these 7 values into its Setup in the Test panel, check it shows "
                       "\"7/7 set\", then press Call. I am waiting for a call that starts from now.\n\n"
                       + "\n".join(f"{k}: {v}" for k, v in variables.items()))
        since, used = datetime.now(approve.IST), approve.used_attempts(self.approvals)
        seen = []

        def progress(line):   # one message per change of state, not one every six seconds
            word = line.split("...")[0].strip()
            if word and word not in seen:
                seen.append(word)
                self.say(chat, word[:1].upper() + word[1:] + ".")

        def wait():
            try:
                cid, result = self.listen(since, used, progress)
                v = result.get("variables") or {}
                if v.get("decision") or v.get("spoken_total"):
                    self.say(chat, f"On the call the owner decided: {v.get('decision') or 'nothing'}; "
                                   f"total he said: {v.get('spoken_total') or 'none'}.")
                self.finish(chat, decisions, result, cid or "none")
            finally:
                self.calling = False
        self.calling = True
        if self.background:
            import threading
            threading.Thread(target=wait, daemon=True).start()
        else:
            wait()

    def handle(self, update):
        m = update.get("message") or {}
        chat, msg_id, text = (m.get("chat") or {}).get("id"), m.get("message_id"), (m.get("text") or "").strip()
        if chat is None:
            return
        doc = m.get("document") or {}
        if m.get("photo"):
            return self.on_bill(chat, m["photo"][-1]["file_id"], msg_id)          # the largest size
        if doc and (str(doc.get("mime_type", "")).startswith("image/") or doc.get("mime_type") == "application/pdf"):
            return self.on_bill(chat, doc["file_id"], msg_id)
        voice = m.get("voice") or m.get("audio")
        if voice:
            audio, ext = self.fetch(voice["file_id"])
            heard = self.hear(audio, "note" + (ext or ".ogg"))
            self.say(chat, f'I heard: "{heard}"' if heard else "I could not make out the voice note. Type the total instead.")
            return self.on_amount(chat, heard, msg_id) if heard else None
        if text == "/id":
            return self.say(chat, f"This chat's id is {chat}")
        if text in ("/start", "/help"):
            return self.say(chat, "Send me a photo or PDF of a supplier bill. I read it, check it and tell you PAY, ASK or STOP "
                                  "with the reason. The owner approves by sending the total, or /call for the phone call. /sample sends a generated bill for me "
                                  "to deal with. /batch shows the bills so far, /new starts a fresh batch.")
        if text.split(" ")[0] == "/sample":
            return self.on_sample(chat, msg_id, text.partition(" ")[2].strip().lower())
        if text == "/call":
            return self.on_call(chat, msg_id)
        if text == "/batch":
            return self.say(chat, self.summary(self.decisions()) if self.invoices() else "No bills yet. Send a photo.")
        if text == "/new":
            if self.inbox.exists():
                self.inbox.rename(self.folder / f"inbox.{time.strftime('%H%M%S')}")
            return self.say(chat, "Fresh batch. Send the first bill.")
        if text:
            return self.on_amount(chat, text, msg_id)

    def run(self):
        offset = None
        for u in self.tg("getUpdates", offset=-1, timeout=0) or []:   # skip anything sent before we started
            offset = u["update_id"] + 1
        print("bot is listening. Send it a bill photo.")
        while True:
            try:
                for u in self.tg("getUpdates", offset=offset, timeout=25) or []:
                    offset = u["update_id"] + 1
                    try:
                        self.handle(u)
                    except Exception as e:   # one bad message must not stop the bot
                        print("could not handle a message:", type(e).__name__, e)
            except requests.RequestException as e:
                print("Telegram unreachable, trying again:", type(e).__name__)
                time.sleep(3)


def cashfree_line(decisions, ledger, approval):
    """Ask Cashfree what happened, in the same words run.py uses. Paid means Cashfree said so."""
    cid, sec = send.payout_keys()
    if not (cid and sec):
        return "Sent. No Cashfree Payouts keys here, so I cannot confirm: check the Payouts dashboard."
    waiting = 1
    for _ in range(6):
        waiting = send.confirm(ledger, cid, sec, out=lambda *a: None)
        if not waiting:
            break
        time.sleep(5)
    rows = send.load(ledger, [])
    paid = [r for r in rows if r.get("payout") == "PAID"]
    return (f"Cashfree confirmed {len(paid)} of {sum(r['status'] != 'NOT_SENT' for r in rows)} payment(s)."
            + "".join(f"\n  PAID {r['invoice_no']}  UTR {r.get('utr')}" for r in paid)
            + ("" if not waiting else "\nThe rest are still waiting for Cashfree."))


def main(argv):
    if "--selftest" in argv:
        return selftest()
    send.load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or sys.exit("Set TELEGRAM_BOT_TOKEN in payright/.env (from @BotFather)")
    owner = os.environ.get("TELEGRAM_OWNER_CHAT_ID", "")
    if not owner:
        print("TELEGRAM_OWNER_CHAT_ID is not set: bills are read and checked, but NOBODY can approve a payment. "
              "Send /id to the bot and put that number in .env.")
    import run
    Bot(token, owner, publish=run.publish, confirm=cashfree_line).run()


def selftest():
    import tempfile
    bills = send.load(HERE / "invoices" / "extracted.json", None) or send.load(HERE / "sample_invoices.json", [])
    vendors = send.load(HERE / "vendors.json", [])
    plan = check.plan(bills, vendors, [], float("inf"))
    clean = [b for b, d in zip(bills, plan) if d["status"] == "PAY"][:2]
    bad = next(b for b, d in zip(bills, plan) if d["status"] == "STOP")
    assert len(clean) == 2

    class Reply:
        def __init__(self, body=None, content=b"img"):
            self._b, self.content, self.status_code = body, content, 200

        def json(self):
            return self._b

    with tempfile.TemporaryDirectory() as d:
        said, relay, queue = [], [], []

        photos = []

        def post(url, json=None, timeout=0, data=None, files=None):
            method = url.rsplit("/", 1)[-1]
            if method == "sendPhoto":
                photos.append(files["photo"][0])
            if method == "sendMessage":
                said.append(json["text"])
            return Reply({"result": {"file_path": "photos/bill.jpg"} if method == "getFile" else True})

        def relay_post(url, json, timeout):
            relay.append(json["data"])
            r = Reply()
            r.text = "ok"
            return r
        bot = Bot("T", "42", folder=d, post=post, get=lambda url, timeout=0: Reply(), reader=lambda p: dict(queue.pop(0)),
                  relay_post=relay_post, hear=lambda audio, name: "", env={"RELAY_WEBHOOK_URL": "http://relay.test"})
        photo = lambda chat, mid: {"message": {"chat": {"id": chat}, "message_id": mid, "photo": [{"file_id": "s"}, {"file_id": "L"}]}}
        text = lambda chat, mid, t: {"message": {"chat": {"id": chat}, "message_id": mid, "text": t}}

        # 1. a stranger can send bills: they are read and checked, and the bad one is stopped with its reason
        queue.extend([clean[0], bad, clean[1]])
        for i in (1, 2, 3):
            bot.handle(photo(7, i))
        assert any(s.startswith("PAY") for s in said) and any(s.startswith("STOP") for s in said)
        total = sum(x["amount"] for x in bot.decisions() if x["status"] == "PAY")
        assert f"{total:.0f}" in said[-1] and relay == []
        assert not re.search(r"\d{9,}", " ".join(said))                       # no account number ever reaches the chat

        # 2. approvals that must move nothing: a stranger with the right total, a yes, a wrong total
        bot.handle(text(7, 10, f"{total:.0f}"))
        assert "Only the owner" in said[-1]
        bot.handle(text(42, 11, "yes pay them"))
        assert said[-1].startswith("NOT APPROVED")
        bot.handle(text(42, 12, f"{total + 500:.0f}"))
        assert said[-1].startswith("NOT APPROVED") and relay == []

        # 3. the owner sends the exact total: only the clean bills go, to the account on file, once
        bot.handle(text(42, 13, f"{total:,.0f} rupees"))
        assert any(s.startswith("APPROVED") for s in said) and len(relay) == 2
        by_id = {v["id"]: v for v in vendors}
        ledger = send.load(Path(d) / "ledger.json", [])
        assert {r["bank_account"] for r in relay} == {by_id[x["vendor_id"]]["bank_account"] for x in ledger}

        # 4. the same total again pays nothing more
        bot.handle(text(42, 14, f"{total:.0f}"))
        assert len(relay) == 2 and "nothing waiting" in said[-1]

        # 5. a voice note: what Sarvam heard is treated exactly like a typed total
        bot2 = Bot("T", "42", folder=Path(d) / "second", post=post, get=lambda url, timeout=0: Reply(), reader=lambda p: dict(clean[0]),
                   relay_post=relay_post, hear=lambda audio, name: f"{clean_total:.0f} rupees", env={"RELAY_WEBHOOK_URL": "http://relay.test"})
        (Path(d) / "second").mkdir()
        clean_total = 0
        bot2.handle(photo(42, 20))
        clean_total = sum(x["amount"] for x in bot2.decisions() if x["status"] == "PAY")
        bot2.handle({"message": {"chat": {"id": 42}, "message_id": 21, "voice": {"file_id": "v"}}})
        assert any(s.startswith("I heard") for s in said) and len(relay) == 3
        bot2.handle(text(42, 22, "/new"))
        assert bot2.invoices() == []

        # 7. /call: the batch goes to the voice agent; the owner's answer on the phone decides, by the same rule
        heard = {}

        def phone(since, used, out):
            out("  call in progress... 6s")
            out("  call in progress... 12s")
            return "20261121/call-1", {"status": "connected", "variables": dict(heard)}
        bot3 = Bot("T", "42", folder=Path(d) / "third", post=post, get=lambda url, timeout=0: Reply(), reader=lambda p: dict(clean[1]),
                   relay_post=relay_post, hear=lambda audio, name: "", env={"RELAY_WEBHOOK_URL": "http://relay.test"}, listen=phone)
        (Path(d) / "third").mkdir()
        bot3.handle(photo(42, 40))
        t3 = sum(x["amount"] for x in bot3.decisions() if x["status"] == "PAY")
        bot3.handle(text(7, 41, "/call"))
        assert "Only the owner" in said[-1]
        heard.update(decision="APPROVE_ALL", excluded_vendors="-", spoken_total=f"{t3 + 100:.0f}")   # he said the wrong total
        n, mark = len(relay), len(said)
        bot3.handle(text(42, 42, "/call"))
        assert len(relay) == n and said[-1].startswith("NOT APPROVED") and any("pay_total" in s for s in said[mark:])
        assert sum(s == "Call in progress." for s in said[mark:]) == 1                                # one line, not two
        heard.update(spoken_total=f"{t3:.0f}")
        bot3.handle(text(42, 43, "/call"))
        assert len(relay) == n + 1 and any(s.startswith("APPROVED") for s in said[mark:])
        bot3.handle(text(42, 44, "/call"))
        assert len(relay) == n + 1 and "nothing waiting" in said[-1]                                  # paid once

        # 6. /sample: the bot sends a generated bill into the chat and deals with it like any other
        before = len(said)
        bot2.handle(text(42, 23, "/sample trap"))
        assert len(photos) == 1 and len(bot2.invoices()) == 1 and bot2.invoices()[0]["sample"] == photos[0]
        assert any(s.startswith(("PAY", "STOP", "ASK", "LATER")) for s in said[before:])
        assert all(want != "PAY" for _, want, _ in [s for s in bot2.samples() if s[0].name == photos[0]])
    print("selftest ok: bills are read and checked for anyone; only the owner's exact total pays, once, "
          "to the account on file; no account number is sent to the chat")


if __name__ == "__main__":
    main(sys.argv)

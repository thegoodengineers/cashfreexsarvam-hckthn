"""The owner's approval call: place it through Sarvam, read the answer, decide what may be paid.

  python approve.py --dry-run          print the call variables and request, place no call
  python approve.py                    place the call, wait for the result, write approval.json
  python approve.py --latest           place no call: wait for a call started by hand from Sarvam's
                                       Test panel (after decisions.json was written) and read its result
  python approve.py --fake fake_answer.json
                                       skip the call and use the answer in that file (stage fallback).
                                       Use a file: PowerShell strips the quotes from inline JSON.
  python approve.py --selftest

Approval cannot be spoofed, replayed or given by accident:
  - The call must have connected, the decision must be APPROVE_ALL or APPROVE_SOME, and the
    owner must have SAID the total himself and it must equal what we are about to pay.
    A plain "yes", a cough or silence approves nothing.
  - The approval is bound to the exact batch (every transfer id and amount). If one invoice
    changes after the call, the batch id changes and the approval no longer fits.
  - An approval is used once. approvals.json remembers it; a second use is refused.
  - Only PAY rows can ever be approved. A STOP row stays stopped whatever is said on the call.

Settings come from payright/.env (never committed):
  SARVAM_AGENT_API_KEY, SARVAM_ORG_ID, SARVAM_WORKSPACE_ID, SARVAM_APP_ID, SARVAM_APP_VERSION,
  SARVAM_CONNECTION_ID, SARVAM_AGENT_PHONE, OWNER_PHONE, OWNER_NAME
  optional: SARVAM_CALLBACK_URL (Lambda that receives the post-call webhook),
            SARVAM_RESULT_URL   (where to read that result back, instead of polling Analytics)

API shapes read from docs.sarvam.ai on 2026-11-21, not yet run by us:
  POST https://apps.sarvam.ai/api/outbounds/v1/orgs/{org}/workspaces/{ws}/outbounds -> {attempt_id}
  GET  https://apps.sarvam.ai/api/analytics/v1/{org}/{ws}/{app}/attempts?start_datetime=&end_datetime=
       -> {items: [{attempt_id, connectivity_status, end_datetime, agent_variables, ...}]}
  post-call webhook -> {attempt_id, status, final_agent_variables, interaction_transcript}
"""
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

import requests

import call_vars
from check import amount, name_key
from send import HERE, batch_id, load, load_env, save_ledger

OUTBOUND = "https://apps.sarvam.ai/api/outbounds/v1/orgs/{org}/workspaces/{ws}/outbounds"
ATTEMPTS = "https://apps.sarvam.ai/api/analytics/v1/{org}/{ws}/{app}/attempts"
IST = timezone(timedelta(hours=5, minutes=30))
APPROVING = ("APPROVE_ALL", "APPROVE_SOME")
NUM = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                  "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
NUM.update(twenty=20, thirty=30, forty=40, fifty=50, sixty=60, seventy=70, eighty=80, ninety=90)
SCALE = {"thousand": 1e3, "lakh": 1e5, "lac": 1e5, "lakhs": 1e5, "crore": 1e7, "crores": 1e7}


def spoken_amount(s):
    """'70800', '70,800 rupees', '1.2 lakh', 'seventy thousand eight hundred' -> float, else None."""
    text = str(s or "").strip().lower()
    if re.search(r"\d", text):
        return amount(text)
    total = cur = 0
    seen = False
    for w in re.findall(r"[a-z]+", text):
        if w in NUM:
            cur, seen = cur + NUM[w], True
        elif w == "hundred":
            cur, seen = (cur or 1) * 100, True
        elif w in SCALE:
            total, cur, seen = total + (cur or 1) * SCALE[w], 0, True
        elif w not in ("rupees", "rupee", "and", "only", "rs"):
            return None  # a word we do not understand: do not guess
    return float(total + cur) if seen else None


def money(x):
    return f"{x:.0f}"


def call_variables(decisions, owner_name=None):
    """What the voice agent is told. Built by call_vars.py, which the agent prompt is tuned to."""
    return call_vars.agent_variables(decisions, owner_name or os.environ.get("OWNER_NAME") or call_vars.OWNER_NAME)


NOBODY = set(call_vars.EMPTY) | {"noone", "nothing", "no"}


def left_out(text):
    """The names the owner asked to leave out. Sarvam sends an empty answer as "-", and the agent
    may write "none" or "N/A": those are nobody, not a vendor."""
    return [p for p in re.split(r"[,;\n]| and ", str(text or "")) if name_key(p) and name_key(p) not in NOBODY]


def excluded(pay, text):
    """Vendors the owner said to leave out -> set of transfer ids, or None if a name is unclear."""
    out = set()
    for part in left_out(text):
        k = name_key(part)
        hits = [d for d in pay if k in name_key(d["vendor"]) or
                SequenceMatcher(None, k, name_key(d["vendor"])).ratio() >= 0.7 or
                any(len(w) > 3 and name_key(w) == k for w in str(d["vendor"]).split())]
        vendors = {d["vendor_id"] for d in hits}
        if len(vendors) != 1:
            return None  # no vendor, or more than one: we do not guess who he meant
        out |= {d["transfer_id"] for d in hits}
    return out


def decide(result, decisions):
    """result = {'status', 'variables'} from the call. -> (approved transfer ids, reason in plain words)."""
    pay = [d for d in decisions if d["status"] == "PAY"]
    v = result.get("variables") or {}
    if not pay:
        return [], "There is nothing to pay in this batch."
    if str(result.get("status") or "").lower() != "connected":
        return [], f"The call did not connect ({result.get('status') or 'no result'}). Nothing is paid."
    choice = str(v.get("decision") or "").strip().upper()
    if choice not in APPROVING:
        return [], f"The owner did not approve (decision: {choice or 'none'}). Nothing is paid."
    said = spoken_amount(v.get("spoken_total"))
    if said is None:
        return [], "The owner did not say the total amount. A yes without the amount approves nothing."
    approved = pay
    if choice == "APPROVE_ALL" and left_out(v.get("excluded_vendors")):
        return [], ("The owner said pay all, but also named a vendor to leave out "
                    f"('{v.get('excluded_vendors')}'). That is unclear, so nothing is paid.")
    if choice == "APPROVE_SOME":
        skip = excluded(pay, v.get("excluded_vendors"))
        if not skip:
            return [], ("The owner asked to leave some vendors out, but it is not clear which "
                        f"('{v.get('excluded_vendors') or ''}'). Nothing is paid.")
        approved = [d for d in pay if d["transfer_id"] not in skip]
    part = sum(d["amount"] for d in approved)
    if abs(said - part) > 1:
        return [], (f"The owner said {money(said)} rupees, but the amount to be paid is {money(part)}. "
                    "The amounts do not match, so nothing is paid.")
    if not approved:
        return [], "The owner left every vendor out. Nothing is paid."
    # Second opinion: call_vars.approved() is written separately. Both must agree, or nothing is paid.
    # (It gets the amount as digits: it does not read amounts spoken in words.)
    second = call_vars.approved(decisions, {**v, "spoken_total": money(said),
                                            "excluded_vendors": ", ".join(left_out(v.get("excluded_vendors")))})
    if {d["transfer_id"] for d in second} != {d["transfer_id"] for d in approved}:
        return [], "The two approval checks disagree about what the owner approved. Nothing is paid."
    return [d["transfer_id"] for d in approved], (
        f"The owner approved {len(approved)} payment(s), {money(part)} rupees, and said the amount himself.")


# ------------------------------------------------------------------ the call


def cfg():
    need = ("SARVAM_AGENT_API_KEY", "SARVAM_ORG_ID", "SARVAM_WORKSPACE_ID", "SARVAM_APP_ID",
            "SARVAM_APP_VERSION", "SARVAM_CONNECTION_ID", "SARVAM_AGENT_PHONE", "OWNER_PHONE")
    missing = [k for k in need if not os.environ.get(k)]
    return {k: os.environ.get(k, "") for k in need}, missing


def call_request(c, variables, bid, nonce=""):
    body = {"app_config": {"app_id": c["SARVAM_APP_ID"], "app_version": int(c["SARVAM_APP_VERSION"] or 1),
                           "connection_config": {"connection_id": c["SARVAM_CONNECTION_ID"],
                                                 "agent_phone_number": c["SARVAM_AGENT_PHONE"]},
                           "agent_variables": variables},
            "user_config": {"user_phone_number": c["OWNER_PHONE"]}}
    if os.environ.get("SARVAM_CALLBACK_URL"):
        body["webhook_config"] = {"url": os.environ["SARVAM_CALLBACK_URL"], "metadata": {"batch_id": bid, "nonce": nonce}}
    return OUTBOUND.format(org=c["SARVAM_ORG_ID"], ws=c["SARVAM_WORKSPACE_ID"]), body


def place_call(c, variables, bid, nonce="", post=requests.post):
    url, body = call_request(c, variables, bid, nonce)
    try:
        r = post(url, json=body, headers={"X-API-Key": c["SARVAM_AGENT_API_KEY"]}, timeout=30)
    except requests.RequestException as e:
        sys.exit(f"Could not reach Sarvam to place the call: {type(e).__name__}. Nothing is paid.")
    if r.status_code >= 300:
        sys.exit(f"Sarvam refused the call ({r.status_code}): {r.text[:300]}. Nothing is paid.")
    try:
        return r.json()["attempt_id"]
    except (ValueError, KeyError, TypeError):
        sys.exit(f"Sarvam answered without an attempt id: {r.text[:200]}. Nothing is paid.")


def fake_answer(arg):
    """The owner's answer for the stage fallback. -> (attempt id, result).
    Takes a file path (the reliable way), real JSON, or the form PowerShell leaves behind when it
    strips the quotes: {decision:APPROVE_ALL,spoken_total:70800}."""
    text = arg
    for p in (Path(arg), HERE / arg):
        try:
            if p.is_file():
                text = p.read_text(encoding="utf-8-sig")
                break
        except (OSError, ValueError):
            pass
    try:
        v = json.loads(text)
    except ValueError:
        v = {}
        for part in re.split(r",\s*(?=[A-Za-z_]+\s*:)", text.strip().strip("{}")):
            k, colon, val = part.partition(":")
            if colon:
                v[k.strip().strip("\"'")] = val.strip().strip("\"'")
    if not isinstance(v, dict) or "decision" not in v:
        sys.exit(f"Could not read the fake answer from '{arg}'. Put it in a file, e.g. fake_answer.json: "
                 '{"decision": "APPROVE_ALL", "spoken_total": "70800"}')
    v = {k: "" if x is None else str(x) for k, x in v.items()}
    return "fake-" + uuid.uuid4().hex[:8], {"status": v.pop("status", "connected"), "variables": v, "source": "fake"}


def _attempts(c, since, get):
    return get(ATTEMPTS.format(org=c["SARVAM_ORG_ID"], ws=c["SARVAM_WORKSPACE_ID"], app=c["SARVAM_APP_ID"]),
               headers={"X-API-Key": c["SARVAM_AGENT_API_KEY"]}, timeout=20, params={
                   "start_datetime": (since - timedelta(minutes=5)).isoformat(timespec="seconds"),
                   "end_datetime": (datetime.now(IST) + timedelta(minutes=5)).isoformat(timespec="seconds"),
                   "limit": 100, "sort_by": "attempted_at", "sort_order": "desc"})


def _ended(a):
    return bool(a.get("end_datetime")) or str(a.get("connectivity_status") or "").lower() not in ("", "connected")


def _when(s):
    """Sarvam's timestamps -> aware datetime. No offset means UTC."""
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def call_id(a):
    """What identifies one call. Calls started from Sarvam's Test panel all carry the attempt id
    NO_JOB_ID (seen in real data, 21 Nov), so for those the interaction id is the unique one."""
    att = a.get("attempt_id")
    return att if att and att != "NO_JOB_ID" else (a.get("interaction_id") or att)


def latest_call(c, since, used=(), get=requests.get, wait_s=420, every_s=6, settle_s=40, sleep=time.sleep, out=print):
    """For a call started by hand from Sarvam's Test panel (calls from code have no caller number yet).
    Waits for the newest call of our agent that began after `since` and reads its result once it ends.
    `since` ties the call to this batch; `used` are calls already spent on an approval, never taken again.
    Sarvam can list one call more than once while it is still writing it, so we keep the fullest row
    and only accept a result that reads the same twice in a row. -> (call id or None, result)."""
    t0, bad, last, done_at = time.time(), 0, None, None
    while time.time() - t0 < wait_s:
        problem, code = None, None
        try:
            r = _attempts(c, since, get)
            code = r.status_code
            if code == 200:
                calls = {}
                for a in r.json().get("items") or []:
                    began, cid = _when(a.get("attempted_at") or a.get("start_datetime")), call_id(a)
                    if not began or not cid or cid in used or began < since - timedelta(seconds=90):
                        continue
                    fullness = (str(a.get("end_datetime") or ""), a.get("num_messages") or 0)
                    if cid not in calls or fullness > calls[cid][0]:
                        calls[cid] = (fullness, began, a)
                if not calls:
                    out(f"  no call started yet... {int(time.time() - t0)}s")
                    last = done_at = None
                else:
                    cid, (fullness, _, a) = max(calls.items(), key=lambda kv: kv[1][1])   # the newest call
                    v = a.get("agent_variables") or a.get("final_agent_variables") or {}
                    if not _ended(a):
                        out(f"  call in progress... {int(time.time() - t0)}s")
                        last = done_at = None
                    else:
                        snap = (cid, fullness, str(v.get("decision") or ""), str(v.get("spoken_total") or ""))
                        done_at = done_at or time.time()
                        # the decision is written a little after the call ends: give it settle_s to appear
                        if snap == last and (snap[2] or time.time() - done_at >= settle_s):
                            return cid, {"status": a.get("connectivity_status"), "source": "test panel call", "variables": v}
                        last = snap
                        out("  call ended, waiting for Sarvam to finish writing the result...")
            else:
                problem = f"Sarvam Analytics answered {code}: {(r.text or '')[:120]}"
        except (requests.RequestException, ValueError) as e:
            problem = f"Sarvam Analytics unreachable ({type(e).__name__})"
        if problem:
            bad += 1
            out(f"  {problem}  [{bad}/3]")
            if bad >= 3 or code in (401, 403):
                return None, {"status": f"could not read the call result: {problem}", "variables": {}}
        else:
            bad = 0
        sleep(every_s)
    return None, {"status": f"no finished call found after {wait_s} seconds", "variables": {}}


def read_result(c, attempt_id, started, nonce="", get=requests.get, wait_s=300, every_s=6, sleep=time.sleep, out=print):
    """Wait for the call to finish, saying what is happening every few seconds.
    Reads the callback link if there is one, else polls Sarvam Analytics. The callback is an
    unsigned webhook, so its result counts only if it carries our nonce.
    Fails fast: three bad answers in a row (or one 401/403) and it stops and says why."""
    via_callback = bool(os.environ.get("SARVAM_RESULT_URL"))
    t0, bad = time.time(), 0
    while time.time() - t0 < wait_s:
        problem, code = None, None
        try:
            if via_callback:
                r = get(os.environ["SARVAM_RESULT_URL"], params={"attempt_id": attempt_id}, timeout=20)
                code = r.status_code
                if code == 200:
                    p = r.json()
                    echoed = ((p.get("webhook_config") or {}).get("metadata") or {}).get("nonce")
                    if p.get("attempt_id") == attempt_id and nonce and echoed == nonce:
                        return {"status": p.get("status"), "variables": p.get("final_agent_variables") or {},
                                "transcript": p.get("interaction_transcript"), "source": "callback"}
                elif code != 404:  # 404 only means the call has not ended yet
                    problem = f"the callback link answered {code}"
            else:
                r = _attempts(c, started, get)
                code = r.status_code
                if code == 200:
                    for a in r.json().get("items") or []:
                        if a.get("attempt_id") == attempt_id and _ended(a):
                            return {"status": a.get("connectivity_status"), "source": "analytics",
                                    "variables": a.get("agent_variables") or a.get("final_agent_variables") or {}}
                else:
                    problem = f"Sarvam Analytics answered {code}: {(r.text or '')[:120]}"
        except (requests.RequestException, ValueError) as e:
            problem = f"{'callback link' if via_callback else 'Sarvam Analytics'} unreachable ({type(e).__name__})"
        if problem:
            bad += 1
            out(f"  {problem}  [{bad}/3]")
            if bad >= 3 or code in (401, 403):
                if via_callback:  # the callback is a convenience; Sarvam itself still has the answer
                    out("  giving up on the callback link, asking Sarvam Analytics instead")
                    via_callback, bad = False, 0
                    continue
                return {"status": f"could not read the call result: {problem}", "variables": {}}
        else:
            bad = 0
            out(f"  waiting for the call to end... {int(time.time() - t0)}s")
        sleep(every_s)
    return {"status": f"no result after {wait_s} seconds", "variables": {}}


# ------------------------------------------------------------- one-time use


def record(path, bid, attempt_id, approved, reason, result):
    """Save the approval. Returns it. Each approval has its own id and is unused."""
    rows = load(path, [])
    a = {"approval_id": "A" + uuid.uuid4().hex[:12], "batch_id": bid, "attempt_id": attempt_id,
         "approved_transfer_ids": approved, "reason": reason, "variables": result.get("variables"),
         "call_status": result.get("status"), "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "used_at": None}
    rows.append(a)
    save_ledger(path, rows)
    return a


def consume(path, approval_id, decisions):
    """Use an approval exactly once, for exactly the batch it was given for.
    -> (approved transfer ids, None) or ([], why not). Marks it used BEFORE any money moves."""
    rows = load(path, [])
    a = next((r for r in rows if r["approval_id"] == approval_id), None)
    if a is None:
        return [], "No such approval."
    if a["used_at"]:
        return [], f"This approval was already used at {a['used_at']}. One approval is good for one batch."
    if a["batch_id"] != batch_id(decisions):
        return [], "The batch has changed since the owner approved it. Call him again."
    if not a["approved_transfer_ids"]:
        return [], a["reason"]
    a["used_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    save_ledger(path, rows)
    return a["approved_transfer_ids"], None


def use_latest(decisions, here=HERE):
    """For send.py: use up the approval approve.py last wrote, for exactly this batch.
    -> (approved transfer ids, approval id), or (None, why nothing may be sent)."""
    a = load(here / "approval.json", None)
    if not a:
        return None, "There is no owner approval on file. Run approve.py first."
    ids, why = consume(here / "approvals.json", a["approval_id"], decisions)
    return (None, why) if why else (ids, a["approval_id"])


def used_attempts(path):
    return {a.get("attempt_id") for a in load(path, [])}


LATEST_NEEDS = ("SARVAM_AGENT_API_KEY", "SARVAM_ORG_ID", "SARVAM_WORKSPACE_ID", "SARVAM_APP_ID")


def main(argv):
    if "--selftest" in argv:
        return selftest()
    load_env()
    decisions = load(HERE / "decisions.json", None)
    if decisions is None:
        sys.exit("No decisions.json. Run: python check.py invoices.json")
    variables = call_variables(decisions, os.environ.get("OWNER_NAME"))
    bid = batch_id(decisions)
    c, missing = cfg()
    if "--dry-run" in argv:
        url, body = call_request({**c, "SARVAM_APP_VERSION": c["SARVAM_APP_VERSION"] or "1"}, variables, bid)
        print("batch", bid)
        print(json.dumps(variables, ensure_ascii=False, indent=2))
        print("WOULD POST", url)
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return print("missing in .env: " + ", ".join(missing) if missing else "settings complete")
    if "--fake" in argv:
        attempt_id, result = fake_answer(argv[argv.index("--fake") + 1])
    elif "--latest" in argv:
        if [k for k in LATEST_NEEDS if not c[k]]:
            sys.exit("Missing in payright/.env: " + ", ".join(k for k in LATEST_NEEDS if not c[k]))
        since = datetime.fromtimestamp((HERE / "decisions.json").stat().st_mtime, IST)
        print(f"Start the call from Sarvam's Test panel now. Waiting for a call that began after {since:%H:%M:%S}...")
        attempt_id, result = latest_call(c, since, used_attempts(HERE / "approvals.json"))
        attempt_id = attempt_id or "none"
    else:
        if missing:
            sys.exit("Missing in payright/.env: " + ", ".join(missing))
        started, nonce = datetime.now(IST), uuid.uuid4().hex
        attempt_id = place_call(c, variables, bid, nonce)
        print(f"calling {c['OWNER_PHONE'][:3]}*****{c['OWNER_PHONE'][-2:]}, attempt {attempt_id}")
        result = read_result(c, attempt_id, started, nonce)
    approved, reason = decide(result, decisions)
    a = record(HERE / "approvals.json", bid, attempt_id, approved, reason, result)
    (HERE / "approval.json").write_text(json.dumps(a, ensure_ascii=False, indent=2), encoding="utf-8")
    print(("APPROVED  " if approved else "NOT APPROVED  ") + reason)
    print(f"approval {a['approval_id']} for batch {bid}: {len(approved)} payment(s)")


def selftest():
    import tempfile
    import check
    vendors = load(HERE / "vendors.json", [])
    D = check.plan(load(HERE / "sample_invoices.json", []), vendors, [], 100000)
    pay = [d for d in D if d["status"] == "PAY"]
    doe, wells = pay[0]["transfer_id"], pay[1]["transfer_id"]
    ok = lambda **v: {"status": "connected", "variables": v}

    v = call_variables(D, "Raghu")
    assert (v["pay_count"], v["pay_total"], v["held_count"]) == ("2", "70800", "3") and "bank account changed" in v["held_list"]

    # approvals that count
    assert decide(ok(decision="APPROVE_ALL", spoken_total="70800"), D)[0] == [doe, wells]
    assert decide(ok(decision="approve_all", spoken_total="70,800 rupees"), D)[0] == [doe, wells]
    assert decide(ok(decision="APPROVE_ALL", spoken_total="seventy thousand eight hundred"), D)[0] == [doe, wells]
    assert decide(ok(decision="APPROVE_SOME", excluded_vendors="Wells Paints", spoken_total="11800"), D)[0] == [doe]
    assert decide(ok(decision="APPROVE_SOME", excluded_vendors="wells", spoken_total="11,800"), D)[0] == [doe]

    # how Sarvam and the agent write "nobody left out": none of these may block a plain approval
    for blank in ("-", " - ", "", "none", "None", "N/A", "na", "nil", "no one", "nobody"):
        assert decide(ok(decision="APPROVE_ALL", excluded_vendors=blank, spoken_total="70800"), D)[0] == [doe, wells], blank
        assert decide(ok(decision="APPROVE_SOME", excluded_vendors=blank, spoken_total="70800"), D)[0] == [], blank

    # things that must approve nothing
    nothing = [
        ok(decision="APPROVE_ALL", spoken_total="78000"),                    # wrong amount
        ok(decision="APPROVE_ALL"),                                          # a yes without the amount
        ok(decision="APPROVE_ALL", spoken_total="okay pay it"),              # not an amount
        ok(decision="REJECT", spoken_total="70800"),
        ok(decision="CALL_LATER", spoken_total="70800"),
        ok(spoken_total="70800"),                                            # no decision
        ok(decision="APPROVE_SOME", spoken_total="70800"),                   # leave out whom?
        ok(decision="APPROVE_SOME", excluded_vendors="Wells", spoken_total="70800"),         # the old total
        ok(decision="APPROVE_ALL", excluded_vendors="Doe", spoken_total="70800"),            # all, except...?
        ok(decision="APPROVE_SOME", excluded_vendors="Sharma Steel", spoken_total="70800"),  # unknown vendor
        ok(decision="APPROVE_SOME", excluded_vendors="Doe, Wells", spoken_total="70800"),    # left everyone out
        {"status": "no_answer", "variables": {"decision": "APPROVE_ALL", "spoken_total": "70800"}},
        {"status": "no result in time", "variables": {}},
    ]
    for r in nothing:
        assert decide(r, D)[0] == [], r
    # "pay the stopped one also": a STOP row is never in an approval, whatever is said
    # (a duplicate bill shares its transfer id with the original on purpose, so compare against PAY rows)
    assert set(decide(ok(decision="APPROVE_ALL", spoken_total="70800", excluded_vendors=""), D)[0]) == {doe, wells}
    hope = next(d["transfer_id"] for d in D if d["vendor_id"] == "v3")
    assert all(hope not in decide(r, D)[0] for r in (
        ok(decision="APPROVE_ALL", spoken_total="70800"), ok(decision="APPROVE_ALL", spoken_total="94400")))
    assert decide(ok(decision="APPROVE_ALL", spoken_total="94400"), D)[0] == []  # total including the stopped bill

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "approvals.json"
        res = ok(decision="APPROVE_ALL", spoken_total="70800")
        a = record(path, batch_id(D), "att-1", *decide(res, D), res)
        assert consume(path, a["approval_id"], D) == ([doe, wells], None)
        assert consume(path, a["approval_id"], D)[0] == []                   # replay refused
        b = record(path, batch_id(D), "att-2", *decide(res, D), res)
        changed = [dict(x) for x in D]
        changed[0]["amount"] += 5000                                         # batch changed after the call
        assert consume(path, b["approval_id"], changed)[0] == []
        assert consume(path, "A-not-real", D)[0] == []

    # the request we would send, and reading the result both ways
    c = {"SARVAM_AGENT_API_KEY": "k", "SARVAM_ORG_ID": "o", "SARVAM_WORKSPACE_ID": "w", "SARVAM_APP_ID": "app",
         "SARVAM_APP_VERSION": "3", "SARVAM_CONNECTION_ID": "c", "SARVAM_AGENT_PHONE": "+9180", "OWNER_PHONE": "+9199"}
    url, body = call_request(c, v, "B1")
    assert url.endswith("/orgs/o/workspaces/w/outbounds") and body["app_config"]["app_version"] == 3
    assert body["app_config"]["agent_variables"]["pay_total"] == "70800" and body["user_config"]["user_phone_number"] == "+9199"

    class R:
        status_code = 200
        def __init__(self, j): self._j = j
        def json(self): return self._j
    os.environ.pop("SARVAM_RESULT_URL", None)
    R.text = ""
    pages = [R({"items": []}), R({"items": [{"attempt_id": "att-9", "connectivity_status": "connected",
                                           "end_datetime": "2026-11-21T08:00:00",
                                           "agent_variables": {"decision": "APPROVE_ALL", "spoken_total": "70800"}}]})]
    got = read_result(c, "att-9", datetime.now(IST), get=lambda *a, **k: pages.pop(0), sleep=lambda s: None, out=lambda *a: None)
    assert got["status"] == "connected" and decide(got, D)[0] == [doe, wells]
    # callback route: a forged result without our nonce is ignored, the real one is accepted
    os.environ["SARVAM_RESULT_URL"] = "http://lambda.test"
    hook = {"attempt_id": "att-9", "status": "connected", "final_agent_variables": {"decision": "APPROVE_ALL", "spoken_total": "70800"}}
    forged = R({**hook, "webhook_config": {"metadata": {"nonce": "guess"}}})
    real = R({**hook, "webhook_config": {"metadata": {"nonce": "n-123"}}})
    q = lambda *a: None
    assert read_result(c, "att-9", datetime.now(IST), "n-123", get=lambda *a, **k: forged, wait_s=0.2, every_s=0,
                       sleep=lambda s: time.sleep(0.05), out=q)["status"].startswith("no result")
    assert read_result(c, "att-9", datetime.now(IST), "n-123", get=lambda *a, **k: real, sleep=lambda s: None, out=q)["source"] == "callback"
    # a broken callback link is dropped after three bad answers and Sarvam is asked directly
    done = {"attempt_id": "att-9", "connectivity_status": "connected", "end_datetime": "2026-11-21T08:00:00",
            "attempted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "agent_variables": {"decision": "APPROVE_ALL", "spoken_total": "70800"}}
    answers = [R({}), R({}), R({}), R({"items": [done]})]
    for a in answers[:3]:
        a.status_code, a.text = 502, "bad gateway"
    assert read_result(c, "att-9", datetime.now(IST), "n-123", get=lambda *a, **k: answers.pop(0), sleep=lambda s: None, out=q)["source"] == "analytics"
    del os.environ["SARVAM_RESULT_URL"]
    # fail fast: a 401 from Sarvam stops at once and says why; so does an unreachable network
    denied = R({})
    denied.status_code, denied.text = 401, "bad key"
    got = read_result(c, "att-9", datetime.now(IST), get=lambda *a, **k: denied, sleep=lambda s: None, out=q)
    assert "401" in got["status"] and decide(got, D)[0] == []

    def offline(*a, **k):
        raise requests.ConnectionError("down")
    tries = []
    got = read_result(c, "att-9", datetime.now(IST), get=offline, sleep=tries.append, out=q)
    assert "unreachable" in got["status"] and len(tries) == 2 and decide(got, D)[0] == []
    # the stage fallback: a file, real JSON, and what PowerShell leaves of inline JSON all work
    import tempfile as _t
    with _t.TemporaryDirectory() as d:
        f = Path(d) / "answer.json"
        f.write_text('{"decision": "APPROVE_SOME", "excluded_vendors": "Wells Paints", "spoken_total": 11800}', encoding="utf-8")
        assert decide(fake_answer(str(f))[1], D)[0] == [doe]
    assert decide(fake_answer('{"decision":"APPROVE_ALL","spoken_total":"70800"}')[1], D)[0] == [doe, wells]
    assert decide(fake_answer("{decision:APPROVE_ALL,spoken_total:70800}")[1], D)[0] == [doe, wells]
    assert decide(fake_answer("{decision:APPROVE_SOME,excluded_vendors:Wells Paints,spoken_total:11800}")[1], D)[0] == [doe]
    # a call started by hand from the Test panel: taken only if it began after the batch was made,
    # has ended, and was not already used for an approval
    now = datetime.now(IST)
    old = {**done, "attempt_id": "old", "attempted_at": (now - timedelta(minutes=30)).astimezone(timezone.utc).isoformat(timespec="seconds")}
    live = {**done, "attempt_id": "live", "end_datetime": None, "attempted_at": now.astimezone(timezone.utc).isoformat(timespec="seconds")}
    ended = {**live, "end_datetime": "2026-11-21T08:41:43"}
    pages = [R({"items": [old]}), R({"items": [live, old]}), R({"items": [ended, old]}), R({"items": [ended, old]})]
    att, got = latest_call(c, now, get=lambda *a, **k: pages.pop(0), sleep=lambda s: None, out=q)
    assert att == "live" and decide(got, D)[0] == [doe, wells] and pages == []   # accepted only once it reads the same twice
    # real Sarvam data: Test-panel calls all have attempt id NO_JOB_ID, and one call can be listed twice
    # while it is being written. The interaction id tells calls apart; the fullest row wins.
    half = {**ended, "attempt_id": "NO_JOB_ID", "interaction_id": "20261121/aaa", "num_messages": 5,
            "end_datetime": "2026-11-21T08:41:31", "agent_variables": {"decision": "", "spoken_total": ""}}
    full = {**half, "num_messages": 7, "end_datetime": "2026-11-21T08:41:43",
            "agent_variables": {"decision": "APPROVE_ALL", "excluded_vendors": "", "spoken_total": "70800"}}
    att, got = latest_call(c, now, get=lambda *a, **k: R({"items": [half, full, old]}), sleep=lambda s: None, out=q)
    assert att == "20261121/aaa" and decide(got, D)[0] == [doe, wells]
    other = {**full, "interaction_id": "20261121/bbb"}                    # a second test call is a different call
    att, got = latest_call(c, now, used={"20261121/aaa"}, get=lambda *a, **k: R({"items": [other, full]}), sleep=lambda s: None, out=q)
    assert att == "20261121/bbb"
    # the decision arrives a moment after the call ends: an empty one is not accepted straight away
    pages = [R({"items": [half]}), R({"items": [half]}), R({"items": [full]}), R({"items": [full]})]
    att, got = latest_call(c, now, get=lambda *a, **k: pages.pop(0), sleep=lambda s: None, out=q)
    assert decide(got, D)[0] == [doe, wells] and pages == []
    live = ended
    att, got = latest_call(c, now, used={"live"}, get=lambda *a, **k: R({"items": [{**live, "end_datetime": "x"}, old]}),
                           wait_s=0.2, every_s=0, sleep=lambda s: time.sleep(0.05), out=q)
    assert att is None and decide(got, D)[0] == []                       # the same call cannot approve twice
    print("selftest ok: only a connected call, an approving decision and the spoken total approve; "
          "replays, changed batches and stopped bills are refused")


if __name__ == "__main__":
    main(sys.argv)

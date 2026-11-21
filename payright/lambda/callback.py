"""Lambda <ID>-payright-callback: receives Sarvam's post-call webhook and hands it back.

  POST  (from Sarvam)       body = {attempt_id, status, final_agent_variables,
                                    interaction_transcript, webhook_config{metadata}}
  GET   ?attempt_id=...     -> that payload, or 404 while the call is still running

Put this function's call link in payright/.env as BOTH:
  SARVAM_CALLBACK_URL   (Sarvam posts the result here)
  SARVAM_RESULT_URL     (approve.py reads it back, so it no longer polls Analytics)

The webhook is not signed, so anyone with the link could post a fake "approved".
approve.py therefore puts a random nonce in webhook_config.metadata when it places the
call, Sarvam echoes it back, and approve.py ignores any result whose nonce is not its own.

Results are kept in memory and /tmp. That survives for as long as the Lambda stays warm,
which is enough for a demo. Single file, standard library only. Paste it into the console editor as lambda_function.py
(the default handler name works), or upload it as callback.py with handler callback.handler.
"""
import base64
import json
import os
import time

STORE = "/tmp/payright_attempts.json"
MEM = {}


def _load():
    if not MEM and os.path.exists(STORE):
        try:
            MEM.update(json.load(open(STORE, encoding="utf-8")))
        except (OSError, ValueError):
            pass
    return MEM


def _save():
    try:
        json.dump(MEM, open(STORE, "w", encoding="utf-8"))
    except OSError:
        pass  # memory copy still serves this warm instance


def _request(event):
    """Works for an API Gateway / Function URL event and for a direct invoke."""
    event = event or {}
    ctx = event.get("requestContext") or {}
    method = (ctx.get("http") or {}).get("method") or event.get("httpMethod") or ""
    query = event.get("queryStringParameters") or {}
    body = event.get("body")
    if body and event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8", "replace")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            body = None
    if not method:  # direct invoke: the event itself is the payload or the query
        if "final_agent_variables" in event or "status" in event:
            method, body = "POST", event
        else:
            method, query = "GET", {**query, **{k: v for k, v in event.items() if k == "attempt_id"}}
    return method.upper(), query, body


def _reply(code, obj):
    return {"statusCode": code, "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"},
            "body": json.dumps(obj, ensure_ascii=False)}


def handler(event, context=None):
    method, query, body = _request(event)
    store = _load()
    if method == "POST":
        if not isinstance(body, dict) or not body.get("attempt_id"):
            return _reply(400, {"error": "expected a JSON body with attempt_id"})
        store[str(body["attempt_id"])] = {**body, "received_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        _save()
        return _reply(200, {"ok": True})
    attempt = query.get("attempt_id")
    if attempt:
        return _reply(200, store[attempt]) if attempt in store else _reply(404, {})
    return _reply(200, {"service": "payright-callback", "stored": len(store)})  # no ids or transcripts listed


def selftest():
    import tempfile
    global STORE
    STORE = os.path.join(tempfile.mkdtemp(), "store.json")  # never the real /tmp copy
    MEM.clear()
    assert handler({"httpMethod": "GET", "queryStringParameters": {"attempt_id": "a1"}})["statusCode"] == 404
    payload = {"attempt_id": "a1", "status": "connected", "final_agent_variables": {"decision": "APPROVE_ALL"},
               "webhook_config": {"url": "x", "metadata": {"nonce": "n1"}}}
    assert handler({"requestContext": {"http": {"method": "POST"}}, "body": json.dumps(payload)})["statusCode"] == 200
    got = json.loads(handler({"httpMethod": "GET", "queryStringParameters": {"attempt_id": "a1"}})["body"])
    assert got["final_agent_variables"]["decision"] == "APPROVE_ALL" and got["webhook_config"]["metadata"]["nonce"] == "n1"
    b64 = base64.b64encode(json.dumps({**payload, "attempt_id": "a2"}).encode()).decode()
    assert handler({"httpMethod": "POST", "body": b64, "isBase64Encoded": True})["statusCode"] == 200
    assert handler({**payload, "attempt_id": "a3"})["statusCode"] == 200          # direct invoke
    assert json.loads(handler({"attempt_id": "a3"})["body"])["status"] == "connected"
    assert handler({"httpMethod": "POST", "body": "not json"})["statusCode"] == 400
    assert "a1" not in handler({"httpMethod": "GET"})["body"]
    print("selftest ok")


lambda_handler = handler  # the console default is lambda_function.lambda_handler: paste this file as is


if __name__ == "__main__":
    selftest()

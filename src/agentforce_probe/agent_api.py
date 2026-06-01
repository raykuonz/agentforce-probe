"""Headless Agent API client for InternalCopilot (employee) agents.

This is the tool's core value: Salesforce Testing Center / `sf agent test`
cannot run employee agents (they route through bypassUser:true with no Bot User
and the session never starts). The only programmatic path is the headless Agent
API with an External Client App configured for Client Credentials + a Run-As
user (bypassUser:false).

⚠️ SECURITY / TOKEN HYGIENE (this entire module exists partly to enforce it):
  * The bearer token lives ONLY in a runtime variable. It is NEVER printed, never
    logged, never written to evidence, never put in a literal "Bearer <...>"
    string, and never passed through a shell.
  * Diagnostics expose only len(token) and the dot-segment count — never bytes
    of the token itself.
  * All HTTP is done with urllib.request and req.add_header(...) using the
    runtime variable value, which sidesteps both shell-quoting and log-redaction
    traps that have burned this flow repeatedly.

Known-gotchas baked in (do not re-guess these — they are battle-tested):
  1. Mint: grant_type=client_credentials POST to {instance}/services/oauth2/token
     with client_id + client_secret. Read access_token AND api_instance_url.
  2. Token MUST be a JWT (~1700 chars, 3 dot-separated segments). An opaque
     (short) token => Agent API session endpoint 404s => ECA's
     isNamedUserJwtEnabled is off.
  3. Host = the api_instance_url from the mint response (NOT *.my.salesforce.com).
     Sandbox/scratch resolves to https://test.api.salesforce.com — that's
     correct, do not rewrite to api.salesforce.com. Never hardcode; read it
     every time.
  4. Session create: POST {api_instance_url}/einstein/ai-agent/v1/agents/
     {BotDefinitionId 0Xx...}/sessions with bypassUser:false (true => 400
     "Invalid user ID provided on start session"). Run-as user comes from the
     ECA's clientCredentialsFlowUser; do NOT pass userId in the body.
  5. Send message: POST {api_instance_url}/einstein/ai-agent/v1/sessions/
     {sessionId}/messages with {"message":{"sequenceId":N,"type":"Text",
     "text":"..."}}; sequenceId increments per turn.
  6. Error evolution (tells you which layer is OK): 404 empty body = wrong host
     or opaque token; 400 "Invalid user ID" = use bypassUser:false; 412
     "Invalid Config" = auth fully OK but planner config is broken (usually an
     action missing its inputs block).
"""

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


class AgentApiError(RuntimeError):
    def __init__(self, message, status=None, body=None):
        super().__init__(message)
        self.status = status
        self.body = body


def token_shape(token):
    """Safe diagnostic descriptor of a token — length + segment count ONLY.

    NEVER returns any substring of the token itself.
    """
    if not token:
        return {"len": 0, "segments": 0, "looks_like_jwt": False}
    segs = token.count(".") + 1
    n = len(token)
    return {"len": n, "segments": segs, "looks_like_jwt": (segs == 3 and n > 800)}


def _http(method, url, *, headers=None, data=None, timeout=60, retries=3):
    """urllib request with retry on transient network errors (EAI_AGAIN/timeout).

    Returns (status_code, body_text). Raises AgentApiError on non-transient HTTP
    errors only after capturing status + body for the caller's diagnosis.
    """
    headers = headers or {}
    body_bytes = None
    if data is not None:
        body_bytes = json.dumps(data).encode("utf-8")

    last_exc = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=body_bytes, method=method)
        for k, v in headers.items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.getcode(), resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            # HTTP-level error: capture status + body, do NOT retry 4xx (except 429).
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")
            except Exception:
                pass
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                last_exc = e
                continue
            return e.code, body
        except (TimeoutError, urllib.error.URLError, socket.gaierror) as e:
            # Transient network: EAI_AGAIN (DNS), timeouts, conn reset.
            last_exc = e
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise AgentApiError(f"network error after {retries} attempts: {e}")
    if last_exc:
        raise AgentApiError(f"request failed: {last_exc}")
    raise AgentApiError("request failed for unknown reason")


def mint_token(instance_url, consumer_key, consumer_secret, *, timeout=60):
    """Client Credentials mint. Returns dict: {token, api_instance_url, shape}.

    `instance_url` is the org's my.salesforce(.com) host used ONLY for the token
    endpoint. The Agent API host comes back as api_instance_url and MUST be used
    for all subsequent calls.
    """
    url = instance_url.rstrip("/") + "/services/oauth2/token"
    form = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": consumer_key,
            "client_secret": consumer_secret,
        }
    ).encode("utf-8")

    for attempt in range(3):
        req = urllib.request.Request(url, data=form, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
                break
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")
            except Exception:
                pass
            # Don't leak; body here is an OAuth error description, safe-ish but keep short.
            raise AgentApiError(f"mint failed (HTTP {e.code}): {body[:300]}", status=e.code)
        except (TimeoutError, urllib.error.URLError, socket.gaierror) as e:
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise AgentApiError(f"mint network error after 3 attempts: {e}")

    token = payload.get("access_token")
    api_instance_url = payload.get("api_instance_url")
    if not token:
        raise AgentApiError("mint response had no access_token")
    if not api_instance_url:
        raise AgentApiError("mint response had no api_instance_url (cannot locate Agent API host)")
    shape = token_shape(token)
    if not shape["looks_like_jwt"]:
        raise AgentApiError(
            f"minted token is OPAQUE, not a JWT (segments={shape['segments']} len={shape['len']}). Enable "
            "isNamedUserJwtEnabled on the ECA — opaque tokens make the Agent API "
            "session endpoint 404."
        )
    return {"token": token, "api_instance_url": api_instance_url.rstrip("/"), "shape": shape}


class AgentApiSession:
    """One headless Agent API session against an InternalCopilot agent."""

    def __init__(self, api_instance_url, token, bot_definition_id):
        self._api = api_instance_url.rstrip("/")
        self._token = token  # runtime-only; never logged
        self._bot = bot_definition_id
        self.session_id = None
        self._seq = 0

    def _auth_headers(self):
        # NOTE: the "Bearer " + value is built at runtime from the variable; it is
        # never a source literal and never echoed.
        return {
            "Authorization": "Bearer " + self._token,
            "Content-Type": "application/json",
        }

    def start(self, *, timeout=60):
        """Create a headless session (bypassUser:false). Returns session_id."""
        url = f"{self._api}/einstein/ai-agent/v1/agents/{self._bot}/sessions"
        body = {
            "externalSessionKey": str(uuid.uuid4()),
            "instanceConfig": {"endpoint": self._api},
            "streamingCapabilities": {"chunkTypes": ["Text"]},
            "bypassUser": False,
        }
        status, text = _http("POST", url, headers=self._auth_headers(), data=body, timeout=timeout)
        if status == 404:
            raise AgentApiError(
                "session create 404 (empty/not-found). Wrong host or opaque "
                "token. Confirm api_instance_url from mint and JWT shape.",
                status=404,
                body=text,
            )
        if status == 400 and "user id" in (text or "").lower():
            raise AgentApiError(
                "session create 400 'Invalid user ID' — set bypassUser:false and "
                "do not pass userId; run-as comes from the ECA's "
                "clientCredentialsFlowUser.",
                status=400,
                body=text,
            )
        if status == 412:
            raise AgentApiError(
                "session create 412 'Invalid Config' — auth is OK but the planner "
                "config is broken (commonly an action missing its inputs block).",
                status=412,
                body=text,
            )
        if status not in (200, 201):
            raise AgentApiError(
                "session create failed (HTTP {}): {}".format(status, (text or "")[:300]), status=status, body=text
            )
        try:
            obj = json.loads(text)
        except Exception:
            raise AgentApiError("session create returned non-JSON body", status=status)
        self.session_id = obj.get("sessionId") or obj.get("id")
        if not self.session_id:
            raise AgentApiError("session create succeeded but no sessionId in body")
        return self.session_id

    def send(self, text, *, timeout=120):
        """Send one utterance. Returns {response, invokedActions, topic, raw}."""
        if not self.session_id:
            raise AgentApiError("no active session; call start() first")
        self._seq += 1
        url = f"{self._api}/einstein/ai-agent/v1/sessions/{self.session_id}/messages"
        body = {"message": {"sequenceId": self._seq, "type": "Text", "text": text}}
        status, raw = _http("POST", url, headers=self._auth_headers(), data=body, timeout=timeout)
        if status not in (200, 201):
            raise AgentApiError(
                "send message failed (HTTP {}): {}".format(status, (raw or "")[:300]), status=status, body=raw
            )
        try:
            obj = json.loads(raw)
        except Exception:
            raise AgentApiError("send message returned non-JSON body", status=status)
        return parse_agent_response(obj)

    def close(self, *, timeout=30):
        """End the session (best-effort; ignores failures)."""
        if not self.session_id:
            return
        url = f"{self._api}/einstein/ai-agent/v1/sessions/{self.session_id}"
        try:
            _http("DELETE", url, headers=self._auth_headers(), timeout=timeout, retries=1)
        except Exception:
            pass
        self.session_id = None


def parse_agent_response(obj):
    """Extract response text + invokedActions + topic from an Agent API reply.

    messages[].message holds the text; we also pull invokedActions and topic
    where present.
    """
    messages = obj.get("messages") or obj.get("result", {}).get("messages", []) or []
    texts = []
    invoked = []
    topic = None
    for m in messages:
        if m.get("message"):
            texts.append(m["message"])
        # invoked actions can appear under a few keys depending on message type
        for k in ("invokedActions", "actions"):
            if m.get(k):
                for a in m[k]:
                    name = None
                    if isinstance(a, dict):
                        name = a.get("name") or a.get("function", {}).get("name")
                    if name:
                        invoked.append(name)
        if m.get("planId") and not topic:
            topic = m.get("topic")
        if m.get("topic") and not topic:
            topic = m.get("topic")
    return {
        "response": "\n".join(texts).strip(),
        "invokedActions": invoked,
        "topic": topic,
        "raw": obj,
    }

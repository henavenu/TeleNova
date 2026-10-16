"""
TeleNova — Nova assistant server (FastAPI, port 5002).

A standalone client of the RAI Trust platform: the graph is wrapped by the RAI Trust
SDK, every agent and tool action is evaluated by the Policy Engine, holds go to the
platform's Human Review, and the activity panel shows the platform's own audit trail.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import uuid
from pathlib import Path
from typing import Dict, List, Optional

import httpx
from dotenv import load_dotenv

_dir = Path(__file__).parent
load_dotenv(_dir / ".env")


def _require_env(name: str, why: str) -> None:
    if not os.getenv(name, "").strip():
        sys.stderr.write(f"\nFATAL [TeleNova]: required env '{name}' is not set — {why}.\n\n")
        raise SystemExit(1)


_require_env("TRUST_PE_URL", "the activity panel reads the Policy Engine audit trail")
_require_env("PAP_URL", "held actions are resolved in the platform's Human Review")

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

import graph as G
import mock_data as md
from rai_sdk_langgraph import GovernanceBlock, HITLInterrupt, instrument

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
                    handlers=[logging.StreamHandler(),
                              logging.FileHandler(_dir / "telenova.log", encoding="utf-8")])
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("telenova")

APP_ID = os.getenv("TRUST_APP_ID", "telenova")
PE_URL = os.getenv("TRUST_PE_URL", "").rstrip("/")
PAP_URL = os.getenv("PAP_URL", "").rstrip("/")

# ── RAI Trust SDK ─────────────────────────────────────────────────────────────
# pe_url / pap_url / eval & enforcement mode / timeout come from rai.env.
nova = instrument(
    G.app,
    app_id=APP_ID,
    app_key=os.getenv("RAI_APP_KEY"),
    # Account Recovery Board: each reviewer is its own A2A tool → its own agent identity.
    # The tool NAMES are what the platform's council deadlock detection keys on.
    a2a_tools={
        "transaction_monitoring_review": "fraud_reviewer",
        "revenue_review":                "retention_reviewer",
        "cx_review":                     "care_reviewer",
        "risk_review":                   "compliance_reviewer",
        "request_policy_review":         "recovery_board",
        "agent_handoff":                 "coordinator",
    },
    privacy_config={"project_names": [], "client_names": []},
)

# Beta PAP bug (register-agents): with autoflush off, a re-registration more than
# AGENT_RETIRE_GRACE_MIN (15) minutes after the last one marks EVERY agent retired, and
# the app drops out of the Agent Registry. A second registration right away revives them
# (retired rows are outside the reconcile filter). Harmless once the PAP is fixed.
try:
    nova._register_agents()
except Exception as _exc:   # noqa: BLE001 — never block startup on the workaround
    logger.warning("agent re-registration (retire workaround) failed: %s", _exc)
logger.info("TeleNova starting — LLM provider: %s", G.LLM_SELECTION)

# tool → the agent the customer sees acting (the pill chain)
_TOOL_AGENT = {
    "get_bill_summary": "Billing Agent", "issue_bill_credit": "Billing Agent",
    "refund_inactive_service": "Provisioning Agent", "add_service": "Provisioning Agent",
    "set_call_forwarding": "Provisioning Agent",
    "sim_swap": "SIM & Porting Agent", "port_out": "SIM & Porting Agent",
    "make_retention_offer": "Retention Agent",
    "agent_handoff": "Recovery Board Coordinator",
    "transaction_monitoring_review": "Fraud Reviewer", "revenue_review": "Retention Reviewer",
    "cx_review": "Customer Care Reviewer", "risk_review": "Compliance Reviewer",
    "request_policy_review": "Account Recovery Board",
}

# platform dimension → what the customer is told when it blocks
_BLOCK_COPY = {
    "sim_swap_auth": "I can't move your number to a new SIM without verifying it's really you. Verify with the "
                     "code on your current phone, or bring photo ID to any TeleNova store.",
    "port_out_velocity": "Your number has had several port-out requests today, so further port-outs are blocked "
                         "to protect it. Our fraud team has been alerted.",
    "third_party_charge_consent": "I didn't add that subscription: third-party charges need your explicit OK "
                                  "for each service. Nothing was added to your bill.",
    "credit_authority": "That credit is above what I can approve. I've passed it to a billing supervisor "
                        "instead of applying it.",
    "premium_rate_destination": "I can't forward calls to that number: it's a premium international range "
                                "used in call-forwarding fraud. Forwarding to a US number works fine.",
}
_ADVISORY_COPY = {
    "retention_offer_fairness": "Offer flagged for fairness review: it was personalised on a postcode "
                                "segment, a proxy for protected characteristics.",
}

_sessions: Dict[str, dict] = {}
_pending: Dict[str, dict] = {}       # session → held action awaiting Human Review
_resolved: Dict[str, dict] = {}      # session → outcome once Human Review decided
_lock = threading.Lock()

app = FastAPI(title="TeleNova — Nova assistant")
app.mount("/static", StaticFiles(directory=str(_dir / "ui")), name="static")
_NO_CACHE = {"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"}


class LoginRequest(BaseModel):
    username: str
    pin: str


class ChatRequest(BaseModel):
    message: str
    session_id: str


class ChatResponse(BaseModel):
    reply: str
    verdict: str = "PERMISSIVE"          # PERMISSIVE | NORMATIVE | HITL | COERCIVE
    violations: List[str] = []
    advisories: List[str] = []
    notice: Optional[str] = None
    agent_chain: List[str] = []
    hitl_pending: bool = False


def _dims(violations: List[str]) -> List[str]:
    """Violation strings → dimension ids, matched against the copy tables."""
    out = []
    for v in violations or []:
        low = str(v).lower().replace(" ", "_")
        for key in list(_BLOCK_COPY) + list(_ADVISORY_COPY) + ["account_takeover_risk", "inactive_service_billing",
                                                                "passport_oversight"]:
            if key in low and key not in out:
                out.append(key)
    return out


def _chain(messages: list) -> List[str]:
    chain: List[str] = []
    for m in messages:
        for tc in getattr(m, "tool_calls", None) or []:
            label = _TOOL_AGENT.get(tc.get("name", ""))
            if label and label not in chain:
                chain.append(label)
    return chain or ["Customer Intake"]


def _held_reply(kind: str, held: dict) -> str:
    if kind == "sim_swap":
        return ("⏳ For your protection, this SIM change needs a quick check by our fraud team — "
                + "; ".join(held.get("signals", [])[:2]) + ". I'll update you here as soon as they've reviewed it.")
    if kind == "port_out":
        return (f"⏳ {held.get('carrier')} didn't present a porting passport we recognise, so a specialist must "
                "confirm before your number leaves TeleNova. I'll update you here.")
    if kind == "refund":
        return (f"⏳ Found it: {held.get('service')} was billed for {held.get('months')} cycles after it was "
                f"deactivated on {held.get('deactivated_on')}. The ${held.get('refund_amount', 0):,.2f} refund needs a "
                "billing-desk check — you'll see it here shortly.")
    return ("⏳ I've frozen the line to protect it and opened an account-recovery case. Our Account Recovery Board "
            "couldn't agree on the next step, so a specialist is deciding now. I'll update you here.")


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return FileResponse(str(_dir / "ui" / "index.html"), headers=_NO_CACHE)


@app.get("/api/trust-links")
def trust_links():
    """Where the Trust dashboard lives (local gateway :3080, or the GCP ingress via
    TRUST_DASHBOARD_URL). The UI shows an "Open Human Review" link on held requests."""
    dash = os.getenv("TRUST_DASHBOARD_URL", "http://127.0.0.1:3080/ui/dashboard")
    return {"dashboard_url": dash, "review_url": dash + ("&" if "?" in dash else "?") + "goto=hitl"}


@app.get("/passports")
def passports_page():
    return FileResponse(str(_dir / "ui" / "passports.html"), headers=_NO_CACHE)


@app.get("/api/passports")
def list_passports():
    from passports import PASSPORTS, summary
    return {"app_id": APP_ID, "passports": summary(), "detail": PASSPORTS,
            "registry_url": os.getenv("TRUST_DASHBOARD_URL", "http://127.0.0.1:3080/ui/dashboard")}


@app.post("/api/login")
def login(req: LoginRequest):
    cred = md.CREDENTIALS.get(req.username.strip().lower())
    if not cred or cred["pin"] != req.pin:
        raise HTTPException(status_code=401, detail="Wrong username or PIN.")
    return {"session_id": f"tn-{uuid.uuid4().hex[:12]}", "customer": md.CUSTOMER}


@app.get("/api/account")
def account():
    return {"customer": md.CUSTOMER, "lines": md.LINES, "bill_total": md.bill_total(), "ledger": md.LEDGER[-8:]}


@app.post("/api/reset")
def reset():
    md.reset()
    for d in (_sessions, _pending, _resolved, G._certified, G._port_counts, G._held, G._council_cache):
        d.clear()
    return {"reset": True}


# ── Chat ──────────────────────────────────────────────────────────────────────

@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    sid = req.session_id
    prior = _sessions.get(sid, {}).get("messages", [])
    state = {"messages": prior + [HumanMessage(content=req.message)], "customer_id": md.CUSTOMER["customer_id"],
             "session_id": sid, "intent": "", "council_round": 1, "council_idx": 0}
    snapshot = list(state["messages"])
    n_before = len(_trail_events(sid))
    try:
        result = nova.invoke(state, config={"configurable": {"thread_id": sid}})
    except GovernanceBlock as exc:
        violations = list(exc.result.violations or [])
        dims = _dims(violations)
        reply = next((_BLOCK_COPY[d] for d in dims if d in _BLOCK_COPY),
                     "I can't do that — it was blocked by TeleNova's trust controls.")
        logger.warning("BLOCKED session=%s violations=%s", sid, violations)
        _sessions[sid] = {"messages": snapshot + [AIMessage(content=reply)]}
        agent = {"sim_swap_auth": "SIM & Porting Agent", "port_out_velocity": "SIM & Porting Agent",
                 "third_party_charge_consent": "Provisioning Agent", "premium_rate_destination": "Provisioning Agent",
                 "credit_authority": "Billing Agent"}.get(dims[0] if dims else "", "Nova")
        return ChatResponse(reply="⛔ " + reply, verdict="COERCIVE", violations=violations, agent_chain=[agent])
    except HITLInterrupt as exc:
        payload = dict(exc.payload or {})
        is_council = payload.get("tool") == "request_policy_review" or payload.get("agent") in ("recovery_board", "coordinator")
        held = G._held.pop(sid, {}) if not is_council else {"kind": "council"}
        kind = held.get("kind", "council")
        with _lock:
            _pending[sid] = {"kind": kind, "held": held, "state": {**state, "messages": snapshot},
                             "payload": payload, "council": G._council_cache.get(sid)}
        reply = _held_reply(kind, held)
        logger.info("HELD session=%s kind=%s reason=%s", sid, kind, payload.get("reason", "")[:120])
        _sessions[sid] = {"messages": snapshot + [AIMessage(content=reply)]}
        chain = {"sim_swap": ["SIM & Porting Agent"], "port_out": ["SIM & Porting Agent"],
                 "refund": ["Provisioning Agent"]}.get(kind, ["Account Recovery", "Fraud Reviewer", "Retention Reviewer",
                                                             "Customer Care Reviewer", "Compliance Reviewer",
                                                             "Account Recovery Board"])
        return ChatResponse(reply=reply, verdict="HITL", violations=list(payload.get("violations") or []),
                            agent_chain=chain, hitl_pending=True)

    _sessions[sid] = result
    reply = next((G._content_to_text(m.content) for m in reversed(result["messages"]) if isinstance(m, AIMessage)
                  and G._content_to_text(m.content)), "")
    # NORMATIVE advisories: read from the platform's own audit trail for this turn (the SDK's
    # advisory buffer does not carry tool-call advisories).
    advisories, verdict = [], "PERMISSIVE"
    for e in _turn_events(sid, n_before):
        if e.get("verdict") == "NORMATIVE":
            verdict = "NORMATIVE"
            for d in e.get("flagged", []):
                if d in _ADVISORY_COPY and _ADVISORY_COPY[d] not in advisories:
                    advisories.append(_ADVISORY_COPY[d])
    notice = "SIM changes need verification" if "need to confirm it's you" in reply else None
    new_msgs = result["messages"][len(snapshot):]
    return ChatResponse(reply=reply, verdict=verdict, advisories=advisories, notice=notice,
                        agent_chain=_chain(new_msgs))


# ── Human Review: the app polls the platform for the decision ─────────────────

def _pap_decision(sid: str) -> Optional[tuple]:
    try:
        r = httpx.get(f"{PAP_URL}/v1/hitl/{sid}", timeout=3.0)
        if r.status_code == 200:
            d = r.json()
            if d.get("found") and d.get("status") == "resolved" and d.get("decision"):
                return d["decision"], d.get("reviewer") or "Trust platform reviewer"
    except httpx.HTTPError as exc:
        logger.debug("PAP decision pull failed for %s: %s", sid, exc)
    return None


def _resume(sid: str, item: dict, reviewer: str) -> str:
    """Approved: re-run the held request with the reviewer's clearance recorded on the call."""
    kind = item["kind"]
    if kind == "council":
        return ("✅ A specialist reviewed your case. Your number stays frozen until you verify your identity "
                "with photo ID in any TeleNova store — then we'll restore it to a new SIM the same day, and "
                "reverse the port-out with the other carrier.")
    G._certified.setdefault(sid, {})[kind] = reviewer
    try:
        result = nova.invoke(item["state"], config={"configurable": {"thread_id": sid + "-resume"}})
        _sessions[sid] = result
        text = next((G._content_to_text(m.content) for m in reversed(result["messages"])
                     if isinstance(m, AIMessage) and G._content_to_text(m.content)), "Done.")
        return "✅ Approved by " + reviewer + ". " + text
    except GovernanceBlock as exc:
        return "⛔ Approved, but another control blocked it: " + ", ".join(exc.result.violations or [])
    except HITLInterrupt:
        return "⏳ Still under review."


@app.get("/api/hitl/status/{session_id}")
def hitl_status(session_id: str):
    if session_id in _resolved:
        return {"status": "resolved", **_resolved[session_id]}
    item = _pending.get(session_id)
    if not item:
        return {"status": "none"}
    got = _pap_decision(session_id)
    if not got:
        return {"status": "pending", "kind": item["kind"]}
    decision, reviewer = got
    with _lock:
        if session_id in _resolved:
            return {"status": "resolved", **_resolved[session_id]}
        _pending.pop(session_id, None)
        if decision == "approved":
            reply = _resume(session_id, item, reviewer)
        else:
            reply = {"sim_swap": "Your SIM change was declined after review. Please verify in store with photo ID.",
                     "port_out": "The port-out was declined after review. Your number stays with TeleNova.",
                     "refund": "The billing desk declined the refund. A specialist will call you.",
                     }.get(item["kind"], "A specialist reviewed your case and will contact you.")
            reply = "✖ " + reply
        _resolved[session_id] = {"decision": decision, "reviewer": reviewer, "reply": reply}
    return {"status": "resolved", **_resolved[session_id]}


# ── Governance trail: the Policy Engine's own audit events for this session ───

def _turn_events(sid: str, n_before: int) -> List[dict]:
    """Events recorded for this session since the turn started (oldest first)."""
    ev = _trail_events(sid)
    return ev[n_before:] if len(ev) > n_before else []


def _trail_events(session_id: str) -> List[dict]:
    return list(reversed(trail(session_id)["events"]))


@app.get("/api/trail/{session_id}")
def trail(session_id: str):
    try:
        r = httpx.get(f"{PE_URL}/v1/audit/events", params={"session_id": session_id, "limit": 40}, timeout=5.0,
                      headers={"X-RAI-App-Key": os.getenv("RAI_APP_KEY", "")} if os.getenv("RAI_APP_KEY") else None)
        events = r.json().get("events", []) if r.status_code == 200 else []
    except httpx.HTTPError:
        events = []
    out = []
    for e in reversed(events):
        md_ = e.get("metadata") or {}
        flagged = [d["dimension"] for d in e.get("dimension_results") or [] if d.get("status") != "PASS"]
        out.append({"role": e.get("role"), "verdict": e.get("verdict"), "time": e.get("timestamp"),
                    "agent": (md_.get("agent_name") or md_.get("source_agent")) if isinstance(md_, dict) else None,
                    "tool": md_.get("tool_name") if isinstance(md_, dict) else None,
                    "flagged": flagged, "latency_ms": e.get("latency_ms")})
    return {"session_id": session_id, "events": out}


if __name__ == "__main__":
    # Cloud Run sets PORT; locally run.sh uses APP_PORT / the 5002 default.
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT") or os.getenv("APP_PORT", "5002")))

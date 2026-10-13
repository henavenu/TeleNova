"""
TeleNova — Nova assistant: a multi-agent LangGraph app governed by the RAI Trust platform.

    router ─┬─ billing_agent        statements, credits
            ├─ provisioning_agent   services, refunds, call forwarding
            ├─ sim_porting_agent    SIM changes, port-outs to other carriers  (passport mode)
            ├─ retention_agent      save offers
            ├─ account_recovery ── coordinator ⇄ fraud / retention / care / compliance reviewers
            └─ fallback

Agents report the facts of an action on the tool call; the Trust platform decides.
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.types import Command

import mock_data as md
from passports import stamp_port_out
from state import CareState
from tools import (
    get_bill_summary, issue_bill_credit, refund_inactive_service, add_service, set_call_forwarding,
    sim_swap, port_out, make_retention_offer,
    transaction_monitoring_review, revenue_review, cx_review, risk_review, request_policy_review, agent_handoff,
)

logger = logging.getLogger(__name__)

# ── LLM provider selection (same chain as the platform's reference apps) ──────
_LLM_DISABLED = os.environ.get("LLM_DISABLED", "false").lower() in ("true", "1", "yes")

if _LLM_DISABLED:
    # Stub model: lets the governance pipeline run end-to-end without any LLM
    # call. It ignores bound tools (never emits tool_calls), so every node takes
    # its "model returned conversational text" path. Useful for exercising the
    # Trust Platform plumbing in CI / smoke tests without burning LLM quota.
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    class _StubChatModel(FakeListChatModel):
        """LLM_DISABLED stub — returns a canned reply and ignores tool binding."""
        def bind_tools(self, tools, **kwargs):  # FakeListChatModel has no bind_tools
            return self

    _llm = _StubChatModel(responses=[
        "[LLM disabled] Stub response — the RAI Trust governance pipeline is "
        "active, but no language model was called."
    ])
    # LLM_SELECTION: human-readable label for the active provider, logged at
    # startup by server.py (where logging is configured) so the chosen mode is
    # visible in container logs.
    LLM_SELECTION = "stub (LLM_DISABLED=true) — no external LLM calls"
    logger.warning("LLM_DISABLED=true — using stub chat model. No external LLM calls.")

elif os.getenv("GOOGLE_CLOUD_PROJECT", "").strip():
    # 1) Google Gemini on Vertex AI via the google-genai SDK (langchain_google_genai),
    # NOT langchain_google_vertexai. ChatVertexAI builds the host
    # "global-aiplatform.googleapis.com" for location=global — which does not exist
    # (→ 404 / gRPC "501 http2 status 404"). ChatGoogleGenerativeAI addresses the
    # global endpoint correctly; passing `project` auto-selects the Vertex backend
    # (ADC auth, no API key). location defaults to 'global'; set GOOGLE_CLOUD_LOCATION
    # to a region (e.g. us-central1) if the model is only served regionally for you.
    # (This matches the snippet tested against the corp GCP project.)
    from langchain_google_genai import ChatGoogleGenerativeAI
    _gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    _llm = ChatGoogleGenerativeAI(
        model=_gemini_model,
        project=os.getenv("GOOGLE_CLOUD_PROJECT"),
        location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
        temperature=1.0,
    )
    LLM_SELECTION = f"Google Gemini ({_gemini_model}) — Vertex/{os.getenv('GOOGLE_CLOUD_LOCATION', 'global')}"
    logger.info("LLM provider: %s", LLM_SELECTION)

elif os.getenv("ANTHROPIC_API_KEY", "").strip():
    # 2) Anthropic Claude via the LangChain integration (NOT the raw anthropic SDK —
    # ChatAnthropic preserves .bind_tools() / LangGraph tool-calling). Selected when
    # GOOGLE_CLOUD_PROJECT is unset — the fallback for cloud-without-Vertex and for
    # local dev. ANTHROPIC_MODEL overrides the default. NOTE: temperature is
    # deliberately NOT passed — Opus 4.8 / 4.7 reject sampling params (HTTP 400),
    # and omitting it is valid for every Claude model.
    from langchain_anthropic import ChatAnthropic
    _anthropic_model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    _llm = ChatAnthropic(
        model=_anthropic_model,
        max_tokens=int(os.getenv("ANTHROPIC_MAX_TOKENS", "4096")),
    )
    LLM_SELECTION = f"Anthropic Claude ({_anthropic_model})"
    logger.info("LLM provider: %s", LLM_SELECTION)

elif os.getenv("AZURE_OPENAI_API_KEY", "").strip():
    # 3) Azure OpenAI — for deployments that have Azure keys. Requires
    # AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_DEPLOYMENT_NAME (OPENAI_API_VERSION
    # optional). Selected when GOOGLE_CLOUD_PROJECT and ANTHROPIC_API_KEY are unset.
    from langchain_openai import AzureChatOpenAI
    _azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o")
    _llm = AzureChatOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        azure_deployment=_azure_deployment,
        api_version=os.getenv("OPENAI_API_VERSION", "2024-08-01-preview"),
        temperature=0,
    )
    LLM_SELECTION = f"Azure OpenAI ({_azure_deployment})"
    logger.info("LLM provider: %s", LLM_SELECTION)

elif os.getenv("GROQ_API_KEY", "").strip():
    # 4) Groq — fast/cheap, primarily for local dev.
    from langchain_groq import ChatGroq
    _groq_model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    _llm = ChatGroq(
        model=_groq_model,
        temperature=0,
    )
    LLM_SELECTION = f"Groq ({_groq_model}) — local"
    logger.info("LLM provider: %s", LLM_SELECTION)

else:
    # No provider configured. Fail fast with an actionable message rather than
    # silently degrading — every real deploy sets exactly one of the keys below.
    raise RuntimeError(
        "No LLM provider configured. Set one of: "
        "GOOGLE_CLOUD_PROJECT (Gemini/Vertex — cloud), "
        "ANTHROPIC_API_KEY (Claude — cloud fallback or local), "
        "AZURE_OPENAI_API_KEY (Azure — cloud), or "
        "GROQ_API_KEY (Groq — local); "
        "or set LLM_DISABLED=true for the CI stub. See .env.example."
    )



# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_last_human_text(state: CareState) -> str:
    """Extract the content of the most recent HumanMessage in the state."""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            content = msg.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                # Handle multi-modal content blocks
                parts = [
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                return " ".join(p for p in parts if p)
    return ""


def _content_to_text(content: Any) -> str:
    """Flatten an LLM message's `.content` to plain text.

    Gemini via langchain-google-genai returns content as a LIST of blocks — e.g.
    [{"type": "text", "text": "...", "extras": {"signature": "..."}}] — whereas
    Groq/Anthropic return a plain string. Calling str() on that list dumps the raw
    repr (including the thinking `signature`), which is what leaked into the UI as a
    garbled response. This extracts and joins the text blocks; thinking/signature
    blocks are dropped. Safe for str, list, or None.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") in (None, "text"):
                t = block.get("text")
                if t:
                    parts.append(t)
        return "".join(parts)
    return "" if content is None else str(content)


def _execute_tools(
    ai_msg: AIMessage,
    tool_map: Dict[str, Any],
    config: Optional[RunnableConfig] = None,
) -> List[ToolMessage]:
    """
    Execute the tool_calls present on an AIMessage.

    Passes the LangGraph RunnableConfig to each tool.invoke() call so that
    the middleware's _ToolGuardCallback fires on_tool_start for every tool
    execution — enabling Layer 2 (tool_call) governance evaluation.

    Returns a list of ToolMessages with the results, ready to append to the
    message history for the final LLM call.
    """
    results: List[ToolMessage] = []
    for call in ai_msg.tool_calls:
        tool_name = call["name"]
        tool_args = call["args"]
        tool_id = call["id"]

        if tool_name not in tool_map:
            content = f"Error: tool '{tool_name}' not found."
        else:
            try:
                raw = (
                    tool_map[tool_name].invoke(tool_args, config=config)
                    if config is not None
                    else tool_map[tool_name].invoke(tool_args)
                )
                content = json.dumps(raw) if not isinstance(raw, str) else raw
            except Exception as exc:
                # GovernanceBlock and HITLInterrupt are governance signals that
                # must propagate to the middleware — never convert them to error
                # ToolMessages.  Check by name to avoid importing SDK types here.
                if type(exc).__name__ in ("GovernanceBlock", "HITLInterrupt"):
                    raise
                content = f"Tool error: {exc}"

        results.append(
            ToolMessage(content=content, tool_call_id=tool_id, name=tool_name)
        )
    return results


def _synth_a2a_call(tool_name: str, args: dict, call_id: str) -> AIMessage:
    """
    Synthesise an AIMessage whose sole tool call is (tool_name, args).

    Used by the payment-council nodes to build each A2A delegation/vote without
    calling the LLM. The AIMessage is passed to _execute_tools, which invokes the
    tool normally and fires on_tool_start (→ A2A PE evaluation / count).
    """
    return AIMessage(content="", tool_calls=[{
        "name": tool_name,
        "args": args,
        "id":   call_id,
        "type": "tool_call",
    }])



# ── Session caches read by server.py ──────────────────────────────────────────
# session_id → reviewer who cleared a held action; on resume the stamp records it.
_certified: Dict[str, Dict[str, str]] = {}      # {session: {"sim_swap"|"port_out"|"refund": reviewer}}
# session_id → port-out requests this session (velocity fact for port_requests_24h)
_port_counts: Dict[str, int] = {}
# session_id → what a held action was, for the Human Review payload
_held: Dict[str, dict] = {}
# session_id → Account Recovery Board votes, for the Human Review payload
_council_cache: Dict[str, dict] = {}


def _session(state: CareState) -> str:
    return state.get("session_id", "") or ""


def _call(state: CareState, config: RunnableConfig, tool, args: dict) -> tuple:
    """Run one governed tool call. GovernanceBlock / HITLInterrupt propagate to server.py."""
    ai = _synth_a2a_call(tool.name, args, f"{tool.name}-{uuid.uuid4().hex[:8]}")
    results = _execute_tools(ai, {tool.name: tool}, config)
    data = {}
    try:
        data = json.loads(results[0].content)
    except (json.JSONDecodeError, IndexError, TypeError):
        pass
    return ai, results, data


def _reply(ai, results, text: str) -> Dict[str, Any]:
    return {"messages": [ai, *results, AIMessage(content=text)]}


def _amount(text: str) -> Optional[float]:
    m = re.search(r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)", text) or re.search(r"(\d[\d,]*(?:\.\d{1,2})?)\s?(?:dollars|usd)", text, re.I)
    return float(m.group(1).replace(",", "")) if m else None


def _phone(text: str) -> Optional[str]:
    """First phone number in the text, normalised to E.164 without spaces."""
    m = re.search(r"\+?\d[\d\s().-]{7,}\d", text)
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(0))
    return "+" + digits if m.group(0).strip().startswith("+") or len(digits) > 11 else "+1" + digits[-10:]


# ── Intent routing (deterministic first; the LLM only for unmatched requests) ──

_INTENTS = [
    ("account_recovery", ("didn't port", "did not port", "without my permission", "someone ported",
                          "didn't request", "did not request", "stole my number", "hijack")),
    ("retention",        ("switching to another carrier", "thinking of switching", "thinking of leaving",
                          "cancel my service", "better deal", "leave telenova")),
    ("sim_porting",      ("sim", "port my", "port the", "port number", "move my number",
                          "transfer my number", "new phone")),
    ("provisioning",     ("forward", "partner", "bundle offer", "subscription", "still charged",
                          "still being charged", "cancelled", "canceled", "deactivat", "home internet", "refund")),
    ("billing",          ("bill", "statement", "credit", "charge", "invoice", "how much do i owe")),
]
_VALID_INTENTS = {i for i, _ in _INTENTS} | {"fallback"}


def router_node(state: CareState, config: RunnableConfig) -> Dict[str, Any]:
    text = _get_last_human_text(state).lower()
    for intent, words in _INTENTS:
        if any(w in text for w in words):
            logger.info("router: intent=%s (keyword)", intent)
            return {"intent": intent}
    ask = ("Classify this telecom customer request into exactly one of: billing, provisioning, "
           "sim_porting, retention, account_recovery, fallback. Reply with the single word only.")
    try:
        out = _content_to_text(_llm.invoke([SystemMessage(content=ask), HumanMessage(content=text)],
                                           config=config).content).strip().lower()
    except Exception as exc:
        logger.warning("router: LLM classify failed (%s) → fallback", exc)
        out = "fallback"
    intent = out if out in _VALID_INTENTS else "fallback"
    logger.info("router: intent=%s (llm)", intent)
    return {"intent": intent}


def route_intent(state: CareState) -> str:
    return state.get("intent", "fallback")


# ── Billing Agent ─────────────────────────────────────────────────────────────

def billing_agent_node(state: CareState, config: RunnableConfig) -> Dict[str, Any]:
    text = _get_last_human_text(state)
    if "credit" in text.lower():
        amount = _amount(text) or 25.0
        reason = "network outage on Saturday" if "outage" in text.lower() else "goodwill credit"
        ai, res, d = _call(state, config, issue_bill_credit, {"credit_amount": amount, "reason": reason})
        return _reply(ai, res, f"Done — I've applied a ${amount:,.2f} credit for the {reason}. "
                               f"Your new balance this cycle is ${d.get('new_total', 0):,.2f}. Reference {d.get('reference_id')}.")
    ai, res, d = _call(state, config, get_bill_summary, {})
    lines = "\n".join(f"  • {l['item']}: ${l['amount']:,.2f}" for l in d.get("lines", []))
    flag = ("\n\nOne thing stands out: Home Internet is still on this bill, but our records show it was "
            "deactivated on Aug 2. Ask me to fix it and I'll start a correction."
            if any(l.get("service") == "home_internet" for l in d.get("lines", [])) else "")
    return _reply(ai, res, f"Here's your statement for {d.get('period')} (due {d.get('due')}):\n{lines}\n"
                           f"  Total: ${d.get('total', 0):,.2f}{flag}")


# ── Provisioning Agent ────────────────────────────────────────────────────────

def provisioning_agent_node(state: CareState, config: RunnableConfig) -> Dict[str, Any]:
    text = _get_last_human_text(state)
    low = text.lower()
    sid = _session(state)

    if "forward" in low:
        dest = _phone(text) or "+14045550199"
        line = md.LINES[0]["number"]
        ai, res, d = _call(state, config, set_call_forwarding, {"line": line, "forward_to": dest})
        return _reply(ai, res, f"Call forwarding is on: calls to {line} now ring {dest}. Reference {d.get('reference_id')}.")

    if any(w in low for w in ("partner", "bundle offer", "subscription")):
        offer = md.PARTNER_OFFERS[0]
        # The partner bundle enrols the customer in a third-party subscription billed through
        # TeleNova. The customer asked for "the offers", not for this specific charge.
        ai, res, d = _call(state, config, add_service, {
            "service_name": offer["service_name"], "provider": offer["provider"],
            "monthly_charge": offer["monthly"], "third_party_charge": True, "third_party_consent": False})
        return _reply(ai, res, f"Added {offer['service_name']} (${offer['monthly']:.2f}/mo).")

    # Billing for a service that was deactivated (the default provisioning request).
    svc = md.SERVICES["home_internet"]
    cleared = _certified.get(sid, {}).pop("refund", None)
    months = svc["billed_after_deactivation_months"]
    refund = round(svc["monthly"] * months, 2)
    _held[sid] = {"kind": "refund", "service": svc["name"], "refund_amount": refund, "months": months,
                  "deactivated_on": svc["deactivated_on"]}
    ai, res, d = _call(state, config, refund_inactive_service, {
        "service": "home_internet",
        "service_status": "deactivation_confirmed_by_billing_desk" if cleared else svc["status"],
        "deactivated_on": svc["deactivated_on"], "months_billed_after_deactivation": months,
        "refund_amount": refund})
    return _reply(ai, res, f"You're right — {svc['name']} was deactivated on {svc['deactivated_on']} but billed for "
                           f"{months} more cycles. I've refunded ${refund:,.2f} and removed the charge. "
                           f"New balance: ${d.get('new_total', 0):,.2f}. Reference {d.get('reference_id')}.")


# ── SIM & Porting Agent ───────────────────────────────────────────────────────

_NO_AUTH = ("can't get the code", "cant get the code", "can't receive the code", "skip the code",
            "no code", "don't have the code", "dont have the code", "without the code", "lost my phone")


def sim_porting_agent_node(state: CareState, config: RunnableConfig) -> Dict[str, Any]:
    text = _get_last_human_text(state)
    low = text.lower()
    sid = _session(state)
    line = md.find_line(text)["number"]

    if "port" in low or any(k in low for k in md.CARRIER_REGISTRY):
        carrier = md.find_carrier(text)
        cleared = _certified.get(sid, {}).pop("port_out", None)
        if not cleared:
            _port_counts[sid] = _port_counts.get(sid, 0) + 1
        stamp = stamp_port_out(carrier, certified_by=cleared)
        _held[sid] = {"kind": "port_out", "line": line, "carrier": carrier["name"], "stamp": stamp}
        ai, res, d = _call(state, config, port_out, {
            "line": line, "gaining_carrier": carrier["name"],
            "port_requests_24h": _port_counts.get(sid, 1), "passport": stamp})
        basis = (f"Their porting agent presented passport {stamp['counterparty_passport']}, which we recognise."
                 if stamp["counterparty_recognised"] else
                 f"{carrier['name']} presented no passport we recognise, so the fraud desk certified this release.")
        return _reply(ai, res, f"Port-out released: {line} → {carrier['name']}. {basis} Reference {d.get('reference_id')}.")

    # SIM change. The facts of authentication and the account's takeover signals ride on the call.
    if any(k in low for k in _NO_AUTH):
        auth_method, secure = "none", False
    elif "in store" in low or "photo id" in low:
        auth_method, secure = "in_store_id", True
    elif "email" in low or "verified" in low or "code" in low:
        auth_method, secure = "email_otp", True
    else:
        return {"messages": [AIMessage(content=(
            "Happy to help. To protect your number, I need to confirm it's you first. I've sent a code to the "
            "email on your account — tell me once you've verified, or verify with photo ID in any TeleNova store."))]}

    signals = md.takeover_signals()
    # An email OTP right after the account email changed is weak: the attacker may own the inbox.
    risk = "high" if auth_method == "email_otp" and len(signals) >= 2 else "low"
    cleared = _certified.get(sid, {}).pop("sim_swap", None)
    if cleared and risk == "high":
        risk = "cleared_by_fraud_desk"
    device = "iPhone 16 (eSIM)" if "iphone" in low else "new SIM card"
    _held[sid] = {"kind": "sim_swap", "line": line, "device": device, "auth_method": auth_method, "signals": signals}
    ai, res, d = _call(state, config, sim_swap, {
        "line": line, "target_device": device, "secure_auth": secure, "auth_method": auth_method,
        "takeover_risk": risk, "risk_signals": signals})
    return _reply(ai, res, f"Your number {line} is now active on the {device}. {d.get('notice', '')} "
                           f"Reference {d.get('reference_id')}.")


# ── Retention Agent ───────────────────────────────────────────────────────────

def retention_agent_node(state: CareState, config: RunnableConfig) -> Dict[str, Any]:
    cp = md.CHURN_PROFILE
    offer = "$20/month off for 12 months, plus a free line for 6 months"
    ai, res, d = _call(state, config, make_retention_offer, {
        "churn_score": cp["churn_score"], "offer": offer, "offer_value_usd": 300.0,
        "offer_basis": cp["segment_basis"], "segment": cp["segment"]})
    return _reply(ai, res, f"You've been with us {md.CUSTOMER['tenure_years']} years and we'd like to keep you. I can offer {offer}. "
                           f"Want me to apply it? Reference {d.get('reference_id')}.")


# ── Account Recovery Board (multi-agent council → deadlock → human) ──────────
#   node, tool, role, label, vote, view
_REVIEWERS = [
    ("fraud_reviewer", transaction_monitoring_review, "fraud", "Fraud", "UPHOLD",
     "Port-out of +14045550142 to an unrecognised carrier 40 minutes after a password reset and an email "
     "change, on a line used for banking 2FA — classic account takeover. Keep the line frozen. "
     "Vote: UPHOLD the freeze."),
    ("retention_reviewer", revenue_review, "retention", "Retention", "OVERTURN",
     "Six-year customer, three lines. Leaving them without a number while we investigate risks losing the "
     "account. Vote: OVERTURN the freeze and restore service now."),
    ("care_reviewer", cx_review, "customer_care", "Customer Care", "OVERTURN",
     "The customer has no working phone, cannot receive 2FA codes and is locked out of their bank. Restore "
     "the number to a new SIM today. Vote: OVERTURN the freeze."),
    ("compliance_reviewer", risk_review, "compliance", "Compliance", "UPHOLD",
     "Restoring the number needs secure authentication of the real subscriber and notice on every SIM change. "
     "We cannot authenticate yet. Vote: UPHOLD the freeze until identity is verified in store."),
]
_REVIEWER_NODES = [r[0] for r in _REVIEWERS]
_COUNCIL_POLL_ROUNDS = 2      # A2A = 2 rounds × 4 reviewers + 1 escalation = 9 (the platform's council cap)

_COORDINATOR_PROMPT = (
    "ACCOUNT RECOVERY REVIEW — Coordinator: after {rounds} polling rounds the Account Recovery Board is split "
    "2-2. Fraud and Compliance vote UPHOLD the freeze; Retention and Customer Care vote OVERTURN and restore "
    "service. Majority rule gives NO MAJORITY and the coordinator cannot resolve the deadlock. The subscriber "
    "is not yet authenticated. Escalate under the decision precedence (compliance and fraud prevention first, "
    "customer care second, retention third): the safe action is to UPHOLD the freeze pending verified identity."
)


def account_recovery_node(state: CareState, config: RunnableConfig):
    sid = _session(state)
    # Reset the platform's one-shot council latch so a repeat run in this session escalates again.
    try:
        import urllib.request as _ur
        _ur.urlopen(_ur.Request(f"{os.getenv('TRUST_PE_URL', 'http://127.0.0.1:3003')}/internal/a2a-reset/{sid}",
                                method="POST"), timeout=2)
    except Exception as exc:
        logger.debug("account_recovery: PE latch reset skipped: %s", exc)
    _council_cache[sid] = {
        "members": [{"role": role, "label": label, "vote": vote, "explanation": view,
                     "recommendation": "UPHOLD the freeze" if vote == "UPHOLD" else "OVERTURN — restore service"}
                    for (_n, _t, role, label, vote, view) in _REVIEWERS],
        "vote_tally": {"UPHOLD": 2, "OVERTURN": 2},
        "deliberation_rounds": _COUNCIL_POLL_ROUNDS,
    }
    for i, hp in enumerate((
        {"agent_prompt": "Customer reports a port-out they did not request. Please convene the Account Recovery Board.",
         "from_agent": "account_recovery", "to_agent": "coordinator"},
        {"agent_prompt": "Board, please assess the disputed port-out and vote on keeping or lifting the freeze.",
         "from_agent": "coordinator", "to_agent": "reviewers"},
    )):
        _execute_tools(_synth_a2a_call(agent_handoff.name, hp, f"ar-hand{i}-{sid[:8]}"),
                       {agent_handoff.name: agent_handoff}, config)
    return Command(goto="coordinator", update={"council_round": 1, "council_idx": 0})


def _make_reviewer(node: str, tool, role: str, label: str, vote: str, view: str):
    def _reviewer(state: CareState, config: RunnableConfig):
        rnd = int(state.get("council_round", 1) or 1)
        idx = int(state.get("council_idx", 0) or 0)
        prompt = f"ACCOUNT RECOVERY REVIEW — {label} (round {rnd}): {view}"
        _execute_tools(_synth_a2a_call(tool.name, {"agent_prompt": prompt, "vote": vote, "round_number": rnd},
                                       f"ar-{node}-r{rnd}-{_session(state)[:8]}"), {tool.name: tool}, config)
        return Command(goto="coordinator", update={"council_idx": idx + 1})
    return _reviewer


def coordinator_node(state: CareState, config: RunnableConfig):
    rnd = int(state.get("council_round", 1) or 1)
    idx = int(state.get("council_idx", 0) or 0)
    if rnd > _COUNCIL_POLL_ROUNDS:
        ai = _synth_a2a_call(request_policy_review.name, {
            "agent_prompt": _COORDINATOR_PROMPT.format(rounds=_COUNCIL_POLL_ROUNDS),
            "agent_role": "coordinator", "round_number": _COUNCIL_POLL_ROUNDS + 1}, f"ar-coord-{_session(state)[:8]}")
        _execute_tools(ai, {request_policy_review.name: request_policy_review}, config)   # → HITLInterrupt
        return {"messages": [AIMessage(content="The Account Recovery Board has your case; a specialist will follow up.")]}
    if idx < len(_REVIEWER_NODES):
        return Command(goto=_REVIEWER_NODES[idx])
    return Command(goto="coordinator", update={"council_round": rnd + 1, "council_idx": 0})


# ── Fallback ──────────────────────────────────────────────────────────────────

def fallback_node(state: CareState) -> Dict[str, Any]:
    return {"messages": [AIMessage(content=(
        "I can help with your bill and credits, services and call forwarding, SIM changes and moving your "
        "number to another carrier, plan offers, or a number you think was taken without your permission. "
        "What would you like to do?"))]}


# ── Graph ─────────────────────────────────────────────────────────────────────

def build_graph():
    g = StateGraph(CareState)
    g.add_node("router", router_node)
    g.add_node("billing_agent", billing_agent_node)
    g.add_node("provisioning_agent", provisioning_agent_node)
    g.add_node("sim_porting_agent", sim_porting_agent_node)
    g.add_node("retention_agent", retention_agent_node)
    g.add_node("account_recovery", account_recovery_node)
    g.add_node("coordinator", coordinator_node)
    for (node, tool, role, label, vote, view) in _REVIEWERS:
        g.add_node(node, _make_reviewer(node, tool, role, label, vote, view))
    g.add_node("fallback", fallback_node)
    g.set_entry_point("router")
    g.add_conditional_edges("router", route_intent, {
        "billing": "billing_agent", "provisioning": "provisioning_agent", "sim_porting": "sim_porting_agent",
        "retention": "retention_agent", "account_recovery": "account_recovery", "fallback": "fallback"})
    for n in ("billing_agent", "provisioning_agent", "sim_porting_agent", "retention_agent", "coordinator", "fallback"):
        g.add_edge(n, END)
    return g.compile()


app = build_graph()

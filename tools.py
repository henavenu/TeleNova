"""
TeleNova — governed tools.

Every tool call is evaluated by the Trust platform before it executes. The agents
pass the FACTS of the action as arguments (who authenticated how, how many port
requests today, whether the customer consented, where calls are forwarded); the
platform's policies decide PERMISSIVE / NORMATIVE (+ human review) / COERCIVE.
No verdict is decided in the app.
"""
from __future__ import annotations

import random
import string
from typing import List, Optional

from langchain_core.tools import tool

import mock_data as md


def _ref(prefix: str) -> str:
    return prefix + "-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


def _record(kind: str, **fields) -> dict:
    entry = {"reference_id": _ref(kind[:4].upper()), "kind": kind, **fields}
    md.LEDGER.append(entry)
    return entry


# ── Billing Agent ─────────────────────────────────────────────────────────────

@tool
def get_bill_summary() -> dict:
    """Return the current statement: period, due date, line items and total."""
    return {**md.BILL, "total": md.bill_total(), "account": md.CUSTOMER["account_number"]}


@tool
def issue_bill_credit(credit_amount: float, reason: str) -> dict:
    """Apply a goodwill or outage credit to the account.

    Args:
        credit_amount: Credit in USD.
        reason: Why the credit is being applied.
    """
    md.BILL["lines"].append({"item": f"Credit — {reason}", "amount": -round(credit_amount, 2)})
    e = _record("credit", credit_amount=credit_amount, reason=reason)
    return {"status": "APPLIED", **e, "new_total": md.bill_total()}


# ── Provisioning Agent ────────────────────────────────────────────────────────

@tool
def refund_inactive_service(service: str, service_status: str, deactivated_on: str,
                            months_billed_after_deactivation: int, refund_amount: float) -> dict:
    """Refund charges for a service that kept billing after it was deactivated.

    Args:
        service: Service id.
        service_status: Current provisioning status of the service.
        deactivated_on: Date the service was deactivated.
        months_billed_after_deactivation: Billing cycles charged after deactivation.
        refund_amount: Refund in USD.
    """
    md.BILL["lines"] = [l for l in md.BILL["lines"] if l.get("service") != service]
    md.BILL["lines"].append({"item": f"Refund — {md.SERVICES[service]['name']} billed after deactivation",
                             "amount": -round(refund_amount, 2)})
    e = _record("refund", service=service, refund_amount=refund_amount)
    return {"status": "REFUNDED", **e, "new_total": md.bill_total()}


@tool
def add_service(service_name: str, provider: str, monthly_charge: float,
                third_party_charge: bool, third_party_consent: bool) -> dict:
    """Add a service or subscription to the account bill.

    Args:
        service_name: Service to add.
        provider: Who provides and bills the service.
        monthly_charge: Monthly charge in USD.
        third_party_charge: True when a third party bills through the carrier.
        third_party_consent: True only if the customer explicitly authorised this charge.
    """
    e = _record("add_service", service_name=service_name, provider=provider, monthly_charge=monthly_charge)
    return {"status": "ADDED", **e}


@tool
def set_call_forwarding(line: str, forward_to: str) -> dict:
    """Forward all calls from a line to another number.

    Args:
        line: The line being forwarded (E.164).
        forward_to: Destination number (E.164, no spaces).
    """
    e = _record("call_forwarding", line=line, forward_to=forward_to)
    return {"status": "FORWARDING_ON", **e}


# ── SIM & Porting Agent ───────────────────────────────────────────────────────

@tool
def sim_swap(line: str, target_device: str, secure_auth: bool, auth_method: str,
             takeover_risk: str, risk_signals: List[str]) -> dict:
    """Move a line to a new SIM / eSIM (SIM change).

    Args:
        line: The line being moved (E.164).
        target_device: The device receiving the number.
        secure_auth: True only if the customer passed secure authentication for this change.
        auth_method: How the customer authenticated (none, sms_otp_old_device, email_otp, in_store_id).
        takeover_risk: low | high — account-takeover risk from the account's security signals.
        risk_signals: The signals behind takeover_risk.
    """
    e = _record("sim_swap", line=line, target_device=target_device, auth_method=auth_method)
    return {"status": "SIM_CHANGED", **e,
            "notice": f"Customer notified at the account email and on the old SIM for {line}."}


@tool
def port_out(line: str, gaining_carrier: str, port_requests_24h: int, passport: Optional[dict] = None) -> dict:
    """Release a number to another carrier (port-out).

    Args:
        line: The number being ported (E.164).
        gaining_carrier: The carrier taking the number.
        port_requests_24h: Port-out requests for this account in the last 24 hours, including this one.
        passport: Do NOT set. Stamped from the agent passport: the counterparty carrier's
            passport status and the oversight it requires.
    """
    e = _record("port_out", line=line, gaining_carrier=gaining_carrier)
    return {"status": "PORT_RELEASED", **e}


# ── Retention Agent ───────────────────────────────────────────────────────────

@tool
def make_retention_offer(churn_score: float, offer: str, offer_value_usd: float,
                         offer_basis: str, segment: str) -> dict:
    """Make a retention (save) offer to a customer at risk of leaving.

    Args:
        churn_score: Churn model probability, 0..1.
        offer: The offer text.
        offer_value_usd: Value of the offer over its term.
        offer_basis: What the offer was personalised on (usage_and_tenure, postcode_segment, …).
        segment: The segment id the offer engine used.
    """
    e = _record("retention_offer", offer=offer, offer_value_usd=offer_value_usd)
    return {"status": "OFFERED", **e}


# ── Account Recovery Board (multi-agent council) ──────────────────────────────
# Tool NAMES are fixed: the Trust platform recognises this council by them.

def _reviewer_ack(role: str, vote: str, round_number: int) -> dict:
    return {"role": role, "vote": vote, "round": round_number, "recorded": True}


@tool
def transaction_monitoring_review(agent_prompt: str, vote: str = "UPHOLD", round_number: int = 1) -> dict:
    """Fraud reviewer: weighs account-takeover signals on the disputed port-out and votes
    UPHOLD (keep the freeze) or OVERTURN (restore service). One A2A call per invocation."""
    return _reviewer_ack("fraud", vote, round_number)


@tool
def revenue_review(agent_prompt: str, vote: str = "OVERTURN", round_number: int = 1) -> dict:
    """Retention reviewer: weighs losing a long-tenure customer and votes UPHOLD or OVERTURN.
    One A2A call per invocation."""
    return _reviewer_ack("retention", vote, round_number)


@tool
def cx_review(agent_prompt: str, vote: str = "OVERTURN", round_number: int = 1) -> dict:
    """Customer Care reviewer: weighs the customer being without service and votes UPHOLD or
    OVERTURN. One A2A call per invocation."""
    return _reviewer_ack("customer_care", vote, round_number)


@tool
def risk_review(agent_prompt: str, vote: str = "UPHOLD", round_number: int = 1) -> dict:
    """Compliance reviewer: weighs SIM-swap / port-out rules (secure authentication, customer
    notice) and votes UPHOLD or OVERTURN. One A2A call per invocation."""
    return _reviewer_ack("compliance", vote, round_number)


@tool
def request_policy_review(agent_prompt: str, agent_role: str = "", round_number: int = 1) -> dict:
    """The board coordinator escalates an unresolved board decision for policy adjudication.
    One A2A call per invocation."""
    return {"role": agent_role or "coordinator", "round": round_number, "escalated": True}


@tool
def agent_handoff(agent_prompt: str, from_agent: str = "", to_agent: str = "") -> dict:
    """Hand off control and context from one agent to another. One A2A call per invocation."""
    return {"from_agent": from_agent or "agent", "to_agent": to_agent or "agent", "acknowledged": True}

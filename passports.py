"""
Agent passports for the TeleNova fleet.

Every agent has one governance record. Inside the trust domain TeleNova controls it
is held in IDENTITY mode (the agent card in the Trust registry). An agent that acts
across a boundary TeleNova does not control presents the same record in PASSPORT
mode. Here that is the SIM & Porting agent: a port-out hands a customer's number to
ANOTHER carrier, so the counterparty's porting agent must present a passport we
recognise. Recognised counterparty → the release proceeds under monitoring (HOTL);
unrecognised → the platform holds it for a human (HITL).

Risk tier follows the RAI primer: the highest of agency, impact and reach sets the
tier; each amplifier (coordination, trust-boundary exposure) that fires adds one;
swarm behaviour or a cross-jurisdiction boundary set Tier 4 on their own. Human
oversight follows agency: Instruct / Assist → HITL · Execute → HOTL · Delegate → HIC.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

# ── The primer's scales ───────────────────────────────────────────────────────

TIER_NAMES = {1: "Limited", 2: "Elevated", 3: "High", 4: "Critical"}

AGENCY = {          # level → (tier, label)
    "instruct": (1, "Instruct · no discretion"),
    "assist":   (2, "Assist · human confirms"),
    "execute":  (3, "Execute · human on call"),
    "delegate": (4, "Delegate · operates independently"),
}
OVERSIGHT_FOR_AGENCY = {"instruct": "HITL", "assist": "HITL", "execute": "HOTL", "delegate": "HIC"}
OVERSIGHT_LABEL = {
    "HITL": "Human in the loop — every consequential action is approved by a human",
    "HOTL": "Human on the loop — the agent acts; a human monitors and can intervene",
    "HIC":  "Human in command — oversight at the system level, per mandate",
}
IMPACT = {
    1: "Low impact · fully reversible",
    2: "Limited consequences · easily corrected",
    3: "Significant impact · difficult to reverse",
    4: "Severe impact · irreversible harm to rights, safety or finances",
}
REACH = {
    1: "Single isolated system or dataset",
    2: "Multiple internal systems · within one business unit",
    3: "External systems or regulated data",
    4: "Open-ended ecosystem · cross-organizational or public reach",
}
TRUST_BOUNDARY = {   # value → (amplifier yes?, sets Tier 4 alone?, label)
    "single":              (False, False, "Single trust boundary · one organization, one system"),
    "internal":            (False, False, "Inside the organization's own systems"),
    "cross-platform":      (True,  False, "Cross-platform"),
    "cross-jurisdiction":  (True,  True,  "Cross-jurisdiction"),
}
COORDINATION = {     # value → (amplifier yes?, sets Tier 4 alone?, label)
    "single":      (False, False, "Single agent · no delegation to or from other agents"),
    "sequential":  (True,  False, "Sequential workflow"),
    "supervised":  (True,  False, "Supervised orchestration"),
    "swarm":       (True,  True,  "Swarm behaviour · no central controller"),
}
# Higher tier buys a shorter leash (AGENT_PASSPORT_DESIGN.md §"Validity derived from tier").
VALIDITY_MONTHS = {4: 6, 3: 12, 2: 24, 1: 36}

ISSUED = date(2026, 10, 13)


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    return d.replace(year=d.year + y, month=m + 1)


def assign_tier(agency: str, impact: int, reach: int, coordination: str, trust_boundary: str) -> dict:
    """Primer rule: highest dimension sets the tier; each amplifier 'yes' adds one;
    swarm / cross-jurisdiction set Tier 4 alone. Returns the tier and its basis."""
    agency_tier = AGENCY[agency][0]
    dims = {"agency": agency_tier, "impact": impact, "reach": reach}
    base = max(dims.values())
    top = [k for k, v in dims.items() if v == base]
    driver = top[0] if len(top) == 1 else ", ".join(top[:-1]) + " and " + top[-1]

    c_yes, c_alone, _ = COORDINATION[coordination]
    b_yes, b_alone, _ = TRUST_BOUNDARY[trust_boundary]
    raised = []
    if c_yes:
        raised.append("coordination")
    if b_yes:
        raised.append("trust boundary")

    if c_alone or b_alone:
        tier = 4
        why = f"{'swarm behaviour' if c_alone else 'cross-jurisdiction exposure'} sets Tier 4 alone"
    else:
        tier = min(4, base + len(raised))
        why = f"{driver} {'sets' if len(top) == 1 else 'set'} Tier {base}" + (f"; +{len(raised)} for {', '.join(raised)}" if raised else "")
    return {"tier": tier, "name": TIER_NAMES[tier], "dimensions": dims, "amplifiers": raised, "basis": why}


# ── Fleet-wide facts ──────────────────────────────────────────────────────────

OWNER = "TeleNova Communications Inc."
DEPLOY = "Digital Care & Network Operations"
US_ENTITY = "TeleNova Communications Inc. — Atlanta, GA"
REAUTH = ["new tool", "new authority", "new counterparty", "new model", "tier change"]
US_LAW = ("FCC CPNI rules 47 CFR 64.2001–2011 (2023 SIM-swap / port-out amendments) · "
          "Local number portability 47 CFR 52 · FTC Act §5 (unauthorised charges) · TCPA")

_FLEET_MODEL = {
    "base_model": "Groq-hosted open-weight model (see LLM_SELECTION at startup)",
    "build": "stock instruct weights — no fine-tune; behaviour is prompt- and policy-defined",
    "weights_host": "Groq · US (us-east)",
    "runtime_params": "temperature 0 · deterministic",
}


def _us_stamp(agency: str, action: str, escalation: str) -> dict:
    return {
        "code": "US", "name": "United States", "legal_entity": US_ENTITY,
        "applicable_law": US_LAW, "authorized_action": action,
        "agency": agency, "agency_label": AGENCY[agency][1],
        "oversight": OVERSIGHT_FOR_AGENCY[agency], "escalation": escalation, "status": "active",
    }


def _passport(agent_id: str, name: str, role: str, *, agency: str, impact: int, reach: int,
              coordination: str = "single", trust_boundary: str = "internal", scope: str,
              regime: str, kill_cost: str, version: str, escalation: str = "Supervisor review on any policy hold",
              capability_ceiling: Optional[str] = None, counterparties: Optional[List[dict]] = None) -> dict:
    tier = assign_tier(agency, impact, reach, coordination, trust_boundary)
    stamps = [_us_stamp(agency, scope, escalation)]
    return {
        "agent_id": agent_id,
        "name": name,
        "role": role,
        "passport_no": f"TN-{agent_id.upper().replace('_', '-')}-{version}",
        "version": version,
        "issued": ISSUED.isoformat(),
        "valid_until": _add_months(ISSUED, VALIDITY_MONTHS[tier["tier"]]).isoformat(),
        "risk_tier": tier,
        "agency": agency,
        "agency_label": AGENCY[agency][1],
        "capability_ceiling": capability_ceiling or AGENCY[agency][1],
        "impact": impact, "impact_label": IMPACT[impact],
        "reach": reach, "reach_label": REACH[reach],
        "coordination": coordination, "coordination_label": COORDINATION[coordination][2],
        "trust_boundary": trust_boundary, "trust_boundary_label": TRUST_BOUNDARY[trust_boundary][2],
        "jurisdictions": stamps,
        "cross_jurisdiction": False,
        "record_mode": "passport" if TRUST_BOUNDARY[trust_boundary][0] else "identity",
        "counterparties": counterparties or [],
        "sovereignty": {
            "acts_in": ["US"],
            "data_residency": {"US": "US (us-east)"},
            "model_region": "US",
            "transfer_basis": {"US": "domestic deployment — no cross-border transfer"},
        },
        "ownership": {"owner_org": OWNER, "deployment_owner": DEPLOY, "legal_entities": {"US": US_ENTITY}},
        "lineage": [
            {"from": f"{OWNER} (board delegation)", "to": DEPLOY,
             "scope": "commission the digital-care agent fleet", "recorded": "2026-02-02"},
            {"from": DEPLOY, "to": name, "scope": scope, "recorded": "2026-02-16"},
        ],
        "assurance": {
            "pre_release_eval": "Scenario bench — the app's governance scenarios replayed against expected verdicts",
            "certifying_regime": regime,
            "red_team": "SIM-swap social engineering, port-out velocity, cramming and IRSF probes per release",
        },
        "reauth_triggers": REAUTH,
        "revocation": f"Trust platform → Agent registry → evict ({kill_cost})",
        "model": _FLEET_MODEL,
    }


def _counterparties() -> List[dict]:
    from mock_data import CARRIER_REGISTRY
    return [{"name": c["name"], "passport_no": c["passport_no"], "issuer": c["issuer"],
             "porting_agreement": c["porting_agreement"], "recognised": c["passport_recognised"],
             "oversight": "HOTL" if c["passport_recognised"] else "HITL"}
            for c in CARRIER_REGISTRY.values()]


_FLEET = [
    _passport("router", "Customer Intake", "Classifies each customer request and routes it to a specialist",
              agency="assist", impact=1, reach=2, coordination="sequential", version="intake-1.4",
              scope="accept and classify customer requests", regime="Internal control attestation",
              kill_cost="requests queue for a human agent"),
    _passport("billing_agent", "Billing Agent", "Explains statements; applies credits within its limit",
              agency="execute", impact=2, reach=2, version="bill-2.1",
              scope="explain statements and apply credits up to $50",
              escalation="Credits over $50 → billing supervisor",
              regime="Internal billing-accuracy audit (quarterly)",
              kill_cost="credits and bill explanations route to the billing desk"),
    _passport("provisioning_agent", "Provisioning Agent", "Adds, changes and refunds services; sets call forwarding",
              agency="execute", impact=3, reach=3, version="prov-3.0",
              scope="change services, refund billing errors, set call forwarding",
              escalation="Refunds for deactivated services → billing-correction desk",
              regime="FTC cramming controls review · internal billing-accuracy audit",
              kill_cost="service changes route to the provisioning desk"),
    _passport("sim_porting_agent", "SIM & Porting Agent", "SIM changes and port-outs to other carriers",
              agency="execute", impact=4, reach=4, trust_boundary="cross-platform", version="port-2.4",
              scope="SIM changes after secure authentication; port-outs to carriers whose passport we recognise",
              escalation="High takeover risk or unrecognised counterparty → fraud desk (human review)",
              capability_ceiling="Execute — built to move numbers between SIMs and carriers unsupervised",
              regime="FCC CPNI / LNP compliance review · independent penetration test (annual)",
              kill_cost="SIM changes and port-outs move to in-store ID verification",
              counterparties=_counterparties()),
    _passport("retention_agent", "Retention Agent", "Makes save offers to customers likely to leave",
              agency="execute", impact=2, reach=3, version="ret-1.7",
              scope="make retention offers within the approved offer catalogue",
              escalation="Offers keyed on protected or proxy attributes → fairness review",
              regime="Fairness review of the offer engine (semi-annual)",
              kill_cost="customers who want to leave are routed to the retention desk"),
    _passport("account_recovery", "Account Recovery", "Opens a recovery case when a customer reports a takeover",
              agency="assist", impact=2, reach=2, coordination="supervised", version="rec-1.2",
              scope="open an account-recovery case and convene the board",
              regime="Internal RAI review board sign-off", kill_cost="recovery cases go straight to the fraud desk"),
    _passport("coordinator", "Recovery Board Coordinator", "Runs the Account Recovery Board and escalates a deadlock",
              agency="assist", impact=2, reach=2, coordination="supervised", version="coord-1.2",
              scope="poll the board and escalate an unresolved split to a human",
              regime="Internal RAI review board sign-off", kill_cost="every recovery case escalates to a human"),
    _passport("recovery_board", "Account Recovery Board", "The board's escalation channel: hands a deadlock to a human",
              agency="assist", impact=2, reach=2, coordination="supervised", version="board-1.2",
              scope="escalate an unresolved board decision for human adjudication",
              regime="Internal RAI review board sign-off", kill_cost="recovery cases go straight to the fraud desk"),
    _passport("fraud_reviewer", "Fraud Reviewer", "Weighs account-takeover signals",
              agency="assist", impact=2, reach=3, coordination="supervised", version="frd-2.0",
              scope="assess takeover signals and vote", regime="Fraud-model validation (annual)",
              kill_cost="the fraud lens is absent from board votes"),
    _passport("retention_reviewer", "Retention Reviewer", "Weighs the cost of losing the customer",
              agency="assist", impact=2, reach=2, coordination="supervised", version="rtr-1.1",
              scope="assess retention impact and vote", regime="Internal control attestation",
              kill_cost="the retention lens is absent from board votes"),
    _passport("care_reviewer", "Customer Care Reviewer", "Weighs the customer being left without service",
              agency="assist", impact=2, reach=2, coordination="supervised", version="care-1.1",
              scope="assess service impact and vote", regime="Internal control attestation",
              kill_cost="the care lens is absent from board votes"),
    _passport("compliance_reviewer", "Compliance Reviewer", "Weighs SIM-swap / port-out rules",
              agency="assist", impact=2, reach=3, coordination="supervised", version="cmp-1.3",
              scope="assess FCC SIM-swap / port-out obligations and vote", regime="FCC CPNI compliance review",
              kill_cost="the compliance lens is absent from board votes"),
    _passport("fallback", "Help Desk", "Answers requests no specialist matches; takes no actions",
              agency="instruct", impact=1, reach=1, version="help-1.0",
              scope="answer unmatched requests without acting", regime="Internal control attestation",
              kill_cost="unmatched requests get no reply"),
]

PASSPORTS: Dict[str, dict] = {p["agent_id"]: p for p in _FLEET}


# ── Runtime: what does the passport require for THIS counterparty? ───────────

def stamp_port_out(gaining_carrier: dict, certified_by: Optional[str] = None) -> dict:
    """The passport fields stamped onto a port-out. The platform's passport_oversight
    policy holds HITL stamps for human review; HOTL and FRAUD-DESK-CERTIFIED pass."""
    p = PASSPORTS["sim_porting_agent"]
    recognised = bool(gaining_carrier.get("passport_recognised"))
    stamp = {
        "passport_no": p["passport_no"],
        "passport_tier": f"T{p['risk_tier']['tier']}",
        "counterparty": gaining_carrier.get("name"),
        "counterparty_passport": gaining_carrier.get("passport_no") or "none presented",
        "counterparty_recognised": recognised,
        "passport_oversight": "HOTL" if recognised else "HITL",
    }
    if certified_by and not recognised:
        stamp["passport_oversight"] = "FRAUD-DESK-CERTIFIED"
        stamp["passport_certified_by"] = certified_by
    return stamp


def summary() -> List[dict]:
    """Compact rows for the passport list."""
    return [{
        "agent_id": p["agent_id"], "name": p["name"], "role": p["role"],
        "passport_no": p["passport_no"], "tier": p["risk_tier"]["tier"],
        "tier_name": p["risk_tier"]["name"], "basis": p["risk_tier"]["basis"],
        "jurisdictions": [{"code": s["code"], "agency": s["agency"], "oversight": s["oversight"]}
                          for s in p["jurisdictions"]],
        "cross_jurisdiction": p["cross_jurisdiction"], "valid_until": p["valid_until"],
        "record_mode": p["record_mode"], "counterparties": len(p["counterparties"]),
    } for p in _FLEET]

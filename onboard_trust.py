"""Onboard TeleNova onto a Trust platform (local beta or GCP) — configuration only.

    venv/bin/python onboard_trust.py [--pap URL] [--pe URL] [--rotate-key]

Idempotent. Steps:
  1. Register the app (POST /v1/apps) and write the one-time credential to .env (RAI_APP_KEY).
  2. Telecom controls — declarative rules (Policy Builder), the app-only `telecom_controls`
     pack, and an app-scoped policy per rule (hitl_trigger where a person must decide).
  3. Agent-passport enforcement — reuse the platform's `passport_oversight` rule and
     `agent_passport` pack, with a TeleNova-scoped hitl_trigger policy.
  4. Assign packs, publish (Policy Engine reloads).
  5. Agent cards — the operator half of each registry card, from agent_cards.json.
     Needs the agents registered first: start the app once, then run this.

The rules read the FACTS agents put on their tool calls; the platform decides:
  score 8 → COERCIVE (blocked) · score 5 → NORMATIVE (+ human review where hitl_trigger).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import httpx
from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent
APP_ID = "telenova"
ACTOR = {"X-Actor": "telenova-onboarding"}
PACKS = ["session_guard", "prompt_filters", "agent_coordination", "telecom_controls", "agent_passport"]

APP = {
    "app_id": APP_ID, "display_name": "TeleNova", "owner": "TeleNova Communications Inc.",
    "application_domain": "tech-it", "base_tier": "HIGH", "environment": "development",
    "description": "Nova assistant for a US carrier: billing, provisioning, SIM changes, port-outs, retention, "
                   "account recovery.",
    "owner_team": "Digital Care & Network Operations",
    "intended_purpose": "Govern customer-care agents that act on accounts, numbers and bills.",
    "regulatory_regimes": ["FCC CPNI (47 CFR 64.2001-2011)", "FCC LNP (47 CFR 52)", "FTC Act s.5", "TCPA"],
    "sensitive_use": True,
}

#  dimension, display name, regex over the governed tool call, score, why, hitl_trigger
RULES = [
    ("sim_swap_auth", "SIM change without secure authentication",
     r"'secure_auth': False", 8, "SIM change requested without secure authentication (FCC 2023 SIM-swap rules)", False),
    ("account_takeover_risk", "SIM change with account-takeover signals",
     r"'takeover_risk': 'high'", 5, "SIM change with account-takeover signals: hold for the fraud desk", True),
    ("port_out_velocity", "Port-out velocity",
     r"'port_requests_24h': ([3-9]|[1-9]\d+)(?!\d)", 8, "Three or more port-out requests in 24 hours", False),
    ("third_party_charge_consent", "Third-party charge without consent",
     r"'third_party_consent': False", 8, "Third-party charge without the customer's explicit consent (cramming)", False),
    ("credit_authority", "Credit above agent authority",
     r"'credit_amount': (5[1-9]|[6-9]\d|\d{3,})(\.\d+)?(?!\d)", 8, "Bill credit above the agent's $50 authority", False),
    ("inactive_service_billing", "Billing for a deactivated service",
     r"'service_status': 'deactivated'", 5, "Refund for a service billed after deactivation: billing-desk check", True),
    ("premium_rate_destination", "Call forwarding to a premium-rate range",
     r"'forward_to': '\+88[1-3]", 8, "Forwarding to an international premium range used in revenue-share fraud", False),
    ("retention_offer_fairness", "Retention offer keyed on a proxy attribute",
     r"'offer_basis': 'postcode_segment'", 5, "Retention offer personalised on a postcode segment (proxy attribute)", False),
]

PASSPORT_RULE = {
    "dimension_id": "passport_oversight", "display_name": "Agent Passport Oversight", "category": "custom",
    "roles": ["tool_call", "agent_to_agent"],
    "rule": {
        "rule_id": "passport_oversight_v1", "dimension": "passport_oversight", "hit_policy": "F",
        "columns": [{"field": "content.text", "type": "string"}],
        "rows": [{"cells": {"content.text": {"op": "regex", "value": {
                     "pattern": r"passport_oversight\W{1,6}HITL(?![A-Za-z0-9_])", "case_sensitive": True}}},
                  "score": 5, "reason": "Agent passport stamp requires human-in-the-loop for this counterparty"}],
        "otherwise": {"score": 1, "reason": "passport oversight is not HITL"},
    },
}
PASSPORT_PACK = {"id": "agent_passport", "definition": {
    "display_name": "Agent Passport",
    "description": "Holds actions whose agent-passport stamp requires human-in-the-loop oversight",
    "layer": "domain-addon", "enforcement": "flexible", "mode": "collect-all", "combining_algorithm": "worst_case",
    "hitl_trigger": False, "owner": "platform", "version": "1.0.0", "active": True,
    "dimensions": [{"id": "passport_oversight", "profile": "standard", "severity": 2, "abort": False,
                    "roles": ["tool_call", "agent_to_agent"], "note": "score 5 = HITL stamp -> NORMATIVE"}],
    "context_adjustments": [],
}}


def _rule_body(dim, name, pattern, score, why):
    return {"dimension_id": dim, "display_name": name, "category": "custom", "roles": ["tool_call", "agent_to_agent"],
            "rule": {"rule_id": f"{dim}_v1", "dimension": dim, "hit_policy": "F",
                     "columns": [{"field": "content.text", "type": "string"}],
                     "rows": [{"cells": {"content.text": {"op": "regex", "value": {"pattern": pattern, "case_sensitive": True}}},
                               "score": score, "reason": why}],
                     "otherwise": {"score": 1, "reason": "not applicable"}}}


def _policy_body(dim, why, score, hitl):
    coercive = score >= 7
    return {"dimension": dim, "app_id": APP_ID, "severity": 3 if coercive else 2,
            "thresholds": {"permissive": [1, 3], "normative": [4, 6] if coercive else [4, 9],
                           "coercive": [7, 9] if coercive else [10, 10]},
            "remediation_normative": why, "remediation_coercive": why if coercive else None,
            "policy_code": "TN-" + dim.upper()[:17], "normative_action": "HITL" if hitl else "REVISION",
            "normative_guidance": why, "human_note": why, "ops_alert": coercive,
            "hitl_trigger": hitl, "incident_routing": "platform_dashboard"}


TELECOM_PACK = {"id": "telecom_controls", "definition": {
    "display_name": "Telecom Controls",
    "description": "SIM-swap, port-out, cramming, billing-accuracy, IRSF and retention-fairness controls",
    "layer": "domain-addon", "enforcement": "flexible", "mode": "collect-all", "combining_algorithm": "worst_case",
    "hitl_trigger": False, "owner": APP_ID, "version": "1.0.0", "active": True,
    "dimensions": [{"id": d, "profile": "standard", "severity": 3 if s >= 7 else 2, "abort": False,
                    "roles": ["tool_call", "agent_to_agent"], "note": n} for (d, n, _p, s, _w, _h) in RULES],
    "context_adjustments": [],
}}


def _retry_insert(fn, tries: int = 25):
    """Beta's seeded Postgres sequences can lag the seeded rows, so a first insert may
    collide (500). Each failed insert advances the sequence; retry until it lands."""
    r = fn()
    for _ in range(tries):
        if r.status_code < 500:
            return r
        r = fn()
    return r


def _save_key(key: str) -> None:
    env = HERE / ".env"
    text = env.read_text() if env.exists() else ""
    line = f"RAI_APP_KEY={key}"
    text = re.sub(r"(?m)^RAI_APP_KEY=.*$", line, text) if re.search(r"(?m)^RAI_APP_KEY=", text) else text + f"\n{line}\n"
    env.write_text(text)
    env.chmod(0o600)


def _upsert_policy(pap, body) -> int:
    r = _retry_insert(lambda: pap.post("/v1/policies", json=body, headers=ACTOR))
    if r.status_code == 409:
        r = pap.put(f"/v1/policies/{body['dimension']}?app_id={APP_ID}",
                    json={k: v for k, v in body.items() if k not in ("dimension", "app_id")}, headers=ACTOR)
    return r.status_code


def _ensure_pack(pe, spec) -> str:
    packs = pe.get("/internal/packs").json()
    items = packs.get("packs", packs) if isinstance(packs, dict) else packs
    ids = {p.get("id") or p.get("pack_id") for p in items} if isinstance(items, list) else set(items or [])
    if spec["id"] in ids:
        return "exists"
    r = _retry_insert(lambda: pe.post("/internal/packs", json=spec))
    return "created" if r.status_code < 300 else f"HTTP {r.status_code} {r.text[:160]}"


def main() -> int:
    cfg = dotenv_values(HERE / "rai.env") if (HERE / "rai.env").exists() else {}
    ap = argparse.ArgumentParser()
    ap.add_argument("--pap", default=(cfg.get("RAI_PAP_URL") or "http://127.0.0.1:3002").split("#")[0].strip())
    ap.add_argument("--pe", default=(cfg.get("RAI_PE_URL") or "http://127.0.0.1:3003").split("#")[0].strip())
    ap.add_argument("--rotate-key", action="store_true")
    a = ap.parse_args()
    pap, pe = httpx.Client(base_url=a.pap, timeout=30), httpx.Client(base_url=a.pe, timeout=30)
    print(f"Trust platform: PAP={a.pap}  PE={a.pe}")
    ok_all = True

    # 1. app + credential
    cred = None
    if pap.get(f"/v1/apps/{APP_ID}").status_code != 200:
        r = _retry_insert(lambda: pap.post("/v1/apps", json=APP, headers=ACTOR))
        if r.status_code == 201:
            cred = r.json().get("credential")
        elif r.status_code != 409:
            print(f"  ✗ register app: HTTP {r.status_code} {r.text[:200]}"); return 1
        print("  ✓ app registered")
    else:
        print("  · app already registered")
    env_text = (HERE / ".env").read_text() if (HERE / ".env").exists() else ""
    if cred is None and (a.rotate_key or not re.search(r"(?m)^RAI_APP_KEY=.+", env_text)):
        r = _retry_insert(lambda: pap.post(f"/v1/apps/{APP_ID}/credentials", headers=ACTOR))
        if r.status_code != 201:
            print(f"  ✗ issue credential: HTTP {r.status_code} {r.text[:200]}"); return 1
        cred = r.json()
    if cred:
        _save_key(f"{cred['key_id']}.{cred['app_secret']}")
        print("  ✓ app credential written to .env (RAI_APP_KEY)")
    else:
        print("  · keeping existing RAI_APP_KEY in .env")

    # 2. telecom rules → pack → policies
    for (dim, name, pattern, score, why, hitl) in RULES:
        r = pap.post("/v1/policy-builder/evaluation", json=_rule_body(dim, name, pattern, score, why), headers=ACTOR)
        good = r.status_code in (200, 201)
        ok_all &= good
        print(f"  {'✓' if good else '✗'} rule {dim} ({'COERCIVE' if score >= 7 else 'NORMATIVE'}"
              f"{' + human review' if hitl else ''})" + ("" if good else f": HTTP {r.status_code} {r.text[:120]}"))
    print(f"  · telecom_controls pack: {_ensure_pack(pe, TELECOM_PACK)}")
    for (dim, _n, _p, score, why, hitl) in RULES:
        code = _upsert_policy(pap, _policy_body(dim, why, score, hitl))
        ok_all &= code < 300
        if code >= 300:
            print(f"  ✗ policy {dim}: HTTP {code}")
    print("  ✓ telecom policies (app-scoped)")

    # 3. passport enforcement (shared rule + pack, TeleNova policy)
    r = pap.post("/v1/policy-builder/evaluation", json=PASSPORT_RULE, headers=ACTOR)
    print(f"  {'✓' if r.status_code in (200, 201) else '✗'} passport_oversight rule")
    print(f"  · agent_passport pack: {_ensure_pack(pe, PASSPORT_PACK)}")
    code = _upsert_policy(pap, _policy_body("passport_oversight",
                                            "Port-out to a carrier whose porting passport we do not recognise: "
                                            "hold for the fraud desk.", 5, True))
    print(f"  {'✓' if code < 300 else '✗'} passport_oversight policy (hitl_trigger)")

    # 4. assign + publish
    for pk in PACKS:
        r = _retry_insert(lambda: pe.post(f"/internal/app-stacks/{APP_ID}/packs/{pk}", json={"active": True}))
        ok_all &= r.status_code < 300
        print(f"  {'✓' if r.status_code < 300 else '✗'} pack {pk}")
    r = pap.post("/v1/policies/publish", json={"notes": "telenova onboarding"}, headers=ACTOR)
    pub = r.status_code < 300 and r.json().get("success")
    print(f"  {'✓' if pub else '✗'} published (PE reload: {(r.json().get('reload') or {}).get('status') if pub else r.status_code})")

    # 5. agent cards
    cards = json.loads((HERE / "agent_cards.json").read_text())
    done = 0
    for agent_id, c in cards.items():
        meta = {k: v for k, v in c.items() if k not in ("kill_switch", "hitl_mode")}
        try:
            rm = _retry_insert(lambda: pap.patch(f"/v1/agent-cards/{APP_ID}/{agent_id}/metadata", json=meta, headers=ACTOR), tries=3)
            rf = pap.patch(f"/v1/agent-cards/{APP_ID}/{agent_id}", headers=ACTOR,
                           json={"kill_switch": c.get("kill_switch"), "hitl_mode": c.get("hitl_mode")})
        except httpx.HTTPError as exc:
            print(f"  ✗ card {agent_id}: {type(exc).__name__} — PAP rejected the update"); continue
        if rm.status_code < 300 and rf.status_code < 300:
            done += 1
        else:
            print(f"  ✗ card {agent_id}: metadata HTTP {rm.status_code}, flags HTTP {rf.status_code}")
    print(f"  {'✓' if done == len(cards) else '✗'} agent cards: {done}/{len(cards)}"
          + ("" if done else " (start the app first so the SDK registers its agents)"))
    return 0 if ok_all and pub and done == len(cards) else 1


if __name__ == "__main__":
    sys.exit(main())

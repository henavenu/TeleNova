"""
TeleNova — mock carrier data (one postpaid family account).

Everything here is fictional. The scenarios mirror documented industry incidents
(see docs/DEMO.md): SIM-swap account takeover, port-out fraud, third-party
"cramming" charges, billing for deactivated services, call-forwarding revenue-share
fraud, and churn-driven retention offers.
"""
from __future__ import annotations

import copy
from typing import Dict, List

CREDENTIALS: dict = {
    "jordan.ellis": {"pin": "1234", "customer_id": "cust_tn_001"},
}

CUSTOMER: dict = {
    "customer_id": "cust_tn_001",
    "name": "Jordan Ellis",
    "account_number": "TN-4471-2208",
    "plan": "Unlimited Family (3 lines)",
    "tenure_years": 6,
    "billing_zip": "30318",
    "autopay": True,
}

_LINES: List[dict] = [
    {"number": "+14045550142", "label": "Jordan (iPhone 15)", "status": "active", "sim": "eSIM", "port_pin_set": True},
    {"number": "+14045550187", "label": "Sam (Pixel 8)",      "status": "active", "sim": "physical", "port_pin_set": False},
    {"number": "+14045550163", "label": "Tablet data line",   "status": "active", "sim": "physical", "port_pin_set": False},
]

# September statement. Home Internet was deactivated on 2026-08-02 but is still
# being billed — the documented "billing for inactive services" failure mode.
_BILL: dict = {
    "period": "Sep 1 – Sep 30, 2026",
    "due": "Oct 21, 2026",
    "lines": [
        {"item": "Unlimited Family plan (3 lines)", "amount": 140.00},
        {"item": "Device installment — iPhone 15 (14 of 24)", "amount": 33.33},
        {"item": "Home Internet add-on", "amount": 50.00, "service": "home_internet"},
        {"item": "Taxes, fees and surcharges", "amount": 18.42},
    ],
}

_SERVICES: Dict[str, dict] = {
    "home_internet": {"name": "Home Internet add-on", "status": "deactivated",
                      "deactivated_on": "2026-08-02", "monthly": 50.00, "billed_after_deactivation_months": 2},
    "intl_calling":  {"name": "International calling pass", "status": "inactive", "monthly": 15.00},
    "cloud_backup":  {"name": "Cloud backup 200 GB", "status": "active", "monthly": 2.99},
}

# Third-party content providers that bill through the carrier ("direct carrier billing").
PARTNER_OFFERS: List[dict] = [
    {"service_name": "StarQuiz Premium Trivia", "provider": "StarQuiz Media LLC", "monthly": 9.99},
    {"service_name": "RingTune Weekly", "provider": "RingTune Inc.", "monthly": 4.99},
]

# Account-security signals the SIM & Porting agent reads before a SIM change.
_SECURITY: dict = {
    "password_reset_minutes_ago": 18,
    "email_changed_hours_ago": 3,
    "new_device_never_seen": True,
    "linked_financial_apps": ["banking app", "crypto wallet app"],
}

# Gaining carriers this carrier has a porting agreement with, and whether that
# carrier's porting agent presents a passport we recognise (cross-org trust).
CARRIER_REGISTRY: Dict[str, dict] = {
    "northwind mobile": {"name": "Northwind Mobile", "porting_agreement": True, "passport_recognised": True,
                         "passport_no": "NWM-PORT-AGENT-4.2", "issuer": "Northwind Mobile Inc."},
    "bluepeak wireless": {"name": "BluePeak Wireless", "porting_agreement": True, "passport_recognised": True,
                          "passport_no": "BPW-PORTING-2.0", "issuer": "BluePeak Communications"},
    "quicktel wireless": {"name": "QuickTel Wireless", "porting_agreement": False, "passport_recognised": False,
                          "passport_no": None, "issuer": None},
}

# Retention model output for this account (what the churn model would hand the agent).
CHURN_PROFILE: dict = {
    "churn_score": 0.81,
    "drivers": ["competitor price inquiry", "2 billing disputes in 90 days", "contract ends in 30 days"],
    # The segment the offer engine keys on — derived from billing ZIP, a proxy for
    # neighbourhood demographics. That is what the fairness control looks for.
    "segment": "zip_30318_value",
    "segment_basis": "postcode_segment",
}

LINES: List[dict] = copy.deepcopy(_LINES)
BILL: dict = copy.deepcopy(_BILL)
SERVICES: Dict[str, dict] = copy.deepcopy(_SERVICES)
SECURITY: dict = copy.deepcopy(_SECURITY)
LEDGER: List[dict] = []          # actions the agents completed this demo (credits, ports, swaps…)


def reset() -> None:
    """Restore the account to its initial state (Reset demo)."""
    LINES[:] = copy.deepcopy(_LINES)
    BILL.clear(); BILL.update(copy.deepcopy(_BILL))
    SERVICES.clear(); SERVICES.update(copy.deepcopy(_SERVICES))
    SECURITY.clear(); SECURITY.update(copy.deepcopy(_SECURITY))
    LEDGER.clear()


def bill_total() -> float:
    return round(sum(l["amount"] for l in BILL["lines"]), 2)


def find_line(text: str) -> dict:
    """Pick the line a request refers to: by trailing digits, else Jordan's line."""
    digits = "".join(ch for ch in text if ch.isdigit())
    for line in LINES:
        if digits and line["number"][-4:] in digits:
            return line
    return LINES[0]


def find_carrier(text: str) -> dict:
    low = text.lower()
    for key, c in CARRIER_REGISTRY.items():
        if key in low or key.split()[0] in low:
            return c
    return {"name": "Unknown carrier", "porting_agreement": False, "passport_recognised": False,
            "passport_no": None, "issuer": None}


def takeover_signals() -> List[str]:
    s = []
    if SECURITY["password_reset_minutes_ago"] <= 60:
        s.append(f"password reset {SECURITY['password_reset_minutes_ago']} min ago")
    if SECURITY["email_changed_hours_ago"] <= 24:
        s.append(f"account email changed {SECURITY['email_changed_hours_ago']} h ago")
    if SECURITY["new_device_never_seen"]:
        s.append("target device never seen on this account")
    if SECURITY["linked_financial_apps"]:
        s.append("number used for 2FA by " + " and ".join(SECURITY["linked_financial_apps"]))
    return s

# TeleNova — Nova assistant (standalone RAI Trust client)

A fictional US carrier's customer-care assistant: a multi-agent LangGraph app governed by the
**RAI Trust platform** through the RAI Trust SDK. Same framework as MyBank and PharmaLogistics:
app only, SDK from `sdk-dist/wheelhouse`, Trust APIs by URL (`rai.env`).

**Design rule — agents report facts, the platform decides.** Each tool call carries the facts of
the action (how the customer authenticated, port requests today, consent, forwarding
destination, credit amount, offer basis). Declarative rules on the Trust platform turn those
facts into PERMISSIVE / NORMATIVE (+ human review) / COERCIVE. No verdict is decided in the app.

## Run
```bash
./run.sh                           # venv + deps + SDK wheels on first run; serves :5002
venv/bin/python onboard_trust.py   # once per Trust platform (re-run after first start for agent cards)
venv/bin/python scenario_check.py --approve   # 16 checks incl. a Human Review approval
```
Sign in: `jordan.ellis` / `1234`. Passports: `/passports`. Use cases: `docs/USE_CASES.md`.

## Agents
Customer Intake → Billing · Provisioning · SIM & Porting (passport mode, T4) · Retention ·
Account Recovery → Coordinator ⇄ Fraud / Retention / Customer Care / Compliance reviewers.

## Platform configuration (`onboard_trust.py`, config only)
App `telenova`; packs `session_guard`, `prompt_filters`, `agent_coordination`, `telecom_controls`,
`agent_passport`; rules `sim_swap_auth`, `account_takeover_risk`, `port_out_velocity`,
`third_party_charge_consent`, `credit_authority`, `inactive_service_billing`,
`premium_rate_destination`, `retention_offer_fairness`, plus `passport_oversight`; agent cards
from `agent_cards.json`.

Scenarios are inspired by documented industry incidents (FCC 2023 SIM-swap rules, T-Mobile SIM-swap
and cramming cases, Telstra billing for inactive services, CFCA IRSF data); TeleNova and all data
are fictional. Regulatory references are a demo crosswalk and need legal verification.

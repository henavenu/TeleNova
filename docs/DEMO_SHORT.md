# TeleNova demo — short script (~8 min)

Tabs: Nova http://127.0.0.1:5002 · passports http://127.0.0.1:5002/passports · dashboard http://127.0.0.1:3080/ui/dashboard
Before: **Reset demo** (under the Try Nova chips). Watch the verdict chip under each reply and the **Trust activity** panel.

> **Human Review:** use the **Open Human Review ↗** link next to "Waiting for a TeleNova specialist". Locally that's the :3080 dashboard (started by `./run.sh`). **Never use :3004:** its Human Review looks empty.

| # | Click (Try Nova chip) | Expect | Say |
|---|---|---|---|
| 1 | **Explain my bill** | PASS; Nova flags Home Internet still billed | "Everyday care runs freely, and every action is still evaluated." |
| 2 | **$25 outage credit** → **$400 credit** | PASS → BLOCK | "The Billing Agent's $50 authority lives on the platform, not in its prompt." |
| 3 | **Still charged for Home Internet** | REVIEW | "Billed after deactivation, the Telstra pattern. The refund waits for a billing check." |
| 4 | **Open Human Review ↗** → **Approve**, back to Nova | "Approved… refunded $100" | "A person approved it, and the trail records who." |
| 5 | **Apply partner offers** | BLOCK | "Third-party charges need explicit consent: the cramming case behind T-Mobile's $90M settlement." |
| 6 | **Forward calls to +882…** | BLOCK | "Premium-rate range used in revenue-share fraud. US numbers forward fine." |
| 7 | **Move my number to a new SIM** | amber *SIM changes need verification* | "Exactly the promise on the homepage." |
| 8 | **Lost phone, no code** | BLOCK | "No secure authentication, no SIM change (FCC 2023 rules)." |
| 9 | **Verified by email — new iPhone** → Human Review → **Approve** | REVIEW → "now active… customer notified" | "Code is fine, but the password was reset 18 min ago and the email changed today: takeover signals go to the fraud desk." |
| 10 | **Reset demo**, then **Port to Northwind** ×3 | PASS, PASS, BLOCK | "Port-out velocity: the agent reports the count, the platform decides." |
| 11 | **Port to QuickTel** | REVIEW | "Cross-organisation: Northwind's porting agent presented a passport we recognise; QuickTel's didn't." Show `/passports` → SIM & Porting Agent → *Counterparty passports*. |
| 12 | **Thinking of switching** | WARN + ⚠ fairness note | "The offer still goes out, but it was keyed on postcode, a proxy attribute, so compliance is told." |
| 13 | **My number was ported without me** | HITL, five agent pills | "Fraud and Compliance want the freeze; Retention and Care want service back. 2–2 deadlock, so the platform escalates to a person." |
| 14 | Dashboard → **Agent Registry** → *telenova* | 13 cards | "Every agent has a card. The one that crosses into other carriers also carries a passport." |

**If something misbehaves:** a hold not appearing in Human Review → Reset demo (one item per session). Rules missing → `venv/bin/python onboard_trust.py`.

# TeleNova — use cases, scenario by scenario

App: http://127.0.0.1:5002 (Sign in → jordan.ellis / 1234). Prompts are the **Try Nova** chips.
Watch the verdict chip under each reply and the **Trust activity** panel (the platform's own audit trail).
Human Review: http://127.0.0.1:3080/ui/dashboard → Human Review. Click **Reset demo** before you start.

---

## 1. Credit within authority
**Description.** Nova applies a small outage credit on its own, but a large one is refused because it is beyond the Billing Agent's authority. The limit lives on the platform, not in the agent's prompt.
**Business proof.** Agents can resolve routine billing on first contact without creating an uncontrolled refund channel.
**Governance demoed.** Authority envelope (credit ≤ $50) · tool-level policy evaluated before execution · hard block (BLOCK).
**Steps.**
1. Chip **$25 outage credit** → credit applied, chip shows PASS.
2. Chip **$400 credit** → "That credit is above what I can approve…", chip BLOCK.
3. Trust activity shows `issue_bill_credit` flagged `credit_authority`.

## 2. Billing for a deactivated service
**Description.** The customer is still billed for Home Internet two months after it was deactivated. Nova finds the error and proposes a $100 refund, which the platform routes to the billing desk before money moves. Mirrors Telstra's ~$24M refunds for billing inactive services.
**Business proof.** Billing errors are caught and corrected in the conversation, with a human check on refunds, so fixes are fast but audited.
**Governance demoed.** Policy-triggered human-in-the-loop · hold → Human Review → resume · audit trail of the correction.
**Steps.**
1. Chip **Explain my bill** → Nova flags Home Internet still billed (PASS).
2. Chip **Still charged for Home Internet** → reply "needs a billing-desk check", chip REVIEW.
3. Dashboard → Human Review → **Approve**.
4. Back in Nova (~5 s) → "Approved… refunded $100.00".

## 3. Third-party charges need consent (cramming)
**Description.** Asked to "apply the partner offers", the Provisioning Agent tries to add a third-party trivia subscription billed through TeleNova. The platform blocks it because the customer never consented to that specific charge. Mirrors T-Mobile's $90M FCC cramming settlement.
**Business proof.** Delivers the brand promise "add-ons only with your OK"; removes a major source of complaints and regulatory exposure.
**Governance demoed.** Consent as a policy fact · BLOCK block on the agent's own action (not the user's words).
**Steps.**
1. Chip **Apply partner offers** → "I didn't add that subscription…", chip BLOCK.
2. Point at the Trust activity row: `add_service` flagged `third_party_charge_consent`.

## 4. Call-forwarding fraud (IRSF)
**Description.** A request to forward calls to a +882 number is blocked: that is an international premium range used in revenue-share fraud. Forwarding to a normal US number works. IRSF is among the top five telecom fraud types (CFCA, ~$39.9B industry losses in 2021).
**Business proof.** Fraud losses are prevented at the moment of the action, without blocking legitimate customers.
**Governance demoed.** Destination screening policy on tool arguments · precise block (one destination class, not the feature).
**Steps.**
1. Chip **Forward calls to +882…** → blocked, BLOCK.
2. Type **Forward my calls to 404-555-0199** → forwarding on, PASS.

## 5. SIM change: verification and takeover signals
**Description.** Moving a number to a new SIM needs secure authentication. Without it the change is blocked. With an email code that looks fine on its own, the platform still holds it because the account shows takeover signals (password reset 18 min ago, email changed today, number used for banking 2FA). Mirrors the FCC's 2023 SIM-swap rules and T-Mobile's $33M SIM-swap award.
**Business proof.** Stops the most damaging telecom fraud (SIM-swap account takeover) while keeping a fast path for genuine customers.
**Governance demoed.** Two policies on one action: hard block on missing authentication, HITL on risk · fraud-desk review · resume with clearance recorded.
**Steps.**
1. Chip **Move my number to a new SIM** → "I've sent a code to the email on your account" + amber *SIM changes need verification* (matches the site).
2. Chip **Lost phone, no code** → blocked, BLOCK.
3. Chip **Verified by email — new iPhone** → held for the fraud team, HITL.
4. Human Review → **Approve** → Nova: "Approved by … now active on the iPhone 16 (eSIM). Customer notified…".

## 6. Port-out velocity
**Description.** The first two port-out requests to Northwind Mobile go through; the third in 24 hours is blocked as a port-out fraud pattern. The agent reports the count; the platform decides.
**Business proof.** Pattern-based fraud is caught across requests, not just within one.
**Governance demoed.** Cross-request (velocity) control · facts-on-the-call design (`port_requests_24h`).
**Steps.**
1. Click **Port to Northwind (try 3×)** three times in the same session.
2. Verdicts: PASS, PASS, BLOCK ("several port-out requests today…").

## 7. Cross-organisation passport check (port-out to another carrier)
**Description.** A port-out hands the customer's number to another company's agent. The SIM & Porting Agent is in passport mode (Tier 4: cross-organisational reach). Northwind's porting agent presents a passport TeleNova recognises → proceeds; QuickTel presents none → held for the fraud desk.
**Business proof.** Trust between companies is checked per transaction, not assumed, so partner integrations can be automated safely.
**Governance demoed.** Agent passport (passport mode) · counterparty passport verification · per-counterparty oversight (HOTL vs HITL) · cross-org trust boundary.
**Steps.**
1. Open **/passports** → SIM & Porting Agent (T4, PASSPORT MODE) → drawer → *Counterparty passports*.
2. Back in Nova (Reset demo first): chip **Port to Northwind** → PASS, "presented passport NWM-PORT-AGENT-4.2".
3. Chip **Port to QuickTel** → held, REVIEW → Human Review → Approve → released as FRAUD-DESK-CERTIFIED.

## 8. Retention offer fairness
**Description.** A customer considering leaving gets a save offer, but the platform flags it: the offer engine personalised it on a postcode segment, a proxy for protected characteristics. The offer still goes out; compliance gets the signal.
**Business proof.** Churn reduction continues, with fairness risk surfaced before it becomes a pattern.
**Governance demoed.** Advisory (WARN) verdict that warns without blocking · fairness / proxy-attribute monitoring.
**Steps.**
1. Chip **Thinking of switching** → offer shown, chip WARN + ⚠ "Offer flagged for fairness review…".

## 9. Account Recovery Board (multi-agent deadlock → human)
**Description.** The customer reports a port-out they never requested. Four reviewer agents with legitimate but conflicting goals (Fraud and Compliance: keep the freeze; Retention and Care: restore service) deadlock 2–2 over two rounds. The platform detects the impasse and escalates to a person.
**Business proof.** Multi-agent decisions don't get stuck or resolved by whichever agent shouts loudest; a human decides with full context.
**Governance demoed.** Multi-agent conflict detection · A2A governance · Sentinel escalation · precedence rule (fraud/compliance first).
**Steps.**
1. Chip **My number was ported without me** → line frozen, chip REVIEW; agent pills show all five agents.
2. Human Review → open the item (votes and precedence) → **Approve**.
3. Nova: "Your number stays frozen until you verify your identity in store…".

## 10. Fleet passports and the agent registry (close)
**Description.** Every agent has a governance record: an agent card in the Trust registry (identity mode), and for the one agent that crosses a boundary TeleNova doesn't control, a passport.
**Business proof.** One auditable inventory of what every agent may do, who owns it, and how it is overseen.
**Governance demoed.** Agent registry · identity vs passport record mode · RAI primer risk tiers · validity by tier.
**Steps.**
1. Dashboard → **Agent Registry** → app *telenova* → 13 cards with purpose, authority, allowed/prohibited actions.
2. **/passports** → record mode column; tiers and their basis.

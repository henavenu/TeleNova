# TeleNova on Cloud Run

Container image for Cloud Run, built from the repo's `Dockerfile` (python:3.12-slim,
listens on `$PORT` 8080, non-root, local config files removed). Tested locally against the
beta platform: SDK `governance ACTIVE eval=SYNC enforce=RAISE`, `scenario_check.py --approve`
ALL PASS.

| | |
|---|---|
| App id on the platform | `telenova` (`TRUST_APP_ID`) |
| Cloud Run service | `telenova`, project `cb9252819a-raigov-gc` (project ID `cog01kmzvxwkcp4jrwtxtgttgsnh0`), region `us-east1` |
| Environment variables | `cloudrun.env.example` |
| RAI Trust SDK | 0.1.2 (`sdk-dist/wheelhouse`). Upgrading to langgraph 0.1.4 needs the Account Recovery Board votes remapped to the coordinator, as in VitaLink (0.1.4 governs a tool mapped to its own caller as a plain tool_call, so the deadlock never reaches Human Review). |

## Notes

- Required at startup: `TRUST_PE_URL` and `PAP_URL` (the container exits without them).
- One instance (`--min-instances=1 --max-instances=1`): sessions and Human Review holds live in memory.
- `RAI_APP_KEY` must be the full `<key_id>.<secret>` credential issued for `telenova` on the cloud
  platform. Without a valid key the SDK starts `Ready (DEGRADED) -- observe-only` (PAP/PE answer 401).
- The LLM is optional (the scenarios are deterministic). With Gemini, `GOOGLE_CLOUD_PROJECT` must be
  the project ID, and the service account needs `roles/aiplatform.user`. Or set `LLM_DISABLED=true`.

## Verify

- Logs: `Ready -- governance ACTIVE   eval=SYNC  enforce=RAISE`.
- `venv/bin/python scenario_check.py https://<service-url>` (add `--approve` only when the PAP is reachable from where you run it).

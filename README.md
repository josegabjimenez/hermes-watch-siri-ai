# Hermes Watch Siri AI

Watch-first iOS/watchOS capture system for routing quick Apple Watch and Siri captures into Hermes Agents.

The project starts with a documented backend staging layer and API contract, then moves toward a native iOS + watchOS app that prioritizes Apple Watch capture speed.

## Current scope

- Native iOS + watchOS app roadmap.
- Watch-first UX and Apple-platform constraints.
- `mobile_capture.v1` API contract.
- Synchronous BFF staging endpoint for Watch-friendly responses.
- HMAC V2 signing and idempotency ledger design.
- Domain gates for Megan/Aura write-enabled actions.
- Fable 5 review gates for important architecture/security/product decisions.

## What “BFF” means here

**BFF = Backend for Frontend.** In this project it is a small synchronous backend tailored to the iPhone/Apple Watch frontend. It verifies requests, enforces idempotency, returns short Watch-friendly JSON, and keeps sensitive agent/tool writes behind server-side gates.

The generic Hermes webhook adapter remains useful for async ingestion/logging, but the Watch MVP should target the BFF because the Watch UI needs immediate feedback.

## Repository layout

```text
backend/
  mobile_capture_staging_server.py       # local synchronous dry-run BFF
  mobile-capture-v1-webhook-prompt.md    # generic Hermes webhook prompt, log-only/no-write
  fixtures/                              # signed-request test fixtures
  scripts/sign_and_post_mobile_capture.py
  tests/test_mobile_capture_staging_server.py

docs/
  ROADMAP.md
  ARCHITECTURE.md
  API_CONTRACT_V1.md
  BACKEND_STAGING_PLAN.md
  IMPLEMENTATION_STATUS.md
  TAILSCALE_SERVE_ENDPOINT.md
  DOMAIN_GATES_MEGAN_AURA.md
  FABLE5_GATES.md
  FABLE5_REVIEW_*.md
  DECISION_LOG.md
  IMPLEMENTATION_TICKETS.md
  SUBAGENT_SYNTHESIS.md
  subagent-briefs/
```

## Local development

Start the staging BFF:

```bash
python3 backend/mobile_capture_staging_server.py --port 8650
```

Health check:

```bash
curl -fsS http://127.0.0.1:8650/health
```

Run tests:

```bash
cd backend
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

## Tailscale Serve for device testing

Expose the local BFF inside a Tailscale tailnet:

```bash
tailscale serve --bg --yes --https=8650 http://127.0.0.1:8650
```

Use this public-safe placeholder in docs/app config examples:

```text
https://<TAILSCALE_DNS_NAME>:8650/webhooks/mobile-capture-v1
```

Replace `<TAILSCALE_DNS_NAME>` locally with your actual tailnet DNS name. Do not commit secrets or private local config.

## Security status

Current status is **dry-run/no-write**.

Blocked before production writes:

- durable deployment behind HTTPS;
- iPhone/Watch Keychain secret bootstrap;
- server-side domain write flags;
- production-grade ledger retention/backup;
- privacy/log redaction policy;
- physical Apple Watch QA;
- Fable 5 domain gates for Megan/Aura.

## License

MIT — see [`LICENSE`](LICENSE).

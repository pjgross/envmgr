"""AI / copilot substrate.

Three pieces, each usable without the others:

- `client`  — the seam to an OpenAI-compatible gateway (the local AI test
              server in dev; anything with a base_url in prod). Reasoning is
              split off from answers here, once.
- `tools`   — the registry of functions a model may call. ADDITIVE allowlist:
              a capability is invisible to the model until listed here. Every
              handler is tenant-scoped and answers bad arguments with an
              explicit error the model can act on.
- `copilot_service` — the agent loop that joins the two.

No HTTP endpoint exposes this yet; its consumer is the test suite, by design —
it exists so the Phase 8 copilot has a tested seam and the AI test server has
a real flow to exercise. See CLAUDE.md, "Local AI test server".
"""

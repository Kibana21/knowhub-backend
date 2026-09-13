# ADR-018 — All model access crosses the Model Gateway

- **Status:** Accepted
- **Scope:** backend
- **Origin:** master blueprint §82
- **Supersedes:** —
- **Superseded by:** —

## Decision

All generative/embedding model access crosses the KnowHub Model Gateway; provider SDKs do not leak into domain/workflow code.

## Rationale / consequence

Supports approved cloud models and local inference (Ollama/OpenAI-compatible endpoints) while keeping routing, capability checks, residency and fallbacks governable.

---

Origin: [master blueprint §82](../../../knowhub_master_blueprint.html#adr-register) — the frozen origin register.
Decision and rationale above are reproduced from §82 without addition.
Registered in [the ADR register](https://github.com/Kibana21/knowhub-specs/blob/main/02-adrs/README.md).

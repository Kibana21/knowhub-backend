# ADR-020 — DSPy is a selective optimization layer

- **Status:** Accepted
- **Scope:** backend
- **Origin:** master blueprint §82
- **Supersedes:** —
- **Superseded by:** —

## Decision

DSPy is a selective AI-program optimization layer inside LangGraph nodes, not the workflow orchestrator or provider abstraction.

## Rationale / consequence

Stable LLM tasks can be compiled/evaluated systematically while LangGraph remains responsible for workflow state and the Model Gateway remains responsible for providers.

---

Origin: [master blueprint §82](../../../knowhub_master_blueprint.html#adr-register) — the frozen origin register.
Decision and rationale above are reproduced from §82 without addition.
Registered in [the ADR register](https://github.com/Kibana21/knowhub-specs/blob/main/02-adrs/README.md).

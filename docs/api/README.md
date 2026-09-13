# API contract documentation

This directory holds OpenAPI guidance and contract changelogs for
`knowhub-backend`, per master blueprint §84.3 and
[ADR-026](https://github.com/Kibana21/knowhub-specs/blob/main/02-adrs/ADR-026-adr-ownership-and-location.md).

## Current state

The backend owns the HTTP contract: FastAPI and Pydantic models are
authoritative for request and response shape, and the frontend generates its
client from a pinned artifact rather than from hand-written types
([ADR-017](https://github.com/Kibana21/knowhub-specs/blob/main/02-adrs/ADR-017-openapi-is-the-shared-contract.md)).

No contract artifact is published yet. The M00 foundation exposes only
liveness and readiness probes, which are operational endpoints rather than a
product API surface, so there is nothing to version, publish or diff against.

## What arrives with the first business endpoint

When M1 introduces the first business API surface, this directory gains:

- guidance on exporting the versioned `openapi.json` artifact from the
  running application;
- the contract-update workflow the frontend follows to refresh its pinned
  copy;
- a changelog recording additive changes and any change requiring a new API
  version or a documented compatibility transition.

Until then, this file records why the directory is empty of contracts rather
than leaving that unexplained.

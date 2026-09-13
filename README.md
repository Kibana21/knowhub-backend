# knowhub-backend

The KnowHub backend: a standalone, pure-Python application codebase that owns
every server-side domain rule, API, worker, connector, evidence and knowledge
operation, and AI workflow for the KnowHub platform.

This repository contains **no** React, Next.js or TypeScript application
source. It builds, lints, type-checks and tests without cloning
`knowhub-frontend`; the two repositories integrate through the backend's
versioned OpenAPI contract and share no source code.

Development is specification-driven. Requirements live in the `knowhub-specs`
workspace; architectural decisions live in [`docs/adr/`](docs/adr/) and in the
workspace-wide ADR register. Neither is restated here.

## Runtime baseline

- **Python 3.12** — the only tested runtime. `.python-version` pins the exact
  patch; `requires-python` is `>=3.12`, which keeps the floor without
  claiming compatibility that has not been tested.
- **`uv` + `pyproject.toml` + a committed `uv.lock`** is the single path to a
  working environment. There is no second dependency path: no ad-hoc
  installs, no requirements file, no vendored tree.

## Getting started

```sh
uv sync --frozen
```

That is sufficient to obtain the exact, reproducible environment.

## Repository layout

| Path | Contents |
|---|---|
| `src/knowhub/` | Application packages. A package is created by the milestone that first puts working code in it; the target layout is recorded in the blueprint, not materialised ahead of its code. |
| `docs/adr/` | Backend-scoped architectural decision records. |
| `docs/api/` | OpenAPI guidance and contract changelogs. |

## Quality tooling

| Tool | Purpose |
|---|---|
| Ruff | Lint and format, including import order and annotation coverage on KnowHub-owned code. |
| Pyright | Static type checking at `standard` strictness. |

Configuration for both lives in `pyproject.toml`.

## Not yet present

The following arrive with the foundation tasks that own them, and this
section shrinks as they land:

- **Dependency services and the developer loop** — PostgreSQL, Redis and
  Azurite, how they are provisioned, and how their availability is verified.
  KnowHub consumes them as configured endpoints and never detects how a
  service was provisioned, so an existing local instance and a managed
  container are equally valid.
- **Configuration** — the typed settings model and `.env.example`.
- **Observability, the minimal API, migrations, tests, the container image
  and CI.**

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

## Dependency services

KnowHub consumes PostgreSQL, Redis and object storage as **configured
endpoints**. It neither knows nor cares how they were provisioned — a
container, Homebrew, a native install or any other runtime are
indistinguishable to the application. Two modes are supported, and the
application, its configuration and its tests are identical in both.

### Mode A — existing services

Use what your machine already runs, and start only what you lack. Requires
PostgreSQL 15 or later with the `vector` extension **available** (KnowHub does
not create it), a database of your own, and a reachable Redis.

### Mode B — managed compose

The reproducible clean-room environment. CI uses it, onboarding uses it when a
dependency is absent, and the M00 acceptance criteria are verified against it.

```sh
docker compose -f docker-compose.dev.yml up -d --wait
```

Published on deliberately non-default ports — 55432, 56379, 10000-10002 — so
it never collides with a service already on 5432 or 6379.

## Getting started

Identical in both modes:

```sh
cp .env.example .env                            # 1. configure your endpoints
uv sync --frozen                                # 2. exact, reproducible env
uv run python scripts/check_dependencies.py     # 3. verify availability
```

Steps 4 onward — migrations, running the API, the validation sweep — arrive
with the tasks that own them.

## Repository layout

| Path | Contents |
|---|---|
| `src/knowhub/` | Application packages. A package is created by the milestone that first puts working code in it; the target layout is recorded in the blueprint, not materialised ahead of its code. |
| `docs/adr/` | Backend-scoped architectural decision records. |
| `docs/api/` | OpenAPI guidance and contract changelogs. |
| `docs/telemetry-naming.md` | The telemetry naming and cardinality convention. |
| `scripts/` | Developer and CI tooling. Not application code. |

## Quality tooling

| Tool | Purpose |
|---|---|
| Ruff | Lint and format, including import order and annotation coverage on KnowHub-owned code. |
| Pyright | Static type checking at `standard` strictness. |

Configuration for both lives in `pyproject.toml`.

## Not yet present

The following arrive with the foundation tasks that own them, and this
section shrinks as they land:

- **CI** — the pipeline that runs the gates above on every change.

## Container image

One image per commit, started in different process modes (blueprint §30.1).
At M00 only `api` has an implementation; `worker` and `scheduler` arrive with
the M2 code that backs them.

```sh
docker build -t knowhub-backend .
docker run --rm -p 8000:8000 \
  -e KNOWHUB_DATABASE__PASSWORD_REF=env:KH_DB_PASSWORD \
  -e KH_DB_PASSWORD=... \
  knowhub-backend api
```

The image runs as a non-root user, contains only the virtualenv and the
entrypoint, and carries no configuration of its own — every value comes from
the environment through the canonical settings model. An unknown process mode
exits non-zero rather than falling through to a shell.

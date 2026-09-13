# syntax=docker/dockerfile:1

# KnowHub backend runtime image.
#
# One image per commit, started in different process modes (blueprint §30.1).
# Only the `api` mode has an implementation at M00; worker and scheduler
# modes arrive with the M2 functionality that backs them, as new commands
# rather than as a change to this image's contract.
#
# Both bases are pinned by tag AND by multi-architecture *index* digest, so
# the pin resolves correctly on arm64 and amd64 alike. A platform-specific
# manifest digest would break on the other architecture.
#
# **Reproducibility invariant:** the interpreter that builds the virtualenv is
# the interpreter that executes it. The builder and runtime stages therefore
# share one pinned `python:3.12-slim-bookworm` digest, and `uv` is copied in
# from the pinned Astral image rather than the build running on Astral's own
# Python. Building against one patch and running on another is ABI-safe for
# cp312, but "ABI-safe" is not the same as reproducible.

# --------------------------------------------------------------------------
# uv — the build tool only. A static binary; nothing else is taken from here,
# and it never reaches the runtime stage.
# --------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58 AS uv

# --------------------------------------------------------------------------
# Builder — the runtime image plus uv. Same digest as the final stage, so the
# virtualenv is built by the interpreter that will run it.
# --------------------------------------------------------------------------
FROM python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254 AS builder

COPY --from=uv /usr/local/bin/uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    # Never fetch an interpreter: the base image supplies the one that must be
    # used, and a download would silently reintroduce the drift this stage
    # exists to remove.
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3.12

WORKDIR /app

# Dependencies first, as their own layer: they change far less often than the
# source, so an edit to src/ does not re-resolve the world.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --no-editable

# Then the project itself. --no-editable installs it into site-packages, so
# the runtime stage needs the virtualenv and nothing else.
COPY README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# Record the interpreter that built the environment, so the invariant above is
# verifiable from the shipped image rather than taken on trust.
RUN /app/.venv/bin/python --version > /app/.venv/BUILD_PYTHON_VERSION

# --------------------------------------------------------------------------
# Runtime — same base digest as the builder. The virtualenv, an entrypoint,
# and nothing else.
# --------------------------------------------------------------------------
FROM python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254 AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Fixed UID/GID so file ownership is predictable wherever this runs.
RUN groupadd --gid 10001 knowhub \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin knowhub

WORKDIR /app

# Only the virtualenv crosses the stage boundary. uv and the build cache stay
# behind.
COPY --from=builder --chown=10001:10001 /app/.venv /app/.venv
COPY --chown=10001:10001 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 0555 /usr/local/bin/docker-entrypoint.sh

USER 10001:10001

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["api"]

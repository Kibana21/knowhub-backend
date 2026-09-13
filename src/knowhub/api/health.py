"""Liveness and readiness probes.

These are operational endpoints, not a product API surface. They report
process state and nothing else: no configuration value, no credential, no
connection string, no internal host address (M00-SPEC-001 R10). Detail is
deliberately coarse — enough for an orchestrator to act on, not enough to
describe the deployment to whoever asks.

**Readiness at M00 is strictly foundation-scoped** (R9): settings loaded, and
observability initialisation completed. It must not probe PostgreSQL, Redis,
object storage, identity, the run model or any connector. None of those exist
yet, and reaching for one to look thorough would broaden the milestone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field

__all__ = [
    "HealthResponse",
    "ReadinessResponse",
    "ReadinessState",
    "get_readiness_state",
    "router",
]


@dataclass
class ReadinessState:
    """What the process has completed at startup.

    Held on ``app.state``. Flipped to not-ready during shutdown so a draining
    process stops advertising readiness while it finishes in-flight work.
    """

    settings_loaded: bool = False
    observability_ready: bool = False

    def pending(self) -> list[str]:
        """Return the names of components that are not ready. Names only."""
        not_ready: list[str] = []
        if not self.settings_loaded:
            not_ready.append("settings")
        if not self.observability_ready:
            not_ready.append("observability")
        return not_ready


def get_readiness_state(request: Request) -> ReadinessState:
    """Return the readiness state the application factory recorded."""
    state: ReadinessState = request.app.state.readiness
    return state


class HealthResponse(BaseModel):
    status: str


class ReadinessResponse(BaseModel):
    status: str
    pending: list[str] = Field(default_factory=list)


router = APIRouter(tags=["operations"])


@router.get("/healthz", response_model=HealthResponse, summary="Liveness probe")
async def healthz() -> HealthResponse:
    """Report that the process is alive and serving.

    Performs no I/O and consults no dependency: liveness answers "is this
    process running", and a probe that queried a database would report a
    healthy process as dead whenever the database blinked.
    """
    return HealthResponse(status="ok")


@router.get("/readyz", response_model=ReadinessResponse, summary="Readiness probe")
async def readyz(
    response: Response,
    state: Annotated[ReadinessState, Depends(get_readiness_state)],
) -> ReadinessResponse:
    """Report whether startup completed and the process can serve.

    Returns 503 with the names of the components still pending. Component
    names only — never why, never with what configuration.
    """
    pending = state.pending()
    if pending:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="not_ready", pending=pending)
    return ReadinessResponse(status="ready")

"""KnowHub HTTP API.

At M00 this package carries application bootstrap and the two operational
probes, and nothing else. Business routers arrive with M1, in ``routers/``.
"""

from knowhub.api.main import create_app

__all__ = ["create_app"]

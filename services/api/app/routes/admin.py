"""Read-only internal OPS dashboard API.

Serves the developer/operations dashboard (the apps/web AdminScreen): the mix/set event stream,
the one-line health summary, and the per-device rollup. It reads the event log the mix/set
pipelines write (app/events.py) and nothing else.

STRICTLY READ-ONLY. It never creates, changes, or deletes a mix, a set, or a file — which is
what keeps this new surface out of the dangerous render/storage code entirely. If it ever grows a
button that deletes or re-triggers a render, that crosses into the "handle with care" surfaces and
needs the stop-and-ask review.

SECURITY — a one-way door flagged on purpose. This endpoint exposes user content (the songs each
device mixed). On the founder's localhost, no auth is fine. The MOMENT it is served at any
internet-reachable URL it MUST be gated. The gate is built in but OFF by default for zero-friction
local dev: set the PROMPTDJ_DASHBOARD_TOKEN environment variable, and every /admin request must
then carry a matching `X-Dashboard-Token` header. With no token set, the API is open (local use).
Until a real login exists, do not expose this reachable without setting that token.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app import events
from app.config import settings


def _require_token(x_dashboard_token: str | None = Header(default=None)) -> None:
    """Optional shared-secret gate. Open when PROMPTDJ_DASHBOARD_TOKEN is unset (local dev);
    otherwise every request must present the matching X-Dashboard-Token header."""
    token = os.environ.get("PROMPTDJ_DASHBOARD_TOKEN")
    if token and x_dashboard_token != token:
        raise HTTPException(401, "This dashboard is locked. A valid access token is required.")


# The guard runs on every route in this router (so the whole /admin surface is protected at once).
router = APIRouter(prefix="/admin", dependencies=[Depends(_require_token)])


@router.get("/summary")
def admin_summary() -> dict:
    """The health strip: all-time + today's totals, failures, degraded mixes, and distinct devices."""
    return events.summary(settings.data_dir)


@router.get("/events")
def admin_events(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user_id: str | None = Query(None),
    kind: str | None = Query(None),
) -> dict:
    """A page of mix/set events, newest first — {events, total}. Every mix ever made is here;
    the page is bounded (never an unbounded fetch) and the dashboard pages through with offset.
    Optional filters: `user_id` (a device), `kind` ('mix' | 'set')."""
    return events.query_events(settings.data_dir, limit=limit, offset=offset,
                               user_id=user_id, kind=kind)


@router.get("/devices")
def admin_devices() -> list:
    """The 'user by user' rollup — one row per anonymous device, busiest first, with its
    mix count and how many broke or came out degraded. (A device, not a person, until login.)"""
    return events.devices(settings.data_dir)

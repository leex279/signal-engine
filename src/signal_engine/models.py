"""Item schema and pipeline models matching templates/item_schema.md."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
import hashlib


def make_changelog_id(page_url: str, heading: str, body: str) -> str:
    """Stable ID for changelog entries: hash of page_url + heading + first ~200 chars of body."""
    snippet = (body or "").strip()[:200]
    raw = f"{page_url.strip()}|{heading.strip()}|{snippet}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"changelog:{digest}"


@dataclass
class SignalItem:
    """The single item shape every source maps to before storage."""

    id: str
    source: str
    title: str
    url: str
    body: str
    published_at: datetime | None = None
    engagement: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # Pipeline state columns
    filtered_by: str | None = None
    decision: dict[str, Any] | None = None
    in_digest: str | None = None

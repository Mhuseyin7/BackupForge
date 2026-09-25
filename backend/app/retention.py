from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone


def artifacts_to_delete(artifacts: list, policy: dict, now: datetime | None = None) -> list:
    """Return only old VERIFIED artifacts. The newest valid artifact is never selected."""
    if not artifacts:
        return []
    now = now or datetime.now(timezone.utc)
    ordered = sorted(artifacts, key=lambda item: item.completed_at, reverse=True)
    keep: set[object] = {ordered[0].id}
    latest = int(policy.get("keep_latest", 1))
    keep.update(item.id for item in ordered[:max(1, latest)])

    def keep_period(field: str, count: int, period):
        seen = set()
        for item in ordered:
            if item.completed_at < now - timedelta(days=count * period[1]):
                continue
            marker = period[0](item.completed_at)
            if marker not in seen:
                keep.add(item.id)
                seen.add(marker)

    if (daily := int(policy.get("daily", 0))) > 0:
        keep_period("daily", daily, (lambda d: d.date(), 1))
    if (weekly := int(policy.get("weekly", 0))) > 0:
        keep_period("weekly", weekly, (lambda d: d.isocalendar()[:2], 7))
    if (monthly := int(policy.get("monthly", 0))) > 0:
        keep_period("monthly", monthly, (lambda d: (d.year, d.month), 31))
    return [item for item in ordered if item.id not in keep]


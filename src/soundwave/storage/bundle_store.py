from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
SOURCE_ID = "twitter_security_list"

# Bundles are named by Beijing date: the crawl fires at 21:13 UTC, which is
# already the next day in Asia/Shanghai, and the bundle serves that morning's
# briefing. Naming by UTC date would put it in the wrong day.
CST = timezone(timedelta(hours=8))


def beijing_date(dt: datetime) -> str:
    return dt.astimezone(CST).strftime("%Y-%m-%d")


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value).astimezone(timezone.utc).isoformat()
        except ValueError:
            return value
    return ""


def _producer() -> dict[str, Any]:
    try:
        from importlib.metadata import version

        pkg_version = version("soundwave")
    except Exception:
        pkg_version = "unknown"

    return {
        "name": "soundwave",
        "version": pkg_version,
        "run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "commit": os.environ.get("GITHUB_SHA", "")[:7],
    }


def to_item(tweet: Any, list_name: str = "") -> dict[str, Any]:
    """Map a TweetRecord (or its dict form from data/) to a contract Item.

    Drops `raw` (89% of payload, debug-only — recoverable from the run artifact)
    and keeps `media`, which security tweets often carry as their actual content.
    """
    t = asdict(tweet) if is_dataclass(tweet) else dict(tweet)
    media = t.get("media") or {}
    name = t.get("list_name") or list_name

    return {
        "external_id": str(t["id"]),
        "url": t.get("url", ""),
        "content": t.get("content", ""),
        "author": t.get("author_handle", ""),
        "author_name": t.get("author_name", ""),
        "published_at": _iso(t.get("published_at")),
        "collected_at": _iso(t.get("collected_at")),
        "tags": [f"list:{name}"] if name else [],
        "hashtags": list(t.get("hashtags") or []),
        "links": list(t.get("urls") or []),
        "media": {
            "photos": list(media.get("photos") or []),
            "videos": list(media.get("videos") or []),
        },
        "metrics": {
            "like_count": t.get("like_count", 0),
            "retweet_count": t.get("retweet_count", 0),
            "reply_count": t.get("reply_count", 0),
            "view_count": t.get("view_count", 0),
        },
        "flags": {
            "is_retweet": bool(t.get("is_retweet")),
            "is_quote": bool(t.get("is_quote")),
        },
    }


class BundleStore:
    """Day bundles: the contract surface Megatron pulls.

    One file per Beijing day, all lists merged, `raw` stripped. Writes merge by
    external_id rather than overwrite, so a same-day rerun (workflow_dispatch,
    backup cron) is strictly additive — the rolling crawl window means a later
    run starts later, and an overwrite would silently drop the earlier head.
    """

    def __init__(self, bundle_dir: str = "bundles", source_id: str = SOURCE_ID):
        self.dir = Path(bundle_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.source_id = source_id

    def path_for(self, date: str) -> Path:
        return self.dir / f"{date}.json"

    def write(
        self,
        date: str,
        items: list[dict[str, Any]],
        window_start: datetime,
        window_end: datetime,
        window_hours: int,
        failed_lists: list[str] | None = None,
    ) -> Path:
        path = self.path_for(date)
        existing = json.loads(path.read_text()) if path.exists() else {}

        merged: dict[str, dict[str, Any]] = {
            it["external_id"]: it for it in existing.get("items", [])
        }
        merged.update({it["external_id"]: it for it in items})

        start, end = _iso(window_start), _iso(window_end)
        old_window = existing.get("collect_window") or {}
        if old_window.get("start"):
            start = min(start, old_window["start"])
        if old_window.get("end"):
            end = max(end, old_window["end"])

        ordered = sorted(
            merged.values(), key=lambda it: it["published_at"], reverse=True
        )
        by_list: dict[str, int] = {}
        for it in ordered:
            for tag in it["tags"]:
                if tag.startswith("list:"):
                    by_list[tag[5:]] = by_list.get(tag[5:], 0) + 1

        bundle = {
            "schema_version": SCHEMA_VERSION,
            "source_id": self.source_id,
            "collect_date": date,
            "collect_window": {"start": start, "end": end, "hours": window_hours},
            "producer": _producer(),
            "stats": {
                "total": len(ordered),
                "by_list": by_list,
                "failed_lists": failed_lists or [],
            },
            "items": ordered,
        }

        path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2))
        return path

    def rebuild_index(self) -> Path:
        """Rewrite index.json — Core's entry point and readiness marker."""
        days = []
        watermark = ""

        for path in sorted(self.dir.glob("*.json"), reverse=True):
            if path.name == "index.json":
                continue
            data = json.loads(path.read_text())
            days.append(
                {
                    "date": data["collect_date"],
                    "count": data["stats"]["total"],
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "window_end": data["collect_window"]["end"],
                }
            )
            watermark = max(watermark, data["collect_window"]["end"])

        index = {
            "source_id": self.source_id,
            "schema_version": SCHEMA_VERSION,
            "latest": days[0]["date"] if days else "",
            "watermark": watermark,
            "updated_at": _iso(datetime.now(timezone.utc)),
            "days": days,
        }

        path = self.dir / "index.json"
        path.write_text(json.dumps(index, ensure_ascii=False, indent=2))
        return path


__all__ = ["BundleStore", "beijing_date", "to_item", "SCHEMA_VERSION", "SOURCE_ID"]

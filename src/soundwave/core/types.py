from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MediaInfo:
    photos: list[str] = field(default_factory=list)
    videos: list[str] = field(default_factory=list)
    thumbnails: list[str] = field(default_factory=list)


@dataclass
class TweetRecord:
    id: str
    list_name: str
    author_handle: str
    author_name: str
    content: str
    url: str
    published_at: datetime
    collected_at: datetime
    like_count: int = 0
    retweet_count: int = 0
    reply_count: int = 0
    view_count: int = 0
    hashtags: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    media: MediaInfo = field(default_factory=MediaInfo)
    is_retweet: bool = False
    is_quote: bool = False
    raw: dict = field(default_factory=dict)


@dataclass
class ListConfig:
    name: str
    list_id: str
    alias: str = ""
    enabled: bool = True


@dataclass
class FilterStats:
    total_fetched: int = 0
    skipped: int = 0
    tracked_ids: int = 0
    stop_reason: str | None = None


@dataclass
class CrawlResult:
    list_name: str
    list_id: str
    records: list[TweetRecord] = field(default_factory=list)
    filter_stats: FilterStats = field(default_factory=FilterStats)
    duration: float = 0.0
    output_path: str | None = None
    error_type: str | None = None
    error_msg: str | None = None

    @property
    def collected(self) -> int:
        return len(self.records)

    @property
    def success(self) -> bool:
        return self.error_type is None


__all__ = [
    "MediaInfo",
    "TweetRecord",
    "ListConfig",
    "FilterStats",
    "CrawlResult",
]

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import TYPE_CHECKING

from ..core.types import FilterStats

if TYPE_CHECKING:
    from twscrape.models import Tweet


class Action(str, Enum):
    COLLECT = "collect"
    SKIP = "skip"
    STOP = "stop"


class TweetFilter:
    MAX_CONSECUTIVE_OLD_RETWEETS = 50

    def __init__(self, window_hours: int = 24):
        self.cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        self.window_hours = window_hours
        self._retweeted_ids: set[str] = set()
        self._pending_old: Tweet | None = None
        self._consecutive_old_retweets: int = 0
        self._skipped_count: int = 0
        self._total_fetched: int = 0

    def process(self, tweet: Tweet) -> Action:
        self._total_fetched += 1
        self._track_ids(tweet)

        if self._is_referenced(tweet):
            self._skipped_count += 1
            return Action.SKIP

        tweet_time = tweet.date.astimezone(timezone.utc)
        in_window = tweet_time >= self.cutoff

        if in_window and self._pending_old is not None:
            self._pending_old = None

        if in_window:
            self._consecutive_old_retweets = 0
            return Action.COLLECT

        is_retweet = tweet.retweetedTweet is not None

        if not is_retweet:
            if self._pending_old is not None:
                return Action.STOP
            self._pending_old = tweet
            return Action.SKIP

        self._consecutive_old_retweets += 1
        if self._consecutive_old_retweets >= self.MAX_CONSECUTIVE_OLD_RETWEETS:
            return Action.STOP
        return Action.SKIP

    def get_stats(self, stop_reason: str | None = None) -> FilterStats:
        return FilterStats(
            total_fetched=self._total_fetched,
            skipped=self._skipped_count,
            tracked_ids=len(self._retweeted_ids),
            stop_reason=stop_reason,
        )

    def _track_ids(self, tweet: Tweet) -> None:
        if tweet.retweetedTweet:
            self._retweeted_ids.add(str(tweet.retweetedTweet.id))
        if tweet.quotedTweet:
            self._retweeted_ids.add(str(tweet.quotedTweet.id))

    def _is_referenced(self, tweet: Tweet) -> bool:
        return str(tweet.id) in self._retweeted_ids


__all__ = ["TweetFilter", "Action"]

from __future__ import annotations

import asyncio
import random
import time
from pathlib import Path

from twscrape import API

from ..core.config import TwitterCredentials, Settings
from ..core.logger import Logger, LogFlow
from ..core.types import CrawlResult, FilterStats, ListConfig, TweetRecord
from .filter import TweetFilter, Action
from .util import tweet_to_record


AUTH_KEYWORDS = ("403", "unauthorized", "forbidden", "could not authenticate", "login")
RATE_KEYWORDS = ("429", "rate limit", "too many requests", "ratelimit")
NETWORK_KEYWORDS = ("connection", "timeout", "proxy", "resolve", "refused", "unreachable")


def diagnose_error(exc: Exception) -> tuple[str, str]:
    msg = str(exc).lower()
    if any(kw in msg for kw in AUTH_KEYWORDS):
        return (
            "AUTH_FAILED",
            f"Authentication failed (cookies may be expired). "
            f"Update TWITTER_AUTH_TOKEN and TWITTER_CT0 in repo secrets. Error: {exc}",
        )
    if any(kw in msg for kw in RATE_KEYWORDS):
        return (
            "RATE_LIMITED",
            f"Rate limited by Twitter. Consider increasing delays in config/settings.json. Error: {exc}",
        )
    if any(kw in msg for kw in NETWORK_KEYWORDS):
        return (
            "NETWORK",
            f"Network error. Check proxy/connectivity. Error: {exc}",
        )
    return (
        "UNKNOWN",
        f"Unexpected error: {exc}",
    )


class TwitterCrawler:
    def __init__(
        self,
        config: ListConfig,
        credentials: TwitterCredentials,
        settings: Settings,
    ):
        self.config = config
        self.logger = Logger()

        db_path = credentials.temp_db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        from twscrape.accounts_pool import AccountsPool
        pool = AccountsPool(db_file=db_path)
        self.api = API(pool=pool, proxy=credentials.proxy or None)

        self._initialized = False
        self.credentials = credentials

        self.delay_min = settings.delay_min
        self.delay_max = settings.delay_max
        self.batch_size = settings.batch_size
        self.pause_every_n_batches = settings.pause_every_n_batches
        self.pause_min = settings.pause_min
        self.pause_max = settings.pause_max

    async def _ensure_accounts(self):
        if not self._initialized:
            for account in self.credentials.accounts:
                if account.active:
                    await self.api.pool.add_account(
                        username=account.username,
                        password="",
                        email="",
                        email_password="",
                        cookies=account.cookies,
                    )

            active = sum(1 for a in self.credentials.accounts if a.active)
            proxy = self.credentials.proxy or "none"
            self.logger.info(LogFlow.SOURCE, "twitter",
                f"Accounts diagnostic: {active} active, proxy={proxy}")

            self._initialized = True

    async def _check_and_unlock(self):
        try:
            accounts = await self.api.pool.get_all()
            locked = [a for a in accounts if a.locks]

            if locked:
                names = ", ".join(a.username for a in locked)
                self.logger.warning(LogFlow.SOURCE, "twitter", f"Locked accounts: {names}")
                await self.api.pool.reset_locks()
                self.logger.info(LogFlow.SOURCE, "twitter", f"Unlocked: {names}")
                await asyncio.sleep(2)
            else:
                self.logger.info(LogFlow.SOURCE, "twitter", "All accounts available")
        except Exception as e:
            self.logger.warning(LogFlow.SOURCE, "twitter", f"Unlock check failed: {e}")

    async def _auto_unlock(self):
        try:
            await self.api.pool.reset_locks()
            self.logger.info(LogFlow.SOURCE, "twitter", "Accounts unlocked")
            await asyncio.sleep(2)
        except Exception as e:
            self.logger.warning(LogFlow.SOURCE, "twitter", f"Unlock failed: {e}")

    async def fetch(self, window_hours: int = 24, max_retries: int = 3) -> CrawlResult:
        start_time = time.time()

        try:
            await self._ensure_accounts()
            await self._check_and_unlock()

            for attempt in range(max_retries):
                try:
                    if attempt > 0:
                        self.logger.info(LogFlow.SOURCE, "twitter", f"Retry {attempt + 1}/{max_retries}")
                        await self._auto_unlock()

                    records, filter_stats, stop_reason = await self._do_fetch(window_hours)

                    return CrawlResult(
                        list_name=self.config.name,
                        list_id=self.config.list_id,
                        records=records,
                        filter_stats=FilterStats(
                            total_fetched=filter_stats[0],
                            skipped=filter_stats[1],
                            tracked_ids=filter_stats[2],
                            stop_reason=stop_reason,
                        ),
                        duration=time.time() - start_time,
                    )

                except asyncio.TimeoutError:
                    if attempt < max_retries - 1:
                        self.logger.warning(LogFlow.SOURCE, "twitter",
                            f"Timeout (attempt {attempt + 1}/{max_retries})")
                        continue
                    raise

                except Exception as e:
                    msg = str(e).lower()
                    if attempt < max_retries - 1 and any(
                        kw in msg for kw in ("no account", "queue", "lock")
                    ):
                        self.logger.warning(LogFlow.SOURCE, "twitter",
                            f"Account issue: {e} (attempt {attempt + 1}/{max_retries})")
                        continue
                    raise

        except Exception as e:
            error_type, error_msg = diagnose_error(e)

            if error_type == "AUTH_FAILED":
                self.logger.error(LogFlow.SOURCE, "twitter", error_msg)
            elif error_type == "RATE_LIMITED":
                self.logger.warning(LogFlow.SOURCE, "twitter", error_msg)
            elif error_type == "NETWORK":
                self.logger.warning(LogFlow.SOURCE, "twitter", error_msg)
            else:
                self.logger.error(LogFlow.SOURCE, "twitter", error_msg)

            return CrawlResult(
                list_name=self.config.name,
                list_id=self.config.list_id,
                duration=time.time() - start_time,
                error_type=error_type,
                error_msg=error_msg,
            )

        return CrawlResult(
            list_name=self.config.name,
            list_id=self.config.list_id,
            duration=time.time() - start_time,
        )

    async def _do_fetch(self, window_hours: int) -> tuple[list[TweetRecord], tuple[int, int, int], str | None]:
        tweet_filter = TweetFilter(window_hours=window_hours)
        records: list[TweetRecord] = []
        batch_count = 0
        start_time = time.time()
        stop_reason = None

        async for tweet in self.api.list_timeline(list_id=int(self.config.list_id)):
            action = tweet_filter.process(tweet)

            if action == Action.STOP:
                stop_reason = "Reached tweets outside time window"
                break
            elif action == Action.SKIP:
                continue

            record = tweet_to_record(tweet, self.config.name)
            records.append(record)
            batch_count += 1

            preview = (tweet.rawContent or "No content")[:60]
            self.logger.info(LogFlow.SOURCE, "twitter",
                f'Matched: "{preview}..." by @{tweet.user.username}')

            if batch_count % self.batch_size == 0:
                elapsed = time.time() - start_time
                delay = random.uniform(self.delay_min, self.delay_max)
                self.logger.info(LogFlow.SOURCE, "twitter",
                    f"Fetched {len(records)} tweets, waiting {delay:.1f}s, elapsed {elapsed:.0f}s")
                await asyncio.sleep(delay)

                batches_done = batch_count // self.batch_size
                if batches_done % self.pause_every_n_batches == 0 and batches_done > 0:
                    pause = random.uniform(self.pause_min, self.pause_max)
                    self.logger.info(LogFlow.SOURCE, "twitter",
                        f"Pausing for {pause:.0f}s...")
                    await asyncio.sleep(pause)

        stats = tweet_filter.get_stats(stop_reason)
        self.logger.info(LogFlow.SOURCE, "twitter",
            f"Filter: fetched={stats.total_fetched}, skipped={stats.skipped}, "
            f"tracked={stats.tracked_ids}, stop={stop_reason or 'N/A'}")
        self.logger.info(LogFlow.SOURCE, "twitter",
            f"Collected {len(records)} tweets from {self.config.name}")

        filter_tuple = (stats.total_fetched, stats.skipped, stats.tracked_ids)
        return records, filter_tuple, stop_reason

    async def close(self):
        pass


__all__ = ["TwitterCrawler", "diagnose_error"]

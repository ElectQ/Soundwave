from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from .core.config import ConfigManager
from .core.logger import Logger, LogFlow
from .core.types import CrawlResult
from .crawler import create_crawler
from .storage.json_store import JsonStore


logger = Logger()


def crawl(
    list_name: str | None = None,
    hours: int = 24,
    max_retries: int = 3,
) -> dict[str, Any]:
    """Crawl tweets from configured Twitter Lists.

    Returns:
        {
            "started_at": "...",
            "finished_at": "...",
            "duration": 72.5,
            "window_hours": 24,
            "total": 108,
            "results": [CrawlResult, ...],
        }
    """
    async def _run():
        config_manager = ConfigManager()
        settings = config_manager.load_settings()
        credentials = config_manager.load_twitter_credentials()
        store = JsonStore(settings.output_dir)

        all_lists = config_manager.load_lists()
        if list_name:
            targets = [l for l in all_lists if l.name == list_name and l.enabled]
        else:
            targets = [l for l in all_lists if l.enabled]

        started_at = datetime.now(timezone.utc)

        if not targets:
            logger.info(LogFlow.SOURCE, "twitter", "No lists to crawl")
            return {
                "started_at": started_at.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "duration": 0.0,
                "window_hours": hours,
                "total": 0,
                "results": [],
            }

        logger.info(LogFlow.SOURCE, "twitter", "=" * 50)
        logger.info(LogFlow.SOURCE, "twitter", "Soundwave Crawl Started")
        logger.info(LogFlow.SOURCE, "twitter", f"  Time: {started_at.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        logger.info(LogFlow.SOURCE, "twitter", f"  Window: {hours}h")
        logger.info(LogFlow.SOURCE, "twitter", f"  Lists: {', '.join(l.name for l in targets)}")
        logger.info(LogFlow.SOURCE, "twitter", "=" * 50)

        results: list[CrawlResult] = []

        for list_config in targets:
            logger.info(LogFlow.SOURCE, "twitter",
                f"Crawling {list_config.name} ({list_config.alias or list_config.list_id})...")

            crawler = create_crawler(list_config, credentials, settings)
            try:
                result = await crawler.fetch(window_hours=hours, max_retries=max_retries)
            except Exception as e:
                from .crawler.crawler import diagnose_error
                error_type, error_msg = diagnose_error(e)
                result = CrawlResult(
                    list_name=list_config.name,
                    list_id=list_config.list_id,
                    error_type=error_type,
                    error_msg=error_msg,
                )
                logger.error(LogFlow.SOURCE, "twitter", error_msg)

            if result.records:
                path = store.save(result.records, list_config.list_id, list_config.name)
                result.output_path = str(path)
                logger.info(LogFlow.STORAGE, "json",
                    f"Saved {result.collected} tweets to {path}")
            elif result.success:
                logger.info(LogFlow.SOURCE, "twitter",
                    f"No tweets collected from {list_config.name}")

            results.append(result)
            await crawler.close()

        finished_at = datetime.now(timezone.utc)
        duration = (finished_at - started_at).total_seconds()
        total = sum(r.collected for r in results)

        logger.info(LogFlow.SOURCE, "twitter", "=" * 50)
        logger.info(LogFlow.SOURCE, "twitter", "Soundwave Crawl Finished")
        logger.info(LogFlow.SOURCE, "twitter", f"  Duration: {duration:.0f}s")
        logger.info(LogFlow.SOURCE, "twitter", f"  Total: {total} tweets")
        for r in results:
            status = f"{r.collected} tweets" if r.success else f"FAILED ({r.error_type})"
            logger.info(LogFlow.SOURCE, "twitter",
                f"  {r.list_name}: {status}")
        logger.info(LogFlow.SOURCE, "twitter", "=" * 50)

        return {
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration": duration,
            "window_hours": hours,
            "total": total,
            "results": results,
        }

    return asyncio.run(_run())


def get_stats() -> dict[str, Any]:
    """Get crawl statistics."""
    config_manager = ConfigManager()
    store = JsonStore(config_manager.load_settings().output_dir)
    return {"days": store.get_stats()}


__all__ = ["crawl", "get_stats"]

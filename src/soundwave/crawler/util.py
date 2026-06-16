from __future__ import annotations

from datetime import datetime, timezone

from twscrape.models import Tweet

from ..core.types import MediaInfo, TweetRecord


def extract_media(tweet: Tweet) -> MediaInfo:
    media_info = MediaInfo()

    for source in [tweet, tweet.retweetedTweet]:
        if not source or not source.media:
            continue
        if source.media.photos:
            media_info.photos.extend(p.url for p in source.media.photos)
        if source.media.videos:
            for v in source.media.videos:
                if v.variants:
                    best = max(v.variants, key=lambda x: x.bitrate)
                    media_info.videos.append(best.url)
                if v.thumbnailUrl:
                    media_info.thumbnails.append(v.thumbnailUrl)
        if source.media.animated:
            for a in source.media.animated:
                if a.videoUrl:
                    media_info.videos.append(a.videoUrl)
                if a.thumbnailUrl:
                    media_info.thumbnails.append(a.thumbnailUrl)

    return media_info


def tweet_to_record(tweet: Tweet, list_name: str) -> TweetRecord:
    return TweetRecord(
        id=str(tweet.id),
        list_name=list_name,
        author_handle=tweet.user.username,
        author_name=tweet.user.displayname,
        content=tweet.rawContent or "",
        url=tweet.url,
        published_at=tweet.date.astimezone(timezone.utc),
        collected_at=datetime.now(timezone.utc),
        like_count=tweet.likeCount or 0,
        retweet_count=tweet.retweetCount or 0,
        reply_count=tweet.replyCount or 0,
        view_count=tweet.viewCount or 0,
        hashtags=tweet.hashtags or [],
        urls=[link.url for link in (tweet.links or [])],
        media=extract_media(tweet),
        is_retweet=tweet.retweetedTweet is not None,
        is_quote=tweet.quotedTweet is not None,
        raw=tweet.dict() if hasattr(tweet, "dict") else {},
    )


__all__ = ["extract_media", "tweet_to_record"]

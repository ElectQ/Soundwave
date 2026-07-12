# Soundwave

Twitter List crawler running on GitHub Actions. **This is a Collector, not an agent** — it
fetches, normalizes, and publishes. Grading, pushing, and feedback all live in Megatron.

## What it produces

```
bundles/index.json        <- entry point + readiness marker (fixed name)
bundles/2026-07-12.json   <- one file per Beijing day, all lists merged
data/2026-07-11/{list_id}.json   <- internal raw archive (UTC-dated, keeps `raw`)
```

`bundles/` is the **contract with Megatron**. `data/` is the internal raw layer — useful for
debugging and re-deriving bundles, not meant to be consumed directly.

### Why bundles are named by Beijing date

The crawl fires at 21:13 UTC, which is already **the next day in Asia/Shanghai**. The bundle
serves that morning's briefing, so it carries the Beijing date. Naming it by UTC date would
file it under the wrong day. This also makes the name robust to scheduling delay — a run can
slip 10+ hours and still land in the same Beijing day.

`data/` keeps its original UTC-dated layout so the existing git-pull path stays valid.

### Bundle shape

```json
{
  "schema_version": 1,
  "source_id": "twitter_security_list",
  "collect_date": "2026-07-12",
  "collect_window": { "start": "...", "end": "...", "hours": 30 },
  "producer": { "name": "soundwave", "version": "1.0.0", "run_id": "...", "commit": "..." },
  "stats": { "total": 145, "by_list": { "sec_list": 145 }, "failed_lists": [] },
  "items": [ { "external_id": "...", "content": "...", "media": {...}, "metrics": {...} } ]
}
```

`collect_date` is the **collection batch day, not the publish day** — items inside span the
whole `collect_window`, which reaches back across the previous day. `raw` is stripped (87% of
the payload); recover it from the run artifact via `producer.run_id` if you need it.

Writes **merge by `external_id`** rather than overwrite, so a rerun (`workflow_dispatch`, or a
delayed schedule) is strictly additive. The crawl window is rolling, so a later run starts
later — an overwrite would silently drop the earlier head of the day.

## Fetching the data

The repo is public, so pulling needs no auth, no token, and no git clone — two fixed URLs
over raw HTTP:

```
https://raw.githubusercontent.com/ElectQ/Soundwave/master/bundles/index.json
https://raw.githubusercontent.com/ElectQ/Soundwave/master/bundles/<date>.json
```

Ask the index what the newest day is, then fetch that day:

```bash
BASE=https://raw.githubusercontent.com/ElectQ/Soundwave/master/bundles

# what's available, and is today's bundle ready?
curl -s "$BASE/index.json" | jq '{latest, watermark, days: (.days | length)}'
# → { "latest": "2026-07-12", "watermark": "2026-07-11T21:13:00+00:00", "days": 26 }

# pull that day (~150 KB)
curl -s "$BASE/$(curl -s "$BASE/index.json" | jq -r .latest).json" -o bundle.json

# and it's ready to use
jq '.stats, (.items[0] | {external_id, author, content, url})' bundle.json
```

The bundle is a single self-contained JSON — no pagination, no per-list assembly, no `raw`
noise to strip. Point an ingest at `.items[]` and dedupe on `(source_id, external_id)`.

### Doing it properly in production

**Poll the readiness marker, don't watch the clock.** GitHub dispatches scheduled runs
2h-5h late and the spread is wide, so any "pull at HH:MM" rule is a bet on a number GitHub
doesn't promise.

```python
CST = timezone(timedelta(hours=8))
RAW = "https://raw.githubusercontent.com/ElectQ/Soundwave/master/bundles"

def _get(name):                       # raw.githubusercontent is a CDN, max-age=300
    r = httpx.get(f"{RAW}/{name}", params={"t": int(time.time())}, timeout=30)
    r.raise_for_status()
    return r.json(), r.content

def fetch_day(date):
    index, _ = _get("index.json")
    entry = next((d for d in index["days"] if d["date"] == date), None)
    if entry is None:
        raise BundleNotReady(date, latest=index["latest"])
    bundle, body = _get(f"{date}.json")
    if hashlib.sha256(body).hexdigest() != entry["sha256"]:
        raise IntegrityError(date)    # CDN served a fresh index with a stale bundle; retry
    return bundle

def pull_today(deadline_hour=8, interval=300):
    today = datetime.now(CST).strftime("%Y-%m-%d")
    while True:
        try:
            return fetch_day(today)
        except (BundleNotReady, IntegrityError):
            if datetime.now(CST).hour >= deadline_hour:
                raise SourceMissing("twitter_security_list", today)
            time.sleep(interval)
```

`index.json` and `<date>.json` are separate CDN entries and can be cached out of step, which is
what the `sha256` check is for. Poll every 300s to match the cache TTL.

A missing bundle at the deadline means **publish degraded and alert** — never "no news today".
On 2026-06-26 a crawl returned zero tweets, stayed green, and the day vanished silently; the
zero-tweet guard now fails that job, but Core still has to notice the absence.

`index.days` carries every day ever built, so Core can reconcile after an outage instead of
needing a human:

```python
def catch_up(already_have: set[str]):
    index, _ = _get("index.json")
    for d in index["days"]:
        if d["date"] not in already_have:
            ingest(fetch_day(d["date"])["items"])
```

Dedupe on `(source_id, external_id)` — the crawler's raw output contains 1-3 duplicate tweets
on most days, and the 30h window overlaps the previous day on purpose.

## Scheduling

`cron: '13 21 * * *'` → 21:13 UTC = **05:13 Beijing**.

The slot is deliberately cold. The previous setting (05:00 UTC) is US-Eastern midnight on the
hour — GitHub's most congested cron slot — and every one of the last 25 runs was dispatched
**2h10m to 5h36m late**. The delay is in GitHub's cron dispatcher (`createdAt == startedAt`),
so no amount of runner tuning helps; only the slot does. 05:13 leaves ~2h45m of delay budget
against the 08:00 deadline.

The window is **30h, not 24h**. Jitter means a run can start up to 5h36m later than the
previous one, and a 24h window would leave that stretch uncollected — this had already opened
a real 57-minute hole on 2026-07-08. The overlap is absorbed by `external_id` dedup.

## Commands

```bash
soundwave crawl                          # crawl + write bundle (default 30h window)
soundwave crawl --hours 48               # wider window, e.g. catching up after a failure
soundwave build-bundle                   # rebuild all bundles from data/ (backfill)
soundwave build-bundle --date 2026-07-11 # rebuild one day
soundwave stats / lists / status
```

A crawl returning **0 tweets fails the job**. A security list is never silent for 30h, so zero
means broken auth — not a quiet day. Left unchecked this stays green and silently skips the
day, which is exactly what happened on 2026-06-26.

## Secrets

`TWITTER_AUTH_TOKEN`, `TWITTER_CT0` — cookies from a logged-in session, set in
Settings → Secrets. Never logged.

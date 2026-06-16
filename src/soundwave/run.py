from __future__ import annotations

import os
from datetime import datetime

import click
from dotenv import load_dotenv

load_dotenv()

from .api import crawl, get_stats
from .core.config import ConfigManager


def _write_job_summary(result: dict) -> None:
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_file:
        return

    lines = [
        "## Soundwave Crawl Report",
        "",
        f"**Date**: {datetime.fromisoformat(result['started_at']).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Duration**: {result['duration']:.0f}s",
        f"**Window**: {result['window_hours']}h",
        f"**Total Tweets**: {result['total']}",
        "",
        "### Per-List Results",
        "",
        "| List | ID | Tweets | Filter Stats | Status | File |",
        "|---|---|---|---|---|---|",
    ]

    for r in result["results"]:
        if r.success:
            status = "✅"
            filter_str = (
                f"fetched:{r.filter_stats.total_fetched} "
                f"skipped:{r.filter_stats.skipped}"
            )
            file_str = r.output_path or "N/A"
        else:
            status = f"❌ {r.error_type}"
            filter_str = "-"
            file_str = "-"

        lines.append(
            f"| {r.list_name} | {r.list_id} | {r.collected} | {filter_str} | {status} | `{file_str}` |"
        )

    lines.append("")

    errors = [r for r in result["results"] if not r.success]
    if errors:
        lines.append("### ⚠️ Errors")
        lines.append("")
        for r in errors:
            lines.append(f"- **{r.list_name}** ({r.error_type}): {r.error_msg}")
        lines.append("")

    with open(summary_file, "w") as f:
        f.write("\n".join(lines))


@click.group()
def cli():
    """Soundwave - Twitter List Crawler"""
    pass


@click.command("crawl")
@click.option("--list", "-l", "list_name", type=str, default=None, help="List name to crawl")
@click.option("--hours", "-h", type=int, default=24, help="Time window in hours")
def crawl_cmd(list_name, hours):
    """Crawl tweets from Twitter Lists"""
    result = crawl(list_name=list_name, hours=hours)

    print(f"\nDone: {result['total']} tweets in {result['duration']:.0f}s")
    for r in result["results"]:
        if r.success:
            print(f"  {r.list_name}: {r.collected} tweets")
        else:
            print(f"  {r.list_name}: FAILED ({r.error_type})")

    _write_job_summary(result)

    if any(not r.success for r in result["results"]):
        raise click.ClickException("Crawl completed with errors")


@click.command("stats")
def stats_cmd():
    """Show crawl statistics"""
    result = get_stats()
    days = result["days"]
    if not days:
        print("No data collected yet")
        return
    print(f"{'Date':<14} {'Total':>6}  Lists")
    print("-" * 50)
    for day in days[:30]:
        lists_str = ", ".join(f"{l['list_id']}:{l['count']}" for l in day["lists"])
        print(f"{day['date']:<14} {day['total']:>6}  {lists_str}")


@click.command("lists")
def lists_cmd():
    """List configured Twitter Lists"""
    config_mgr = ConfigManager()
    lists = config_mgr.load_lists()
    if not lists:
        print("No lists configured")
        return
    print("Configured lists:")
    for l in lists:
        status = "enabled" if l.enabled else "disabled"
        alias = f" ({l.alias})" if l.alias else ""
        print(f"  [{status}] {l.name}{alias} -> {l.list_id}")


@click.command("status")
def status_cmd():
    """Check Twitter account status"""
    credentials = ConfigManager().load_twitter_credentials()
    if not credentials.accounts:
        print("No accounts configured")
        return
    for acc in credentials.accounts:
        s = "active" if acc.active else "inactive"
        cookies = "yes" if acc.cookies else "no"
        print(f"  {acc.username}: [{s}] cookies={cookies}")


cli.add_command(crawl_cmd)
cli.add_command(stats_cmd)
cli.add_command(lists_cmd)
cli.add_command(status_cmd)


if __name__ == "__main__":
    cli()

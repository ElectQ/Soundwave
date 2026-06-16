from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .types import ListConfig

load_dotenv()


@dataclass
class TwitterAccount:
    username: str
    cookies: str
    active: bool = True


@dataclass
class TwitterCredentials:
    accounts: list[TwitterAccount] = field(default_factory=list)
    proxy: str = ""
    temp_db_path: str = "/tmp/twscrape.db"


@dataclass
class ProxyConfig:
    enabled: bool = False
    http: str = ""
    https: str = ""

    def get_proxy(self, url: str) -> str | None:
        if not self.enabled:
            return None
        if url.startswith("https://"):
            return self.https or self.http
        return self.http


@dataclass
class Settings:
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    delay_min: float = 3.0
    delay_max: float = 8.0
    batch_size: int = 20
    pause_every_n_batches: int = 3
    pause_min: float = 10.0
    pause_max: float = 20.0
    output_dir: str = "data"


class ConfigManager:
    CONFIG_DIR = Path("config")

    def __init__(self):
        self._settings: Settings | None = None
        self._twitter_credentials: TwitterCredentials | None = None
        self._lists: list[ListConfig] | None = None

    def load_settings(self) -> Settings:
        if self._settings is None:
            path = self.CONFIG_DIR / "settings.json"
            if path.exists():
                data = json.loads(path.read_text())
                proxy_data = data.get("proxy", {})
                crawl = data.get("crawl", {})
                storage = data.get("storage", {})
                self._settings = Settings(
                    proxy=ProxyConfig(
                        enabled=proxy_data.get("enabled", False),
                        http=proxy_data.get("http", ""),
                        https=proxy_data.get("https", ""),
                    ),
                    delay_min=crawl.get("delay_min", 3.0),
                    delay_max=crawl.get("delay_max", 8.0),
                    batch_size=crawl.get("batch_size", 20),
                    pause_every_n_batches=crawl.get("pause_every_n_batches", 3),
                    pause_min=crawl.get("pause_min", 10.0),
                    pause_max=crawl.get("pause_max", 20.0),
                    output_dir=storage.get("output_dir", "data"),
                )
            else:
                self._settings = Settings()
        return self._settings

    def load_twitter_credentials(self) -> TwitterCredentials:
        if self._twitter_credentials is None:
            auth_token = os.getenv("TWITTER_AUTH_TOKEN")
            ct0 = os.getenv("TWITTER_CT0")
            proxy = os.getenv("PROXY_URL", "")

            accounts = []
            if auth_token and ct0:
                cookies = json.dumps({"auth_token": auth_token, "ct0": ct0})
                accounts.append(
                    TwitterAccount(
                        username="soundwave",
                        cookies=cookies,
                        active=True,
                    )
                )

            self._twitter_credentials = TwitterCredentials(
                accounts=accounts,
                proxy=proxy,
                temp_db_path="/tmp/twscrape.db",
            )
        return self._twitter_credentials

    def load_lists(self) -> list[ListConfig]:
        if self._lists is None:
            path = self.CONFIG_DIR / "twitter" / "sources.json"
            if path.exists():
                data = json.loads(path.read_text())
                self._lists = [
                    ListConfig(
                        name=item["name"],
                        list_id=item["list_id"],
                        alias=item.get("alias", ""),
                        enabled=item.get("enabled", True),
                    )
                    for item in data.get("sources", [])
                ]
            else:
                self._lists = []
        return self._lists


__all__ = [
    "ConfigManager",
    "TwitterAccount",
    "TwitterCredentials",
    "Settings",
    "ProxyConfig",
]

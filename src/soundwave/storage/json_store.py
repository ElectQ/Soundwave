from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class JsonStore:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def save(self, records: list, list_id: str, list_name: str = "") -> Path:
        now = datetime.now(timezone.utc)
        date_dir = self.data_dir / now.strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)

        path = date_dir / f"{list_id}.json"

        payload = {
            "date": now.strftime("%Y-%m-%d"),
            "list_id": list_id,
            "list_name": list_name,
            "crawled_at": now.isoformat(),
            "count": len(records),
            "tweets": [self._to_dict(r) for r in records],
        }

        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return path

    def load(self, list_id: str, date: datetime) -> list[dict]:
        date_dir = self.data_dir / date.strftime("%Y-%m-%d")
        path = date_dir / f"{list_id}.json"
        if not path.exists():
            return []
        return json.loads(path.read_text()).get("tweets", [])

    def load_all_for_date(self, date: datetime) -> dict[str, list[dict]]:
        date_dir = self.data_dir / date.strftime("%Y-%m-%d")
        if not date_dir.exists():
            return {}
        result = {}
        for file in date_dir.glob("*.json"):
            data = json.loads(file.read_text())
            key = data.get("list_id", file.stem)
            result[key] = data.get("tweets", [])
        return result

    def get_stats(self) -> list[dict]:
        if not self.data_dir.exists():
            return []

        stats = []
        for date_dir in sorted(self.data_dir.iterdir(), reverse=True):
            if not date_dir.is_dir():
                continue
            date_str = date_dir.name
            files = list(date_dir.glob("*.json"))
            total = 0
            lists = []
            for f in files:
                data = json.loads(f.read_text())
                count = data.get("count", 0)
                total += count
                lists.append({
                    "list_id": data.get("list_id", f.stem),
                    "list_name": data.get("list_name", ""),
                    "count": count,
                })
            stats.append({"date": date_str, "total": total, "lists": lists})
        return stats

    def _to_dict(self, obj):
        if hasattr(obj, "__dataclass_fields__"):
            return {k: self._to_dict(v) for k, v in obj.__dict__.items() if not k.startswith("_")}
        if isinstance(obj, list):
            return [self._to_dict(item) for item in obj]
        if isinstance(obj, dict):
            return {k: self._to_dict(v) for k, v in obj.items()}
        return obj


__all__ = ["JsonStore"]

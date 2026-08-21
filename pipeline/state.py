"""Persistent state: which URLs we've seen, and the episode catalogue."""
from __future__ import annotations
from .config import STATE_FILE
from .util import read_json, write_json, iso_now


class State:
    def __init__(self):
        d = read_json(STATE_FILE, {"seen": {}, "episodes": [], "next_episode": 1, "baseline_date": None})
        self.seen: dict = d["seen"]
        self.episodes: list[dict] = d["episodes"]
        self.next_episode: int = d.get("next_episode", 1)
        self.baseline_date: str | None = d.get("baseline_date")

    def save(self):
        write_json(STATE_FILE, {"seen": self.seen, "episodes": self.episodes, "next_episode": self.next_episode,
                                "baseline_date": self.baseline_date})

    def mark(self, url: str, status: str, **extra):
        rec = self.seen.get(url, {"first_seen": iso_now(), "attempts": 0})
        rec.update(status=status, updated=iso_now(), **extra)
        if status == "failed":
            rec["attempts"] = rec.get("attempts", 0) + 1
        self.seen[url] = rec

    def status(self, url: str) -> str | None:
        return (self.seen.get(url) or {}).get("status")

    def add_episode(self, ep: dict):
        self.episodes = [e for e in self.episodes if e["url"] != ep["url"]]
        self.episodes.append(ep)
        self.episodes.sort(key=lambda e: e["date"])

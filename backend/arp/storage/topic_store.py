from __future__ import annotations

import json
from pathlib import Path

from arp.schemas.emerging_themes import EmergingThemeCandidate, LineageEvent, TopicCluster
from arp.storage.safe_path import safe_id


class TopicStateStore:
    """File-based persistence for the Emerging Themes Scanner's
    period-over-period state: this is what makes lineage tracking possible
    across separate runs, since a single run/period's clustering only
    shows what's being discussed *now* -- see arp/emerging_themes/lineage.py.

    Layout: `portfolios/topics/periods/<period>.json` (that period's
    TopicClusters), `portfolios/topics/lineage/<period>.jsonl` (that
    period's LineageEvents), and `portfolios/topics/candidates.jsonl` (an
    append-only history of every EmergingThemeCandidate ever emitted --
    read back by Phase 2's dedup/drift check to catch a theme oscillating
    between promoted and rejected).
    """

    def __init__(self, topics_dir: Path) -> None:
        self.topics_dir = topics_dir
        self.periods_dir = topics_dir / "periods"
        self.lineage_dir = topics_dir / "lineage"

    def _period_path(self, period: str) -> Path:
        return self.periods_dir / f"{safe_id(period, label='period')}.json"

    def _lineage_path(self, period: str) -> Path:
        return self.lineage_dir / f"{safe_id(period, label='period')}.jsonl"

    def candidates_path(self) -> Path:
        return self.topics_dir / "candidates.jsonl"

    def save_period(self, period: str, clusters: list[TopicCluster]) -> None:
        path = self._period_path(period)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([c.model_dump(mode="json") for c in clusters], indent=2))

    def load_period(self, period: str) -> list[TopicCluster] | None:
        path = self._period_path(period)
        if not path.exists():
            return None
        return [TopicCluster.model_validate(row) for row in json.loads(path.read_text())]

    def list_periods(self) -> list[str]:
        if not self.periods_dir.exists():
            return []
        return sorted(p.stem for p in self.periods_dir.glob("*.json"))

    def latest_period_before(self, period: str) -> str | None:
        """The most recent saved period strictly before `period`, for
        lineage linking -- periods sort lexicographically because callers
        are expected to use ISO date/week keys."""
        earlier = [p for p in self.list_periods() if p < period]
        return earlier[-1] if earlier else None

    def save_lineage_events(self, period: str, events: list[LineageEvent]) -> None:
        path = self._lineage_path(period)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as f:
            for event in events:
                f.write(json.dumps(event.model_dump(mode="json")) + "\n")

    def append_candidate(self, candidate: EmergingThemeCandidate) -> None:
        path = self.candidates_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(candidate.model_dump(mode="json")) + "\n")

    def list_candidates(self) -> list[EmergingThemeCandidate]:
        path = self.candidates_path()
        if not path.exists():
            return []
        candidates = []
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    candidates.append(EmergingThemeCandidate.model_validate(json.loads(line)))
                except (json.JSONDecodeError, ValueError):
                    continue
        return candidates

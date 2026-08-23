from __future__ import annotations

from pydantic import BaseModel, Field

from arp.schemas.thematic import MatchVerdict


class CalibrationScheduleConfig(BaseModel):
    """Persisted to <calibration_agent_state_dir>/schedule.json -- same
    shape/role as arp.schemas.discovery.DiscoveryScheduleConfig."""

    enabled: bool = False
    interval_hours: float = 24.0
    last_run_id: str | None = None


class DriftFlag(BaseModel):
    """A past theme-run verdict for which a newer company disclosure has
    since been fetched -- not a claim the verdict is wrong, just that
    newer evidence exists and a human may want to re-run classification.
    See arp/agents/calibration_agent.py::check_company_staleness.
    """

    source_run_id: str
    company_id: str
    activity_id: str
    old_verdict: MatchVerdict
    old_confidence: float
    old_generated_at: str
    newest_document_at: str
    reason: str = ""

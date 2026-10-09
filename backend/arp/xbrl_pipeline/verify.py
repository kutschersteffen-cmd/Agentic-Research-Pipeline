from __future__ import annotations

import json

from pydantic import ValidationError

from arp.normalise.units import convert
from arp.schemas.datapoints import ExtractionRecord
from arp.storage.atomic_io import atomic_write_text
from arp.storage.run_store import RunStore
from arp.xbrl_pipeline.models import VerifyRow
from arp.xbrl_pipeline.store import XbrlStore


class CircularRunError(ValueError):
    """The run may have copied XBRL values, so comparing against XBRL proves nothing."""


class UnsupportedRunError(ValueError):
    """The run's results are not generic extraction records (financials, tnfd, ...)."""


def assert_xbrl_off(run_id: str, *, run_store: RunStore) -> None:
    settings_path = run_store.run_dir(run_id) / "step_settings.json"
    if not settings_path.exists():
        raise CircularRunError(
            f"{run_id}: step_settings.json is missing, so it cannot be proven that XBRL was off. Runs started "
            "from the app, the API or `arp extract run` record their step settings (older CLI runs do not); "
            'start (or re-run) the extraction with "SEC XBRL facts first" switched off '
            "(in the app, or ARP_XBRL_FACTS_ENABLED=false for the CLI).")
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        enabled = data.get("xbrl_facts_enabled")
    except (ValueError, AttributeError) as exc:  # invalid JSON, or valid JSON that is not an object
        raise CircularRunError(f"{run_id}: step_settings.json is malformed, cannot prove XBRL was off") from exc
    if enabled:
        raise CircularRunError(f"{run_id}: ran with xbrl_facts_enabled, its values are copied from XBRL")


def verify_run(run_id: str, *, run_store: RunStore, store: XbrlStore, mapping: dict[str, str],
               tolerance: float = 0.005) -> list[VerifyRow]:
    assert_xbrl_off(run_id, run_store=run_store)

    # ponytail: linear scan, index by company above ~10k companies
    xbrl = {(cid, r.metric, r.fiscal_year): r
            for cik in store.ciks() for r in store.read_required(cik)
            for cid in {r.company_id, *store.company_ids(cik)}}

    rows: list[VerifyRow] = []
    for raw in run_store.read_jsonl(run_store.results_path(run_id)):
        try:
            rec = ExtractionRecord.model_validate(raw)
        except ValidationError as exc:
            raise UnsupportedRunError(f"run {run_id} does not contain generic extraction records; "
                                      "financials/tnfd runs are not supported") from exc
        # Calendar year of period_end, never a filing's fy.
        years = sorted({int(f.period_end[:4]) for f in rec.fields if f.period_end})
        for metric, field_id in mapping.items():
            for year in years:
                run_field = next((f for f in rec.fields if f.field_id == field_id and f.period_end
                                  and int(f.period_end[:4]) == year and f.canonical_value is not None), None)
                x = xbrl.get((rec.company_id, metric, year))
                x_value = x.value if x is not None and x.status == "found" else None
                run_value = run_field.canonical_value if run_field else None
                if run_value is None and x_value is None:
                    continue
                unit = x.unit if x_value is not None else run_field.canonical_unit
                detail = ""
                if run_value is None:
                    outcome = "missing_in_run"
                elif x_value is None:
                    outcome = "missing_in_xbrl"
                else:
                    compared = run_value
                    if run_field.canonical_unit != x.unit:  # normalise the run value into the XBRL unit
                        compared = convert(run_value, run_field.canonical_unit or "", x.unit or "").value
                    if compared is None:
                        outcome, detail = "mismatch", "unit"
                    else:
                        ok = abs(compared - x_value) <= tolerance * abs(x_value)
                        outcome = "match" if ok else "mismatch"
                rows.append(VerifyRow(company_id=rec.company_id, metric=metric, fiscal_year=year,
                                      outcome=outcome, run_value=run_value, xbrl_value=x_value,
                                      unit=unit, run_unit=run_field.canonical_unit if run_field else None,
                                      detail=detail))

    atomic_write_text(run_store.run_dir(run_id) / "xbrl_verify.jsonl",
                      "".join(r.model_dump_json() + "\n" for r in rows))
    return rows

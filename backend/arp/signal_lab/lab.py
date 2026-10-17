from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from arp.cli._shared import _run_store
from arp.config import get_settings
from arp.db.session import require_dsn
from arp.replication.characteristics_data import CharacteristicPanel
from arp.signal_lab.compare import Comparison, compare_experiments
from arp.signal_lab.cutoffs import CutoffTable, load_cutoff_table
from arp.signal_lab.inputs import load_inputs
from arp.signal_lab.methods.base import MethodInput, run_method, run_recipe
from arp.signal_lab.methods.checks import lookahead_violations
from arp.signal_lab.registry import ExperimentRecord, Recipe, Registry
from arp.signal_lab.stats import IcSummary, rank_ic_series, summarize_ic
from arp.signal_lab.text_store import TextRecord, TextStore

UNREGISTERED = "unregistered, not evidence"
_PREVIEW_REFUSAL = "a preview is unregistered, not evidence; run it first"


@dataclass
class Preview:
    panel: CharacteristicPanel
    model: str | None
    notes: dict
    ic: IcSummary
    label: str = UNREGISTERED

    def __repr__(self) -> str:
        return f"[{self.label}] model={self.model!r} IC mean={self.ic.mean} n={self.ic.n}"


def _experiment_id(value: object) -> str:
    if isinstance(value, Preview):
        raise ValueError(_PREVIEW_REFUSAL)
    if not isinstance(value, str):
        raise ValueError(f"expected an experiment id (str), got {type(value).__name__}")
    return value


def save_recipe(recipe: Recipe, path: Path) -> None:
    Path(path).write_text(recipe.model_dump_json(indent=2))


def load_recipe(path: Path) -> Recipe:
    try:
        return Recipe.model_validate(json.loads(Path(path).read_text()))
    except OSError as exc:
        raise ValueError(f"cannot read recipe {path}: {exc.strerror}") from exc
    except ValidationError as exc:
        detail = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'recipe'}: {e['msg']}" for e in exc.errors())
        raise ValueError(f"invalid recipe {path}: {detail}") from exc
    except ValueError as exc:  # malformed JSON
        raise ValueError(f"invalid recipe {path}: {exc}") from exc


class Lab:
    """Notebook facade: previews are labelled and unregistered; only `run` registers evidence."""

    def __init__(self, *, registry: Registry, cutoffs: CutoffTable, text_store: TextStore | None = None) -> None:
        self.registry = registry
        self.cutoffs = cutoffs
        self.text_store = text_store

    @classmethod
    def from_settings(cls) -> Lab:
        settings = get_settings()
        return cls(
            registry=Registry(_run_store()),
            cutoffs=load_cutoff_table(settings.training_cutoffs_path),
            text_store=TextStore(require_dsn(settings)) if settings.postgres_dsn else None,
        )

    def texts(self, *, known_by: str | None = None) -> list[TextRecord]:
        if self.text_store is None:
            raise ValueError("no text store: set ARP_POSTGRES_DSN or pass text_store to Lab")
        return self.text_store.items(known_by=known_by)

    def inputs(
        self,
        recipe: Recipe,
        prices: Path,
        *,
        panels: dict[str, Path] | None = None,
        texts: list[TextRecord] | None = None,
        history_from: str | None = None,
    ) -> tuple[MethodInput, str]:
        return load_inputs(recipe, prices, panels=panels, texts=texts, history_from=history_from)

    def preview(self, spec: dict, inp: MethodInput) -> Preview:
        result = run_method(spec, inp)
        ic = summarize_ic(rank_ic_series(result.panel, inp.prices))
        return Preview(panel=result.panel, model=result.model, notes=result.notes, ic=ic)

    def check(self, spec: dict, inp: MethodInput, *, at: list[int] | None = None) -> list[tuple[str, int]]:
        return lookahead_violations(spec, inp, at=at)

    def run(self, recipe: Recipe, inp: MethodInput, data_version: str) -> ExperimentRecord:
        return run_recipe(recipe, inp, registry=self.registry, cutoffs=self.cutoffs, data_version=data_version)

    def experiments(self) -> list[ExperimentRecord]:
        return self.registry.list_experiments()

    def compare(self, a: str, b: str, *, confidence: float = 0.95) -> Comparison:
        return compare_experiments(_experiment_id(a), _experiment_id(b), self.registry, confidence=confidence)

    def decide(
        self, experiment_id: str, decision: Literal["graduate", "shelve"], *, approver: str
    ) -> ExperimentRecord:
        return self.registry.decide(_experiment_id(experiment_id), decision, approver=approver, cutoffs=self.cutoffs)

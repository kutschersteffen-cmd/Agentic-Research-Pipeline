"""The closed set of step functions a plan script may call, with their typed inputs: the catalog's plan lane.

Adapters that start the real run types come with the executor (plan task 7); the checker, the dry run
and the planner prompt only need the input models.
"""
from __future__ import annotations

from arp.orchestration.capabilities import CATALOG

STEPS = {c.id: c.input_model for c in CATALOG if c.lane == "plan"}

# Fields a step result exposes to the script. Each company carries id, name, included (bool) and exposure
# (pure_play | significant | minor | none, the best across the theme's activities).
BUILTINS = ("len", "min", "max", "sorted", "sum", "range")

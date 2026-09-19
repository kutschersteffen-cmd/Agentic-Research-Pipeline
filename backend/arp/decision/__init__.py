"""Decision Mechanism: a deterministic scoring, ranking and tiering layer
over any per-entity table this system produces.

Zero LLM calls anywhere in the computation -- the same commitment
`arp/portfolio/aggregation.py` makes. Every automated choice is emitted as
an `AuditEntry` carrying its basis, and every entry records whether it came
from the data (`origin="derived"`) or from a person (`origin="human"`).

The two entry points are deliberately separate:

    derive_mechanism(dataset)          -> MechanismConfig + audit trail
    apply_mechanism(dataset, config)   -> DecisionResult

Derivation looks at data and proposes rules; application takes rules and
produces decisions. Keeping them apart is what makes a ratified framework
reusable -- it can be applied to next quarter's snapshot unchanged, which
is what `compare_results` then reports on.
"""

from arp.decision.compare import compare_results
from arp.decision.dataset import Dataset, build_dataset
from arp.decision.mechanism import apply_mechanism, derive_mechanism
from arp.decision.parsing import load_table
from arp.decision.profiling import profile_dataset
from arp.decision.sensitivity import tipping_points

__all__ = [
    "Dataset",
    "apply_mechanism",
    "build_dataset",
    "compare_results",
    "derive_mechanism",
    "load_table",
    "profile_dataset",
    "tipping_points",
]

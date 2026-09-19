"""Analyses underpinning docs/CORPORATE_DECARBONISATION_REVIEW.md.

Each module implements a specific claim in the review, so a reader can check
the argument by running the code rather than taking the prose on trust.

    schemas       Panel and firm-year types; enforces a single Scope 2 basis
    labels        Constant-perimeter (chained) decarbonisation labels        (S2.2, rule 1)
    attribution   LMDI split of intensity change into emissions/norm/alloc   (S2.2)
    scope2        Location- against market-based Scope 2 wedge               (S2.3, S3.1)
    saturation    Indicator prevalence decay and rarity weighting            (S7.3, rule 3)
    redflags      Seven-dimension greenwashing profile, orthogonality test   (S8, rule 4)
    divergence    Rank correlation across transition-risk metrics            (S3.5, rule 5)
    predict       Out-of-time increment over a persistence baseline          (S7.5, rule 2)
    synthetic     Calibrated simulated panel so everything runs unlicensed
    pipeline      One call that runs the full set and prints a report

No module requires numpy, pandas or scikit-learn.
"""

from __future__ import annotations

from arp.decarb import attribution, divergence, labels, predict, redflags, saturation, scope2, stats, synthetic
from arp.decarb.schemas import EmissionsBasis, FirmYear, Panel, RED_FLAGS, Scope2Basis

__all__ = [
    "attribution",
    "divergence",
    "labels",
    "predict",
    "redflags",
    "saturation",
    "scope2",
    "stats",
    "synthetic",
    "EmissionsBasis",
    "FirmYear",
    "Panel",
    "RED_FLAGS",
    "Scope2Basis",
]

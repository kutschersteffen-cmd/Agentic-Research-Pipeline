"""Econometrics and figures for the corporate decarbonisation review.

Separate from `arp.decarb` core because these modules need numpy, pandas,
scipy, statsmodels, scikit-learn and matplotlib:

    pip install "arp[research]"

The core package stays dependency-free so the descriptive analyses, label
construction and attribution run in any Python 3.11 environment. This
subpackage adds what the core cannot honestly provide: standard errors,
identification, and figures.

    frames      Panel <-> pandas bridge, growth and lag columns
    matching    Coarsened exact matching (Schüder & Zülch 2026)
    did         Staggered DiD event study (Dietz & Hastreiter 2026)
    inference   Panel OLS, fixed effects, clustered SEs, sign-stability checks
    models      Model comparison and the level-against-change distinction
    figures     The paper's figures, light and dark
"""

from __future__ import annotations

__all__ = ["did", "figures", "frames", "inference", "matching", "models"]

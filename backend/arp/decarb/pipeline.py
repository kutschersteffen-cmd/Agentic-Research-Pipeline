"""Run the full analysis set and print a report.

`python -m arp.decarb.pipeline` runs against the synthetic panel. Pass a
`Panel` built from real data to `run` to get the same report for it.

The report is organised to follow the review's argument, so the output can be
read next to the prose.
"""

from __future__ import annotations

import math

from arp.decarb import attribution, divergence, labels, predict, redflags, saturation, scope2
from arp.decarb.schemas import Panel
from arp.decarb.stats import auc_stratified
from arp.decarb.synthetic import GOVERNANCE_INDICATORS, make_panel


def _hdr(text: str) -> str:
    return f"\n{text}\n{'-' * len(text)}"


def run(panel: Panel, *, start_year: int | None = None, end_year: int | None = None) -> str:
    years = panel.years
    start = start_year or years[0]
    end = end_year or years[-1]
    out: list[str] = []

    out.append(f"Panel: {len(panel.firm_ids)} firms, {len(panel.rows)} firm-years, {start}-{end}")

    # 1. How much of the aggregate change is composition (review S2.2)
    out.append(_hdr("1. Aggregate against constant-perimeter change"))
    ch = labels.chained_change(panel, start, end)
    out.append(f"  aggregate        {ch.aggregate_pct:+7.1%}")
    out.append(f"  chained          {ch.chained_pct:+7.1%}   ({ch.n_continuing} continuing firms)")
    out.append(f"  composition      {ch.composition_pct:+7.1%}   ({ch.n_entered} entered, {ch.n_exited} exited)")

    # 2. What drove the intensity metric (review S2.2)
    out.append(_hdr("2. LMDI attribution of the WACI change"))
    attr = attribution.decompose_waci(panel.by_year(start), panel.by_year(end))
    pct = attr.as_pct_of_start()
    out.append(f"  WACI {attr.start_value:.1f} -> {attr.end_value:.1f}  ({attr.total_change:+.1f})")
    out.append(f"  emissions        {pct['emissions']:+7.1%}")
    out.append(f"  normalisation    {pct['normalisation']:+7.1%}")
    out.append(f"  allocation       {pct['allocation']:+7.1%}")
    out.append(f"  residual         {attr.residual:+.2e}  (identity check, should be ~0)")

    # 3. Scope 2 wedge (review S2.3)
    out.append(_hdr("3. Scope 2: location against market basis"))
    w = scope2.wedge_summary(panel, start, end)
    if w.n_firms:
        out.append(f"  dual reporters   {w.n_firms}")
        out.append(f"  location-based   {w.location_change_pct:+7.1%}")
        out.append(f"  market-based     {w.market_change_pct:+7.1%}")
        out.append(f"  wedge            {w.wedge_pct:+7.1%}")
        by_sector = scope2.wedge_by_group(panel, start, end, key="sector")
        worst = sorted(by_sector.items(), key=lambda kv: -kv[1].wedge_pct)[:3]
        for sector, sw in worst:
            out.append(f"    {sector:<14} wedge {sw.wedge_pct:+6.1%}  (n={sw.n_firms})")
    else:
        out.append("  no dual reporters in panel")

    # 4. Labels
    out.append(_hdr("4. Decarbonisation labels (disclosed emitters only)"))
    lab = labels.decarboniser_labels(panel, start_year=start, end_year=end)
    if lab:
        rates = sorted(r for r, _ in lab.values())
        n_dec = sum(1 for _, d in lab.values() if d)
        out.append(f"  labelled firms   {len(lab)}")
        out.append(f"  decarbonising    {n_dec} ({n_dec / len(lab):.0%})")
        out.append(f"  median rate      {rates[len(rates) // 2]:+.2%}/yr")
        out.append(f"  p25 / p75        {rates[len(rates) // 4]:+.2%} / {rates[3 * len(rates) // 4]:+.2%}")
    else:
        out.append("  no firms met the labelling criteria")

    # 5. Indicator saturation (review S6.3)
    out.append(_hdr("5. Indicator saturation and discriminatory power"))
    binary = {f: d for f, (_, d) in lab.items()}
    out.append(f"  {'indicator':<26}{'prev ' + str(start):>10}{'prev ' + str(end):>10}{'AUC(strat)':>12}")
    for ind in GOVERNANCE_INDICATORS:
        prev = saturation.prevalence_by_year(panel, ind)
        if start not in prev or end not in prev:
            continue
        a = prev[start].prevalence
        b = prev[end].prevalence
        auc_start = saturation.discriminatory_power(panel, ind, binary, year=start) if binary else float("nan")
        mark = "  <- saturated" if prev[end].is_saturated else ""
        out.append(f"  {ind:<26}{a:>9.0%}{b:>10.0%}{auc_start:>11.3f}{mark}")

    out.append("")
    weights = saturation.rarity_weights(panel, GOVERNANCE_INDICATORS, year=start)
    top = sorted(weights.items(), key=lambda kv: -kv[1])[:3]
    out.append("  rarity weights (top 3 at start): " + ", ".join(f"{k} {v:.2f}" for k, v in top))

    ws = saturation.weighted_score(panel, GOVERNANCE_INDICATORS, year=start)
    rc = saturation.raw_count(panel, GOVERNANCE_INDICATORS, year=start)
    rows_at_start = {r.firm_id: r for r in panel.rows if r.year == start}
    common = sorted(set(ws) & set(rc) & set(binary) & set(rows_at_start))
    if len(common) > 10:
        ys = [binary[f] for f in common]
        strata = [rows_at_start[f].sector for f in common]
        out.append(f"  AUC, raw count           {auc_stratified([float(rc[f]) for f in common], ys, strata):.3f}")
        out.append(f"  AUC, rarity-weighted     {auc_stratified([ws[f] for f in common], ys, strata):.3f}")
        out.append("  (stratified by sector; pooled AUC would mostly rank sectors)")

    # 6. Red flags (review S7)
    out.append(_hdr("6. Greenwashing red-flag profile"))
    for fp in redflags.prevalence(panel, year=end):
        pub = f"  (published {fp.published:.0%})" if fp.published is not None else ""
        out.append(f"  {fp.flag:<26}{fp.observed:>7.0%}{pub}")
    counts = redflags.profile_counts(panel, year=end)
    total = sum(counts.values())
    if total:
        at_least_one = sum(v for k, v in counts.items() if k >= 1) / total
        four_plus = sum(v for k, v in counts.items() if k >= 4) / total
        out.append(f"  at least one flag        {at_least_one:.0%}")
        out.append(f"  four or more flags       {four_plus:.0%}")
    verdict = redflags.profile_is_multidimensional(panel, year=end)
    out.append(f"  {verdict.explain()}")

    # 7. Metric divergence (review S3.5)
    out.append(_hdr("7. Transition-metric divergence"))
    rep = divergence.divergence_report(panel, year=end)
    out.append(f"  {rep.explain()}")

    # 8. Does anything beat persistence (review S6.5)
    out.append(_hdr("8. Out-of-time increment over persistence (forward 3y label, embargoed split)"))
    result = _persistence_test(panel)
    if result is None:
        out.append("  insufficient data for an out-of-time split")
    else:
        out.append(f"  baseline  AUC {result.baseline_auc:.3f}   R2 {result.baseline_r2:+.3f}")
        out.append(f"  augmented AUC {result.augmented_auc:.3f}   R2 {result.augmented_r2:+.3f}")
        out.append(f"  {result.verdict()}")
        for warn in result.warnings:
            out.append(f"  warning: {warn}")

    return "\n".join(out)


def _persistence_test(panel: Panel, horizon: int = 3):
    """Do the rare governance indicators add anything over lagged growth?

    Built to avoid the two failure modes that make this kind of test
    meaningless. The outcome is a *forward* rate over (t, t+horizon], so it
    shares no observations with the lagged growth used as the baseline. And
    the train/test split leaves a gap of `horizon` years between the last
    training base-year and the first test base-year, so no training label
    window extends into the test period.
    """
    years = panel.years
    if len(years) < 2 * horizon + 3:
        return None

    fwd = labels.forward_labels(panel, horizon=horizon)
    if not fwd:
        return None

    sectors = [r.sector for r in panel.rows]
    regions = [r.region for r in panel.rows]
    dummies = predict.sector_region_dummies(sectors, regions)

    base_rows, extra_rows, y_num, y_bin, row_years = [], [], [], [], []
    for row, dummy in zip(panel.rows, dummies):
        key = (row.firm_id, row.year)
        if key not in fwd:
            continue
        series = [s for s in panel.firm_series(row.firm_id) if s.year <= row.year and s.scope12]
        if len(series) < 2:
            continue
        prev, curr = series[-2], series[-1]
        if not prev.scope12 or not curr.scope12:
            continue
        lagged = math.log(curr.scope12 / prev.scope12)
        rate, is_dec = fwd[key]
        base_rows.append([lagged, *dummy])
        extra_rows.append([
            1.0 if row.indicators.get("capex_aligned_plan") else 0.0,
            1.0 if row.indicators.get("scope3_supplier_program") else 0.0,
            1.0 if row.indicators.get("internal_carbon_price") else 0.0,
        ])
        y_num.append(rate)
        y_bin.append(is_dec)
        row_years.append(row.year)

    if len(base_rows) < 60:
        return None

    usable = sorted({y for y in row_years})
    split = usable[len(usable) // 2]
    train = [y for y in usable if y <= split]
    # Embargo: skip `horizon` years so training label windows cannot reach
    # into the test base-years.
    test = [y for y in usable if y > split + horizon]
    if not train or not test:
        return None

    try:
        return predict.evaluate(
            baseline_features=base_rows,
            extra_features=extra_rows,
            outcome_numeric=y_num,
            outcome_binary=y_bin,
            years=row_years,
            design=predict.Design(train_years=train, test_years=test),
        )
    except ValueError:
        return None


def main() -> None:  # pragma: no cover - console entry point
    print(run(make_panel()))


if __name__ == "__main__":  # pragma: no cover
    main()

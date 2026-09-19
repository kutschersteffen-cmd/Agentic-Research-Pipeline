"""Model comparison, and the level-against-change distinction.

Xu, Wei and Ji (2026) compare six models predicting corporate carbon
intensity and report XGBoost reaching R-squared of 0.95 in the pre-COVID
period, 0.85 with carbon-related variables removed, with board characteristics
the most important governance block.

Section 6.5 of the review argues that result answers a different question from
the one investors have. Their target is carbon intensity as a *level*. Firms
are carbon-intensive mainly because of what sector they are in and how big
they are, so a model predicting levels without carbon inputs is largely
recovering sector and size. Predicting which firms are dirty is a much easier
problem than predicting which firms are getting cleaner.

`compare_targets` runs the same feature set against both targets on the same
panel, so the gap is visible rather than argued. `shuffled_sector_control`
goes further and reports how much of the level R-squared survives once sector
is randomised.

Splitting is by time throughout. A random split of a firm-year panel puts
adjacent years of the same firm in train and test and inflates every score.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.linear_model import ElasticNet, Lasso, Ridge
from sklearn.metrics import r2_score, root_mean_squared_error
from sklearn.preprocessing import StandardScaler

__all__ = ["ModelScore", "TargetComparison", "build_models", "time_split_evaluate", "compare_targets"]


@dataclass(slots=True)
class ModelScore:
    name: str
    r2: float
    rmse: float
    n_train: int
    n_test: int
    importances: pd.Series | None = None


@dataclass(slots=True)
class TargetComparison:
    level: list[ModelScore]
    change: list[ModelScore]
    level_without_sector: list[ModelScore] = field(default_factory=list)

    def best(self, scores: list[ModelScore]) -> ModelScore:
        return max(scores, key=lambda s: s.r2)

    def summary(self) -> str:
        lines = [f"{'model':<20}{'R2 level':>11}{'R2 change':>12}"]
        by_name = {s.name: s for s in self.change}
        for s in self.level:
            c = by_name.get(s.name)
            lines.append(f"{s.name:<20}{s.r2:>11.3f}{(c.r2 if c else float('nan')):>12.3f}")
        bl, bc = self.best(self.level), self.best(self.change)
        lines.append("")
        lines.append(f"Best on levels: {bl.name} R2 {bl.r2:.3f}. Best on change: {bc.name} R2 {bc.r2:.3f}.")
        lines.append(
            "These two numbers answer different questions and are not comparable as a pair: "
            "the level model ranks firms by how carbon-intensive they are, the change model "
            "by whether they are reducing."
        )
        if self.level_without_sector:
            bw = self.best(self.level_without_sector)
            drop = bl.r2 - bw.r2
            share = drop / bl.r2 if bl.r2 > 0 else float("nan")
            lines.append(
                f"Shuffling sector drops the best level R2 from {bl.r2:.3f} to {bw.r2:.3f} "
                f"({share:.0%} of it). That share was sector identification, not insight into "
                "any firm's carbon management."
            )
        return "\n".join(lines)


def build_models(*, seed: int = 0) -> dict:
    """Five models spanning the families Xu et al. compare.

    Not their exact specification: they run six, including a neural network,
    and use XGBoost where this uses sklearn's gradient booster. Their feature
    set is 60 variables in four categories, which a user supplies here. The
    point of this function is the comparison design, not a replication.
    """
    return {
        "lasso": Lasso(alpha=0.001, max_iter=5000),
        "ridge": Ridge(alpha=1.0),
        "elastic_net": ElasticNet(alpha=0.001, l1_ratio=0.5, max_iter=5000),
        "random_forest": RandomForestRegressor(n_estimators=200, min_samples_leaf=3, random_state=seed, n_jobs=-1),
        "gradient_boosting": GradientBoostingRegressor(random_state=seed),
    }


def time_split_evaluate(
    frame: pd.DataFrame,
    *,
    target: str,
    features: list[str],
    split_year: int,
    time_col: str = "year",
    models: dict | None = None,
    compute_importance: bool = False,
    seed: int = 0,
) -> list[ModelScore]:
    """Fit on years <= split_year, score on years > split_year.

    Linear models are standardised; tree ensembles are not, since scaling
    does not affect them and leaving the raw units makes importances easier
    to read.
    """
    work = frame[[target, time_col, *features]].dropna()
    train = work[work[time_col] <= split_year]
    test = work[work[time_col] > split_year]
    if len(train) < 50 or len(test) < 20:
        raise ValueError(f"insufficient data: {len(train)} train, {len(test)} test rows")

    x_tr, y_tr = train[features].to_numpy(float), train[target].to_numpy(float)
    x_te, y_te = test[features].to_numpy(float), test[target].to_numpy(float)

    scaler = StandardScaler().fit(x_tr)
    x_tr_s, x_te_s = scaler.transform(x_tr), scaler.transform(x_te)

    out: list[ModelScore] = []
    for name, model in (models or build_models(seed=seed)).items():
        linear = name in {"lasso", "ridge", "elastic_net"}
        a, b = (x_tr_s, x_te_s) if linear else (x_tr, x_te)
        model.fit(a, y_tr)
        pred = model.predict(b)
        imp = None
        if compute_importance and not linear:
            r = permutation_importance(model, b, y_te, n_repeats=5, random_state=seed, n_jobs=-1)
            imp = pd.Series(r.importances_mean, index=features).sort_values(ascending=False)
        out.append(
            ModelScore(
                name=name,
                r2=float(r2_score(y_te, pred)),
                rmse=float(root_mean_squared_error(y_te, pred)),
                n_train=len(train),
                n_test=len(test),
                importances=imp,
            )
        )
    return out


def compare_targets(
    frame: pd.DataFrame,
    *,
    features: list[str],
    level_target: str = "intensity",
    change_target: str = "g_scope12",
    split_year: int | None = None,
    time_col: str = "year",
    sector_col: str = "sector",
    shuffle_sector: bool = True,
    seed: int = 0,
) -> TargetComparison:
    """Same features, same split, two targets: a level and a change.

    The gap between the two columns is the point of the exercise.
    """
    years = sorted(frame[time_col].dropna().unique())
    split = split_year if split_year is not None else years[int(len(years) * 0.7)]

    level = time_split_evaluate(
        frame, target=level_target, features=features, split_year=split, time_col=time_col, seed=seed
    )
    change = time_split_evaluate(
        frame, target=change_target, features=features, split_year=split, time_col=time_col, seed=seed
    )

    without = []
    if shuffle_sector and sector_col in frame.columns:
        rng = np.random.default_rng(seed)
        shuffled = frame.copy()
        sector_features = [f for f in features if f.startswith("sector_")]
        if sector_features:
            idx = rng.permutation(len(shuffled))
            for f in sector_features:
                shuffled[f] = shuffled[f].to_numpy()[idx]
            without = time_split_evaluate(
                shuffled, target=level_target, features=features, split_year=split, time_col=time_col, seed=seed
            )

    return TargetComparison(level=level, change=change, level_without_sector=without)

"""`comparison_table` (mockup 5): text columns left, numbers right in mono; an optional total row (sum or mean)."""

from statistics import fmean

from arp.reporting.render_model import VISUALS, TablePrim, VisualDataError
from arp.reporting.visuals._common import dataset, number, signed

ROW_H, MAX_ROWS = 72, 8


def _is_number(v: object) -> bool:
    try:
        number(v)
    except VisualDataError:
        return False
    return True


def _written(v: object) -> str:
    return "" if v is None else str(v)


def render(visual, box, ctx):
    spec = visual.table
    ds = dataset(ctx, spec.dataset_id, spec.columns)
    cols = spec.columns or ds.column_names()
    shown = ds.rows[spec.row_offset:spec.row_offset + min(spec.max_rows, MAX_ROWS)]
    raw = [[r.get(col) for col in cols] for r in shown]
    numeric = [bool(raw) and all(_is_number(row[j]) for row in raw) for j in range(len(cols))]
    rows = [[signed(_written(v)) if numeric[j] else _written(v) for j, v in enumerate(row)] for row in raw]
    total = None
    if any(visual.total_row.get(col, "none") != "none" for col in cols):
        total = []
        for j, col in enumerate(cols):
            how = visual.total_row.get(col, "none")
            if how == "none":
                total.append("")
                continue
            if not numeric[j]:
                raise VisualDataError(f"a {how} of the non-numeric column {col!r}")
            values = [number(row[j]) for row in raw]
            if how == "sum":  # as many decimals as the most precise value as written
                dec = max(len(_written(row[j]).partition(".")[2]) for row in raw)
                total.append(signed(f"{sum(values):.{dec}f}"))
            else:
                total.append(signed(f"{fmean(values):.1f}"))
        if not numeric[0] and not total[0]:
            total[0] = "Total"
    n = 1 + len(rows) + (total is not None)
    rh = min(ROW_H, box.h / n)
    hl = cols.index(visual.highlight_column) if visual.highlight_column in cols else None
    return [TablePrim("table", box.x, box.y, box.w, rh * n, list(cols), rows, total, hl, {},
                      align=["right" if x else "left" for x in numeric], mono=list(numeric))]


VISUALS["comparison_table"] = render

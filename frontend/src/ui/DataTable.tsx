import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Button } from "./Button";
import { StateBlock } from "./StateBlock";

export interface Column<Row> {
  id: string;
  header: ReactNode;
  /** Numbers go right and get tabular figures, so digits line up. */
  align?: "left" | "right";
  /** Return a sort key to make the column sortable; omit for unsortable. */
  sortValue?: (row: Row) => string | number | null | undefined;
  render: (row: Row) => ReactNode;
}

interface DataTableProps<Row> {
  columns: Column<Row>[];
  rows: Row[];
  getKey: (row: Row) => string;
  /** What this table lists, for screen readers. */
  label: string;
  onRowClick?: (row: Row) => void;
  empty?: ReactNode;
  /** Rows rendered before the "show all" control. */
  pageSize?: number;
}

type SortState = { id: string; dir: "asc" | "desc" } | null;

/** The app's table: a sticky header, right-aligned tabular numerals, sorting
 *  where a column offers a key, and a row cap so a 5,000-row result does not
 *  put 5,000 rows in the DOM.
 *
 *  Deliberately capped rather than virtualized: several tables in this app
 *  expand a row into a detail panel, which gives rows variable height and
 *  makes windowing by row index wrong. A cap keeps every rendered row real —
 *  find-in-page, copy and screen readers all still work on what is shown. */
export function DataTable<Row>({
  columns,
  rows,
  getKey,
  label,
  onRowClick,
  empty,
  pageSize = 250,
}: DataTableProps<Row>) {
  const [sort, setSort] = useState<SortState>(null);
  const [showAll, setShowAll] = useState(false);

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const column = columns.find((c) => c.id === sort.id);
    if (!column?.sortValue) return rows;
    const direction = sort.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const av = column.sortValue!(a);
      const bv = column.sortValue!(b);
      // Missing values sort last whichever way the column is pointing.
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * direction;
      return String(av).localeCompare(String(bv)) * direction;
    });
  }, [rows, sort, columns]);

  const visible = showAll ? sorted : sorted.slice(0, pageSize);

  if (rows.length === 0) {
    return <>{empty ?? <StateBlock kind="empty" message="Nothing to show." />}</>;
  }

  function toggleSort(id: string) {
    setSort((was) => (was?.id === id ? { id, dir: was.dir === "asc" ? "desc" : "asc" } : { id, dir: "asc" }));
  }

  return (
    <>
      <div className="table-wrap">
        <table className="data-table" aria-label={label}>
          <thead>
            <tr>
              {columns.map((c) => {
                const active = sort?.id === c.id;
                return (
                  <th
                    key={c.id}
                    className={c.align === "right" ? "numeric" : undefined}
                    aria-sort={active ? (sort!.dir === "asc" ? "ascending" : "descending") : undefined}
                  >
                    {c.sortValue ? (
                      <button type="button" className="th-sort" onClick={() => toggleSort(c.id)}>
                        {c.header}
                        <span className="th-sort-marker" aria-hidden="true">
                          {active ? (sort!.dir === "asc" ? "↑" : "↓") : "↕"}
                        </span>
                      </button>
                    ) : (
                      c.header
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => (
              <tr
                key={getKey(row)}
                className={onRowClick ? "clickable-row" : undefined}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
              >
                {columns.map((c) => (
                  <td key={c.id} className={c.align === "right" ? "numeric" : undefined}>
                    {c.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!showAll && sorted.length > visible.length && (
        <p className="table-more">
          Showing {visible.length} of {sorted.length}.{" "}
          <Button variant="ghost" size="sm" onClick={() => setShowAll(true)}>
            Show all
          </Button>
        </p>
      )}
    </>
  );
}

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../api/client";
import type { ReviewableRunKind, RunManifest } from "../types";
import { Button, DataTable, Field, FilterBar, PageHeader, StateBlock } from "../ui";
import { useParam } from "../router";

const REVIEWABLE_KINDS = new Set<ReviewableRunKind>(["theme", "extraction", "financials", "identity"]);

const RUN_TYPES = [
  { id: "theme", label: "Thematic universe" },
  { id: "extraction", label: "Extraction" },
  { id: "financials", label: "Company financials" },
  { id: "discovery", label: "Discovery" },
  { id: "taxonomy_research", label: "Taxonomy Researcher" },
  { id: "calibration", label: "Calibration" },
  { id: "emerging_themes", label: "Emerging themes" },
] as const;

const RUN_STATUSES = ["running", "completed", "partially_completed", "failed", "cancelled", "pending"] as const;

function isReviewable(runType: string): runType is ReviewableRunKind {
  return REVIEWABLE_KINDS.has(runType as ReviewableRunKind);
}

interface Props {
  onOpenReview?: (kind: ReviewableRunKind, runId: string) => void;
}

export function RunHistory({ onOpenReview }: Props = {}) {
  const [runs, setRuns] = useState<RunManifest[]>([]);
  const [error, setError] = useState<string | null>(null);
  // Both filters live in the URL: a filtered history is a link, which is
  // what lets the dashboard's tiles point at the runs behind a number.
  const [filter, setFilter] = useParam("type");
  const [status, setStatus] = useParam("status");

  async function load() {
    try {
      const res = (await api.listRuns(filter || undefined)) as { runs: RunManifest[] };
      setRuns(res.runs);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  const visible = status ? runs.filter((r) => r.status === status) : runs;
  const totalCost = visible.reduce((sum, r) => sum + r.estimated_cost_usd, 0);
  const activeFilters = [
    filter && {
      id: "type",
      label: <>Type: {RUN_TYPES.find((t) => t.id === filter)?.label ?? filter}</>,
      onClear: () => setFilter(null),
    },
    status && { id: "status", label: <>Status: {status.replace("_", " ")}</>, onClear: () => setStatus(null) },
  ].filter(Boolean) as { id: string; label: ReactNode; onClear: () => void }[];

  return (
    <div className="page">
      <PageHeader
        title="Run History"
        description="Every batch run this instance has recorded, with its status, progress, flagged-item count and estimated spend. A run with flagged items links straight into the Review Queue."
      />
      <FilterBar
        active={activeFilters}
        onClearAll={() => {
          setFilter(null);
          setStatus(null);
        }}
        summary={`${visible.length} run${visible.length === 1 ? "" : "s"}, $${totalCost.toFixed(2)} estimated spend`}
      >
        <Field label="Type">
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">All</option>
            {RUN_TYPES.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Status">
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option>
            {RUN_STATUSES.map((s) => (
              <option key={s} value={s}>
                {s.replace("_", " ")}
              </option>
            ))}
          </select>
        </Field>
        <Button variant="secondary" onClick={load}>
          Refresh
        </Button>
      </FilterBar>

      {error && <StateBlock kind="error" message={error} onRetry={load} />}

      <section className="card">
        <DataTable
          label="Runs"
          rows={visible}
          getKey={(r) => r.run_id}
          empty={
            <StateBlock
              kind="empty"
              message={activeFilters.length > 0 ? "No runs match these filters." : "No runs recorded yet."}
            />
          }
          columns={[
            { id: "run_id", header: "Run ID", sortValue: (r) => r.run_id, render: (r) => r.run_id },
            { id: "type", header: "Type", sortValue: (r) => r.run_type, render: (r) => r.run_type },
            {
              id: "status",
              header: "Status",
              sortValue: (r) => r.status,
              render: (r) => <span className={`status-pill status-${r.status}`}>{r.status}</span>,
            },
            {
              id: "progress",
              header: "Progress",
              align: "right",
              sortValue: (r) => (r.company_count ? r.completed_count / r.company_count : 0),
              render: (r) => `${r.completed_count}/${r.company_count} (${r.failed_count} failed)`,
            },
            { id: "flagged", header: "Flagged", align: "right", sortValue: (r) => r.review_count, render: (r) => r.review_count },
            {
              id: "cost",
              header: "Cost",
              align: "right",
              sortValue: (r) => r.estimated_cost_usd,
              render: (r) => `$${r.estimated_cost_usd.toFixed(2)}`,
            },
            {
              id: "created",
              header: "Created",
              sortValue: (r) => r.created_at,
              render: (r) => new Date(r.created_at).toLocaleString(),
            },
            {
              id: "actions",
              header: "",
              render: (r) => (
                <>
                  <a href={api.exportRunCsvUrl(r.run_id)} target="_blank" rel="noreferrer">
                    CSV
                  </a>
                  {r.review_count > 0 && isReviewable(r.run_type) && onOpenReview && (
                    <>
                      {" "}
                      <Button variant="ghost" onClick={() => onOpenReview(r.run_type as ReviewableRunKind, r.run_id)}>
                        Review
                      </Button>
                    </>
                  )}
                </>
              ),
            },
          ]}
        />
      </section>
    </div>
  );
}

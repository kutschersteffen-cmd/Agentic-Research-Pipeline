import type { AskResponse } from "../types";
import { AggregationView } from "./ResultView";
import { BarChart } from "./BarChart";
import { SmartSearchRows } from "./SmartSearchRows";

const fmt = (v: number | null) => (v == null ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: 2 }));
const pct = (v: number) => `${v.toFixed(2)}%`; // fixed decimals so a column of weights lines up

function sourceLine(r: AskResponse): string | null {
  if (r.portfolio?.resolvable) return `Source: holdings engine · holdings as of ${String(r.portfolio.vintage.holdings_as_of ?? "—")}`;
  if (r.smart_search?.resolvable) return `Source: Data Hub lists · ${r.answered_at.slice(0, 16).replace("T", " ")} UTC`;
  if (r.transition_plan) return `Source: run ${r.transition_plan.run_id} · ${r.transition_plan.run_date.slice(0, 10)}`;
  if (r.benchmark_sectors) {
    const b = r.benchmark_sectors;
    return b.is_sample ? "Source: synthetic sample" : `Source: ${b.name} · as of ${b.check.as_of}`;
  }
  return null;
}

function TransitionPlan({ card }: { card: NonNullable<AskResponse["transition_plan"]> }) {
  const f = card.figures;
  const rows: [string, string][] = [
    ["Indicators disclosed", fmt(f.indicators_disclosed_count)],
    ["Walk disclosed", fmt(f.walk_disclosed_count)],
    ["Talk disclosed", fmt(f.talk_disclosed_count)],
    ["Walk share", f.walk_share_pct == null ? "—" : `${fmt(f.walk_share_pct)}%`],
    ["Assessment confidence", f.assessment_confidence_pct == null ? "—" : `${fmt(f.assessment_confidence_pct)}%`],
    ["Open review items", String(card.open_review_items)],
  ];
  return (
    <>
      <dl className="ask-facts">
        {rows.map(([k, v]) => (
          <div key={k}><dt>{k}</dt><dd className="mono">{v}</dd></div>
        ))}
      </dl>
      <p className="ask-links">
        <a href={`#/review/${card.run_type}/${card.run_id}`}>Open run {card.run_id} →</a>
        {card.open_review_items > 0 && <> · <a href={`#/review/${card.run_type}/${card.run_id}`}>Review the open items →</a></>}
      </p>
      {card.older_runs.length > 0 && (
        <p className="muted">
          Older assessments:{" "}
          {card.older_runs.map((o, i) => (
            <span key={o.run_id}>{i > 0 && ", "}<a href={`#/review/${card.run_type}/${o.run_id}`}>{o.run_date.slice(0, 10)}</a></span>
          ))}
        </p>
      )}
    </>
  );
}

function Benchmark({ card }: { card: NonNullable<AskResponse["benchmark_sectors"]> }) {
  const c = card.check;
  const checks: [string, string][] = [
    ["Source", c.source],
    ["As of", c.as_of ?? "—"],
    ["Constituents", String(c.constituents)],
    ["Dropped lines", String(c.dropped)],
    ["Unclassified weight", pct(c.unclassified_pct)],
    ["Total weight", pct(c.total_pct)],
  ];
  return (
    <>
      <dl className="ask-facts" aria-label="Data check">
        {checks.map(([k, v]) => (
          <div key={k}><dt>{k}</dt><dd className="mono">{v}</dd></div>
        ))}
      </dl>
      <BarChart data={card.sectors.map((s) => ({ label: s.sector, value: s.weight_pct }))} valueFormatter={pct} />
      <div className="table-wrap">
        <table className="data-table">
          <thead><tr><th>Sector</th><th className="num">Weight</th></tr></thead>
          <tbody>
            {card.sectors.map((s) => (
              <tr key={s.sector}><td>{s.sector}</td><td className="num mono">{pct(s.weight_pct)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

/** One Ask ARP answer: its text first, then what code computed, then where it came from. */
export function AskCard({ response: r }: { response: AskResponse }) {
  const source = sourceLine(r);
  const spec = r.portfolio?.resolvable ? r.portfolio.spec : null;
  return (
    <div className="ask-card">
      <p className="ask-answer">{r.answer_text}</p>
      {spec && (
        <p className="muted">
          Filters: {Object.entries(spec.security_filter).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(", ") || "none"}
          {" · "}portfolios {spec.portfolio_filter.join(", ") || "all"}
        </p>
      )}
      {r.portfolio?.resolvable && r.portfolio.result && <AggregationView result={r.portfolio.result} />}
      {r.smart_search?.resolvable && <SmartSearchRows answer={r.smart_search} />}
      {r.transition_plan && <TransitionPlan card={r.transition_plan} />}
      {r.benchmark_sectors && <Benchmark card={r.benchmark_sectors} />}
      {source && <p className="ask-source">{source}</p>}
    </div>
  );
}

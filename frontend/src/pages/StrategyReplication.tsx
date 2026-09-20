import { useState } from "react";
import { api } from "../api/client";
import { LineChart, type LineSeries } from "../components/LineChart";
import { BarChart, type BarDatum } from "../components/BarChart";
import type {
  BacktestResult,
  PaperCandidate,
  ReplicationRunDetail,
  SpecReviewState,
  StrategySpec,
} from "../types";
import { Button, Field, PageHeader, StateBlock } from "../ui";

// ---- helpers ----------------------------------------------------------------

/** Display-only cumulative-return index (100 x prod(1+r)), computed client
 * side purely for the chart -- the real Sharpe/return/t-stat numbers always
 * come from the backend's LegPerformance, never recomputed here. */
function cumulativeIndex(periods: BacktestResult["periods"], field: "long_return_pct" | "short_return_pct" | "long_short_return_pct"): number[] {
  let level = 100;
  return periods.map((p) => {
    level = level * (1 + p[field] / 100);
    return level;
  });
}

/** Drawdown DEPTH (always >= 0, 0 = at a new high) rather than signed
 * drawdown -- LineChart assumes a non-negative 0-based magnitude scale
 * (every other caller only ever charts positive metrics like WACI or
 * emissions); feeding it negative values breaks its y-axis scaling
 * entirely. A bigger depth number still reads as "worse", same as a
 * signed drawdown would, just flipped to fit the chart's actual scale. */
function drawdownDepthSeries(index: number[]): number[] {
  let runningMax = -Infinity;
  return index.map((v) => {
    runningMax = Math.max(runningMax, v);
    return (1 - v / runningMax) * 100;
  });
}

function pct(v: number | null | undefined, digits = 2): string {
  return v == null ? "—" : `${v.toFixed(digits)}%`;
}

function num(v: number | null | undefined, digits = 2): string {
  return v == null ? "—" : v.toFixed(digits);
}

const VERDICT_LABEL: Record<string, string> = {
  replicated: "Replicated",
  partially_replicated: "Partially replicated",
  not_replicated: "Not replicated",
  decayed_out_of_sample: "Decayed out-of-sample",
  insufficient_data: "Insufficient data",
};

function VerdictPill({ verdict }: { verdict: string }) {
  const cls = verdict === "replicated" ? "badge badge-high" : verdict === "not_replicated" ? "badge badge-low" : "badge badge-mid";
  return <span className={cls}>{VERDICT_LABEL[verdict] ?? verdict}</span>;
}

// ---- Stage 1: Propose -------------------------------------------------------

function ProposeStage({
  onSpecCreated,
  onSpecLoaded,
}: {
  onSpecCreated: (specRunId: string, spec: StrategySpec) => void;
  onSpecLoaded: (state: SpecReviewState) => void;
}) {
  const [topic, setTopic] = useState("");
  const [candidates, setCandidates] = useState<PaperCandidate[]>([]);
  const [paperCitation, setPaperCitation] = useState("");
  const [paperText, setPaperText] = useState("");
  const [resumeId, setResumeId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function resumeDraft() {
    if (!resumeId.trim()) return;
    setBusy(true);
    setError(null);
    try {
      onSpecLoaded(await api.getSpecDraft(resumeId.trim()));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function discover() {
    if (!topic.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.discoverReplicationPapers(topic);
      setCandidates(res.candidates);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function selectCandidate(c: PaperCandidate) {
    setPaperCitation(c.title);
    setPaperText(`${c.title}\n${c.url}\n\n${c.snippet}\n\n(Paste the paper's own methodology/results text here before drafting a spec.)`);
  }

  async function draftSpec() {
    if (!paperCitation.trim() || !paperText.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.createSpecDraft(paperCitation, paperText);
      onSpecCreated(res.spec_run_id, res.spec);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <h3>1. Propose a strategy</h3>
      <p className="help-text">
        Search for candidate "outperformance" papers on a topic, or skip straight to describing your own methodology
        in plain English below -- both ways feed the same drafting step, which produces a spec sheet you review
        before anything runs.
      </p>

      <span className="field-label">Search a topic (optional)</span>
      <div className="toolbar">
        <input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="e.g. momentum anomaly" />
        <Button onClick={discover} disabled={busy || !topic.trim()}>
          Search
        </Button>
      </div>

      <span className="field-label">...or resume a spec draft you started earlier</span>
      <div className="toolbar">
        <input value={resumeId} onChange={(e) => setResumeId(e.target.value)} placeholder="spec draft run ID" />
        <Button onClick={resumeDraft} disabled={busy || !resumeId.trim()}>
          Resume
        </Button>
      </div>

      {candidates.length > 0 && (
        <div className="review-item-list">
          {candidates.map((c) => (
            <div className="review-item" key={c.candidate_id}>
              <strong>{c.title}</strong>{" "}
              {c.replication_worthiness_score != null && <span className="badge badge-mid">{Math.round(c.replication_worthiness_score * 100)}%</span>}
              <p className="muted">{c.snippet}</p>
              {c.worthiness_reasoning && <p className="muted">{c.worthiness_reasoning}</p>}
              <div className="toolbar">
                <a href={c.url} target="_blank" rel="noreferrer">
                  View source
                </a>
                <Button onClick={() => selectCandidate(c)}>Use this paper</Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <Field label="Paper citation">
        <input value={paperCitation} onChange={(e) => setPaperCitation(e.target.value)} placeholder="Author (Year), Journal Vol(Issue)" />
      </Field>

      <Field label="Paper text, or describe your own methodology">
        <textarea
          rows={8}
          value={paperText}
          onChange={(e) => setPaperText(e.target.value)}
          placeholder="Paste the paper's methodology/results text, or write your own strategy description in plain English (e.g. 'Rank stocks by 6-month prior return, buy the top decile, short the bottom decile, hold for 3 months, rebalance monthly.')"
        />
      </Field>
      <Button onClick={draftSpec} disabled={busy || !paperCitation.trim() || !paperText.trim()}>
        Draft spec sheet
      </Button>
      {error && <StateBlock kind="error" message={error} />}
    </section>
  );
}

// ---- Stage 2: Review spec ---------------------------------------------------

function ReviewStage({
  specRunId,
  state,
  onRefresh,
  onApproved,
}: {
  specRunId: string;
  state: SpecReviewState;
  onRefresh: (state: SpecReviewState) => void;
  onApproved: () => void;
}) {
  const [jsonDraft, setJsonDraft] = useState(() => JSON.stringify(state.spec, null, 2));
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    const fresh = await api.getSpecDraft(specRunId);
    onRefresh(fresh);
    setJsonDraft(JSON.stringify(fresh.spec, null, 2));
  }

  async function saveDirectEdit() {
    setBusy(true);
    setError(null);
    try {
      const parsed = JSON.parse(jsonDraft) as StrategySpec;
      await api.updateSpecDraft(specRunId, parsed);
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function reviseWithInstruction() {
    if (!instruction.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.reviseSpecDraft(specRunId, instruction);
      await refresh();
      setInstruction("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function approve() {
    setBusy(true);
    setError(null);
    try {
      await api.approveSpecDraft(specRunId);
      await refresh();
      onApproved();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const spec = state.spec;

  return (
    <section className="card">
      <div className="section-heading">
        <h3>2. Review the spec sheet</h3>
        {state.approved ? <span className="badge badge-high">Approved</span> : <span className="badge badge-mid">Needs approval</span>}
      </div>
      <p className="help-text">
        {spec.strategy_name} -- {spec.signal_type}, {spec.holding_period_months}-month holding period,
        {" "}{spec.num_portfolios} portfolios (long #{spec.long_leg_portfolio} / short #{spec.short_leg_portfolio}),
        {" "}{spec.rebalance_frequency} rebalance. Grounded: {spec.grounded ? "yes" : "no"} (confidence {Math.round(spec.confidence * 100)}%).
        {!spec.grounded && " Any manually edited or instruction-revised field is no longer grounded against source text -- review it carefully before approving."}
      </p>

      <span className="field-label">Give an instruction in natural language</span>
      <div className="toolbar">
        <input
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          placeholder="e.g. switch to quarterly rebalancing"
          className="grow"
        />
        <Button onClick={reviseWithInstruction} disabled={busy || !instruction.trim()}>
          Apply instruction
        </Button>
      </div>

      <Field label="Or edit the spec sheet directly">
        <textarea rows={16} className="review-json-edit" value={jsonDraft} onChange={(e) => setJsonDraft(e.target.value)} />
      </Field>
      <div className="toolbar">
        <Button onClick={saveDirectEdit} disabled={busy}>
          Save direct edit
        </Button>
        <Button onClick={approve} disabled={busy} className="push">
          Approve spec
        </Button>
      </div>
      {error && <StateBlock kind="error" message={error} />}

      {state.history.length > 0 && (
        <>
          <h4>Revision history</h4>
          <table className="data-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Decision</th>
                <th>Note</th>
              </tr>
            </thead>
            <tbody>
              {state.history.map((h, i) => (
                <tr key={i}>
                  <td>{h.decided_at}</td>
                  <td>{h.decision}</td>
                  <td>{h.comment ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}

// ---- Stage 3: Backtest & results --------------------------------------------

function BacktestStage({ specRunId, spec }: { specRunId: string; spec: StrategySpec }) {
  const [tickers, setTickers] = useState("");
  const [pricesRef, setPricesRef] = useState<string | null>(null);
  const [characteristicsRef, setCharacteristicsRef] = useState<string | null>(null);
  const [benchmark, setBenchmark] = useState("");
  const [oosStart, setOosStart] = useState("");
  const [oosEnd, setOosEnd] = useState("");
  const [runId, setRunId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ReplicationRunDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const tickerList = tickers.split(/[\s,]+/).map((t) => t.trim()).filter(Boolean);

  async function uploadPrices(file: File) {
    const res = await api.uploadPriceDataset(specRunId, file);
    setPricesRef(res.ref);
  }

  async function uploadCharacteristics(file: File) {
    if (!spec.characteristic_name) return;
    const res = await api.uploadCharacteristicsDataset(specRunId, spec.characteristic_name, file);
    setCharacteristicsRef(res.ref);
  }

  async function runBacktest() {
    if (!pricesRef || tickerList.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.runReplicationBacktest(specRunId, {
        tickers: tickerList,
        prices_ref: pricesRef,
        characteristics_refs: characteristicsRef && spec.characteristic_name ? { [spec.characteristic_name]: characteristicsRef } : undefined,
        benchmark: benchmark.trim() || undefined,
        out_of_sample_start: oosStart || undefined,
        out_of_sample_end: oosEnd || undefined,
      });
      setRunId(res.run_id);
      const fresh = await api.getReplicationRunDetail(res.run_id);
      setDetail(fresh);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function refreshDetail() {
    if (!runId) return;
    setDetail(await api.getReplicationRunDetail(runId));
  }

  async function runSanityCheck() {
    if (!runId) return;
    setBusy(true);
    setError(null);
    try {
      await api.runReplicationSanityCheck(runId);
      await refreshDetail();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function runRegimeReport() {
    if (!runId) return;
    setBusy(true);
    setError(null);
    try {
      await api.runReplicationRegimeReport(runId);
      await refreshDetail();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <h3>3. Run the backtest &amp; review results</h3>

      <Field label="Tickers (comma or newline separated)">
        <textarea rows={3} value={tickers} onChange={(e) => setTickers(e.target.value)} placeholder="AAPL, MSFT, ..." />
      </Field>

      <Field label="Price panel CSV (date column + one column per ticker)">
        <input type="file" accept=".csv" onChange={(e) => e.target.files?.[0] && uploadPrices(e.target.files[0])} />
      </Field>
      {pricesRef && <p className="muted">Uploaded.</p>}

      {spec.characteristic_name && (
        <>
          <Field label={<>{spec.characteristic_name} characteristics CSV</>}>
            <input type="file" accept=".csv" onChange={(e) => e.target.files?.[0] && uploadCharacteristics(e.target.files[0])} />
          </Field>
          {characteristicsRef && <p className="muted">Uploaded.</p>}
        </>
      )}

      <div className="toolbar">
        <input value={benchmark} onChange={(e) => setBenchmark(e.target.value)} placeholder="Benchmark ticker (optional)" />
        <input value={oosStart} onChange={(e) => setOosStart(e.target.value)} placeholder="Out-of-sample start (optional)" />
        <input value={oosEnd} onChange={(e) => setOosEnd(e.target.value)} placeholder="Out-of-sample end (optional)" />
      </div>
      <Button onClick={runBacktest} disabled={busy || !pricesRef || tickerList.length === 0}>
        Run backtest
      </Button>
      {error && <StateBlock kind="error" message={error} />}

      {detail && <ResultsView detail={detail} busy={busy} onRunSanityCheck={runSanityCheck} onRunRegimeReport={runRegimeReport} />}
    </section>
  );
}

function ResultsView({
  detail,
  busy,
  onRunSanityCheck,
  onRunRegimeReport,
}: {
  detail: ReplicationRunDetail;
  busy: boolean;
  onRunSanityCheck: () => void;
  onRunRegimeReport: () => void;
}) {
  const ls = detail.in_sample.long_short;
  const reportedLs = detail.comparison.reported_performance.long_short;
  const dates = detail.in_sample.periods.map((p) => p.period_end);
  const equitySeries: LineSeries[] = [
    { label: "Long", values: cumulativeIndex(detail.in_sample.periods, "long_return_pct") },
    { label: "Short", values: cumulativeIndex(detail.in_sample.periods, "short_return_pct") },
    { label: "Long-short", values: cumulativeIndex(detail.in_sample.periods, "long_short_return_pct") },
  ];
  const drawdownData: LineSeries[] = [
    { label: "Long-short drawdown depth", values: drawdownDepthSeries(cumulativeIndex(detail.in_sample.periods, "long_short_return_pct")) },
  ];

  return (
    <div>
      <div className="dashboard-grid">
        <div className="stat-tile">
          <span className="stat-value">
            <VerdictPill verdict={detail.comparison.verdict} />
          </span>
          <span className="stat-label">Verdict</span>
        </div>
        <div className="stat-tile">
          <span className="stat-value">{pct(ls.annualized_return_pct)}</span>
          <span className="stat-label">In-sample annualized return</span>
        </div>
        <div className="stat-tile">
          <span className="stat-value">{num(ls.sharpe_ratio)}</span>
          <span className="stat-label">In-sample Sharpe</span>
        </div>
        <div className="stat-tile">
          <span className="stat-value">{num(ls.t_stat)}</span>
          <span className="stat-label">t-stat</span>
        </div>
        <div className="stat-tile">
          <span className="stat-value">{pct(detail.comparison.in_sample_return_gap_pp)}</span>
          <span className="stat-label">Gap vs. paper (pp)</span>
        </div>
        {detail.comparison.deflated_sharpe && (
          <div className="stat-tile">
            <span className="stat-value">{num(detail.comparison.deflated_sharpe.deflated_sharpe_ratio)}</span>
            <span className="stat-label">Deflated Sharpe Ratio ({detail.comparison.deflated_sharpe.n_trials} trial(s))</span>
          </div>
        )}
      </div>
      <p className="muted">{detail.comparison.verdict_notes}</p>

      <h4>Equity curve (in-sample, display index = 100)</h4>
      <LineChart dates={dates} series={equitySeries} />

      <h4>Drawdown depth (long-short, 0 = at a new high)</h4>
      <LineChart dates={dates} series={drawdownData} valueFormatter={(v) => `${v.toFixed(1)}%`} />

      <h4>Reported vs. measured (long-short)</h4>
      <table className="data-table">
        <thead>
          <tr>
            <th></th>
            <th>Paper reported</th>
            <th>Replication (in-sample)</th>
            {detail.out_of_sample && <th>Replication (out-of-sample)</th>}
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Annualized return</td>
            <td>{pct(reportedLs.annualized_return_pct)}</td>
            <td>{pct(ls.annualized_return_pct)}</td>
            {detail.out_of_sample && <td>{pct(detail.out_of_sample.long_short.annualized_return_pct)}</td>}
          </tr>
          <tr>
            <td>Sharpe ratio</td>
            <td>{num(reportedLs.sharpe_ratio)}</td>
            <td>{num(ls.sharpe_ratio)}</td>
            {detail.out_of_sample && <td>{num(detail.out_of_sample.long_short.sharpe_ratio)}</td>}
          </tr>
          <tr>
            <td>t-stat</td>
            <td>{num(reportedLs.t_stat)}</td>
            <td>{num(ls.t_stat)}</td>
            {detail.out_of_sample && <td>{num(detail.out_of_sample.long_short.t_stat)}</td>}
          </tr>
        </tbody>
      </table>

      <div className="section-heading">
        <h4>Sanity check</h4>
        <Button onClick={onRunSanityCheck} disabled={busy}>
          {detail.sanity_check ? "Re-run sanity check" : "Run sanity check"}
        </Button>
      </div>
      {detail.sanity_check ? (
        <div>
          <p>
            <span className={detail.sanity_check.plausible ? "badge badge-high" : "badge badge-low"}>
              {detail.sanity_check.plausible ? "plausible" : "suspicious"}
            </span>{" "}
            {detail.sanity_check.summary}
          </p>
          {detail.sanity_check.findings.map((f, i) => (
            <p key={i} className="muted">
              [{f.concern}] {f.explanation}
            </p>
          ))}
        </div>
      ) : (
        <p className="muted">Not run yet -- an LLM second opinion on whether these figures look plausible.</p>
      )}

      <div className="section-heading">
        <h4>Regime breakdown</h4>
        <Button onClick={onRunRegimeReport} disabled={busy}>
          {detail.regime_report ? "Re-run regime report" : "Run regime report"}
        </Button>
      </div>
      {detail.regime_report ? (
        detail.regime_report.buckets.length > 0 ? (
          <BarChart
            data={detail.regime_report.buckets.map(
              (b): BarDatum => ({ label: `${b.regime.replace("_volatility", "")} vol (${b.num_periods}p)`, value: b.long_short.annualized_return_pct ?? 0 })
            )}
            valueFormatter={(v) => `${v.toFixed(1)}%`}
          />
        ) : (
          <p className="muted">{detail.regime_report.notes}</p>
        )
      ) : (
        <p className="muted">Not run yet -- breaks performance out by low/mid/high benchmark-volatility regime.</p>
      )}
      <p className="muted">
        Charts are long/short/long-short leg-level only -- the backtest engine doesn't retain per-decile-portfolio
        returns, so a per-decile breakdown isn't available.
      </p>
    </div>
  );
}

// ---- Page --------------------------------------------------------------------

export function StrategyReplication() {
  const [specRunId, setSpecRunId] = useState<string | null>(null);
  const [specState, setSpecState] = useState<SpecReviewState | null>(null);

  function onSpecCreated(id: string, spec: StrategySpec) {
    setSpecRunId(id);
    setSpecState({ spec_run_id: id, spec, approved: false, history: [] });
  }

  function onSpecLoaded(state: SpecReviewState) {
    setSpecRunId(state.spec_run_id);
    setSpecState(state);
  }

  return (
    <div className="page">
      <PageHeader
        title="Investment Strategy Replication"
        description={
          <>
            Propose a strategy (from a paper or your own description), review and approve the spec sheet it produces,
            then backtest it and analyze the results -- nothing runs against real data until you explicitly approve the
            spec.
          </>
        }
      />

      <ProposeStage onSpecCreated={onSpecCreated} onSpecLoaded={onSpecLoaded} />

      {specState && (
        <ReviewStage
          specRunId={specRunId as string}
          state={specState}
          onRefresh={setSpecState}
          onApproved={() => {}}
        />
      )}

      {specState?.approved && <BacktestStage specRunId={specRunId as string} spec={specState.spec} />}
    </div>
  );
}

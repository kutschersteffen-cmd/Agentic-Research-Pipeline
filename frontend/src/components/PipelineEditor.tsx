import { useCallback, useEffect, useMemo, useState, type ReactElement } from "react";
import ReactFlow, { Controls, Handle, MarkerType, Position, type Edge, type Node, type NodeProps } from "reactflow";
import "reactflow/dist/style.css";
import { api } from "../api/client";
import { COARSE_POINTER, layoutPipeline } from "../lib/pipelineLayout";
import type {
  ExtractionProfile,
  PipelineNode,
  PipelineShape,
  RunCompany,
  RunDecision,
  RunManifest,
  RunSteps,
  StepSettingKey,
  StepSettings,
} from "../types";

const CARD_W = 214;
const PILL_W = 170;
const COL_W = CARD_W + 64;
const ROW_H = 210;

type Value = StepSettings[StepSettingKey];
type Status = "idle" | "pending" | "running" | "done" | "skipped" | "failed";

const ICON = { width: 15, height: 15, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.9, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
const STEP_ICONS: Record<string, ReactElement> = {
  gather_evidence: (
    <svg {...ICON}>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="M15.3 15.3 20.5 20.5" />
    </svg>
  ),
  extract: (
    <svg {...ICON}>
      <path d="M4 20h4L19 9l-4-4L4 16z" />
      <path d="m13.5 6.5 4 4" />
    </svg>
  ),
  verify: (
    <svg {...ICON}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="m8.5 12 2.5 2.5 4.5-5" />
    </svg>
  ),
  aggregate: (
    <svg {...ICON}>
      <path d="M12 3 4.5 6v5.5c0 4.5 3.2 8 7.5 9.5 4.3-1.5 7.5-5 7.5-9.5V6z" />
    </svg>
  ),
  company: (
    <svg {...ICON}>
      <path d="m12 3 9 5-9 5-9-5z" />
      <path d="m3 13 9 5 9-5" />
    </svg>
  ),
  rules: (
    <svg {...ICON}>
      <path d="M12 4v16M6 20h12M4 8h16M6 8l-3 6a3 3 0 0 0 6 0zM18 8l-3 6a3 3 0 0 0 6 0z" />
    </svg>
  ),
  finalize: (
    <svg {...ICON}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M8.5 12h7" />
    </svg>
  ),
};
STEP_ICONS.answer = STEP_ICONS.extract;
STEP_ICONS.identity = (
  <svg {...ICON}>
    <rect x="3" y="5" width="18" height="14" rx="2" />
    <circle cx="9" cy="11" r="2.2" />
    <path d="M5.8 16c.6-1.6 1.8-2.4 3.2-2.4s2.6.8 3.2 2.4M14.5 10h4M14.5 13.5h3" />
  </svg>
);
STEP_ICONS.content_search = (
  <svg {...ICON}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M3.5 12h17M12 3.5c2.4 2.4 3.5 5.2 3.5 8.5s-1.1 6.1-3.5 8.5c-2.4-2.4-3.5-5.2-3.5-8.5S9.6 5.9 12 3.5z" />
  </svg>
);
STEP_ICONS.document_mgmt = (
  <svg {...ICON}>
    <path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z" />
  </svg>
);
STEP_ICONS.parse_index = (
  <svg {...ICON}>
    <path d="M6 3.5h8l4 4v13H6z" />
    <path d="M9 11h6M9 14.5h6M9 18h4" />
  </svg>
);

const iconFor = (id: string) => STEP_ICONS[id] ?? (id.startsWith("finalize") ? STEP_ICONS.finalize : null);

function show(value: Value): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "on" : "off";
  return String(value);
}

function duration(seconds: number): string {
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 90) return `${seconds.toFixed(1)} s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

type Row = { label: string; value: string; changed?: boolean };

type CardData = {
  kind: "card" | "pill";
  id: string;
  label: string;
  about: string;
  rows: Row[];
  banner: { text: string; tone: "good" | "bad" | "neutral" } | null;
  footer: string | null;
  share: number | null;
  status: Status;
  selected: boolean;
  onSelect: (id: string) => void;
};

function StepCard({ data }: NodeProps<CardData>) {
  if (data.kind === "pill") {
    return (
      <>
        <Handle type="target" position={Position.Left} />
        <button className={`pipeline-pill status-${data.status}${data.selected ? " selected" : ""}`} style={{ width: PILL_W }} onClick={() => data.onSelect(data.id)}>
          <span className="pipeline-pill-label">{data.label}</span>
          {data.footer && <span className="pipeline-pill-sub">{data.footer}</span>}
        </button>
        <Handle type="source" position={Position.Right} />
      </>
    );
  }
  return (
    <>
      <Handle type="target" position={Position.Left} />
      <button
        className={`pipeline-card status-${data.status}${data.selected ? " selected" : ""}${data.id.startsWith("finalize") ? " exit" : ""}`}
        style={{ width: CARD_W }}
        onClick={() => data.onSelect(data.id)}
        aria-pressed={data.selected}
      >
        <span className="pipeline-card-head">
          <span className="pipeline-card-icon" aria-hidden>
            {iconFor(data.id)}
          </span>
          <span className="pipeline-card-title">{data.label}</span>
          {data.status === "running" && <span className="pipeline-card-spinner" aria-label="running" />}
        </span>
        {data.banner && <span className={`pipeline-card-banner ${data.banner.tone}`}>{data.banner.text}</span>}
        {data.rows.length === 0 && data.about && <span className="pipeline-card-about">{data.about}</span>}
        {data.rows.length > 0 && (
          <span className="pipeline-card-rows">
            {data.rows.map((r) => (
              <span key={r.label} className={`pipeline-card-row${r.changed ? " changed" : ""}`}>
                <span>{r.label}</span>
                <span>{r.value}</span>
              </span>
            ))}
          </span>
        )}
        {data.share !== null && (
          <span className="pipeline-card-bar" aria-hidden>
            <span style={{ transform: `scaleX(${data.share})` }} />
          </span>
        )}
        {data.footer && <span className="pipeline-card-footer">{data.footer}</span>}
      </button>
      <Handle type="source" position={Position.Right} />
    </>
  );
}

const NODE_TYPES = { step: StepCard };

interface Props {
  profile: ExtractionProfile;
  /** Edit mode: the run's overrides, changed through `onChange`. */
  value?: StepSettings;
  onChange?: (next: StepSettings) => void;
  /** Run mode: counts, times and status per step, with stop and restart. */
  runId?: string;
  /** A restart started a new run: the screen follows it. */
  onRestarted?: (runId: string) => void;
}

/** A profile's pipeline, start to end, as a node diagram. Before a run,
 * clicking a step edits its settings for that run. During and after one,
 * each step shows how many items went through it and how long they took --
 * for the whole run or one company -- and can stop the run or restart it
 * from that step. */
export function PipelineEditor({ profile, value = {}, onChange, runId, onRestarted }: Props) {
  const [shape, setShape] = useState<PipelineShape | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [steps, setSteps] = useState<RunSteps | null>(null);
  const [manifest, setManifest] = useState<RunManifest | null>(null);
  const [decision, setDecision] = useState<RunDecision | null>(null);
  const [companies, setCompanies] = useState<RunCompany[]>([]);
  const [companyId, setCompanyId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    setShape(null);
    setSelected(null);
    api.getExtractionPipeline(profile).then(setShape).catch((e: Error) => setError(e.message));
  }, [profile]);

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!runId) return;
    let timer: number | undefined;
    let stopped = false;
    async function poll() {
      try {
        const [s, m, c] = await Promise.all([
          api.getRunSteps(runId!, companyId),
          api.getRun(runId!) as Promise<RunManifest>,
          api.getRunCompanies(runId!),
        ]);
        if (stopped) return;
        setSteps(s);
        setManifest(m);
        setCompanies(c.companies);
        const running = s.live || m.status === "running" || m.status === "pending";
        if (running) timer = window.setTimeout(poll, 2500);
        else setDecision(await api.getRunDecision(runId!).catch(() => null));
      } catch (e) {
        if (!stopped) setError((e as Error).message);
      }
    }
    poll();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [runId, companyId, tick]);

  const running = !!runId && (!!steps?.live || manifest?.status === "running" || manifest?.status === "pending");
  const company = companies.find((c) => c.company_id === companyId) ?? null;

  const effective = (key: StepSettingKey): Value => {
    if (runId) return steps?.settings?.[key] ?? null;
    return value[key] ?? shape?.defaults[key] ?? null;
  };

  function describe(node: PipelineNode): Omit<CardData, "kind" | "id" | "label" | "about" | "selected" | "onSelect"> {
    const settingRows: Row[] = node.settings.map((key) => ({
      label: shape!.setting_info[key].label,
      value: show(effective(key)),
      changed: runId ? effective(key) !== shape!.defaults[key] : value[key] !== undefined && value[key] !== null,
    }));
    const empty = { rows: settingRows, banner: null, footer: null, share: null };
    const on = node.optional ? !!effective(node.settings[0]) : true;
    if (!runId) return { ...empty, rows: node.optional ? [] : settingRows, footer: node.optional ? (on ? "on for this run" : "off — click to switch on") : null, status: on ? "idle" : "skipped" };
    if (!steps) return { ...empty, status: "pending" };

    const items = steps.counts.gather_evidence ?? 0;
    if (node.id === "item") return { ...empty, rows: [], footer: `${items} items`, status: running ? "running" : "done" };
    if (node.id === "start") return { ...empty, rows: [], footer: company ? company.name : manifest ? `${manifest.company_count} companies` : null, status: running ? "running" : "done" };
    if (node.optional) return describePreStep(node, on);

    if (node.id === "company") {
      if (company) {
        const stoppedAt = shape!.nodes.find((n) => n.optional && steps.details[n.id]?.failed);
        const status: Status = company.status === "done" ? "done" : company.status === "failed" || company.status === "review" ? "failed" : running ? "running" : "skipped";
        const banner =
          company.status === "review"
            ? ({ text: `Stopped at ${stoppedAt?.label ?? "a step before extraction"} — in review`, tone: "bad" } as const)
            : company.status === "failed"
              ? ({ text: "Failed — see the run's errors", tone: "bad" } as const)
              : null;
        return { rows: [], banner, footer: company.status === "review" ? "error report in the Review Queue" : company.status, share: null, status };
      }
      if (!manifest) return { ...empty, rows: [], status: "pending" };
      const done = manifest.completed_count;
      return {
        rows: [
          { label: "Companies done", value: `${done}/${manifest.company_count}` },
          { label: "Failed", value: String(manifest.failed_count) },
          { label: "In review", value: String(manifest.review_count) },
        ],
        banner: null,
        footer: null,
        share: manifest.company_count ? done / manifest.company_count : null,
        status: manifest.failed_count && !done ? "failed" : running ? "running" : done ? "done" : "skipped",
      };
    }

    if (node.id === "rules") {
      if (running) return { ...empty, rows: [], footer: "runs after the last company", status: "pending" };
      if (!decision) return { ...empty, rows: [], footer: "no framework attached", status: "skipped" };
      const r = decision.result;
      if (company) {
        const entity = r.entities.find((e) => e.name === company.name || e.entity_key === company.company_id);
        if (!entity) return { ...empty, rows: [], footer: "not in the scored table", status: "skipped" };
        const tone = entity.status !== "scored" ? "neutral" : entity.tier === 1 ? "good" : entity.tier && entity.tier >= (decision.result.tier_summary?.length ?? 4) ? "bad" : "neutral";
        return {
          rows: [
            { label: "Score", value: entity.score != null ? entity.score.toFixed(2) : "—" },
            { label: "Status", value: entity.status },
          ],
          banner: { text: entity.tier_name ?? entity.status, tone },
          footer: decision.framework.name,
          share: null,
          status: "done",
        };
      }
      return {
        rows: [
          { label: "Scored", value: String(r.scored_count) },
          { label: "Excluded", value: String(r.excluded_count) },
          { label: "Too little data", value: String(r.insufficient_count) },
        ],
        banner: null,
        footer: decision.framework.name,
        share: null,
        status: "done",
      };
    }

    const n = steps.counts[node.id] ?? 0;
    const secs = steps.seconds[node.id] ?? 0;
    const failedStep = node.id === "finalize_answer_error" && n > 0;
    if (!n && !running) return { rows: [], banner: null, footer: "not reached", share: null, status: "skipped" };
    return {
      rows: [
        { label: "Items", value: String(n) },
        ...(items && node.id !== "gather_evidence" ? [{ label: "Share", value: `${Math.round((n / items) * 100)}%` }] : []),
        ...(n ? [{ label: "Avg per item", value: duration(secs / n) }] : []),
      ],
      banner: failedStep ? { text: `${n} answer${n === 1 ? "" : "s"} failed`, tone: "bad" } : null,
      footer: n ? `${duration(secs)} in total` : null,
      share: items ? n / items : null,
      status: failedStep ? "failed" : n ? (running ? "running" : "done") : running ? "pending" : "skipped",
    };
  }

  /** A step before extraction: what it found, for one company or summed over the run. */
  function describePreStep(node: PipelineNode, on: boolean): ReturnType<typeof describe> {
    if (!on) return { rows: [], banner: null, footer: "off for this run", share: null, status: "skipped" };
    const n = steps!.counts[node.id] ?? 0;
    const secs = steps!.seconds[node.id] ?? 0;
    const found = steps!.details[node.id] ?? {};
    const num = (k: string) => Number(found[k] ?? 0);
    const text = (k: string) => (found[k] == null ? "—" : String(found[k]));
    const mb = (bytes: number) => `${(bytes / 1_048_576).toFixed(2)} MB`;
    const rows: Row[] = [];
    if (node.id === "identity") {
      if (company) rows.push({ label: "Verdict", value: text("verdict") }, { label: "Website", value: text("website") }, { label: "CIK", value: text("cik") });
      else rows.push({ label: "Resolved", value: `${num("resolved")}/${n}` }, { label: "Flagged", value: String(num("flagged")) });
    } else if (node.id === "content_search") {
      if (company) rows.push({ label: "Homepage", value: text("homepage") }, { label: "Report links", value: String(num("links")) });
      else rows.push({ label: "Homepages found", value: `${num("found_homepage")}/${n}` }, { label: "Report links", value: String(num("links")) });
    } else if (node.id === "document_mgmt") {
      rows.push(
        { label: "Documents", value: String(num("documents")) },
        { label: "Total size", value: mb(num("bytes")) },
        { label: "Downloaded", value: String(num("downloaded")) },
        { label: "New or changed", value: String(num("new_or_changed")) },
      );
    } else if (node.id === "parse_index") {
      rows.push({ label: "Documents parsed", value: String(num("documents")) }, { label: "Chunks", value: String(num("chunks")) });
    }
    const failed = num("failed");
    const total = company ? 1 : manifest?.company_count ?? 0;
    return {
      rows: n ? rows : [],
      banner: failed
        ? { text: company ? `Failed: ${text("error")}` : `${failed} ${failed === 1 ? "company" : "companies"} stopped here — in review`, tone: "bad" }
        : null,
      footer: n ? (company ? duration(secs) : `${n} companies · ${duration(secs / n)} per company`) : null,
      share: total && !company ? n / total : null,
      status: failed && (company || failed === n) ? "failed" : n ? (running ? "running" : "done") : running ? "pending" : "skipped",
    };
  }

  const { nodes, edges } = useMemo(() => {
    if (!shape) return { nodes: [] as Node<CardData>[], edges: [] as Edge[] };
    const all = { ...shape, nodes: [...shape.nodes, { id: "end", label: "End", about: "", per_item: false, settings: [] }], edges: [...shape.edges, { source: "rules", target: "end", conditional: false }] };
    const positions = layoutPipeline(all, COL_W, ROW_H);
    const nodes: Node<CardData>[] = all.nodes.map((node) => {
      const pill = node.id === "start" || node.id === "item" || node.id === "end";
      const d = describe(node);
      const pos = positions[node.id] ?? { x: 0, y: 0 };
      return {
        id: node.id,
        type: "step",
        position: pill ? { x: pos.x + (CARD_W - PILL_W) / 2, y: pos.y + 40 } : pos,
        draggable: false,
        // React Flow drops pointer events on nodes that are neither
        // selectable nor draggable; the cards are buttons, so keep them.
        style: { pointerEvents: "all" },
        data: {
          kind: pill ? "pill" : "card",
          id: node.id,
          label: node.id === "item" ? "Per item" : node.label,
          about: node.about,
          ...d,
          footer:
            node.id === "item" && !runId
              ? node.label.replace(/^For /, "for ")
              : node.id === "start" && !runId
                ? "each company"
                : node.id === "end"
                  ? runId
                    ? (manifest?.status ?? null)
                    : null
                  : d.footer,
          status: node.id === "end" ? (runId ? (running ? "pending" : "done") : "idle") : d.status,
          selected: selected === node.id,
          onSelect: (id) => setSelected(selected === id ? null : id),
        },
      };
    });
    const edges: Edge[] = all.edges.map((e) => ({
      id: `${e.source}>${e.target}`,
      source: e.source,
      target: e.target,
      animated: running,
      className: e.conditional ? "pipeline-edge conditional" : "pipeline-edge",
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
    }));
    return { nodes, edges };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shape, value, selected, steps, manifest, decision, company, runId, running]);

  if (error) return <p className="error-text" role="alert">{error}</p>;
  if (!shape) return <p className="muted">Loading the pipeline…</p>;

  const current = shape.nodes.find((n) => n.id === selected);
  const set = (key: StepSettingKey, next: Value) => {
    const copy: StepSettings = { ...value };
    if (next === null || next === undefined || next === shape.defaults[key]) delete copy[key];
    else (copy as Record<string, Value>)[key] = next;
    onChange?.(copy);
  };
  const changedCount = Object.keys(value).length;

  async function stop() {
    if (!runId) return;
    setBusy(true);
    try {
      await api.cancelRun(runId);
      setNotice("Stopping: companies already in progress finish their current step; no new ones start.");
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function restart(step: string) {
    if (!runId) return;
    setBusy(true);
    setNotice(null);
    try {
      const res = await api.restartRun(runId, { from_step: step, company_ids: company ? [company.company_id] : undefined });
      if (res.rescored) {
        setNotice("Scored again with the attached framework.");
        refresh();
      } else {
        onRestarted?.(res.run_id);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const restartable = !!steps?.restartable || current?.id === "rules";
  const scope = company ? company.name : `all ${companies.length || ""} companies`.replace("  ", " ");

  return (
    <div className="pipeline-editor">
      {runId && (
        <div className="pipeline-toolbar">
          <label className="field-label pipeline-company">
            Company
            <select value={companyId ?? ""} onChange={(e) => setCompanyId(e.target.value || null)}>
              <option value="">All companies ({companies.length})</option>
              {companies.map((c) => (
                <option key={c.company_id} value={c.company_id}>
                  {c.name} — {c.status}
                </option>
              ))}
            </select>
          </label>
          {steps?.restarted_from && (
            <span className="muted">
              Restarted from {shape.nodes.find((n) => n.id === steps.restarted_from!.step)?.label ?? steps.restarted_from.step} of run{" "}
              <code>{steps.restarted_from.run_id}</code>
            </span>
          )}
        </div>
      )}
      <div className="chart-scroll">
      {/* Touch: the canvas does not pan, so it is drawn wide enough for every step at the 0.9 zoom below and the page scrolls it sideways. */}
      <div className="flow-rf pipeline-rf" style={COARSE_POINTER ? { minWidth: Math.max(0, ...nodes.map((n) => n.position.x)) * 0.9 + CARD_W + 48 } : undefined}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          // Readable from the start: open at the left edge, full size, and pan
          // to the right (drag, or the controls) rather than shrinking the
          // whole pipeline to fit the card.
          defaultViewport={{ x: 24, y: 40, zoom: 0.9 }}
          nodesConnectable={false}
          elementsSelectable={false}
          panOnDrag={!COARSE_POINTER}
          zoomOnScroll={false}
          preventScrolling={false}
          proOptions={{ hideAttribution: true }}
          minZoom={0.3}
          maxZoom={1.4}
        >
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      </div>
      <p className="help-text">
        Drag the canvas to see every step. Dashed arrows are branches: an item takes one of them.
        {!runId && (changedCount ? ` ${changedCount} setting${changedCount === 1 ? "" : "s"} changed for this run.` : " Click a step to change its settings for this run.")}
        {!runId && changedCount > 0 && (
          <>
            {" "}
            <button className="link-button" onClick={() => onChange?.({})}>
              Reset all
            </button>
          </>
        )}
        {runId && " Click a step to stop the run or restart it from there."}
        {runId && steps && !steps.settings && " This run was started before per-run step settings, so the settings it used aren't recorded."}
      </p>
      {notice && <p className="status-text">{notice}</p>}

      {current && (
        <div className="pipeline-detail">
          <h3>{current.label}</h3>
          {current.about && <p className="help-text">{current.about}</p>}

          {runId && (
            <div className="toolbar">
              {running ? (
                <button onClick={stop} disabled={busy || !!manifest?.cancel_requested}>
                  {manifest?.cancel_requested ? "Stopping…" : "Stop run"}
                </button>
              ) : (
                <button onClick={() => restart(current.id)} disabled={busy || !restartable || (current.id === "rules" && !decision)}>
                  {current.id === "rules" ? "Score again" : `Restart from here for ${scope}`}
                </button>
              )}
              <span className="help-text">
                {running
                  ? "Stops the whole run: companies in progress finish, no new ones start. Restart from any step once it has stopped."
                  : current.id === "rules"
                    ? decision
                      ? "Applies the attached framework to this run's results again; nothing is extracted."
                      : "No framework is attached to this run."
                    : !restartable
                      ? "This run wasn't started from this screen, so its inputs aren't saved to restart from."
                      : current.id === "start" || current.optional || current.id === "item" || current.id === "gather_evidence"
                        ? "A new run: documents are fetched and parsed again, and every later step runs afresh."
                        : current.id === "extract" || current.id === "answer"
                          ? "A new run: evidence is reused; the extractor, the verifier and everything after them run afresh."
                          : current.id === "verify"
                            ? "A new run: evidence and extractor answers are reused; the verifier and everything after it run afresh."
                            : "A new run: evidence and model answers are reused from the cache; grounding and the record are rebuilt."}
              </span>
            </div>
          )}

          {current.id === "rules" && !runId && <p className="help-text">Pick the framework in &ldquo;Score the results&rdquo; below.</p>}
          {!runId && current.settings.length === 0 && current.id !== "rules" && <p className="muted">This step has no settings.</p>}
          {current.settings.map((key) => {
            const info = shape.setting_info[key];
            const v = effective(key);
            const id = `step-${key}`;
            return (
              <div key={key} className="pipeline-setting">
                <label htmlFor={id} className="field-label">
                  {info.label}
                </label>
                {runId ? (
                  <span id={id}>{show(v)}</span>
                ) : info.type === "bool" ? (
                  <input id={id} type="checkbox" checked={!!v} onChange={(e) => set(key, e.target.checked)} />
                ) : info.type === "number" ? (
                  <input id={id} type="number" min={info.min} max={info.max} step={info.step} value={v as number} onChange={(e) => set(key, e.target.value === "" ? null : Number(e.target.value))} />
                ) : (
                  <>
                    <input id={id} list={`${id}-models`} value={(v as string) ?? ""} onChange={(e) => set(key, e.target.value.trim() || null)} />
                    <datalist id={`${id}-models`}>
                      {[...new Set([shape.defaults.llm_model, shape.defaults.llm_verifier_model])].map((m) => (
                        <option key={m} value={m} />
                      ))}
                    </datalist>
                  </>
                )}
                <span className="help-text">
                  {info.help}
                  {!runId && value[key] !== undefined && (
                    <>
                      {" "}Default: {show(shape.defaults[key])}.{" "}
                      <button className="link-button" onClick={() => set(key, null)}>
                        Reset
                      </button>
                    </>
                  )}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

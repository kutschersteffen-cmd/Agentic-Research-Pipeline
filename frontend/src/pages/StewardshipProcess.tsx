import { useCallback, useEffect, useState, type CSSProperties } from "react";
import { api } from "../api/client";
import type {
  EscalationDecisionItem,
  MetricSource,
  PolicyDifferenceItem,
  StewardshipFlow,
  StewardshipStage,
  StewardshipStream,
} from "../types";

// Flowchart layout: the house row (stages 1-6) above the client row (7-8),
// as in docs/STEWARDSHIP_OPERATING_MODEL.md, Part 2.
const NODE_W = 160;
const NODE_H = 132;
const GAP = 18;
const HOUSE_Y = 56;
const CLIENT_Y = 300;
const X = (i: number) => 16 + i * (NODE_W + GAP);
const POSITIONS: Record<string, { x: number; y: number }> = {
  monitoring: { x: X(0), y: HOUSE_Y },
  selection: { x: X(1), y: HOUSE_Y },
  drafting: { x: X(2), y: HOUSE_Y },
  voting: { x: X(3), y: HOUSE_Y },
  checkpoint: { x: X(4), y: HOUSE_Y },
  tracking: { x: X(5), y: HOUSE_Y },
  client_policy: { x: X(4), y: CLIENT_Y },
  reporting: { x: X(5), y: CLIENT_Y },
};
const WIDTH = X(6) - GAP + 16;
const HEIGHT = CLIENT_Y + NODE_H + 24;

const SOURCE_LABEL: Record<MetricSource, string> = { live: "live data", sample: "synthetic sample", not_built: "not built yet" };

function edgePath(from: string, to: string): { d: string; labelAt?: { x: number; y: number } } {
  const a = POSITIONS[from];
  const b = POSITIONS[to];
  if (from === "tracking" && to === "monitoring") {
    // loop back over the top of the house row
    const y = HOUSE_Y - 26;
    return { d: `M ${a.x + NODE_W / 2} ${a.y} V ${y} H ${b.x + NODE_W / 2} V ${b.y - 6}`, labelAt: { x: (a.x + b.x + NODE_W) / 2, y: y - 6 } };
  }
  if (from === "monitoring" && to === "client_policy") {
    const y = CLIENT_Y + NODE_H / 2;
    return { d: `M ${a.x + NODE_W / 2} ${a.y + NODE_H} V ${y} H ${b.x - 6}` };
  }
  if (from === "checkpoint" && to === "client_policy") {
    return { d: `M ${a.x + NODE_W / 2 - 18} ${a.y + NODE_H} V ${b.y - 6}` };
  }
  if (from === "client_policy" && to === "checkpoint") {
    const x = a.x + NODE_W / 2 + 18;
    return { d: `M ${x} ${a.y} V ${b.y + NODE_H + 6}`, labelAt: { x: x + 6, y: (a.y + b.y + NODE_H) / 2 } };
  }
  // same row, left to right
  return { d: `M ${a.x + NODE_W} ${a.y + NODE_H / 2} H ${b.x - 6}` };
}

function StageNode({ stage, selected, onSelect, style }: { stage: StewardshipStage; selected: boolean; onSelect: (id: string) => void; style?: CSSProperties }) {
  const open = stage.decisions.filter((d) => d.kind === "escalation" || d.decision === null).length;
  return (
    <button className={`flow-node flow-${stage.layer}${selected ? " selected" : ""}`} style={style} aria-pressed={selected} onClick={() => onSelect(stage.id)}>
      <span className="flow-node-head">
        <span className="flow-node-number">{stage.number}</span>
        <span className="flow-node-title">{stage.title}</span>
      </span>
      {stage.metrics.slice(0, 3).map((m) => (
        <span key={m.label} className={`flow-node-metric tone-${m.tone}`} title={`${m.label}: ${SOURCE_LABEL[m.source]}`}>
          <span className={`source-dot source-${m.source}`} />
          <span className="flow-node-metric-label">{m.label}</span>
          <strong>{m.value}</strong>
        </span>
      ))}
      {open > 0 && <span className="flow-node-badge">{open} to decide</span>}
    </button>
  );
}

/** Narrow screens: the same stages as a stacked list, in process order. */
function FlowList({ flow, selected, onSelect }: { flow: StewardshipFlow; selected: string; onSelect: (id: string) => void }) {
  return (
    <div className="flow-list">
      {(["house", "client"] as const).map((layer) => (
        <div key={layer}>
          <p className="flow-band-label">{layer === "house" ? "House truth · stages 1–6" : "Client overlay · stages 7–8"}</p>
          {flow.stages
            .filter((s) => s.layer === layer)
            .map((stage) => (
              <StageNode key={stage.id} stage={stage} selected={stage.id === selected} onSelect={onSelect} />
            ))}
        </div>
      ))}
      <p className="muted">Tracking loops back to monitoring; client exceptions go back to the human checkpoint.</p>
    </div>
  );
}

function FlowChart({ flow, selected, onSelect }: { flow: StewardshipFlow; selected: string; onSelect: (id: string) => void }) {
  return (
    <div className="flow-scroll">
      <div className="flow-canvas" style={{ width: WIDTH, height: HEIGHT }}>
        <svg className="flow-edges" width={WIDTH} height={HEIGHT} aria-hidden="true">
          <defs>
            <marker id="flow-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto">
              <path d="M 0 0 L 10 5 L 0 10 z" className="flow-arrowhead" />
            </marker>
          </defs>
          <rect className="flow-band" x={4} y={HOUSE_Y - 44} width={WIDTH - 8} height={NODE_H + 60} rx={10} />
          <rect className="flow-band flow-band-client" x={X(4) - 12} y={CLIENT_Y - 30} width={WIDTH - X(4) + 4} height={NODE_H + 46} rx={10} />
          <text className="flow-band-label" x={X(1)} y={HOUSE_Y + NODE_H + 30}>
            House truth · stages 1–6 use house policies only
          </text>
          <text className="flow-band-label" x={X(5)} y={CLIENT_Y - 12}>
            Client overlay · stages 7–8
          </text>
          {flow.edges.map((e) => {
            const { d, labelAt } = edgePath(e.from, e.to);
            return (
              <g key={`${e.from}-${e.to}`}>
                <path d={d} className="flow-edge" markerEnd="url(#flow-arrow)" />
                {e.label && labelAt && (
                  <text className="flow-edge-label" x={labelAt.x} y={labelAt.y} textAnchor={e.from === "tracking" ? "middle" : "start"}>
                    {e.label}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
        {flow.stages.map((stage) => {
          const pos = POSITIONS[stage.id];
          return (
            <StageNode
              key={stage.id}
              stage={stage}
              selected={stage.id === selected}
              onSelect={onSelect}
              style={{ position: "absolute", left: pos.x, top: pos.y, width: NODE_W, height: NODE_H }}
            />
          );
        })}
      </div>
    </div>
  );
}

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "not set";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "object") return Object.entries(v as Record<string, unknown>).map(([k, x]) => `${k}: ${fmt(x)}`).join(", ");
  return String(v);
}

const words = (s: string) => s.replace(/_/g, " ");

function EscalationDecisions({ items, actor, onDone }: { items: EscalationDecisionItem[]; actor: string; onDone: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function escalate(item: EscalationDecisionItem) {
    if (!item.next) return;
    setBusy(item.issue_id);
    setError(null);
    try {
      await api.escalateEngagementIssue(item.company_id, item.issue_id, { stage: item.next, decided_by: actor, reason: item.reason });
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }
  return (
    <>
      {error && <p className="error-text">{error}</p>}
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Company</th>
              <th>Theme</th>
              <th>Why it is flagged</th>
              <th>Escalation step</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.issue_id}>
                <td>{item.company}</td>
                <td>{words(item.theme)}</td>
                <td>{item.reason}</td>
                <td>
                  {words(item.current)} → <strong>{item.next ? words(item.next) : "top of the ladder"}</strong>
                </td>
                <td>
                  <button
                    onClick={() => escalate(item)}
                    disabled={!actor || !item.next || busy !== null}
                    title={actor ? undefined : "Enter your name above first"}
                  >
                    {busy === item.issue_id ? "Escalating…" : "Escalate"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted">Not escalating is also a decision: log the next outreach on the Engagement page to restart the clock.</p>
    </>
  );
}

const DECISIONS_FOR: Record<string, string[]> = {
  unclear: ["clarify", "decline"],
  unmapped: ["clarify", "decline"],
};
const DEFAULT_DECISIONS = ["adopt", "decline", "defer"];
const RECOMMENDED: Record<string, string> = {
  adopt: "adopt",
  adopt_when_scale_defined: "defer",
  adopt_with_modification: "defer",
  review_with_house: "decline",
  decline_or_change_vehicle: "decline",
  clarify: "clarify",
  clarify_or_add_issue: "clarify",
};

function PolicyDifference({ item, streamId, actor, onDone }: { item: PolicyDifferenceItem; streamId: string; actor: string; onDone: () => void }) {
  const options = DECISIONS_FOR[item.difference] ?? DEFAULT_DECISIONS;
  const [choice, setChoice] = useState(options.includes(RECOMMENDED[item.recommendation]) ? RECOMMENDED[item.recommendation] : options[0]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function record() {
    setBusy(true);
    setError(null);
    try {
      await api.recordPolicyDecision(streamId, { issue_id: item.issue_id, decision: choice, decided_by: actor, note: note || undefined });
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className={`decision-card${item.decision ? " decided" : ""}`}>
      <div className="decision-card-head">
        <strong>{item.title}</strong>
        <span className="chip">{words(item.difference)}</span>
        {item.votes_changed !== null && (
          <span className="chip" title="Expected votes this difference changes on the synthetic meeting sample">
            {item.votes_changed} {item.votes_changed === 1 ? "vote" : "votes"} changed (sample)
          </span>
        )}
      </div>
      {item.changes.length > 0 && (
        <ul className="decision-changes">
          {item.changes.map((c) => (
            <li key={c.field}>
              <code>{c.field}</code>: {fmt(c.house)} → <strong>{fmt(c.client)}</strong>
            </li>
          ))}
        </ul>
      )}
      {item.source && <p className="decision-quote">“{item.source}”</p>}
      {item.question && <p className="help-text">Question for the client: {item.question}</p>}
      {item.flags.map((f) => (
        <p key={f} className="decision-flag">
          {f}
        </p>
      ))}
      <p className="muted">
        Recommendation: <strong>{words(item.recommendation)}</strong>
        {item.recommendation === "adopt_with_modification" &&
          " — this page cannot record the modification yet: defer it here, and record the modification through the API."}
      </p>
      {item.decision ? (
        <p className="decision-made">
          Decided: <strong>{words(item.decision.decision)}</strong> by {item.decision.decided_by}
          {item.decision.note ? ` — ${item.decision.note}` : ""}
        </p>
      ) : (
        <div className="inline-fields decision-controls">
          <select aria-label={`Decision on ${item.title}`} value={choice} onChange={(e) => setChoice(e.target.value)}>
            {options.map((o) => (
              <option key={o} value={o}>
                {words(o)}
              </option>
            ))}
          </select>
          <input aria-label={`Note on ${item.title}`} placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
          <button onClick={record} disabled={!actor || busy} title={actor ? undefined : "Enter your name above first"}>
            {busy ? "Recording…" : "Record decision"}
          </button>
        </div>
      )}
      {error && <p className="error-text">{error}</p>}
    </div>
  );
}

function StageDetail({ stage, streamId, onChanged }: { stage: StewardshipStage; streamId: string; onChanged: () => void }) {
  const [actor, setActor] = useState(() => localStorage.getItem("stewardship-actor") ?? "");
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const escalations = stage.decisions.filter((d): d is EscalationDecisionItem => d.kind === "escalation");
  const differences = stage.decisions.filter((d): d is PolicyDifferenceItem => d.kind === "policy_difference");
  const openDifferences = differences.filter((d) => d.decision === null);

  function saveActor(value: string) {
    setActor(value);
    try {
      localStorage.setItem("stewardship-actor", value);
    } catch {
      /* private mode: the name is simply not remembered */
    }
  }
  async function build() {
    setBuilding(true);
    setError(null);
    try {
      await api.buildStreamPolicy(streamId);
      onChanged();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBuilding(false);
    }
  }

  return (
    <section className="card stage-detail">
      <div className="section-heading">
        <h3>
          {stage.number}. {stage.title}
        </h3>
        <span className="chip">{stage.layer === "house" ? "House truth" : "Client overlay"}</span>
      </div>
      <p className="help-text">{stage.summary}</p>

      <div className="metric-grid">
        {stage.metrics.map((m) => (
          <div key={m.label} className={`metric-tile tone-${m.tone}`}>
            <span className="metric-tile-label">{m.label}</span>
            <strong className="metric-tile-value">{m.value}</strong>
            <span className="metric-tile-source">
              <span className={`source-dot source-${m.source}`} /> {SOURCE_LABEL[m.source]}
            </span>
            {m.hint && <span className="muted">{m.hint}</span>}
          </div>
        ))}
      </div>

      {stage.details.map((d) =>
        d.rows.length === 0 ? null : (
          <div key={d.label} className="panel-section">
            <h4>{d.label}</h4>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    {Object.keys(d.rows[0]).map((k) => (
                      <th key={k}>{words(k)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {d.rows.map((row, i) => (
                    <tr key={i}>
                      {Object.values(row).map((v, j) => (
                        <td key={j}>{typeof v === "string" ? words(v) : v}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ),
      )}

      {(escalations.length > 0 || differences.length > 0) && (
        <div className="panel-section">
          <h4>Decisions</h4>
          <label className="field-label">
            Your name (recorded with every decision)
            <input value={actor} onChange={(e) => saveActor(e.target.value)} placeholder="e.g. J. Doe" />
          </label>
          {escalations.length > 0 && <EscalationDecisions items={escalations} actor={actor} onDone={onChanged} />}
          {differences.length > 0 && (
            <>
              <p className="muted">
                {openDifferences.length} of {differences.length} differences still to decide.{" "}
                {stage.can_build && "Every difference is decided: the custom policy can be built."}
              </p>
              {stage.can_build && (
                <div className="toolbar">
                  <button onClick={build} disabled={building}>
                    {building ? "Building…" : "Build the custom policy"}
                  </button>
                </div>
              )}
              {error && <p className="error-text">{error}</p>}
              {[...openDifferences, ...differences.filter((d) => d.decision !== null)].map((item) => (
                <PolicyDifference key={item.issue_id} item={item} streamId={streamId} actor={actor} onDone={onChanged} />
              ))}
            </>
          )}
        </div>
      )}
    </section>
  );
}

function AddStream({ onCreated }: { onCreated: (id: string) => void }) {
  const [name, setName] = useState("");
  const [vehicle, setVehicle] = useState("SMA");
  const [policy, setPolicy] = useState<unknown | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function readFile(file: File | undefined) {
    setError(null);
    if (!file) return;
    try {
      setPolicy(JSON.parse(await file.text()));
      setFileName(file.name);
    } catch {
      setError("That file is not valid JSON.");
    }
  }
  async function create() {
    setBusy(true);
    setError(null);
    try {
      const res = await api.createStewardshipStream({ name, vehicle_type: vehicle, client_policy: policy ?? undefined });
      onCreated(res.stream_id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="card">
      <h3>Add a client stream</h3>
      <p className="help-text">
        A client stream runs the house process with the client's own policy on top. Start from the client's envisioned voting
        policy as a questionnaire (JSON, positions on the issue catalogue), or from the built-in example to try it out.
      </p>
      <div className="inline-fields">
        <input aria-label="Client name" placeholder="Client name" value={name} onChange={(e) => setName(e.target.value)} />
        <select aria-label="Vehicle type" value={vehicle} onChange={(e) => setVehicle(e.target.value)}>
          <option value="SMA">SMA (segregated)</option>
          <option value="CCF">CCF (pooled)</option>
          <option value="ETF">ETF (pooled)</option>
        </select>
        <label className="link-button file-button">
          {fileName ?? "Upload client policy (optional)"}
          <input type="file" accept="application/json,.json" onChange={(e) => readFile(e.target.files?.[0])} hidden />
        </label>
        <button onClick={create} disabled={!name.trim() || busy}>
          {busy ? "Creating…" : "Create stream"}
        </button>
      </div>
      {!policy && <p className="muted">No file chosen: the stream starts from the example envisioned policy.</p>}
      {error && <p className="error-text">{error}</p>}
    </section>
  );
}

export function StewardshipProcess() {
  const [streams, setStreams] = useState<StewardshipStream[]>([]);
  const [active, setActive] = useState("house");
  const [adding, setAdding] = useState(false);
  const [flow, setFlow] = useState<StewardshipFlow | null>(null);
  const [selected, setSelected] = useState("checkpoint");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const loadStreams = useCallback(async () => {
    try {
      setStreams((await api.listStewardshipStreams()).streams);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  const loadFlow = useCallback(async (streamId: string) => {
    setLoading(true);
    setError(null);
    try {
      setFlow(await api.getStewardshipFlow(streamId));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStreams();
  }, [loadStreams]);
  useEffect(() => {
    loadFlow(active);
  }, [active, loadFlow]);

  function openStream(id: string) {
    setAdding(false);
    setActive(id);
    setSelected(id === "house" ? "checkpoint" : "client_policy");
  }

  const stage = flow?.stages.find((s) => s.id === selected) ?? null;
  const mandate = flow?.stream.mandate;

  return (
    <div className="page">
      <h2>Stewardship Process</h2>
      <p className="help-text">
        The house stewardship process, stage by stage, with its key numbers and the decisions waiting for a person. Each client
        stream runs the same process with the client's own policy on top. Click a stage to see its detail and decide.
      </p>

      <nav className="sub-nav" aria-label="Process streams">
        {streams.map((s) => (
          <button key={s.stream_id} className={s.stream_id === active && !adding ? "nav-tab active" : "nav-tab"} onClick={() => openStream(s.stream_id)}>
            {s.name}
          </button>
        ))}
        <button className={adding ? "nav-tab active" : "nav-tab"} onClick={() => setAdding(true)}>
          + Client stream
        </button>
      </nav>

      {adding && (
        <AddStream
          onCreated={async (id) => {
            await loadStreams();
            openStream(id);
          }}
        />
      )}

      {error && <p className="error-text">{error}</p>}
      {!adding && flow && (
        <>
          <section className="card">
            <div className="section-heading">
              <h3>{flow.stream.name}</h3>
              {mandate && <span className="chip">{[mandate.vehicle_type, mandate.benchmark, mandate.voting_mode && words(mandate.voting_mode)].filter(Boolean).join(" · ")}</span>}
              {loading && <span className="muted">Refreshing…</span>}
            </div>
            <div className="chip-row source-legend">
              {(Object.keys(SOURCE_LABEL) as MetricSource[]).map((s) => (
                <span key={s} className="chip">
                  <span className={`source-dot source-${s}`} /> {SOURCE_LABEL[s]}
                </span>
              ))}
            </div>
            <p className="muted">{flow.data_note}</p>
            <FlowChart flow={flow} selected={selected} onSelect={setSelected} />
            <FlowList flow={flow} selected={selected} onSelect={setSelected} />
          </section>
          {stage && <StageDetail key={`${active}-${stage.id}`} stage={stage} streamId={active} onChanged={() => loadFlow(active)} />}
        </>
      )}
      {!adding && !flow && loading && <p className="status-text">Loading the process…</p>}
    </div>
  );
}

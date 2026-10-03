import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { apiMessage, createAndOpen, DEFAULT_NOTIONAL_EUR, STANDARD } from "../../lib/projects";
import type { OpenedDashboard, OpenResult, ProjectSummary } from "../../types";

const KEY = "arp.project"; // a convenience only: storage may be blocked

const stored = () => {
  try {
    return localStorage.getItem(KEY) ?? STANDARD;
  } catch {
    return STANDARD;
  }
};
const remember = (id: string) => {
  try {
    localStorage.setItem(KEY, id);
  } catch {
    /* ignore */
  }
};

/** Project selector for the Dashboards tab. Choosing a project opens it (imports its data and
 * (re)builds its dashboards); "Standard dashboards" is no project and opens nothing. */
export function ProjectBar({
  onOpened,
  onProject,
}: {
  onOpened: (dashboards: OpenedDashboard[]) => void;
  /** The chosen project id, or null for "Standard dashboards". */
  onProject?: (id: string | null) => void;
}) {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selected, setSelected] = useState(STANDARD);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<OpenResult | null>(null);

  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [notional, setNotional] = useState(String(DEFAULT_NOTIONAL_EUR));
  const [files, setFiles] = useState<File[]>([]);

  const created = useRef(false); // the create flow got as far as having a project
  const latest = useRef(0); // a stale open never overwrites newer state

  const open = useCallback(
    async (id: string, flow?: () => Promise<{ id: string; result: OpenResult }>) => {
      const mine = ++latest.current;
      setRunning(true);
      setError(null);
      setSummary(null);
      try {
        const r = flow ? await flow() : { id, result: await api.openProject(id) };
        if (mine !== latest.current) return null;
        setSummary(r.result);
        onOpened(r.result.dashboards);
        return r.id;
      } catch (e) {
        if (mine !== latest.current) return null;
        setError(apiMessage(e));
        if (!flow || created.current) onOpened([]); // a failed createProject leaves the picker as it was
        return null;
      } finally {
        if (mine === latest.current) setRunning(false);
      }
    },
    [onOpened],
  );

  function choose(id: string) {
    setSelected(id);
    remember(id);
    setSummary(null);
    setError(null);
    onProject?.(id || null);
    if (id) void open(id);
  }

  // Load the list once, then restore the remembered project (which opens it).
  useEffect(() => {
    let live = true;
    api.listProjects().then(
      (list) => {
        if (!live) return;
        setProjects(list);
        const s = stored();
        if (s && list.some((p) => p.id === s)) choose(s);
      },
      (e) => live && setError(apiMessage(e)),
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    const notionalEur = Number(notional);
    if (!name.trim() || !(notionalEur > 0) || files.length === 0) return;
    created.current = false;
    // The project becomes the parent's selection as soon as it exists, before the open fills its dashboards.
    const id = await open("", () =>
      createAndOpen(api, { name: name.trim(), notionalEur, files }, (pid) => {
        created.current = true;
        setSelected(pid);
        remember(pid);
        onProject?.(pid);
      }),
    );
    // The project exists even if a later step failed, so list it either way.
    try {
      setProjects(await api.listProjects());
    } catch {
      /* the list refreshes on next load */
    }
    if (id) {
      setCreating(false);
      setName("");
      setFiles([]);
    }
  }

  return (
    <section className="card">
      <h2>Project</h2>
      <div className="toolbar">
        <label className="field-label inline-label">
          Project
          <select value={selected} onChange={(e) => choose(e.target.value)} disabled={running}>
            <option value={STANDARD}>Standard dashboards</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <button className="secondary" onClick={() => void open(selected)} disabled={running || !selected}>
          {running ? "Opening..." : "Open"}
        </button>
        <button className="secondary" onClick={() => setCreating((c) => !c)} disabled={running} aria-expanded={creating}>
          New project
        </button>
      </div>
      {creating && (
        <form onSubmit={create} aria-label="New project">
          <label className="field-label">
            Name
            <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} />
          </label>
          <label className="field-label">
            Notional (EUR)
            <input type="number" min={1} step="any" value={notional} onChange={(e) => setNotional(e.target.value)} required />
          </label>
          <label className="field-label">
            Constituent files (.xlsx)
            <input
              type="file"
              accept=".xlsx"
              multiple
              onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
              required
            />
          </label>
          <div className="toolbar">
            <button type="submit" disabled={running || !name.trim() || files.length === 0}>
              {running ? "Creating..." : "Create and open"}
            </button>
          </div>
        </form>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {summary && (
        <div className="banner banner-success" aria-live="polite">
          <ul className="citation-list">
            {summary.data.map((d, i) => (
              <li key={i}>
                Data: {Object.entries(d).map(([k, v]) => `${k} ${typeof v === "object" ? JSON.stringify(v) : String(v)}`).join(", ")}
              </li>
            ))}
            {summary.dashboards.map((d) => (
              <li key={d.slug}>
                {d.title}: <strong>{d.status}</strong>
                {!d.published && " (draft)"}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

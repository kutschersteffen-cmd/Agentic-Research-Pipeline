import { useCallback, useEffect, useRef, useState } from "react";
import { embedDashboard } from "@superset-ui/embedded-sdk";
import { api } from "../../api/client";
import { designRequestBody, embedErrorText, embedUrlFor, pickDefaultDashboard, SUPERSET_URL } from "../../lib/biEmbed";
import { apiMessage, embeddable, saveBody, UNSCOPED_CAVEAT } from "../../lib/projects";
import type { BIDesignResult, DashboardItem, OpenedDashboard } from "../../types";
import { ProjectBar } from "./ProjectBar";

const EXAMPLE_BRIEFS = [
  "Exposure overview: total exposure in EUR, split by sector and by country",
  "Which portfolios hold the most, and in which asset classes and currencies?",
  "Review backlog: share of run records needing review, by pipeline",
];

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** Mounts one dashboard through Superset's embed SDK. The iframe loads Superset's
 * /embedded/<uuid> page and asks this app for a guest token (and again whenever
 * the token nears expiry), so it shows the dashboard with the guest role.
 * Render it with `key={dashboardId}`: a new selection remounts it, which unmounts
 * the old embed and drops any token response still in flight for it. */
function EmbeddedDashboard({ dashboardId, title }: { dashboardId: number; title: string }) {
  const mount = useRef<HTMLDivElement>(null);
  const [embeddedId, setEmbeddedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const frameUrl = embedUrlFor({ dashboard_id: dashboardId }, embeddedId);

  useEffect(() => {
    let live = true;
    setEmbeddedId(null);
    setError(null);
    api.biEmbedToken(dashboardId).then(
      (t) => live && setEmbeddedId(t.embedded_id),
      (e) => live && setError(embedErrorText(message(e))),
    );
    return () => {
      live = false;
    };
  }, [dashboardId]);

  useEffect(() => {
    if (!frameUrl || !embeddedId || !mount.current) return;
    const embedded = embedDashboard({
      id: embeddedId,
      supersetDomain: SUPERSET_URL,
      mountPoint: mount.current,
      fetchGuestToken: async () => (await api.biEmbedToken(dashboardId)).token,
      // The native filter bar (fund, sector, country) is this tab's selection UI.
      dashboardUiConfig: { hideTitle: true, filters: { expanded: true } },
      iframeTitle: `Superset dashboard: ${title}`,
    });
    return () => {
      embedded.then((d) => d.unmount(), () => undefined);
    };
  }, [frameUrl, embeddedId, dashboardId, title]);

  if (error) return <p className="error-text" role="alert">The dashboard could not be embedded: {error}</p>;
  return <div ref={mount} className="superset-embed" aria-busy={!frameUrl} />;
}

/** What the designer did with the last brief. The dashboard itself shows in the picker above. */
function ResultView({ result, onSave }: { result: BIDesignResult; onSave?: () => void }) {
  if (result.dashboard_id === null) {
    return (
      <div className="banner banner-warning">
        No dashboard was drafted. The plan was refused for these reasons:
        <ul className="citation-list">
          {result.rejected.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
        Nothing was created in Superset. Refine the brief and try again.
      </div>
    );
  }

  return (
    <div className="banner banner-success">
      Drafted in Superset: <strong>{result.plan?.title ?? result.slug}</strong>.
      {onSave && saveBody(result) && (
        <div className="toolbar">
          <button className="secondary" onClick={onSave}>Save to project</button>
        </div>
      )}
      {result.plan && (
        <details>
          <summary>Chart plan (what the model asked Superset for)</summary>
          <ul className="citation-list">
            {result.plan.charts.map((c) => (
              <li key={c.title}>
                {c.title} <span className="muted">— {c.viz_type} on {c.dataset}: {c.metrics.join(", ")}
                {c.groupby.length > 0 && ` by ${c.groupby.join(", ")}`}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function ListError({ error }: { error: string }) {
  // The API's detail is a short message of ours ("503: Superset is not configured: ..."); never a Superset body.
  if (error.startsWith("503:")) {
    return <div className="banner banner-warning" role="alert">{error.slice(4).trim()}</div>;
  }
  return <div className="banner banner-danger" role="alert">The dashboard list could not be loaded. {error.replace(/^\d{3}:\s*/, "")}</div>;
}

/** Dashboards (Superset): every `arp-` dashboard in Superset, embedded here.
 * A brief can draft a new one: the model only picks datasets, saved metrics and
 * chart types from a fixed catalogue; Superset runs every query. Drafts stay
 * unpublished until a person publishes them in Superset. */
export function SupersetBI() {
  const [dashboards, setDashboards] = useState<DashboardItem[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const listRequest = useRef(0);

  const [project, setProject] = useState<string | null>(null);
  const [projectDashboards, setProjectDashboards] = useState<DashboardItem[] | null>(null);
  const [saveNote, setSaveNote] = useState<string | null>(null);

  const [brief, setBrief] = useState("");
  const [result, setResult] = useState<BIDesignResult | null>(null);
  const [busy, setBusy] = useState<"design" | "ask" | null>(null);
  const [error, setError] = useState<string | null>(null);

  /** (Re)load the list; select `preferId` if listed, else keep the current pick, else the default. */
  const loadList = useCallback(async (preferId?: number) => {
    const req = ++listRequest.current;
    try {
      const items = await api.biDashboards();
      if (req !== listRequest.current) return; // a newer load superseded this one
      setDashboards(items);
      setListError(null);
      setSelectedId((current) => {
        const listed = (id: number | null | undefined) => items.some((d) => d.id === id);
        if (listed(preferId)) return preferId!;
        if (listed(current)) return current;
        return pickDefaultDashboard(items)?.id ?? null;
      });
    } catch (e) {
      if (req !== listRequest.current) return;
      setListError(message(e));
    }
  }, []);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  async function run(mode: "design" | "ask", text: string) {
    setBusy(mode);
    setError(null);
    setResult(null);
    try {
      const body = designRequestBody(text);
      const r = mode === "design" ? await api.designBI(body) : await api.askBI(body.brief);
      setResult(r);
      if (r.dashboard_id !== null) await loadList(r.dashboard_id);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(null);
    }
  }

  // With a project chosen the picker shows only what open returned; otherwise every arp- dashboard.
  const shown = project ? projectDashboards : dashboards;
  const selected = shown?.find((d) => d.id === selectedId) ?? null;

  const onOpened = useCallback((ds: OpenedDashboard[]) => {
    const items = embeddable(ds);
    setProjectDashboards(items);
    setSelectedId(items[0]?.id ?? null);
  }, []);
  const onProject = useCallback((id: string | null) => {
    setProject(id);
    setProjectDashboards(null);
    setSaveNote(null);
  }, []);

  async function saveToProject(action: () => Promise<string>) {
    setSaveNote(null);
    try {
      setSaveNote(await action());
    } catch (e) {
      setSaveNote(`Could not save to the project. ${apiMessage(e)}`);
    }
  }
  const saveDesign = () => {
    const body = saveBody(result);
    if (!project || !body) return;
    void saveToProject(async () => {
      const d = await api.saveProjectDashboard(project, body);
      if (d.id !== null) {
        const item = { id: d.id, slug: d.slug, title: d.title, published: d.published };
        setProjectDashboards((cur) => [...(cur ?? []).filter((x) => x.id !== item.id), item]);
        setSelectedId(d.id);
      }
      return `Saved to the project: ${d.title}.`;
    });
  };
  const exportPicked = () => {
    if (!project || !selected) return;
    void saveToProject(async () => {
      const d = await api.exportProjectDashboard(project, selected.id);
      return `Saved to the project: ${d.title}.${d.scoped ? "" : ` ${UNSCOPED_CAVEAT}.`}`;
    });
  };

  return (
    <>
      <ProjectBar onOpened={onOpened} onProject={onProject} />
      <section className="card">
        <h2>Dashboards</h2>
        {!project && listError ? (
          <ListError error={listError} />
        ) : shown === null ? (
          <p className="muted" aria-live="polite">{project ? "Opening the project…" : "Loading dashboards…"}</p>
        ) : shown.length === 0 ? (
          <p className="muted">
            {project ? "This project has no dashboards open." : <>No dashboards yet — run <code>arp bi bootstrap</code> or describe one below.</>}
          </p>
        ) : (
          <>
            <div className="toolbar">
              <label className="field-label inline-label">
                Dashboard
                <select value={selectedId ?? ""} onChange={(e) => setSelectedId(Number(e.target.value))}>
                  {shown.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.published ? d.title : `${d.title} (draft)`}
                    </option>
                  ))}
                </select>
              </label>
              {selected && !selected.published && <span className="badge badge-mid">Draft</span>}
              {selected && (
                <a href={`${SUPERSET_URL.replace(/\/+$/, "")}/superset/dashboard/${selected.slug}/`} target="_blank" rel="noopener noreferrer">
                  Open in Superset
                </a>
              )}
              {project && selected && !selected.slug.startsWith(`arp-${project}--`) && (
                <button className="secondary" onClick={exportPicked}>Save to project</button>
              )}
            </div>
            {saveNote && <p className="muted" role="status">{saveNote}</p>}
            {selected && !selected.published && (
              <p className="await-text">Draft — unpublished. Review and publish it in Superset.</p>
            )}
            {selected && <EmbeddedDashboard key={selected.id} dashboardId={selected.id} title={selected.title} />}
          </>
        )}
        <p className="muted">
          Filter with the dashboard's own filter bar. A dashboard you build by hand in Superset shows up here once its
          slug starts with <code>arp-</code> (set it in the dashboard's Properties).
        </p>
      </section>

      <section className="card">
        <h2>Describe a dashboard</h2>
        <p className="help-text">
          The model chooses charts from the portfolio datasets and saved metrics registered in Superset; it never writes SQL
          or produces a number. Superset computes every figure. The result is an unpublished draft: review it, then publish
          it in Superset. A quick question adds one chart to the shared Scratch dashboard instead. Requires Superset and{" "}
          <code>ARP_ANTHROPIC_API_KEY</code> on the server.
        </p>
        <textarea
          aria-label="Dashboard brief"
          rows={3}
          value={brief}
          onChange={(e) => setBrief(e.target.value)}
          placeholder="e.g. exposure overview: market value by sector and by country"
        />
        <div className="toolbar">
          <button onClick={() => run("design", brief)} disabled={busy !== null || !brief.trim()}>
            {busy === "design" ? "Designing..." : "Design in Superset"}
          </button>
          <button className="secondary" onClick={() => run("ask", brief)} disabled={busy !== null || !brief.trim()}>
            {busy === "ask" ? "Asking..." : "Ask as one chart"}
          </button>
        </div>
        <div className="toolbar">
          {EXAMPLE_BRIEFS.map((b) => (
            <button
              key={b}
              className="link-button"
              disabled={busy !== null}
              onClick={() => {
                setBrief(b);
                run("design", b);
              }}
            >
              {b}
            </button>
          ))}
        </div>
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
        {saveNote && !shown?.length && <p className="muted" role="status">{saveNote}</p>}
        {result && <ResultView result={result} onSave={project ? saveDesign : undefined} />}
      </section>
    </>
  );
}

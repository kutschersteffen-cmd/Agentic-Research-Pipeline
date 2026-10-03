import { useEffect, useRef, useState } from "react";
import { embedDashboard } from "@superset-ui/embedded-sdk";
import { api } from "../../api/client";
import { designRequestBody, embedUrlFor, SUPERSET_URL } from "../../lib/biEmbed";
import type { BIDesignResult } from "../../types";

const EXAMPLE_BRIEFS = [
  "Exposure overview: total exposure in EUR, split by sector and by country",
  "Which portfolios hold the most, and in which asset classes and currencies?",
  "Review backlog: share of run records needing review, by pipeline",
];

/** Mounts the draft through Superset's embed SDK. The iframe loads Superset's
 * /embedded/<uuid> page and asks this app for a guest token (and again
 * whenever the token nears expiry), so it shows the draft with the guest role. */
function EmbeddedDashboard({ dashboardId }: { dashboardId: number }) {
  const mount = useRef<HTMLDivElement>(null);
  const [embeddedId, setEmbeddedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const frameUrl = embedUrlFor({ dashboard_id: dashboardId }, embeddedId);

  useEffect(() => {
    setEmbeddedId(null);
    setError(null);
    api.biEmbedToken(dashboardId).then(
      (t) => setEmbeddedId(t.embedded_id),
      (e) => setError(String(e)),
    );
  }, [dashboardId]);

  useEffect(() => {
    if (!frameUrl || !embeddedId || !mount.current) return;
    const embedded = embedDashboard({
      id: embeddedId,
      supersetDomain: SUPERSET_URL,
      mountPoint: mount.current,
      fetchGuestToken: async () => (await api.biEmbedToken(dashboardId)).token,
      dashboardUiConfig: { hideTitle: true, filters: { expanded: false } },
      iframeTitle: "Superset dashboard draft",
    });
    return () => {
      embedded.then((d) => d.unmount(), () => undefined);
    };
  }, [frameUrl, embeddedId, dashboardId]);

  if (error) return <p className="error-text" role="alert">The draft could not be embedded: {error}</p>;
  return <div ref={mount} className="superset-embed" aria-busy={!frameUrl} />;
}

function ResultView({ result }: { result: BIDesignResult }) {
  if (result.dashboard_id === null) {
    return (
      <section className="card">
        <div className="banner banner-warning">
          No dashboard was drafted. The plan was refused for these reasons:
          <ul className="citation-list">
            {result.rejected.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
          Nothing was created in Superset. Refine the brief and try again.
        </div>
      </section>
    );
  }

  return (
    <section className="card">
      <h2>{result.plan?.title ?? result.slug}</h2>
      {result.plan?.goal && <p className="help-text">{result.plan.goal}</p>}
      <p className="await-text">Draft — unpublished. Review and publish it in Superset.</p>
      <div className="toolbar">
        {result.url && (
          <a href={result.url} target="_blank" rel="noopener noreferrer">
            Open the draft in Superset
          </a>
        )}
        <span className="chip">{result.slug}</span>
        {result.plan && <span className="chip">{result.plan.charts.length} chart(s)</span>}
      </div>
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
      <EmbeddedDashboard dashboardId={result.dashboard_id} />
    </section>
  );
}

/** Superset BI: a brief becomes a draft dashboard in Superset itself. The
 * model only picks datasets, saved metrics and chart types from a fixed
 * catalogue; Superset runs every query. Drafts stay unpublished until a
 * person publishes them in Superset. */
export function SupersetBI() {
  const [brief, setBrief] = useState("");
  const [result, setResult] = useState<BIDesignResult | null>(null);
  const [busy, setBusy] = useState<"design" | "ask" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(mode: "design" | "ask", text: string) {
    setBusy(mode);
    setError(null);
    setResult(null);
    try {
      const body = designRequestBody(text);
      setResult(mode === "design" ? await api.designBI(body) : await api.askBI(body.brief));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <section className="card">
        <h2>Design a dashboard in Superset</h2>
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
      </section>

      {result && <ResultView result={result} />}
    </>
  );
}

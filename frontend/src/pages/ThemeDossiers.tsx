import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { STATE_CLASS, STATE_LABEL, dossierHref, shelvedBanner, stepLinkText, visibleDossiers } from "../lib/dossiers";
import type { Dossier, DossierItem, Taxonomy } from "../types";
import { ContextBriefBody } from "../components/ContextBrief";
import { NO_BRIEF } from "../lib/contextBrief";
import { ThemeResearch } from "./ThemeResearch";

type Props = { params: string[]; onFindCompanies: (taxonomyId: string) => void };

/** #/themes lists the theme dossiers; #/themes/<id> shows one dossier's five steps; #/themes/<id>/research its step 3. */
export function ThemeDossiers({ params, onFindCompanies }: Props) {
  if (params[0] && params[1] === "research") return <ThemeResearch key={params[0]} id={params[0]} />;
  return params[0] ? <DossierPage key={params[0]} id={params[0]} onFindCompanies={onFindCompanies} /> : <DossierList />;
}

function useTaxonomies(): Taxonomy[] {
  const [taxonomies, setTaxonomies] = useState<Taxonomy[]>([]);
  useEffect(() => {
    api.listTaxonomies().then((r) => setTaxonomies(r.taxonomies as Taxonomy[]), () => setTaxonomies([]));
  }, []);
  return taxonomies;
}

function TaxonomySelect({ id, value, onChange, taxonomies, optional }: { id: string; value: string; onChange: (v: string) => void; taxonomies: Taxonomy[]; optional?: boolean }) {
  return (
    <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{optional ? "No taxonomy yet" : "Pick a taxonomy"}</option>
      {taxonomies.map((t) => (
        <option key={t.taxonomy_id} value={t.taxonomy_id}>
          {t.name} ({t.taxonomy_id})
        </option>
      ))}
    </select>
  );
}

function DossierList() {
  const [items, setItems] = useState<DossierItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showShelved, setShowShelved] = useState(false);
  const [name, setName] = useState("");
  const [taxonomyId, setTaxonomyId] = useState("");
  const [busy, setBusy] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const taxonomies = useTaxonomies();

  useEffect(() => {
    api.listDossiers().then((r) => setItems(r.items), (err: Error) => setError(err.message));
  }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setCreateError(null);
    try {
      window.location.hash = dossierHref((await api.createDossier(name, taxonomyId || null)).dossier_id);
    } catch (err) {
      setCreateError((err as Error).message);
      setBusy(false);
    }
  }

  const shown = visibleDossiers(items ?? [], showShelved);
  return (
    <div className="page">
      <h1>Theme dossiers</h1>
      <p className="help-text">One record per theme: where it stands in the five research steps and what waits on someone.</p>
      <form className="card" onSubmit={create} aria-label="New theme">
        <h2>New theme</h2>
        <div className="inline-fields">
          <label htmlFor="dossier-name">Name</label>
          <input id="dossier-name" value={name} onChange={(e) => setName(e.target.value)} required />
          <label htmlFor="dossier-taxonomy">Taxonomy</label>
          <TaxonomySelect id="dossier-taxonomy" value={taxonomyId} onChange={setTaxonomyId} taxonomies={taxonomies} optional />
          <button type="submit" disabled={busy || !name.trim()}>
            Create
          </button>
        </div>
      </form>
      {createError && <p className="error-text" role="alert">The dossier could not be created: {createError}.</p>}
      {error && <p className="error-text" role="alert">Dossiers could not be loaded: {error}.</p>}
      <label>
        <input type="checkbox" checked={showShelved} onChange={(e) => setShowShelved(e.target.checked)} /> Show shelved
      </label>
      <div className="table-wrap">
        <table className="data-table stack-on-phone" aria-label="Theme dossiers">
          <thead>
            <tr>
              <th>Theme</th>
              <th>Origin</th>
              <th>Current step</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {items !== null && shown.length === 0 && (
              <tr>
                <td colSpan={4} className="muted">
                  {items.length ? "Every dossier is shelved. Turn on Show shelved to see them." : "No dossiers yet. Create one above, or promote an Emerging Themes candidate."}
                </td>
              </tr>
            )}
            {shown.map((d) => (
              <tr key={d.dossier_id}>
                <td>
                  <a href={dossierHref(d.dossier_id)}>{d.name}</a>
                  {d.status === "shelved" && <span className="muted"> · shelved</span>}
                </td>
                <td>{d.origin === "candidate" ? "Emerging Themes" : "Topic"}</td>
                <td className="mono">{d.current_step ?? "—"}</td>
                <td className="mono">{d.created_at.slice(0, 10)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DossierPage({ id, onFindCompanies }: { id: string; onFindCompanies: (taxonomyId: string) => void }) {
  const [dossier, setDossier] = useState<Dossier | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [chosen, setChosen] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [showBrief, setShowBrief] = useState(false);
  const taxonomies = useTaxonomies();

  useEffect(() => {
    api.getDossier(id).then(setDossier, (err: Error) => setError(err.message));
  }, [id]);

  const patch = useCallback(
    async (body: Parameters<typeof api.patchDossier>[1]) => {
      setBusy(true);
      setActionError(null);
      try {
        setDossier(await api.patchDossier(id, body));
        return true;
      } catch (err) {
        setActionError((err as Error).message);
        return false;
      } finally {
        setBusy(false);
      }
    },
    [id],
  );

  if (error) return <div className="page"><p className="error-text" role="alert">The dossier could not be loaded: {error}.</p><a href="#/themes">All theme dossiers</a></div>;
  if (!dossier) return <p className="muted" role="status">Loading…</p>;
  const banner = shelvedBanner(dossier);
  return (
    <div className="page">
      <p><a href="#/themes">All theme dossiers</a></p>
      <h1>{dossier.name}</h1>
      <p className="muted">
        {dossier.origin === "candidate" ? "Promoted from Emerging Themes" : "Started from a topic"} · <span className="mono">{dossier.dossier_id}</span>
      </p>
      {banner && <p className="banner banner-warning" role="status">{banner}</p>}
      {actionError && <p className="error-text" role="alert">{actionError}</p>}
      <ol className="dossier-steps" aria-label="Steps">
        {dossier.steps.map((s) => (
          <li key={s.number} className="card dossier-step">
            <span className="stepper-num">{s.number}</span>
            <div>
              <h2>{s.title}</h2>
              <p>
                <span className={STATE_CLASS[s.state]}>{STATE_LABEL[s.state]}</span> <span className="mono">{s.detail}</span>
              </p>
              {s.href &&
                (s.number === 4 && s.href === "#/theme" && dossier.taxonomy_id ? (
                  <a href="#/theme" onClick={(e) => { e.preventDefault(); onFindCompanies(dossier.taxonomy_id!); }}>
                    {stepLinkText(4, s.href)}
                  </a>
                ) : (
                  <a href={s.href}>{stepLinkText(s.number, s.href)}</a>
                ))}
              {s.number === 1 && dossier.origin === "candidate" &&
                (!dossier.context_brief ? (
                  <p className="muted">{NO_BRIEF}</p>
                ) : showBrief ? (
                  <ContextBriefBody brief={dossier.context_brief} />
                ) : (
                  <button type="button" className="secondary" onClick={() => setShowBrief(true)}>
                    Show context brief
                  </button>
                ))}
              {s.number === 2 && !dossier.taxonomy_id && (
                <form
                  className="inline-fields"
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (chosen) patch({ taxonomy_id: chosen });
                  }}
                >
                  <label htmlFor="dossier-choose">Choose a taxonomy</label>
                  <TaxonomySelect id="dossier-choose" value={chosen} onChange={setChosen} taxonomies={taxonomies} />
                  <button type="submit" disabled={busy || !chosen}>
                    Choose a taxonomy
                  </button>
                </form>
              )}
            </div>
          </li>
        ))}
      </ol>
      {dossier.status === "active" && (
        <form
          className="card inline-fields"
          aria-label="Shelve"
          onSubmit={async (e) => {
            e.preventDefault();
            if (await patch({ status: "shelved", reason })) setReason("");
          }}
        >
          <label htmlFor="dossier-reason">Reason</label>
          <input id="dossier-reason" value={reason} onChange={(e) => setReason(e.target.value)} required />
          <button type="submit" className="secondary" disabled={busy || !reason.trim()}>
            Shelve
          </button>
        </form>
      )}
    </div>
  );
}

import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { apiMessage } from "../../lib/projects";
import { useMe } from "../../lib/reviewer";
import { exposureHash, recipesHash } from "../../lib/valueChain";
import type { VcRecipe } from "../../types";
import { NodeSearch } from "./PortfolioView";
import { useVcQuery } from "./useVcQuery";

const STATUS = { ok: "OK", unresolved: "Not in this edition", inconsistent: "Does not fit this edition" } as const;

function Caveats({ caveat, model }: { caveat: string; model: string }) {
  return (
    <>
      <p className="help-text vc-note">{caveat}</p>
      <p className="help-text vc-note">{model}</p>
    </>
  );
}

/** `#/valueChain/recipes`: every recipe with its status on the current build. */
export function RecipeList() {
  const q = useVcQuery(() => api.valueChainRecipes(), []);
  return (
    <>
      {q.error && (
        <p className="error-text" role="alert">
          {q.error}
        </p>
      )}
      <div className="toolbar">
        <a className="button-link" href={recipesHash("new")}>
          New recipe
        </a>
      </div>
      {q.data && (
        <>
          <section className="card" aria-label="Recipes">
            {q.data.items.length === 0 ? (
              <p className="muted">No recipes yet.</p>
            ) : (
              <table className="data-table stack-on-phone">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Home</th>
                    <th className="num">Output</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {q.data.items.map((r) => (
                    <tr key={r.recipe_id}>
                      <td>
                        <a href={recipesHash(r.recipe_id)}>{r.name}</a>
                      </td>
                      <td>
                        {r.home.sector} <span className="muted">· {r.home.region}</span>
                      </td>
                      <td className="num mono">{r.output_meur} M EUR</td>
                      <td>{STATUS[r.status]}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
          <Caveats caveat={q.data.caveat} model={q.data.model_caveat} />
        </>
      )}
    </>
  );
}

type Input = { key: number; region: string; sector: string; pct: string };
let nextKey = 0;
const blank = (): Input => ({ key: nextKey++, region: "", sector: "", pct: "" });

/** `#/valueChain/recipes/<rid>` or `/new`: the recipe form, read-only for viewers. */
export function RecipeForm({ rid, onTitle }: { rid: string | null; onTitle: (title: string) => void }) {
  const me = useMe();
  const canEdit = me !== null && me.role !== "viewer";
  // An existing recipe fills the form; a new one still loads the list for the caveat lines.
  const q = useVcQuery(
    () => (rid ? api.valueChainRecipe(rid).then((r) => ({ recipe: r as VcRecipe | null, caveat: r.caveat, model: r.model_caveat })) : api.valueChainRecipes().then((l) => ({ recipe: null, caveat: l.caveat, model: l.model_caveat }))),
    [rid],
  );
  const loaded = q.data?.recipe ?? null;
  const [form, setForm] = useState<{ name: string; home: { region: string; sector: string }; output: string; inputs: Input[]; source: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (q.data && form === null) {
    const r = loaded;
    setForm({
      name: r?.name ?? "",
      home: r?.home ?? { region: "", sector: "" },
      output: r ? String(r.output_meur) : "",
      inputs: r ? r.inputs.map((i) => ({ key: nextKey++, region: i.region, sector: i.sector, pct: String(Number((i.share * 100).toFixed(9))) })) : [blank()],
      source: r?.source ?? "",
    });
  }
  const title = q.data ? (loaded?.name ?? "New recipe") : null;
  useEffect(() => {
    if (title) onTitle(title);
  }, [title, onTitle]);

  const setInput = (key: number, patch: Partial<Input>) => setForm((f) => f && { ...f, inputs: f.inputs.map((i) => (i.key === key ? { ...i, ...patch } : i)) });

  async function save() {
    if (!form) return;
    setBusy(true);
    setError(null);
    try {
      const saved = await api.saveValueChainRecipe(rid, {
        name: form.name,
        home: form.home,
        output_meur: Number(form.output),
        inputs: form.inputs.map((i) => ({ region: i.region, sector: i.sector, share: Number(i.pct) / 100 })),
        source: form.source,
      });
      window.location.hash = exposureHash(`recipe:${saved.recipe_id}`);
    } catch (err) {
      setError(apiMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!rid || !window.confirm("Delete this recipe?")) return;
    setBusy(true);
    try {
      await api.deleteValueChainRecipe(rid);
      window.location.hash = recipesHash();
    } catch (err) {
      setError(apiMessage(err));
      setBusy(false);
    }
  }

  return (
    <>
      {q.error && (
        <p className="error-text" role="alert">
          {q.error}
        </p>
      )}
      {form && (
        <section className="card" aria-label="Recipe">
          {loaded && (
            <p>
              <a href={exposureHash(`recipe:${loaded.recipe_id}`)}>Revenue exposure</a>
            </p>
          )}
          <fieldset className="rules-fieldset" disabled={!canEdit || busy}>
            <label className="field-label">
              Name
              <input value={form.name} maxLength={120} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </label>
            <div className="field-label">
              Home
              {canEdit ? (
                <NodeSearch row={form.home} onPick={(n) => setForm({ ...form, home: { region: n.region, sector: n.sector } })} />
              ) : (
                <span>
                  {form.home.region} · {form.home.sector}
                </span>
              )}
            </div>
            <label className="field-label">
              Output M EUR
              <input type="number" min={0} step="any" value={form.output} onChange={(e) => setForm({ ...form, output: e.target.value })} />
            </label>
            <h3>Inputs</h3>
            <ul className="vc-editor-rows">
              {form.inputs.map((i) => (
                <li key={i.key}>
                  {canEdit ? (
                    <NodeSearch row={i} onPick={(n) => setInput(i.key, { region: n.region, sector: n.sector })} />
                  ) : (
                    <span>
                      {i.region} · {i.sector}
                    </span>
                  )}
                  <label className="field-label vc-share">
                    Share %
                    <input type="number" min={0} max={100} step="any" value={i.pct} onChange={(e) => setInput(i.key, { pct: e.target.value })} />
                  </label>
                  {canEdit && form.inputs.length > 1 && (
                    <button type="button" className="secondary" onClick={() => setForm({ ...form, inputs: form.inputs.filter((x) => x.key !== i.key) })}>
                      Remove
                    </button>
                  )}
                </li>
              ))}
            </ul>
            {canEdit && form.inputs.length < 50 && (
              <button type="button" className="secondary" onClick={() => setForm({ ...form, inputs: [...form.inputs, blank()] })}>
                Add input
              </button>
            )}
            <label className="field-label">
              Source
              <textarea value={form.source} maxLength={2000} onChange={(e) => setForm({ ...form, source: e.target.value })} />
            </label>
          </fieldset>
          {error && (
            <p className="error-text" role="alert">
              {error}
            </p>
          )}
          {canEdit && (
            <div className="toolbar">
              <button type="button" onClick={save} disabled={busy}>
                Save
              </button>
              {rid && (
                <button type="button" className="secondary" onClick={remove} disabled={busy}>
                  Delete
                </button>
              )}
            </div>
          )}
        </section>
      )}
      {q.data && <Caveats caveat={q.data.caveat} model={q.data.model} />}
    </>
  );
}

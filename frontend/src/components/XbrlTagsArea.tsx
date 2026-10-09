import { useEffect, useState } from "react";
import { api } from "../api/client";
import { TagCombobox } from "./TagCombobox";

type Saved = { name: string; tags: string[]; created_at?: string };

const msg = (err: unknown) => (err as Error).message;
const tagCount = (n: number) => `${n} ${n === 1 ? "tag" : "tags"}`;

/** XBRL Facts, Tags area: choose tags, save them as a named selection, update the tag registry. */
export function XbrlTagsArea({ tags, onChange }: { tags: string[]; onChange: (next: string[]) => void }) {
  const [name, setName] = useState("");
  const [saved, setSaved] = useState<Saved[] | null>(null);
  const [savedError, setSavedError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<{ ok: boolean; text: string } | null>(null);
  const [registry, setRegistry] = useState<{ busy: boolean; ok: boolean; text: string } | null>(null);

  const loadSaved = () =>
    api
      .listXbrlSelections()
      .then((rows) => {
        setSaved(rows as Saved[]);
        setSavedError(null);
      })
      .catch((err) => setSavedError(msg(err)));
  useEffect(() => {
    loadSaved();
  }, []);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaveStatus(null);
    setSaving(true);
    try {
      const res = await api.saveXbrlSelection(name.trim(), tags);
      setSaveStatus({ ok: true, text: `Saved “${res.name}”: ${tagCount(res.tags.length)}, ${res.row_count.toLocaleString()} facts from stored companies.` });
      setName("");
      loadSaved();
    } catch (err) {
      setSaveStatus({ ok: false, text: `Could not save the selection (${msg(err)}).` });
    } finally {
      setSaving(false);
    }
  }

  async function updateRegistry() {
    setRegistry({ busy: true, ok: true, text: "Updating the tag registry from the official taxonomies. This can take a minute…" });
    try {
      const counts = (await api.updateXbrlTaxonomy()) as Record<string, number>;
      const parts = Object.entries(counts).map(([t, n]) => `${t} ${n.toLocaleString()} tags`);
      setRegistry({ busy: false, ok: true, text: `Tag registry updated: ${parts.join(", ")}.` });
    } catch (err) {
      setRegistry({ busy: false, ok: false, text: `Tag registry update failed (${msg(err)}). The previous registry is still in use.` });
    }
  }

  return (
    <section className="card" aria-labelledby="xbrl-tags-title">
      <h2 id="xbrl-tags-title">Tags</h2>
      <TagCombobox selected={tags} onChange={onChange} />

      <form className="inline-fields xbrl-save" onSubmit={save}>
        <label className="field-label" htmlFor="xbrl-selection-name">
          Selection name
        </label>
        <input
          id="xbrl-selection-name"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          aria-describedby="xbrl-selection-hint"
        />
        <button type="submit" disabled={saving || !name.trim() || tags.length === 0}>
          {saving ? "Saving…" : "Save as selection"}
        </button>
      </form>
      <p className="help-text" id="xbrl-selection-hint">
        Letters, digits, dot, underscore and hyphen, starting with a letter or digit, e.g. revenue-core. Saving cuts these
        tags out of every stored company. Saving reads every stored company file and can take a few minutes for large lists.
      </p>
      <div aria-live="polite">
        {saving && <p className="status-text">Saving… this reads every stored company file.</p>}
        {saveStatus && <p className={saveStatus.ok ? "status-text" : "error-text"}>{saveStatus.text}</p>}</div>

      <h3>Saved selections</h3>
      {savedError && <p className="error-text">Saved selections could not be loaded ({savedError}).</p>}
      {saved && saved.length === 0 && <p className="muted">No saved selections yet.</p>}
      {saved && saved.length > 0 && (
        <ul className="xbrl-selections">
          {saved.map((s) => (
            <li key={s.name}>
              <span>
                <strong>{s.name}</strong> <span className="muted">{tagCount(s.tags.length)}</span>
              </span>
              <button className="secondary" onClick={() => onChange(s.tags)} aria-label={`Load ${s.name} into the chosen tags`}>
                Load
              </button>
            </li>
          ))}
        </ul>
      )}

      <h3>Tag registry</h3>
      <p className="help-text">Downloads the latest US GAAP, IFRS and DEI taxonomies so every official tag can be chosen.</p>
      <button className="secondary" onClick={updateRegistry} disabled={registry?.busy}>
        Update tag registry
      </button>
      <div aria-live="polite">{registry && <p className={registry.ok ? "status-text" : "error-text"}>{registry.text}</p>}</div>
    </section>
  );
}

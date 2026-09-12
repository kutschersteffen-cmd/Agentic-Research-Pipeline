import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { SearchHit, SearchResultType } from "../types";

const ALL_TYPES: { id: SearchResultType; label: string }[] = [
  { id: "document", label: "Documents" },
  { id: "company", label: "Companies" },
  { id: "taxonomy", label: "Taxonomy" },
];

export function Search() {
  const [q, setQ] = useState("");
  const [types, setTypes] = useState<SearchResultType[]>(["document"]);
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notConfigured, setNotConfigured] = useState(false);

  async function load() {
    if (!q.trim()) {
      setHits([]);
      return;
    }
    setLoading(true);
    setError(null);
    setNotConfigured(false);
    try {
      const res = await api.searchAll(q, types);
      setHits(res.hits);
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      if (message.startsWith("503")) {
        setNotConfigured(true);
      } else {
        setError(message);
      }
      setHits([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const id = setTimeout(load, 300);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, types]);

  function toggleType(id: SearchResultType) {
    setTypes((prev) => (prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id]));
  }

  return (
    <div className="page">
      <h2>Search</h2>
      <section className="card">
        <label className="field-label">Query</label>
        <input
          type="text"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search companies, documents, taxonomy..."
        />
        {ALL_TYPES.map((t) => (
          <label key={t.id} style={{ marginLeft: "1rem" }}>
            <input type="checkbox" checked={types.includes(t.id)} onChange={() => toggleType(t.id)} />
            {" " + t.label}
          </label>
        ))}
      </section>

      <section className="card">
        {notConfigured && (
          <p className="muted">
            Search is not enabled on this server -- an administrator needs to set ARP_OPENSEARCH_URL to turn it on.
          </p>
        )}
        {error && <p className="error">{error}</p>}
        {loading && <p className="muted">Searching...</p>}
        {!loading && !notConfigured && !error && q.trim() && hits.length === 0 && <p className="muted">No results.</p>}
        {hits.length > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                <th>Type</th>
                <th>Title</th>
                <th>Snippet</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {hits.map((h) => (
                <tr key={`${h.type}-${h.id}`}>
                  <td>{h.type}</td>
                  <td>{h.title}</td>
                  <td>{h.snippet}</td>
                  <td>
                    {h.link && (
                      <a href={`${api.base}${h.link}`} target="_blank" rel="noreferrer">
                        Open
                      </a>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

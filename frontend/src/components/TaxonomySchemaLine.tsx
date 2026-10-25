import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useMe } from "../lib/reviewer";
import type { DataPointSchema, Taxonomy } from "../types";
import { ConfirmSignedIn } from "./ConfirmSignedIn";

/** One taxonomy version's generated extraction schema: generate it (analyst), release it (approver). */
export function TaxonomySchemaLine({ taxonomy }: { taxonomy: Taxonomy }) {
  const me = useMe();
  const [schema, setSchema] = useState<DataPointSchema | null | undefined>(undefined);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ratified = taxonomy.status === "ratified";
  const schemaId = `sch_${taxonomy.taxonomy_id}_v${taxonomy.version}`;

  useEffect(() => {
    if (!ratified) return;
    api
      .getTaxonomySchema(taxonomy.taxonomy_id, taxonomy.version)
      .then(setSchema)
      .catch((err: Error) => (err.message.startsWith("404") ? setSchema(null) : setError(err.message)));
  }, [ratified, taxonomy.taxonomy_id, taxonomy.version]);

  async function act(call: () => Promise<DataPointSchema>) {
    setConfirming(false);
    setBusy(true);
    setError(null);
    try {
      setSchema(await call());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!ratified) return <p className="muted">Schema: ratify this version first</p>;
  if (schema === undefined) return error ? <p className="error-text" role="alert">{error}</p> : null;
  return (
    <div className="toolbar">
      {confirming && schema && (
        <ConfirmSignedIn
          title={`Release schema ${schemaId}?`}
          confirmLabel="Release schema"
          onConfirm={() => act(() => api.releaseSchema(schemaId, schema.version ?? 1))}
          onCancel={() => setConfirming(false)}
        >
          <p>Releasing lets Thematic Universe runs and extraction jobs use this schema for final results.</p>
        </ConfirmSignedIn>
      )}
      <span>
        Schema:{" "}
        {schema === null
          ? "Not generated"
          : schema.release_flag
            ? `Released by ${schema.released_by} on ${schema.released_at?.slice(0, 10)}`
            : "Not released"}
      </span>
      {schema === null && me && me.role !== "viewer" && (
        <button onClick={() => act(() => api.generateTaxonomySchema(taxonomy.taxonomy_id, taxonomy.version))} disabled={busy}>
          Generate schema
        </button>
      )}
      {schema && !schema.release_flag && me?.role === "approver" && (
        <button onClick={() => setConfirming(true)} disabled={busy}>
          Release schema
        </button>
      )}
      {error && <p className="error-text" role="alert">{error}</p>}
    </div>
  );
}

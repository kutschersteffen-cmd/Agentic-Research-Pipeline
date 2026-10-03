import { useId, useState } from "react";
import { useMe, useToken } from "../lib/reviewer";

/** Shows who is signed in. Without a valid token it asks for one; the server
 * resolves the token to a user, so the name on every decision is verified. */
export function SignedInAs({ compact = false }: { compact?: boolean }) {
  const me = useMe();
  const [token, setToken] = useToken();
  const [draft, setDraft] = useState("");
  const hintId = useId();
  const cls = compact ? "reviewer-field reviewer-field-compact" : "reviewer-field";
  if (me) {
    return (
      <div className={cls}>
        <span>
          Signed in as {me.name} ({me.role})
        </span>
        {token && (
          <button type="button" className="link-button" onClick={() => setToken("")}>
            Sign out
          </button>
        )}
      </div>
    );
  }
  return (
    <label className={cls}>
      <span>{token ? "Signing in…" : "Access token"}</span>
      <input
        type="password"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={(e) => e.target.value.trim() && setToken(e.target.value.trim())}
        onKeyDown={(e) => e.key === "Enter" && draft.trim() && setToken(draft.trim())}
        placeholder="Paste your token"
        autoComplete="off"
        aria-describedby={hintId}
      />
      <small id={hintId} className={compact ? "visually-hidden" : "reviewer-hint"}>
        Decisions are recorded against the user this token belongs to.
      </small>
    </label>
  );
}

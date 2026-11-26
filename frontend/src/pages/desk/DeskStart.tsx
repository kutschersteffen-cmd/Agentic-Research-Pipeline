import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { errorDetail } from "../../lib/barrier";
import { OrbChat } from "../../components/argus/OrbChat";
import { ScopeChips } from "../../components/argus/ScopeChips";
import type { DeskChatSummary, DeskScopeItem } from "../../types";

export type DeskMode = "quick" | "thorough";

/** The two-button Quick / Thorough toggle. */
export function ModeToggle({ mode, onChange }: { mode: DeskMode; onChange: (mode: DeskMode) => void }) {
  return (
    <div className="desk-mode" role="group" aria-label="How hard to look">
      <button type="button" className="secondary" aria-pressed={mode === "quick"} onClick={() => onChange("quick")}>Quick</button>
      <button type="button" className="secondary" aria-pressed={mode === "thorough"} onClick={() => onChange("thorough")}>Thorough</button>
    </div>
  );
}

/** #/argus/desk: ask about the companies you pick, and the recent chats. */
export function DeskStart() {
  const [scope, setScope] = useState<DeskScopeItem[]>([]);
  const [mode, setMode] = useState<DeskMode>("quick");
  const [chats, setChats] = useState<DeskChatSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listDeskChats().then(setChats, (err) => setError(errorDetail(err as Error)));
  }, []);

  const ask = async (question: string) => {
    try {
      const { id } = await api.createDeskChat();
      await api.putDeskScope(id, scope.map(({ kind, ref }) => ({ kind, ref })));
      await api.postDeskTurn(id, question, mode);
      window.location.hash = `#/argus/desk/${id}`;
      return true;
    } catch (err) {
      setError(errorDetail(err as Error));
      return false;
    }
  };

  return (
    <div className="page desk-page">
      <h1>Research Desk</h1>
      <OrbChat context="Research Desk" phase="READY" placeholder="Ask anything about the companies you pick" ready={scope.length > 0} onAction={ask}>
        <div className="desk-controls">
          <ScopeChips scope={scope} onChange={setScope} />
          <ModeToggle mode={mode} onChange={setMode} />
        </div>
      </OrbChat>
      {error && <p className="error-text" role="alert">{error}</p>}
      <section className="desk-recent" aria-labelledby="desk-recent-h">
        <h2 id="desk-recent-h">Recent chats</h2>
        {chats === null && !error && <p className="muted" role="status">Loading…</p>}
        {chats?.length === 0 && <p className="muted">No chats yet.</p>}
        <ul>
          {chats?.map((c) => <li key={c.id}><a href={`#/argus/desk/${c.id}`}>{c.title}</a></li>)}
        </ul>
      </section>
    </div>
  );
}

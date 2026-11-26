import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { errorDetail } from "../../lib/barrier";
import { OrbChat } from "../../components/argus/OrbChat";
import { ScopeChips } from "../../components/argus/ScopeChips";
import { STAGE_LABEL, StageList, seconds } from "../../components/argus/StageList";
import { FigureCheck } from "../../components/argus/FigureCheck";
import { CitationPanel } from "../../components/argus/CitationPanel";
import { ModeToggle, type DeskMode } from "./DeskStart";
import type { DeskChat as Chat, DeskScopeItem, DeskStage, DeskTurn } from "../../types";

const ordinal = (n: number) => `${n}${n % 100 >= 11 && n % 100 <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] ?? "th"}`;

/** #/argus/desk/<chatId>: the latest question working, its answer, or how the answer was found. */
export function DeskChat({ chatId }: { chatId: string }) {
  const [chat, setChat] = useState<Chat | null>(null);
  const [turn, setTurn] = useState<DeskTurn | null>(null);
  const [stages, setStages] = useState<DeskStage[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [scope, setScope] = useState<DeskScopeItem[]>([]);
  const [mode, setMode] = useState<DeskMode>("quick");
  const [view, setView] = useState<"answer" | "how">("answer");
  const [cited, setCited] = useState<number | null>(null);

  const load = useCallback(async () => {
    let c: Chat;
    try {
      c = await api.getDeskChat(chatId);
    } catch (err) {
      if ((err as Error).message.startsWith("404")) setNotFound(true);
      else setError(errorDetail(err as Error));
      return;
    }
    setChat(c);
    setScope(c.scope);
    setView("answer");
    setCited(null);
    const last = c.turns.at(-1);
    try { // a turn that cannot be read leaves the chat and its earlier questions on screen
      const t = last ? await api.getDeskTurn(last.id) : null;
      setTurn(t);
      setStages(t?.stages ?? []);
    } catch (err) {
      setTurn(null);
      setError(errorDetail(err as Error));
    }
  }, [chatId]);

  useEffect(() => { load(); }, [load]);

  // A running turn: follow its event stream, then read the turn once when it ends.
  const runningId = turn?.status === "running" ? turn.id : null;
  useEffect(() => {
    if (runningId === null) return;
    const stop = new AbortController();
    api.deskTurnEvents(runningId, (s) => setStages((all) => all.map((x) => (x.name === s.name ? s : x))), stop.signal)
      .then(async (end) => {
        if (!end) return;
        const t = await api.getDeskTurn(runningId);
        setTurn(t);
        setStages(t.stages);
      })
      .catch((err) => { if (!stop.signal.aborted) setError(errorDetail(err as Error)); });
    return () => stop.abort();
  }, [runningId]);

  const opener = useRef<HTMLButtonElement | null>(null); // the chip that opened the panel gets focus back
  const closeCitation = useCallback(() => setCited(null), []);
  useEffect(() => { if (cited === null) opener.current?.focus(); }, [cited]);

  if (notFound) return <div className="page desk-page"><p role="alert">Chat not found.</p></div>;
  if (!chat) return <div className="page desk-page">{error ? <p className="error-text" role="alert">{error}</p> : <p className="muted" role="status">Loading…</p>}</div>;

  const running = turn?.status === "running";
  const answer = turn?.status === "done" ? turn.answer : null;
  const citations = answer?.sentences.flatMap((s) => s.citations) ?? [];
  const earlier = chat.turns.slice(0, -1);
  const used = turn?.sources.filter((s) => s.used) ?? [];

  const ask = async (question: string) => {
    try {
      const same = scope.length === chat.scope.length && scope.every((s, i) => s.kind === chat.scope[i].kind && s.ref === chat.scope[i].ref);
      if (!same) await api.putDeskScope(Number(chatId), scope.map(({ kind, ref }) => ({ kind, ref })));
      await api.postDeskTurn(Number(chatId), question, mode);
      setError(null);
      await load();
      return true;
    } catch (err) {
      setError(errorDetail(err as Error));
      return false;
    }
  };

  const href = `#/argus/desk/${chatId}`;

  return (
    <div className="page desk-page">
      <h1>Research Desk</h1>
      <div className={cited !== null ? "desk-layout desk-layout-panel" : "desk-layout"}>
        <div className="desk-main">
          <OrbChat
            context="Research Desk"
            phase={running ? "WORKING" : turn?.status === "failed" ? "FAILED" : turn ? "DONE" : "READY"}
            placeholder="Ask a follow-up or a new question"
            ready={!running}
            onAction={ask}
            say={turn && (
              <div className="desk-question">
                <span className="desk-cap">Your question</span>
                <p>{turn.question}</p>
              </div>
            )}
          >
            {running ? <StageList stages={stages} /> : (
              <div className="desk-controls">
                <ScopeChips scope={scope} onChange={setScope} />
                <ModeToggle mode={mode} onChange={setMode} />
              </div>
            )}
          </OrbChat>
          {error && <p className="error-text" role="alert">{error}</p>}
          {turn?.status === "failed" && <p className="error-text" role="alert">This question failed: {turn.error}</p>}

          {answer && view === "answer" && (
            <article className="desk-answer">
              {answer.sentences[0] && <h2 className="desk-lead">{answer.sentences[0].text}</h2>}
              <FigureCheck check={answer.check} />
              {answer.sentences.map((s) => (
                <p key={s.n} className="desk-sentence" data-status={s.status}>
                  {s.text}
                  {s.status === "calculated" && <span className="desk-mark" data-kind="calculated"> (calculated)</span>}
                  {s.status === "to_check" && <span className="desk-mark" data-kind="to_check"> to check</span>}
                  {s.citations.map((c) => {
                    const at = citations.indexOf(c);
                    return <button key={at} type="button" className="desk-cite" aria-pressed={cited === at} onClick={(e) => { opener.current = e.currentTarget; setCited(at); }}>{c.source}</button>;
                  })}
                </p>
              ))}
              {answer.calculations.filter((c) => !c.error).map((c) => (
                <details key={c.id} className="desk-calc" open>
                  <summary>How the {c.display}{c.unit} was worked out</summary>
                  <code>{c.formula}</code>
                </details>
              ))}
              <p><a href={href} onClick={(e) => { e.preventDefault(); setCited(null); setView("how"); }}>How was this found?</a></p>
            </article>
          )}

          {answer && view === "how" && turn && (
            <article className="desk-how">
              <p><span aria-hidden="true">← </span><a href={href} onClick={(e) => { e.preventDefault(); setView("answer"); }}>Back to the answer</a></p>
              <h2>How this answer was found</h2>
              <p className="muted">{turn.question}</p>
              <h3>Where the time went</h3>
              <ul className="desk-time">
                {turn.stages.filter((s) => s.status !== "skipped").map((s) => (
                  <li key={s.name}><span>{STAGE_LABEL[s.name] ?? s.name}</span> <span className="desk-stage-ms">{s.ms !== null ? seconds(s.ms) : "–"}</span></li>
                ))}
              </ul>
              <h3>The {used.length} passages the answer used</h3>
              <div className="desk-table-wrap">
                <table className="desk-passages">
                  <thead><tr><th>#</th><th>Passage</th><th>Same words</th><th>Same meaning</th><th>Rank</th></tr></thead>
                  <tbody>
                    {used.map((s) => (
                      <tr key={s.n}>
                        <td>{s.n}</td>
                        <td>{(s.text ?? "").slice(0, 200)}<div className="muted">{s.company_name} · {s.filename}</div></td>
                        <td>{s.scores?.bm25?.toFixed(2) ?? "–"}</td>
                        <td>{s.scores?.vector_rank ?? "–"}</td>
                        <td>{ordinal(s.n)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </article>
          )}

          {earlier.length > 0 && (
            <section className="desk-earlier" aria-labelledby="desk-earlier-h">
              <h2 id="desk-earlier-h">Earlier</h2>
              <ul>{earlier.map((t) => <li key={t.id}>{t.question}</li>)}</ul>
            </section>
          )}
        </div>
        {answer && cited !== null && citations[cited] && (
          <CitationPanel key={cited} citations={citations} at={cited} sources={turn!.sources} onMove={setCited} onClose={closeCitation} />
        )}
      </div>
    </div>
  );
}

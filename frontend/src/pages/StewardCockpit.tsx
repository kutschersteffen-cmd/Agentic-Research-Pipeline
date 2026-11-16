import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../api/client";
import {
  ABSTAIN_LABEL,
  CONTRIBUTOR_STATUS,
  SHOWN_ROWS,
  ballotText,
  fmtCount,
  fmtDate,
  fmtDay,
  fmtPct,
  fmtShare,
  fmtTonnes,
  gapText,
  isWeekend,
  monthLabel,
  pct,
  stepTone,
  OTHER_THEME,
  themeLabel,
  themeScale,
  topicNote,
  weekday,
} from "../lib/cockpit";
import type { Cockpit } from "../types";

type Ladder = Cockpit["ladder"];
const WEEKDAYS = ["S", "M", "T", "W", "T", "F", "S"];

/** StewardIQ cockpit (spec stewardship-cockpit): read-only; every figure is the API's, summed or divided at most. */
export function StewardCockpit({ asOf }: { asOf?: string }) {
  const [portfolioId, setPortfolioId] = useState<string | null>(null);
  // The last response stays for the header (scope selector); the body shows only the selected scope's.
  const [result, setResult] = useState<{ scope: string | null; data: Cockpit } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const data = result?.data ?? null;
  const current = !error && result && result.scope === portfolioId ? result.data : null;

  useEffect(() => {
    let live = true;
    setError(null);
    api.getCockpit(asOf, portfolioId).then(
      (d) => live && setResult({ scope: portfolioId, data: d }),
      (e: unknown) => live && setError(e instanceof Error ? e.message : String(e)),
    );
    return () => {
      live = false;
    };
  }, [asOf, portfolioId]);

  return (
    <div className="page cockpit">
      <header className="cockpit-head">
        <div>
          <a className="cockpit-crumb" href="#/stewardiq">StewardIQ</a>
          <h1>Cockpit</h1>
        </div>
        {data && (
          <div className="cockpit-scope">
            <label>
              <span className="cockpit-label">Scope</span>
              <select value={portfolioId ?? ""} onChange={(e) => setPortfolioId(e.target.value || null)}>
                <option value="">All portfolios ({fmtCount(data.portfolios.length)})</option>
                {data.portfolios.map((p) => (
                  <option key={p.portfolio_id} value={p.portfolio_id}>{p.name}</option>
                ))}
              </select>
            </label>
            <span className="cockpit-label">As of {fmtDate(data.as_of)}</span>
            {data.demo && <span className="chip chip-sample">Demo data</span>}
          </div>
        )}
      </header>
      {error && <p className="error-text" role="alert">The cockpit could not be loaded: {error}</p>}
      {!current && !error && <p className="muted" role="status">Loading…</p>}
      {current && <Body key={portfolioId ?? ""} data={current} />}
    </div>
  );
}

function Body({ data }: { data: Cockpit }) {
  return (
    <>
      <KeyFigures data={data} />
      <Strip days={data.days} />
      <ThemeGrid data={data} />
      <ProgrammePanel data={data} />
      {data.emissions && <EmissionsCard emissions={data.emissions} />}
      <div className="cockpit-row">
        <EngagementMeetings rows={data.engagement_meetings} ladder={data.ladder} />
        <ShareholderMeetings rows={data.shareholder_meetings} />
      </div>
      <div className="cockpit-row cockpit-row-3">
        <ControlGaps rows={data.control_gaps} />
        <LadderCard ladder={data.ladder} />
        <VotingCard voting={data.voting} />
      </div>
    </>
  );
}

/** A box that scrolls sideways when its table is wider. Only while it overflows is it a focusable region, so the
 * keyboard reaches the hidden columns and a box that fits is no extra tab stop. */
function Scroll({ label, children }: { label: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [overflows, setOverflows] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const check = () => setOverflows(el.scrollWidth > el.clientWidth);
    check();
    const watch = new ResizeObserver(check);
    watch.observe(el);
    if (el.firstElementChild) watch.observe(el.firstElementChild);
    return () => watch.disconnect();
  }, []);
  return (
    <div ref={ref} className="cockpit-scroll" {...(overflows ? { tabIndex: 0, role: "region", "aria-label": label } : {})}>
      {children}
    </div>
  );
}

function Card({ title, label, children, className = "" }: { title: string; label?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card cockpit-card ${className}`} aria-label={title}>
      <div className="cockpit-card-head">
        <h2>{title}</h2>
        {label}
      </div>
      {children}
    </section>
  );
}

function Figure({ label, value, note, signal = false, bar }: { label: string; value: ReactNode; note: ReactNode; signal?: boolean; bar?: number | null }) {
  return (
    <div className="cockpit-figure">
      <span className="cockpit-label">{label}</span>
      <span className={signal ? "cockpit-figure-value await-text" : "cockpit-figure-value"}>{value}</span>
      {bar !== undefined && (
        <span className="cockpit-meter" aria-hidden="true">
          <span style={{ width: `${bar ?? 0}%` }} />
        </span>
      )}
      <span className="cockpit-figure-note">{note}</span>
    </div>
  );
}

const escalated = (ladder: Ladder) => ladder.filter((s) => s.step >= 2).flatMap((s) => s.companies);

function KeyFigures({ data }: { data: Cockpit }) {
  const { summary: s, voting: v, control_gaps: gaps, ladder, emissions: e } = data;
  const eng = data.engagement_meetings.length;
  const agm = data.shareholder_meetings.length;
  const top = [...ladder].reverse().find((st) => st.step >= 2 && st.companies.length);
  return (
    <section className="cockpit-figures" aria-label="Key figures">
      <Figure
        label="Companies engaged"
        value={<>{fmtCount(s.engaged_selected)}<span className="cockpit-figure-of"> / {fmtCount(s.selected)}</span></>}
        bar={pct(s.engaged_selected, s.selected)}
        note={`${fmtPct(s.engaged_selected, s.selected)} of selected companies`}
      />
      {e && (
        <Figure
          label="Financed emissions covered"
          value={fmtPct(e.engaged_tco2e, e.total_tco2e)}
          bar={pct(e.engaged_tco2e, e.total_tco2e)}
          note={`${fmtTonnes(e.engaged_tco2e)} of ${fmtTonnes(e.total_tco2e)} t CO₂e in engagement`}
        />
      )}
      <Figure label="Next 30 days" value={fmtCount(eng + agm)} note={<>{fmtCount(eng)} engagement meetings<br />{fmtCount(agm)} shareholder meetings</>} />
      <Figure
        label="Control gaps"
        value={fmtCount(gaps.length)}
        signal={gaps.length > 0}
        note={`${fmtCount(gaps.filter((g) => g.gaps.includes("no_objective")).length)} without objective · ${fmtCount(gaps.filter((g) => g.gaps.includes("no_next_meeting")).length)} without next meeting`}
      />
      <Figure label="In escalation" value={fmtCount(escalated(ladder).length)} note={`Highest step: ${top ? top.label : "–"}`} />
      <Figure
        label={`Votes cast, ${v.season}`}
        value={fmtCount(v.votes)}
        note={`${fmtCount(v.meetings)} meetings · ${fmtPct(v.against_management, v.votes)} against management`}
      />
    </section>
  );
}

function Legend({ items }: { items: [string, string][] }) {
  return (
    <span className="cockpit-legend">
      {items.map(([cls, text]) => (
        <span key={text}><span className={`cockpit-swatch ${cls}`} aria-hidden="true" />{text}</span>
      ))}
    </span>
  );
}

function Strip({ days }: { days: Cockpit["days"] }) {
  const max = Math.max(1, ...days.flatMap((d) => [d.engagement_meetings, d.shareholder_meetings]));
  const h = (n: number) => `${(n / max) * 100}%`;
  return (
    <Card title="Next 30 days" label={<Legend items={[["eng", "Engagement meeting"], ["agm", "Shareholder meeting"]]} />}>
      {days.every((d) => !d.engagement_meetings && !d.shareholder_meetings) && <p className="muted">No meetings in the next 30 days.</p>}
      <Scroll label="Next 30 days, by day">
        <ol className="cockpit-strip">
          {days.map((d, i) => (
            <li key={d.date} className={isWeekend(d.date) ? "weekend" : undefined}>
              <span className="visually-hidden">{`${fmtDay(d.date)}: ${d.engagement_meetings} engagement meetings, ${d.shareholder_meetings} shareholder meetings`}</span>
              <span className="cockpit-label" aria-hidden="true">{monthLabel(d.date, i === 0)}</span>
              <span className="cockpit-bars" aria-hidden="true">
                {d.engagement_meetings > 0 && <span className="eng" style={{ height: h(d.engagement_meetings) }} title={`${d.engagement_meetings}`} />}
                {d.shareholder_meetings > 0 && <span className="agm" style={{ height: h(d.shareholder_meetings) }} title={`${d.shareholder_meetings}`} />}
              </span>
              <span className="cockpit-num" aria-hidden="true">{Number(d.date.slice(8, 10))}</span>
              <span className="cockpit-label" aria-hidden="true">{WEEKDAYS[weekday(d.date)]}</span>
            </li>
          ))}
        </ol>
      </Scroll>
    </Card>
  );
}

function Cell({ e, s, max }: { e: number; s: number; max: number }) {
  if (s === 0) return <td className="cockpit-num cockpit-empty-cell">–</td>;
  return (
    <td>
      <span className="cockpit-num">{fmtCount(e)} / {fmtCount(s)}</span>
      <span className="cockpit-cell-bar" aria-hidden="true">
        <span className="track" style={{ width: `${(s / max) * 100}%` }} />
        <span className="fill" style={{ width: `${(e / max) * 100}%` }} />
      </span>
    </td>
  );
}

function ThemeGrid({ data }: { data: Cockpit }) {
  const { themes, tiers, summary } = data;
  const { maxOf, note } = themeScale(themes, summary.selected);
  return (
    <Card
      title="Engaged vs selected, by theme and tier"
      label={<span className="cockpit-label">{fmtCount(summary.engaged_selected)} / {fmtCount(summary.selected)}</span>}
    >
      {summary.selected === 0 ? (
        <p className="muted">No selected companies: no coverage tier is confirmed in this scope.</p>
      ) : (
        <>
        <Scroll label="Engaged vs selected table">
          <table className="cockpit-grid">
            <thead>
              <tr>
                <th scope="col">Theme</th>
                {tiers.map((t) => (
                  <th key={t.tier} scope="col">{t.label}</th>
                ))}
                <th scope="col">Total</th>
              </tr>
              <tr className="cockpit-grid-total">
                <th scope="row">All themes</th>
                {tiers.map((t) => <Cell key={t.tier} e={t.engaged} s={t.selected} max={maxOf(null)} />)}
                <Cell e={summary.engaged_selected} s={summary.selected} max={maxOf(null)} />
              </tr>
            </thead>
            <tbody>
              {themes.map((row) => (
                <tr key={row.theme} className={row.theme === OTHER_THEME ? "cockpit-grid-other" : undefined}>
                  <th scope="row">{themeLabel(row.theme)}</th>
                  {row.tiers.map((c) => <Cell key={c.tier} e={c.engaged} s={c.selected} max={maxOf(row.theme)} />)}
                  <Cell e={row.engaged} s={row.selected} max={maxOf(row.theme)} />
                </tr>
              ))}
            </tbody>
          </table>
        </Scroll>
        <Legend items={[["eng", "Engaged"], ["sel", "Selected"]]} />
        <p className="cockpit-grid-scale">{note}</p>
        </>
      )}
    </Card>
  );
}

/** Spec stewardship-cockpit-programmes: one bar per programme, all on one scale (the largest `selected`). */
function ProgrammePanel({ data }: { data: Cockpit }) {
  const { programmes: rows, programme_totals: t } = data;
  const max = Math.max(1, ...rows.map((r) => r.selected));
  const workbench = "#/stewardship/workbench";
  return (
    <Card
      title="Engaged vs selected, by programme"
      label={rows.length > 0 && <span className="cockpit-label">{fmtCount(t.engaged)} / {fmtCount(t.selected)}</span>}
    >
      {rows.length === 0 ? (
        <>
          <p className="muted">No programme has members yet.</p>
          <a href={workbench}>Open the Workbench →</a>
        </>
      ) : (
        <>
          <ul className="cockpit-programmes">
            {rows.map((r) => (
              <li key={r.programme_id}>
                <span>{r.label}</span>
                {r.selected === 0 ? (
                  <span className="cockpit-num muted">–</span>
                ) : (
                  <span className="cockpit-cell-bar" aria-hidden="true">
                    <span className="track" style={{ width: `${(r.selected / max) * 100}%` }} />
                    <span className="fill" style={{ width: `${(r.engaged / max) * 100}%` }} />
                  </span>
                )}
                <span className="cockpit-num">{r.selected > 0 && `${fmtCount(r.engaged)} / ${fmtCount(r.selected)}`}</span>
                <span className="muted">{r.proposed > 0 && `+${fmtCount(r.proposed)} proposed`}</span>
              </li>
            ))}
          </ul>
          <Legend items={[["eng", "Engaged"], ["sel", "Selected"]]} />
          <p className="muted cockpit-foot">Selected: confirmed programme members. Engaged: with an open engagement.</p>
          <a href={workbench}>Manage programmes in the Workbench →</a>
        </>
      )}
    </Card>
  );
}

type Emissions = NonNullable<Cockpit["emissions"]>;

function EmissionsCard({ emissions: e }: { emissions: Emissions }) {
  const parts: [string, string, number][] = [
    ["eng", "engaged", e.engaged_tco2e],
    ["sel", "selected, not engaged", e.selected_not_engaged_tco2e],
    ["rest", "not selected", e.not_selected_tco2e],
  ];
  return (
    <Card title="Financed emissions in engagement" label={<span className="cockpit-label cockpit-unit">{fmtTonnes(e.total_tco2e)} t CO₂e, scope 1+2</span>}>
      <div className="cockpit-emissions">
        <div>
          <div className="cockpit-stack cockpit-emissions-bar" role="img" aria-label={parts.map(([, l, t]) => `${fmtPct(t, e.total_tco2e)} ${l}`).join(", ")}>
            {parts.filter(([, , t]) => t > 0).map(([cls, , t]) => <span key={cls} className={cls} style={{ flexGrow: t }} />)}
          </div>
          <ul className="cockpit-emissions-legend">
            {parts.map(([cls, l, t]) => (
              <li key={cls}>
                <span className={`cockpit-swatch ${cls}`} aria-hidden="true" />
                <span className="cockpit-num cockpit-emissions-pct">{fmtPct(t, e.total_tco2e)}</span>
                <span>{l}</span>
                <span className="cockpit-num muted">{fmtTonnes(t)} t</span>
              </li>
            ))}
          </ul>
          {e.uncovered_holding_count > 0 && (
            <p className="muted cockpit-foot">
              {fmtCount(e.uncovered_holding_count)} {e.uncovered_holding_count === 1 ? "holding is" : "holdings are"} left out: no company mapped, no EVIC or an EVIC of 0, or no Scope 1 or 2 figure.
            </p>
          )}
        </div>
        <Scroll label="Largest contributors table">
          <table className="cockpit-table cockpit-contributors">
            <thead>
              <tr><th scope="col">Largest contributors</th><th scope="col" className="num">Share</th><th scope="col">Status</th></tr>
            </thead>
            <tbody>
              {e.contributors.map((c) => (
                <tr key={c.company_id}>
                  <td>{c.company}{c.sector && <><span className="visually-hidden"> · </span><br /><span className="muted">{c.sector}</span></>}</td>
                  <td className="cockpit-num num">{fmtShare(c.share)}</td>
                  <td>
                    {c.status === "engaged" || c.status === "in_escalation" ? (
                      <span className={`cockpit-step${c.status === "in_escalation" ? " tone-mid" : ""}`}>{CONTRIBUTOR_STATUS[c.status]}</span>
                    ) : (
                      <span className="muted">{CONTRIBUTOR_STATUS[c.status] ?? c.status}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Scroll>
      </div>
    </Card>
  );
}

function useMore<T>(rows: T[]) {
  const [all, setAll] = useState(false);
  const shown = all ? rows : rows.slice(0, SHOWN_ROWS);
  const button = !all && rows.length > SHOWN_ROWS ? (
    <button type="button" className="link-button" onClick={() => setAll(true)}>All {fmtCount(rows.length)}</button>
  ) : null;
  return [shown, button] as const;
}

function EngagementMeetings({ rows, ladder }: { rows: Cockpit["engagement_meetings"]; ladder: Ladder }) {
  const [shown, more] = useMore(rows);
  return (
    <Card title="Upcoming engagement meetings" label={more}>
      {rows.length === 0 ? (
        <p className="muted">No engagement meetings in the next 30 days.</p>
      ) : (
        <Scroll label="Upcoming engagement meetings table">
          {/* Explicit roles: on a phone the rows are laid out as grids, which drops implicit table semantics in some browsers. */}
          <table className="cockpit-table cockpit-meetings" role="table">
            <thead role="rowgroup">
              <tr role="row"><th scope="col" role="columnheader">Date</th><th scope="col" role="columnheader">Company</th><th scope="col" role="columnheader">Objective</th><th scope="col" role="columnheader">Step</th></tr>
            </thead>
            <tbody role="rowgroup">
              {shown.map((m) => (
                <tr key={m.engagement_id} role="row">
                  <td className="cockpit-num" role="cell">{fmtDay(m.date)}</td>
                  <td role="cell">{m.company}<br /><span className="muted">{m.theme}</span></td>
                  <td role="cell">{m.objective ?? <span className="muted">No objective</span>}</td>
                  <td role="cell"><span className={`cockpit-step tone-${stepTone(m.step)}`}>{m.step} {ladder[m.step - 1]?.label}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Scroll>
      )}
    </Card>
  );
}

function ShareholderMeetings({ rows }: { rows: Cockpit["shareholder_meetings"] }) {
  const [shown, more] = useMore(rows);
  return (
    <Card title="Upcoming shareholder meetings" label={more}>
      {rows.length === 0 ? (
        <p className="muted">No shareholder meetings in the next 30 days.</p>
      ) : (
        <>
          <Scroll label="Upcoming shareholder meetings table">
            <table className="cockpit-table">
              <thead>
                <tr>
                  <th scope="col">Date</th><th scope="col">Company</th><th scope="col" className="num">Items</th>
                  <th scope="col" className="num">Flagged</th><th scope="col">Ballot</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((m) => (
                  <tr key={`${m.company_id}/${m.date}`}>
                    <td className="cockpit-num">{fmtDay(m.date)}</td>
                    <td>{m.run_id ? <a href={`#/voting/${encodeURIComponent(m.run_id)}`}>{m.company}</a> : m.company}</td>
                    <td className="cockpit-num num">{fmtCount(m.items)}</td>
                    <td className="cockpit-num num">{m.flagged === null ? "–" : fmtCount(m.flagged)}</td>
                    <td>
                      <span className={m.action_due ? "cockpit-ballot await-text" : "cockpit-ballot"}>
                        {ballotText(m.ballot_state, m.action_due, m.days_to_meeting)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Scroll>
          <p className="muted cockpit-foot">Flagged: items where the voting policy recommends a vote against management.</p>
        </>
      )}
    </Card>
  );
}

function ControlGaps({ rows }: { rows: Cockpit["control_gaps"] }) {
  const [shown, more] = useMore(rows);
  return (
    <Card
      title="Control gaps"
      label={rows.length > 0 ? <span className="cockpit-card-actions"><span className="cockpit-needs await-text">{fmtCount(rows.length)} need you</span>{more}</span> : null}
    >
      {rows.length === 0 ? (
        <p className="muted">No control gaps.</p>
      ) : (
        <>
          <ul className="cockpit-list">
            {shown.map((g) => (
              <li key={g.engagement_id}>
                <span>
                  {g.company}
                  <br />
                  <span className="muted">{g.theme}{g.open_days !== null && ` · open ${fmtCount(g.open_days)} days`}</span>
                </span>
                <span className="cockpit-gap await-text">
                  {g.gaps.map((k, i) => (
                    <Fragment key={k}>{i > 0 && " · "}<span>{gapText([k])}</span></Fragment>
                  ))}
                </span>
              </li>
            ))}
          </ul>
          <p className="muted cockpit-foot">A gap is an open engagement with no objective or no planned next meeting.</p>
        </>
      )}
    </Card>
  );
}

function LadderCard({ ladder }: { ladder: Ladder }) {
  const beyond = escalated(ladder).length;
  return (
    <Card title="Escalation ladder" label={<span className="cockpit-label">{fmtCount(beyond)} beyond step 1</span>}>
      <ol className="cockpit-ladder">
        {ladder.map((s) => (
          <li key={s.step}>
            <span className="cockpit-num muted">{s.step}</span>
            <span>{s.label}</span>
            <span className={`cockpit-num cockpit-ladder-count${s.companies.length ? "" : " muted"}`}>{fmtCount(s.companies.length)}</span>
            <span className="muted">{s.step > 1 ? s.companies.map((c) => c.company).join(", ") : ""}</span>
          </li>
        ))}
      </ol>
    </Card>
  );
}

function VotingCard({ voting: v }: { voting: Cockpit["voting"] }) {
  const parts: [string, string, number][] = [["for", "for", v.for], ["against", "against", v.against], ["abstain", ABSTAIN_LABEL, v.abstain]];
  if (v.other > 0) parts.push(["other", "other", v.other]);
  return (
    <Card title="Voting, season to date" label={<span className="cockpit-label">{fmtCount(v.votes)} votes</span>}>
      {v.votes === 0 ? (
        <p className="muted">No votes cast in {v.season} yet.</p>
      ) : (
        <>
          <div className="cockpit-stack" role="img" aria-label={parts.map(([, l, n]) => `${fmtPct(n, v.votes)} ${l}`).join(", ")}>
            {parts.filter(([, , n]) => n > 0).map(([cls, , n]) => <span key={cls} className={cls} style={{ flexGrow: n }} />)}
          </div>
          <div className="cockpit-stack-legend">
            {parts.map(([cls, l, n]) => (
              <span key={cls}><span className={`cockpit-swatch ${cls}`} aria-hidden="true" /><span className="cockpit-num">{fmtCount(n)}</span> {l} ({fmtPct(n, v.votes)})</span>
            ))}
          </div>
        </>
      )}
      <div className="cockpit-label cockpit-topics-head">Against management, by topic</div>
      <ul className="cockpit-topics">
        {v.topics.map((t) => (
          <li key={t.topic}>
            <span>{t.topic}</span>
            <span className="cockpit-topic-bar" aria-hidden="true"><span style={{ width: `${pct(t.against_management, t.votes) ?? 0}%` }} /></span>
            <span className="cockpit-num">{fmtPct(t.against_management, t.votes)} <span className="muted">{topicNote(t)}</span></span>
          </li>
        ))}
      </ul>
      <p className="muted cockpit-foot">Abstentions never count as against management. A withhold counts as against management only when management recommended for.</p>
    </Card>
  );
}

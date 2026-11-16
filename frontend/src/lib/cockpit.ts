// StewardIQ cockpit (spec stewardship-cockpit): the page's wording and number formats. Every number comes from
// GET /api/stewardship/cockpit; these only format it, add it up or take a percentage of it.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** The API path for a route's optional `as_of` segment (`#/stewardiq/cockpit/<as_of>`) and scope. */
export function cockpitPath(asOf?: string, portfolioId?: string | null): string {
  const q = new URLSearchParams();
  if (portfolioId) q.set("portfolio_id", portfolioId);
  if (asOf) q.set("as_of", asOf);
  const s = q.toString();
  return `/api/stewardship/cockpit${s ? `?${s}` : ""}`;
}

/** Whole percent, rounded half up; null when there is nothing to divide by. */
export function pct(part: number, whole: number): number | null {
  return whole > 0 ? Math.floor((part * 200 + whole) / (2 * whole)) : null;
}

export function fmtPct(part: number, whole: number): string {
  const p = pct(part, whole);
  return p === null ? "–" : `${p}%`;
}

export const fmtCount = (n: number): string => n.toLocaleString("en-US");

function ymd(iso: string): [number, number, number] {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return [y, m, d];
}

/** "17 Nov 2026" */
export function fmtDate(iso: string): string {
  const [y, m, d] = ymd(iso);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

/** "17 Nov" */
export function fmtDay(iso: string): string {
  const [, m, d] = ymd(iso);
  return `${d} ${MONTHS[m - 1]}`;
}

export function weekday(iso: string): number {
  const [y, m, d] = ymd(iso);
  return new Date(Date.UTC(y, m - 1, d)).getUTCDay();
}

export const isWeekend = (iso: string): boolean => [0, 6].includes(weekday(iso));

export function monthLabel(iso: string, first: boolean): string {
  const [, m, d] = ymd(iso);
  return first || d === 1 ? MONTHS[m - 1] : "";
}

const BALLOT: Record<string, string> = { cast: "Cast", decided: "Decided, not cast", awaiting: "Awaiting decision", not_started: "Not started" };

export function ballotText(state: string, actionDue: boolean, days: number): string {
  if (!actionDue) return BALLOT[state] ?? state;
  if (days <= 0) return "Decision due today";
  return days === 1 ? "Decision due in 1 day" : `Decision due in ${days} days`;
}

const GAP: Record<string, string> = { no_objective: "No objective", no_next_meeting: "No next meeting" };
export const gapText = (gaps: string[]): string => gaps.map((g) => GAP[g] ?? g).join(" · ");

/** Escalation step tone: status colours, never the signal (DESIGN.md). */
export const stepTone = (step: number): "neutral" | "mid" | "low" => (step <= 1 ? "neutral" : step <= 3 ? "mid" : "low");

export const SHOWN_ROWS = 6;

/** tCO₂e as whole tonnes with thousands separators ("37,936"); above 0 and below 1 t keeps two decimals, so no amount reads 0. */
export const fmtTonnes = (tco2e: number): string =>
  tco2e.toLocaleString("en-US", { maximumFractionDigits: tco2e > 0 && tco2e < 1 ? 2 : 0 });

/** A 0–1 share (4 decimals) as a whole percent, rounded half up. */
export const fmtShare = (share: number): string => fmtPct(Math.round(share * 10000), 10000);

export const CONTRIBUTOR_STATUS: Record<string, string> = {
  in_escalation: "In escalation",
  engaged: "Engaged",
  selected: "Selected",
  not_selected: "Not selected",
};

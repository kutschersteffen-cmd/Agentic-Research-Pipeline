export function ConfidenceBadge({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const cls = value >= 0.8 ? "badge badge-high" : value >= 0.5 ? "badge badge-mid" : "badge badge-low";
  return <span className={cls}>{pct}%</span>;
}

export function VerdictBadge({ verdict }: { verdict: string }) {
  const cls = verdict === "include" ? "badge badge-high" : verdict === "exclude" ? "badge badge-neutral" : "badge badge-mid";
  return <span className={cls}>{verdict}</span>;
}

export function GroundedBadge({ grounded }: { grounded: boolean }) {
  return <span className={grounded ? "badge badge-high" : "badge badge-low"}>{grounded ? "grounded" : "ungrounded"}</span>;
}

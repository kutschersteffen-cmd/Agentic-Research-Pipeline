// "Why this tier" links: one per framework whose latest publication has a row for the company.

type Row = { entity_id: string; status: string; tier_name: string | null };
type Snapshot = { snapshot_id: string; framework_id: string; framework_name: string; published_at: string; rows: Row[] };

export type WhyLink = { label: string; snapshotId: string; entityId: string };

export function whyLinks(issuerId: string, published: Snapshot[]): WhyLink[] {
  const latest = new Map<string, Snapshot>();
  for (const s of published) {
    const seen = latest.get(s.framework_id);
    if (!seen || s.published_at > seen.published_at) latest.set(s.framework_id, s);
  }
  return [...latest.values()]
    .sort((a, b) => a.framework_name.localeCompare(b.framework_name))
    .flatMap((s) => {
      const row = s.rows.find((r) => r.entity_id === issuerId);
      if (!row) return [];
      const what = row.status === "no_score" ? "no score" : row.tier_name ?? row.status;
      return [{ label: `Why: ${s.framework_name} ${what}`, snapshotId: s.snapshot_id, entityId: issuerId }];
    });
}

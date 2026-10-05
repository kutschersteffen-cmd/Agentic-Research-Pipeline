import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { embedErrorText } from "../../lib/biEmbed";
import type { DashboardItem } from "../../types";
import { ProfileActionStrip } from "./ProfileActionStrip";
import { EmbeddedDashboard } from "./SupersetBI";

const PROFILE_SLUG = "arp-company-profile";

/** Company Profile (spec §6, hybrid): the native action strip above, the Superset
 * `arp-company-profile` dashboard below. The picked issuer reaches the dashboard as
 * row-level security in the guest token, so the dashboard shows that issuer only. */
export function CompanyProfiles() {
  const [companyId, setCompanyId] = useState("");
  const [dashboard, setDashboard] = useState<DashboardItem | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.biDashboards().then(
      (ds) => setDashboard(ds.find((d) => d.slug === PROFILE_SLUG) ?? null),
      (e) => setError(embedErrorText(String(e instanceof Error ? e.message : e))),
    );
  }, []);

  return (
    <>
      <ProfileActionStrip companyId={companyId} onCompany={setCompanyId} />
      <section className="card">
        <h2>Profile dashboard</h2>
        {error ? (
          <p className="error-text" role="alert">The profile dashboard could not be loaded: {error}</p>
        ) : dashboard === undefined ? (
          <p className="muted" aria-live="polite">Loading dashboard…</p>
        ) : dashboard === null ? (
          <p className="muted">No <code>{PROFILE_SLUG}</code> dashboard in Superset yet — run <code>arp bi bootstrap</code>.</p>
        ) : !companyId ? (
          <p className="muted">Pick an issuer above to show its profile dashboard.</p>
        ) : (
          <EmbeddedDashboard key={`${dashboard.id}:${companyId}`} dashboardId={dashboard.id} title={dashboard.title} companyId={companyId} />
        )}
      </section>
    </>
  );
}

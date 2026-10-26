// Theme dossier display rules: state labels, their colour classes, step link text and the shelved banner.
// The states themselves are derived by the backend (arp/themes/dossiers.py).
import type { Dossier, DossierItem, DossierStepState } from "../types.ts";

export const STATE_LABEL: Record<DossierStepState, string> = {
  done: "Done",
  waiting: "Waiting",
  running: "Running",
  failed: "Failed",
  not_started: "Not started",
  skipped: "Skipped",
  not_built: "Coming later",
};

// Waiting is on a person, so it alone takes the signal (DESIGN.md, The One Signal Rule).
export const STATE_CLASS: Record<DossierStepState, string> = {
  done: "status-pill status-completed",
  waiting: "status-pill dossier-waiting",
  running: "status-pill status-running",
  failed: "status-pill status-failed",
  not_started: "status-pill status-pending",
  skipped: "status-pill status-pending",
  not_built: "status-pill status-pending dossier-not-built",
};

export const dossierHref = (id: string) => `#/themes/${encodeURIComponent(id)}`;

export function stepLinkText(number: number, href: string): string {
  if (number === 4) return href === "#/theme" ? "Find companies" : "Open the run";
  if (number === 3) return "Open research";
  if (number === 5) return "Open position and standards";
  return number === 1 ? "Open Emerging Themes" : "Open the Taxonomy Library";
}

export function shelvedBanner(d: Pick<Dossier, "status" | "shelved_by" | "shelved_at" | "shelve_reason">): string | null {
  if (d.status !== "shelved") return null;
  return `Shelved by ${d.shelved_by} on ${(d.shelved_at ?? "").slice(0, 10)}: ${d.shelve_reason}`;
}

export const visibleDossiers = (items: DossierItem[], showShelved: boolean) =>
  showShelved ? items : items.filter((d) => d.status !== "shelved");

/** The dossier opened from an Emerging Themes candidate, if one has it as origin. */
export const dossierOfCandidate = (items: DossierItem[], runId: string, themeId: string) =>
  items.find((d) => d.origin === "candidate" && d.run_id === runId && d.theme_id === themeId);

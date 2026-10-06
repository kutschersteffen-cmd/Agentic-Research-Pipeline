export type Status = "await" | "run" | "done";
export type Rating = "H" | "M" | "L";
export interface Evidence {
  code: string;
  text: string;
  rating: Rating;
  conf: number;
  src: string;
}
export interface Run {
  id: string;
  name: string;
  scope: string;
  status: Status;
  evidence: Evidence[];
  verdict: string;
  /** CLI command shown when approved */
  approveCmd: string;
}

const E = (code: string, text: string, rating: Rating, conf: number, src: string): Evidence => ({ code, text, rating, conf, src });

export const RUNS: Run[] = [
  { id: "r-0412", name: "transition-barrier refresh", scope: "Steel / EU", status: "await", approveCmd: "arp transition-barrier refresh",
    evidence: [E("OGU-R1", "EU CBAM text: free allocation phase-out confirmed", "H", 0.92, "eur-lex 2023/956 art.31"), E("STL-C3", "Capex guidance disagrees with plan page 41", "M", 0.61, "ArcelorMittal CMD 2025"), E("STL-T2", "H2-DRI offtake unsigned; MoU only", "L", 0.44, "press release 2026-03")],
    verdict: "Rate Steel/EU as HIGH barrier. 2 of 3 cells are backed by primary text." },
  { id: "r-0411", name: "voting review", scope: "AGM batch 14", status: "await", approveCmd: "arp voting cast r-0411",
    evidence: [E("VOT-07", "Resolution 9 conflicts with climate policy s.3.2", "H", 0.88, "proxy statement p.22"), E("VOT-11", "Director tenure 14y exceeds policy cap", "H", 0.95, "board bios")],
    verdict: "Vote AGAINST resolutions 9 and 11 per policy." },
  { id: "r-0409", name: "theme classify-lifecycle", scope: "Emerging themes", status: "await", approveCmd: "arp theme resume r-0409",
    evidence: [E("THM-31", "Green hydrogen: pilot -> early commercial", "M", 0.7, "IEA outlook 2026"), E("THM-33", "Grid storage lifecycle ambiguous", "L", 0.38, "2 conflicting sources")],
    verdict: "Promote THM-31; send THM-33 back for more sources." },
  { id: "r-0408", name: "documents reground", scope: "Cement filings", status: "run", approveCmd: "arp runs show r-0408",
    evidence: [E("DOC-88", "Re-anchoring 41 of 60 quotes", "M", 0.68, "in progress")],
    verdict: "Running. Nothing to decide yet." },
  { id: "r-0405", name: "climate waci", scope: "Portfolio P3", status: "done", approveCmd: "arp climate waci --portfolio P3",
    evidence: [E("WACI", "Weighted avg carbon intensity 118 tCO2e/$M", "H", 0.97, "holdings 2026-09-30")],
    verdict: "Ratified by S. Kutscher, 2026-10-03." },
  { id: "r-0402", name: "publish run", scope: "Q3 report", status: "done", approveCmd: "arp publish run r-0402",
    evidence: [E("PUB-1", "All 14 claims carry signed evidence", "H", 0.99, "audit log")],
    verdict: "Published 2026-10-02." },
];

/** Verified against backend/arp/cli (Typer apps + commands). */
export const CMDS: string[] = [
  "arp runs list", "arp runs show <id>", "arp runs diff <a> <b>", "arp runs cancel <id>", "arp runs results <id>",
  "arp decision list", "arp decision show <id>", "arp decision ratify <id>", "arp decision audit <id>",
  "arp voting ballots", "arp voting review <id>", "arp voting cast <id>",
  "arp transition-barrier scores --rating H", "arp transition-barrier sources --code <code>", "arp transition-barrier staleness", "arp transition-barrier refresh",
  "arp theme classify-lifecycle", "arp theme resume <id>", "arp documents reground", "arp climate waci --portfolio P3",
  "arp engagement record-list", "arp engagement issue-escalate", "arp golden-set run", "arp publish run", "arp publish withdraw",
  "arp calibration run", "arp discover run",
];

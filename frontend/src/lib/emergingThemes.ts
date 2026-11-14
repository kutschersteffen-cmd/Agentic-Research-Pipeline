// Emerging Themes wording and polling rules (spec showcase-themes-fixes, section 7).

export const SCANNING = "Scanning… candidates appear when the scan finishes.";
export const NOVELTY_HELP = "How different this cluster is from themes in earlier scans. 100% on a first scan.";
export const NO_COMPANIES = "None in your universe";
export const SCHEDULE_SAVED = "Schedule saved.";

/** A scan still working: the page keeps polling while one is listed. */
export const scanActive = (status: string | undefined): boolean => status === "running" || status === "pending";

/** The schedule form's own check; null when the interval may be sent. NaN (an emptied field) counts as too small. */
export const intervalError = (hours: number): string | null => (hours >= 1 ? null : "Enter an interval of at least 1 hour.");

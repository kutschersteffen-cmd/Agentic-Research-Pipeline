import type { ReactElement } from "react";

/** Card-header icons for every flow canvas: one 24-grid stroke family, ink only. */
const ICON = { width: 15, height: 15, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.9, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
const STEP_ICONS: Record<string, ReactElement> = {
  gather_evidence: (
    <svg {...ICON}>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="M15.3 15.3 20.5 20.5" />
    </svg>
  ),
  extract: (
    <svg {...ICON}>
      <path d="M4 20h4L19 9l-4-4L4 16z" />
      <path d="m13.5 6.5 4 4" />
    </svg>
  ),
  verify: (
    <svg {...ICON}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="m8.5 12 2.5 2.5 4.5-5" />
    </svg>
  ),
  aggregate: (
    <svg {...ICON}>
      <path d="M12 3 4.5 6v5.5c0 4.5 3.2 8 7.5 9.5 4.3-1.5 7.5-5 7.5-9.5V6z" />
    </svg>
  ),
  company: (
    <svg {...ICON}>
      <path d="m12 3 9 5-9 5-9-5z" />
      <path d="m3 13 9 5 9-5" />
    </svg>
  ),
  rules: (
    <svg {...ICON}>
      <path d="M12 4v16M6 20h12M4 8h16M6 8l-3 6a3 3 0 0 0 6 0zM18 8l-3 6a3 3 0 0 0 6 0z" />
    </svg>
  ),
  finalize: (
    <svg {...ICON}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M8.5 12h7" />
    </svg>
  ),
};
STEP_ICONS.answer = STEP_ICONS.extract;
STEP_ICONS.identity = (
  <svg {...ICON}>
    <rect x="3" y="5" width="18" height="14" rx="2" />
    <circle cx="9" cy="11" r="2.2" />
    <path d="M5.8 16c.6-1.6 1.8-2.4 3.2-2.4s2.6.8 3.2 2.4M14.5 10h4M14.5 13.5h3" />
  </svg>
);
STEP_ICONS.content_search = (
  <svg {...ICON}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M3.5 12h17M12 3.5c2.4 2.4 3.5 5.2 3.5 8.5s-1.1 6.1-3.5 8.5c-2.4-2.4-3.5-5.2-3.5-8.5S9.6 5.9 12 3.5z" />
  </svg>
);
STEP_ICONS.document_mgmt = (
  <svg {...ICON}>
    <path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z" />
  </svg>
);
STEP_ICONS.parse_index = (
  <svg {...ICON}>
    <path d="M6 3.5h8l4 4v13H6z" />
    <path d="M9 11h6M9 14.5h6M9 18h4" />
  </svg>
);

// Extraction stage overview (StageFlowChart)
STEP_ICONS.companies = STEP_ICONS.company;
STEP_ICONS.identify = STEP_ICONS.identity;
STEP_ICONS.documents = STEP_ICONS.document_mgmt;
STEP_ICONS.schema = STEP_ICONS.parse_index;
STEP_ICONS.scoring = STEP_ICONS.aggregate;
STEP_ICONS.results = STEP_ICONS.verify;
// Stewardship stages (steward flow)
STEP_ICONS.monitoring = (
  <svg {...ICON}>
    <path d="M2.5 12s3.5-6.5 9.5-6.5 9.5 6.5 9.5 6.5-3.5 6.5-9.5 6.5S2.5 12 2.5 12z" />
    <circle cx="12" cy="12" r="2.8" />
  </svg>
);
STEP_ICONS.selection = (
  <svg {...ICON}>
    <path d="M3.5 5h17l-6.5 7.5V19l-4 1.5v-8z" />
  </svg>
);
STEP_ICONS.drafting = STEP_ICONS.extract;
STEP_ICONS.voting = (
  <svg {...ICON}>
    <rect x="4" y="10" width="16" height="10.5" rx="1.5" />
    <path d="M8 10V4.5h8V10M10 7.5l1.5 1.5 3-3" />
  </svg>
);
STEP_ICONS.checkpoint = (
  <svg {...ICON}>
    <path d="M5 21V4M5 4.5h12l-2.5 4 2.5 4H5" />
  </svg>
);
STEP_ICONS.tracking = (
  <svg {...ICON}>
    <path d="M3.5 20.5h17M5 16l4.5-5 3.5 3 6-7" />
  </svg>
);
STEP_ICONS.client_policy = STEP_ICONS.aggregate;
STEP_ICONS.reporting = STEP_ICONS.parse_index;

export const flowIcon = (id: string): ReactElement | null => STEP_ICONS[id] ?? (id.startsWith("finalize") ? STEP_ICONS.finalize : null);

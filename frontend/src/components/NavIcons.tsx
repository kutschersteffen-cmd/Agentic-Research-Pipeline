import type { ReactElement } from "react";

const ICON_PROPS = {
  width: 17,
  height: 17,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.9,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

// One consistent stroke-icon set for the sidebar nav, keyed by tab id (see
// App.tsx's TABS). Kept as inline SVG (not a font/emoji) so it recolors
// with currentColor and stays crisp at any zoom.
export const NAV_ICONS: Record<string, ReactElement> = {
  dashboard: (
    <svg {...ICON_PROPS}>
      <rect x="3" y="3" width="8" height="8" rx="1.5" />
      <rect x="13" y="3" width="8" height="8" rx="1.5" />
      <rect x="3" y="13" width="8" height="8" rx="1.5" />
      <rect x="13" y="13" width="8" height="8" rx="1.5" />
    </svg>
  ),
  search: (
    <svg {...ICON_PROPS}>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <line x1="15.3" y1="15.3" x2="20.5" y2="20.5" />
    </svg>
  ),
  theme: (
    <svg {...ICON_PROPS}>
      <path d="M12 3 L21 8 L12 13 L3 8 Z" />
      <path d="M3 13 L12 18 L21 13" />
      <path d="M3 17 L12 22 L21 17" />
    </svg>
  ),
  taxonomy: (
    <svg {...ICON_PROPS}>
      <path d="M4 5a2 2 0 0 1 2-2h6v18H6a2 2 0 0 1-2-2Z" />
      <path d="M20 5a2 2 0 0 0-2-2h-6v18h6a2 2 0 0 0 2-2Z" />
    </svg>
  ),
  backgroundAgents: (
    <svg {...ICON_PROPS}>
      <path d="M3 12h4l2-7 4 14 2-7h6" />
    </svg>
  ),
  extraction: (
    <svg {...ICON_PROPS}>
      <path d="M4 4 H20 L14 12 V19 L10 21 V12 Z" />
    </svg>
  ),
  transitionPlan: (
    <svg {...ICON_PROPS}>
      <path d="M12 3 L20 6 V12 C20 17 16.5 20.5 12 22 C7.5 20.5 4 17 4 12 V6 Z" />
    </svg>
  ),
  identity: (
    <svg {...ICON_PROPS}>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <circle cx="9" cy="11" r="2.1" />
      <path d="M6 16c0-2 1.5-3 3-3s3 1 3 3" />
      <line x1="14" y1="9" x2="18" y2="9" />
      <line x1="14" y1="13" x2="18" y2="13" />
    </svg>
  ),
  discovery: (
    <svg {...ICON_PROPS}>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18" />
      <path d="M12 3c2.5 2.5 3.5 6 3.5 9s-1 6.5-3.5 9c-2.5-2.5-3.5-6-3.5-9s1-6.5 3.5-9z" />
    </svg>
  ),
  "portfolio-monitoring": (
    <svg {...ICON_PROPS}>
      <rect x="4" y="12" width="4" height="8" rx="0.5" />
      <rect x="10" y="7" width="4" height="13" rx="0.5" />
      <rect x="16" y="3" width="4" height="17" rx="0.5" />
    </svg>
  ),
  review: (
    <svg {...ICON_PROPS}>
      <path d="M9 6h11" />
      <path d="M9 12h11" />
      <path d="M9 18h11" />
      <path d="M4 6l1 1 1.5-1.5" />
      <path d="M4 12l1 1 1.5-1.5" />
      <path d="M4 18l1 1 1.5-1.5" />
    </svg>
  ),
  history: (
    <svg {...ICON_PROPS}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3.5 2" />
    </svg>
  ),
  engagement: (
    <svg {...ICON_PROPS}>
      <circle cx="9" cy="12" r="4.5" />
      <circle cx="15" cy="12" r="4.5" />
    </svg>
  ),
  voting: (
    <svg {...ICON_PROPS}>
      <circle cx="12" cy="12" r="9" />
      <path d="M8 12.3 L11 15.3 L16.3 9.3" />
    </svg>
  ),
  reporting: (
    <svg {...ICON_PROPS}>
      <rect x="3" y="4" width="18" height="12" rx="1.5" />
      <line x1="12" y1="16" x2="12" y2="20" />
      <line x1="8" y1="20" x2="16" y2="20" />
    </svg>
  ),
  library: (
    <svg {...ICON_PROPS}>
      <path d="M3 7.5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />
    </svg>
  ),
};

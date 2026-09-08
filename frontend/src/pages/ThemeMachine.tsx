import { useState } from "react";
import { EmergingThemes } from "./EmergingThemes";
import { TaxonomyLibrary } from "./TaxonomyLibrary";
import { ThemeBuilder } from "./ThemeBuilder";

const SUB_TABS = [
  { id: "emerging", label: "Emerging Themes" },
  { id: "taxonomy", label: "Taxonomy Library" },
  { id: "thematic", label: "Thematic Universe" },
] as const;

interface Props {
  onSendToExtraction?: (path: string, count: number) => void;
  initialSub?: string | null;
}

/** The theme-discovery-to-investable-universe pipeline in one place: scan
 * public signal for candidate themes, promote the ones worth formalizing
 * into a versioned taxonomy, then screen a company universe against it. */
export function ThemeMachine({ onSendToExtraction, initialSub }: Props = {}) {
  const [sub, setSub] = useState<(typeof SUB_TABS)[number]["id"]>(
    (SUB_TABS.some((t) => t.id === initialSub) ? initialSub : "emerging") as (typeof SUB_TABS)[number]["id"],
  );
  const [pendingTaxonomyId, setPendingTaxonomyId] = useState<string | null>(null);

  function sendToTaxonomyLibrary(taxonomyId: string) {
    setPendingTaxonomyId(taxonomyId);
    setSub("taxonomy");
  }

  function sendToThematicUniverse(taxonomyId: string) {
    setPendingTaxonomyId(taxonomyId);
    setSub("thematic");
  }

  return (
    <div>
      <nav className="sub-nav app-nav">
        {SUB_TABS.map((t) => (
          <button key={t.id} className={t.id === sub ? "nav-tab active" : "nav-tab"} onClick={() => setSub(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>
      {sub === "emerging" && <EmergingThemes onPromoted={sendToTaxonomyLibrary} />}
      {sub === "taxonomy" && <TaxonomyLibrary onUseInTheme={sendToThematicUniverse} />}
      {sub === "thematic" && <ThemeBuilder onSendToExtraction={onSendToExtraction} pendingTaxonomyId={pendingTaxonomyId} />}
    </div>
  );
}

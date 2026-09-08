import { useState } from "react";
import { IdentityResolution } from "./IdentityResolution";
import { DocumentDiscovery } from "./DocumentDiscovery";

const SUB_TABS = [
  { id: "identity", label: "Identity Resolution" },
  { id: "discovery", label: "Document Discovery" },
] as const;

interface Props {
  initialSub?: string | null;
}

/** Company onboarding, in pipeline order: resolve a raw company list to
 * websites/CIKs, then crawl each resolved homepage for documents. */
export function IdentityDiscovery({ initialSub }: Props = {}) {
  const [sub, setSub] = useState<(typeof SUB_TABS)[number]["id"]>(
    (SUB_TABS.some((t) => t.id === initialSub) ? initialSub : "identity") as (typeof SUB_TABS)[number]["id"],
  );
  const [pendingDiscoveryUniverse, setPendingDiscoveryUniverse] = useState<{ path: string; count: number } | null>(null);

  function sendToDiscovery(path: string, count: number) {
    setPendingDiscoveryUniverse({ path, count });
    setSub("discovery");
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
      {sub === "identity" && <IdentityResolution onSendToDiscovery={sendToDiscovery} />}
      {sub === "discovery" && <DocumentDiscovery pendingUniverse={pendingDiscoveryUniverse} />}
    </div>
  );
}

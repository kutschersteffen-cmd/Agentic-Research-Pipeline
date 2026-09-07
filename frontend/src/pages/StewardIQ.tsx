import { useState } from "react";
import { Extraction } from "./Extraction";
import { TransitionPlanAssessment } from "./TransitionPlanAssessment";

const SUB_TABS = [
  { id: "extraction", label: "Extraction" },
  { id: "transitionPlan", label: "Transition Plan Assessment" },
] as const;

interface Props {
  pendingUniverse?: { path: string; count: number } | null;
}

/** Schema-driven document research: run either the free-form/company-financials
 * extraction engine or the 64-indicator transition-plan assessment against
 * the same kind of company universe. */
export function StewardIQ({ pendingUniverse }: Props = {}) {
  const [sub, setSub] = useState<(typeof SUB_TABS)[number]["id"]>("extraction");

  return (
    <div>
      <nav className="sub-nav app-nav">
        {SUB_TABS.map((t) => (
          <button key={t.id} className={t.id === sub ? "nav-tab active" : "nav-tab"} onClick={() => setSub(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>
      {sub === "extraction" && <Extraction pendingUniverse={pendingUniverse} />}
      {sub === "transitionPlan" && <TransitionPlanAssessment pendingUniverse={pendingUniverse} />}
    </div>
  );
}

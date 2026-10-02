import { useReducer, useState } from "react";
import { IdentityStage } from "../components/IdentityStage";
import { SourcePanel, type ActiveSource } from "../components/SourcePanel";
import { flowReducer, initialFlow } from "../lib/stagedFlow";
import { useReviewer } from "../lib/reviewer";

interface Props {
  onSendToDiscovery?: (path: string, count: number) => void;
}

export function IdentityResolution({ onSendToDiscovery }: Props = {}) {
  const [flow, dispatch] = useReducer(flowReducer, initialFlow);
  const [reviewer] = useReviewer();
  const [activeSource, setActiveSource] = useState<ActiveSource | null>(null);
  const out = flow.identify.state === "done" ? flow.identify.output : null;

  return (
    <div className="page">
      <h1>Identity Resolution</h1>
      <p className="help-text">Resolve company names to a verified website and CIK before document discovery. Anything ambiguous goes to the Review Queue instead of being guessed.</p>

      <section className="card">
        <h2>Resolve identity</h2>
        <IdentityStage input={null} stage={flow.identify} dispatch={dispatch} view="run" reviewer={reviewer} onOpenSource={setActiveSource} />
        {out && (
          <div className="toolbar">
            <button onClick={() => onSendToDiscovery?.(out.path, out.count)}>Go to Document Discovery &rarr;</button>
          </div>
        )}
      </section>
      {activeSource && <SourcePanel source={activeSource} onClose={() => setActiveSource(null)} />}
    </div>
  );
}

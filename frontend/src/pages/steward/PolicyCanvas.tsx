import "@gorules/jdm-editor/dist/style.css";
import { DecisionGraph, JdmConfigProvider, type DecisionGraphType } from "@gorules/jdm-editor";
import { useEditorTheme } from "../../lib/editorTheme";

/** The rule graph editor (about 4 MB): its own chunk, loaded only when a studio shows a policy graph. */
export default function PolicyCanvas({ graph, onChange }: { graph: Record<string, unknown>; onChange: (g: Record<string, unknown>) => void }) {
  const editorTheme = useEditorTheme();
  return (
    <div className="card rule-canvas studio-canvas">
      <JdmConfigProvider theme={editorTheme}>
        <DecisionGraph
          value={graph as unknown as DecisionGraphType}
          onChange={(next) => {
            if (JSON.stringify(next) !== JSON.stringify(graph)) onChange(next as unknown as Record<string, unknown>);
          }}
        />
      </JdmConfigProvider>
    </div>
  );
}

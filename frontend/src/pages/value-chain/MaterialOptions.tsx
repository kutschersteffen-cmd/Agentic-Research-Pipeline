import { api } from "../../api/client";
import { useVcQuery } from "./useVcQuery";

/** One <optgroup> per material group of the build, in /status order; option values are `<prefix><key>`.
 * Renders nothing until /status answers, or when it fails, so the other options keep working. */
export function MaterialOptions({ prefix }: { prefix: string }) {
  const materials = useVcQuery(() => api.valueChainStatus(), []).data?.materials ?? [];
  return [...new Set(materials.map((m) => m.group))].map((g) => (
    <optgroup key={g} label={g}>
      {materials
        .filter((m) => m.group === g)
        .map((m) => (
          <option key={m.key} value={prefix + m.key}>
            {m.label}
          </option>
        ))}
    </optgroup>
  ));
}

import { COLUMN_ROLES, type ColumnProfile, type ColumnRole, type Direction, type MechanismConfig, type RoleProposal } from "../types";

function roleOf(config: MechanismConfig, column: string): ColumnRole {
  if (config.criteria.some((c) => c.column === column)) return "criterion";
  if (config.gates.some((g) => g.column === column)) return "gate";
  if (config.label_column === column) return "label";
  if (config.size_column === column) return "size";
  if (config.segment_column === column) return "segment";
  return "excluded";
}

/** Types come from the values, not the headers. Direction is the one
 * inference worth checking every time: a wrong direction inverts the
 * ranking and nothing on the screen looks wrong. */
export function ColumnProfileTable({
  profiles,
  proposals,
  config,
  onSetRole,
  onSetDirection,
}: {
  profiles: ColumnProfile[];
  proposals: RoleProposal[];
  config: MechanismConfig;
  onSetRole: (column: string, role: ColumnRole) => void;
  onSetDirection: (column: string, direction: Direction) => void;
}) {
  const proposalByColumn = new Map(proposals.map((p) => [p.column, p]));
  const directionOf = (column: string): Direction =>
    config.criteria.find((c) => c.column === column)?.direction ?? proposalByColumn.get(column)?.direction ?? "higher";

  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>Column</th>
          <th>Type</th>
          <th>Coverage</th>
          <th>Distinct</th>
          <th>Job</th>
          <th>Direction</th>
          <th>Why</th>
        </tr>
      </thead>
      <tbody>
        {profiles.map((profile) => {
          const proposal = proposalByColumn.get(profile.name);
          const role = roleOf(config, profile.name);
          const isCriterion = role === "criterion";
          return (
            <tr key={profile.name} className={proposal?.needs_check ? "audit-needs-check" : undefined}>
              <td>
                <strong>{profile.name}</strong>
                {profile.decimal_comma && <div className="muted">comma decimals detected</div>}
                {!profile.spread && <div className="muted">single value across all rows</div>}
              </td>
              <td>{profile.type}</td>
              <td>{Math.round(profile.coverage * 100)}%</td>
              <td>{profile.unique}</td>
              <td>
                <select value={role} onChange={(e) => onSetRole(profile.name, e.target.value as ColumnRole)}>
                  {COLUMN_ROLES.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              </td>
              <td>
                {isCriterion ? (
                  <select value={directionOf(profile.name)} onChange={(e) => onSetDirection(profile.name, e.target.value as Direction)}>
                    <option value="higher">higher is better</option>
                    <option value="lower">lower is better</option>
                  </select>
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
              <td className="muted">
                {proposal?.role_reason}
                {isCriterion && proposal?.direction_reason ? ` · ${proposal.direction_reason}` : ""}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

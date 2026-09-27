/** The one visual state for anything an agent proposed that no person has
 * ratified yet. Same look on every surface, so a screen-shared view never
 * leaves a room guessing which values are settled. Pair with `.proposed` on
 * the container when the whole block is unratified. */
export function ProposedTag({ children = "Proposed · awaiting review" }: { children?: string }) {
  return <span className="proposed-tag">{children}</span>;
}

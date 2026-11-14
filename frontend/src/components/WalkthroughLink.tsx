/** Opens the Argus walkthrough of the value or section above it. */
export function WalkthroughLink({ href, row }: { href: string; row?: string }) {
  // the row goes after the visible words, hidden, so the link's name still starts with what it shows (WCAG 2.5.3)
  return <p className="walkthrough-link"><a href={href}>How was this found?{row && <span className="visually-hidden"> ({row})</span>}</a></p>;
}

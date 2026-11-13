/** Opens the Argus walkthrough of the value or section above it. */
export function WalkthroughLink({ href, label }: { href: string; label?: string }) {
  return <p className="walkthrough-link"><a href={href} aria-label={label}>How was this found?</a></p>;
}

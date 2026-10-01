/** Tells screen readers what a decision just did, through the one live region
 * App renders (#announcer), and tells App to refresh the sidebar counts.
 * Cleared first so the same text re-announces. */
export function announce(message: string) {
  window.dispatchEvent(new Event("arp:decided"));
  const el = document.getElementById("announcer");
  if (!el) return;
  el.textContent = "";
  requestAnimationFrame(() => (el.textContent = message));
}

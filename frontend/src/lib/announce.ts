/** Tells screen readers what a click just did, through the one live region
 * App renders (#announcer). Cleared first so the same text re-announces. */
export function announce(message: string) {
  const el = document.getElementById("announcer");
  if (!el) return;
  el.textContent = "";
  requestAnimationFrame(() => (el.textContent = message));
}

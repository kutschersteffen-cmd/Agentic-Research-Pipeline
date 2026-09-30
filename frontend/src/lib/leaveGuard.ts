// A screen holding unsaved work registers a check here; the app asks it
// before navigating to another screen. One screen at a time can hold one.
let guard: (() => boolean) | null = null;

export function setLeaveGuard(check: (() => boolean) | null) {
  guard = check;
}

/** True when nothing would be lost, or the person agreed to lose it. */
export function canLeave() {
  return !guard || guard();
}

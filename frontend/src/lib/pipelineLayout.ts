/** Touch screens: a one-finger drag on a graph scrolls the page instead of panning the canvas.
 * ponytail: read once at load; a hybrid device that switches pointer mid-session keeps the first answer. */
export const COARSE_POINTER = typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(pointer: coarse)").matches;

/** Bearer token + signed-in user, shared by the API client and the hooks. No React here. */
import type { Me } from "./reviewKeys";

const KEY = "arp.token";
const listeners = new Set<() => void>();
let memory = "";
let me: Me | null = null;

export function getToken(): string {
  try {
    return localStorage.getItem(KEY) ?? memory;
  } catch {
    return memory;
  }
}

function emit() {
  listeners.forEach((l) => l());
}

export function setToken(token: string) {
  memory = token;
  me = null;
  try {
    localStorage.setItem(KEY, token);
  } catch {
    // Storage blocked: the in-memory token lasts for this session.
  }
  emit();
}

/** A 401 means the token is unknown: forget it so the UI asks again. */
export function clearToken() {
  memory = "";
  me = null;
  try {
    localStorage.removeItem(KEY);
  } catch {
    // ignore
  }
  emit();
}

export const getMe = () => me;
export function setMe(next: Me | null) {
  me = next;
  emit();
}

export function subscribeAuth(l: () => void) {
  listeners.add(l);
  return () => listeners.delete(l);
}

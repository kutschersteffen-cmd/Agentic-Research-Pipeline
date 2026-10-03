import { useEffect, useSyncExternalStore } from "react";

/** The one reviewer identity for the whole app. Every approve, override,
 * reject and cast records this name, so a decision is always attributable to
 * a named person -- set once, reused by every review surface, remembered
 * across reloads on this device. */
const KEY = "arp.reviewer";
const listeners = new Set<() => void>();
let memory = "";

function read(): string {
  try {
    return localStorage.getItem(KEY) ?? "";
  } catch {
    return memory;
  }
}

function write(name: string) {
  memory = name;
  try {
    localStorage.setItem(KEY, name);
  } catch {
    // Storage blocked: keep the in-memory value for this session.
  }
  listeners.forEach((l) => l());
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => listeners.delete(l);
}

export function useReviewer(): [string, (name: string) => void] {
  return [useSyncExternalStore(subscribe, read), write];
}

export const REVIEWER_REQUIRED = "Enter your name under “Reviewing as” first: every decision is recorded against a named person.";

// --- Signed-in user (bearer token). The server records who decided; the UI never sends a name. ---
import { api } from "../api/client";
import { getMe, getToken, setMe, setToken, subscribeAuth } from "./auth";
import type { Me } from "./reviewKeys";

export function useToken(): [string, (token: string) => void] {
  return [useSyncExternalStore(subscribeAuth, getToken), setToken];
}

// One /api/me request per token, however many components mount useMe at once.
let inflight: { token: string; promise: Promise<void> } | null = null;

function loadMe(token: string) {
  if (inflight?.token === token) return;
  const promise = api
    .getMe()
    .then((m) => {
      if (getToken() === token) setMe(m);
    })
    .catch(() => {})
    .finally(() => {
      if (inflight?.promise === promise) inflight = null;
    });
  inflight = { token, promise };
}

/** The signed-in user from /api/me, or null while loading / signed out (a 401 clears the token). */
export function useMe(): Me | null {
  const token = useSyncExternalStore(subscribeAuth, getToken);
  const me = useSyncExternalStore(subscribeAuth, getMe);
  useEffect(() => {
    if (token && !me) loadMe(token);
  }, [token, me]);
  return token ? me : null;
}

export const SIGN_IN_REQUIRED = "Enter your access token in the sidebar first: every decision is recorded against the signed-in user.";

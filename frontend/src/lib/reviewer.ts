import { useSyncExternalStore } from "react";

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

export const REVIEWER_REQUIRED = "Enter your name under “Deciding as” first: every decision is recorded against a named person.";

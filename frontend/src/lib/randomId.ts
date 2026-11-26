/** 32 lowercase hex characters; works on plain http, where `crypto.randomUUID` does not exist. */
export function randomId(): string {
  const b = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
}

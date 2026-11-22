export const ASK_ERROR_TEXT = "Ask could not answer this question. Try again.";

/** What an error card says: the API's detail without the "502: " the client puts in front of it. */
export function askErrorText(err: unknown): string {
  return err instanceof Error && err.message ? err.message.replace(/^\d{3}: /, "") : ASK_ERROR_TEXT;
}

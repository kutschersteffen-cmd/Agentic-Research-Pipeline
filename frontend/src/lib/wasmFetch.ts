/** The rule engine's bytes, or a clear error when the download was not a success. */
export async function wasmBytes(res: Response): Promise<ArrayBuffer> {
  if (!res.ok) throw new Error(`the rule engine could not be downloaded (HTTP ${res.status})`);
  return res.arrayBuffer();
}

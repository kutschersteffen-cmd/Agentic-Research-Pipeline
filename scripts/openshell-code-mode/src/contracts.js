export const maxCalls = 12;
export const maxResultBytes = 16_384;
export const maxRequestBytes = 32_768;

export class ToolError extends Error {
  constructor(code) {
    super(code);
    this.code = code;
  }
}

export const toolErrorCodes = new Set([
  "UNKNOWN_TOOL", "TOOL_DENIED", "INVALID_ARGUMENTS", "CALL_LIMIT", "OUTPUT_LIMIT",
]);

export function checkedResult(result) {
  const json = JSON.stringify(result);
  if (json === undefined) throw new ToolError("INVALID_RESULT");
  if (new TextEncoder().encode(json).byteLength > maxResultBytes) {
    throw new ToolError("OUTPUT_LIMIT");
  }
  return JSON.parse(json);
}

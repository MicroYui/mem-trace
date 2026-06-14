export class MemTraceError extends Error {
  readonly status: number;
  readonly code: string;
  readonly responseBody: unknown;

  constructor(message: string, options: { status: number; code: string; responseBody: unknown }) {
    super(message);
    this.name = new.target.name;
    this.status = options.status;
    this.code = options.code;
    this.responseBody = options.responseBody;
  }
}

export class BadRequestError extends MemTraceError {}
export class ForbiddenError extends MemTraceError {}
export class NotFoundError extends MemTraceError {}
export class RateLimitedError extends MemTraceError {}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function detailToMessage(detail: unknown): string | undefined {
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail) && detail.length > 0) {
    return detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (isRecord(item) && typeof item.msg === "string") return item.msg;
        return JSON.stringify(item);
      })
      .join("; ");
  }
  return undefined;
}

function messageFromBody(body: unknown, rawText: string, status: number, statusText: string): string {
  if (isRecord(body)) {
    const detail = detailToMessage(body.detail);
    if (detail) return detail;
    if (typeof body.error === "string") return body.error;
    if (typeof body.message === "string") return body.message;
  }
  const trimmed = rawText.trim();
  if (trimmed.length > 0) return trimmed;
  if (statusText.trim().length > 0) return statusText;
  return `MemTrace request failed with status ${status}`;
}

async function parseBody(response: Response): Promise<{ body: unknown; rawText: string }> {
  const rawText = await response.text();
  if (rawText.trim().length === 0) {
    return { body: undefined, rawText };
  }
  try {
    return { body: JSON.parse(rawText) as unknown, rawText };
  } catch {
    return { body: rawText, rawText };
  }
}

export async function errorFromResponse(response: Response): Promise<MemTraceError> {
  const { body, rawText } = await parseBody(response);
  const message = messageFromBody(body, rawText, response.status, response.statusText);
  const options = { status: response.status, code: String(response.status), responseBody: body };

  if (response.status === 400 || response.status === 422) return new BadRequestError(message, options);
  if (response.status === 401 || response.status === 403) return new ForbiddenError(message, options);
  if (response.status === 404) return new NotFoundError(message, options);
  if (response.status === 429) return new RateLimitedError(message, options);
  return new MemTraceError(message, options);
}

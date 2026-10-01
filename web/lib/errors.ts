/** Failure from the API client, with a stable `code` (matches the backend's error codes plus a few client-side ones). */
export class ApiRequestError extends Error {
  constructor(
    public code: string,
    message: string,
    public retryable: boolean,
    /** true when the failure looks like a sleeping/cold-starting server rather than a real answer */
    public wakeable = false,
    public retryAfter?: number,
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

export type Failure = { code: string; message: string; retryable: boolean; retryAfter?: number };

export function toFailure(e: unknown): Failure {
  if (e instanceof ApiRequestError) return { code: e.code, message: e.message, retryable: e.retryable, retryAfter: e.retryAfter };
  return { code: "UNKNOWN", message: "Something went wrong.", retryable: true };
}

/** Human-friendly text. Messages for user-fixable problems come from the server; the rest are fixed copy. */
export function friendlyMessage(f: Failure): string {
  switch (f.code) {
    case "OFFLINE":
      return "You appear to be offline. Check your connection and try again.";
    case "NETWORK":
    case "SERVER_ERROR":
    case "TIMEOUT":
      return "We couldn't reach the server. It may still be starting up — please try again in a moment.";
    case "UPSTREAM_TIMEOUT":
      return "The market-data provider is responding slowly. Please try again in a moment.";
    case "DATA_UNAVAILABLE":
      return "Market data isn't available for this request right now. Check the symbol, or try again later.";
    case "RATE_LIMITED":
      return `Too many requests. Please wait ${f.retryAfter ?? 30} seconds and try again.`;
    case "INVALID_SYMBOL":
    case "INVALID_RANGE":
    case "INVALID_REQUEST":
    case "INSUFFICIENT_DATA":
      return f.message; // written for end users by the backend
    default:
      return "Something went wrong. Please try again.";
  }
}

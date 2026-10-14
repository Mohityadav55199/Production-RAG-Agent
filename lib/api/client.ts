export const API_BASE = "/api";

const TOKEN_KEY = "rag_token";
export const UNAUTHORIZED_EVENT = "rag:unauthorized";

export function getApiBase(): string {
  if (typeof window !== "undefined") {
    const stored = localStorage.getItem("rag_backend_url");
    if (stored) return stored.replace(/\/$/, "");
  }
  return (
    process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ||
    API_BASE
  );
}

// ── Session token ────────────────────────────────────────────────────────────

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // storage blocked: the session will last until the page is closed
  }
}

export function clearToken(): void {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    // ignore
  }
}

export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Called for any 401 on an authenticated request: drop the dead session and tell the app. */
export function handleUnauthorized(): void {
  if (!getToken()) return;
  clearToken();
  if (typeof window !== "undefined") window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
}

/** fetch() that sends the session token and reacts to an expired session. */
export async function authedFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const res = await fetch(input, {
    ...init,
    headers: { ...authHeaders(), ...(init.headers as Record<string, string> | undefined) },
  });
  if (res.status === 401) handleUnauthorized();
  return res;
}

// ── Errors ───────────────────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function parseErrorMessage(text: string, fallback: string): string {
  if (!text) return fallback;
  try {
    const json = JSON.parse(text) as { detail?: string | { msg?: string }[] };
    if (typeof json.detail === "string") return json.detail;
    if (Array.isArray(json.detail)) {
      return json.detail.map((d) => d.msg ?? String(d)).join(", ");
    }
  } catch {
    // plain text response
  }
  return text.length > 200 ? fallback : text;
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit & { timeout?: number }
): Promise<T> {
  const timeoutMs = init?.timeout ?? 30000; // default 30s
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  const apiBase = getApiBase();

  try {
    const res = await authedFetch(`${apiBase}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...init?.headers,
      },
    });

    clearTimeout(timeoutId);

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new ApiError(
        res.status,
        parseErrorMessage(text, res.statusText || "Request failed")
      );
    }

    if (res.status === 204) return undefined as T;
    return res.json() as Promise<T>;
  } catch (err: any) {
    clearTimeout(timeoutId);
    if (err.name === "AbortError") {
      throw new ApiError(408, "Request timed out");
    }
    throw err;
  }
}

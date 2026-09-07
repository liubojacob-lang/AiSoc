/** Typed API client: JSON envelope errors, Bearer access token in memory,
 * 401 → silent refresh (httpOnly cookie) & retry. Access token never touches
 * localStorage (XSS hardening per docs/ARCHITECTURE.md §8). */

export class ApiError extends Error {
  code: string;
  status: number;
  details: unknown;

  constructor(code: string, message: string, status: number, details: unknown) {
    super(message);
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

async function tryRefresh(): Promise<boolean> {
  refreshing ??= fetch("/api/v1/auth/refresh", { method: "POST" })
    .then(async (r) => {
      if (!r.ok) return false;
      const body = (await r.json()) as { access_token?: string };
      accessToken = body.access_token ?? null;
      return accessToken !== null;
    })
    .catch(() => false)
    .finally(() => {
      setTimeout(() => (refreshing = null), 100);
    });
  return refreshing;
}

async function request<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const headers: Record<string, string> = {};
  if (init.body && typeof init.body === "string") headers["Content-Type"] = "application/json";
  if (!(init.body instanceof FormData) && accessToken) headers["Authorization"] = `Bearer ${accessToken}`;
  const res = await fetch(path, { ...init, headers: { ...headers, ...init.headers } });

  if (res.status === 401 && retry && !path.includes("/auth/login")) {
    if (await tryRefresh()) return request<T>(path, init, false);
    setAccessToken(null);
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const err = body?.error ?? {};
    throw new ApiError(err.code ?? "unknown", err.message ?? res.statusText, res.status, err.details);
  }
  return body as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  upload: async <T>(path: string, file: File, title?: string): Promise<T> => {
    const form = new FormData();
    form.append("file", file);
    const qs = title ? `?title=${encodeURIComponent(title)}` : "";
    return request<T>(path + qs, { method: "POST", body: form });
  },
};

export const qs = (params: Record<string, string | number | undefined | null>) => {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : "";
};

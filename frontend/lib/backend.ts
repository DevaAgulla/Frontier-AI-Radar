const DEFAULT_BACKEND_BASE = "http://127.0.0.1:8000/api/v1";

export function getBackendBaseUrl(): string {
  const configured = process.env.BACKEND_API_BASE_URL?.replace(/\/$/, "");
  if (!configured) return DEFAULT_BACKEND_BASE;

  // Accept either full base (.../api/v1) or bare host (...:8000)
  if (/\/api\/v\d+$/i.test(configured)) return configured;
  if (/\/api$/i.test(configured)) return `${configured}/v1`;
  return `${configured}/api/v1`;
}

export async function fetchBackend(path: string, init?: RequestInit): Promise<Response> {
  const base = getBackendBaseUrl();
  const url = `${base}${path}`;
  return fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
}


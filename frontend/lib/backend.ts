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
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 120_000); // 120s timeout for free-tier cold starts
  try {
    return await fetch(url, {
      ...init,
      signal: init?.signal ?? controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers || {}),
      },
      cache: "no-store",
    });
  } finally {
    clearTimeout(timeout);
  }
}


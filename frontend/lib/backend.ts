const DEFAULT_BACKEND_BASE = "http://127.0.0.1:8000/api/v1";
const DEPLOYED_BACKEND_BASE = "https://frontier-ai-radar-production-75c1.up.railway.app/api/v1";
export function getBackendBaseUrl(): string {
  const configured = process.env.BACKEND_API_BASE_URL || process.env.NEXT_PUBLIC_BACKEND_API_BASE_URL;
  if (!configured) return DEFAULT_BACKEND_BASE;

  // Accept either full base (.../api/v1) or bare host (...:8000)
  const trimmed = configured.replace(/\/$/, "");
  if (/\/api\/v\d+$/i.test(trimmed)) return trimmed;
  if (/\/api$/i.test(trimmed)) return `${trimmed}/v1`;
  return `${trimmed}/api/v1`;
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


import { NextResponse } from "next/server";
import { fetchBackend } from "@/lib/backend";

/**
 * Login-time prefetch proxy.
 *
 * Called once after the user authenticates. Forwards to the backend
 * /api/v1/prefetch endpoint which warms Redis and returns all page-critical
 * data (runs, dashboard, presets) in a single round trip.
 */
export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const user_id = searchParams.get("user_id");
    const authHeader = request.headers.get("authorization") || "";

    const params = new URLSearchParams();
    if (user_id) params.set("user_id", user_id);

    const res = await fetchBackend(
      `/prefetch${params.toString() ? `?${params.toString()}` : ""}`,
      { headers: { Authorization: authHeader } }
    );

    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    // Prefetch is best-effort — never block the user
    return NextResponse.json({ runs: [], dashboard: {}, presets: null }, { status: 200 });
  }
}

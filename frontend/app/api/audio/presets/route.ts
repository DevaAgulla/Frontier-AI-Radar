import { NextRequest, NextResponse } from "next/server";
import { fetchBackend } from "@/lib/backend";

/**
 * GET  /api/audio/presets?run_id=<id>
 *   → proxies GET /api/v1/audio/{run_id}/presets
 *
 * POST /api/audio/presets?run_id=<id>&preset_id=<id>
 *   → proxies POST /api/v1/audio/{run_id}/generate?preset_id=<id>
 */

export async function GET(request: NextRequest) {
  const run_id = request.nextUrl.searchParams.get("run_id");
  if (!run_id) return NextResponse.json({ error: "run_id required" }, { status: 400 });

  try {
    const res = await fetchBackend(`/audio/${run_id}/presets`);
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    console.error("[audio/presets GET] error:", err);
    return NextResponse.json({ error: "Failed to reach backend" }, { status: 502 });
  }
}

export async function POST(request: NextRequest) {
  const run_id    = request.nextUrl.searchParams.get("run_id");
  const preset_id = request.nextUrl.searchParams.get("preset_id");

  if (!run_id || !preset_id) {
    return NextResponse.json({ error: "run_id and preset_id are required" }, { status: 400 });
  }

  try {
    const res = await fetchBackend(
      `/audio/${run_id}/generate?preset_id=${encodeURIComponent(preset_id)}`,
      { method: "POST" }
    );
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    console.error("[audio/presets POST] error:", err);
    return NextResponse.json({ error: "Failed to reach backend" }, { status: 502 });
  }
}

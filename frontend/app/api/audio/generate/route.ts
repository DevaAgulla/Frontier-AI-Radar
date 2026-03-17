import { NextRequest, NextResponse } from "next/server";
import { fetchBackend } from "@/lib/backend";

/**
 * POST /api/audio/generate?run_id=<id>&voice=<preset>
 * Proxies to backend POST /api/v1/audio/{run_id}/generate?voice_preset=<preset>
 * Returns { status: "done", voice_preset: "...", audio_path: "..." }
 */
export async function POST(request: NextRequest) {
  const run_id = request.nextUrl.searchParams.get("run_id");
  const voice  = request.nextUrl.searchParams.get("voice") ?? "rachel";

  if (!run_id) {
    return NextResponse.json({ error: "run_id is required" }, { status: 400 });
  }

  try {
    const res = await fetchBackend(
      `/audio/${run_id}/generate?voice_preset=${encodeURIComponent(voice)}`,
      { method: "POST" }
    );

    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      return NextResponse.json(
        { error: data?.detail ?? "Audio generation failed" },
        { status: res.status }
      );
    }

    return NextResponse.json(data);
  } catch (err: any) {
    console.error("[audio/generate] Error:", err);
    return NextResponse.json({ error: "Failed to reach backend" }, { status: 502 });
  }
}

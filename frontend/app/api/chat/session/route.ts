import { NextRequest, NextResponse } from "next/server";
import { fetchBackend } from "@/lib/backend";

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const run_id     = searchParams.get("run_id");
    const user_id    = searchParams.get("user_id");
    const persona_id = searchParams.get("persona_id");
    const session_id = searchParams.get("session_id");

    if (!run_id) {
      return NextResponse.json({ error: "run_id is required" }, { status: 400 });
    }

    const params = new URLSearchParams({ run_id });
    if (user_id)    params.set("user_id", user_id);
    if (persona_id) params.set("persona_id", persona_id);
    if (session_id) params.set("session_id", session_id);

    const res = await fetchBackend(`/chat/session?${params.toString()}`);

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      return NextResponse.json(
        { error: err.detail || "Session load failed" },
        { status: res.status }
      );
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Session unavailable" },
      { status: 500 }
    );
  }
}

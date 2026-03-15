import { NextRequest, NextResponse } from "next/server";
import { fetchBackend } from "@/lib/backend";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { run_id, message, history = [], mode = "text", session_id, user_id } = body;

    if (!run_id || !message?.trim()) {
      return NextResponse.json(
        { error: "run_id and message are required" },
        { status: 400 }
      );
    }

    const res = await fetchBackend("/chat/ask", {
      method: "POST",
      body: JSON.stringify({ run_id, message, history, mode, session_id, user_id }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      return NextResponse.json(
        { error: err.detail || "Chat request failed" },
        { status: res.status }
      );
    }

    // Voice mode returns plain JSON
    if (mode === "voice") {
      const data = await res.json();
      return NextResponse.json(data);
    }

    // Text mode — pass through SSE stream directly to client
    if (!res.body) {
      return NextResponse.json({ error: "No response body from backend" }, { status: 502 });
    }
    return new NextResponse(res.body, {
      status: 200,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        Connection: "keep-alive",
      },
    });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Chat unavailable" },
      { status: 500 }
    );
  }
}

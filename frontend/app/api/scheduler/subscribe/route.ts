import { NextResponse } from "next/server";
import { fetchBackend } from "@/lib/backend";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const email = String(body?.email || "").trim();
    const name = body?.name ? String(body.name).trim() : undefined;
    if (!email) {
      return NextResponse.json(
        { error: "email is required", status: 400 },
        { status: 400 }
      );
    }

    const res = await fetchBackend("/scheduler/subscribe", {
      method: "POST",
      body: JSON.stringify({ email, name }),
    });
    const payload = await res.json();
    if (!res.ok) {
      return NextResponse.json(
        { error: payload?.detail ?? "Failed to subscribe", status: res.status },
        { status: res.status }
      );
    }
    return NextResponse.json({ data: payload, status: 200 });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Subscribe proxy failed", status: 500 },
      { status: 500 }
    );
  }
}


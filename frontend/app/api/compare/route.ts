import { NextResponse } from "next/server";
import { fetchBackend } from "@/lib/backend";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const res = await fetchBackend("/compare", {
      method: "POST",
      body: JSON.stringify(body),
    });
    const payload = await res.json();
    if (!res.ok) {
      return NextResponse.json(
        { error: payload?.detail ?? "Compare request failed", status: res.status },
        { status: res.status }
      );
    }
    return NextResponse.json({ data: payload, status: 200 });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Compare proxy failed", status: 500 },
      { status: 500 }
    );
  }
}


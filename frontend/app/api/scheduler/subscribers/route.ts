import { NextResponse } from "next/server";
import { fetchBackend } from "@/lib/backend";

export async function GET() {
  try {
    const res = await fetchBackend("/scheduler/subscribers");
    const payload = await res.json();
    if (!res.ok) {
      return NextResponse.json(
        { error: payload?.detail ?? "Failed to fetch subscribers", status: res.status },
        { status: res.status }
      );
    }
    return NextResponse.json({ data: payload, status: 200 });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Subscribers proxy failed", status: 500 },
      { status: 500 }
    );
  }
}


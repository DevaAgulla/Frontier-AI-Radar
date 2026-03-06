import { NextResponse } from "next/server";
import { fetchBackend } from "@/lib/backend";

export async function GET(request: Request) {
  try {
    const authHeader = request.headers.get("authorization") || "";
    const res = await fetchBackend("/auth/me", {
      headers: { Authorization: authHeader },
    });
    const data = await res.json();
    if (!res.ok) {
      return NextResponse.json(
        { error: data.detail || "Unauthorized", status: res.status },
        { status: res.status }
      );
    }
    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Auth check failed", status: 500 },
      { status: 500 }
    );
  }
}

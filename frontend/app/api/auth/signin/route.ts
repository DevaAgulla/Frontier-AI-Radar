import { NextResponse } from "next/server";
import { fetchBackend } from "@/lib/backend";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const res = await fetchBackend("/auth/signin", {
      method: "POST",
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) {
      return NextResponse.json(
        { error: data.detail || "Sign in failed", status: res.status },
        { status: res.status }
      );
    }
    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Sign in failed", status: 500 },
      { status: 500 }
    );
  }
}

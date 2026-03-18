import { NextRequest, NextResponse } from "next/server";
import { fetchBackend } from "@/lib/backend";

export async function POST(request: NextRequest) {
  const body = await request.json();
  const res = await fetchBackend("/chat/threads/new", {
    method: "POST",
    body: JSON.stringify(body),
  }).catch(() => null);
  if (!res?.ok) return NextResponse.json({ error: "Failed" }, { status: 500 });
  return NextResponse.json(await res.json());
}

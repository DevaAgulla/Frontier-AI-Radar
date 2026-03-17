import { NextRequest, NextResponse } from "next/server";
import { fetchBackend } from "@/lib/backend";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const res = await fetchBackend(
    `/chat/threads?${searchParams.toString()}`,
    { method: "GET" }
  ).catch(() => null);
  if (!res?.ok) return NextResponse.json({ threads: [] });
  return NextResponse.json(await res.json());
}

import { NextResponse } from "next/server";
import { fetchBackend } from "@/lib/backend";
import { buildRunFromBackend } from "../_shared";

export async function GET() {
  try {
    const res = await fetchBackend("/dashboard");
    const payload = await res.json();
    if (!res.ok) {
      return NextResponse.json({ error: payload?.detail ?? "Failed to load dashboard", status: res.status }, { status: res.status });
    }

    return NextResponse.json({
      data: {
        last_run: payload.last_run ? buildRunFromBackend(payload.last_run) : null,
        top_findings: payload.top_findings ?? [],
      },
      status: 200,
    });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Dashboard proxy failed", status: 500 },
      { status: 500 }
    );
  }
}

import { NextResponse } from "next/server";
import { fetchBackend } from "@/lib/backend";
import { buildRunFromBackend } from "../_shared";

export async function GET() {
  const attempt = async () => {
    const res = await fetchBackend("/dashboard");
    const payload = await res.json();
    return { res, payload };
  };

  try {
    let { res, payload } = await attempt();

    // Retry once after 3s if backend was cold-starting
    if (!res.ok && res.status >= 500) {
      await new Promise((r) => setTimeout(r, 3000));
      ({ res, payload } = await attempt());
    }

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
      { error: error instanceof Error ? error.message : "Dashboard proxy failed — backend may be starting up", status: 503 },
      { status: 503 }
    );
  }
}

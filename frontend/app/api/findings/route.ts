import { NextResponse } from "next/server";
import { fetchBackend } from "@/lib/backend";
import { uiAgentToBackend, backendAgentToUi } from "../_shared";

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const backendParams = new URLSearchParams();
    const agentId = searchParams.get("agent_id");
    if (agentId) backendParams.set("agent_id", uiAgentToBackend(agentId as any));
    for (const key of ["entity", "category", "run_id", "limit"]) {
      const value = searchParams.get(key);
      if (value) backendParams.set(key, value);
    }

    const path = `/findings${backendParams.toString() ? `?${backendParams.toString()}` : ""}`;
    const res = await fetchBackend(path);
    const payload = await res.json();
    if (!res.ok) {
      return NextResponse.json({ error: payload?.detail ?? "Failed to load findings", status: res.status }, { status: res.status });
    }

    const data = Array.isArray(payload)
      ? payload.map((f: any) => ({
          ...f,
          agent_id: backendAgentToUi(f.agent_id),
        }))
      : [];
    return NextResponse.json({ data, total: data.length, status: 200 });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Findings proxy failed", status: 500 },
      { status: 500 }
    );
  }
}

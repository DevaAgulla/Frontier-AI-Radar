import { NextResponse } from "next/server";
import type { Source } from "@/lib/types";
import { fetchBackend } from "@/lib/backend";
import { backendAgentToUi } from "../_shared";

export async function GET() {
  try {
    const res = await fetchBackend("/sources/competitors");
    const payload = await res.json();
    if (!res.ok) {
      return NextResponse.json({ error: payload?.detail ?? "Failed to load sources", status: res.status }, { status: res.status });
    }
    const data: Source[] = Array.isArray(payload)
      ? payload.map((src: any) => ({
          id: src.id,
          url: src.url,
          agent_id: backendAgentToUi("competitor"),
          label: src.name,
          source_type: src.source_type,
          is_active: src.is_active,
          is_default: src.is_default,
          created_at: src.created_at ?? new Date().toISOString(),
          updated_at: src.created_at ?? new Date().toISOString(),
        }))
      : [];
    return NextResponse.json({ data, status: 200 });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Sources proxy failed", status: 500 },
      { status: 500 }
    );
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { url, agent_id, label, source_type } = body as Partial<Source>;
    if (!url || !agent_id) {
      return NextResponse.json(
        { error: "url and agent_id are required", status: 400 },
        { status: 400 }
      );
    }

    if (agent_id !== "competitor") {
      return NextResponse.json(
        { error: "Only competitor sources are DB-configurable in this version.", status: 400 },
        { status: 400 }
      );
    }

    const res = await fetchBackend("/sources/competitors", {
      method: "POST",
      body: JSON.stringify({
        name: (label || "Custom Competitor Source").trim(),
        url: url.trim(),
        source_type: source_type || "webpage",
      }),
    });
    const payload = await res.json();
    if (!res.ok) {
      return NextResponse.json(
        { error: payload?.detail ?? "Failed to add source", status: res.status },
        { status: res.status }
      );
    }

    const data: Source = {
      id: payload.id,
      url: payload.url,
      agent_id: "competitor",
      label: payload.name,
      source_type: payload.source_type,
      is_active: payload.is_active,
      is_default: payload.is_default,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    return NextResponse.json({ data, status: 201 });
  } catch {
    return NextResponse.json(
      { error: "Invalid request body", status: 400 },
      { status: 400 }
    );
  }
}

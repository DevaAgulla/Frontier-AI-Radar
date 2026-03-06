import { NextResponse } from "next/server";
import { fetchBackend } from "@/lib/backend";
import { buildRunFromBackend } from "../../_shared";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const runId = Number(id);
  if (!Number.isFinite(runId)) {
    return NextResponse.json(
      { error: "Run not found", status: 404 },
      { status: 404 }
    );
  }
  try {
    const res = await fetchBackend(`/runs/${runId}`);
    const payload = await res.json();
    if (!res.ok) {
      return NextResponse.json(
        { error: payload?.detail ?? "Run not found", status: res.status },
        { status: res.status }
      );
    }
    return NextResponse.json({ data: buildRunFromBackend(payload), status: 200 });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Failed to load run", status: 500 },
      { status: 500 }
    );
  }
}

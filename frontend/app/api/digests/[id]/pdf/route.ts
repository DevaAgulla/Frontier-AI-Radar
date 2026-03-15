import { NextResponse } from "next/server";
import { fetchBackend } from "@/lib/backend";

/**
 * Returns a placeholder PDF (or 404). In production, return the actual PDF binary
 * with Content-Type: application/pdf and the file stream.
 */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const runId = Number(id);
  if (!Number.isFinite(runId)) {
    return NextResponse.json(
      { error: "Digest not found", status: 404 },
      { status: 404 }
    );
  }
  try {
    const res = await fetchBackend(`/runs/${runId}/export/pdf`);
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}));
      return NextResponse.json(
        { error: payload?.detail ?? "Digest not found", status: res.status },
        { status: res.status }
      );
    }

    const bytes = await res.arrayBuffer();
    return new NextResponse(bytes, {
      status: 200,
      headers: {
        "Content-Type": "application/pdf",
        // inline = browser renders in iframe; never attachment
        "Content-Disposition": `inline; filename="digest-run-${runId}.pdf"`,
        "Cache-Control": "private, max-age=3600",
      },
    });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "PDF proxy failed", status: 500 },
      { status: 500 }
    );
  }
}

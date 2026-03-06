import { NextResponse } from "next/server";
import { fetchBackend } from "@/lib/backend";

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const from_date = searchParams.get("from_date");
    const to_date = searchParams.get("to_date");
    const q = searchParams.get("q")?.toLowerCase();

    const params = new URLSearchParams();
    if (from_date) params.set("start_date", from_date);
    if (to_date) params.set("end_date", to_date);

    const res = await fetchBackend(`/runs${params.toString() ? `?${params.toString()}` : ""}`);
    const payload = await res.json();
    if (!res.ok) {
      return NextResponse.json({ error: payload?.detail ?? "Failed to load digests", status: res.status }, { status: res.status });
    }

    const rows = Array.isArray(payload) ? payload : [];
    const digests = rows
      .filter((run: any) => Boolean(run.pdf_available))
      .map((run: any) => {
        const date = String(run.started_at || "").slice(0, 10);
        const findingsCount = Number(run.findings_count || 0);
        const summary = `Run ${run.run_id} completed with ${findingsCount} findings (${run.mode || "full"} mode).`;
        return {
          id: String(run.run_id),
          run_id: String(run.run_id),
          date,
          executive_summary: summary,
          findings_count: findingsCount,
          pdf_url: `/api/digests/${run.run_id}/pdf`,
          created_at: run.started_at || new Date().toISOString(),
        };
      })
      .filter((d: any) => !q || d.executive_summary.toLowerCase().includes(q) || d.date.includes(q))
      .sort((a: any, b: any) => (a.date < b.date ? 1 : -1));

    return NextResponse.json({ data: digests, status: 200 });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Digest proxy failed", status: 500 },
      { status: 500 }
    );
  }
}

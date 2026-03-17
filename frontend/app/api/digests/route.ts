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
      .filter((run: any) => {
        const s = (run.status ?? "").toLowerCase();
        return s === "success" || s === "completed";
      })
      .map((run: any) => {
        const date = String(run.started_at || "").slice(0, 10);
        const findingsCount = Number(run.findings_count || 0);
        const hasPdf = Boolean(run.pdf_available) || Boolean(run.pdf_path);
        return {
          id: String(run.run_id),
          run_id: String(run.run_id),
          date,
          period: (run.period as string) || "daily",
          executive_summary: run.executive_summary || `Frontier AI Intelligence Brief — ${findingsCount} findings across research, competitor, model & benchmark agents.`,
          findings_count: findingsCount,
          pdf_url: hasPdf ? `/api/digests/${run.run_id}/pdf` : null,
          audio_url: `/api/audio/${run.run_id}`,
          created_at: run.started_at || new Date().toISOString(),
        };
      })
      .filter((d: any) => !q || d.executive_summary.toLowerCase().includes(q) || d.date.includes(q))
      .sort((a: any, b: any) => (a.created_at < b.created_at ? 1 : -1));

    return NextResponse.json({ data: digests, status: 200 });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Digest proxy failed", status: 500 },
      { status: 500 }
    );
  }
}

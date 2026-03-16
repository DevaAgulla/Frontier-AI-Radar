import { NextRequest, NextResponse } from "next/server";
import { fetchBackend } from "@/lib/backend";
import path from "path";
import fs from "fs";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ run_id: string }> }
) {
  const { run_id } = await params;

  // ── Strategy 1: Local filesystem (preferred — always the complete master copy) ──
  // Azure blob uploads can be partial; the local file is always the full version.
  try {
    let date8 = "";
    try {
      const runRes = await fetchBackend(`/runs/${run_id}`);
      if (runRes.ok) {
        const run = await runRes.json();
        const startedAt: string = run.started_at || "";
        if (startedAt) {
          date8 = startedAt.slice(0, 10).replace(/-/g, ""); // "20260315"
        }
      }
    } catch {
      // ignore — will try all mp3s
    }

    const audioDir = path.join(process.cwd(), "..", "Backend", "data", "audio");

    if (fs.existsSync(audioDir)) {
      const allMp3s = fs.readdirSync(audioDir).filter((f) => f.endsWith(".mp3"));
      if (allMp3s.length > 0) {
        // Match by run date prefix; fall back to most recent
        const match = (date8 ? allMp3s.find((f) => f.includes(date8)) : null)
          ?? allMp3s.sort().at(-1)!;

        console.log(`[audio] Serving local file for run ${run_id}: ${match}`);
        const filePath = path.join(audioDir, match);
        const fileBuffer = fs.readFileSync(filePath);
        const totalSize = fileBuffer.length;

        // Support Range requests so the browser can seek and show correct duration immediately
        const rangeHeader = request.headers.get("range");
        if (rangeHeader) {
          const [, startStr, endStr] = /bytes=(\d*)-(\d*)/.exec(rangeHeader) ?? [];
          const start = startStr ? parseInt(startStr, 10) : 0;
          const end = endStr ? parseInt(endStr, 10) : totalSize - 1;
          const chunk = fileBuffer.slice(start, end + 1);
          return new NextResponse(chunk, {
            status: 206,
            headers: {
              "Content-Type": "audio/mpeg",
              "Content-Range": `bytes ${start}-${end}/${totalSize}`,
              "Content-Length": String(chunk.length),
              "Accept-Ranges": "bytes",
              "Cache-Control": "public, max-age=3600",
            },
          });
        }

        return new NextResponse(fileBuffer, {
          headers: {
            "Content-Type": "audio/mpeg",
            "Content-Disposition": `inline; filename="${match}"`,
            "Content-Length": String(totalSize),
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=3600",
          },
        });
      }
    }
    console.log(`[audio] No local file found for run ${run_id} (date=${date8}), trying Azure...`);
  } catch (err) {
    console.error("[audio] Local strategy error:", err);
  }

  // ── Strategy 2: Azure Blob fallback (when no local file exists) ──────────
  // Stream directly — never redirect, so Web Audio API / CORS works correctly.
  try {
    const sasRes = await fetchBackend(`/runs/${run_id}/asset?type=audio`);
    if (sasRes.ok) {
      const data = await sasRes.json();
      if (data?.url) {
        console.log(`[audio] Streaming from Azure for run ${run_id}...`);
        const audioRes = await fetch(data.url, { redirect: "follow" });
        if (audioRes.ok && audioRes.body) {
          const contentLength = audioRes.headers.get("Content-Length");
          const headers: Record<string, string> = {
            "Content-Type": audioRes.headers.get("Content-Type") || "audio/mpeg",
            "Content-Disposition": `inline; filename="audio-run-${run_id}.mp3"`,
            "Accept-Ranges": "bytes",
            "Cache-Control": "private, max-age=3600",
          };
          if (contentLength) headers["Content-Length"] = contentLength;
          return new NextResponse(audioRes.body, { headers });
        }
        console.error(`[audio] Azure fetch failed: ${audioRes.status} ${audioRes.statusText}`);
      }
    }
  } catch (err) {
    console.error("[audio] Azure strategy error:", err);
  }

  return NextResponse.json({ error: "Audio not available" }, { status: 404 });
}

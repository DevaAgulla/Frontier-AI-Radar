import { NextResponse } from "next/server";
import type { TriggerRunPayload } from "@/lib/types";
import { fetchBackend } from "@/lib/backend";
import { buildRunFromBackend, uiAgentToBackend } from "../_shared";

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const backendParams = new URLSearchParams();
    for (const key of ["status", "start_date", "end_date"]) {
      const value = searchParams.get(key);
      if (value) backendParams.set(key, value);
    }
    const path = `/runs${backendParams.toString() ? `?${backendParams.toString()}` : ""}`;

    const res = await fetchBackend(path);
    const payload = await res.json();
    if (!res.ok) {
      return NextResponse.json({ error: payload?.detail ?? "Failed to load runs", status: res.status }, { status: res.status });
    }

    const data = Array.isArray(payload) ? payload.map(buildRunFromBackend) : [];
    return NextResponse.json({ data, status: 200 });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Runs proxy failed", status: 500 },
      { status: 500 }
    );
  }
}

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as TriggerRunPayload;
    const { agent_ids, user_id, recipient_emails = [], extra_recipients = [], urls = [], url_mode = "default", since_days = 1, async_run = false } = body;
    if (!agent_ids?.length) {
      return NextResponse.json(
        { error: "agent_ids (non-empty array) is required", status: 400 },
        { status: 400 }
      );
    }

    const mappedAgents = agent_ids.map(uiAgentToBackend);
    const mode = mappedAgents.length === 4 ? "full" : mappedAgents.join(",");

    // user_id = logged-in user (primary recipient); extra_recipients = additional CCs
    const primaryEmail = recipient_emails[0]?.trim();
    const validExtras = extra_recipients.filter((e) => e.trim().length > 0);
    const runPayload = {
      mode,
      since_days,
      ...(user_id ? { user_id } : { email: primaryEmail || undefined }),
      ...(validExtras.length > 0 ? { extra_recipients: validExtras } : {}),
      urls: urls.filter((u) => u.trim().length > 0),
      url_mode,
    };

    let endpoint = async_run ? "/pipeline/run/async" : "/pipeline/run";
    let res = await fetchBackend(endpoint, {
      method: "POST",
      body: JSON.stringify(runPayload),
    });
    let payload = await res.json();

    // Strict fire-and-forget behavior with compatibility mode:
    // if backend async endpoint is unavailable, trigger sync endpoint in
    // detached mode and return immediately.
    if (async_run && res.status === 404) {
      void fetchBackend("/pipeline/run", {
        method: "POST",
        body: JSON.stringify(runPayload),
      }).catch(() => {
        // Detached fallback call intentionally swallows errors;
        // UI polling on /runs reveals final status.
      });

      // Give backend a tiny moment to create run row, then fetch latest running run.
      await new Promise((resolve) => setTimeout(resolve, 250));
      const probe = await fetchBackend("/runs?status=running");
      if (probe.ok) {
        const probePayload = await probe.json();
        if (Array.isArray(probePayload) && probePayload.length > 0) {
          const latest = buildRunFromBackend(probePayload[0]);
          return NextResponse.json({ data: latest, status: 202 });
        }
      }

      return NextResponse.json(
        {
          data: {
            id: `pending-${Date.now()}`,
            status: "running",
            started_at: new Date().toISOString(),
            mode,
            source_url: urls[0] || undefined,
            agent_ids,
            recipient_emails,
            findings_count: 0,
          },
          status: 202,
        },
        { status: 202 }
      );
    }

    if (!res.ok) {
      return NextResponse.json(
        { error: payload?.detail ?? payload?.error ?? "Failed to trigger run", status: res.status },
        { status: res.status }
      );
    }

    let runData = null;
    if (payload.run_db_id && !async_run) {
      const detailRes = await fetchBackend(`/runs/${payload.run_db_id}`);
      if (detailRes.ok) {
        const detail = await detailRes.json();
        runData = buildRunFromBackend(detail);
      }
    }

    const isRunning = async_run && endpoint.endsWith("/async");
    if (!runData) {
      runData = {
        id: String(payload.run_db_id || payload.run_id || Date.now()),
        status: isRunning ? "running" : "completed",
        started_at: payload.started_at ?? new Date().toISOString(),
        finished_at: isRunning ? undefined : (payload.finished_at ?? new Date().toISOString()),
        mode,
        source_url: urls[0] || undefined,
        agent_ids,
        recipient_emails,
        findings_count: payload.findings_count ?? 0,
      };
    }

    return NextResponse.json({ data: runData, status: 201 });
  } catch (err) {
    const isAbort = err instanceof DOMException && err.name === "AbortError";
    if (isAbort) {
      return NextResponse.json(
        { error: "Backend is starting up — please retry in 30 seconds", status: 504 },
        { status: 504 }
      );
    }
    return NextResponse.json(
      { error: "Invalid request body", status: 400 },
      { status: 400 }
    );
  }
}

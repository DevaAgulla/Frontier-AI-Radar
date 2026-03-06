import { NextResponse } from "next/server";
import { fetchBackend } from "@/lib/backend";

/**
 * PUT /api/sources/:id — toggle is_active on a competitor source.
 * Proxies to PUT /api/v1/sources/competitors/:id?is_active=true|false
 */
export async function PUT(
  request: Request,
  { params }: { params: { id: string } }
) {
  try {
    const body = await request.json();
    const isActive = body?.is_active ?? true;
    const res = await fetchBackend(
      `/sources/competitors/${params.id}?is_active=${isActive}`,
      { method: "PUT" }
    );
    const payload = await res.json();
    if (!res.ok) {
      return NextResponse.json(
        { error: payload?.detail ?? "Failed to update source", status: res.status },
        { status: res.status }
      );
    }
    return NextResponse.json({ data: payload, status: 200 });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Update source failed", status: 500 },
      { status: 500 }
    );
  }
}

/**
 * DELETE /api/sources/:id — remove a competitor source.
 * Proxies to DELETE /api/v1/sources/competitors/:id
 */
export async function DELETE(
  _request: Request,
  { params }: { params: { id: string } }
) {
  try {
    const res = await fetchBackend(`/sources/competitors/${params.id}`, {
      method: "DELETE",
    });
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}));
      return NextResponse.json(
        { error: payload?.detail ?? "Failed to delete source", status: res.status },
        { status: res.status }
      );
    }
    return NextResponse.json({ data: { ok: true }, status: 200 });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Delete source failed", status: 500 },
      { status: 500 }
    );
  }
}

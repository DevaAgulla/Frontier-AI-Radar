import { NextResponse } from "next/server";
import type { SendDigestPayload } from "@/lib/types";

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as SendDigestPayload;
    const { run_id, recipient_emails, include_pdf_attachment = true } = body;
    if (!run_id || !recipient_emails?.length) {
      return NextResponse.json(
        { error: "run_id and non-empty recipient_emails are required", status: 400 },
        { status: 400 }
      );
    }
    // Dummy: always success
    return NextResponse.json({
      data: {
        run_id,
        recipient_emails,
        include_pdf_attachment,
        sent_at: new Date().toISOString(),
        message: "Email queued for delivery.",
      },
      status: 200,
    });
  } catch {
    return NextResponse.json(
      { error: "Invalid request body", status: 400 },
      { status: 400 }
    );
  }
}

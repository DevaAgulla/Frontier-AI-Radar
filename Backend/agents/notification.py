"""Notification Agent — LangGraph-native ReAct agent (Layer 6 Delivery).

Composes and sends the email with inline summary and PDF attachment.
"""

import json
from langchain_core.messages import HumanMessage

from pipeline.state import RadarState
from agents.base_agent import (
    build_react_agent,
    get_recursion_limit,
    extract_agent_output,
    parse_json_object,
    handle_agent_error,
)
from core.tools import send_email_mcp, read_memory, write_memory
from config.settings import settings
import structlog

logger = structlog.get_logger()


# ── SYSTEM PROMPT ──────────────────────────────────────────────────────────

NOTIFICATION_SYSTEM_PROMPT = """You are the Notification Agent for Frontier AI Radar.

GOAL: Compose and send the daily intelligence email.  The email must include
an inline executive summary and attach the PDF digest.

TOOLS YOU CAN CALL:
- send_email_mcp: Send the email with PDF attachment via MCP protocol.
- read_memory: Check past email subjects to avoid repetition.

NOTE: write_memory is handled automatically after you emit your output.

REASONING BEFORE ACTING:
1. Read the digest data provided (executive summary + PDF path).
2. Compose a professional email subject line (vary daily).
3. Compose the email body with the executive summary inline.
4. Call send_email_mcp to deliver the email.
5. Save delivery status via write_memory.
6. Emit a JSON object with the delivery result.

EMAIL FORMAT:
- Subject: "Frontier AI Radar — [Date] — [Top Finding Title]"
- Body: Executive summary with bullet points + "Full digest attached."
- Attachment: PDF at the provided path

OUTPUT FORMAT: Return ONLY a valid JSON object:
{
    "status": "sent|failed",
    "message_id": "<from send_email_mcp>",
    "subject": "<email subject used>",
    "recipients": ["email1", "email2"],
    "error": null or "<error message>"
}

CRITICAL JSON RULES:
- Output ONLY the JSON. No text before or after.
- Do NOT wrap in markdown code fences.
- Ensure the JSON is COMPLETE — every [ has a ], every { has a }.
- If output would be very long, reduce the number of items rather than truncating.
- Keep string values concise (under 200 chars each) to avoid hitting token limits.
"""


# ── AGENT CONFIGURATION ───────────────────────────────────────────────────

NOTIFICATION_CONFIG = {

    # ── PARAMETER 1: TOOLS ─────────────────────────────────────────
    "tools": [
        send_email_mcp,        # Claude calls to send email
        read_memory,           # Claude checks past subjects
        # write_memory → mandatory Phase 4 (deterministic, not optional)
    ],

    # ── PARAMETER 2: LLM (BRAIN) ──────────────────────────────────
    "system_prompt": NOTIFICATION_SYSTEM_PROMPT,

    # ── PARAMETER 3: STATE (LANGGRAPH) ────────────────────────────
    "state": RadarState,       # reads: digest_markdown, pdf_path
                               # writes: email_status

    # ── PARAMETER 4: CONFIG ───────────────────────────────────────
    "config": {
        "max_iterations": 3,
    },
}

# write_memory is NOT given to the ReAct agent — it runs in Phase 4.
_optional_tools = [send_email_mcp, read_memory]

_react_agent = build_react_agent(
    system_prompt=NOTIFICATION_CONFIG["system_prompt"],
    tools=_optional_tools,
)


# ── LANGGRAPH NODE FUNCTION ───────────────────────────────────────────────

async def notification_agent(state: RadarState) -> RadarState:
    """
    LangGraph node: Notification Agent.

    Claude composes the email, calls send_email_mcp, and reports status.
    """
    try:
        digest_md = state.get("digest_markdown", "")
        pdf_path = state.get("pdf_path", "")
        run_id = state.get("run_id", "unknown")
        if (state.get("config") or {}).get("suppress_email"):
            logger.info("Notification Agent: suppressed for compare run", run_id=run_id)
            return {"email_status": "skipped"}
        recipients = state.get("email_recipients", [])

        # Fallback to .env if no recipients in state (backward compat)
        if not recipients:
            recipients = [e.strip() for e in settings.email_recipients.split(",") if e.strip()]

        logger.info("Notification Agent: starting", recipients=len(recipients))

        # Extract executive summary (first section of digest)
        exec_summary = digest_md[:2000] if len(digest_md) > 2000 else digest_md

        dashboard_url = f"http://localhost:3000/runs"
        user_prompt = (
            f"Executive summary for email body:\n\n{exec_summary}\n\n"
            f"PDF path to attach: {pdf_path}\n"
            f"Recipients: {json.dumps(recipients)}\n"
            f"Run ID: {run_id}\n\n"
            "1. Compose a professional subject line.\n"
            "2. Compose the email body with the executive summary.\n"
            f"3. Include a link to the full dashboard at the end of the email body: {dashboard_url}\n"
            "   Use text like: 'View full dashboard and drill into findings: <link>'\n"
            "4. Call send_email_mcp to deliver the email.\n"
            "5. Save delivery status with write_memory.\n"
            "6. Emit the delivery result JSON."
        )

        result = await _react_agent.ainvoke(
            {"messages": [HumanMessage(content=user_prompt)]},
            config={"recursion_limit": get_recursion_limit(
                NOTIFICATION_CONFIG["config"]["max_iterations"]
            )},
        )

        final_text = extract_agent_output(result["messages"])
        delivery = parse_json_object(final_text)

        email_status = delivery.get("status", "unknown")

        # ── PHASE 4: MANDATORY write_memory (deterministic) ──────
        await write_memory.ainvoke({
            "type": "long_term",
            "key": "last_notification_status",
            "value": json.dumps(delivery),
        })

        logger.info("Notification Agent: complete", status=email_status)
        return {"email_status": email_status}

    except Exception as e:
        logger.exception("Notification Agent error", error=str(e))
        return handle_agent_error("notification", e)

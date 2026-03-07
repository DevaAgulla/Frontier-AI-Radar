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

GOAL: Compose a professional daily intelligence email subject line and HTML body.
The actual sending is handled deterministically by the system — you only write the content.

TOOLS YOU CAN CALL:
- read_memory: Check past email subjects to avoid repeating the same subject line.

REASONING BEFORE ACTING:
1. Optionally call read_memory to check yesterday's subject and vary today's.
2. Compose a professional subject line: "Frontier AI Radar — [Date] — [Top Finding Title]"
3. Compose an HTML email body with the executive summary inline and bullet points.
4. End the body with: "Full digest attached. View dashboard: <dashboard_url>"
5. Emit the result JSON.

OUTPUT FORMAT: Return ONLY a valid JSON object:
{
    "subject": "<email subject>",
    "html_body": "<full HTML email body>",
    "preview": "<one-line summary of top finding>"
}

CRITICAL JSON RULES:
- Output ONLY the JSON. No text before or after.
- Do NOT wrap in markdown code fences.
- Ensure the JSON is COMPLETE — every [ has a ], every { has a }.
- Keep html_body concise (plain HTML, no embedded CSS, under 1500 chars).
"""


# ── AGENT CONFIGURATION ───────────────────────────────────────────────────

NOTIFICATION_CONFIG = {

    # ── PARAMETER 1: TOOLS ─────────────────────────────────────────
    "tools": [
        read_memory,           # Claude checks past subjects
        # send_email_mcp → called deterministically in Phase 3 (not by LLM)
        # write_memory → called deterministically in Phase 4
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

# send_email_mcp and write_memory are called deterministically — NOT by the LLM.
_optional_tools = [read_memory]

_react_agent = build_react_agent(
    system_prompt=NOTIFICATION_CONFIG["system_prompt"],
    tools=_optional_tools,
)


# ── LANGGRAPH NODE FUNCTION ───────────────────────────────────────────────

async def notification_agent(state: RadarState) -> RadarState:
    """
    LangGraph node: Notification Agent.

    Claude composes the email subject + body; backend sends deterministically.
    """
    try:
        digest_md = state.get("digest_markdown", "")
        pdf_path = state.get("pdf_path", "")
        run_id = state.get("run_id", "unknown")
        if (state.get("config") or {}).get("suppress_email"):
            logger.info("Notification Agent: suppressed for compare run", run_id=run_id)
            return {"email_status": "skipped"}

        # ── PHASE 1: Resolve recipients deterministically ────────
        # State recipients come from the API (DB user + extra_recipients)
        state_recipients = state.get("email_recipients", [])

        # Also include .env EMAIL_RECIPIENTS for belt-and-suspenders coverage
        env_recipients = [
            e.strip().lower()
            for e in settings.email_recipients.split(",")
            if e.strip()
        ]

        # Merge & deduplicate (state first, then .env extras)
        seen: set = set()
        recipients: list = []
        for addr in state_recipients + env_recipients:
            normalized = addr.strip().lower()
            if normalized and "@" in normalized and normalized not in seen:
                seen.add(normalized)
                recipients.append(normalized)

        logger.info(
            "Notification Agent: starting",
            recipients=len(recipients),
            emails=recipients,
        )

        # ── PHASE 2: LLM composes subject + html_body only ───────
        exec_summary = digest_md[:2000] if len(digest_md) > 2000 else digest_md
        dashboard_url = "http://localhost:3000/runs"
        user_prompt = (
            f"Executive summary for email body:\n\n{exec_summary}\n\n"
            f"Run ID: {run_id}\n"
            f"Dashboard URL: {dashboard_url}\n\n"
            "Compose the email subject line and HTML body. "
            "End the body with a link: 'View full dashboard: <link>'. "
            "Emit the result JSON."
        )

        result = await _react_agent.ainvoke(
            {"messages": [HumanMessage(content=user_prompt)]},
            config={"recursion_limit": get_recursion_limit(
                NOTIFICATION_CONFIG["config"]["max_iterations"]
            )},
        )

        final_text = extract_agent_output(result["messages"])
        composed = parse_json_object(final_text)

        subject = composed.get("subject", f"Frontier AI Radar — Run {run_id}")
        html_body = composed.get("html_body", exec_summary)

        # ── PHASE 3: Send email deterministically ─────────────────
        email_status = "skipped_no_recipients"
        if recipients:
            send_result = await send_email_mcp.ainvoke({
                "to": recipients,
                "subject": subject,
                "body": html_body,
                "pdf_path": pdf_path,
            })
            email_status = "sent" if send_result else "failed"
            logger.info(
                "Notification Agent: email sent",
                status=email_status,
                recipients=recipients,
                result=send_result,
            )
        else:
            logger.warning("Notification Agent: no recipients, skipping send")

        # ── PHASE 4: MANDATORY write_memory (deterministic) ──────
        delivery = {"status": email_status, "recipients": recipients, "subject": subject}
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

"""LangGraph-native agent factory using create_react_agent from langgraph.prebuilt.

Every agent in the Frontier AI Radar system is built through this factory.
The ReAct loop (Observe → Think → Act → Loop) is handled natively by LangGraph,
NOT by hand-coded Python recursion.

Supports two LLM backends (configurable via LLM_BACKEND env / settings):
  - "openrouter"  → Claude via OpenRouter (fast, reliable, preferred)
  - "gemini"      → Google Gemini (free tier, slower)
"""

from langgraph.prebuilt import create_react_agent
from langchain_core.messages import AIMessage, HumanMessage
from pipeline.state import RadarState, AgentError
from config.settings import settings
from datetime import datetime, timezone
import json
import re
import structlog

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# LLM BUILDER — selects backend based on settings.llm_backend
# ---------------------------------------------------------------------------

def _build_llm():
    """Create the LLM instance based on the configured backend.

    Returns a LangChain chat model (ChatOpenAI or ChatGoogleGenerativeAI).
    """
    backend = (settings.llm_backend or "gemini").lower().strip()

    if backend == "openrouter" and settings.openrouter_api_key:
        from langchain_openai import ChatOpenAI

        logger.info(
            "LLM backend: OpenRouter",
            model=settings.openrouter_model,
        )
        return ChatOpenAI(
            model=settings.openrouter_model,
            openai_api_key=settings.openrouter_api_key,
            openai_api_base=settings.openrouter_base_url,
            temperature=0.0,
            max_tokens=4096,
            default_headers={
                "HTTP-Referer": "https://frontier-ai-radar.local",
                "X-Title": "Frontier AI Radar",
            },
        )
    else:
        from langchain_google_genai import ChatGoogleGenerativeAI

        logger.info(
            "LLM backend: Gemini",
            model=settings.gemini_model,
        )
        return ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.gemini_api_key,
            temperature=0.0,
        )


# ---------------------------------------------------------------------------
# AGENT FACTORY
# ---------------------------------------------------------------------------

def build_react_agent(
    system_prompt: str,
    tools: list,
    response_format=None,
    checkpointer=None,
    store=None,
    interrupt_before=None,
):
    """
    Build a LangGraph-native ReAct agent using create_react_agent.

    This is the CORE FACTORY — every agent in the system is built through this.
    LangGraph handles the full ReAct loop natively:
      - LLM sees all tools + their docstrings → autonomous decision-making
      - LLM decides which tool to call → tool usage
      - Tool results auto-injected back to LLM → observation / memory
      - Loop continues until LLM emits final text → goal-driven behavior
      - Every step traced in LangSmith → full observability

    Args:
        system_prompt:    Agent identity, goal, rules, output schema.
        tools:            List of @tool-decorated functions the LLM can invoke.
        response_format:  Optional Pydantic BaseModel class. When set, LangGraph adds
                          a final structured-output node that stores the result in
                          result["structured_response"]. Eliminates manual JSON parsing.
                          Requires LLM to support .with_structured_output().
        checkpointer:     Optional LangGraph checkpointer (e.g. PostgresSaver).
                          Enables persistent state, interrupt/resume, and streaming
                          with tool use. Wired after DB credentials arrive.
        store:            Optional LangGraph store (e.g. PostgresStore).
                          Enables cross-agent shared memory. Wired after DB.
        interrupt_before: Optional list of node names to pause before (human-in-loop).

    Returns:
        Compiled LangGraph agent graph.
        Invoke with:  agent.ainvoke({"messages": [HumanMessage(content=...)]})
        Stream with:  agent.astream({"messages": [...]}, stream_mode="values")

    Structured output extraction pattern:
        structured = result.get("structured_response")
        if structured is not None:
            data = structured.model_dump()   # or .findings, .verdicts, etc.
        else:
            final_text = extract_agent_output(result["messages"])
            data = parse_json_output(final_text)
    """
    model = _build_llm()

    kwargs: dict = {
        "model": model,
        "tools": tools,
        "prompt": system_prompt,
    }

    # Only pass optional params when provided — avoids changing LangGraph defaults.
    # OpenRouter does not support the OpenAI structured-output API (parsed/refusal fields),
    # so we skip response_format for OpenRouter and rely on the text fallback instead.
    _backend = (settings.llm_backend or "gemini").lower().strip()
    if response_format is not None and _backend != "openrouter":
        kwargs["response_format"] = response_format
    if checkpointer is not None:
        kwargs["checkpointer"] = checkpointer
    if store is not None:
        kwargs["store"] = store
    if interrupt_before is not None:
        kwargs["interrupt_before"] = interrupt_before

    return create_react_agent(**kwargs)


# ---------------------------------------------------------------------------
# UTILITIES
# ---------------------------------------------------------------------------

def get_recursion_limit(max_iterations: int) -> int:
    """Convert max_iterations to LangGraph recursion_limit.

    Each ReAct cycle = 1 LLM call + 1 tool execution = 2 graph steps.
    Final emission = 1 step.  Buffer of 2 for safety.
    """
    return (max_iterations * 2) + 3


def extract_agent_output(messages: list) -> str:
    """Extract the final text from the agent's message history.

    After the ReAct loop completes, the last AIMessage without tool_calls
    contains the agent's structured output (JSON array of findings, etc.).

    NOTE: Gemini returns AIMessage.content as a list of content blocks like
    [{'type': 'text', 'text': '...'}] instead of a plain string.
    This function handles both formats.

    IMPORTANT: Content blocks are joined WITHOUT spaces so that JSON tokens
    spanning two blocks are not broken by an injected whitespace character.
    """
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content and not getattr(msg, "tool_calls", None):
            content = msg.content
            # Gemini returns content as list of blocks: [{'type':'text','text':'...'}]
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict):
                        parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        parts.append(block)
                    else:
                        parts.append(str(block))
                # Join WITHOUT spaces — spaces can break JSON tokens
                return "".join(parts).strip()
            return content if isinstance(content, str) else str(content)
    return ""


# ---------------------------------------------------------------------------
# BULLETPROOF JSON EXTRACTION
# ---------------------------------------------------------------------------

# Regex to match ```json ... ``` or ``` ... ``` fenced blocks
_CODE_FENCE_RE = re.compile(
    r"```(?:json)?\s*\n?(.*?)```",
    re.DOTALL,
)


def _strip_code_fences(text: str) -> str:
    """Extract content from ALL markdown code fences and merge them.

    If no fences are found the original text is returned unchanged.
    """
    blocks = _CODE_FENCE_RE.findall(text)
    if blocks:
        return "\n".join(b.strip() for b in blocks)
    return text


def _find_json_boundaries(text: str) -> str:
    """Locate the outermost JSON structure in *text*.

    Finds the first ``[`` or ``{`` and the LAST matching ``]`` or ``}``
    and returns the substring between them (inclusive).
    """
    # Find the first JSON-start character
    first_bracket = text.find("[")
    first_brace = text.find("{")

    if first_bracket == -1 and first_brace == -1:
        return text  # no JSON structure found — return as-is

    # Pick whichever comes first
    if first_bracket == -1:
        start = first_brace
        open_char, close_char = "{", "}"
    elif first_brace == -1:
        start = first_bracket
        open_char, close_char = "[", "]"
    else:
        if first_bracket < first_brace:
            start = first_bracket
            open_char, close_char = "[", "]"
        else:
            start = first_brace
            open_char, close_char = "{", "}"

    # Find the last matching close character
    last_close = text.rfind(close_char)
    if last_close > start:
        return text[start : last_close + 1]

    # No closing char found — return from start to end (truncated case)
    return text[start:]


def _repair_truncated_json(text: str):
    """Attempt to repair truncated JSON so ``json.loads`` succeeds.

    Strategy:
      - For arrays  ``[...``: find the last complete ``}`` and close with ``]``.
      - For objects ``{...``: count open/close braces and append missing ones.

    Returns the parsed Python object or *None* if repair fails.
    """
    text = text.rstrip().rstrip(",")  # remove trailing commas

    if text.startswith("["):
        # Array: find last complete object boundary
        last_brace = text.rfind("}")
        if last_brace > 0:
            candidate = text[: last_brace + 1] + "]"
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

    if text.startswith("{"):
        # Object: count unmatched braces/brackets and close them
        opens_brace = text.count("{") - text.count("}")
        opens_bracket = text.count("[") - text.count("]")
        # Strip any trailing partial key/value
        # Find last complete value delimiter (comma, close-brace, close-bracket)
        for i in range(len(text) - 1, -1, -1):
            if text[i] in (",", "}", "]", '"', "0", "1", "2", "3", "4",
                           "5", "6", "7", "8", "9", "e", "l", "s"):
                candidate = text[: i + 1].rstrip(",")
                candidate += "]" * max(0, opens_bracket)
                candidate += "}" * max(0, opens_brace)
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue

    return None


def _extract_json(text: str):
    """Robust JSON extractor that handles all known Gemini output patterns.

    Handles:
      1. Markdown code fences (```json ... ```)
      2. Extra text before/after JSON
      3. Truncated JSON (Gemini hit max output tokens)
      4. Multiple code blocks
      5. Raw JSON with no wrapping

    Returns the parsed Python object (dict, list, etc.) or None.
    """
    if not text or not text.strip():
        return None

    # Step 1: Strip markdown code fences
    cleaned = _strip_code_fences(text).strip()

    # Step 2: Fast path — try direct parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Step 3: Locate JSON boundaries (handles extra text around JSON)
    bounded = _find_json_boundaries(cleaned)
    if bounded != cleaned:
        try:
            return json.loads(bounded)
        except json.JSONDecodeError:
            pass
    else:
        bounded = _find_json_boundaries(text.strip())
        try:
            return json.loads(bounded)
        except json.JSONDecodeError:
            pass

    # Step 4: Attempt truncation repair
    repaired = _repair_truncated_json(bounded)
    if repaired is not None:
        logger.info("Recovered truncated JSON", items=len(repaired) if isinstance(repaired, list) else 1)
        return repaired

    # Step 5: Last resort — try repairing the original cleaned text
    repaired = _repair_truncated_json(cleaned)
    if repaired is not None:
        logger.info("Recovered truncated JSON (fallback)", items=len(repaired) if isinstance(repaired, list) else 1)
        return repaired

    logger.warning("All JSON extraction attempts failed", preview=text[:300])
    return None


def parse_json_output(text: str) -> list:
    """Parse a JSON **array** from agent output, with maximum tolerance.

    Handles: code fences, truncation, extra text, object-wrapped arrays,
    single objects, and all Gemini output quirks.
    """
    result = _extract_json(text)

    if result is None:
        return []

    # Direct array
    if isinstance(result, list):
        return result

    # Object that wraps an array (e.g. {"findings": [...], "results": [...]})
    if isinstance(result, dict):
        # Look for the first list-valued key
        for key in ("findings", "results", "items", "papers", "signals",
                     "sources", "verdicts", "entries", "ranked", "data"):
            if key in result and isinstance(result[key], list):
                return result[key]
        # Check any key that holds a list
        for v in result.values():
            if isinstance(v, list) and v:
                return v
        # Single object — wrap it
        return [result]

    return []


def parse_json_object(text: str) -> dict:
    """Parse a single JSON **object** from agent output, with maximum tolerance.

    Handles: code fences, truncation, extra text, array-of-one-object,
    and all Gemini output quirks.
    """
    result = _extract_json(text)

    if result is None:
        return {}

    # Direct object
    if isinstance(result, dict):
        return result

    # Array of objects — return the first one
    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict):
                return item

    return {}


def handle_agent_error(agent_name: str, error: Exception) -> dict:
    """Create standardised error entry for agent failures.

    Returns a PARTIAL state update (only 'errors') — safe for parallel fan-in.
    """
    agent_error: AgentError = {
        "agent_name": agent_name,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "context": {},
    }
    return {"errors": [agent_error]}

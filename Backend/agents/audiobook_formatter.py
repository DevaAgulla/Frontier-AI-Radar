"""Audiobook Formatter — converts raw digest text into spoken-word narration.

Sits between PDF text extraction and ElevenLabs TTS in the audio book pipeline.
Transforms raw digest content (which may contain markdown, timestamps, run IDs,
tables, and URLs) into clean flowing prose that sounds natural when read aloud.

Target output: 1,400–1,500 words (~10 minutes at 150 wpm speaking pace).
"""

import structlog
from config.settings import settings

logger = structlog.get_logger()

AUDIOBOOK_SYSTEM_PROMPT = """You are an expert audio script writer for a busy executive intelligence briefing.

Your job: Transform a raw AI intelligence digest into a professional spoken audio script.

STRICT RULES — NEVER VIOLATE:
- Write ONLY flowing sentences. Zero markdown, zero bullet points, zero lists.
- No asterisks (*), no hashes (#), no dashes as bullets, no underscores.
- No URLs, no timestamps, no run IDs, no ISO dates, no UTC references.
- No section headers, no table content, no raw numbers without context.
- No "as shown in the table below" or any reference to visual elements.
- Write as if speaking directly to one executive — use "you" and "we" naturally.

STRUCTURE (must follow this order):
1. Opening (about 75 words): Greet and name the 3 most important items from today.
2. Deep dives (about 250 words each for top 3 items): For each item, explain what happened, why it matters to the business, and what action — if any — is warranted.
3. Competitor highlights (about 150 words): What are competitors doing today that deserves attention.
4. Closing (about 75 words): Brief forward-looking note — what to watch in the next 24-48 hours.

TARGET LENGTH: 1,400 to 1,500 words total. No more, no less.
TONE: Calm, authoritative, like a trusted senior analyst briefing the CEO.
OUTPUT: Plain text only. No formatting whatsoever."""


def format_for_audiobook(raw_text: str) -> str:
    """Transform raw digest text into audio-friendly narration.

    Calls the configured LLM (OpenRouter or Gemini) with the audiobook system
    prompt and returns clean spoken-word prose ready for ElevenLabs TTS.

    Falls back to basic markdown stripping if the LLM call fails.
    """
    if not raw_text or not raw_text.strip():
        return raw_text

    try:
        backend = (settings.llm_backend or "gemini").lower().strip()

        if backend == "openrouter" and settings.openrouter_api_key:
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                model=settings.openrouter_model,
                api_key=settings.openrouter_api_key,
                base_url=settings.openrouter_base_url,
                temperature=0.4,
                max_tokens=2000,
            )
        else:
            from langchain_google_genai import ChatGoogleGenerativeAI
            llm = ChatGoogleGenerativeAI(
                model=settings.gemini_model,
                google_api_key=settings.gemini_api_key,
                temperature=0.4,
                max_output_tokens=2000,
            )

        from langchain_core.messages import SystemMessage, HumanMessage
        messages = [
            SystemMessage(content=AUDIOBOOK_SYSTEM_PROMPT),
            HumanMessage(content=f"Here is the digest content to transform:\n\n{raw_text[:8000]}"),
        ]
        response = llm.invoke(messages)
        narration = response.content.strip() if hasattr(response, "content") else str(response).strip()

        if narration:
            logger.info("audiobook_formatter: narration generated",
                        input_chars=len(raw_text), output_words=len(narration.split()))
            return narration

    except Exception as exc:
        logger.warning("audiobook_formatter: LLM call failed, using fallback", error=str(exc))

    # Fallback: basic markdown stripping (better than raw PDF text with symbols)
    import re
    cleaned = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', raw_text)   # bold/italic
    cleaned = re.sub(r'^#{1,6}\s+', '', cleaned, flags=re.MULTILINE)   # headers
    cleaned = re.sub(r'^[-*+]\s+', '', cleaned, flags=re.MULTILINE)    # bullets
    cleaned = re.sub(r'\[.*?\]\(.*?\)', '', cleaned)                    # markdown links
    cleaned = re.sub(r'https?://\S+', '', cleaned)                      # bare URLs
    cleaned = re.sub(r'\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?\b', '', cleaned)  # ISO timestamps
    cleaned = re.sub(r'\bRun\s+\d+\b', '', cleaned, flags=re.IGNORECASE)           # Run IDs
    return cleaned.strip()

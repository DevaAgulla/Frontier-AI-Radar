"""
ElevenLabs Voice Digest Generator
==================================
Converts a Frontier AI Radar PDF digest into an MP3 audio file.

Uses ElevenLabs REST API directly (no SDK — avoids Windows Long Path issues).
Requires: httpx, pdfplumber (both already in requirements.txt)

Usage:
    python voice/generate_voice_digest.py
    python voice/generate_voice_digest.py --pdf data/reports/digest-20260309-170217.pdf
    python voice/generate_voice_digest.py --pdf <path> --voice adam

Voice presets:
    rachel  (default) — calm, professional female narrator
    adam               — deep, authoritative male narrator

Output saved to: data/audio/<pdf_stem>_<voice>.mp3
"""

import sys
import os
import re
import argparse
from pathlib import Path

# ── path setup ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── load voice/config.env (standalone — does NOT touch Backend/.env) ────────
CONFIG_ENV = Path(__file__).parent / "config.env"

def _load_config_env(path: Path) -> dict:
    cfg = {}
    if not path.exists():
        return cfg
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            cfg[k.strip()] = v.strip()
    return cfg

_cfg = _load_config_env(CONFIG_ENV)

# ── ElevenLabs voice IDs ─────────────────────────────────────────────────────
VOICE_PRESETS = {
    "rachel": "21m00Tcm4TlvDq8ikWAM",   # calm, professional female
    "adam":   "pNInz6obpgDQGcFmaJgB",   # deep, authoritative male
}

ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

DEFAULT_PDF = ROOT / "data" / "reports" / "digest-20260309-170217.pdf"
OUTPUT_DIR  = ROOT / "data" / "audio"


# ── PDF text extraction ──────────────────────────────────────────────────────

def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract and clean text from PDF using pdfplumber."""
    import pdfplumber

    print(f"Reading PDF: {pdf_path.name}")
    pages_text = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        print(f"  {len(pdf.pages)} pages found")
        for i, page in enumerate(pdf.pages, 1):
            text = page.extract_text()
            if text:
                pages_text.append(text)

    raw = "\n".join(pages_text)
    return _clean_text(raw)


def _clean_text(text: str) -> str:
    """Clean PDF artifacts for clean TTS narration."""
    # Remove page numbers (standalone digits or "Page X of Y")
    text = re.sub(r"\bPage\s+\d+\s+of\s+\d+\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*\d+\s*$", "", text, flags=re.MULTILINE)
    # Collapse runs of dashes/underscores (section dividers)
    text = re.sub(r"[-_=]{4,}", " ", text)
    # Collapse excessive whitespace / blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    # Remove URLs (TTS reads them letter by letter — ugly)
    text = re.sub(r"https?://\S+", "", text)
    return text.strip()


# ── text chunking ─────────────────────────────────────────────────────────────

def _chunk_text(text: str, max_chars: int) -> list[str]:
    """
    Split text into chunks <= max_chars, breaking on sentence boundaries.
    Ensures ElevenLabs per-request limit is respected.
    """
    if len(text) <= max_chars:
        return [text]

    chunks = []
    # Split on sentence-ending punctuation followed by whitespace
    sentences = re.split(r"(?<=[.!?])\s+", text)
    current = ""

    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= max_chars:
            current = (current + " " + sentence).strip()
        else:
            if current:
                chunks.append(current)
            # If a single sentence exceeds limit, hard-split it
            if len(sentence) > max_chars:
                for i in range(0, len(sentence), max_chars):
                    chunks.append(sentence[i:i + max_chars])
                current = ""
            else:
                current = sentence

    if current:
        chunks.append(current)

    return chunks


# ── ElevenLabs TTS via REST API ───────────────────────────────────────────────

def generate_audio(text: str, voice_id: str, api_key: str, audio_format: str) -> bytes:
    """
    Call ElevenLabs TTS REST API and return raw MP3 bytes.
    Uses httpx (sync) — no SDK required.
    """
    import httpx

    url = ELEVENLABS_API_URL.format(voice_id=voice_id)
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "output_format": audio_format,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True,
        },
    }

    with httpx.Client(timeout=120.0) as client:
        resp = client.post(url, json=payload, headers=headers)

    if resp.status_code != 200:
        raise RuntimeError(
            f"ElevenLabs API error {resp.status_code}: {resp.text[:400]}"
        )

    return resp.content


# ── main ──────────────────────────────────────────────────────────────────────

def run(pdf_path: Path, voice_name: str, api_key: str,
        audio_format: str, chunk_size: int) -> Path:
    """Full pipeline: PDF -> text -> TTS chunks -> MP3 file."""

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    voice_id = VOICE_PRESETS.get(voice_name)
    if not voice_id:
        raise ValueError(
            f"Unknown voice '{voice_name}'. Choose from: {list(VOICE_PRESETS)}"
        )

    # 1. Extract text
    text = extract_text_from_pdf(pdf_path)
    print(f"  Extracted {len(text):,} characters of text")

    if not text.strip():
        raise ValueError("PDF produced no extractable text.")

    # 2. Chunk
    chunks = _chunk_text(text, chunk_size)
    print(f"  Split into {len(chunks)} TTS chunk(s) (max {chunk_size} chars each)")

    # 3. Generate audio per chunk
    audio_parts: list[bytes] = []
    for i, chunk in enumerate(chunks, 1):
        print(f"  Generating chunk {i}/{len(chunks)} ({len(chunk):,} chars) with voice [{voice_name}]...")
        part = generate_audio(chunk, voice_id, api_key, audio_format)
        audio_parts.append(part)
        print(f"    -> {len(part):,} bytes received")

    # 4. Concatenate and save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_filename = f"{pdf_path.stem}_{voice_name}.mp3"
    out_path = OUTPUT_DIR / out_filename

    with open(out_path, "wb") as f:
        for part in audio_parts:
            f.write(part)

    size_kb = out_path.stat().st_size // 1024
    print(f"\nSaved: {out_path}")
    print(f"Size : {size_kb} KB")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Generate voice digest from PDF")
    parser.add_argument(
        "--pdf",
        type=Path,
        default=DEFAULT_PDF,
        help=f"Path to the digest PDF (default: {DEFAULT_PDF.name})",
    )
    parser.add_argument(
        "--voice",
        choices=list(VOICE_PRESETS.keys()),
        default=_cfg.get("VOICE_PRESET", "rachel"),
        help="Voice preset: rachel (female) or adam (male)",
    )
    parser.add_argument(
        "--both",
        action="store_true",
        help="Generate audio for BOTH voice presets",
    )
    args = parser.parse_args()

    # Resolve API key
    api_key = _cfg.get("ELEVENLABS_API_KEY", "")
    if not api_key or api_key == "your_api_key_here":
        print("\nERROR: Set ELEVENLABS_API_KEY in voice/config.env first.")
        print(f"  Edit: {CONFIG_ENV}")
        sys.exit(1)

    audio_format = _cfg.get("AUDIO_FORMAT", "mp3_44100_128")
    chunk_size   = int(_cfg.get("CHUNK_SIZE", 4500))

    voices = list(VOICE_PRESETS.keys()) if args.both else [args.voice]

    print(f"\nFrontier AI Radar — Voice Digest Generator")
    print(f"PDF  : {args.pdf}")
    print(f"Voice: {', '.join(voices)}")
    print(f"Output: {OUTPUT_DIR}/\n")
    print("-" * 60)

    for voice_name in voices:
        print(f"\n[Voice: {voice_name}]")
        try:
            out = run(
                pdf_path=args.pdf,
                voice_name=voice_name,
                api_key=api_key,
                audio_format=audio_format,
                chunk_size=chunk_size,
            )
            print(f"Done -> {out.name}")
        except Exception as e:
            print(f"FAILED [{voice_name}]: {e}")

    print("\nAll done.")


if __name__ == "__main__":
    main()

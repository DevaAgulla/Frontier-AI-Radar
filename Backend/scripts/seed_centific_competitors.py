"""
Seed Centific-specific competitor sources into the competitors table.

These are Centific's closest peers in "expert data as a service":
managed annotation, RLHF, evaluation, and training data vendors.

Usage (run from Backend/ directory):
    python scripts/seed_centific_competitors.py

Safe to re-run — uses INSERT ... ON CONFLICT DO UPDATE (upsert).
"""

import sys
import os
from pathlib import Path

# ── allow running from any directory ──────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from sqlalchemy import create_engine, text
from config.settings import settings

# ── connection ─────────────────────────────────────────────────────────────────
DATABASE_URL = settings.database_url
TARGET_SCHEMA = "ai_radar"

# psycopg2-binary is used here (sync ORM path)
engine = create_engine(DATABASE_URL, echo=False)

# ── competitor data ────────────────────────────────────────────────────────────
# Each entry: (display_name, crawl_url, source_type, css_selector_or_None)
#
# source_type:
#   "rss"     — agent uses fetch_rss_feed tool (structured XML, preferred)
#   "webpage" — agent uses crawl_page tool (full HTML extraction)
#
# css_selector:
#   None → agent crawls whole page (safe default)
#   "article" → restrict to <article> tags (reduces noise on heavy pages)

CENTIFIC_COMPETITORS = [
    # ── GROUP 1: Core AI training data competitors ──────────────────────────
    # Most directly comparable to Centific's managed data services
    ("Scale AI Blog",          "https://scale.com/blog",                                                           "webpage", "article"),
    ("Appen Blog",             "https://www.appen.com/blog",                                                       "webpage", None),
    ("iMerit Blog",            "https://imerit.net/resources/blog/",                                               "webpage", None),
    ("Sama Blog",              "https://www.sama.com/blog",                                                        "webpage", None),
    ("RWS TrainAI Blog",       "https://www.rws.com/artificial-intelligence/train-ai-data-services/blog/",         "webpage", None),
    ("Cognizant AI Lab Blog",  "https://www.cognizant.com/us/en/ai-lab/blog",                                      "webpage", None),
    ("SuperAnnotate Blog",     "https://www.superannotate.com/blog",                                               "webpage", None),

    # ── GROUP 2: Platform-centric labeling vendors ──────────────────────────
    # Can be competitors OR infrastructure Centific plugs into
    ("Labelbox Blog",          "https://labelbox.com/blog/",                                                       "webpage", "article"),
    ("V7 Labs News",           "https://www.v7labs.com/news",                                                      "webpage", None),
    ("Encord Blog",            "https://encord.com/blog/",                                                         "webpage", "article"),
    ("Kili Technology Blog",   "https://kili-technology.com/blog",                                                 "webpage", None),
    ("CloudFactory Blog",      "https://www.cloudfactory.com/blog",                                                "webpage", None),

    # ── GROUP 3: Expert crowd and research-grade marketplaces ───────────────
    # Especially relevant for RLHF, safety evaluations, and benchmark work
    ("Surge AI Blog",          "https://surgehq.ai/blog",                                                          "webpage", None),
    ("Prolific Resources",     "https://www.prolific.com/resources",                                               "webpage", None),

    # ── GROUP 4: Newly added direct competitors (per March 2026 review) ─────
    ("Turing Blog",                        "https://www.turing.com/blog",                                                       "webpage", "article"),
    ("Deccan AI",                          "https://www.deccanai.com",                                                          "webpage", None),
    ("Margot AI",                          "https://www.margot.ai",                                                             "webpage", None),
    ("Cognizant AI Data Services",         "https://www.cognizant.com/us/en/services/artificial-intelligence/data-services",    "webpage", None),
    ("Toloka Blog",                        "https://toloka.ai/blog/",                                                           "webpage", "article"),
    ("Abaca AI",                           "https://www.abaca.ai",                                                              "webpage", None),
]


def seed():
    inserted = 0
    updated = 0

    with engine.begin() as conn:
        conn.execute(text(f"SET search_path TO {TARGET_SCHEMA}"))

        for name, url, source_type, selector in CENTIFIC_COMPETITORS:
            # Check if URL already exists to report insert vs update
            existing = conn.execute(
                text("SELECT id FROM competitors WHERE url = :url"),
                {"url": url},
            ).fetchone()

            conn.execute(text("""
                INSERT INTO competitors (name, url, source_type, selector, is_default, is_active)
                VALUES (:name, :url, :source_type, :selector, TRUE, TRUE)
                ON CONFLICT (url) DO UPDATE
                    SET name        = EXCLUDED.name,
                        source_type = EXCLUDED.source_type,
                        selector    = EXCLUDED.selector,
                        is_active   = TRUE
            """), {
                "name": name,
                "url": url,
                "source_type": source_type,
                "selector": selector,
            })

            if existing:
                print(f"   >> Updated : {name}")
                updated += 1
            else:
                print(f"   ++ Inserted: {name}")
                inserted += 1

    print(f"\nDone — {inserted} inserted, {updated} updated.")

    # ── verify ─────────────────────────────────────────────────────────────
    with engine.connect() as conn:
        conn.execute(text(f"SET search_path TO {TARGET_SCHEMA}"))
        rows = conn.execute(text("""
            SELECT id, name, url, source_type, is_active
            FROM competitors
            ORDER BY id
        """)).fetchall()

    print(f"\nAll competitors in DB ({len(rows)} total):")
    print(f"  {'ID':<4} {'Active':<7} {'Type':<9} Name  —  URL")
    print("  " + "-" * 80)
    for r in rows:
        active = "YES" if r.is_active else "no"
        print(f"  {r.id:<4} {active:<7} {r.source_type:<9} {r.name}  —  {r.url}")


if __name__ == "__main__":
    print(f"\nSeeding Centific competitor sources into [{TARGET_SCHEMA}.competitors]...\n")
    try:
        seed()
    except Exception as e:
        print(f"\nSeed FAILED: {e}")
        sys.exit(1)

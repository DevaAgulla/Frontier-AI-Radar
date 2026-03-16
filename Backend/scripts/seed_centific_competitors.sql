-- =============================================================================
-- Centific Competitor Seed Data
-- =============================================================================
-- Centific's closest peers in "expert data as a service" — specialist humans
-- + tooling providing training/validation data for AI models.
--
-- These are the companies that appear in the same RFPs as Centific for expert,
-- project-specific AI data work (annotation, RLHF, red-teaming, evaluation).
--
-- Usage:
--   psql -h <host> -U <user> -d <db> -f seed_centific_competitors.sql
--   OR run via: python scripts/setup_db.py --seed-competitors
--
-- All INSERTs use ON CONFLICT (url) DO UPDATE so the script is safe to re-run.
-- Source types:
--   "rss"     — agent uses fetch_rss_feed tool (structured, efficient)
--   "webpage" — agent uses crawl_page tool (full-page HTML extraction)
--
-- Selectors are NULL for most sites (agent crawls full page).
-- Add a CSS selector when you want to restrict crawling to article cards only
-- (e.g. 'article', '.blog-post', '.post-card') — reduces noise on heavy pages.
-- =============================================================================

SET search_path TO ai_radar;

-- -----------------------------------------------------------------------------
-- GROUP 1: Core AI training data competitors
-- Human-in-the-loop, expert labeling, RLHF / evaluation vendors
-- Most directly comparable to Centific's managed data services offering
-- -----------------------------------------------------------------------------

-- Scale AI — full-stack data generation, annotation, red-teaming, evaluation
INSERT INTO competitors (name, url, source_type, selector, is_default, is_active)
VALUES ('Scale AI Blog', 'https://scale.com/blog', 'webpage', 'article', TRUE, TRUE)
ON CONFLICT (url) DO UPDATE
    SET name = EXCLUDED.name,
        source_type = EXCLUDED.source_type,
        selector = EXCLUDED.selector,
        is_active = TRUE;

-- Appen — 1M+ contributors, enterprise text/audio/image/video labeling
INSERT INTO competitors (name, url, source_type, selector, is_default, is_active)
VALUES ('Appen Blog', 'https://www.appen.com/blog', 'webpage', NULL, TRUE, TRUE)
ON CONFLICT (url) DO UPDATE
    SET name = EXCLUDED.name,
        source_type = EXCLUDED.source_type,
        selector = EXCLUDED.selector,
        is_active = TRUE;

-- iMerit — managed annotation, computer vision, geospatial, document understanding
INSERT INTO competitors (name, url, source_type, selector, is_default, is_active)
VALUES ('iMerit Blog', 'https://imerit.net/resources/blog/', 'webpage', NULL, TRUE, TRUE)
ON CONFLICT (url) DO UPDATE
    SET name = EXCLUDED.name,
        source_type = EXCLUDED.source_type,
        selector = EXCLUDED.selector,
        is_active = TRUE;

-- Sama — human-in-the-loop annotation (vision, NLP), ethical sourcing focus
INSERT INTO competitors (name, url, source_type, selector, is_default, is_active)
VALUES ('Sama Blog', 'https://www.sama.com/blog', 'webpage', NULL, TRUE, TRUE)
ON CONFLICT (url) DO UPDATE
    SET name = EXCLUDED.name,
        source_type = EXCLUDED.source_type,
        selector = EXCLUDED.selector,
        is_active = TRUE;

-- RWS TrainAI — 100k+ vetted AI data specialists, expert data positioning
INSERT INTO competitors (name, url, source_type, selector, is_default, is_active)
VALUES ('RWS TrainAI Blog', 'https://www.rws.com/artificial-intelligence/train-ai-data-services/blog/', 'webpage', NULL, TRUE, TRUE)
ON CONFLICT (url) DO UPDATE
    SET name = EXCLUDED.name,
        source_type = EXCLUDED.source_type,
        selector = EXCLUDED.selector,
        is_active = TRUE;

-- Cognizant AI Training Data — SI-style data curation for Global 2000 clients
INSERT INTO competitors (name, url, source_type, selector, is_default, is_active)
VALUES ('Cognizant AI Lab Blog', 'https://www.cognizant.com/us/en/ai-lab/blog', 'webpage', NULL, TRUE, TRUE)
ON CONFLICT (url) DO UPDATE
    SET name = EXCLUDED.name,
        source_type = EXCLUDED.source_type,
        selector = EXCLUDED.selector,
        is_active = TRUE;

-- SuperAnnotate — enterprise data platform + managed expert-labeling services
INSERT INTO competitors (name, url, source_type, selector, is_default, is_active)
VALUES ('SuperAnnotate Blog', 'https://www.superannotate.com/blog', 'webpage', NULL, TRUE, TRUE)
ON CONFLICT (url) DO UPDATE
    SET name = EXCLUDED.name,
        source_type = EXCLUDED.source_type,
        selector = EXCLUDED.selector,
        is_active = TRUE;

-- -----------------------------------------------------------------------------
-- GROUP 2: Platform-centric labeling vendors
-- Compete on tooling; many now bundle expert teams or partner networks.
-- Can be Centific's competitors OR infrastructure Centific plugs into.
-- -----------------------------------------------------------------------------

-- Labelbox — leading labeling + data management platform, often with managed services
INSERT INTO competitors (name, url, source_type, selector, is_default, is_active)
VALUES ('Labelbox Blog', 'https://labelbox.com/blog/', 'webpage', 'article', TRUE, TRUE)
ON CONFLICT (url) DO UPDATE
    SET name = EXCLUDED.name,
        source_type = EXCLUDED.source_type,
        selector = EXCLUDED.selector,
        is_active = TRUE;

-- V7 Labs (Darwin) — vision-focused platform for large-scale multimodal datasets
INSERT INTO competitors (name, url, source_type, selector, is_default, is_active)
VALUES ('V7 Labs News', 'https://www.v7labs.com/news', 'webpage', NULL, TRUE, TRUE)
ON CONFLICT (url) DO UPDATE
    SET name = EXCLUDED.name,
        source_type = EXCLUDED.source_type,
        selector = EXCLUDED.selector,
        is_active = TRUE;

-- Encord — very active blog covering data-centric AI and labeling platforms
INSERT INTO competitors (name, url, source_type, selector, is_default, is_active)
VALUES ('Encord Blog', 'https://encord.com/blog/', 'webpage', 'article', TRUE, TRUE)
ON CONFLICT (url) DO UPDATE
    SET name = EXCLUDED.name,
        source_type = EXCLUDED.source_type,
        selector = EXCLUDED.selector,
        is_active = TRUE;

-- Kili Technology — enterprise AI data labeling techniques and product updates
INSERT INTO competitors (name, url, source_type, selector, is_default, is_active)
VALUES ('Kili Technology Blog', 'https://kili-technology.com/blog', 'webpage', NULL, TRUE, TRUE)
ON CONFLICT (url) DO UPDATE
    SET name = EXCLUDED.name,
        source_type = EXCLUDED.source_type,
        selector = EXCLUDED.selector,
        is_active = TRUE;

-- CloudFactory — managed workforce + platform; newsroom and blog
INSERT INTO competitors (name, url, source_type, selector, is_default, is_active)
VALUES ('CloudFactory Blog', 'https://www.cloudfactory.com/blog', 'webpage', NULL, TRUE, TRUE)
ON CONFLICT (url) DO UPDATE
    SET name = EXCLUDED.name,
        source_type = EXCLUDED.source_type,
        selector = EXCLUDED.selector,
        is_active = TRUE;

-- -----------------------------------------------------------------------------
-- GROUP 3: Expert crowd and research-grade marketplaces
-- Relevant for "expert evaluator" and research-grade data projects.
-- Especially important for RLHF, safety evaluations, and benchmark work.
-- -----------------------------------------------------------------------------

-- Surge AI — high-quality LLM/RLHF data with carefully screened annotators
INSERT INTO competitors (name, url, source_type, selector, is_default, is_active)
VALUES ('Surge AI Blog', 'https://surgehq.ai/blog', 'webpage', NULL, TRUE, TRUE)
ON CONFLICT (url) DO UPDATE
    SET name = EXCLUDED.name,
        source_type = EXCLUDED.source_type,
        selector = EXCLUDED.selector,
        is_active = TRUE;

-- Prolific — participant marketplace for rigorous human data collection
INSERT INTO competitors (name, url, source_type, selector, is_default, is_active)
VALUES ('Prolific Resources', 'https://www.prolific.com/resources', 'webpage', NULL, TRUE, TRUE)
ON CONFLICT (url) DO UPDATE
    SET name = EXCLUDED.name,
        source_type = EXCLUDED.source_type,
        selector = EXCLUDED.selector,
        is_active = TRUE;

-- =============================================================================
-- VERIFY: Check all Centific competitor rows were inserted
-- Run this query to confirm after executing the seed above:
-- =============================================================================
-- SELECT id, name, url, source_type, selector, is_active
-- FROM ai_radar.competitors
-- WHERE name NOT LIKE '%OpenAI%'
--   AND name NOT LIKE '%Anthropic%'
--   AND name NOT LIKE '%DeepMind%'
--   AND name NOT LIKE '%Meta AI%'
--   AND name NOT LIKE '%Mistral%'
--   AND name NOT LIKE '%HuggingFace%'
--   AND name NOT LIKE '%Cohere%'
--   AND name NOT LIKE '%AWS%'
--   AND name NOT LIKE '%Microsoft%'
--   AND name NOT LIKE '%NVIDIA%'
-- ORDER BY id;
-- =============================================================================
-- OPTIONAL: Disable LLM-provider entries if you want competitor_intel agent
-- to focus ONLY on Centific's training-data peers:
-- =============================================================================
-- UPDATE ai_radar.competitors SET is_active = FALSE
-- WHERE url IN (
--     'https://openai.com/blog/rss.xml',
--     'https://www.anthropic.com/news/rss.xml',
--     'https://deepmind.google/blog/rss.xml',
--     'https://ai.meta.com/blog/rss/',
--     'https://mistral.ai/news/rss',
--     'https://huggingface.co/blog/feed.xml',
--     'https://cohere.com/blog/rss',
--     'https://aws.amazon.com/blogs/machine-learning/feed/',
--     'https://blogs.microsoft.com/ai/feed/',
--     'https://blogs.nvidia.com/blog/category/deep-learning/feed/'
-- );
-- =============================================================================

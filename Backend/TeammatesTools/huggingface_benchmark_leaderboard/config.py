"""
Configuration for Hugging Face Benchmark & Leaderboard Tracker.
All data is fetched in real time from Hugging Face APIs/datasets — no dummy data.
"""

# What to track (all enabled by default; set to False to disable)
TRACK = {
    "open_llm_leaderboard": True,   # Open LLM Leaderboard (scores from HF dataset)
    "trending_models": True,        # Trending models (likes7d / trending_score via HF API)
    "eval_datasets": True,          # Official benchmark/evaluation datasets
    "model_eval_results": True,     # Eval results on model cards (when available via API)
}

# Open LLM Leaderboard — HF dataset: open-llm-leaderboard/contents
LEADERBOARD_DATASET = "open-llm-leaderboard/contents"
LEADERBOARD_TOP_N = 50             # Top N models to report
LEADERBOARD_TASKS = [              # Task columns of interest (match dataset columns if present)
    "average",
    "arc",
    "hellaswag",
    "mmlu",
    "truthfulqa",
    "winogrande",
    "gsm8k",
]

# Trending models — via HfApi.list_models(sort=...)
TRENDING_SORT = "trending_score"   # or "downloads", "likes", "last_modified", "created_at"
TRENDING_LIMIT = 30
TRENDING_DAILY_LIMIT = 15          # For "daily" trending feel, use smaller limit

# Evaluation datasets — via HfApi.list_datasets(benchmark="official")
EVAL_DATASETS_LIMIT = 25
EVAL_DATASETS_SEARCH = None        # Optional: e.g. "reasoning" or "code" to narrow

# Model info — optional expansion for eval results on model cards
MODEL_INFO_EXPAND = ["evalResults", "likes", "downloads", "trendingScore"]

# Output
OUTPUT_DIR = "output"
REPORT_FORMAT = "text"             # "text" | "json"

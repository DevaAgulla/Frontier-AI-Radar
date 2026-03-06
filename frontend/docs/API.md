# Frontier AI Radar — API Documentation

Base URL: `/api` (relative to app origin). All responses are JSON unless noted.

---

## 1. Dashboard

### GET `/api/dashboard`

Returns last run status and top 10 findings for the dashboard.

**Response**

```json
{
  "data": {
    "last_run": {
      "id": "run-001",
      "status": "completed",
      "started_at": "2026-03-06T10:32:00Z",
      "finished_at": "2026-03-06T10:38:00Z",
      "source_url": "openai.com",
      "agent_ids": ["competitor", "foundation"],
      "recipient_emails": ["alice@example.com"],
      "findings_count": 12
    },
    "top_findings": [
      {
        "id": "f1",
        "title": "GPT-4o API general availability",
        "date_detected": "2026-03-06",
        "source_url": "https://openai.com/blog/...",
        "publisher": "OpenAI",
        "agent_id": "competitor",
        "category": "release",
        "summary_short": "...",
        "summary_long": "...",
        "why_it_matters": "...",
        "confidence": 0.95,
        "tags": ["api", "gpt-4o"],
        "entities": ["OpenAI", "GPT-4o"],
        "impact_score": 0.88
      }
    ]
  },
  "status": 200
}
```

---

## 2. Sources

### GET `/api/sources`

List all configured sources (URLs per agent).

**Response**

```json
{
  "data": [
    {
      "id": "src-1",
      "url": "https://openai.com/blog",
      "agent_id": "competitor",
      "label": "OpenAI Blog",
      "created_at": "2026-03-01T00:00:00Z",
      "updated_at": "2026-03-06T00:00:00Z"
    }
  ],
  "status": 200
}
```

### POST `/api/sources`

Add a new source.

**Payload**

| Field       | Type   | Required | Description                |
|------------|--------|----------|----------------------------|
| `url`      | string | Yes      | Source URL to crawl         |
| `agent_id` | string | Yes      | One of: `competitor`, `foundation`, `research`, `huggingface` |
| `label`    | string | No       | Display label              |

**Example**

```json
{
  "url": "https://anthropic.com/news",
  "agent_id": "foundation",
  "label": "Anthropic News"
}
```

**Response** (201)

```json
{
  "data": {
    "id": "src-1234567890",
    "url": "https://anthropic.com/news",
    "agent_id": "foundation",
    "label": "Anthropic News",
    "created_at": "2026-03-06T12:00:00Z",
    "updated_at": "2026-03-06T12:00:00Z"
  },
  "status": 201
}
```

**Error** (400): `{ "error": "url and agent_id are required", "status": 400 }`

---

## 3. Runs

### GET `/api/runs`

List runs with optional filters.

**Query parameters**

| Param        | Type   | Description                          |
|-------------|--------|--------------------------------------|
| `status`   | string | Filter by `completed`, `running`, `failed`, `pending` |
| `start_date` | string | ISO date, e.g. `2026-03-01`        |
| `end_date`   | string | ISO date, e.g. `2026-03-06`        |

**Response**

```json
{
  "data": [
    {
      "id": "run-001",
      "status": "completed",
      "started_at": "2026-03-06T10:32:00Z",
      "finished_at": "2026-03-06T10:38:00Z",
      "source_url": "openai.com",
      "agent_ids": ["competitor", "foundation"],
      "recipient_emails": ["alice@example.com"],
      "findings_count": 12
    }
  ],
  "status": 200
}
```

### GET `/api/runs/:id`

Get a single run by ID.

**Response** (200): same run object as in list.

**Error** (404): `{ "error": "Run not found", "status": 404 }`

### POST `/api/runs`

Trigger a new run (manual run).

**Payload**

| Field              | Type     | Required | Description                                    |
|--------------------|----------|----------|------------------------------------------------|
| `agent_ids`        | string[] | Yes      | Non-empty list of agent IDs                    |
| `source_url`       | string   | No       | Optional source URL for this run              |
| `recipient_emails` | string[] | No       | Emails to receive the digest                   |
| `send_email`       | boolean  | No       | If true and emails provided, send digest email |

**Example**

```json
{
  "agent_ids": ["competitor", "foundation", "research"],
  "source_url": "https://openai.com",
  "recipient_emails": ["user@example.com"],
  "send_email": true
}
```

**Response** (201)

```json
{
  "data": {
    "id": "run-1737123456789",
    "status": "running",
    "started_at": "2026-03-06T12:00:00Z",
    "source_url": "https://openai.com",
    "agent_ids": ["competitor", "foundation", "research"],
    "recipient_emails": ["user@example.com"],
    "findings_count": 0
  },
  "status": 201
}
```

Run status may transition to `completed` (or `failed`) asynchronously; poll `GET /api/runs/:id` for updates.

**Error** (400): `{ "error": "agent_ids (non-empty array) is required", "status": 400 }`

---

## 4. Findings

### GET `/api/findings`

List findings with optional filters.

**Query parameters**

| Param       | Type   | Description                                      |
|------------|--------|--------------------------------------------------|
| `agent_id` | string | Filter by agent: `competitor`, `foundation`, `research`, `huggingface` |
| `entity`   | string | Filter by entity or publisher name (substring)   |
| `category` | string | Filter by category: `release`, `research`, `benchmark`, `api`, `pricing`, `safety` |
| `run_id`   | string | Filter by run (findings from that run’s agents)  |
| `limit`    | number | Max results (default 50, max 100)                |

**Response**

```json
{
  "data": [
    {
      "id": "f1",
      "title": "GPT-4o API general availability",
      "date_detected": "2026-03-06",
      "source_url": "https://openai.com/blog/...",
      "publisher": "OpenAI",
      "agent_id": "competitor",
      "category": "release",
      "summary_short": "...",
      "summary_long": "...",
      "why_it_matters": "...",
      "evidence": "...",
      "confidence": 0.95,
      "tags": ["api", "gpt-4o"],
      "entities": ["OpenAI", "GPT-4o"],
      "impact_score": 0.88
    }
  ],
  "total": 10,
  "status": 200
}
```

---

## 5. Digests

### GET `/api/digests`

List digest archives.

**Query parameters**

| Param       | Type   | Description                          |
|------------|--------|--------------------------------------|
| `from_date` | string | ISO date (inclusive)                 |
| `to_date`   | string | ISO date (inclusive)                 |
| `q`         | string | Search in executive_summary and date |

**Response**

```json
{
  "data": [
    {
      "id": "dig-001",
      "run_id": "run-001",
      "date": "2026-03-06",
      "executive_summary": "Today's digest covers...",
      "findings_count": 12,
      "pdf_url": "/api/digests/dig-001/pdf",
      "created_at": "2026-03-06T10:38:00Z"
    }
  ],
  "status": 200
}
```

### GET `/api/digests/:id/pdf`

Get PDF for a digest. Currently returns JSON metadata; in production return binary PDF with `Content-Type: application/pdf`.

**Response** (200): `{ "data": { "digest_id": "dig-001", "pdf_url": "...", "message": "..." } }`

**Error** (404): `{ "error": "Digest not found", "status": 404 }`

### POST `/api/digests/send`

Send digest email to recipients.

**Payload**

| Field                   | Type     | Required | Description                    |
|-------------------------|----------|----------|--------------------------------|
| `run_id`                | string   | Yes      | Run ID for the digest          |
| `recipient_emails`      | string[] | Yes      | Non-empty list of email addresses |
| `include_pdf_attachment`| boolean  | No       | Default true                   |

**Example**

```json
{
  "run_id": "run-001",
  "recipient_emails": ["user@example.com", "team@company.com"],
  "include_pdf_attachment": true
}
```

**Response** (200)

```json
{
  "data": {
    "run_id": "run-001",
    "recipient_emails": ["user@example.com"],
    "include_pdf_attachment": true,
    "sent_at": "2026-03-06T12:00:00Z",
    "message": "Email queued for delivery."
  },
  "status": 200
}
```

**Error** (400): `{ "error": "run_id and non-empty recipient_emails are required", "status": 400 }`

---

## Types reference

- **AgentId**: `"competitor"` | `"foundation"` | `"research"` | `"huggingface"`
- **RunStatus**: `"completed"` | `"running"` | `"failed"` | `"pending"`
- **FindingCategory**: `"release"` | `"research"` | `"benchmark"` | `"api"` | `"pricing"` | `"safety"`

All timestamps are ISO 8601 (e.g. `2026-03-06T10:32:00Z`).

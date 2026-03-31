# Memory System Design

## Goal

This document defines a memory-system V1 for the document editing platform.

Target outcomes:

- bind memory to real authenticated users
- reuse persisted chat sessions/messages as the source of truth
- separate stable preferences from time-sensitive episodic memory
- keep write logic deterministic and auditable
- keep retrieval cheap enough to run on every edit workflow

This design intentionally does not require a full `deepagents` migration. It fits the current `LangGraph + workflow + services` architecture.

## Current Foundation

The current codebase already has the minimum prerequisites:

- authenticated `users`
- document ownership via `documents.user_id`
- `chat_sessions`
- `chat_messages`
- `pgvector` on document blocks
- a workflow entry point that can load extra context before planning edits

Recent refactor work has also added:

- real-user binding for `/v1/chat/edit` and `/v1/chat/confirm`
- per-turn session/message persistence
- workflow trace metadata with `agents_used`, `skills_used`, and `events`
- agent/skill-style decoupling on top of the existing runtime

## Principles

1. Memory is system state, not free-form conversation history.
2. Extraction may use LLMs; storage policy should stay mostly rule-driven.
3. Stable preferences should be stored as structured rows, not vector chunks.
4. Time-sensitive memory should be retrieved by relevance + recency, not blindly appended to prompts.
5. Users must be able to inspect and delete stored memory.

## Memory Types

### 1. Stable Preferences

Long-lived user preferences that can be read directly and injected into prompts.

Examples:

- answer language: `zh`, `en`
- response style: `concise`, `detailed`, `structured`
- editing style: `conservative`, `rewrite_aggressive`
- default confirmation preference: `preview_first`, `auto_apply_low_risk`
- formatting preference: `bullet_first`, `table_ok`, `no_emoji`

### 2. Episodic Memory

Short-term or medium-term facts about recent work.

Examples:

- user is editing release notes for project X this week
- user is revising a technical design document for search indexing
- recent task focus is legal-style wording cleanup

### 3. Working Context Memory

Short-lived context that is useful during the current editing streak and should expire automatically.

Examples:

- the user is currently rewriting the project background section
- the user recently preferred replacing paragraphs instead of deleting them
- the user has been editing the same document for the last 30 minutes

## Storage Model

### Table: `user_preferences`

Structured storage for stable preferences.

Suggested schema:

```sql
CREATE TABLE user_preferences (
    preference_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    preference_key TEXT NOT NULL,
    preference_value JSONB NOT NULL,
    source TEXT NOT NULL DEFAULT 'memory_extractor',
    confidence NUMERIC(4,3) NOT NULL DEFAULT 0.800,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, preference_key)
);

CREATE INDEX idx_user_preferences_user_key
ON user_preferences (user_id, preference_key);
```

Notes:

- `preference_value` is `JSONB` to support both scalar and structured values.
- overwrite is the default strategy for the same `preference_key`.

### Table: `user_memory_items`

Vector-searchable storage for episodic and working-context memory.

Suggested schema:

```sql
CREATE TABLE user_memory_items (
    memory_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    doc_id UUID NULL,
    session_id UUID NULL,
    memory_layer TEXT NOT NULL DEFAULT 'episodic',
    memory_type TEXT NOT NULL,
    memory_subtype TEXT NULL,
    scope TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    summary TEXT NULL,
    retrieval_text TEXT NULL,
    source_message_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    extraction_reason JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_type TEXT NOT NULL DEFAULT 'turn_trace',
    confidence NUMERIC(4,3) NOT NULL,
    importance NUMERIC(4,3) NOT NULL DEFAULT 0.500,
    memory_strength DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    stability DOUBLE PRECISION NOT NULL DEFAULT 7.0,
    review_count INTEGER NOT NULL DEFAULT 0,
    recall_count INTEGER NOT NULL DEFAULT 0,
    retention_score DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    last_recalled_at TIMESTAMPTZ NULL,
    last_reinforced_at TIMESTAMPTZ NULL,
    min_keep_until TIMESTAMPTZ NULL,
    max_keep_until TIMESTAMPTZ NULL,
    archived_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

If you want vector retrieval inside PostgreSQL:

```sql
ALTER TABLE user_memory_items
ADD COLUMN embedding vector(1024);

CREATE INDEX idx_user_memory_items_user_type_time
ON user_memory_items (user_id, memory_type, created_at DESC);
```

Recommended value sets:

- `memory_layer`: `working`, `episodic`, `persona`, `relation`
- `memory_type`: `edit_pattern`, `failure_case`, `project_context`
- `memory_subtype`: `confirmed_edit`, `failed_edit`, `retry_trace`
- `scope`: `short_term`, `medium_term`, `long_term`

### Optional Table: `memory_extraction_runs`

Useful for audit/debug only.

```sql
CREATE TABLE memory_extraction_runs (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    session_id UUID NOT NULL,
    source_message_ids JSONB NOT NULL,
    extractor_version TEXT NOT NULL,
    candidates JSONB NOT NULL,
    decisions JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

This table is optional for V1. If you want fast delivery, skip it first.

## Source Data

Memory extraction should read from persisted chat turns, not raw transport payloads.

Primary source:

- `chat_sessions`
- `chat_messages`

Important metadata already available in `chat_messages.meta`:

- `doc_id`
- `request_type`
- `status`
- `operation_type`
- `confirm_token`
- `preview_hash`
- `new_rev_id`
- `trace.agents_used`
- `trace.skills_used`
- `trace.events`

This is enough to build first-generation memory without introducing more write paths.

## Extraction Pipeline

### Step 1. Candidate Extraction

Run after a completed user/assistant turn.

Recommended trigger points:

- after `/v1/chat/edit` response is persisted
- after `/v1/chat/confirm` response is persisted

Input:

- latest user message
- latest assistant message
- recent 5 to 20 messages in the same session
- document metadata
- workflow trace

Output format:

```json
[
  {
    "memory_class": "preference",
    "key": "response_style",
    "value": "concise",
    "confidence": 0.92,
    "reason": "User repeatedly asked for shorter, direct answers."
  },
  {
    "memory_class": "episodic",
    "title": "Editing release notes for search launch",
    "content": "The user is actively revising release-note wording for the March search launch.",
    "scope": "medium_term",
    "confidence": 0.81,
    "reason": "Recent session context repeatedly references launch notes and release wording."
  }
]
```

Implementation recommendation:

- use one LLM-backed `MemoryExtractor`
- keep its output schema strict
- reject outputs that fail schema validation

### Step 2. Policy Decision

This step should be rule-driven first, LLM-assisted only when needed.

Decision fields:

- store or discard
- target store: `user_preferences` or `user_memory_items`
- overwrite, merge, or append
- initial heat and decay parameters
- minimum and maximum retention boundaries
- minimum confidence required

### Step 3. Persistence

Persistence should be plain application code.

- upsert preferences into `user_preferences`
- insert or merge memory rows into `user_memory_items`
- never let the extractor write to storage directly

## Extraction Rules

### Store as Stable Preference

Store in `user_preferences` when the candidate is:

- phrased as an explicit user preference
- repeated across multiple sessions
- likely to stay useful for more than a week
- directly actionable during response generation or edit planning

Examples:

- “以后都用中文回复”
- “回答简洁一点”
- “默认先给结论再展开”
- “修改时尽量保守，不要大改”

Default action:

- `overwrite` existing value for the same `preference_key`

### Store as Episodic or Working Context

Store in `user_memory_items` when the candidate is:

- tied to a current project or recent editing streak
- useful for future retrieval but not stable enough to become a preference
- document-specific or task-specific

Examples:

- user is currently preparing a product launch doc
- user recently focused on polishing PRD wording
- user is comparing multiple edit options for the same document

Default action:

- `append` new row if content is materially new
- `merge/update` if similarity is high and scope overlaps

### Discard

Discard when the candidate is:

- one-off operational chatter
- a request that only applies to the current single turn
- low confidence
- personally sensitive without clear product value
- derived from assistant output only, with no user signal

Examples:

- “谢谢”
- “现在先这样”
- one-time typo fix request with no broader pattern

## Confidence, Heat Decay, and Retention Policy

Recommended thresholds:

- stable preference write threshold: `>= 0.85`
- episodic memory write threshold: `>= 0.75`
- working-context write threshold: `>= 0.65`
- discard below threshold

Short- and medium-term memory should not rely only on fixed TTL. Prefer:

- forgetting-curve decay
- scheduled cleanup
- minimum retention protection
- maximum retention as a fallback boundary
- archive before physical deletion

Suggested initialization:

- new short-term memory: `memory_strength = 0.85`, `stability = 7`
- new medium-term memory: `memory_strength = 0.92`, `stability = 21`
- higher-value context can start higher based on `importance` and `confidence`

Suggested reinforcement:

- retrieved only: increment `recall_count`
- actually injected into prompt: increment `review_count` and raise `memory_strength`
- reinforced by subsequent user behavior: raise `stability`
- repeated use within the same theme can receive an additional `stability` boost

Suggested forgetting formula:

```text
retention_score = memory_strength * exp(-days_elapsed / stability)
```

Suggested scheduler cadence:

- hourly or daily

Suggested archival rules:

- `short_term`: archive if not recalled for 7+ days and `retention_score < 0.25`
- `medium_term`: archive if not recalled for 30+ days and `retention_score < 0.20`
- do not archive while still protected by `min_keep_until`
- if `max_keep_until` is exceeded, move it into configurable archive/degrade handling even if retention remains high

Suggested deletion strategy:

- set `archived_at` first
- physically delete later via a separate cleanup task

Stable preferences should still avoid forgetting-curve deletion. They should support only:

- overwrite
- explicit delete

## Overwrite vs Append

### Overwrite

Use overwrite for:

- `response_style`
- `language`
- `editing_style`
- `confirmation_preference`

Reason:

- these should have one current effective value

### Append

Use append for:

- project context
- recent activity
- task streaks
- episodic facts

Reason:

- history matters
- multiple parallel contexts may exist

### Merge

Use merge when:

- new candidate is semantically close to an existing episodic item
- same user, same project, same doc or same session cluster
- new candidate adds freshness or precision

Merge result:

- update `summary`
- combine `source_message_ids`
- refresh `confidence`, `importance`, `memory_strength`, `stability`, `retention_score`, `last_reinforced_at`, and retention boundaries
- refresh `updated_at`

## Runtime Retrieval

### Load Path Before Workflow

At the beginning of `EditWorkflow.execute(...)`:

1. load stable preferences for `user_id`
2. retrieve top-K relevant memory items for the current request
3. build a compact memory context
4. attach the memory context to workflow state

Suggested state additions:

```python
state["user_preferences"] = {...}
state["retrieved_memories"] = [...]
state["memory_context"] = {
    "stable_preferences": "...",
    "recent_context": "...",
}
```

### Prompt Use

Do not dump raw memory rows into prompts.

Preferred prompt structure:

```text
Stable user preferences:
- Respond in Chinese.
- Prefer concise, structured answers.
- Default to conservative edits before aggressive rewrites.

Recent relevant context:
- The user has recently been editing release notes for the search launch.
- The user is working on the same document and tends to confirm previews before applying.
```

### Retrieval Query Strategy

For `user_memory_items`, rank by:

- vector similarity to current user message
- same `doc_id` boost
- recent `session_id` boost
- heat
- recency of actual use
- importance

Suggested top-K:

- 3 to 8 items

## API Design

### 1. List User Preferences

`GET /v1/users/me/preferences`

Response:

```json
{
  "items": [
    {
      "preference_key": "response_style",
      "preference_value": "concise",
      "confidence": 0.94,
      "last_seen_at": "2026-03-27T10:00:00Z"
    }
  ]
}
```

### 2. Upsert User Preference

`PUT /v1/users/me/preferences/{preference_key}`

Request:

```json
{
  "preference_value": "concise",
  "source": "user_explicit"
}
```

This endpoint is useful for explicit preference management and for UI-level controls.

### 3. List User Memory Items

`GET /v1/users/me/memory`

Query params:

- `memory_type`
- `scope`
- `doc_id`
- `active_only=true`

### 4. Delete Memory Item

`DELETE /v1/users/me/memory/{memory_id}`

### 5. Delete Preference

`DELETE /v1/users/me/preferences/{preference_key}`

### 6. Inspect Session History

`GET /v1/chat/sessions/{session_id}`

Purpose:

- debug session replay
- support future “what the assistant remembers” UI

### 7. Optional Manual Re-Extraction

`POST /v1/users/me/memory/extract`

Purpose:

- admin/debug trigger
- rebuild memory for a session range

This endpoint is optional for V1.

## Suggested Service Layer

### `MemoryExtractor`

Responsibilities:

- read recent turns
- call LLM with a strict extraction schema
- produce candidate memories

Suggested methods:

- `extract_from_session_turn(session_id, message_ids)`
- `extract_candidates(messages, document_context)`

### `MemoryPolicyService`

Responsibilities:

- score candidates
- decide target store
- decide overwrite vs append vs merge
- assign initial heat, decay rate, and retention boundaries

Suggested methods:

- `evaluate(candidate)`
- `decide(candidate, existing_memories, existing_preferences)`

### `MemoryStoreService`

Responsibilities:

- persist preferences
- persist or merge memory items
- decay memory heat on schedule
- archive cold memory
- delete archived memory later

Suggested methods:

- `upsert_preference(...)`
- `insert_memory_item(...)`
- `merge_memory_item(...)`
- `delete_memory_item(...)`
- `decay_memory_heat(...)`
- `archive_cold_memories(...)`
- `prune_archived_memories(...)`

### `MemoryRetriever`

Responsibilities:

- read stable preferences
- retrieve relevant episodic memory
- build compact memory context for prompts

Suggested methods:

- `get_user_preferences(user_id)`
- `search_memories(user_id, query, doc_id=None, top_k=5)`
- `build_memory_context(user_id, query, doc_id=None)`

## Proposed Extraction Prompt Rules

The extractor should follow these rules:

1. Extract only user-relevant memory, not generic task summaries.
2. Prefer explicit user preferences over inferred preferences.
3. Do not store transient one-turn details as stable preferences.
4. Do not store secrets, credentials, or unnecessary personal data.
5. When uncertain, lower confidence instead of forcing a strong memory.
6. Prefer compact canonical values for stable preferences.

Suggested stable preference keys:

- `response_language`
- `response_style`
- `response_structure`
- `editing_style`
- `confirmation_preference`
- `risk_tolerance`

## Integration Plan

### Phase 1

- keep current real-user session persistence
- add APIs for reading session history
- add `user_preferences`
- add manual preference endpoints

### Phase 2

- add `user_memory_items`
- implement `MemoryExtractor`
- run extraction asynchronously after persisted turns

### Phase 3

- inject preferences and retrieved memories into `EditWorkflow`
- add user-facing memory inspection/deletion UI/API

## Why This Fits This Project

This design fits the current document-editing platform because:

- user identity is now stable
- sessions and turns are now persisted
- the main workflow is deterministic enough to benefit from structured preferences
- the project already uses PostgreSQL and `pgvector`
- memory can improve edit quality without requiring a full multi-agent runtime migration

## Explicit Non-Goals for V1

- fully autonomous memory agents that write state without policy checks
- storing all raw chat history as memory
- building a separate external knowledge base before proving product value
- migrating the whole app to `deepagents`

## Recommended Next Implementation Slice

1. add `GET /v1/chat/sessions/{session_id}` to inspect stored turns
2. add `user_preferences`
3. inject stable preferences into `EditWorkflow`
4. add `user_memory_items`
5. implement extractor + policy + persistence

"""
Schema sync helpers for runtime-safe additive migrations.
"""
from __future__ import annotations

from sqlalchemy import text


MEMORY_SCHEMA_DDL = [
    "CREATE EXTENSION IF NOT EXISTS vector",
    """
    ALTER TABLE IF EXISTS user_preferences
    ADD COLUMN IF NOT EXISTS memory_layer TEXT NOT NULL DEFAULT 'persona'
    """,
    """
    ALTER TABLE IF EXISTS user_preferences
    ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT 'inferred'
    """,
    """
    ALTER TABLE IF EXISTS document_preferences
    ADD COLUMN IF NOT EXISTS memory_layer TEXT NOT NULL DEFAULT 'relation'
    """,
    """
    ALTER TABLE IF EXISTS document_preferences
    ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT 'inferred'
    """,
    """
    ALTER TABLE IF EXISTS document_preferences
    ADD COLUMN IF NOT EXISTS entity_type TEXT NOT NULL DEFAULT 'document'
    """,
    """
    ALTER TABLE IF EXISTS editing_rules
    ADD COLUMN IF NOT EXISTS memory_layer TEXT NOT NULL DEFAULT 'relation'
    """,
    """
    ALTER TABLE IF EXISTS editing_rules
    ADD COLUMN IF NOT EXISTS rule_source TEXT NOT NULL DEFAULT 'inferred'
    """,
    """
    ALTER TABLE IF EXISTS user_memory_items
    ADD COLUMN IF NOT EXISTS memory_layer TEXT NOT NULL DEFAULT 'episodic'
    """,
    """
    ALTER TABLE IF EXISTS user_memory_items
    ADD COLUMN IF NOT EXISTS memory_subtype TEXT
    """,
    """
    ALTER TABLE IF EXISTS user_memory_items
    ADD COLUMN IF NOT EXISTS retrieval_text TEXT
    """,
    """
    ALTER TABLE IF EXISTS user_memory_items
    ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT 'turn_trace'
    """,
    """
    ALTER TABLE IF EXISTS user_memory_items
    ADD COLUMN IF NOT EXISTS memory_strength DOUBLE PRECISION NOT NULL DEFAULT 1.0
    """,
    """
    ALTER TABLE IF EXISTS user_memory_items
    ADD COLUMN IF NOT EXISTS stability DOUBLE PRECISION NOT NULL DEFAULT 7.0
    """,
    """
    ALTER TABLE IF EXISTS user_memory_items
    ADD COLUMN IF NOT EXISTS review_count INTEGER NOT NULL DEFAULT 0
    """,
    """
    ALTER TABLE IF EXISTS user_memory_items
    ADD COLUMN IF NOT EXISTS recall_count INTEGER NOT NULL DEFAULT 0
    """,
    """
    ALTER TABLE IF EXISTS user_memory_items
    ADD COLUMN IF NOT EXISTS retention_score DOUBLE PRECISION NOT NULL DEFAULT 1.0
    """,
    """
    ALTER TABLE IF EXISTS user_memory_items
    ADD COLUMN IF NOT EXISTS last_recalled_at TIMESTAMPTZ
    """,
    """
    ALTER TABLE IF EXISTS memory_audit_log
    ADD COLUMN IF NOT EXISTS memory_layer TEXT NOT NULL DEFAULT 'episodic'
    """,
    """
    ALTER TABLE IF EXISTS memory_audit_log
    ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT 'system'
    """,
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'user_memory_items'
              AND column_name = 'heat_score'
        ) THEN
            EXECUTE '
                UPDATE user_memory_items
                SET
                    memory_strength = COALESCE(memory_strength, heat_score, 1.0),
                    stability = COALESCE(stability, GREATEST(3.0, 7.0 / NULLIF(COALESCE(decay_rate, 0.05), 0.0)), 7.0),
                    review_count = COALESCE(review_count, use_count, 0),
                    recall_count = COALESCE(recall_count, use_count, 0),
                    retention_score = COALESCE(retention_score, heat_score, 1.0),
                    last_recalled_at = COALESCE(last_recalled_at, last_used_at, last_accessed_at)
                WHERE
                    memory_strength IS NULL
                    OR stability IS NULL
                    OR review_count IS NULL
                    OR recall_count IS NULL
                    OR retention_score IS NULL
                    OR last_recalled_at IS NULL
            ';
        END IF;
    END $$;
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_user_memory_items_retention
    ON user_memory_items (user_id, archived_at, retention_score)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_user_memory_items_layer_type
    ON user_memory_items (user_id, memory_layer, memory_type)
    """,
]


def ensure_memory_schema(engine) -> None:
    """Apply additive schema sync for memory-related tables."""
    with engine.begin() as connection:
        for statement in MEMORY_SCHEMA_DDL:
            connection.execute(text(statement))

"""
Multi-layer memory services.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional
from uuid import UUID

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import database as db_models
from app.services.cache import get_cache_manager


settings = get_settings()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clip_text(text: str, limit: int = 240) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _normalize_string(value: str) -> str:
    value = (value or "").strip().lower()
    return re.sub(r"\s+", " ", value)


def _extract_keywords(text: str) -> List[str]:
    text = (text or "").strip().lower()
    if not text:
        return []

    keywords: List[str] = []
    for token in re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", text):
        if re.fullmatch(r"[\u4e00-\u9fff]{4,}", token):
            keywords.extend(token[i:i + 2] for i in range(0, len(token) - 1))
        else:
            keywords.append(token)
    return list(dict.fromkeys(keywords))


def _cosine_similarity(vec1: Optional[List[float]], vec2: Optional[List[float]]) -> float:
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    dot = 0.0
    norm1 = 0.0
    norm2 = 0.0
    for left, right in zip(vec1, vec2):
        dot += left * right
        norm1 += left * left
        norm2 += right * right
    if norm1 <= 0 or norm2 <= 0:
        return 0.0
    return dot / (math.sqrt(norm1) * math.sqrt(norm2))


class MemoryService:
    """Coordinates working memory, structured preferences, and episodic memory."""

    def __init__(self, db: Session, cache_manager=None):
        self.db = db
        self.cache = cache_manager or get_cache_manager()

    def build_memory_context(
        self,
        *,
        user_id: str,
        doc_id: str,
        session_id: str,
        user_message: str,
        top_k: int = 5,
    ) -> Dict[str, Any]:
        preferences = self.list_user_preferences(user_id)
        document_preferences = self.list_document_preferences(user_id, doc_id)
        editing_rules = self.list_editing_rules(user_id, doc_id)
        retrieved_memories = self.search_memories(
            user_id=user_id,
            doc_id=doc_id,
            session_id=session_id,
            query=user_message,
            top_k=top_k,
        )
        working_memory = self.get_working_memory(session_id) or {}

        if retrieved_memories:
            self._mark_memories_injected(retrieved_memories)

        stable_preferences_lines = self._build_preference_lines(preferences, document_preferences)
        rule_lines = self._build_rule_lines(editing_rules)
        recent_context_lines = self._build_memory_lines(retrieved_memories, working_memory)

        sections: List[str] = []
        if stable_preferences_lines:
            sections.append("稳定偏好：\n" + "\n".join(f"- {line}" for line in stable_preferences_lines))
        if rule_lines:
            sections.append("已知编辑规则：\n" + "\n".join(f"- {line}" for line in rule_lines))
        if recent_context_lines:
            sections.append("近期相关上下文：\n" + "\n".join(f"- {line}" for line in recent_context_lines))

        return {
            "preferences": preferences,
            "document_preferences": document_preferences,
            "editing_rules": editing_rules,
            "retrieved_memories": retrieved_memories,
            "working_memory": working_memory,
            "prompt_context": "\n\n".join(sections).strip(),
            "summary": {
                "preference_count": len(preferences) + len(document_preferences),
                "rule_count": len(editing_rules),
                "memory_count": len(retrieved_memories),
            },
        }

    def record_turn(
        self,
        *,
        user_id: str,
        doc_id: str,
        session_id: str,
        user_content: str,
        user_meta: Dict[str, Any],
        assistant_content: str,
        assistant_meta: Dict[str, Any],
        source_message_ids: Optional[List[str]] = None,
    ) -> None:
        self._update_working_memory(
            session_id=session_id,
            user_id=user_id,
            doc_id=doc_id,
            user_content=user_content,
            assistant_content=assistant_content,
            assistant_meta=assistant_meta,
        )

        for candidate in self._extract_preference_candidates(user_content):
            self.upsert_user_preference(
                user_id=user_id,
                preference_key=candidate["key"],
                preference_value=candidate["value"],
                source=candidate["source"],
                source_type=candidate.get("source_type", "inferred"),
                confidence=candidate["confidence"],
                details={"from_message": _clip_text(user_content, 160)},
            )

        for candidate in self._extract_document_preference_candidates(user_content):
            self.upsert_document_preference(
                user_id=user_id,
                doc_id=doc_id,
                preference_key=candidate["key"],
                preference_value=candidate["value"],
                scope_type="document",
                scope_key=doc_id,
                source=candidate["source"],
                source_type=candidate.get("source_type", "inferred"),
                confidence=candidate["confidence"],
            )

        for candidate in self._extract_rule_candidates(user_content, doc_id):
            self.upsert_editing_rule(
                user_id=user_id,
                doc_id=doc_id if candidate["scope_type"] == "document" else None,
                scope_type=candidate["scope_type"],
                scope_key=candidate["scope_key"],
                rule_name=candidate["rule_name"],
                rule_type=candidate["rule_type"],
                rule_definition=candidate["rule_definition"],
                source=candidate["source"],
                rule_source=candidate.get("rule_source", "inferred"),
                confidence=candidate["confidence"],
            )

        memory_candidate = self._build_episodic_memory_candidate(
            user_id=user_id,
            doc_id=doc_id,
            session_id=session_id,
            user_content=user_content,
            assistant_content=assistant_content,
            assistant_meta=assistant_meta,
            source_message_ids=source_message_ids or [],
        )
        if memory_candidate:
            self.upsert_memory_item(**memory_candidate)

    def list_user_preferences(self, user_id: str) -> List[db_models.UserPreference]:
        user_uuid = UUID(user_id)
        return self.db.query(db_models.UserPreference).filter(
            db_models.UserPreference.user_id == user_uuid
        ).order_by(db_models.UserPreference.preference_key.asc()).all()

    def list_document_preferences(self, user_id: str, doc_id: str) -> List[db_models.DocumentPreference]:
        user_uuid = UUID(user_id)
        doc_uuid = UUID(doc_id)
        return self.db.query(db_models.DocumentPreference).filter(
            db_models.DocumentPreference.user_id == user_uuid,
            or_(
                db_models.DocumentPreference.doc_id == doc_uuid,
                and_(
                    db_models.DocumentPreference.doc_id.is_(None),
                    db_models.DocumentPreference.scope_type != "document",
                ),
            ),
        ).order_by(db_models.DocumentPreference.updated_at.desc()).all()

    def list_editing_rules(self, user_id: str, doc_id: str) -> List[db_models.EditingRule]:
        user_uuid = UUID(user_id)
        doc_uuid = UUID(doc_id)
        return self.db.query(db_models.EditingRule).filter(
            db_models.EditingRule.user_id == user_uuid,
            db_models.EditingRule.is_active.is_(True),
            or_(db_models.EditingRule.doc_id.is_(None), db_models.EditingRule.doc_id == doc_uuid)
        ).order_by(db_models.EditingRule.updated_at.desc()).limit(20).all()

    def list_memory_items(
        self,
        *,
        user_id: str,
        memory_type: Optional[str] = None,
        scope: Optional[str] = None,
        doc_id: Optional[str] = None,
        active_only: bool = True,
        limit: int = 50,
    ) -> List[db_models.UserMemoryItem]:
        query = self.db.query(db_models.UserMemoryItem).filter(
            db_models.UserMemoryItem.user_id == UUID(user_id)
        )
        if memory_type:
            query = query.filter(db_models.UserMemoryItem.memory_type == memory_type)
        if scope:
            query = query.filter(db_models.UserMemoryItem.scope == scope)
        if doc_id:
            query = query.filter(db_models.UserMemoryItem.doc_id == UUID(doc_id))
        if active_only:
            query = query.filter(db_models.UserMemoryItem.archived_at.is_(None))
        return query.order_by(
            db_models.UserMemoryItem.retention_score.desc(),
            db_models.UserMemoryItem.updated_at.desc()
        ).limit(limit).all()

    def search_memories(
        self,
        *,
        user_id: str,
        doc_id: str,
        session_id: str,
        query: str,
        top_k: int = 5,
    ) -> List[db_models.UserMemoryItem]:
        candidates = self.db.query(db_models.UserMemoryItem).filter(
            db_models.UserMemoryItem.user_id == UUID(user_id),
            db_models.UserMemoryItem.archived_at.is_(None),
        ).order_by(
            db_models.UserMemoryItem.updated_at.desc()
        ).limit(100).all()

        query_embedding = self._generate_embedding_safe(query)
        query_keywords = set(_extract_keywords(query))
        now = _utcnow()
        ranked: List[tuple[float, db_models.UserMemoryItem]] = []

        for item in candidates:
            base_text = " ".join(filter(None, [item.retrieval_text, item.title, item.summary, item.content]))
            text_score = SequenceMatcher(
                None,
                _normalize_string(query)[:400],
                _normalize_string(base_text)[:400],
            ).ratio()
            item_keywords = set(_extract_keywords(base_text))
            overlap = len(query_keywords & item_keywords) / max(len(query_keywords), 1)
            vector_score = _cosine_similarity(query_embedding, item.embedding) if query_embedding else 0.0
            same_doc_boost = 0.18 if item.doc_id and str(item.doc_id) == doc_id else 0.0
            same_session_boost = 0.08 if item.session_id and str(item.session_id) == session_id else 0.0
            retention_score = self._current_retention(item, now)
            anchor_candidates = [item.last_recalled_at, item.last_reinforced_at, item.updated_at, item.created_at]
            anchor_time = max((ts for ts in anchor_candidates if ts), default=now)
            days_since_recall = max((now - anchor_time).total_seconds() / 86400.0, 0.0)
            recency_score = math.exp(-days_since_recall / 30.0)

            final_score = (
                max(text_score, overlap) * 0.35
                + vector_score * 0.25
                + retention_score * 0.15
                + recency_score * 0.07
                + same_doc_boost
                + same_session_boost
            )

            if final_score >= 0.12 or same_doc_boost > 0:
                ranked.append((final_score, item))

        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in ranked[:top_k]]

    def upsert_user_preference(
        self,
        *,
        user_id: str,
        preference_key: str,
        preference_value: Any,
        source: str,
        confidence: float,
        source_type: str = "inferred",
        details: Optional[Dict[str, Any]] = None,
    ) -> db_models.UserPreference:
        now = _utcnow()
        existing = self.db.query(db_models.UserPreference).filter(
            db_models.UserPreference.user_id == UUID(user_id),
            db_models.UserPreference.preference_key == preference_key,
        ).first()

        if existing:
            existing.preference_value = preference_value
            existing.source = source
            existing.source_type = source_type
            existing.confidence = max(existing.confidence, confidence)
            existing.last_seen_at = now
            existing.updated_at = now
            self._audit(
                user_id=user_id,
                memory_layer="persona",
                memory_category="profile",
                target_table="user_preferences",
                target_id=str(existing.preference_id),
                action="update",
                source=source,
                source_type=source_type,
                confidence=confidence,
                details={"preference_key": preference_key, **(details or {})},
            )
            return existing

        created = db_models.UserPreference(
            user_id=UUID(user_id),
            preference_key=preference_key,
            preference_value=preference_value,
            source=source,
            source_type=source_type,
            confidence=confidence,
            first_seen_at=now,
            last_seen_at=now,
        )
        self.db.add(created)
        self.db.flush()
        self._audit(
            user_id=user_id,
            memory_layer="persona",
            memory_category="profile",
            target_table="user_preferences",
            target_id=str(created.preference_id),
            action="insert",
            source=source,
            source_type=source_type,
            confidence=confidence,
            details={"preference_key": preference_key, **(details or {})},
        )
        return created

    def delete_user_preference(self, *, user_id: str, preference_key: str) -> bool:
        item = self.db.query(db_models.UserPreference).filter(
            db_models.UserPreference.user_id == UUID(user_id),
            db_models.UserPreference.preference_key == preference_key,
        ).first()
        if not item:
            return False
        self._audit(
            user_id=user_id,
            memory_layer="persona",
            memory_category="profile",
            target_table="user_preferences",
            target_id=str(item.preference_id),
            action="delete",
            source="user_explicit",
            source_type="explicit",
            confidence=item.confidence,
            details={"preference_key": preference_key},
        )
        self.db.delete(item)
        return True

    def upsert_document_preference(
        self,
        *,
        user_id: str,
        doc_id: str,
        preference_key: str,
        preference_value: Any,
        scope_type: str,
        scope_key: Optional[str],
        source: str,
        confidence: float,
        source_type: str = "inferred",
    ) -> db_models.DocumentPreference:
        existing = self.db.query(db_models.DocumentPreference).filter(
            db_models.DocumentPreference.user_id == UUID(user_id),
            db_models.DocumentPreference.doc_id == UUID(doc_id),
            db_models.DocumentPreference.preference_key == preference_key,
            db_models.DocumentPreference.scope_type == scope_type,
        ).first()
        now = _utcnow()

        if existing:
            existing.preference_value = preference_value
            existing.scope_key = scope_key
            existing.source = source
            existing.source_type = source_type
            existing.confidence = max(existing.confidence, confidence)
            existing.updated_at = now
            self._audit(
                user_id=user_id,
                memory_layer="relation",
                memory_category="profile",
                target_table="document_preferences",
                target_id=str(existing.preference_id),
                action="update",
                source=source,
                source_type=source_type,
                confidence=confidence,
                details={"preference_key": preference_key},
            )
            return existing

        created = db_models.DocumentPreference(
            user_id=UUID(user_id),
            doc_id=UUID(doc_id),
            memory_layer="relation",
            source_type=source_type,
            entity_type="document",
            scope_type=scope_type,
            scope_key=scope_key,
            preference_key=preference_key,
            preference_value=preference_value,
            source=source,
            confidence=confidence,
        )
        self.db.add(created)
        self.db.flush()
        self._audit(
            user_id=user_id,
            memory_layer="relation",
            memory_category="profile",
            target_table="document_preferences",
            target_id=str(created.preference_id),
            action="insert",
            source=source,
            source_type=source_type,
            confidence=confidence,
            details={"preference_key": preference_key},
        )
        return created

    def upsert_editing_rule(
        self,
        *,
        user_id: str,
        doc_id: Optional[str],
        scope_type: str,
        scope_key: Optional[str],
        rule_name: str,
        rule_type: str,
        rule_definition: Dict[str, Any],
        source: str,
        confidence: float,
        rule_source: str = "inferred",
    ) -> db_models.EditingRule:
        query = self.db.query(db_models.EditingRule).filter(
            db_models.EditingRule.user_id == UUID(user_id),
            db_models.EditingRule.rule_name == rule_name,
            db_models.EditingRule.rule_type == rule_type,
            db_models.EditingRule.scope_type == scope_type,
            db_models.EditingRule.is_active.is_(True),
        )
        if doc_id:
            query = query.filter(db_models.EditingRule.doc_id == UUID(doc_id))
        else:
            query = query.filter(db_models.EditingRule.doc_id.is_(None))
        if scope_key:
            query = query.filter(db_models.EditingRule.scope_key == scope_key)
        else:
            query = query.filter(db_models.EditingRule.scope_key.is_(None))

        existing = query.first()
        now = _utcnow()
        if existing:
            existing.rule_definition = rule_definition
            existing.source = source
            existing.rule_source = rule_source
            existing.confidence = max(existing.confidence, confidence)
            existing.last_confirmed_at = now
            existing.updated_at = now
            self._audit(
                user_id=user_id,
                memory_layer="relation",
                memory_category="profile",
                target_table="editing_rules",
                target_id=str(existing.rule_id),
                action="update",
                source=source,
                source_type=rule_source,
                confidence=confidence,
                details={"rule_name": rule_name, "rule_type": rule_type},
            )
            return existing

        created = db_models.EditingRule(
            user_id=UUID(user_id),
            doc_id=UUID(doc_id) if doc_id else None,
            memory_layer="relation",
            rule_source=rule_source,
            scope_type=scope_type,
            scope_key=scope_key,
            rule_name=rule_name,
            rule_type=rule_type,
            rule_definition=rule_definition,
            source=source,
            confidence=confidence,
            is_active=True,
            last_confirmed_at=now,
        )
        self.db.add(created)
        self.db.flush()
        self._audit(
            user_id=user_id,
            memory_layer="relation",
            memory_category="profile",
            target_table="editing_rules",
            target_id=str(created.rule_id),
            action="insert",
            source=source,
            source_type=rule_source,
            confidence=confidence,
            details={"rule_name": rule_name, "rule_type": rule_type},
        )
        return created

    def upsert_memory_item(
        self,
        *,
        user_id: str,
        doc_id: Optional[str],
        session_id: Optional[str],
        memory_layer: str,
        memory_type: str,
        memory_subtype: Optional[str],
        scope: str,
        title: str,
        content: str,
        summary: Optional[str],
        retrieval_text: Optional[str],
        source_type: str,
        source_message_ids: List[str],
        extraction_reason: Dict[str, Any],
        confidence: float,
        importance: float,
        memory_strength: float,
        stability: float,
        retention_score: float,
        min_keep_until: Optional[datetime],
        max_keep_until: Optional[datetime],
        source: str,
    ) -> db_models.UserMemoryItem:
        existing = self._find_similar_memory(
            user_id=user_id,
            doc_id=doc_id,
            session_id=session_id,
            title=title,
            content=content,
        )
        now = _utcnow()
        if existing:
            existing.summary = summary or existing.summary
            existing.content = content
            existing.retrieval_text = retrieval_text or existing.retrieval_text
            existing.confidence = max(existing.confidence, confidence)
            existing.importance = max(existing.importance, importance)
            existing.memory_strength = min(1.5, max(existing.memory_strength or 0.8, memory_strength, self._current_retention(existing, now)) + 0.12)
            growth_factor = 1.0 + min(0.45, 0.2 * importance + 0.1 * confidence)
            existing.stability = min(180.0, max(existing.stability or 7.0, stability) * growth_factor)
            existing.retention_score = min(1.0, max(existing.retention_score or 0.0, retention_score, existing.memory_strength))
            existing.review_count = (existing.review_count or 0) + 1
            existing.last_reinforced_at = now
            existing.min_keep_until = max(filter(None, [existing.min_keep_until, min_keep_until]), default=min_keep_until)
            existing.max_keep_until = max(filter(None, [existing.max_keep_until, max_keep_until]), default=max_keep_until)
            existing.extraction_reason = {**(existing.extraction_reason or {}), **(extraction_reason or {})}
            existing.source_message_ids = list(dict.fromkeys((existing.source_message_ids or []) + source_message_ids))
            existing.memory_subtype = memory_subtype or existing.memory_subtype
            existing.source_type = source_type or existing.source_type
            self._audit(
                user_id=user_id,
                memory_layer=memory_layer,
                memory_category="episodic",
                target_table="user_memory_items",
                target_id=str(existing.memory_id),
                action="merge",
                source=source,
                source_type=source_type,
                confidence=confidence,
                details={
                    "memory_type": memory_type,
                    "memory_subtype": memory_subtype,
                    "scope": scope,
                    "retention_score": existing.retention_score,
                },
            )
            return existing

        created = db_models.UserMemoryItem(
            user_id=UUID(user_id),
            doc_id=UUID(doc_id) if doc_id else None,
            session_id=UUID(session_id) if session_id else None,
            memory_layer=memory_layer,
            memory_type=memory_type,
            memory_subtype=memory_subtype,
            scope=scope,
            title=title,
            content=content,
            summary=summary,
            retrieval_text=retrieval_text,
            source_type=source_type,
            source_message_ids=source_message_ids,
            extraction_reason=extraction_reason,
            confidence=confidence,
            importance=importance,
            memory_strength=memory_strength,
            stability=stability,
            review_count=0,
            recall_count=0,
            retention_score=retention_score,
            last_reinforced_at=now,
            min_keep_until=min_keep_until,
            max_keep_until=max_keep_until,
            embedding=self._generate_embedding_safe(" ".join(filter(None, [retrieval_text, title, summary, content]))),
        )
        self.db.add(created)
        self.db.flush()
        self._audit(
            user_id=user_id,
            memory_layer=memory_layer,
            memory_category="episodic",
            target_table="user_memory_items",
            target_id=str(created.memory_id),
            action="insert",
            source=source,
            source_type=source_type,
            confidence=confidence,
            details={"memory_type": memory_type, "memory_subtype": memory_subtype, "scope": scope},
        )
        return created

    def delete_memory_item(self, *, user_id: str, memory_id: str) -> bool:
        item = self.db.query(db_models.UserMemoryItem).filter(
            db_models.UserMemoryItem.memory_id == UUID(memory_id),
            db_models.UserMemoryItem.user_id == UUID(user_id),
        ).first()
        if not item:
            return False
        self._audit(
            user_id=user_id,
            memory_layer=item.memory_layer,
            memory_category="episodic",
            target_table="user_memory_items",
            target_id=str(item.memory_id),
            action="delete",
            source="user_explicit",
            source_type="explicit",
            confidence=item.confidence,
            details={"memory_type": item.memory_type, "scope": item.scope},
        )
        self.db.delete(item)
        return True

    def get_working_memory(self, session_id: str) -> Optional[dict]:
        return self.cache.get_working_memory(session_id)

    def set_working_memory(self, session_id: str, payload: dict, ttl: int = 86400) -> bool:
        return self.cache.set_working_memory(session_id, payload, ttl=ttl)

    def clear_working_memory(self, session_id: str) -> None:
        self.cache.delete_working_memory(session_id)

    def run_maintenance(self, *, user_id: Optional[str] = None) -> Dict[str, int]:
        query = self.db.query(db_models.UserMemoryItem).filter(
            db_models.UserMemoryItem.archived_at.is_(None)
        )
        if user_id:
            query = query.filter(db_models.UserMemoryItem.user_id == UUID(user_id))

        decayed = 0
        archived = 0
        now = _utcnow()

        for item in query.all():
            anchor_candidates = [item.last_recalled_at, item.last_reinforced_at, item.updated_at, item.created_at]
            anchor_time = max((ts for ts in anchor_candidates if ts), default=now)
            days_idle = max((now - anchor_time).total_seconds() / 86400.0, 0.0)
            item.retention_score = self._current_retention(item, now)
            decayed += 1

            short_term_archive = item.scope == "short_term" and days_idle >= 7 and item.retention_score < 0.25
            medium_term_archive = item.scope == "medium_term" and days_idle >= 30 and item.retention_score < 0.18
            protected = item.min_keep_until and now < item.min_keep_until
            max_keep_expired = item.max_keep_until and now >= item.max_keep_until

            if not protected and (short_term_archive or medium_term_archive or max_keep_expired):
                item.archived_at = now
                archived += 1
                self._audit(
                    user_id=str(item.user_id),
                    memory_layer=item.memory_layer,
                    memory_category="episodic",
                    target_table="user_memory_items",
                    target_id=str(item.memory_id),
                    action="archive",
                    source="memory_maintenance",
                    source_type="forgetting_curve",
                    confidence=item.confidence,
                    details={"scope": item.scope, "retention_score": item.retention_score},
                )

        return {"decayed": decayed, "archived": archived}

    def get_session_history(self, *, user_id: str, session_id: str) -> tuple[db_models.ChatSession, List[db_models.ChatMessage]]:
        session = self.db.query(db_models.ChatSession).filter(
            db_models.ChatSession.session_id == UUID(session_id),
            db_models.ChatSession.user_id == UUID(user_id),
        ).first()
        if not session:
            raise ValueError("session not found")
        messages = self.db.query(db_models.ChatMessage).filter(
            db_models.ChatMessage.session_id == UUID(session_id)
        ).order_by(db_models.ChatMessage.created_at.asc()).all()
        return session, messages

    def _find_similar_memory(
        self,
        *,
        user_id: str,
        doc_id: Optional[str],
        session_id: Optional[str],
        title: str,
        content: str,
    ) -> Optional[db_models.UserMemoryItem]:
        query = self.db.query(db_models.UserMemoryItem).filter(
            db_models.UserMemoryItem.user_id == UUID(user_id),
            db_models.UserMemoryItem.archived_at.is_(None),
        )
        if doc_id:
            query = query.filter(
                or_(
                    db_models.UserMemoryItem.doc_id == UUID(doc_id),
                    db_models.UserMemoryItem.doc_id.is_(None),
                )
            )
        recent_items = query.order_by(db_models.UserMemoryItem.updated_at.desc()).limit(20).all()

        best_match = None
        best_score = 0.0
        for item in recent_items:
            combined = f"{item.title} {item.content}"
            score = SequenceMatcher(
                None,
                _normalize_string(f"{title} {content}")[:500],
                _normalize_string(combined)[:500],
            ).ratio()
            if session_id and item.session_id and str(item.session_id) == session_id:
                score += 0.1
            if score > best_score:
                best_score = score
                best_match = item
        return best_match if best_score >= 0.82 else None

    def _build_preference_lines(
        self,
        preferences: Iterable[db_models.UserPreference],
        document_preferences: Iterable[db_models.DocumentPreference],
    ) -> List[str]:
        lines: List[str] = []
        for item in preferences:
            lines.append(f"{item.preference_key}: {self._render_jsonish(item.preference_value)}")
        for item in document_preferences:
            lines.append(f"{item.preference_key}: {self._render_jsonish(item.preference_value)}")
        return lines[:8]

    def _build_rule_lines(self, rules: Iterable[db_models.EditingRule]) -> List[str]:
        lines: List[str] = []
        for item in rules:
            lines.append(f"{item.rule_name} ({item.rule_type}): {self._render_jsonish(item.rule_definition)}")
        return lines[:8]

    def _build_memory_lines(
        self,
        memories: Iterable[db_models.UserMemoryItem],
        working_memory: Dict[str, Any],
    ) -> List[str]:
        lines: List[str] = []
        current_goal = working_memory.get("current_goal")
        if current_goal:
            lines.append(f"当前会话目标：{_clip_text(current_goal, 100)}")
        pending_confirmation = working_memory.get("pending_confirmation")
        if pending_confirmation:
            lines.append("当前会话存在待确认修改")
        clarification = working_memory.get("clarification")
        if clarification:
            question = clarification.get("question") or clarification.get("message")
            if question:
                lines.append(f"当前会话仍待澄清：{_clip_text(question, 100)}")
        for item in memories:
            lines.append(_clip_text(item.summary or item.title or item.content, 160))
        return lines[:8]

    def _extract_preference_candidates(self, user_message: str) -> List[Dict[str, Any]]:
        message = (user_message or "").strip()
        lower = message.lower()
        candidates: List[Dict[str, Any]] = []

        if any(token in message for token in ["中文回复", "用中文", "中文回答", "中文输出"]):
            candidates.append({"key": "response_language", "value": "zh", "confidence": 0.95, "source": "memory_extractor_rule", "source_type": "explicit"})
        if any(token in lower for token in ["english", "reply in english"]) or any(token in message for token in ["英文回复", "用英文", "英文回答"]):
            candidates.append({"key": "response_language", "value": "en", "confidence": 0.95, "source": "memory_extractor_rule", "source_type": "explicit"})

        if any(token in message for token in ["简洁", "简短", "精炼", "直接一点"]):
            candidates.append({"key": "response_style", "value": "concise", "confidence": 0.88, "source": "memory_extractor_rule", "source_type": "explicit"})
        if any(token in message for token in ["详细", "展开", "扩展", "说细一点"]):
            candidates.append({"key": "response_style", "value": "detailed", "confidence": 0.88, "source": "memory_extractor_rule", "source_type": "explicit"})
        if any(token in message for token in ["分点", "结构化", "列表", "按点", "表格"]):
            candidates.append({"key": "response_structure", "value": "structured", "confidence": 0.84, "source": "memory_extractor_rule", "source_type": "explicit"})
        if any(token in message for token in ["先给结论", "先说结论", "先写结论"]):
            candidates.append({"key": "response_structure", "value": "conclusion_first", "confidence": 0.93, "source": "memory_extractor_rule", "source_type": "explicit"})

        if any(token in message for token in ["保守修改", "少改", "不要大改", "最小改动", "尽量少改"]):
            candidates.append({"key": "editing_style", "value": "conservative", "confidence": 0.9, "source": "memory_extractor_rule", "source_type": "explicit"})
        if any(token in message for token in ["大胆改", "激进", "重写", "大幅润色"]):
            candidates.append({"key": "editing_style", "value": "rewrite_aggressive", "confidence": 0.86, "source": "memory_extractor_rule", "source_type": "explicit"})

        if any(token in message for token in ["先预览", "先确认", "确认后再应用", "先给我看 diff", "先看修改"]):
            candidates.append({"key": "confirmation_preference", "value": "preview_first", "confidence": 0.92, "source": "memory_extractor_rule", "source_type": "explicit"})
        if any(token in message for token in ["低风险直接应用", "小改动直接应用"]):
            candidates.append({"key": "confirmation_preference", "value": "auto_apply_low_risk", "confidence": 0.8, "source": "memory_extractor_rule", "source_type": "explicit"})

        return list({item["key"]: item for item in candidates}.values())

    def _extract_rule_candidates(self, user_message: str, doc_id: str) -> List[Dict[str, Any]]:
        message = (user_message or "").strip()
        candidates: List[Dict[str, Any]] = []

        replace_match = re.search(r"(?:统一|以后).*?[“\"']?([^“\"'，。,；;]+?)[”\"']?(?:改成|替换为)[“\"']?([^“\"'，。,；;]+?)[”\"']?", message)
        if replace_match:
            source_term = replace_match.group(1).strip()
            target_term = replace_match.group(2).strip()
            if source_term and target_term and source_term != target_term:
                candidates.append({
                    "scope_type": "user",
                    "scope_key": None,
                    "rule_name": f"术语映射:{source_term}->{target_term}",
                    "rule_type": "terminology_mapping",
                    "rule_definition": {"from": source_term, "to": target_term},
                    "source": "memory_extractor_rule",
                    "rule_source": "explicit",
                    "confidence": 0.88,
                })

        blacklist_match = re.search(r"(?:以后|统一|默认)?.*?(?:不要用|不要出现|避免使用)[“\"']?([^“\"'，。,；;]+?)[”\"']?(?:$|，|。|；|;)", message)
        if blacklist_match:
            blocked_term = blacklist_match.group(1).strip()
            if blocked_term:
                candidates.append({
                    "scope_type": "user",
                    "scope_key": None,
                    "rule_name": f"禁用词:{blocked_term}",
                    "rule_type": "blacklist_term",
                    "rule_definition": {"term": blocked_term},
                    "source": "memory_extractor_rule",
                    "rule_source": "explicit",
                    "confidence": 0.84,
                })

        return candidates

    def _extract_document_preference_candidates(self, user_message: str) -> List[Dict[str, Any]]:
        message = (user_message or "").strip()
        candidates: List[Dict[str, Any]] = []

        if "标题层级" in message:
            candidates.append({
                "key": "title_hierarchy_preference",
                "value": {"instruction": _clip_text(message, 240)},
                "source": "memory_extractor_rule",
                "source_type": "explicit",
                "confidence": 0.82,
            })

        if "格式要求" in message or "固定格式" in message:
            candidates.append({
                "key": "document_format_requirement",
                "value": {"instruction": _clip_text(message, 240)},
                "source": "memory_extractor_rule",
                "source_type": "explicit",
                "confidence": 0.8,
            })

        if "术语规范" in message or "团队术语" in message or "公司术语" in message:
            candidates.append({
                "key": "terminology_standard",
                "value": {"instruction": _clip_text(message, 240)},
                "source": "memory_extractor_rule",
                "source_type": "explicit",
                "confidence": 0.84,
            })

        return candidates

    def _build_episodic_memory_candidate(
        self,
        *,
        user_id: str,
        doc_id: str,
        session_id: str,
        user_content: str,
        assistant_content: str,
        assistant_meta: Dict[str, Any],
        source_message_ids: List[str],
    ) -> Optional[Dict[str, Any]]:
        status = assistant_meta.get("status")
        operation_type = assistant_meta.get("operation_type", "unknown")
        if status not in {"applied", "failed"}:
            return None
        if len((user_content or "").strip()) < 4:
            return None

        doc_title = self._get_document_title(doc_id)
        memory_type = "edit_pattern" if status == "applied" else "failure_case"
        memory_subtype = "confirmed_edit" if status == "applied" else "failed_edit"
        scope = "medium_term"
        importance = 0.72 if status == "failed" else 0.65
        now = _utcnow()
        stability = 21.0 if status == "applied" else 12.0
        memory_strength = 0.92 if status == "applied" else 0.78
        retention_score = min(1.0, memory_strength)

        title = f"{doc_title or '文档'}:{operation_type}:{status}"
        content = (
            f"用户在文档《{doc_title or doc_id}》中发起 {operation_type} 编辑。"
            f"用户请求：{_clip_text(user_content, 180)}。"
            f"结果：{status}。"
        )
        summary = _clip_text(assistant_content or content, 180)
        retrieval_text = f"{title} {user_content} {assistant_content} {operation_type} {status}"

        return {
            "user_id": user_id,
            "doc_id": doc_id,
            "session_id": session_id,
            "memory_layer": "episodic",
            "memory_type": memory_type,
            "memory_subtype": memory_subtype,
            "scope": scope,
            "title": title,
            "content": content,
            "summary": summary,
            "retrieval_text": retrieval_text,
            "source_type": "turn_trace",
            "source_message_ids": source_message_ids,
            "extraction_reason": {
                "status": status,
                "operation_type": operation_type,
                "new_rev_id": assistant_meta.get("new_rev_id"),
            },
            "confidence": 0.8 if status == "applied" else 0.76,
            "importance": importance,
            "memory_strength": memory_strength,
            "stability": stability,
            "retention_score": retention_score,
            "min_keep_until": now + timedelta(days=7),
            "max_keep_until": now + timedelta(days=90),
            "source": "turn_memory_extractor",
        }

    def _update_working_memory(
        self,
        *,
        session_id: str,
        user_id: str,
        doc_id: str,
        user_content: str,
        assistant_content: str,
        assistant_meta: Dict[str, Any],
    ) -> None:
        working_memory = self.get_working_memory(session_id) or {}
        working_memory.update({
            "user_id": user_id,
            "doc_id": doc_id,
            "current_goal": user_content,
            "last_user_message": _clip_text(user_content, 200),
            "last_assistant_message": _clip_text(assistant_content, 200),
            "last_status": assistant_meta.get("status"),
            "updated_at": _utcnow().isoformat(),
        })

        status = assistant_meta.get("status")
        if status == "need_confirm":
            working_memory["pending_confirmation"] = {
                "confirm_token": assistant_meta.get("confirm_token"),
                "preview_hash": assistant_meta.get("preview_hash"),
                "new_rev_id": assistant_meta.get("new_rev_id"),
            }
        else:
            working_memory.pop("pending_confirmation", None)

        clarification = assistant_meta.get("clarification")
        if status == "need_clarification" and clarification:
            working_memory["clarification"] = clarification
        else:
            working_memory.pop("clarification", None)

        if status == "need_disambiguation":
            working_memory["disambiguation_required"] = True
        else:
            working_memory.pop("disambiguation_required", None)

        self.set_working_memory(session_id, working_memory, ttl=86400)

    def _mark_memories_injected(self, memories: Iterable[db_models.UserMemoryItem]) -> None:
        now = _utcnow()
        for item in memories:
            current_retention = self._current_retention(item, now)
            item.last_recalled_at = now
            item.recall_count = (item.recall_count or 0) + 1
            item.review_count = (item.review_count or 0) + 1
            item.memory_strength = min(1.5, max(item.memory_strength or 0.7, current_retention) + 0.08)
            item.stability = min(180.0, max(item.stability or 7.0, 3.0) * 1.18)
            item.retention_score = min(1.0, item.memory_strength)

    def _generate_embedding_safe(self, text: str) -> Optional[List[float]]:
        if not settings.ENABLE_VECTOR_SEARCH:
            return None
        try:
            from app.services.embedding import get_embedding_service

            embedding = get_embedding_service().generate_embedding(text)
            if not embedding or not any(abs(value) > 1e-12 for value in embedding):
                return None
            return embedding
        except Exception:
            return None

    def _render_jsonish(self, value: Any) -> str:
        if isinstance(value, dict):
            return ", ".join(f"{key}={val}" for key, val in value.items())
        if isinstance(value, list):
            return ", ".join(str(item) for item in value)
        return str(value)

    def _get_document_title(self, doc_id: str) -> Optional[str]:
        document = self.db.query(db_models.Document).filter(
            db_models.Document.doc_id == UUID(doc_id)
        ).first()
        return document.title if document else None

    def _audit(
        self,
        *,
        user_id: str,
        memory_layer: str,
        memory_category: str,
        target_table: str,
        target_id: str,
        action: str,
        source: str,
        source_type: str,
        confidence: float,
        details: Dict[str, Any],
    ) -> None:
        self.db.add(
            db_models.MemoryAuditLog(
                user_id=UUID(user_id),
                memory_layer=memory_layer,
                memory_category=memory_category,
                target_table=target_table,
                target_id=target_id,
                action=action,
                source=source,
                source_type=source_type,
                confidence=confidence,
                details=details,
            )
        )

    def _current_retention(self, item: db_models.UserMemoryItem, now: Optional[datetime] = None) -> float:
        now = now or _utcnow()
        anchor_candidates = [item.last_recalled_at, item.last_reinforced_at, item.updated_at, item.created_at]
        anchor_time = max((ts for ts in anchor_candidates if ts), default=now)
        days_elapsed = max((now - anchor_time).total_seconds() / 86400.0, 0.0)
        stability = max(item.stability or 7.0, 1.0)
        memory_strength = max(item.memory_strength or 0.5, 0.05)
        retention = memory_strength * math.exp(-days_elapsed / stability)
        return max(min(retention, 1.0), 0.0)

from sqlalchemy import Column, String, Integer, BigInteger, Text, DateTime, Boolean, ForeignKey, Index, CheckConstraint, Float
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
import uuid
from pgvector.sqlalchemy import Vector

Base = declarative_base()


class Document(Base):
    __tablename__ = "documents"
    
    doc_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    title = Column(Text, nullable=False)
    source_filename = Column(Text)
    source_format = Column(Text)
    
    total_blocks = Column(Integer, nullable=False, default=0)
    total_chars = Column(Integer, nullable=False, default=0)
    
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        Index('idx_documents_user_created', 'user_id', 'created_at'),
    )


class DocumentRevision(Base):
    __tablename__ = "document_revisions"
    
    rev_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_id = Column(UUID(as_uuid=True), ForeignKey('documents.doc_id', ondelete='CASCADE'), nullable=False)
    rev_no = Column(BigInteger, nullable=False)
    parent_rev_id = Column(UUID(as_uuid=True), ForeignKey('document_revisions.rev_id'))
    
    created_by = Column(Text, nullable=False)
    change_summary = Column(Text)
    
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    
    __table_args__ = (
        Index('idx_revisions_doc_no', 'doc_id', 'rev_no'),
    )


class DocumentActiveRevision(Base):
    __tablename__ = "document_active_revision"
    
    doc_id = Column(UUID(as_uuid=True), ForeignKey('documents.doc_id', ondelete='CASCADE'), primary_key=True)
    rev_id = Column(UUID(as_uuid=True), ForeignKey('document_revisions.rev_id', ondelete='RESTRICT'), nullable=False)
    version = Column(BigInteger, nullable=False, default=1)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class Block(Base):
    __tablename__ = "blocks"
    
    block_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_id = Column(UUID(as_uuid=True), ForeignKey('documents.doc_id', ondelete='CASCADE'), nullable=False)
    
    first_rev_id = Column(UUID(as_uuid=True), ForeignKey('document_revisions.rev_id'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    
    deleted_at = Column(DateTime(timezone=True))
    deleted_in_rev_id = Column(UUID(as_uuid=True), ForeignKey('document_revisions.rev_id'))
    
    __table_args__ = (
        Index('idx_blocks_doc', 'doc_id'),
    )


class BlockVersion(Base):
    __tablename__ = "block_versions"
    
    block_version_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    block_id = Column(UUID(as_uuid=True), ForeignKey('blocks.block_id', ondelete='CASCADE'), nullable=False)
    rev_id = Column(UUID(as_uuid=True), ForeignKey('document_revisions.rev_id', ondelete='CASCADE'), nullable=False)
    
    order_index = Column(BigInteger, nullable=False)
    block_type = Column(Text, nullable=False)
    heading_level = Column(Integer)
    parent_heading_block_id = Column(UUID(as_uuid=True), ForeignKey('blocks.block_id'))
    
    content_md = Column(Text)
    plain_text = Column(Text)
    content_hash = Column(Text, nullable=False)
    
    # 向量 embedding 字段 (Qwen text-embedding-v3 是 1024 维)
    embedding = Column(Vector(1024))
    
    parent_version_id = Column(UUID(as_uuid=True), ForeignKey('block_versions.block_version_id'))
    
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    
    __table_args__ = (
        Index('idx_block_versions_rev_order', 'rev_id', 'order_index'),
        Index('idx_block_versions_block', 'block_id'),
        Index('idx_block_versions_parent', 'parent_version_id'),
        CheckConstraint(
            '(content_md IS NOT NULL AND parent_version_id IS NULL) OR (content_md IS NULL AND parent_version_id IS NOT NULL)',
            name='check_content_or_parent'
        ),
    )


class EditOperation(Base):
    __tablename__ = "edit_operations"
    
    op_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_id = Column(UUID(as_uuid=True), ForeignKey('documents.doc_id', ondelete='CASCADE'), nullable=False)
    rev_id = Column(UUID(as_uuid=True), ForeignKey('document_revisions.rev_id', ondelete='CASCADE'), nullable=False)
    parent_rev_id = Column(UUID(as_uuid=True))
    
    trace_id = Column(Text)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    
    op_type = Column(Text, nullable=False)
    target_block_id = Column(UUID(as_uuid=True), ForeignKey('blocks.block_id'))
    
    evidence_quote = Column(Text, nullable=False)
    quote_start = Column(Integer)
    quote_end = Column(Integer)
    
    before_hash = Column(Text)
    after_hash = Column(Text)
    
    rationale = Column(Text)
    patch_json = Column(JSONB)
    
    status = Column(Text, nullable=False, default='applied')
    
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    
    __table_args__ = (
        Index('idx_edit_ops_doc_rev', 'doc_id', 'rev_id'),
        Index('idx_edit_ops_trace', 'trace_id'),
        Index('idx_edit_ops_block', 'target_block_id'),
    )


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    
    session_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    doc_id = Column(UUID(as_uuid=True), ForeignKey('documents.doc_id', ondelete='CASCADE'), nullable=False)
    
    status = Column(Text, nullable=False, default='active')
    
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    expires_at = Column(DateTime(timezone=True))
    
    __table_args__ = (
        Index('idx_chat_sessions_user_doc', 'user_id', 'doc_id'),
        Index('idx_chat_sessions_status', 'status', 'updated_at'),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    
    msg_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey('chat_sessions.session_id', ondelete='CASCADE'), nullable=False)
    role = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    
    meta = Column(JSONB)
    
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    
    __table_args__ = (
        Index('idx_chat_messages_session_time', 'session_id', 'created_at'),
    )


class UserPreference(Base):
    __tablename__ = "user_preferences"

    preference_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    memory_layer = Column(Text, nullable=False, default="persona")
    source_type = Column(Text, nullable=False, default="inferred")
    preference_key = Column(Text, nullable=False)
    preference_value = Column(JSONB, nullable=False)
    source = Column(Text, nullable=False, default="memory_extractor")
    confidence = Column(Float, nullable=False, default=0.8)

    first_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_user_preferences_user_key", "user_id", "preference_key", unique=True),
        Index("idx_user_preferences_user_updated", "user_id", "updated_at"),
    )


class DocumentPreference(Base):
    __tablename__ = "document_preferences"

    preference_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    doc_id = Column(UUID(as_uuid=True), ForeignKey('documents.doc_id', ondelete='CASCADE'))
    memory_layer = Column(Text, nullable=False, default="relation")
    source_type = Column(Text, nullable=False, default="inferred")
    entity_type = Column(Text, nullable=False, default="document")
    scope_type = Column(Text, nullable=False, default="document")
    scope_key = Column(Text)
    preference_key = Column(Text, nullable=False)
    preference_value = Column(JSONB, nullable=False)
    source = Column(Text, nullable=False, default="memory_extractor")
    confidence = Column(Float, nullable=False, default=0.8)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_document_preferences_user_scope", "user_id", "scope_type", "scope_key"),
        Index("idx_document_preferences_doc", "doc_id"),
    )


class EditingRule(Base):
    __tablename__ = "editing_rules"

    rule_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    doc_id = Column(UUID(as_uuid=True), ForeignKey('documents.doc_id', ondelete='CASCADE'))
    memory_layer = Column(Text, nullable=False, default="relation")
    rule_source = Column(Text, nullable=False, default="inferred")
    scope_type = Column(Text, nullable=False, default="user")
    scope_key = Column(Text)
    rule_name = Column(Text, nullable=False)
    rule_type = Column(Text, nullable=False)
    rule_definition = Column(JSONB, nullable=False)
    source = Column(Text, nullable=False, default="memory_extractor")
    confidence = Column(Float, nullable=False, default=0.8)
    is_active = Column(Boolean, nullable=False, default=True)
    last_confirmed_at = Column(DateTime(timezone=True))

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_editing_rules_user_active", "user_id", "is_active", "updated_at"),
        Index("idx_editing_rules_scope", "scope_type", "scope_key"),
        Index("idx_editing_rules_doc", "doc_id"),
    )


class UserMemoryItem(Base):
    __tablename__ = "user_memory_items"

    memory_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    doc_id = Column(UUID(as_uuid=True), ForeignKey('documents.doc_id', ondelete='CASCADE'))
    session_id = Column(UUID(as_uuid=True), ForeignKey('chat_sessions.session_id', ondelete='SET NULL'))
    memory_layer = Column(Text, nullable=False, default="episodic")
    memory_type = Column(Text, nullable=False)
    memory_subtype = Column(Text)
    scope = Column(Text, nullable=False)
    title = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    summary = Column(Text)
    retrieval_text = Column(Text)
    source_type = Column(Text, nullable=False, default="turn_trace")
    source_message_ids = Column(JSONB, nullable=False, default=list)
    extraction_reason = Column(JSONB, nullable=False, default=dict)
    confidence = Column(Float, nullable=False)
    importance = Column(Float, nullable=False, default=0.5)
    memory_strength = Column(Float, nullable=False, default=1.0)
    stability = Column(Float, nullable=False, default=7.0)
    review_count = Column(Integer, nullable=False, default=0)
    recall_count = Column(Integer, nullable=False, default=0)
    retention_score = Column(Float, nullable=False, default=1.0)
    last_recalled_at = Column(DateTime(timezone=True))
    last_reinforced_at = Column(DateTime(timezone=True))
    min_keep_until = Column(DateTime(timezone=True))
    max_keep_until = Column(DateTime(timezone=True))
    archived_at = Column(DateTime(timezone=True))
    embedding = Column(Vector(1024))

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_user_memory_items_user_type_time", "user_id", "memory_type", "created_at"),
        Index("idx_user_memory_items_doc", "doc_id"),
        Index("idx_user_memory_items_session", "session_id"),
        Index("idx_user_memory_items_archived", "archived_at"),
    )


class MemoryAuditLog(Base):
    __tablename__ = "memory_audit_log"

    audit_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    memory_layer = Column(Text, nullable=False, default="episodic")
    memory_category = Column(Text, nullable=False)
    target_table = Column(Text, nullable=False)
    target_id = Column(Text, nullable=False)
    action = Column(Text, nullable=False)
    source = Column(Text, nullable=False)
    source_type = Column(Text, nullable=False, default="system")
    confidence = Column(Float, nullable=False, default=0.0)
    details = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_memory_audit_user_time", "user_id", "created_at"),
        Index("idx_memory_audit_target", "target_table", "target_id"),
    )

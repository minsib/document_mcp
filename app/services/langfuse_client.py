"""Langfuse 客户端"""
from typing import Optional, Dict, Any
from langfuse import Langfuse
from app.config import get_settings
import logging

logger = logging.getLogger(__name__)

_langfuse_client: Optional[Langfuse] = None


def get_langfuse_client() -> Optional[Langfuse]:
    """获取 Langfuse 客户端（单例）"""
    global _langfuse_client
    
    settings = get_settings()
    
    # 如果未启用，返回 None
    if not settings.ENABLE_LANGFUSE:
        return None
    
    # 如果已初始化，直接返回
    if _langfuse_client is not None:
        return _langfuse_client
    
    # 初始化客户端
    try:
        _langfuse_client = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST
        )
        logger.info("Langfuse 客户端初始化成功")
        return _langfuse_client
    except Exception as e:
        logger.error(f"Langfuse 客户端初始化失败: {e}")
        return None


def create_trace(
    name: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
):
    """创建 Trace"""
    client = get_langfuse_client()
    if not client:
        return None
    
    try:
        trace = client.trace(
            name=name,
            user_id=user_id,
            session_id=session_id,
            metadata=metadata or {}
        )
        return trace
    except Exception as e:
        logger.error(f"创建 Trace 失败: {e}")
        return None


def create_span(
    trace_id: str,
    name: str,
    input: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None
):
    """创建 Span"""
    client = get_langfuse_client()
    if not client:
        return None
    
    try:
        span = client.span(
            trace_id=trace_id,
            name=name,
            input=input,
            metadata=metadata or {}
        )
        return span
    except Exception as e:
        logger.error(f"创建 Span 失败: {e}")
        return None


def log_generation(
    trace_id: str,
    name: str,
    model: str,
    input: Any,
    output: Any,
    metadata: Optional[Dict[str, Any]] = None,
    usage: Optional[Dict[str, int]] = None
):
    """记录 LLM 生成"""
    client = get_langfuse_client()
    if not client:
        return None
    
    try:
        generation = client.generation(
            trace_id=trace_id,
            name=name,
            model=model,
            input=input,
            output=output,
            metadata=metadata or {},
            usage=usage
        )
        return generation
    except Exception as e:
        logger.error(f"记录 Generation 失败: {e}")
        return None


def flush():
    """刷新缓冲区，确保所有数据发送"""
    client = get_langfuse_client()
    if client:
        try:
            client.flush()
        except Exception as e:
            logger.error(f"Flush 失败: {e}")

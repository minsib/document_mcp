"""
健康检查
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
from typing import Dict, Optional
import redis
import meilisearch
from datetime import datetime

from app.db.connection import get_db
from app.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/health", tags=["健康检查"])


class HealthStatus(BaseModel):
    """健康状态"""
    status: str  # healthy, degraded, unhealthy
    timestamp: datetime
    version: str
    checks: Dict[str, dict]


class ComponentHealth(BaseModel):
    """组件健康状态"""
    status: str  # up, down, degraded
    message: Optional[str] = None
    response_time_ms: Optional[float] = None


@router.get("/", response_model=HealthStatus)
async def health_check(db: Session = Depends(get_db)):
    """
    综合健康检查
    
    检查所有关键组件的健康状态
    """
    checks = {}
    overall_status = "healthy"
    
    # 1. 检查数据库
    db_health = await check_database(db)
    checks["database"] = db_health.dict()
    if db_health.status != "up":
        overall_status = "degraded" if overall_status == "healthy" else "unhealthy"
    
    # 2. 检查 Redis
    redis_health = await check_redis()
    checks["redis"] = redis_health.dict()
    if redis_health.status != "up":
        overall_status = "degraded" if overall_status == "healthy" else "unhealthy"
    
    # 3. 检查 Meilisearch
    meili_health = await check_meilisearch()
    checks["meilisearch"] = meili_health.dict()
    if meili_health.status != "up":
        overall_status = "degraded"  # Meilisearch 不是关键组件
    
    return HealthStatus(
        status=overall_status,
        timestamp=datetime.utcnow(),
        version="1.0.0",
        checks=checks
    )


@router.get("/liveness")
async def liveness():
    """
    存活检查
    
    用于 Kubernetes liveness probe
    简单检查应用是否还在运行
    """
    return {"status": "alive"}


@router.get("/readiness")
async def readiness(db: Session = Depends(get_db)):
    """
    就绪检查
    
    用于 Kubernetes readiness probe
    检查应用是否准备好接收流量
    """
    # 检查数据库连接
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as e:
        return {"status": "not_ready", "reason": str(e)}


async def check_database(db: Session) -> ComponentHealth:
    """检查数据库健康状态"""
    import time
    
    try:
        start_time = time.time()
        db.execute(text("SELECT 1"))
        response_time = (time.time() - start_time) * 1000
        
        return ComponentHealth(
            status="up",
            message="Database is healthy",
            response_time_ms=round(response_time, 2)
        )
    except Exception as e:
        return ComponentHealth(
            status="down",
            message=f"Database error: {str(e)}"
        )


async def check_redis() -> ComponentHealth:
    """检查 Redis 健康状态"""
    import time
    
    try:
        start_time = time.time()
        r = redis.from_url(settings.REDIS_URL)
        r.ping()
        response_time = (time.time() - start_time) * 1000
        
        return ComponentHealth(
            status="up",
            message="Redis is healthy",
            response_time_ms=round(response_time, 2)
        )
    except Exception as e:
        return ComponentHealth(
            status="down",
            message=f"Redis error: {str(e)}"
        )


async def check_meilisearch() -> ComponentHealth:
    """检查 Meilisearch 健康状态"""
    import time
    
    try:
        start_time = time.time()
        client = meilisearch.Client(
            settings.MEILI_HOST,
            settings.MEILI_MASTER_KEY
        )
        client.health()
        response_time = (time.time() - start_time) * 1000
        
        return ComponentHealth(
            status="up",
            message="Meilisearch is healthy",
            response_time_ms=round(response_time, 2)
        )
    except Exception as e:
        return ComponentHealth(
            status="down",
            message=f"Meilisearch error: {str(e)}"
        )

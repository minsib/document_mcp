"""
监控中间件
"""
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import time
import logging

from app.monitoring.metrics import request_duration, errors_total

logger = logging.getLogger(__name__)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Prometheus 指标收集中间件"""
    
    async def dispatch(self, request: Request, call_next):
        # 记录请求开始时间
        start_time = time.time()
        
        # 处理请求
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as e:
            # 记录错误
            errors_total.labels(
                error_type=type(e).__name__,
                endpoint=request.url.path
            ).inc()
            
            logger.error(
                f"Request failed: {request.method} {request.url.path}",
                exc_info=True
            )
            
            # 重新抛出异常
            raise
        finally:
            # 记录请求时长
            duration = time.time() - start_time
            request_duration.labels(
                method=request.method,
                endpoint=request.url.path,
                status_code=status_code if 'status_code' in locals() else 500
            ).observe(duration)
        
        return response


class LoggingMiddleware(BaseHTTPMiddleware):
    """请求日志中间件"""
    
    async def dispatch(self, request: Request, call_next):
        # 记录请求
        logger.info(
            f"Request: {request.method} {request.url.path}",
            extra={
                "method": request.method,
                "path": request.url.path,
                "client": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent")
            }
        )
        
        start_time = time.time()
        
        try:
            response = await call_next(request)
            
            # 记录响应
            duration = time.time() - start_time
            logger.info(
                f"Response: {request.method} {request.url.path} - {response.status_code} ({duration:.3f}s)",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration": duration
                }
            )
            
            return response
            
        except Exception as e:
            # 记录错误
            duration = time.time() - start_time
            logger.error(
                f"Error: {request.method} {request.url.path} - {type(e).__name__} ({duration:.3f}s)",
                exc_info=True,
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "error_type": type(e).__name__,
                    "duration": duration
                }
            )
            
            raise

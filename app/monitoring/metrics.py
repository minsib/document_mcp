"""
Prometheus 指标收集
"""
from prometheus_client import Counter, Histogram, Gauge, Info
import time
from functools import wraps
from typing import Callable

# ============ 业务指标 ============

# 文档操作
documents_uploaded = Counter(
    'documents_uploaded_total',
    'Total number of documents uploaded',
    ['user_id']
)

documents_exported = Counter(
    'documents_exported_total',
    'Total number of documents exported',
    ['user_id']
)

# 编辑操作
edits_requested = Counter(
    'edits_requested_total',
    'Total number of edit requests',
    ['operation_type']
)

edits_applied = Counter(
    'edits_applied_total',
    'Total number of edits applied successfully',
    ['operation_type']
)

edits_failed = Counter(
    'edits_failed_total',
    'Total number of failed edits',
    ['operation_type', 'error_type']
)

# 批量修改
bulk_edits_requested = Counter(
    'bulk_edits_requested_total',
    'Total number of bulk edit requests'
)

bulk_edits_applied = Counter(
    'bulk_edits_applied_total',
    'Total number of bulk edits applied'
)

bulk_changes_count = Histogram(
    'bulk_changes_count',
    'Number of changes in bulk edits',
    buckets=[1, 5, 10, 20, 50, 100]
)

# 检索操作
searches_performed = Counter(
    'searches_performed_total',
    'Total number of searches performed',
    ['search_type']  # bm25, vector, hybrid
)

search_results_count = Histogram(
    'search_results_count',
    'Number of search results returned',
    buckets=[0, 1, 5, 10, 20, 50]
)

# 认证操作
auth_login_attempts = Counter(
    'auth_login_attempts_total',
    'Total number of login attempts',
    ['status']  # success, failed
)

auth_api_key_usage = Counter(
    'auth_api_key_usage_total',
    'Total number of API key authentications',
    ['status']  # success, failed, expired
)

# ============ 性能指标 ============

# 请求延迟
request_duration = Histogram(
    'request_duration_seconds',
    'Request duration in seconds',
    ['method', 'endpoint', 'status_code'],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0]
)

# LLM 调用
llm_call_duration = Histogram(
    'llm_call_duration_seconds',
    'LLM API call duration in seconds',
    ['model', 'operation'],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0]
)

llm_calls_total = Counter(
    'llm_calls_total',
    'Total number of LLM API calls',
    ['model', 'operation', 'status']
)

llm_tokens_used = Counter(
    'llm_tokens_used_total',
    'Total number of tokens used',
    ['model', 'token_type']  # prompt, completion
)

# 数据库操作
db_query_duration = Histogram(
    'db_query_duration_seconds',
    'Database query duration in seconds',
    ['operation'],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0]
)

db_connections_active = Gauge(
    'db_connections_active',
    'Number of active database connections'
)

# 缓存操作
cache_hits = Counter(
    'cache_hits_total',
    'Total number of cache hits',
    ['cache_type']  # redis, local
)

cache_misses = Counter(
    'cache_misses_total',
    'Total number of cache misses',
    ['cache_type']
)

# 搜索引擎
meilisearch_query_duration = Histogram(
    'meilisearch_query_duration_seconds',
    'Meilisearch query duration in seconds',
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0]
)

vector_search_duration = Histogram(
    'vector_search_duration_seconds',
    'Vector search duration in seconds',
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0]
)

# ============ 系统指标 ============

# 应用信息
app_info = Info('app', 'Application information')

# 活跃用户
active_users = Gauge(
    'active_users',
    'Number of active users'
)

# 文档统计
total_documents = Gauge(
    'total_documents',
    'Total number of documents'
)

total_blocks = Gauge(
    'total_blocks',
    'Total number of blocks'
)

# ============ 错误指标 ============

errors_total = Counter(
    'errors_total',
    'Total number of errors',
    ['error_type', 'endpoint']
)

# ============ 装饰器 ============

def track_time(metric: Histogram, labels: dict = None):
    """跟踪函数执行时间的装饰器"""
    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start_time
                if labels:
                    metric.labels(**labels).observe(duration)
                else:
                    metric.observe(duration)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start_time
                if labels:
                    metric.labels(**labels).observe(duration)
                else:
                    metric.observe(duration)
        
        # 判断是否为异步函数
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def track_llm_call(model: str, operation: str):
    """跟踪 LLM 调用的装饰器"""
    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                llm_calls_total.labels(model=model, operation=operation, status='success').inc()
                return result
            except Exception as e:
                llm_calls_total.labels(model=model, operation=operation, status='error').inc()
                raise
            finally:
                duration = time.time() - start_time
                llm_call_duration.labels(model=model, operation=operation).observe(duration)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                llm_calls_total.labels(model=model, operation=operation, status='success').inc()
                return result
            except Exception as e:
                llm_calls_total.labels(model=model, operation=operation, status='error').inc()
                raise
            finally:
                duration = time.time() - start_time
                llm_call_duration.labels(model=model, operation=operation).observe(duration)
        
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator

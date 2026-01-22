"""
多级缓存管理
"""
from typing import Optional, Any
import redis
import json
from functools import lru_cache
from app.config import get_settings
from app.models import database as db_models

settings = get_settings()


class CacheManager:
    """缓存管理器（Redis + 本地 LRU）"""
    
    def __init__(self, redis_url: str = None, local_cache_size: int = 1000):
        self.redis_url = redis_url or settings.REDIS_URL
        try:
            self.redis_client = redis.from_url(self.redis_url, decode_responses=True)
            self.redis_available = True
            # 测试连接
            self.redis_client.ping()
        except Exception as e:
            print(f"Redis 连接失败，仅使用本地缓存: {e}")
            self.redis_client = None
            self.redis_available = False
        
        self.local_cache_size = local_cache_size
        self._local_cache = {}
    
    def get_block_version(self, block_id: str, rev_id: str) -> Optional[dict]:
        """获取块版本（带缓存）"""
        cache_key = f"block:{block_id}:{rev_id}"
        
        # L1: 本地缓存
        if cache_key in self._local_cache:
            return self._local_cache[cache_key]
        
        # L2: Redis 缓存
        if self.redis_available:
            try:
                cached = self.redis_client.get(cache_key)
                if cached:
                    data = json.loads(cached)
                    self._local_cache[cache_key] = data
                    self._trim_local_cache()
                    return data
            except Exception as e:
                print(f"Redis 读取失败: {e}")
        
        return None
    
    def set_block_version(self, block_id: str, rev_id: str, data: dict, ttl: int = 3600):
        """设置块版本缓存"""
        cache_key = f"block:{block_id}:{rev_id}"
        
        # 写入本地缓存
        self._local_cache[cache_key] = data
        self._trim_local_cache()
        
        # 写入 Redis
        if self.redis_available:
            try:
                self.redis_client.setex(
                    cache_key,
                    ttl,
                    json.dumps(data)
                )
            except Exception as e:
                print(f"Redis 写入失败: {e}")
    
    def get_active_revision(self, doc_id: str) -> Optional[dict]:
        """获取当前活跃版本"""
        cache_key = f"active_rev:{doc_id}"
        
        # L1: 本地缓存（短 TTL）
        if cache_key in self._local_cache:
            return self._local_cache[cache_key]
        
        # L2: Redis 缓存
        if self.redis_available:
            try:
                cached = self.redis_client.get(cache_key)
                if cached:
                    data = json.loads(cached)
                    self._local_cache[cache_key] = data
                    return data
            except Exception as e:
                print(f"Redis 读取失败: {e}")
        
        return None
    
    def set_active_revision(self, doc_id: str, data: dict, ttl: int = 300):
        """设置当前活跃版本缓存（5分钟 TTL）"""
        cache_key = f"active_rev:{doc_id}"
        
        # 写入本地缓存
        self._local_cache[cache_key] = data
        self._trim_local_cache()
        
        # 写入 Redis
        if self.redis_available:
            try:
                self.redis_client.setex(
                    cache_key,
                    ttl,
                    json.dumps(data)
                )
            except Exception as e:
                print(f"Redis 写入失败: {e}")
    
    def invalidate_revision(self, rev_id: str):
        """失效某个版本的所有缓存"""
        # 清空本地缓存（简化处理）
        self._local_cache.clear()
        
        # 删除 Redis 中该 revision 的所有 blocks
        if self.redis_available:
            try:
                pattern = f"block:*:{rev_id}"
                keys = []
                for key in self.redis_client.scan_iter(match=pattern):
                    keys.append(key)
                
                if keys:
                    self.redis_client.delete(*keys)
            except Exception as e:
                print(f"Redis 删除失败: {e}")
    
    def invalidate_document(self, doc_id: str):
        """失效某个文档的所有缓存"""
        # 清空本地缓存
        self._local_cache.clear()
        
        # 删除 Redis 中该文档的缓存
        if self.redis_available:
            try:
                # 删除 active_revision
                self.redis_client.delete(f"active_rev:{doc_id}")
                
                # 删除搜索结果缓存
                pattern = f"search:{doc_id}:*"
                keys = []
                for key in self.redis_client.scan_iter(match=pattern):
                    keys.append(key)
                
                if keys:
                    self.redis_client.delete(*keys)
            except Exception as e:
                print(f"Redis 删除失败: {e}")
    
    def get_search_results(self, doc_id: str, query: str, rev_id: str) -> Optional[list]:
        """获取搜索结果缓存"""
        cache_key = f"search:{doc_id}:{rev_id}:{hash(query)}"
        
        if self.redis_available:
            try:
                cached = self.redis_client.get(cache_key)
                if cached:
                    return json.loads(cached)
            except Exception as e:
                print(f"Redis 读取失败: {e}")
        
        return None
    
    def set_search_results(self, doc_id: str, query: str, rev_id: str, results: list, ttl: int = 600):
        """设置搜索结果缓存（10分钟 TTL）"""
        cache_key = f"search:{doc_id}:{rev_id}:{hash(query)}"
        
        if self.redis_available:
            try:
                self.redis_client.setex(
                    cache_key,
                    ttl,
                    json.dumps(results)
                )
            except Exception as e:
                print(f"Redis 写入失败: {e}")
    
    def store_confirm_token(self, session_id: str, token_id: str, payload: dict, ttl: int = 900):
        """存储确认 token（15分钟 TTL）"""
        cache_key = f"confirm_token:{session_id}:{token_id}"
        
        if self.redis_available:
            try:
                self.redis_client.setex(
                    cache_key,
                    ttl,
                    json.dumps(payload)
                )
                return True
            except Exception as e:
                print(f"Redis 写入失败: {e}")
                return False
        
        return False
    
    def get_confirm_token(self, session_id: str, token_id: str) -> Optional[dict]:
        """获取确认 token"""
        cache_key = f"confirm_token:{session_id}:{token_id}"
        
        if self.redis_available:
            try:
                cached = self.redis_client.get(cache_key)
                if cached:
                    return json.loads(cached)
            except Exception as e:
                print(f"Redis 读取失败: {e}")
        
        return None
    
    def delete_confirm_token(self, session_id: str, token_id: str):
        """删除确认 token（一次性使用）"""
        cache_key = f"confirm_token:{session_id}:{token_id}"
        
        if self.redis_available:
            try:
                self.redis_client.delete(cache_key)
            except Exception as e:
                print(f"Redis 删除失败: {e}")
    
    def _trim_local_cache(self):
        """修剪本地缓存"""
        if len(self._local_cache) > self.local_cache_size:
            # 简单的 FIFO 策略
            keys_to_remove = list(self._local_cache.keys())[:len(self._local_cache) - self.local_cache_size]
            for key in keys_to_remove:
                del self._local_cache[key]


# 全局实例
_cache_manager = None


def get_cache_manager() -> CacheManager:
    """获取缓存管理器单例"""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager()
    return _cache_manager

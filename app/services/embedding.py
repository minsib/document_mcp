"""
Embedding 生成服务
"""
from typing import List
from openai import OpenAI
from app.config import get_settings

settings = get_settings()


class EmbeddingService:
    """Embedding 生成服务"""
    
    def __init__(self):
        self.client = OpenAI(
            api_key=settings.QWEN_API_KEY,
            base_url=settings.QWEN_API_BASE
        )
        # 使用 text-embedding-v3 或兼容模型
        self.model = "text-embedding-v3"
    
    def generate_embedding(self, text: str) -> List[float]:
        """生成单个文本的 embedding"""
        # 截断到合理长度
        text = self._truncate_text(text, max_length=8000)
        
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=text
            )
            return response.data[0].embedding
        except Exception as e:
            print(f"Embedding 生成失败: {e}")
            # 返回零向量作为降级
            return [0.0] * 1536
    
    def generate_embeddings_batch(self, texts: List[str], batch_size: int = 10) -> List[List[float]]:
        """批量生成 embeddings（Qwen API 限制每批最多 10 个）"""
        # 确保 batch_size 不超过 10
        batch_size = min(batch_size, 10)
        
        embeddings = []
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            # 截断每个文本
            batch = [self._truncate_text(t, max_length=8000) for t in batch]
            
            try:
                response = self.client.embeddings.create(
                    model=self.model,
                    input=batch
                )
                batch_embeddings = [data.embedding for data in response.data]
                embeddings.extend(batch_embeddings)
            except Exception as e:
                print(f"批量 embedding 生成失败: {e}")
                # 返回零向量
                embeddings.extend([[0.0] * 1536 for _ in batch])
        
        return embeddings
    
    def _truncate_text(self, text: str, max_length: int = 8000) -> str:
        """截断文本到指定长度"""
        if len(text) <= max_length:
            return text
        return text[:max_length]


# 全局实例
_embedding_service = None


def get_embedding_service() -> EmbeddingService:
    """获取 embedding 服务单例"""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service

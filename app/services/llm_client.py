from openai import OpenAI
from typing import Optional, Dict, Any
from app.config import get_settings

settings = get_settings()


class QwenClient:
    """Qwen3 API 客户端"""
    
    def __init__(self):
        self.client = OpenAI(
            api_key=settings.QWEN_API_KEY,
            base_url=settings.QWEN_API_BASE
        )
        self.model = settings.QWEN_MODEL
    
    def chat_completion(
        self,
        messages: list,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None
    ) -> str:
        """调用 Qwen API 进行对话"""
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        
        if response_format:
            kwargs["response_format"] = response_format
        
        response = self.client.chat.completions.create(**kwargs)
        return response.choices[0].message.content
    
    def chat_completion_json(
        self,
        messages: list,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> str:
        """调用 Qwen API 并返回 JSON 格式"""
        return self.chat_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"}
        )


# 全局客户端实例
_qwen_client: Optional[QwenClient] = None


def get_qwen_client() -> QwenClient:
    """获取 Qwen 客户端单例"""
    global _qwen_client
    if _qwen_client is None:
        _qwen_client = QwenClient()
    return _qwen_client

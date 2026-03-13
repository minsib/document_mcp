from openai import OpenAI
from typing import Optional, Dict, Any
from app.config import get_settings
from app.monitoring.metrics import llm_call_duration, llm_calls_total, llm_tokens_used
import time
import logging

settings = get_settings()
logger = logging.getLogger(__name__)


class QwenClient:
    """Qwen3 API 客户端（集成 Langfuse 追踪）"""
    
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
        response_format: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
        span_name: Optional[str] = None
    ) -> str:
        """调用 Qwen API 进行对话（支持 Langfuse 追踪）"""
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        
        if response_format:
            kwargs["response_format"] = response_format
        
        operation = span_name or ("chat_completion_json" if response_format else "chat_completion")
        start_time = time.time()
        status = "success"
        
        try:
            response = self.client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            
            # 计算耗时
            duration = time.time() - start_time

            # 记录 token 使用
            if response.usage:
                llm_tokens_used.labels(model=self.model, token_type="prompt").inc(
                    response.usage.prompt_tokens or 0
                )
                llm_tokens_used.labels(model=self.model, token_type="completion").inc(
                    response.usage.completion_tokens or 0
                )
            
            # 记录到 Langfuse
            if trace_id and settings.ENABLE_LANGFUSE:
                try:
                    from app.services.langfuse_client import log_generation
                    
                    usage = {
                        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                        "total_tokens": response.usage.total_tokens if response.usage else 0
                    }
                    
                    log_generation(
                        trace_id=trace_id,
                        name=span_name or "llm_call",
                        model=self.model,
                        input=messages,
                        output=content,
                        metadata={
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                            "duration_seconds": duration
                        },
                        usage=usage
                    )
                except Exception as e:
                    logger.warning(f"Langfuse 记录失败: {e}")
            
            return content
            
        except Exception as e:
            status = "error"
            logger.error(f"LLM API 调用失败: {e}")
            raise
        finally:
            duration = time.time() - start_time
            llm_call_duration.labels(model=self.model, operation=operation).observe(duration)
            llm_calls_total.labels(model=self.model, operation=operation, status=status).inc()
    
    def chat_completion_json(
        self,
        messages: list,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        trace_id: Optional[str] = None,
        span_name: Optional[str] = None
    ) -> str:
        """调用 Qwen API 并返回 JSON 格式"""
        return self.chat_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            trace_id=trace_id,
            span_name=span_name
        )


# 全局客户端实例
_qwen_client: Optional[QwenClient] = None


def get_qwen_client() -> QwenClient:
    """获取 Qwen 客户端单例"""
    global _qwen_client
    if _qwen_client is None:
        _qwen_client = QwenClient()
    return _qwen_client

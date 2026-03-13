"""
智能体基类
"""
from typing import List, Dict, Any
from langchain.tools import BaseTool
from langchain_openai import ChatOpenAI
from app.config import get_settings

settings = get_settings()


def create_llm():
    """创建 LLM 实例"""
    return ChatOpenAI(
        base_url=settings.QWEN_API_BASE,
        api_key=settings.QWEN_API_KEY,
        model=settings.QWEN_MODEL,
        temperature=0.7
    )


class BaseAgent:
    """智能体基类"""
    
    def __init__(self, tools: List[BaseTool]):
        self.tools = tools
        self.llm = create_llm()
    
    def get_system_prompt(self) -> str:
        """获取系统提示 - 子类必须实现"""
        raise NotImplementedError
    
    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """执行智能体 - 子类必须实现"""
        raise NotImplementedError

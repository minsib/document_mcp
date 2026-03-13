"""
工具基类 - 所有工具的基础类
"""
from typing import Any, Optional, Type
from pydantic import BaseModel, Field
from langchain.tools import BaseTool as LangChainBaseTool
from sqlalchemy.orm import Session


class ToolInput(BaseModel):
    """工具输入的基类"""
    pass


class BaseTool(LangChainBaseTool):
    """自定义工具基类"""
    
    db: Optional[Session] = Field(default=None, exclude=True)
    
    class Config:
        arbitrary_types_allowed = True
    
    def __init__(self, db: Optional[Session] = None, **kwargs):
        super().__init__(**kwargs)
        self.db = db
    
    def _run(self, *args: Any, **kwargs: Any) -> Any:
        """同步执行 - 子类必须实现"""
        raise NotImplementedError("Tool must implement _run method")
    
    async def _arun(self, *args: Any, **kwargs: Any) -> Any:
        """异步执行 - 默认调用同步方法"""
        return self._run(*args, **kwargs)

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # 应用配置
    APP_NAME: str = "DocumentEditSystem"
    APP_ENV: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    
    # 数据库配置
    DATABASE_URL: str
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    
    # Redis 配置
    REDIS_URL: str
    REDIS_MAX_CONNECTIONS: int = 50
    
    # Meilisearch 配置
    MEILI_HOST: str
    MEILI_MASTER_KEY: str
    
    # Qwen API 配置
    QWEN_API_KEY: str
    QWEN_API_BASE: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    QWEN_MODEL: str = "qwen-max-latest"
    
    # Langfuse 配置（可选）
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"
    ENABLE_LANGFUSE: bool = False
    
    # 功能开关
    ENABLE_VECTOR_SEARCH: bool = False
    ENABLE_METRICS: bool = True
    
    # 安全配置
    SECRET_KEY: str = "change-this-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    
    # 性能配置
    MAX_WORKERS: int = 4
    MAX_BLOCK_SIZE: int = 1000
    TARGET_BLOCK_SIZE: int = 300
    MIN_BLOCK_SIZE: int = 50
    
    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()

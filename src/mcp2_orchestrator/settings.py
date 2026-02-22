from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_api_version: str = "2025-01-01-preview"
    azure_chat_deployment: str = "gpt-4.1"

    # URL of the MCP 1 HTTP/SSE server
    mcp1_url: str = "http://localhost:8001"
    mcp2_port: int = 8002


settings = Settings()  # type: ignore[call-arg]

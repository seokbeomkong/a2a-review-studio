import secrets

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    studio_port: int = Field(default=8765, ge=1024, le=65535)
    anthropic_api_key: SecretStr = SecretStr('')
    claude_model: str = ''
    internal_token: str = Field(default_factory=lambda: secrets.token_urlsafe(32), repr=False)
    run_timeout: float = 180
    rpc_timeout: float = 110
    max_concurrent: int = 4
    max_retained: int = 50
    retention_seconds: float = 3600

    @property
    def base_url(self) -> str:
        return f'http://127.0.0.1:{self.studio_port}'

    @property
    def claude_available(self) -> bool:
        return bool(self.anthropic_api_key.get_secret_value() and self.claude_model.strip())


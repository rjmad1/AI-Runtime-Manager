# core/schemas.py
# Pydantic schemas for validating user configuration files.

from typing import Dict, List

from pydantic import BaseModel, ConfigDict, Field, RootModel


class LiteLLMSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 4000
    api_key: str = ""
    set_verbose: bool = False
    drop_params: bool = True
    routing_strategy: str = "latency-based-routing"
    num_retries: int = 3
    request_timeout: int = 30

    model_config = ConfigDict(extra='ignore')

class OpenClawSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 18789
    config_dir: str = ""

    model_config = ConfigDict(extra='ignore')

class OllamaSettings(BaseModel):
    enabled: bool = True
    api_base: str = "http://127.0.0.1:11434"
    autostart: bool = True

    model_config = ConfigDict(extra='ignore')

class LifecycleSettings(BaseModel):
    log_level: str = "INFO"
    backup_dir: str = "backups"
    auto_cleanup_ports: bool = True

    model_config = ConfigDict(extra='ignore')

class SecretsSettings(BaseModel):
    cloud_provider: str = "none"
    vault_mount: str = "secret"
    azure_vault_name: str = ""
    aws_region: str = ""

    model_config = ConfigDict(extra='ignore')

class SettingsConfig(BaseModel):
    litellm: LiteLLMSettings = Field(default_factory=LiteLLMSettings)
    openclaw: OpenClawSettings = Field(default_factory=OpenClawSettings)
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    lifecycle: LifecycleSettings = Field(default_factory=LifecycleSettings)
    secrets: SecretsSettings = Field(default_factory=SecretsSettings)

    model_config = ConfigDict(extra='ignore')


class ModelEntry(BaseModel):
    id: str
    name: str
    provider: str
    litellm_model: str
    context_window: int = 4096
    max_tokens: int = 4096
    fallbacks: List[str] = Field(default_factory=list)

    model_config = ConfigDict(extra='ignore')

class ModelsConfig(BaseModel):
    models: List[ModelEntry] = Field(default_factory=list)

    model_config = ConfigDict(extra='ignore')


class ProviderEntry(BaseModel):
    enabled: bool = False
    env_var: str
    info: str = ""

    model_config = ConfigDict(extra='ignore')

class ProvidersConfig(RootModel[Dict[str, ProviderEntry]]):
    pass

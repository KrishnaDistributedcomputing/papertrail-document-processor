"""Application configuration loaded from environment variables."""

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

OLLAMA_MODEL_CATALOG = {
    "qwen2.5:1.5b": {
        "name": "Qwen 2.5 1.5B",
        "description": "Balanced detail and structured extraction",
        "size": "986 MB",
    },
    "qwen2.5:0.5b": {
        "name": "Qwen 2.5 0.5B",
        "description": "Faster comparison model with a smaller memory footprint",
        "size": "397 MB",
    },
}


class Settings(BaseSettings):
    """Runtime settings shared by the API and processing worker."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    redis_url: str = "redis://redis:6379/0"
    data_dir: Path = Path("/data")
    max_file_size_mb: int = 50
    max_pdf_pages: int = 500
    native_text_min_chars: int = 30
    ocr_languages: str = "eng"
    ocr_dpi: int = 300
    job_timeout_seconds: int = 600
    max_batch_documents: int = 10
    ai_enabled: bool = True
    ollama_url: str = "http://ollama:11434"
    ollama_model: str = "qwen2.5:1.5b"
    ollama_available_models: str = "qwen2.5:1.5b,qwen2.5:0.5b"
    max_analysis_models: int = 2
    ai_timeout_seconds: int = 180
    ai_max_characters: int = 12000
    azure_storage_connection_string: SecretStr | None = None
    azure_storage_account_name: str = ""
    azure_subscription_id: str = ""
    azure_resource_group: str = ""
    azure_management_identity_enabled: bool = False
    azure_storage_region: str = "eastus"
    azure_storage_sku: str = "Standard_LRS"
    azure_storage_gb_month_usd: float = 0.0208
    azure_write_10k_usd: float = 0.065
    azure_read_10k_usd: float = 0.005
    azure_other_10k_usd: float = 0.004
    processing_vcpu_hour_usd: float = 0.096
    processing_memory_gb_hour_usd: float = 0.012
    processing_memory_gb: float = 2.0
    azure_ai_sample_input_1m_tokens_usd: float = 0.15
    azure_ai_sample_output_1m_tokens_usd: float = 0.60

    @property
    def uploads_dir(self) -> Path:
        """Return the source PDF directory."""
        return self.data_dir / "uploads"

    @property
    def results_dir(self) -> Path:
        """Return the JSON result directory."""
        return self.data_dir / "results"

    @property
    def database_path(self) -> Path:
        """Return the persistent SQLite database path."""
        return self.data_dir / "papertrail.db"

    @property
    def available_ollama_models(self) -> list[str]:
        """Return configured model identifiers with the default model first."""
        configured = [
            model.strip()
            for model in self.ollama_available_models.split(",")
            if model.strip()
        ]
        return list(dict.fromkeys([self.ollama_model, *configured]))

    @property
    def azure_storage_enabled(self) -> bool:
        """Return whether Azure Blob persistence is configured."""
        return bool(
            self.azure_storage_connection_string
            and self.azure_storage_connection_string.get_secret_value()
        )

    @property
    def azure_management_enabled(self) -> bool:
        """Return whether Azure lifecycle policy management is configured."""
        return bool(
            self.azure_management_identity_enabled
            and self.azure_subscription_id
            and self.azure_resource_group
            and self.azure_storage_account_name
        )


settings = Settings()
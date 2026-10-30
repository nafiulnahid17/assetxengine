"""Runtime configuration; secrets are strictly environment-sourced."""
from dataclasses import dataclass
from pathlib import Path
import os


def models(name: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in os.getenv(name, "").split(",") if x.strip())


@dataclass(frozen=True)
class Settings:
    root: Path = Path(os.getenv("ASSETSX_ROOT", ".work/assetsx"))
    inbound_token: str = os.getenv("ASSETSX_INBOUND_TOKEN", "")
    max_upload_mb: int = int(os.getenv("ASSETSX_MAX_UPLOAD_MB", "20"))
    max_pixels: int = int(os.getenv("ASSETSX_MAX_PIXELS", "16000000"))
    workers: int = int(os.getenv("ASSETSX_WORKERS", "2"))
    enable_ai: bool = os.getenv("ASSETSX_ENABLE_AI", "false").lower() == "true"
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_base_url: str = os.getenv("ASSETSX_OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    quality_vision_models: tuple[str, ...] = ()
    cost_vision_models: tuple[str, ...] = ()
    quality_edit_models: tuple[str, ...] = ()
    cost_edit_models: tuple[str, ...] = ()
    ai_timeout: float = float(os.getenv("ASSETSX_AI_EDIT_TIMEOUT_SEC", "120"))
    allow_font_derivatives: bool = os.getenv("ASSETSX_ALLOW_FONT_DERIVATIVES", "false").lower() == "true"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(quality_vision_models=models("ASSETSX_QUALITY_VISION_MODELS"),
                   cost_vision_models=models("ASSETSX_COST_VISION_MODELS"),
                   quality_edit_models=models("ASSETSX_QUALITY_EDIT_MODELS"),
                   cost_edit_models=models("ASSETSX_COST_EDIT_MODELS"))

    def validate(self) -> None:
        if self.max_upload_mb < 1 or self.max_pixels < 10_000 or not (1 <= self.workers <= 16):
            raise ValueError("Invalid resource limits")
        if self.enable_ai and not self.openrouter_api_key:
            raise ValueError("ASSETSX_ENABLE_AI requires OPENROUTER_API_KEY")

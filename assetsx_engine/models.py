"""Public request models. Files are server-side and referenced by opaque UUIDs."""
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field, ConfigDict

class Mode(str, Enum):
    quality = "quality"
    cost_effective = "cost_effective"

class Strategy(str, Enum):
    auto = "auto"
    shapes = "shapes"
    monochrome = "monochrome"
    multicolor = "multicolor"
    color_regions = "color_regions"
    existing_vector = "existing_vector"

class Edit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str
    element_ids: list[str] = Field(default_factory=list, max_length=100)
    params: dict[str, Any] = Field(default_factory=dict)

class ProcessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str
    mode: Mode = Mode.cost_effective
    strategy: Strategy = Strategy.auto
    selected_element_ids: list[str] = Field(default_factory=list, max_length=500)
    edits: list[Edit] = Field(default_factory=list, max_length=100)
    ai_analyze: bool = False
    ai_edit_prompt: str | None = Field(default=None, max_length=2000)
    formats: list[str] = Field(default_factory=lambda: ["png", "transparent_png", "svg", "eps", "pdf", "zip"])
    max_colors: int = Field(default=12, ge=2, le=32)
    min_area: int = Field(default=24, ge=1, le=3000)
    strict_true_vector: bool = True

class AssetInfo(BaseModel):
    id: str
    filename: str
    format: str
    input_mode: str
    width: int
    height: int
    asset_type: str
    elements: list[dict[str, Any]]
    palette: list[str]
    import_warnings: list[str]

class JobInfo(BaseModel):
    id: str
    asset_id: str
    state: str
    stage: str
    progress: int
    mode: str
    strategy: str
    created_at: str
    updated_at: str
    error: str | None = None
    outputs: list[str] = Field(default_factory=list)
    report: dict[str, Any] | None = None

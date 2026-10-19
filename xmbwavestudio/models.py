"""Validated settings shared by the HTTP API and bundled editor."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Style = Literal["psp-classic", "psp-original", "ps3"]
HexColor = str


class SceneConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    style: Style = "ps3"
    color: HexColor = Field(default="#3264c5", pattern=r"^#[0-9a-fA-F]{6}$")
    background_color: HexColor | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    wave_color: HexColor | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    speed: float = Field(default=0.5, ge=0, le=4)
    rotation: float = Field(default=0, ge=0, le=360)
    height: float = Field(default=0.55, ge=0, le=2)
    width: float = Field(default=1.15, ge=0.25, le=3)
    overlap: float = Field(default=0.82, ge=0, le=1)
    layer_motion: float = Field(default=1, ge=0, le=2)
    x: float = Field(default=0, ge=-1, le=1)
    y: float = Field(default=0, ge=-1, le=1)
    scale: float = Field(default=1, ge=0.25, le=3)
    glow: float = Field(default=0.9, ge=0, le=3)
    particle_count: int = Field(default=450, ge=0, le=2000, strict=True)
    particle_speed: float = Field(default=0.4, ge=0, le=4)
    particle_size: float = Field(default=1, ge=0.25, le=4)
    seed: int = Field(default=2026, ge=0, le=2**32 - 1, strict=True)


class OutputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    kind: Literal["jpeg", "video"] = "video"
    width: int = Field(default=1080, ge=1, strict=True)
    height: int = Field(default=1920, ge=1, strict=True)
    duration: int = Field(default=10, ge=1, strict=True)
    fps: Literal[30, 60] = 30
    encoder: Literal["auto", "software"] = "auto"

    @model_validator(mode="after")
    def safe_frame_count(self):
        # JavaScript must be able to address every frame exactly. Not a duration preset limit.
        if self.duration * self.fps > 2**53 - 1:
            raise ValueError("영상 프레임 수가 브라우저의 정확한 정수 계산 범위를 넘습니다.")
        return self

    @property
    def frame_count(self) -> int:
        return self.duration * self.fps

    @property
    def encoded_size(self) -> tuple[int, int]:
        return self.width + self.width % 2, self.height + self.height % 2


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene: SceneConfig
    output: OutputConfig


class ImageRequest(ExportRequest):
    time: float = Field(default=0, ge=0, le=2**53 - 1, allow_inf_nan=False)


class PreviewRequest(ImageRequest):
    width: int = Field(default=360, ge=1, le=2048, strict=True)
    height: int = Field(default=640, ge=1, le=2048, strict=True)
    format: Literal["jpeg", "png"] = "jpeg"


STYLE_PRESETS = [
    {
        "id": "psp-classic", "name": "PSP Classic", "era": "4.xx 이하",
        "description": "화면을 넓게 채우는 반투명 곡면과 부드러운 밝은 경계",
        "defaults": SceneConfig(
            style="psp-classic", speed=0.5, height=0.6, width=1.2,
            overlap=0.8, glow=0.7, particle_count=0,
        ).model_dump(),
    },
    {
        "id": "psp-original", "name": "PSP Original", "era": "5.00 이후",
        "description": "짙은 상단에서 밝은 하단으로 이어지는 넓은 물결",
        "defaults": SceneConfig(
            style="psp-original", speed=0.5, height=0.75, width=1.2,
            overlap=0.85, glow=1, particle_count=0,
        ).model_dump(),
    },
    {
        "id": "ps3", "name": "PS3 Wave", "era": "XMB · 파티클",
        "description": "깊이 있는 물결과 은은하게 반짝이는 입자",
        "defaults": SceneConfig().model_dump(),
    },
]

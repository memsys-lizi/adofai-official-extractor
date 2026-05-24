from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LevelProfile:
    level_id: str
    scene_rel: Path
    default_caption: str
    level_desc: str
    level_tags: str
    tile_shape: str = "Short"
    tile_size: float = 1.0


PROFILE_1X = LevelProfile(
    level_id="1-X",
    scene_rel=Path("Assets") / "scenes" / "Levels" / "1-X.unity",
    default_caption="1-X A Dance of Fire and Ice",
    level_desc="Extracted from the old Unity scene-based official 1-X level.",
    level_tags="official,extracted,experimental,1-X",
)

PROFILES = {
    PROFILE_1X.level_id: PROFILE_1X,
}

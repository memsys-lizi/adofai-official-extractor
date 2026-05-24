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

TUTORIAL_1_PROFILES = tuple(
    LevelProfile(
        level_id=f"1-{index}",
        scene_rel=Path("Assets") / "scenes" / "Levels" / f"1-{index}.unity",
        default_caption=f"1-{index}",
        level_desc=f"Extracted from the old Unity scene-based official 1-{index} tutorial level.",
        level_tags=f"official,extracted,experimental,1-X,tutorial,1-{index}",
    )
    for index in range(1, 7)
)

PROFILE_2X = LevelProfile(
    level_id="2-X",
    scene_rel=Path("Assets") / "scenes" / "Levels" / "2-X.unity",
    default_caption="2-X Offbeats",
    level_desc="Extracted from the old Unity scene-based official 2-X level.",
    level_tags="official,extracted,experimental,2-X",
)

PROFILES = {
    **{profile.level_id: profile for profile in TUTORIAL_1_PROFILES},
    PROFILE_1X.level_id: PROFILE_1X,
    PROFILE_2X.level_id: PROFILE_2X,
}

PROFILE_GROUPS = {
    "tutorials-1": tuple(profile.level_id for profile in TUTORIAL_1_PROFILES),
}

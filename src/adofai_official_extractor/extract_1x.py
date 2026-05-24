from __future__ import annotations

from pathlib import Path

from .converter import ExtractionResult, extract_with_profile, main_for_profile
from .profiles import PROFILE_1X


def extract(project_root: str | Path, scene_path: str | Path | None, output_dir: str | Path) -> ExtractionResult:
    return extract_with_profile(PROFILE_1X, project_root, scene_path, output_dir)


def main() -> None:
    main_for_profile(PROFILE_1X)


if __name__ == "__main__":
    main()

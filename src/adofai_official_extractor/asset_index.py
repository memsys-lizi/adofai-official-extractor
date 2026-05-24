from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import struct


GUID_RE = re.compile(r"^guid:\s*([0-9a-f]+)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class AssetRecord:
    guid: str
    path: Path
    project_relative_path: str
    script_name: str | None = None
    sprite_pixels_per_unit: float = 100.0
    sprite_pivot: tuple[float, float] = (0.5, 0.5)
    pixel_size: tuple[int, int] | None = None


class AssetIndex:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.assets_root = project_root / "Assets"
        self.by_guid: dict[str, AssetRecord] = {}
        self.script_name_by_guid: dict[str, str] = {}

    @classmethod
    def build(cls, project_root: str | Path) -> "AssetIndex":
        index = cls(Path(project_root))
        index.scan()
        return index

    def scan(self) -> None:
        if not self.assets_root.exists():
            raise FileNotFoundError(f"Assets folder not found: {self.assets_root}")

        for meta_path in self.assets_root.rglob("*.meta"):
            text = meta_path.read_text(encoding="utf-8", errors="ignore")
            match = GUID_RE.search(text)
            if not match:
                continue

            guid = match.group(1)
            asset_path = Path(str(meta_path)[:-5])
            try:
                rel_path = asset_path.relative_to(self.project_root).as_posix()
            except ValueError:
                rel_path = asset_path.as_posix()

            script_name = None
            if meta_path.name.endswith(".cs.meta"):
                script_name = meta_path.name[: -len(".cs.meta")]
                self.script_name_by_guid[guid] = script_name
            ppu_match = re.search(r"^\s*spritePixelsToUnits:\s*([0-9.]+)\s*$", text, re.MULTILINE)
            sprite_pixels_per_unit = float(ppu_match.group(1)) if ppu_match else 100.0
            pivot_match = re.search(
                r"^\s*spritePivot:\s*\{x:\s*([-0-9.]+),\s*y:\s*([-0-9.]+)\}\s*$",
                text,
                re.MULTILINE,
            )
            sprite_pivot = (
                (float(pivot_match.group(1)), float(pivot_match.group(2))) if pivot_match else (0.5, 0.5)
            )

            self.by_guid[guid] = AssetRecord(
                guid=guid,
                path=asset_path,
                project_relative_path=rel_path,
                script_name=script_name,
                sprite_pixels_per_unit=sprite_pixels_per_unit,
                sprite_pivot=sprite_pivot,
                pixel_size=png_size(asset_path),
            )

    def get(self, guid: str | None) -> AssetRecord | None:
        if not guid:
            return None
        return self.by_guid.get(guid)

    def script_name(self, guid: str | None) -> str | None:
        if not guid:
            return None
        return self.script_name_by_guid.get(guid)


def png_size(path: Path) -> tuple[int, int] | None:
    if path.suffix.lower() != ".png":
        return None
    try:
        with path.open("rb") as handle:
            header = handle.read(24)
    except OSError:
        return None
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", header[16:24])

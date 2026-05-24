from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


GUID_RE = re.compile(r"^guid:\s*([0-9a-f]+)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class AssetRecord:
    guid: str
    path: Path
    project_relative_path: str
    script_name: str | None = None


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

            self.by_guid[guid] = AssetRecord(
                guid=guid,
                path=asset_path,
                project_relative_path=rel_path,
                script_name=script_name,
            )

    def get(self, guid: str | None) -> AssetRecord | None:
        if not guid:
            return None
        return self.by_guid.get(guid)

    def script_name(self, guid: str | None) -> str | None:
        if not guid:
            return None
        return self.script_name_by_guid.get(guid)

from __future__ import annotations

from pathlib import Path
import json
import shutil

from .report import ConversionReport


def _compact(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))


def _object_line(value: dict, indent: str, trailing_comma: bool) -> str:
    body = ", ".join(f"{_compact(key)}: {_compact(item)}" for key, item in value.items())
    suffix = "," if trailing_comma else ""
    return f"{indent}{{ {body} }}{suffix}"


def write_adofai(path: Path, level: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = ["{"]
    lines.append(f'\t"pathData": {_compact(level["pathData"])}, ')
    lines.append('\t"settings":')
    lines.append("\t{")
    settings = level["settings"]
    setting_items = list(settings.items())
    for index, (key, value) in enumerate(setting_items):
        suffix = "," if index < len(setting_items) - 1 else ""
        lines.append(f"\t\t{_compact(key)}: {_compact(value)}{suffix}")
    lines.append("\t},")
    lines.append('\t"actions":')
    lines.append("\t[")
    actions = level.get("actions") or []
    for index, action in enumerate(actions):
        lines.append(_object_line(action, "\t\t", trailing_comma=index < len(actions) - 1))
    lines.append("\t],")
    lines.append('\t"decorations":')
    lines.append("\t[")
    decorations = level.get("decorations") or []
    for index, decoration in enumerate(decorations):
        lines.append(_object_line(decoration, "\t\t", trailing_comma=index < len(decorations) - 1))
    lines.append("\t]")
    lines.append("}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def copy_asset(src: Path, level_dir: Path, used_names: set[str], report: ConversionReport) -> str | None:
    if not src.exists():
        report.add("Missing assets", f"资源文件不存在：{src}")
        return None

    level_dir.mkdir(parents=True, exist_ok=True)
    stem = src.stem
    suffix = src.suffix or ".png"
    candidate = f"{stem}{suffix}"
    counter = 2
    while candidate.lower() in used_names:
        candidate = f"{stem}_{counter}{suffix}"
        counter += 1

    used_names.add(candidate.lower())
    dst = level_dir / candidate
    if not dst.exists():
        shutil.copy2(src, dst)
    return candidate

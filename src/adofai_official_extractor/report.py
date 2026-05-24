from __future__ import annotations

from collections import defaultdict
from pathlib import Path


SECTION_NAMES = {
    "Missing assets": "缺失资源",
    "Unsupported effects": "暂未支持的旧特效",
    "Unsupported post-processing": "暂未精确还原的后处理",
    "Approximate post-processing": "近似还原的后处理",
    "Post-processing": "后处理说明",
    "Camera mapping": "相机事件对照",
    "Decoration mapping": "装饰映射说明",
    "Music and background": "音乐和背景",
    "Speed mapping": "速度映射",
}

STAT_NAMES = {
    "actions": "动作事件数",
    "copied_assets": "复制资源数",
    "decorations": "装饰事件数",
    "old_path_chars": "旧谱面字符数",
    "pathData_chars": "导出 pathData 字符数",
    "scene_floor_components": "场景楼层组件数",
    "unsupported_effect_messages": "暂未支持旧特效条目数",
    "unsupported_post_processing_messages": "暂未精确还原后处理条目数",
    "nonzero_parallax_decorations": "非零视差装饰数",
    "set_speed_events": "设置速度事件数",
    "song_filename": "导出音乐文件",
    "background_image": "导出背景图",
}


class ConversionReport:
    def __init__(self) -> None:
        self.items: dict[str, list[str]] = defaultdict(list)
        self.stats: dict[str, int | float | str] = {}

    def add(self, section: str, message: str) -> None:
        self.items[section].append(message)

    def set_stat(self, key: str, value: int | float | str) -> None:
        self.stats[key] = value

    def write(self, path: Path) -> None:
        lines: list[str] = ["# 转换报告", ""]
        if self.stats:
            lines.append("## 统计")
            lines.append("")
            for key in sorted(self.stats):
                lines.append(f"- {STAT_NAMES.get(key, key)}: {self.stats[key]}")
            lines.append("")

        for section in sorted(self.items):
            lines.append(f"## {SECTION_NAMES.get(section, section)}")
            lines.append("")
            for item in self.items[section]:
                lines.append(f"- {item}")
            lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")

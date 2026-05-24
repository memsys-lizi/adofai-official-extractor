from __future__ import annotations

from pathlib import Path
from typing import Any

from .adofai_writer import copy_asset
from .converter import (
    DEFAULT_PROJECT,
    ExtractionResult,
    LevelConversionHooks,
    color_to_hex,
    effect_floor,
    extract_with_profile,
    main_for_profile,
    round_value,
    safe_float,
    visible_path_from_old_data,
)
from .profiles import PROFILE_3X
from .report import ConversionReport
from .unity_scene import UnityObject, UnityScene, color, ref_id


GROUP_TAGS = {
    "BG/BG NoCrystals": "world3_no_crystals",
    "BG/BG NoCrystalsPurple": "world3_purple",
    "BG/BG Crystals": "world3_crystals",
}

INITIAL_HIDDEN_GROUPS = {"BG/BG NoCrystalsPurple", "BG/BG Crystals"}


class ThreeXHooks(LevelConversionHooks):
    """3-X is hand-ruled: legacy H0/H9 markers and BG SetActive swaps need per-level logic."""

    def path_data(self, old_path_raw: str, scene: UnityScene, report: ConversionReport) -> str:
        cleaned = old_path_raw.replace("H0", "").replace("H9", "")
        path_data = visible_path_from_old_data(cleaned)
        report.add(
            "Path mapping",
            f"3-X 删除旧场景标记 H0/H9：raw {len(old_path_raw)} 字符 -> pathData {len(path_data)} 字符。",
        )
        return path_data

    def adjust_decoration(
        self,
        scene: UnityScene,
        go_id: int,
        decoration: dict[str, Any],
        report: ConversionReport,
    ) -> dict[str, Any] | None:
        path = scene.path_for_gameobject(go_id)
        group = group_for_path(path)
        if group:
            decoration["tag"] = f"{decoration['tag']} {GROUP_TAGS[group]}"
            if group in INITIAL_HIDDEN_GROUPS:
                decoration["opacity"] = 0

        if not any("3-X 背景分组" in item for item in report.items.get("Decoration mapping", [])):
            report.add(
                "Decoration mapping",
                "3-X 背景分组：NoCrystals 初始显示，NoCrystalsPurple/Crystals 初始隐藏；旧 ffxCallFunction(SetActive) 转为逐装饰透明度切换。",
            )
        return decoration

    def floor_effects(
        self,
        scene: UnityScene,
        floor_lookup: dict[int, int],
        tag_by_go: dict[int, str],
        bpm: float,
        floor_speeds: list[float],
        report: ConversionReport,
    ) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        for effect in sorted(scene.by_class("MonoBehaviour"), key=lambda obj: obj.file_id):
            floor = effect_floor(scene, effect, floor_lookup)
            if floor is None:
                continue
            name = effect.script_name or ""
            if name == "ffxBgColor":
                target_color = color_to_hex(effect.data.get("color"))
                fade_seconds = safe_float(effect.data.get("fadeTime"), 0.0)
                actions.append(
                    {
                        "floor": floor,
                        "eventType": "CustomBackground",
                        "color": target_color,
                        "bgImage": "",
                        "imageColor": "ffffff",
                        "parallax": [100, 100],
                        "bgDisplayMode": "FitToScreen",
                        "lockRot": "Disabled",
                        "loopBG": "Disabled",
                        "unscaledSize": 100,
                        "angleOffset": 0,
                        "eventTag": "3-X ffxBgColor",
                    }
                )
                report.add(
                    "Music and background",
                    f"floor {floor}: 3-X ffxBgColor -> CustomBackground color={target_color}（fadeTime={fade_seconds:g}s，现代事件按瞬时背景色近似）。",
                )
            elif name == "ffxCallFunction":
                actions.extend(call_function_bg_switches(scene, effect, floor, tag_by_go, report))
        return actions

    def scene_animations(
        self,
        scene: UnityScene,
        tag_by_go,
        deco_by_go,
        bpm: float,
        floor_speeds: list[float],
        report: ConversionReport,
    ) -> list[dict[str, Any]]:
        skipped = {
            "scrScroller": sum(1 for item in scene.mono_by_script("scrScroller") if item.data.get("m_Enabled", 1)),
            "scrBgbar": sum(1 for item in scene.mono_by_script("scrBgbar") if item.data.get("m_Enabled", 1)),
            "scrBackgroundBars": sum(
                1 for item in scene.mono_by_script("scrBackgroundBars") if item.data.get("m_Enabled", 1)
            ),
            "scrVolumeTrackerFloat": sum(
                1 for item in scene.mono_by_script("scrVolumeTrackerFloat") if item.data.get("m_Enabled", 1)
            ),
            "FallingPetals": sum(1 for item in scene.mono_by_script("FallingPetals") if item.data.get("m_Enabled", 1)),
        }
        details = ", ".join(f"{name} {count} 个" for name, count in skipped.items() if count)
        if details:
            report.add(
                "Unsupported effects",
                f"3-X 跳过脚本驱动/音量驱动动画：{details}。这些运行时循环不硬采样成 MoveDecorations。",
            )
        return []

    def finalize_level(
        self,
        level: dict[str, Any],
        scene: UnityScene,
        asset_index,
        output_dir: Path,
        used_asset_names: set[str],
        copied_by_source: dict[Path, str],
        report: ConversionReport,
    ) -> None:
        level_maker2 = next(iter(scene.mono_by_script("scrLevelMaker2")), None)
        if not level_maker2:
            return
        first_straight = (level_maker2.data.get("arrStraight") or [{}])[0]
        guid = first_straight.get("guid") if isinstance(first_straight, dict) else None
        asset = asset_index.get(guid)
        if not asset:
            report.add("Missing assets", f"3-X 未找到轨道贴图 guid：{guid}")
            return
        copied = copied_by_source.get(asset.path)
        if copied is None:
            copied = copy_asset(asset.path, output_dir, used_asset_names, report)
            if copied:
                copied_by_source[asset.path] = copied
        if copied:
            level["settings"]["trackTexture"] = copied
            level["settings"]["trackTextureScale"] = 1
            level["settings"]["trackColor"] = "ffffff"
            level["settings"]["secondaryTrackColor"] = "ffffff"
            report.add(
                "Music and background",
                f"3-X 轨道贴图：{asset.project_relative_path} -> {copied}；旧 tilecolor=000000 不按现代 trackColor 使用，改为白色保留贴图原色。",
            )


def group_for_path(path: str) -> str | None:
    for group in GROUP_TAGS:
        if path == group or path.startswith(f"{group}/"):
            return group
    return None


def call_function_bg_switches(
    scene: UnityScene,
    effect: UnityObject,
    floor: int,
    tag_by_go: dict[int, str],
    report: ConversionReport,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    calls = (((effect.data.get("ue") or {}).get("persistentCalls") or {}).get("calls") or [])
    for call in calls:
        if call.get("memberName") != "SetActive":
            continue
        target_id = ref_id(call.get("target"))
        target_path = scene.path_for_gameobject(target_id)
        if target_path not in GROUP_TAGS:
            report.add("Unsupported effects", f"floor {floor}: 3-X ffxCallFunction target={target_path or target_id} 未转换。")
            continue
        enabled = bool((call.get("argument") or {}).get("boolArgument"))
        affected = 0
        for renderer in scene.by_class("SpriteRenderer"):
            go_id = scene.component_gameobject_id(renderer)
            if go_id is None or go_id not in tag_by_go:
                continue
            path = scene.path_for_gameobject(go_id)
            if not path.startswith(f"{target_path}/"):
                continue
            _, _, _, alpha = color(renderer.data.get("m_Color"))
            actions.append(
                {
                    "floor": floor,
                    "eventType": "MoveDecorations",
                    "duration": 0,
                    "tag": tag_by_go[go_id],
                    "positionOffset": [0, 0],
                    "angleOffset": 0,
                    "ease": "Linear",
                    "eventTag": "3-X ffxCallFunction SetActive",
                    "opacity": round_value(alpha * 100) if enabled else 0,
                }
            )
            affected += 1
        report.add(
            "Decoration mapping",
            f"floor {floor}: 3-X {target_path} SetActive({enabled}) -> {affected} 个装饰透明度切换。",
        )
    return actions


HOOKS = ThreeXHooks()


def extract(project_root: str | Path, scene_path: str | Path | None, output_dir: str | Path) -> ExtractionResult:
    return extract_with_profile(PROFILE_3X, project_root, scene_path, output_dir, hooks=HOOKS)


def main() -> None:
    main_for_profile(PROFILE_3X, hooks=HOOKS)


if __name__ == "__main__":
    main()

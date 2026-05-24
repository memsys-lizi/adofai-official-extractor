from __future__ import annotations

from pathlib import Path
from typing import Any

from .adofai_writer import copy_asset
from .converter import (
    DEFAULT_PROJECT,
    DecorationExport,
    ExtractionResult,
    LevelConversionHooks,
    color_to_hex,
    duration_beats,
    effect_floor,
    extract_with_profile,
    hitsound_name,
    main_for_profile,
    round_value,
    safe_float,
    speed_at_floor,
)
from .profiles import PROFILE_2X
from .report import ConversionReport
from .unity_scene import UnityScene, ref_id


class TwoXHooks(LevelConversionHooks):
    """2-X is hand-ruled: static Unity scene first, script-driven loops are reported only."""

    def adjust_decoration(
        self,
        scene: UnityScene,
        go_id: int,
        decoration: dict[str, Any],
        report: ConversionReport,
    ) -> dict[str, Any] | None:
        path = scene.path_for_gameobject(go_id)
        original_depth = safe_float(decoration.get("depth"), 0.0)

        if (
            path.startswith("BG/BGStatic/")
            or path.startswith("BG/beanstalk_enhance_A_blur")
            or path.startswith("BG/beanstalk_enhance_C")
            or path.startswith("BG/Cloud ")
        ):
            decoration["depth"] = round_value(320 + original_depth)
            decoration["lockRotation"] = "Enabled"
        elif (
            path.startswith("BG/BG Moving/")
            or path.startswith("BG/beanstalk_enhance_A")
            or path.startswith("BG/beanstalk_enhance_B_highres")
            or path.startswith("BG/pebbles_")
        ):
            decoration["depth"] = round_value(180 + original_depth)
        elif path.startswith("BG/world2_pigstatue_enhance_lowres"):
            decoration["depth"] = round_value(60 + original_depth)

        if not any("2-X 使用旧 Unity 多相机层级" in item for item in report.items.get("Decoration mapping", [])):
            report.add(
                "Decoration mapping",
                "2-X 使用旧 Unity 多相机层级：BGStatic 约 depth 320 并按 scrBGCamNoRotate 锁定旋转，BGMoving/藤蔓/云约 depth 180，主相机前景雕像约 depth 60；组内仍保留 SpriteRenderer sortingOrder。",
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
                        "eventTag": "2-X ffxBgColor",
                    }
                )
                report.add(
                    "Music and background",
                    f"floor {floor}: 2-X ffxBgColor -> CustomBackground color={target_color}（fadeTime={fade_seconds:g}s，现代事件按瞬时背景色近似）。",
                )
            elif name == "ffxPlaySound":
                hit_sound = hitsound_name(effect.data.get("hitSound"))
                if hit_sound == "None":
                    continue
                volume = round_value(safe_float(effect.data.get("volume"), 1.0) * 100.0)
                actions.append(
                    {
                        "floor": floor,
                        "eventType": "PlaySound",
                        "hitsound": hit_sound,
                        "hitsoundVolume": volume,
                        "angleOffset": 0,
                        "eventTag": "2-X ffxPlaySound",
                    }
                )
                report.add("音效映射", f"floor {floor}: 2-X ffxPlaySound -> PlaySound {hit_sound} volume={volume:g}。")
            elif name == "ffxPulseMag":
                report.add(
                    "Unsupported effects",
                    f"floor {floor}: 2-X ffxPulseMag pulsemag={safe_float(effect.data.get('pulsemag'), 0.0):g} 控制旧相机 hit pulse 强度，vanilla .adofai 暂无直接等价项。",
                )
        actions.extend(self._floor_camera_rotations(scene, bpm, floor_speeds, report))
        return actions

    def _floor_camera_rotations(
        self,
        scene: UnityScene,
        bpm: float,
        floor_speeds: list[float],
        report: ConversionReport,
    ) -> list[dict[str, Any]]:
        level_maker = next(iter(scene.mono_by_script("scrLevelMaker")), None)
        camera = next(iter(scene.mono_by_script("scrCamera")), None)
        if not level_maker or not camera:
            return []

        duration_seconds = safe_float(camera.data.get("rotdur"), 2.0) or 2.0
        target_rotation = 0.0
        actions: list[dict[str, Any]] = []
        for floor, floor_ref in enumerate(level_maker.data.get("listFloors") or []):
            floor_component = scene.objects.get(ref_id(floor_ref))
            if not floor_component:
                continue
            rotate_by = safe_float(floor_component.data.get("rotatecamera"), 0.0)
            if abs(rotate_by) < 0.00001:
                continue
            target_rotation = round_value(target_rotation + rotate_by)
            duration = duration_beats(duration_seconds, bpm, speed_at_floor(floor_speeds, floor))
            actions.append(
                {
                    "floor": floor,
                    "eventType": "MoveCamera",
                    "duration": duration,
                    "relativeTo": "Player",
                    "position": [0, 0],
                    "rotation": target_rotation,
                    "zoom": 100,
                    "angleOffset": 0,
                    "ease": "Linear",
                    "eventTag": "2-X scrFloor.rotatecamera",
                }
            )
            report.add(
                "Camera mapping",
                f"floor {floor}: 2-X scrFloor.rotatecamera {rotate_by:g}°，旧 scrCamera.rotdur={duration_seconds:g}s -> MoveCamera rotation={target_rotation:g} duration={duration:g} 拍。",
            )
        return actions

    def scene_animations(
        self,
        scene: UnityScene,
        tag_by_go: dict[int, str],
        deco_by_go: dict[int, DecorationExport],
        bpm: float,
        floor_speeds: list[float],
        report: ConversionReport,
    ) -> list[dict[str, Any]]:
        skipped_gfx = sum(1 for item in scene.mono_by_script("scrGfxFloat") if item.data.get("m_Enabled", 1))
        skipped_tween = sum(
            1
            for item in scene.mono_by_script("DOTweenAnimation")
            if item.data.get("m_Enabled", 1) and item.data.get("autoPlay", 1)
        )
        if skipped_gfx or skipped_tween:
            report.add(
                "Unsupported effects",
                f"2-X 跳过脚本驱动装饰动画：scrGfxFloat {skipped_gfx} 个，DOTweenAnimation {skipped_tween} 个。叶子/漂浮物这类运行时循环动画不再硬采样成 MoveDecorations。",
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
            report.add("Missing assets", f"2-X 未找到轨道贴图 guid：{guid}")
            return
        copied = copied_by_source.get(asset.path)
        if copied is None:
            copied = copy_asset(asset.path, output_dir, used_asset_names, report)
            if copied:
                copied_by_source[asset.path] = copied
        if copied:
            level["settings"]["trackTexture"] = copied
            level["settings"]["trackTextureScale"] = 1
            report.add("Music and background", f"2-X 轨道贴图：{asset.project_relative_path} -> {copied}")


HOOKS = TwoXHooks()


def extract(project_root: str | Path, scene_path: str | Path | None, output_dir: str | Path) -> ExtractionResult:
    return extract_with_profile(PROFILE_2X, project_root, scene_path, output_dir, hooks=HOOKS)


def main() -> None:
    main_for_profile(PROFILE_2X, hooks=HOOKS)


if __name__ == "__main__":
    main()

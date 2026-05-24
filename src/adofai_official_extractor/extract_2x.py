from __future__ import annotations

from math import pi, sin
from pathlib import Path
from typing import Any

from .converter import (
    DEFAULT_PROJECT,
    EASE_BY_DOTWEEN_INT,
    DecorationExport,
    ExtractionResult,
    LevelConversionHooks,
    beat_to_floor_angle,
    color_to_hex,
    effect_floor,
    extract_with_profile,
    floor_start_seconds,
    hitsound_name,
    main_for_profile,
    normalize_angle,
    round_value,
    safe_float,
    seconds_per_floor,
    speed_at_floor,
    world_to_ado_units,
)
from .profiles import PROFILE_2X
from .report import ConversionReport
from .unity_scene import UnityObject, UnityScene, vec3


def enabled_scripts_by_gameobject(scene: UnityScene, script_name: str) -> dict[int, UnityObject]:
    selected: dict[int, UnityObject] = {}
    for go in scene.by_class("GameObject"):
        for component_id in scene.component_ids_for_gameobject(go.file_id):
            component = scene.objects.get(component_id)
            if (
                component
                and component.class_name == "MonoBehaviour"
                and component.script_name == script_name
                and component.data.get("m_Enabled", 1)
            ):
                selected[go.file_id] = component
    return selected


def convert_gfx_float(
    scene: UnityScene,
    tag_by_go: dict[int, str],
    bpm: float,
    floor_speeds: list[float],
    report: ConversionReport,
) -> list[dict[str, Any]]:
    selected = enabled_scripts_by_gameobject(scene, "scrGfxFloat")
    if not selected:
        return []

    actions: list[dict[str, Any]] = []
    starts = floor_start_seconds(floor_speeds, bpm)
    converted = 0
    skipped_local = 0
    for go_id, script in selected.items():
        tag = tag_by_go.get(go_id)
        if not tag:
            continue
        amplitude = safe_float(script.data.get("amplitude"), 0.0)
        period = safe_float(script.data.get("period"), 1.0) or 1.0
        if script.data.get("useLocalPos"):
            skipped_local += 1
            continue
        phase = (go_id % 97) / 97.0 * pi
        for floor, start_seconds in enumerate(starts):
            target_seconds = start_seconds + seconds_per_floor(bpm, speed_at_floor(floor_speeds, floor))
            offset_y = amplitude * sin(target_seconds / period + phase)
            actions.append(
                {
                    "floor": floor,
                    "eventType": "MoveDecorations",
                    "duration": 1,
                    "tag": tag,
                    "positionOffset": [0, world_to_ado_units(offset_y)],
                    "angleOffset": 0,
                    "ease": "InOutSine",
                    "eventTag": "2-X scrGfxFloat approximation",
                }
            )
        converted += 1

    if converted:
        report.add("Decoration mapping", f"2-X scrGfxFloat: {converted} 个启用对象已按每拍采样正弦上下漂浮近似。")
    if skipped_local:
        report.add("Unsupported effects", f"2-X scrGfxFloat: {skipped_local} 个 useLocalPos 对象暂未转换。")
    return actions


def dotween_seconds_to_beat(seconds: float, bpm: float) -> float:
    return seconds * bpm / 60.0


def scale_component(value: float, start_local: float, export_scale: float, is_relative: bool) -> float:
    target_local = start_local + value if is_relative else value
    if abs(start_local) < 0.00001:
        return round_value(export_scale)
    return round_value(export_scale * target_local / start_local)


def convert_dotween_animations(
    scene: UnityScene,
    deco_by_go: dict[int, DecorationExport],
    bpm: float,
    floor_speeds: list[float],
    report: ConversionReport,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    converted = 0
    unsupported: dict[int, int] = {}
    total_beats = len(floor_speeds)

    for tween in scene.mono_by_script("DOTweenAnimation"):
        if not tween.data.get("m_Enabled", 1) or not tween.data.get("autoPlay", 1):
            continue
        animation_type = int(tween.data.get("animationType", -1) or -1)
        if int(tween.data.get("loops", 0) or 0) != -1 or int(tween.data.get("loopType", 0) or 0) != 1:
            unsupported[animation_type] = unsupported.get(animation_type, 0) + 1
            continue
        go_id = scene.component_gameobject_id(tween)
        export = deco_by_go.get(go_id or -1)
        if not export:
            continue

        duration_seconds = safe_float(tween.data.get("duration"), 0.0)
        if duration_seconds <= 0:
            continue
        duration = dotween_seconds_to_beat(duration_seconds, bpm)
        delay = dotween_seconds_to_beat(safe_float(tween.data.get("delay"), 0.0), bpm)
        ease = EASE_BY_DOTWEEN_INT.get(int(tween.data.get("easeType", 1) or 1), "Linear")
        is_relative = bool(tween.data.get("isRelative"))
        end_v3 = vec3(tween.data.get("endValueV3"))

        forward: dict[str, Any]
        restore: dict[str, Any]
        if animation_type == 5:
            forward = {
                "scale": [
                    scale_component(end_v3[0], export.local_scale[0], export.scale[0], is_relative),
                    scale_component(end_v3[1], export.local_scale[1], export.scale[1], is_relative),
                ]
            }
            restore = {"scale": [round_value(export.scale[0]), round_value(export.scale[1])]}
        elif animation_type == 4:
            delta_z = end_v3[2] if is_relative else end_v3[2] - export.local_rotation
            forward = {"rotationOffset": normalize_angle(export.rotation + delta_z)}
            restore = {"rotationOffset": normalize_angle(export.rotation)}
        else:
            unsupported[animation_type] = unsupported.get(animation_type, 0) + 1
            continue

        beat = delay
        while beat < total_beats:
            floor, angle_offset = beat_to_floor_angle(beat, total_beats)
            actions.append(
                {
                    "floor": floor,
                    "eventType": "MoveDecorations",
                    "duration": round_value(duration),
                    "tag": export.tag,
                    **forward,
                    "angleOffset": angle_offset,
                    "ease": ease,
                    "eventTag": "2-X DOTweenAnimation approximation",
                }
            )
            restore_beat = beat + duration
            if restore_beat < total_beats:
                floor, angle_offset = beat_to_floor_angle(restore_beat, total_beats)
                actions.append(
                    {
                        "floor": floor,
                        "eventType": "MoveDecorations",
                        "duration": round_value(duration),
                        "tag": export.tag,
                        **restore,
                        "angleOffset": angle_offset,
                        "ease": ease,
                        "eventTag": "2-X DOTweenAnimation approximation",
                    }
                )
            beat += duration * 2.0
        converted += 1

    if converted:
        report.add("Decoration mapping", f"2-X DOTweenAnimation: {converted} 个无限 Yoyo 缩放/旋转动画已近似为循环 MoveDecorations。")
    for animation_type, count in sorted(unsupported.items()):
        report.add("Unsupported effects", f"2-X DOTweenAnimation animationType={animation_type}: {count} 个组件暂未转换。")
    return actions


class TwoXHooks(LevelConversionHooks):
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
                report.add("Sound mapping", f"floor {floor}: 2-X ffxPlaySound -> PlaySound {hit_sound} volume={volume:g}。")
            elif name == "ffxPulseMag":
                report.add(
                    "Unsupported effects",
                    f"floor {floor}: 2-X ffxPulseMag pulsemag={safe_float(effect.data.get('pulsemag'), 0.0):g} 控制旧相机 hit pulse 强度，vanilla .adofai 暂无直接等价项。",
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
        actions: list[dict[str, Any]] = []
        actions.extend(convert_gfx_float(scene, tag_by_go, bpm, floor_speeds, report))
        actions.extend(convert_dotween_animations(scene, deco_by_go, bpm, floor_speeds, report))
        return actions


HOOKS = TwoXHooks()


def extract(project_root: str | Path, scene_path: str | Path | None, output_dir: str | Path) -> ExtractionResult:
    return extract_with_profile(PROFILE_2X, project_root, scene_path, output_dir, hooks=HOOKS)


def main() -> None:
    main_for_profile(PROFILE_2X, hooks=HOOKS)


if __name__ == "__main__":
    main()

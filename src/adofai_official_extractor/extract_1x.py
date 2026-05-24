from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import shutil
from typing import Any

from .adofai_writer import copy_asset, write_adofai
from .asset_index import AssetIndex
from .report import ConversionReport
from .unity_scene import UnityObject, UnityScene, color, ref_id, vec3


DEFAULT_PROJECT = Path(r"C:\Users\lizi\Documents\Doc\Unity\ADOFAI")
DEFAULT_SCENE_REL = Path("Assets") / "scenes" / "Levels" / "1-X.unity"
OLD_TILE_SIZE = 1.5

EASE_BY_DOTWEEN_INT = {
    0: "Linear",
    1: "Linear",
    2: "InSine",
    3: "OutSine",
    4: "InOutSine",
    5: "InQuad",
    6: "OutQuad",
    7: "InOutQuad",
    8: "InCubic",
    9: "OutCubic",
    10: "InOutCubic",
    11: "InQuart",
    12: "OutQuart",
    13: "InOutQuart",
    14: "InQuint",
    15: "OutQuint",
    16: "InOutQuint",
    26: "InBack",
    27: "OutBack",
    28: "InOutBack",
}


@dataclass
class ExtractionResult:
    level: dict[str, Any]
    report: ConversionReport
    copied_assets: dict[int, str]
    floor_count: int
    old_path_raw: str


def clean_old_path(raw: str) -> str:
    return re.sub(r"\s+", "", raw)


def visible_path_from_old_data(old_path: str) -> str:
    return "".join(ch for ch in old_path if ch != "S")


def clamp_byte(value: float) -> int:
    return max(0, min(255, round(value * 255)))


def color_to_hex(value: Any, include_alpha: bool = False) -> str:
    r, g, b, a = color(value)
    if include_alpha:
        return f"{clamp_byte(r):02x}{clamp_byte(g):02x}{clamp_byte(b):02x}{clamp_byte(a):02x}"
    return f"{clamp_byte(r):02x}{clamp_byte(g):02x}{clamp_byte(b):02x}"


def world_to_ado_units(value: float) -> float:
    return round_value(value / OLD_TILE_SIZE)


def old_parallax_to_modern_multiplier(value: float) -> float:
    if abs(value - 1.0) < 0.00001:
        return 0.99
    return value


def old_world_to_modern_parallax_position(value: float, multiplier: float) -> float:
    modern_multiplier = old_parallax_to_modern_multiplier(multiplier)
    if abs(modern_multiplier) < 0.00001:
        return value
    return value / (1.0 - modern_multiplier)


def enabled(value: bool) -> str:
    return "Enabled" if value else "Disabled"


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def round_value(value: float, digits: int = 5) -> float:
    rounded = round(value, digits)
    return 0.0 if abs(rounded) < 0.00001 else rounded


def normalize_angle(value: float) -> float:
    normalized = (value + 180.0) % 360.0 - 180.0
    return round_value(normalized)


def duration_beats(seconds: float, bpm: float, speed: float) -> float:
    if seconds <= 0:
        return 0.0
    crotchet = 60.0 / max(0.001, bpm * speed)
    return round_value(seconds / crotchet)


def base_settings(
    caption: str,
    bpm: float,
    offset_seconds: float,
    song_filename: str = "",
    bg_image: str = "",
    background_color: str = "250f33",
) -> dict[str, Any]:
    song = caption
    if " " in caption:
        maybe_id, maybe_title = caption.split(" ", 1)
        if maybe_id.endswith("-X"):
            song = maybe_title
    return {
        "version": 6,
        "artist": "7th Beat Games",
        "artistPermission": "",
        "song": song,
        "author": "ADOFAI old official scene extractor",
        "separateCountdownTime": "Disabled",
        "previewImage": "",
        "previewIcon": "",
        "previewIconColor": "ffffff",
        "previewSongStart": 0,
        "previewSongDuration": 10,
        "seizureWarning": "Disabled",
        "levelDesc": "Extracted from the old Unity scene-based official 1-X level.",
        "levelTags": "official,extracted,experimental",
        "difficulty": 1,
        "songFilename": song_filename,
        "bpm": bpm,
        "volume": 100,
        "offset": round(offset_seconds * 1000),
        "pitch": 100,
        "hitsound": "Kick",
        "hitsoundVolume": 100,
        "countdownTicks": 4,
        "trackColorType": "Single",
        "trackColor": "debb7b",
        "secondaryTrackColor": "ffffff",
        "trackColorAnimDuration": 2,
        "trackColorPulse": "None",
        "trackPulseLength": 10,
        "trackStyle": "Standard",
        "trackAnimation": "None",
        "beatsAhead": 3,
        "trackDisappearAnimation": "None",
        "beatsBehind": 4,
        "backgroundColor": background_color,
        "bgImage": bg_image,
        "bgImageColor": "ffffff",
        "parallax": [100, 100],
        "bgDisplayMode": "FitToScreen",
        "lockRot": "Disabled",
        "loopBG": "Disabled",
        "unscaledSize": 100,
        "relativeTo": "Player",
        "position": [0, 0],
        "rotation": 0,
        "zoom": 100,
        "bgVideo": "",
        "loopVideo": "Disabled",
        "vidOffset": 0,
        "floorIconOutlines": "Disabled",
        "stickToFloors": "Disabled",
        "planetEase": "Linear",
        "planetEaseParts": 1,
        "legacyFlash": False,
        "legacySpriteTiles": True,
    }


def find_one(scene: UnityScene, script_name: str) -> UnityObject:
    matches = scene.mono_by_script(script_name)
    if not matches:
        raise RuntimeError(f"Could not find {script_name} in {scene.path}")
    return matches[0]


def build_floor_lookup(scene: UnityScene, level_maker: UnityObject) -> dict[int, int]:
    floor_lookup: dict[int, int] = {}
    for index, floor_ref in enumerate(level_maker.data.get("listFloors") or []):
        floor_component_id = ref_id(floor_ref)
        floor_component = scene.objects.get(floor_component_id) if floor_component_id is not None else None
        go_id = scene.component_gameobject_id(floor_component)
        if go_id is not None:
            floor_lookup[go_id] = index
    return floor_lookup


def floor_speeds_from_scene(scene: UnityScene, level_maker: UnityObject) -> list[float]:
    speeds: list[float] = []
    for floor_ref in level_maker.data.get("listFloors") or []:
        floor_component_id = ref_id(floor_ref)
        floor_component = scene.objects.get(floor_component_id) if floor_component_id is not None else None
        speeds.append(round_value(safe_float(floor_component.data.get("speed"), 1.0) if floor_component else 1.0))
    return speeds


def scene_speed_events(floor_speeds: list[float], bpm: float, report: ConversionReport) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    current = 1.0
    for floor, speed in enumerate(floor_speeds):
        if abs(speed - current) < 0.00001:
            continue
        actions.append(
            {
                "floor": floor,
                "eventType": "SetSpeed",
                "speedType": "Multiplier",
                "beatsPerMinute": bpm,
                "bpmMultiplier": round_value(speed),
            }
        )
        report.add("Speed mapping", f"floor {floor}: Unity scrFloor.speed {current:g} -> {speed:g}")
        current = speed
    return actions


def is_bg_sprite(scene: UnityScene, sprite_renderer: UnityObject) -> bool:
    go_id = scene.component_gameobject_id(sprite_renderer)
    path = scene.path_for_gameobject(go_id)
    if not path.startswith("BG/"):
        return False
    if not sprite_renderer.data.get("m_Enabled", 1):
        return False
    sprite = sprite_renderer.data.get("m_Sprite")
    return isinstance(sprite, dict) and bool(sprite.get("guid"))


def make_tag(path: str, go_id: int, used: set[str]) -> str:
    base = re.sub(r"[^A-Za-z0-9_]+", "_", path).strip("_").lower() or "deco"
    base = base[-44:]
    candidate = f"{base}_{go_id}"
    while candidate in used:
        candidate = f"{candidate}_x"
    used.add(candidate)
    return candidate


def first_script_in_ancestors(scene: UnityScene, go_id: int, script_name: str) -> UnityObject | None:
    for ancestor_id in scene.ancestor_gameobject_ids(go_id):
        script = scene.script_for_gameobject(ancestor_id, script_name)
        if script and script.data.get("m_Enabled", 1):
            return script
    return None


def inherited_parallax(scene: UnityScene, go_id: int, report: ConversionReport) -> tuple[list[float], tuple[float, float], str]:
    parallax = first_script_in_ancestors(scene, go_id, "scrParallax")
    if not parallax:
        return [0, 0], (0.0, 0.0), "Global"
    old_x = 0.0 if parallax.data.get("dontalter_x") else safe_float(parallax.data.get("multiplier_x"), 0.0)
    old_y = 0.0 if parallax.data.get("dontalter_y") else safe_float(parallax.data.get("multiplier_y"), 0.0)
    x = old_parallax_to_modern_multiplier(old_x) * 100.0
    y = old_parallax_to_modern_multiplier(old_y) * 100.0
    relative_to = "Camera" if parallax.data.get("relativeToCamera") else "Global"
    if parallax.data.get("clampToScreen"):
        relative_to = "CameraAspect"
        path = scene.path_for_gameobject(scene.component_gameobject_id(parallax))
        report.add("Decoration mapping", f"{path} 使用 clampToScreen，已近似为 relativeTo: CameraAspect。")
    return [round_value(x), round_value(y)], (old_x, old_y), relative_to


def inherited_camera_lock(scene: UnityScene, go_id: int) -> tuple[bool, bool, bool]:
    lock = first_script_in_ancestors(scene, go_id, "scrLockToCamera")
    if not lock:
        return False, False, False
    return bool(lock.data.get("lockPos")), bool(lock.data.get("lockRot")), bool(lock.data.get("lockScale"))


def sprite_asset_for_renderer(renderer: UnityObject, asset_index: AssetIndex):
    sprite = renderer.data.get("m_Sprite")
    guid = sprite.get("guid") if isinstance(sprite, dict) else None
    return guid, asset_index.get(guid)


def extract_decorations(
    scene: UnityScene,
    asset_index: AssetIndex,
    output_dir: Path,
    used_asset_names: set[str],
    copied_by_source: dict[Path, str],
    report: ConversionReport,
    skip_gameobjects: set[int] | None = None,
) -> tuple[list[dict[str, Any]], dict[int, str], dict[int, str]]:
    decorations: list[dict[str, Any]] = []
    tag_by_go: dict[int, str] = {}
    image_by_go: dict[int, str] = {}
    used_tags: set[str] = set()
    level_dir = output_dir
    skip_gameobjects = skip_gameobjects or set()

    for renderer in scene.by_class("SpriteRenderer"):
        if not is_bg_sprite(scene, renderer):
            continue
        go_id = scene.component_gameobject_id(renderer)
        if go_id is None:
            continue
        if go_id in skip_gameobjects:
            continue
        path = scene.path_for_gameobject(go_id)
        world = scene.world_transform_for_gameobject(go_id)
        guid, asset = sprite_asset_for_renderer(renderer, asset_index)
        copied_name = None
        if asset:
            copied_name = copied_by_source.get(asset.path)
            if copied_name is None:
                copied_name = copy_asset(asset.path, level_dir, used_asset_names, report)
                if copied_name:
                    copied_by_source[asset.path] = copied_name
        if not copied_name:
            report.add("Missing assets", f"{path} 引用了未知的 sprite guid：{guid}")
            continue

        tag = make_tag(path, go_id, used_tags)
        tag_by_go[go_id] = tag
        image_by_go[go_id] = copied_name
        r, g, b, a = color(renderer.data.get("m_Color"))
        sorting_order = int(renderer.data.get("m_SortingOrder", 0) or 0)
        parallax, old_parallax, relative_to = inherited_parallax(scene, go_id, report)
        lock_pos, lock_rot, lock_scale = inherited_camera_lock(scene, go_id)
        if lock_pos:
            relative_to = "Camera"
        export_world_x = old_world_to_modern_parallax_position(world.x, old_parallax[0])
        export_world_y = old_world_to_modern_parallax_position(world.y, old_parallax[1])
        scale_multiplier = 100.0 / max(asset.sprite_pixels_per_unit if asset else 100.0, 0.001)
        scale_x = world.scale_x * 100.0 * scale_multiplier * (-1.0 if renderer.data.get("m_FlipX") else 1.0)
        scale_y = world.scale_y * 100.0 * scale_multiplier * (-1.0 if renderer.data.get("m_FlipY") else 1.0)
        decorations.append(
            {
                "floor": 0,
                "eventType": "AddDecoration",
                "decorationImage": copied_name,
                "position": [world_to_ado_units(export_world_x), world_to_ado_units(export_world_y)],
                "relativeTo": relative_to,
                "pivotOffset": [0, 0],
                "rotation": normalize_angle(world.rotation_z),
                "scale": [round_value(scale_x), round_value(scale_y)],
                "tile": [1, 1],
                "color": f"{clamp_byte(r):02x}{clamp_byte(g):02x}{clamp_byte(b):02x}",
                "opacity": round_value(a * 100),
                "depth": -sorting_order,
                "parallax": parallax,
                "tag": tag,
                "imageSmoothing": "Enabled",
                "lockRotation": enabled(lock_rot),
                "lockScale": enabled(lock_scale),
                "failHitbox": "Disabled",
                "failHitboxType": "Box",
                "failHitboxScale": [100, 100],
                "failHitboxOffset": [0, 0],
                "failHitboxRotation": 0,
                "components": "",
            }
        )
        if len(decorations) <= 40 and (parallax != [0, 0] or relative_to != "Global" or abs(world.rotation_z) > 0.001):
            report.add(
                "Decoration mapping",
                f"{path}: relativeTo={relative_to}, oldParallax=({round_value(old_parallax[0])},{round_value(old_parallax[1])}), exportParallax={parallax}, UnityPos=({round_value(world.x)},{round_value(world.y)}) -> exportPos=({world_to_ado_units(export_world_x)},{world_to_ado_units(export_world_y)}), UnityRot={round_value(world.rotation_z)} -> exportRot={normalize_angle(world.rotation_z)}",
            )
    return decorations, tag_by_go, image_by_go


def effect_floor(scene: UnityScene, effect: UnityObject, floor_lookup: dict[int, int]) -> int | None:
    go_id = scene.component_gameobject_id(effect)
    if go_id is None:
        return None
    return floor_lookup.get(go_id)


def target_tag(scene: UnityScene, effect: UnityObject, tag_by_go: dict[int, str], report: ConversionReport) -> str | None:
    target_id = ref_id(effect.data.get("spriteObject") or effect.data.get("objFade"))
    if target_id is None:
        report.add("Unsupported effects", f"{effect.script_name} 没有 spriteObject/objFade 引用")
        return None
    tag = tag_by_go.get(target_id)
    if tag is None:
        report.add(
            "Unsupported effects",
            f"{effect.script_name} 的目标不是已导出的装饰：{scene.path_for_gameobject(target_id)} ({target_id})",
        )
    return tag


def convert_floor_effects(
    scene: UnityScene,
    floor_lookup: dict[int, int],
    tag_by_go: dict[int, str],
    bpm: float,
    floor_speeds: list[float],
    report: ConversionReport,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []

    for effect in sorted(scene.by_class("MonoBehaviour"), key=lambda obj: obj.file_id):
        name = effect.script_name or ""
        floor = effect_floor(scene, effect, floor_lookup)
        if floor is None:
            continue

        if name == "ffxSpeed":
            speed = safe_float(effect.data.get("speed"), 1.0)
            report.add("Speed mapping", f"floor {floor}: ffxSpeed={speed:g} 是旧运行时 ADOBase.d_speed，未再直接导出为现代 SetSpeed。")
        elif name == "ffxFlash":
            flash_style = int(effect.data.get("flashstyle", 0) or 0)
            duration = safe_float(effect.data.get("timeInCrotchets"), 0.25) or 0.25
            start_color = color_to_hex(effect.data.get("color"))
            secondary_color = color_to_hex(effect.data.get("secondaryColor"))
            if flash_style == 1:
                start_opacity, end_opacity = 0, 100
            elif flash_style == 3:
                start_opacity, end_opacity = 100, 100
            else:
                start_opacity, end_opacity = 100, 0
            actions.append(
                {
                    "floor": floor,
                    "eventType": "Flash",
                    "duration": round_value(duration),
                    "plane": "Foreground",
                    "startColor": start_color,
                    "startOpacity": start_opacity,
                    "endColor": secondary_color,
                    "endOpacity": end_opacity,
                    "angleOffset": 0,
                    "ease": "Linear",
                    "eventTag": "",
                }
            )
        elif name == "ffxJerkCam":
            size = safe_float(effect.data.get("size"), 5.0)
            zoom = round_value(size / 5.0 * 100.0)
            end_zoom = round_value(max(size - 0.3, 0.001) / 5.0 * 100.0)
            should_skew = bool(effect.data.get("shouldSkewAngle"))
            actions.append(
                {
                    "floor": floor,
                    "eventType": "MoveCamera",
                    "duration": 0,
                    "relativeTo": "Player",
                    "position": [0, 0],
                    "rotation": 2.5 if should_skew else 0,
                    "zoom": zoom,
                    "angleOffset": 0,
                    "ease": "Linear",
                    "eventTag": "",
                }
            )
            actions.append(
                {
                    "floor": floor,
                    "eventType": "MoveCamera",
                    "duration": duration_beats(1.0, bpm, speed_at_floor(floor_speeds, floor)),
                    "relativeTo": "Player",
                    "position": [0, 0],
                    "rotation": 5 if should_skew else 0,
                    "zoom": end_zoom,
                    "angleOffset": 0,
                    "ease": "Linear",
                    "eventTag": "",
                }
            )
            report.add("Camera mapping", f"floor {floor}: ffxJerkCam size {size:g} -> zoom {zoom:g}，1 秒后近似到 {end_zoom:g}。")
            for filter_name in ("Grayscale", "Blur"):
                actions.append(
                    {
                        "floor": floor,
                        "eventType": "SetFilter",
                        "filter": filter_name,
                        "enabled": "Enabled",
                        "intensity": 100,
                        "duration": 0,
                        "ease": "Linear",
                        "disableOthers": "Disabled",
                        "angleOffset": 0,
                        "eventTag": "",
                    }
                )
        elif name == "ffxCamRestore":
            report.add("Camera mapping", f"floor {floor}: ffxCamRestore -> 相机旋转复位并关闭灰度/模糊。")
            actions.append(
                {
                    "floor": floor,
                    "eventType": "MoveCamera",
                    "duration": 0,
                    "relativeTo": "Player",
                    "position": [0, 0],
                    "rotation": 0,
                    "zoom": 100,
                    "angleOffset": 0,
                    "ease": "Linear",
                    "eventTag": "",
                }
            )
            for filter_name in ("Grayscale", "Blur"):
                actions.append(
                    {
                        "floor": floor,
                        "eventType": "SetFilter",
                        "filter": filter_name,
                        "enabled": "Disabled",
                        "intensity": 100,
                        "duration": 0,
                        "ease": "Linear",
                        "disableOthers": "Disabled",
                        "angleOffset": 0,
                        "eventTag": "",
                    }
                )
        elif name in {"ffxSpriteScale", "ffxSpriteRotate", "ffxHueSpriteTween", "ffxFadeIn"}:
            tag = target_tag(scene, effect, tag_by_go, report)
            if not tag:
                continue
            event: dict[str, Any] = {
                "floor": floor,
                "eventType": "MoveDecorations",
                "duration": duration_beats(safe_float(effect.data.get("time"), 0.0), bpm, speed_at_floor(floor_speeds, floor)),
                "tag": tag,
                "positionOffset": [0, 0],
                "angleOffset": 0,
                "ease": EASE_BY_DOTWEEN_INT.get(int(effect.data.get("ease", 1) or 1), "Linear"),
                "eventTag": "",
            }
            if name == "ffxSpriteScale":
                scale = effect.data.get("scale") or {}
                event["scale"] = [
                    round_value(safe_float(scale.get("x"), 1.0) * 100),
                    round_value(safe_float(scale.get("y"), 1.0) * 100),
                ]
            elif name == "ffxSpriteRotate":
                angle = effect.data.get("angleDegrees") or {}
                event["rotationOffset"] = round_value(safe_float(angle.get("z"), 0.0))
            elif name == "ffxHueSpriteTween":
                event["color"] = color_to_hex(effect.data.get("color"), include_alpha=True)
                event["opacity"] = round_value(color(effect.data.get("color"))[3] * 100)
            elif name == "ffxFadeIn":
                event["opacity"] = round_value(safe_float(effect.data.get("value"), 1.0) * 100)
            actions.append(event)

    return actions


def convert_scene_animation_scripts(
    scene: UnityScene,
    tag_by_go: dict[int, str],
    bpm: float,
    floor_speeds: list[float],
    report: ConversionReport,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    total_seconds = len(floor_speeds) * 60.0 / max(bpm, 0.001)
    total_beats = len(floor_speeds)

    for mover in scene.mono_by_script("scrMove"):
        go_id = scene.component_gameobject_id(mover)
        tag = tag_by_go.get(go_id or -1)
        if not tag:
            continue
        velocity = vec3(mover.data.get("velocity"))
        delay_seconds = safe_float(mover.data.get("delay"), 0.0)
        start_beat = max(0, min(total_beats - 1, round(delay_seconds * bpm / 60.0)))
        active_seconds = max(0.0, total_seconds - delay_seconds)
        actions.append(
            {
                "floor": start_beat,
                "eventType": "MoveDecorations",
                "duration": duration_beats(active_seconds, bpm, speed_at_floor(floor_speeds, start_beat)),
                "tag": tag,
                "positionOffset": [world_to_ado_units(velocity[0] * active_seconds), world_to_ado_units(velocity[1] * active_seconds)],
                "angleOffset": 0,
                "ease": "Linear",
                "eventTag": "scrMove approximation",
            }
        )
        report.add(
            "Decoration mapping",
            f"{scene.path_for_gameobject(go_id)}: scrMove velocity=({velocity[0]:g},{velocity[1]:g}) delay={delay_seconds:g}s，已近似为长 MoveDecorations。",
        )

    pulse_count = 0
    pulse_count = len([pulse for pulse in scene.mono_by_script("scrPulseOnBeat") if tag_by_go.get(scene.component_gameobject_id(pulse) or -1)])
    if pulse_count:
        report.add("Unsupported effects", f"scrPulseOnBeat: {pulse_count} 个星星脉冲组件会制造大量重复事件，暂不导出，避免第一个砖块堆满 MoveDecorations。")

    opacity_count = len([opacity for opacity in scene.mono_by_script("scrOpacityChangeOnBeat") if tag_by_go.get(scene.component_gameobject_id(opacity) or -1)])
    if opacity_count:
        report.add("Unsupported effects", f"scrOpacityChangeOnBeat: {opacity_count} 个星星透明度组件会制造大量重复事件，暂不导出。")

    for script_name in ("scrLanternShake", "scrVolumeTrackerScale"):
        count = len(scene.mono_by_script(script_name))
        if count:
            report.add("Unsupported effects", f"{script_name}: {count} 个组件依赖运行时/音频采样，第一版先记录，未完全复刻。")

    return actions


def initial_bloom_events(scene: UnityScene, report: ConversionReport) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for effect in scene.by_class("MonoBehaviour"):
        name = effect.script_name or ""
        if name == "VideoBloom" and effect.data.get("m_Enabled", 1):
            actions.append(
                {
                    "floor": 0,
                    "eventType": "Bloom",
                    "enabled": "Enabled",
                    "threshold": round_value(safe_float(effect.data.get("Threshold"), 0.5) * 100),
                    "intensity": round_value(safe_float(effect.data.get("MasterAmount"), 1.0) * 100),
                    "color": color_to_hex(effect.data.get("Tint"), include_alpha=True),
                    "duration": 0,
                    "ease": "Linear",
                    "angleOffset": 0,
                    "eventTag": "",
                }
            )
        elif name == "BloomAndFlares" and effect.data.get("m_Enabled", 1):
            actions.append(
                {
                    "floor": 0,
                    "eventType": "Bloom",
                    "enabled": "Enabled",
                    "threshold": round_value(safe_float(effect.data.get("bloomThreshold"), 0.5) * 100),
                    "intensity": round_value(safe_float(effect.data.get("bloomIntensity"), 1.0) * 100),
                    "color": "ffffffff",
                    "duration": 0,
                    "ease": "Linear",
                    "angleOffset": 0,
                    "eventTag": "",
                }
            )
    if not actions:
        report.add("Post-processing", "没有发现启用状态的 VideoBloom/BloomAndFlares 组件，因此没有生成初始 Bloom 事件。")
    return actions[:1]


def report_post_processing(scene: UnityScene, report: ConversionReport) -> None:
    disabled_count = 0
    for effect in scene.by_class("MonoBehaviour"):
        name = effect.script_name or ""
        is_enabled = bool(effect.data.get("m_Enabled", 1))
        if name.startswith("CameraFilterPack") or name in {"Blur", "CameraMotionBlur"}:
            path = scene.path_for_gameobject(scene.component_gameobject_id(effect))
            if is_enabled:
                report.add("Unsupported post-processing", f"{path or '<未知对象>'} 上启用的 {name}")
            else:
                disabled_count += 1
        elif name == "BloomAndFlares":
            path = scene.path_for_gameobject(scene.component_gameobject_id(effect))
            if is_enabled:
                report.add("Approximate post-processing", f"{path or '<未知对象>'} 上的 {name}：已近似转换为 Bloom。")
            else:
                disabled_count += 1
    if disabled_count:
        report.add("Post-processing", f"检测到 {disabled_count} 个禁用状态的相机后处理组件；它们只是挂在场景里备用，未启用，不算视觉缺失。")


def export_song(
    scene: UnityScene,
    asset_index: AssetIndex,
    output_dir: Path,
    used_asset_names: set[str],
    copied_by_source: dict[Path, str],
    report: ConversionReport,
) -> str:
    for audio in scene.by_class("AudioSource"):
        clip = audio.data.get("m_audioClip")
        guid = clip.get("guid") if isinstance(clip, dict) else None
        asset = asset_index.get(guid)
        if not asset:
            continue
        copied = copied_by_source.get(asset.path)
        if copied is None:
            copied = copy_asset(asset.path, output_dir, used_asset_names, report)
            if copied:
                copied_by_source[asset.path] = copied
        if copied:
            report.add("Music and background", f"音乐：{asset.project_relative_path} -> {copied}")
            return copied
    report.add("Missing assets", "没有找到 Conductor/AudioSource 引用的音乐资源。")
    return ""


def export_background(
    scene: UnityScene,
    asset_index: AssetIndex,
    output_dir: Path,
    used_asset_names: set[str],
    copied_by_source: dict[Path, str],
    report: ConversionReport,
) -> str:
    candidates: list[tuple[int, UnityObject, str]] = []
    for renderer in scene.by_class("SpriteRenderer"):
        go_id = scene.component_gameobject_id(renderer)
        path = scene.path_for_gameobject(go_id)
        if path == "BG/bg_layer1_1080p":
            candidates.insert(0, (go_id or 0, renderer, path))
        elif path == "Camera/BGLofi":
            candidates.append((go_id or 0, renderer, path))
    for go_id, renderer, path in candidates:
        guid, asset = sprite_asset_for_renderer(renderer, asset_index)
        if not asset:
            report.add("Missing assets", f"{path} 背景 sprite guid 未找到：{guid}")
            continue
        copied = copied_by_source.get(asset.path)
        if copied is None:
            copied = copy_asset(asset.path, output_dir, used_asset_names, report)
            if copied:
                copied_by_source[asset.path] = copied
        if copied:
            report.add(
                "Music and background",
                f"背景层资源：{asset.project_relative_path} -> {copied}（源对象 {path}，保留为装饰层，不写入 settings.bgImage）",
            )
            return copied
    report.add("Missing assets", "没有找到可用背景层资源。")
    return ""


def camera_background_color(scene: UnityScene) -> str:
    for camera in scene.by_class("Camera"):
        if scene.path_for_gameobject(scene.component_gameobject_id(camera)) == "Camera/BGStaticCam":
            return color_to_hex(camera.data.get("m_BackGroundColor"))
    return "250f33"


def speed_at_floor(floor_speeds: list[float], floor: int) -> float:
    if not floor_speeds:
        return 1.0
    floor = max(0, min(floor, len(floor_speeds) - 1))
    return floor_speeds[floor] or 1.0


def extract(project_root: str | Path, scene_path: str | Path | None, output_dir: str | Path) -> ExtractionResult:
    project_root = Path(project_root)
    scene_path = Path(scene_path) if scene_path else project_root / DEFAULT_SCENE_REL
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_assets = output_dir / "assets"
    if generated_assets.exists():
        shutil.rmtree(generated_assets)

    report = ConversionReport()
    asset_index = AssetIndex.build(project_root)
    scene = UnityScene.load(scene_path, asset_index)
    level_maker = find_one(scene, "scrLevelMaker")
    conductor = find_one(scene, "scrConductor")

    old_path_raw = clean_old_path(str(level_maker.data.get("leveldata") or ""))
    path_data = visible_path_from_old_data(old_path_raw)
    floor_lookup = build_floor_lookup(scene, level_maker)
    bpm = safe_float(conductor.data.get("bpm"), 150.0)
    offset_seconds = safe_float(conductor.data.get("addoffset"), 0.0)
    floor_speeds = floor_speeds_from_scene(scene, level_maker)
    used_asset_names: set[str] = set()
    copied_by_source: dict[Path, str] = {}

    song_filename = export_song(scene, asset_index, output_dir, used_asset_names, copied_by_source, report)
    bg_layer_image = export_background(scene, asset_index, output_dir, used_asset_names, copied_by_source, report)
    background_color = camera_background_color(scene)
    decorations, tag_by_go, copied_assets = extract_decorations(
        scene,
        asset_index,
        output_dir,
        used_asset_names,
        copied_by_source,
        report,
    )
    actions: list[dict[str, Any]] = []
    actions.extend(initial_bloom_events(scene, report))
    actions.extend(scene_speed_events(floor_speeds, bpm, report))
    actions.extend(convert_floor_effects(scene, floor_lookup, tag_by_go, bpm, floor_speeds, report))
    actions.extend(convert_scene_animation_scripts(scene, tag_by_go, bpm, floor_speeds, report))
    report_post_processing(scene, report)

    actions.sort(key=lambda item: (int(item.get("floor", 0)), str(item.get("eventType", ""))))
    level = {
        "pathData": path_data,
        "settings": base_settings(
            str(level_maker.data.get("caption") or "1-X A Dance of Fire and Ice"),
            bpm,
            offset_seconds,
            song_filename,
            "",
            background_color,
        ),
        "actions": actions,
        "decorations": decorations,
    }

    report.set_stat("old_path_chars", len(old_path_raw))
    report.set_stat("pathData_chars", len(path_data))
    report.set_stat("scene_floor_components", len(level_maker.data.get("listFloors") or []))
    report.set_stat("decorations", len(decorations))
    report.set_stat("actions", len(actions))
    report.set_stat("copied_assets", len(set(copied_assets.values())))
    report.set_stat("nonzero_parallax_decorations", sum(1 for d in decorations if d.get("parallax") != [0, 0]))
    report.set_stat("set_speed_events", sum(1 for a in actions if a.get("eventType") == "SetSpeed"))
    report.set_stat("song_filename", song_filename or "<缺失>")
    report.set_stat("background_image", bg_layer_image or "<缺失>")
    report.set_stat("unsupported_effect_messages", len(report.items.get("Unsupported effects", [])))
    report.set_stat("unsupported_post_processing_messages", len(report.items.get("Unsupported post-processing", [])))

    write_adofai(output_dir / "main.adofai", level)
    report.write(output_dir / "conversion_report.md")
    return ExtractionResult(level, report, copied_assets, len(path_data), old_path_raw)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract old official ADOFAI 1-X Unity scene to vanilla .adofai.")
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT, help="Unity project root.")
    parser.add_argument("--scene", type=Path, default=None, help="Scene path. Defaults to Assets/scenes/Levels/1-X.unity.")
    parser.add_argument("--out", type=Path, default=Path("exports") / "1-X", help="Output level folder.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = extract(args.project, args.scene, args.out)
    print(f"Wrote {args.out / 'main.adofai'}")
    print(f"Floors/path chars: {result.floor_count}")
    print(f"Decorations: {len(result.level['decorations'])}")
    print(f"Actions: {len(result.level['actions'])}")
    print(f"Report: {args.out / 'conversion_report.md'}")


if __name__ == "__main__":
    main()

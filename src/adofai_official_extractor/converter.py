from __future__ import annotations

import argparse
from dataclasses import dataclass
from math import cos, pi, radians, sin
from pathlib import Path
import re
import shutil
from typing import Any

from .adofai_writer import copy_asset, write_adofai
from .asset_index import AssetIndex, AssetRecord
from .profiles import PROFILE_1X, PROFILE_GROUPS, PROFILES, LevelProfile
from .report import ConversionReport
from .unity_scene import UnityObject, UnityScene, color, local_matrix, matrix_to_world, ref_id, vec3


DEFAULT_PROJECT = Path(r"C:\Users\lizi\Documents\Doc\Unity\ADOFAI")
DEFAULT_SCENE_REL = PROFILE_1X.scene_rel
OLD_TILE_SIZE = PROFILE_1X.tile_size

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

OLD_LEVEL_DIRECTION_CHARS = set("UDLRQEZCthTFGByjHJMN!56789qWVYAxop")
HITSOUND_NAMES = [
    "Hat",
    "Kick",
    "Shaker",
    "Sizzle",
    "Chuck",
    "ShakerLoud",
    "None",
    "Hammer",
    "KickChroma",
    "SnareAcoustic2",
    "Sidestick",
    "Stick",
    "ReverbClack",
    "Squareshot",
    "PowerDown",
    "PowerUp",
    "KickHouse",
    "KickRupture",
    "HatHouse",
    "SnareHouse",
    "SnareVapor",
    "ClapHit",
    "ClapHitEcho",
    "ReverbClap",
    "FireTile",
    "IceTile",
    "VehiclePositive",
    "VehicleNegative",
]


@dataclass
class ExtractionResult:
    level: dict[str, Any]
    report: ConversionReport
    copied_assets: dict[int, str]
    floor_count: int
    old_path_raw: str


@dataclass(frozen=True)
class DecorationExport:
    tag: str
    tags: str
    scale: tuple[float, float]
    local_scale: tuple[float, float]
    rotation: float
    local_rotation: float


class LevelConversionHooks:
    def floor_effects(
        self,
        scene: UnityScene,
        floor_lookup: dict[int, int],
        tag_by_go: dict[int, str],
        bpm: float,
        floor_speeds: list[float],
        report: ConversionReport,
    ) -> list[dict[str, Any]]:
        return []

    def scene_animations(
        self,
        scene: UnityScene,
        tag_by_go: dict[int, str],
        deco_by_go: dict[int, DecorationExport],
        bpm: float,
        floor_speeds: list[float],
        report: ConversionReport,
    ) -> list[dict[str, Any]]:
        return []


def clean_old_path(raw: str) -> str:
    return re.sub(r"\s+", "", raw)


def visible_path_from_old_data(old_path: str) -> str:
    return "".join(ch for ch in old_path if ch in OLD_LEVEL_DIRECTION_CHARS)


def clamp_byte(value: float) -> int:
    return max(0, min(255, round(value * 255)))


def color_to_hex(value: Any, include_alpha: bool = False) -> str:
    r, g, b, a = color(value)
    if include_alpha:
        return f"{clamp_byte(r):02x}{clamp_byte(g):02x}{clamp_byte(b):02x}{clamp_byte(a):02x}"
    return f"{clamp_byte(r):02x}{clamp_byte(g):02x}{clamp_byte(b):02x}"


def hitsound_name(value: Any) -> str:
    index = int(safe_float(value, 1.0))
    if 0 <= index < len(HITSOUND_NAMES):
        return HITSOUND_NAMES[index]
    return "Kick"


def world_to_ado_units(value: float) -> float:
    return round_value(value / OLD_TILE_SIZE)


def pivot_offset_for_custom_sprite(asset: AssetRecord | None) -> list[float]:
    if not asset or not asset.pixel_size:
        return [0, 0]
    pivot_x, pivot_y = asset.sprite_pivot
    width, height = asset.pixel_size
    offset_x = (0.5 - pivot_x) * width / 100.0
    offset_y = (0.5 - pivot_y) * height / 100.0
    return [world_to_ado_units(offset_x), world_to_ado_units(offset_y)]


def sprite_center_local_offset(asset: AssetRecord | None) -> tuple[float, float]:
    if not asset or not asset.pixel_size:
        return (0.0, 0.0)
    pivot_x, pivot_y = asset.sprite_pivot
    width, height = asset.pixel_size
    ppu = max(asset.sprite_pixels_per_unit, 0.001)
    return ((0.5 - pivot_x) * width / ppu, (0.5 - pivot_y) * height / ppu)


def transform_point(matrix: list[list[float]], point: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = point
    return (
        matrix[0][0] * x + matrix[0][1] * y + matrix[0][2] * z + matrix[0][3],
        matrix[1][0] * x + matrix[1][1] * y + matrix[1][2] * z + matrix[1][3],
        matrix[2][0] * x + matrix[2][1] * y + matrix[2][2] * z + matrix[2][3],
    )


def local_rotation_z(transform: UnityObject | None) -> float:
    if transform is None:
        return 0.0
    matrix = local_matrix((0.0, 0.0, 0.0), transform.data.get("m_LocalRotation"), (1.0, 1.0, 1.0))
    return matrix_to_world(matrix).rotation_z


def inverse_rotate_2d(x: float, y: float, degrees_value: float) -> tuple[float, float]:
    angle = radians(-degrees_value)
    return (x * cos(angle) - y * sin(angle), x * sin(angle) + y * cos(angle))


def assembly_pivot_offset(
    scene: UnityScene,
    go_id: int,
    anchor_go_id: int,
    asset: AssetRecord | None,
    rotation_z: float,
    scale_x: float,
    scale_y: float,
) -> list[float]:
    transform = scene.transform_for_gameobject(go_id)
    anchor = scene.world_transform_for_gameobject(anchor_go_id)
    if transform is None:
        return [0, 0]
    local_x, local_y = sprite_center_local_offset(asset)
    center_x, center_y, _ = transform_point(scene.world_matrix(transform.file_id), (local_x, local_y, 0.0))
    delta_x, delta_y = center_x - anchor.x, center_y - anchor.y
    offset_x, offset_y = inverse_rotate_2d(delta_x, delta_y, rotation_z)
    if abs(scale_x) > 0.00001:
        offset_x /= scale_x
    if abs(scale_y) > 0.00001:
        offset_y /= scale_y
    return [world_to_ado_units(offset_x), world_to_ado_units(offset_y)]


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


def seconds_per_floor(bpm: float, speed: float) -> float:
    return 60.0 / max(0.001, bpm * speed)


def floor_start_seconds(floor_speeds: list[float], bpm: float) -> list[float]:
    starts: list[float] = []
    current = 0.0
    for speed in floor_speeds:
        starts.append(current)
        current += seconds_per_floor(bpm, speed or 1.0)
    return starts


def beat_to_floor_angle(beat: float, max_floor: int) -> tuple[int, float]:
    floor = max(0, min(int(beat), max(0, max_floor - 1)))
    angle_offset = round_value((beat - int(beat)) * 180.0)
    return floor, angle_offset


def base_settings(
    caption: str,
    bpm: float,
    offset_seconds: float,
    song_filename: str = "",
    bg_image: str = "",
    background_color: str = "250f33",
    track_color: str = "ffffff",
    profile: LevelProfile = PROFILE_1X,
) -> dict[str, Any]:
    song = caption
    if " " in caption:
        maybe_id, maybe_title = caption.split(" ", 1)
        if maybe_id == profile.level_id or re.fullmatch(r"\d+-(?:\d+|X)", maybe_id):
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
        "levelDesc": profile.level_desc,
        "levelTags": profile.level_tags,
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
        "trackColor": track_color,
        "secondaryTrackColor": "ffffff",
        "trackColorAnimDuration": 2,
        "trackColorPulse": "None",
        "trackPulseLength": 10,
        "trackStyle": "Standard",
        "trackTexture": "",
        "trackTextureScale": 1,
        "tileShape": profile.tile_shape,
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


def first_script_and_gameobject_in_ancestors(
    scene: UnityScene, go_id: int, script_name: str
) -> tuple[UnityObject, int] | None:
    for ancestor_id in scene.ancestor_gameobject_ids(go_id):
        script = scene.script_for_gameobject(ancestor_id, script_name)
        if script and script.data.get("m_Enabled", 1):
            return script, ancestor_id
    return None


def lantern_phase_tag(root_go_id: int) -> str:
    return f"lantern_phase_{root_go_id % 4}"


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
) -> tuple[list[dict[str, Any]], dict[int, str], dict[int, str], dict[int, DecorationExport]]:
    decorations: list[dict[str, Any]] = []
    tag_by_go: dict[int, str] = {}
    image_by_go: dict[int, str] = {}
    deco_by_go: dict[int, DecorationExport] = {}
    lantern_assembly_tags: dict[int, str] = {}
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

        lantern = first_script_and_gameobject_in_ancestors(scene, go_id, "scrLanternShake")
        anchor_go_id = lantern[1] if lantern else go_id
        anchor_path = scene.path_for_gameobject(anchor_go_id)
        anchor_world = scene.world_transform_for_gameobject(anchor_go_id)
        position_world = anchor_world if lantern else world

        tag = make_tag(path, go_id, used_tags)
        extra_tags: list[str] = []
        if lantern:
            assembly_tag = lantern_assembly_tags.get(anchor_go_id)
            if assembly_tag is None:
                assembly_tag = make_tag(f"{anchor_path}/lantern_assembly", anchor_go_id, used_tags)
                lantern_assembly_tags[anchor_go_id] = assembly_tag
            extra_tags.extend([assembly_tag, lantern_phase_tag(anchor_go_id)])
        tag_value = " ".join([tag, *extra_tags])
        tag_by_go[go_id] = tag
        image_by_go[go_id] = copied_name
        r, g, b, a = color(renderer.data.get("m_Color"))
        sorting_order = int(renderer.data.get("m_SortingOrder", 0) or 0)
        parallax, old_parallax, relative_to = inherited_parallax(scene, anchor_go_id, report)
        lock_pos, lock_rot, lock_scale = inherited_camera_lock(scene, anchor_go_id)
        if lock_pos:
            relative_to = "Camera"
        export_world_x = old_world_to_modern_parallax_position(position_world.x, old_parallax[0])
        export_world_y = old_world_to_modern_parallax_position(position_world.y, old_parallax[1])
        scale_multiplier = 100.0 / max(asset.sprite_pixels_per_unit if asset else 100.0, 0.001)
        scale_x = world.scale_x * 100.0 * scale_multiplier * (-1.0 if renderer.data.get("m_FlipX") else 1.0)
        scale_y = world.scale_y * 100.0 * scale_multiplier * (-1.0 if renderer.data.get("m_FlipY") else 1.0)
        transform = scene.transform_for_gameobject(go_id)
        local_scale = vec3(transform.data.get("m_LocalScale"), (1.0, 1.0, 1.0)) if transform else (1.0, 1.0, 1.0)
        pivot_offset = (
            assembly_pivot_offset(scene, go_id, anchor_go_id, asset, world.rotation_z, scale_x / 100.0, scale_y / 100.0)
            if lantern
            else pivot_offset_for_custom_sprite(asset)
        )
        decorations.append(
            {
                "floor": 0,
                "eventType": "AddDecoration",
                "decorationImage": copied_name,
                "position": [world_to_ado_units(export_world_x), world_to_ado_units(export_world_y)],
                "relativeTo": relative_to,
                "pivotOffset": pivot_offset,
                "rotation": normalize_angle(world.rotation_z),
                "scale": [round_value(scale_x), round_value(scale_y)],
                "tile": [1, 1],
                "color": f"{clamp_byte(r):02x}{clamp_byte(g):02x}{clamp_byte(b):02x}",
                "opacity": round_value(a * 100),
                "depth": -sorting_order,
                "parallax": parallax,
                "tag": tag_value,
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
        deco_by_go[go_id] = DecorationExport(
            tag=tag,
            tags=tag_value,
            scale=(round_value(scale_x), round_value(scale_y)),
            local_scale=(local_scale[0], local_scale[1]),
            rotation=normalize_angle(world.rotation_z),
            local_rotation=local_rotation_z(transform),
        )
        if len(decorations) <= 40 and (parallax != [0, 0] or relative_to != "Global" or abs(world.rotation_z) > 0.001):
            report.add(
                "Decoration mapping",
                f"{path}: relativeTo={relative_to}, oldParallax=({round_value(old_parallax[0])},{round_value(old_parallax[1])}), exportParallax={parallax}, UnityPos=({round_value(world.x)},{round_value(world.y)}) -> exportPos=({world_to_ado_units(export_world_x)},{world_to_ado_units(export_world_y)}), UnityRot={round_value(world.rotation_z)} -> exportRot={normalize_angle(world.rotation_z)}",
            )
    if lantern_assembly_tags:
        report.add("Decoration mapping", f"已把 {len(lantern_assembly_tags)} 个灯笼组按父级挂点导出，灯体和光效共享同一个旋转轴。")
    return decorations, tag_by_go, image_by_go, deco_by_go


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
    deco_by_go: dict[int, DecorationExport],
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

    actions.extend(convert_lantern_shakes(scene, bpm, floor_speeds, report))
    actions.extend(convert_pulse_on_beat(scene, deco_by_go, bpm, floor_speeds, report))
    actions.extend(convert_opacity_on_beat(scene, deco_by_go, floor_speeds, report))

    for script_name in ("scrVolumeTrackerScale",):
        count = len(scene.mono_by_script(script_name))
        if count:
            report.add("Unsupported effects", f"{script_name}: {count} 个组件依赖运行时/音频采样，第一版先记录，未完全复刻。")

    return actions


def tag_chunks(tags: list[str], limit: int = 850) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for tag in sorted(tags):
        projected = current_len + len(tag) + (1 if current else 0)
        if current and projected > limit:
            chunks.append(" ".join(current))
            current = [tag]
            current_len = len(tag)
        else:
            current.append(tag)
            current_len = projected
    if current:
        chunks.append(" ".join(current))
    return chunks


def convert_lantern_shakes(
    scene: UnityScene,
    bpm: float,
    floor_speeds: list[float],
    report: ConversionReport,
) -> list[dict[str, Any]]:
    lantern_roots = [
        scene.component_gameobject_id(script)
        for script in scene.mono_by_script("scrLanternShake")
        if script.data.get("m_Enabled", 1)
    ]
    lantern_roots = [go_id for go_id in lantern_roots if go_id is not None]
    if not lantern_roots:
        return []

    actions: list[dict[str, Any]] = []
    phases = sorted({root_id % 4 for root_id in lantern_roots})
    for phase_index in phases:
        phase = phase_index * pi / 2.0
        tag = f"lantern_phase_{phase_index}"
        for floor in range(len(floor_speeds)):
            for half in (0, 1):
                beat = floor + half * 0.5
                seconds = beat * 60.0 / max(bpm, 0.001)
                angle = 10.0 * sin(seconds * 5.0 + phase)
                actions.append(
                    {
                        "floor": floor,
                        "eventType": "MoveDecorations",
                        "duration": 0.5,
                        "tag": tag,
                        "rotationOffset": round_value(angle),
                        "angleOffset": 180 * half,
                        "ease": "InOutSine",
                        "eventTag": "scrLanternShake approximation",
                    }
                )
    report.add(
        "Decoration mapping",
        f"scrLanternShake: {len(lantern_roots)} 个灯笼已按 4 组相位近似为正弦旋转 MoveDecorations。",
    )
    return actions


def convert_pulse_on_beat(
    scene: UnityScene,
    deco_by_go: dict[int, DecorationExport],
    bpm: float,
    floor_speeds: list[float],
    report: ConversionReport,
) -> list[dict[str, Any]]:
    groups: dict[tuple[tuple[float, float], tuple[float, float], float], list[str]] = {}
    for pulse in scene.mono_by_script("scrPulseOnBeat"):
        go_id = scene.component_gameobject_id(pulse)
        export = deco_by_go.get(go_id or -1)
        if not export:
            continue
        pulse_width = safe_float(pulse.data.get("pulsewidth"), 1.0)
        local_x = export.local_scale[0] or 1.0
        local_y = export.local_scale[1] or 1.0
        target_scale = (
            round_value(export.scale[0] * pulse_width / local_x),
            round_value(export.scale[1] * pulse_width / local_y),
        )
        restore_scale = (round_value(export.scale[0]), round_value(export.scale[1]))
        time_seconds = safe_float(pulse.data.get("time"), 0.0)
        groups.setdefault((target_scale, restore_scale, time_seconds), []).append(export.tag)

    if not groups:
        return []

    actions: list[dict[str, Any]] = []
    for floor in range(len(floor_speeds)):
        restore_duration = duration_beats(0.8, bpm, speed_at_floor(floor_speeds, floor))
        for (target_scale, restore_scale, time_seconds), tags in groups.items():
            duration = duration_beats(time_seconds, bpm, speed_at_floor(floor_speeds, floor)) or restore_duration
            for tag in tag_chunks(tags):
                actions.append(
                    {
                        "floor": floor,
                        "eventType": "MoveDecorations",
                        "duration": 0,
                        "tag": tag,
                        "scale": list(target_scale),
                        "angleOffset": 0,
                        "ease": "Linear",
                        "eventTag": "scrPulseOnBeat pulse",
                    }
                )
                actions.append(
                    {
                        "floor": floor,
                        "eventType": "MoveDecorations",
                        "duration": duration,
                        "tag": tag,
                        "scale": list(restore_scale),
                        "angleOffset": 0,
                        "ease": "OutSine",
                        "eventTag": "scrPulseOnBeat restore",
                    }
                )
    report.add("Decoration mapping", f"scrPulseOnBeat: {sum(len(v) for v in groups.values())} 个星星已转换为按拍缩放。")
    return actions


def convert_opacity_on_beat(
    scene: UnityScene,
    deco_by_go: dict[int, DecorationExport],
    floor_speeds: list[float],
    report: ConversionReport,
) -> list[dict[str, Any]]:
    groups: dict[tuple[float, ...], list[str]] = {}
    for opacity in scene.mono_by_script("scrOpacityChangeOnBeat"):
        go_id = scene.component_gameobject_id(opacity)
        export = deco_by_go.get(go_id or -1)
        values = opacity.data.get("arrOpacity")
        if not export or not isinstance(values, list) or not values:
            continue
        groups.setdefault(tuple(round_value(safe_float(value) * 100) for value in values), []).append(export.tag)

    if not groups:
        return []

    actions: list[dict[str, Any]] = []
    for floor in range(len(floor_speeds)):
        for values, tags in groups.items():
            opacity = values[(floor + 1) % len(values)]
            for tag in tag_chunks(tags):
                actions.append(
                    {
                        "floor": floor,
                        "eventType": "MoveDecorations",
                        "duration": 0,
                        "tag": tag,
                        "opacity": opacity,
                        "angleOffset": 0,
                        "ease": "Linear",
                        "eventTag": "scrOpacityChangeOnBeat",
                    }
                )
    report.add("Decoration mapping", f"scrOpacityChangeOnBeat: {sum(len(v) for v in groups.values())} 个星星已转换为按拍透明度切换。")
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
    has_bg_sprites = any(
        scene.path_for_gameobject(scene.component_gameobject_id(renderer)).startswith("BG/")
        for renderer in scene.by_class("SpriteRenderer")
        if renderer.data.get("m_Enabled", 1)
    )
    if has_bg_sprites:
        report.add("Music and background", "没有单独 settings.bgImage 背景；此关背景由 BG SpriteRenderer 装饰层导出。")
    else:
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


def extract_with_profile(
    profile: LevelProfile,
    project_root: str | Path,
    scene_path: str | Path | None,
    output_dir: str | Path,
    hooks: LevelConversionHooks | None = None,
) -> ExtractionResult:
    hooks = hooks or LevelConversionHooks()
    project_root = Path(project_root)
    scene_path = Path(scene_path) if scene_path else project_root / profile.scene_rel
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_assets = output_dir / "assets"
    if generated_assets.exists():
        shutil.rmtree(generated_assets)

    report = ConversionReport()
    asset_index = AssetIndex.build(project_root)
    scene = UnityScene.load(scene_path, asset_index)
    level_maker = find_one(scene, "scrLevelMaker")
    level_maker2 = find_one(scene, "scrLevelMaker2")
    conductor = find_one(scene, "scrConductor")

    old_path_raw = clean_old_path(str(level_maker.data.get("leveldata") or ""))
    path_data = visible_path_from_old_data(old_path_raw)
    floor_lookup = build_floor_lookup(scene, level_maker)
    bpm = safe_float(conductor.data.get("bpm"), 150.0)
    offset_seconds = safe_float(conductor.data.get("addoffset"), 0.0)
    track_color = color_to_hex(level_maker2.data.get("tilecolor"))
    floor_speeds = floor_speeds_from_scene(scene, level_maker)
    used_asset_names: set[str] = set()
    copied_by_source: dict[Path, str] = {}

    song_filename = export_song(scene, asset_index, output_dir, used_asset_names, copied_by_source, report)
    bg_layer_image = export_background(scene, asset_index, output_dir, used_asset_names, copied_by_source, report)
    background_color = camera_background_color(scene)
    decorations, tag_by_go, copied_assets, deco_by_go = extract_decorations(
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
    actions.extend(hooks.floor_effects(scene, floor_lookup, tag_by_go, bpm, floor_speeds, report))
    actions.extend(convert_scene_animation_scripts(scene, tag_by_go, deco_by_go, bpm, floor_speeds, report))
    actions.extend(hooks.scene_animations(scene, tag_by_go, deco_by_go, bpm, floor_speeds, report))
    report_post_processing(scene, report)

    actions.sort(key=lambda item: (int(item.get("floor", 0)), str(item.get("eventType", ""))))
    level = {
        "pathData": path_data,
        "settings": base_settings(
            str(level_maker.data.get("caption") or profile.default_caption),
            bpm,
            offset_seconds,
            song_filename,
            "",
            background_color,
            track_color,
            profile,
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


def parse_args(default_level: str = PROFILE_1X.level_id) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract old official Unity scene-based ADOFAI levels to vanilla .adofai.")
    parser.add_argument(
        "--level",
        default=default_level,
        help="Official level profile to export, or a profile group such as tutorials-1.",
    )
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT, help="Unity project root.")
    parser.add_argument("--scene", type=Path, default=None, help="Scene path. Defaults to the selected profile scene.")
    parser.add_argument("--out", type=Path, default=None, help="Output level folder.")
    return parser.parse_args()


def resolve_profiles(level: str) -> list[LevelProfile]:
    if level in PROFILES:
        return [PROFILES[level]]
    if level in PROFILE_GROUPS:
        return [PROFILES[level_id] for level_id in PROFILE_GROUPS[level]]
    known = ", ".join(sorted([*PROFILES, *PROFILE_GROUPS]))
    raise SystemExit(f"Unknown --level {level!r}. Known profiles/groups: {known}")


def print_result(output_dir: Path, result: ExtractionResult) -> None:
    print(f"Wrote {output_dir / 'main.adofai'}")
    print(f"Floors/path chars: {result.floor_count}")
    print(f"Decorations: {len(result.level['decorations'])}")
    print(f"Actions: {len(result.level['actions'])}")
    print(f"Report: {output_dir / 'conversion_report.md'}")


def main_for_profile(profile: LevelProfile, hooks: LevelConversionHooks | None = None) -> None:
    args = parse_args(profile.level_id)
    if args.level != profile.level_id:
        raise SystemExit(f"{profile.level_id} script only exports {profile.level_id}. Use extract_level.py for generic batches.")
    output_dir = args.out or Path("exports") / profile.level_id
    result = extract_with_profile(profile, args.project, args.scene, output_dir, hooks=hooks)
    print_result(output_dir, result)


def main(hooks_by_level: dict[str, LevelConversionHooks] | None = None) -> None:
    hooks_by_level = hooks_by_level or {}
    args = parse_args()
    profiles = resolve_profiles(args.level)
    if args.scene and len(profiles) > 1:
        raise SystemExit("--scene can only be used when exporting a single profile.")
    base_output_dir = args.out or Path("exports") / args.level
    for profile in profiles:
        output_dir = base_output_dir if len(profiles) == 1 else base_output_dir / profile.level_id
        result = extract_with_profile(profile, args.project, args.scene, output_dir, hooks=hooks_by_level.get(profile.level_id))
        print_result(output_dir, result)


if __name__ == "__main__":
    main()

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, degrees, radians, sin
from pathlib import Path
import re
from typing import Any, Iterable

from ruamel.yaml import YAML

from .asset_index import AssetIndex


DOC_RE = re.compile(r"(?m)^--- !u!(\d+) &(-?\d+)\s*$")


@dataclass
class UnityObject:
    type_id: int
    file_id: int
    class_name: str
    data: dict[str, Any]
    script_name: str | None = None


@dataclass(frozen=True)
class WorldTransform:
    x: float
    y: float
    z: float
    rotation_z: float
    scale_x: float
    scale_y: float
    scale_z: float


def ref_id(value: Any) -> int | None:
    if isinstance(value, dict):
        file_id = value.get("fileID")
        if isinstance(file_id, int):
            return file_id
    return None


def vec3(value: Any, default: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> tuple[float, float, float]:
    if not isinstance(value, dict):
        return default
    return (
        float(value.get("x", default[0]) or 0.0),
        float(value.get("y", default[1]) or 0.0),
        float(value.get("z", default[2]) or 0.0),
    )


def color(value: Any) -> tuple[float, float, float, float]:
    if not isinstance(value, dict):
        return (1.0, 1.0, 1.0, 1.0)
    return (
        float(value.get("r", 1.0)),
        float(value.get("g", 1.0)),
        float(value.get("b", 1.0)),
        float(value.get("a", 1.0)),
    )


def quat_to_z_degrees(value: Any) -> float:
    if not isinstance(value, dict):
        return 0.0
    x = float(value.get("x", 0.0) or 0.0)
    y = float(value.get("y", 0.0) or 0.0)
    z = float(value.get("z", 0.0) or 0.0)
    w = float(value.get("w", 1.0) or 1.0)
    # ZYX Euler extraction, enough for these 2D scene objects.
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return degrees(atan2(siny_cosp, cosy_cosp))


class UnityScene:
    def __init__(self, path: Path, asset_index: AssetIndex) -> None:
        self.path = path
        self.asset_index = asset_index
        self.objects: dict[int, UnityObject] = {}
        self._gameobject_to_transform: dict[int, int] = {}
        self._world_cache: dict[int, WorldTransform] = {}

    @classmethod
    def load(cls, path: str | Path, asset_index: AssetIndex) -> "UnityScene":
        scene = cls(Path(path), asset_index)
        scene._load()
        scene._index_transforms()
        return scene

    def _load(self) -> None:
        yaml = YAML(typ="safe")
        text = self.path.read_text(encoding="utf-8-sig")
        parts = DOC_RE.split(text)
        for i in range(1, len(parts), 3):
            type_id = int(parts[i])
            file_id = int(parts[i + 1])
            body = parts[i + 2]
            parsed = yaml.load(body)
            if not isinstance(parsed, dict) or not parsed:
                continue
            class_name = next(iter(parsed))
            data = parsed[class_name] or {}
            script_name = None
            if class_name == "MonoBehaviour":
                script_ref = data.get("m_Script")
                script_name = self.asset_index.script_name(script_ref.get("guid") if isinstance(script_ref, dict) else None)
            self.objects[file_id] = UnityObject(type_id, file_id, class_name, data, script_name)

    def _index_transforms(self) -> None:
        for obj in self.objects.values():
            if obj.class_name not in {"Transform", "RectTransform"}:
                continue
            go_id = ref_id(obj.data.get("m_GameObject"))
            if go_id is not None:
                self._gameobject_to_transform[go_id] = obj.file_id

    def by_class(self, class_name: str) -> Iterable[UnityObject]:
        return (obj for obj in self.objects.values() if obj.class_name == class_name)

    def mono_by_script(self, script_name: str) -> list[UnityObject]:
        return [obj for obj in self.objects.values() if obj.class_name == "MonoBehaviour" and obj.script_name == script_name]

    def gameobject_name(self, go_id: int | None) -> str:
        if go_id is None:
            return ""
        obj = self.objects.get(go_id)
        if not obj or obj.class_name != "GameObject":
            return ""
        return str(obj.data.get("m_Name") or "")

    def component_gameobject_id(self, component: UnityObject | int | None) -> int | None:
        obj = self.objects.get(component) if isinstance(component, int) else component
        if not obj:
            return None
        return ref_id(obj.data.get("m_GameObject"))

    def transform_for_gameobject(self, go_id: int | None) -> UnityObject | None:
        if go_id is None:
            return None
        transform_id = self._gameobject_to_transform.get(go_id)
        if transform_id is None:
            return None
        return self.objects.get(transform_id)

    def component_ids_for_gameobject(self, go_id: int) -> list[int]:
        obj = self.objects.get(go_id)
        if not obj or obj.class_name != "GameObject":
            return []
        ids: list[int] = []
        for item in obj.data.get("m_Component") or []:
            cid = ref_id(item.get("component") if isinstance(item, dict) else item)
            if cid is not None:
                ids.append(cid)
        return ids

    def component_for_gameobject(self, go_id: int, class_name: str) -> UnityObject | None:
        for component_id in self.component_ids_for_gameobject(go_id):
            component = self.objects.get(component_id)
            if component and component.class_name == class_name:
                return component
        return None

    def script_for_gameobject(self, go_id: int, script_name: str) -> UnityObject | None:
        for component_id in self.component_ids_for_gameobject(go_id):
            component = self.objects.get(component_id)
            if component and component.class_name == "MonoBehaviour" and component.script_name == script_name:
                return component
        return None

    def parent_gameobject_id(self, go_id: int | None) -> int | None:
        transform = self.transform_for_gameobject(go_id)
        parent_id = ref_id(transform.data.get("m_Father")) if transform else None
        parent = self.objects.get(parent_id) if parent_id is not None else None
        if not parent:
            return None
        return ref_id(parent.data.get("m_GameObject"))

    def ancestor_gameobject_ids(self, go_id: int | None, include_self: bool = True) -> list[int]:
        ids: list[int] = []
        current = go_id if include_self else self.parent_gameobject_id(go_id)
        while current is not None:
            ids.append(current)
            current = self.parent_gameobject_id(current)
        return ids

    def path_for_gameobject(self, go_id: int | None) -> str:
        if go_id is None:
            return ""
        names = [self.gameobject_name(go_id)]
        transform = self.transform_for_gameobject(go_id)
        while transform:
            parent_id = ref_id(transform.data.get("m_Father"))
            parent = self.objects.get(parent_id) if parent_id is not None else None
            if not parent:
                break
            parent_go = ref_id(parent.data.get("m_GameObject"))
            if parent_go is None:
                break
            names.append(self.gameobject_name(parent_go))
            transform = parent
        return "/".join(reversed([name for name in names if name]))

    def world_transform_for_gameobject(self, go_id: int | None) -> WorldTransform:
        transform = self.transform_for_gameobject(go_id)
        if transform is None:
            return WorldTransform(0, 0, 0, 0, 1, 1, 1)
        return self.world_transform(transform.file_id)

    def world_transform(self, transform_id: int) -> WorldTransform:
        if transform_id in self._world_cache:
            return self._world_cache[transform_id]
        transform = self.objects[transform_id]
        local_pos = vec3(transform.data.get("m_LocalPosition"))
        local_scale = vec3(transform.data.get("m_LocalScale"), (1.0, 1.0, 1.0))
        euler_hint = vec3(transform.data.get("m_LocalEulerAnglesHint"))
        local_rot = euler_hint[2] if any(abs(v) > 0.00001 for v in euler_hint) else quat_to_z_degrees(transform.data.get("m_LocalRotation"))

        parent_id = ref_id(transform.data.get("m_Father"))
        if parent_id is None or parent_id not in self.objects:
            world = WorldTransform(*local_pos, local_rot, *local_scale)
            self._world_cache[transform_id] = world
            return world

        parent = self.world_transform(parent_id)
        scaled_x = local_pos[0] * parent.scale_x
        scaled_y = local_pos[1] * parent.scale_y
        angle = radians(parent.rotation_z)
        rotated_x = scaled_x * cos(angle) - scaled_y * sin(angle)
        rotated_y = scaled_x * sin(angle) + scaled_y * cos(angle)
        world = WorldTransform(
            parent.x + rotated_x,
            parent.y + rotated_y,
            parent.z + local_pos[2] * parent.scale_z,
            parent.rotation_z + local_rot,
            parent.scale_x * local_scale[0],
            parent.scale_y * local_scale[1],
            parent.scale_z * local_scale[2],
        )
        self._world_cache[transform_id] = world
        return world

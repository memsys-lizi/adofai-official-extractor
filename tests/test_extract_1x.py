from __future__ import annotations

import json
from pathlib import Path

from adofai_official_extractor.asset_index import AssetIndex
from adofai_official_extractor.extract_1x import (
    DEFAULT_PROJECT,
    DEFAULT_SCENE_REL,
    clean_old_path,
    extract,
    find_one,
    floor_speeds_from_scene,
    old_parallax_to_modern_multiplier,
    old_world_to_modern_parallax_position,
    visible_path_from_old_data,
)
from adofai_official_extractor.unity_scene import UnityScene


def test_old_level_path_counts() -> None:
    asset_index = AssetIndex.build(DEFAULT_PROJECT)
    scene = UnityScene.load(DEFAULT_PROJECT / DEFAULT_SCENE_REL, asset_index)
    level_maker = find_one(scene, "scrLevelMaker")

    old_path = clean_old_path(level_maker.data["leveldata"])

    assert len(old_path) == 174
    assert old_path.count("S") == 7
    assert len(visible_path_from_old_data(old_path)) == 167
    assert len(level_maker.data["listFloors"]) == 168
    speeds = floor_speeds_from_scene(scene, level_maker)
    assert speeds.count(0.25) == 7
    assert speeds[161:] == [0.25] * 7


def test_world_transform_projects_3d_chain_hierarchy() -> None:
    asset_index = AssetIndex.build(DEFAULT_PROJECT)
    scene = UnityScene.load(DEFAULT_PROJECT / DEFAULT_SCENE_REL, asset_index)
    go_id = next(
        obj.file_id
        for obj in scene.by_class("GameObject")
        if scene.path_for_gameobject(obj.file_id) == "BG/BG Moving/chain_b_new/chain_enhance (153)"
    )
    world = scene.world_transform_for_gameobject(go_id)

    assert abs(world.x - 130.27003) < 0.001
    assert abs(world.y + 5.34901) < 0.001
    assert abs(world.rotation_z - 30.22518) < 0.001


def test_extract_1x_outputs_vanilla_level_folder(tmp_path: Path) -> None:
    out_dir = tmp_path / "1-X"
    result = extract(DEFAULT_PROJECT, None, out_dir)
    level_path = out_dir / "main.adofai"
    report_path = out_dir / "conversion_report.md"

    assert level_path.exists()
    assert report_path.exists()
    assert not (out_dir / "assets").exists()

    level = json.loads(level_path.read_text(encoding="utf-8"))
    event_types = {event["eventType"] for event in level["actions"]}

    assert level["pathData"] == result.level["pathData"]
    assert len(level["pathData"]) == 167
    assert len(level["decorations"]) > 100
    assert level["settings"]["songFilename"] == "1-X.ogg"
    assert level["settings"]["tileShape"] == "Short"
    assert level["settings"]["bgImage"] == ""
    assert level["settings"]["backgroundColor"] == "250f33"
    assert (out_dir / level["settings"]["songFilename"]).exists()
    assert (out_dir / "bg_layer1_1080p.png").exists()
    image_names = {item.name for item in out_dir.iterdir() if item.suffix.lower() in {".png", ".jpg", ".jpeg"}}
    assert len(image_names) <= 30
    assert {"SetSpeed", "Flash", "MoveCamera", "SetFilter", "MoveDecorations"}.issubset(event_types)
    set_speed_events = [event for event in level["actions"] if event["eventType"] == "SetSpeed"]
    assert set_speed_events == [
        {
            "floor": 161,
            "eventType": "SetSpeed",
            "speedType": "Multiplier",
            "beatsPerMinute": 150.0,
            "bpmMultiplier": 0.25,
        }
    ]
    assert all("/" not in str(dec["decorationImage"]) and "\\" not in str(dec["decorationImage"]) for dec in level["decorations"])
    assert all(str(dec["decorationImage"]) in image_names for dec in level["decorations"])
    assert any(dec["parallax"] != [0, 0] for dec in level["decorations"])
    assert any(dec["relativeTo"] != "Global" or dec["parallax"] != [0, 0] for dec in level["decorations"])
    assert sum(1 for event in level["actions"] if event["floor"] == 0 and event["eventType"] == "MoveDecorations") == 0
    statue = next(dec for dec in level["decorations"] if dec["decorationImage"] == "world1_statue_enhance_lowres.png")
    assert abs(statue["position"][0] - 155.51) < 0.01
    assert abs(statue["pivotOffset"][0] - 0.00513) < 0.001
    assert abs(statue["pivotOffset"][1] + 0.02065) < 0.001

    report = report_path.read_text(encoding="utf-8")
    assert "暂未精确还原后处理条目数: 0" in report
    assert "禁用状态的相机后处理组件" in report
    assert "速度映射" in report
    assert "音乐和背景" in report


def test_old_parallax_position_is_inverted_for_modern_decorations() -> None:
    old_position = 13.77655
    old_multiplier = 0.5
    exported_position = old_world_to_modern_parallax_position(old_position, old_multiplier)
    modern_multiplier = old_parallax_to_modern_multiplier(old_multiplier)

    assert round(exported_position * (1 - modern_multiplier), 5) == old_position
    assert old_parallax_to_modern_multiplier(1.0) == 0.99

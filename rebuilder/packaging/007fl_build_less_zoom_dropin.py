#!/usr/bin/env python3
"""
Build a drag-and-drop camera/FOV package for 007 First Light.

Output:
    Runtime/chunk0patch204.rpkg
    Runtime/chunk1patch204.rpkg
    Runtime/packagedefinition.txt unless --rpkg-only is used
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import struct
import sys
from dataclasses import dataclass
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if not (REPO_ROOT / "tools").is_dir() and (SCRIPT_DIR / "tools").is_dir():
    REPO_ROOT = SCRIPT_DIR
TOOLS_DIR = REPO_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import bond_rpkg  # type: ignore
import firstlight_config_crypt  # type: ignore


PATCHLEVEL = 310
PATCH_NUMBER = 204
PATCH_SCALE = 1.40
PACKAGE_NAME = "007FL_Better_Camera_Main"
README_SOURCE = REPO_ROOT / "mods" / "CameraZoom" / "README.txt"
HASH_PATHS_CANDIDATES = (
    REPO_ROOT / "scratch" / "upstream" / "007-Hashes" / "paths" / "TEMP.json",
    REPO_ROOT / "paths" / "TEMP.json",
    SCRIPT_DIR / "paths" / "TEMP.json",
)
HASH_PATHS = next(
    (candidate for candidate in HASH_PATHS_CANDIDATES if candidate.is_file()),
    HASH_PATHS_CANDIDATES[0],
)

FOV_OVERRIDE_VALUE_ID = 0x6DAB89DB
ORBIT_RADIUS_VALUE_ID = 0x9C0139D0
TYPE_TYPEIDS = 0x3989BF9F
SUBENT_TEMP_STRIDE = 0x78
SPHERICAL_FRAMING_TYPE = "TArray<SSphericalFramingOffset>"
SPHERICAL_FRAMING_RECORD_SIZE = 0x38
SPHERICAL_FRAMING_Z_OFFSETS = (0x24, 0x30)
MIN_PATCHABLE_FOV = 5.0
MAX_PATCHABLE_FOV = 130.0
MIN_PATCHABLE_ORBIT_RADIUS = 0.2
MAX_PATCHABLE_ORBIT_RADIUS = 12.0
MIN_PATCHABLE_FRAMING_HEIGHT = -5.0
MAX_PATCHABLE_FRAMING_HEIGHT = 5.0
CAMERA_PATH_MARKER = "/_knt/design/cameras/"
SHARED_GAMEPLAY_CAMERA_MARKER = "/_knt/design/cameras/cameras.template?/"
SHARED_CAMERA_EXCLUDED_TERMS = (
    "bond_death",
    "customcamera",
    "debug camera",
    "gc_animated_camera",
)
VEHICLE_CAMERA_TERMS = (
    "atv",
    "boat",
    "cablecar",
    "chase",
    "drive",
    "driveto",
    "freefall",
    "rover",
    "truck",
    "valhalla",
    "vehicle",
)
VEHICLE_CAMERA_EXCLUDED_TERMS = (
    "arena",
    "bawma",
    "bossfight",
    "combat",
    "crocodilepit",
    "fight",
    "finisher",
    "freefall",
    "monroe",
    "parachute",
    "pit",
    "skydiv",
    "takedown",
)


@dataclass(frozen=True)
class ResourceTarget:
    chunk: str
    hash_value: int
    path: str


@dataclass(frozen=True)
class ResourcePatchStats:
    fov_values: int = 0
    orbit_radius_values: int = 0
    height_offsets: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.fov_values or self.orbit_radius_values or self.height_offsets)


EXTRA_CONTEXT_TARGETS: tuple[ResourceTarget, ...] = (
    ResourceTarget(
        chunk="chunk0",
        hash_value=0x019DBA158E707E27,
        path="[assembly:/_knt/design/interaction_prompts/interactions.template?/inspectobject_activepickup.entitytemplate].entitytype",
    ),
    ResourceTarget(
        chunk="chunk0",
        hash_value=0x01EC05B80A442A72,
        path="[assembly:/_knt/design/interaction_prompts/interactions.template?/inspectobject_passivecinematic.entitytemplate].entitytype",
    ),
    ResourceTarget(
        chunk="chunk0",
        hash_value=0x0116519F933BC452,
        path="[assembly:/_knt/design/utility/utility_dialog.template?/customcamera_conversation.entitytemplate].entitytype",
    ),
    ResourceTarget(
        chunk="chunk0",
        hash_value=0x0154DCAB1C530A2B,
        path="[assembly:/_knt/design/interaction_prompts/interactions.template?/interaction_conversation.entitytemplate].entitytype",
    ),
    ResourceTarget(
        chunk="chunk1",
        hash_value=0x0103BD78B5FDBDA2,
        path="[assembly:/_knt/design/setpieces/setpieces_gadgets.template?/setpiece_gadgetloadoutselector.entitytemplate].entitytype",
    ),
    ResourceTarget(
        chunk="chunk1",
        hash_value=0x01455CB2A82939A8,
        path="[assembly:/_knt/design/setpieces/setpieces_entryways.template?/vent_transition_vertical_enterexit.entitytemplate].entitytype",
    ),
)


def default_game_root() -> Path:
    candidate = Path(r"D:\SteamLibrary\steamapps\common\007 First Light")
    if candidate.is_dir():
        return candidate
    return Path.cwd()


def scaled_value(original: float, scale: float) -> float:
    return round(original * scale, 6)


def bin1_data_bounds(raw: bytes) -> tuple[int, int]:
    if len(raw) < 0x10:
        raise RuntimeError("resource is too small to be a BIN1 payload")

    data_size = int.from_bytes(raw[8:12], "big")
    data_start = 0x10
    data_end = data_start + data_size
    if data_end > len(raw):
        raise RuntimeError("resource BIN1 data section extends past the payload")

    return data_start, data_end


def find_patchable_float_values(
    raw: bytes,
    value_id: int,
    min_value: float,
    max_value: float,
) -> dict[int, float]:
    data_start, data_end = bin1_data_bounds(raw)
    offsets: dict[int, float] = {}
    needle = struct.pack("<I", value_id)
    search_pos = data_start

    while True:
        record_offset = raw.find(needle, search_pos, data_end)
        if record_offset < 0:
            break
        if record_offset + 0x18 > data_end:
            break

        _, _, _, data_offset = struct.unpack_from("<IIQQ", raw, record_offset)
        file_offset = data_start + data_offset
        if file_offset + 4 <= len(raw):
            current_value = struct.unpack_from("<f", raw, file_offset)[0]
            if (
                math.isfinite(current_value)
                and min_value <= current_value <= max_value
            ):
                offsets[data_offset] = current_value

        search_pos = record_offset + 1

    return offsets


def align_len(value: int, alignment: int = 8) -> int:
    remainder = value % alignment
    return value if remainder == 0 else value + (alignment - remainder)


def parse_bin1_type_names(raw: bytes) -> dict[int, str]:
    _, data_end = bin1_data_bounds(raw)
    type_names: dict[int, str] = {}
    segment_pos = data_end

    for _ in range(raw[6]):
        if segment_pos + 8 > len(raw):
            break
        segment_type, segment_size = struct.unpack_from("<II", raw, segment_pos)
        payload_start = segment_pos + 8
        payload_end = payload_start + segment_size
        if payload_end > len(raw):
            break

        if segment_type == TYPE_TYPEIDS:
            payload = raw[payload_start:payload_end]
            pos = 0
            if pos + 4 > len(payload):
                break
            offset_count = struct.unpack_from("<I", payload, pos)[0]
            pos += 4
            if pos + offset_count * 4 > len(payload):
                break
            pos += offset_count * 4
            if pos + 4 > len(payload):
                break
            type_count = struct.unpack_from("<I", payload, pos)[0]
            pos += 4
            for _ in range(type_count):
                pos = align_len(pos, 4)
                if pos + 12 > len(payload):
                    break
                type_index, _marker = struct.unpack_from("<Ii", payload, pos)
                pos += 8
                length = struct.unpack_from("<I", payload, pos)[0]
                pos += 4
                if length <= 0 or pos + length > len(payload):
                    break
                type_names[type_index] = payload[pos : pos + length - 1].decode("utf-8", "replace")
                pos += length

        segment_pos = payload_end

    return type_names


def patch_spherical_camera_height(raw: bytes, patched: bytearray, height_offset: float) -> int:
    data_start, data_end = bin1_data_bounds(raw)
    data_size = data_end - data_start
    type_names = parse_bin1_type_names(raw)
    if SPHERICAL_FRAMING_TYPE not in set(type_names.values()):
        return 0
    if 0x20 + 0x18 > data_size:
        return 0

    sub_begin, sub_end, _ = struct.unpack_from("<QQQ", raw, data_start + 0x20)
    if (
        sub_begin > sub_end
        or sub_end > data_size
        or (sub_end - sub_begin) % SUBENT_TEMP_STRIDE != 0
    ):
        return 0

    entity_count = (sub_end - sub_begin) // SUBENT_TEMP_STRIDE
    patched_arrays: set[tuple[int, int]] = set()
    count = 0

    for entity_index in range(entity_count):
        record_offset = sub_begin + entity_index * SUBENT_TEMP_STRIDE
        for array_offset in (0x30, 0x48, 0x60):
            prop_array_offset = record_offset + array_offset
            if prop_array_offset + 0x18 > data_size:
                continue
            prop_begin, prop_end, _ = struct.unpack_from("<qqq", raw, data_start + prop_array_offset)
            if prop_begin < 0 or prop_end < prop_begin or prop_end > data_size:
                continue
            if (prop_end - prop_begin) % 0x18 != 0:
                continue

            for prop_offset in range(prop_begin, prop_end, 0x18):
                _, _, type_index, data_offset = struct.unpack_from("<IIQQ", raw, data_start + prop_offset)
                if type_names.get(type_index) != SPHERICAL_FRAMING_TYPE:
                    continue
                if data_offset + 0x18 > data_size:
                    continue

                begin, end, _ = struct.unpack_from("<qqq", raw, data_start + data_offset)
                if begin < 0 or end < begin or end > data_size:
                    continue
                if (end - begin) == 0 or (end - begin) % SPHERICAL_FRAMING_RECORD_SIZE != 0:
                    continue
                if (begin, end) in patched_arrays:
                    continue
                patched_arrays.add((begin, end))

                for item_offset in range(begin, end, SPHERICAL_FRAMING_RECORD_SIZE):
                    for relative_offset in SPHERICAL_FRAMING_Z_OFFSETS:
                        value_offset = item_offset + relative_offset
                        if value_offset + 4 > data_size:
                            continue
                        current_value = struct.unpack_from("<f", raw, data_start + value_offset)[0]
                        if (
                            math.isfinite(current_value)
                            and MIN_PATCHABLE_FRAMING_HEIGHT <= current_value <= MAX_PATCHABLE_FRAMING_HEIGHT
                        ):
                            struct.pack_into(
                                "<f",
                                patched,
                                data_start + value_offset,
                                round(current_value + height_offset, 6),
                            )
                            count += 1

    return count


def patch_float_offsets(
    patched: bytearray,
    offsets: dict[int, float],
    transform,
) -> int:
    for data_offset, current_value in offsets.items():
        struct.pack_into("<f", patched, 0x10 + data_offset, transform(current_value))
    return len(offsets)


def patch_resource(
    raw: bytes,
    target: ResourceTarget,
    fov_scale: float,
    orbit_scale: float,
    height_offset: float,
) -> tuple[bytes, ResourcePatchStats]:
    patched = bytearray(raw)
    fov_count = 0
    orbit_count = 0
    height_count = 0

    if fov_scale != 1.0:
        fov_offsets = find_patchable_float_values(
            raw,
            FOV_OVERRIDE_VALUE_ID,
            MIN_PATCHABLE_FOV,
            MAX_PATCHABLE_FOV,
        )
        fov_count = patch_float_offsets(
            patched,
            fov_offsets,
            lambda current_value: scaled_value(current_value, fov_scale),
        )

    if orbit_scale != 1.0:
        orbit_offsets = find_patchable_float_values(
            raw,
            ORBIT_RADIUS_VALUE_ID,
            MIN_PATCHABLE_ORBIT_RADIUS,
            MAX_PATCHABLE_ORBIT_RADIUS,
        )
        orbit_count = patch_float_offsets(
            patched,
            orbit_offsets,
            lambda current_value: scaled_value(current_value, orbit_scale),
        )

    if height_offset != 0.0:
        height_count = patch_spherical_camera_height(raw, patched, height_offset)

    return bytes(patched), ResourcePatchStats(
        fov_values=fov_count,
        orbit_radius_values=orbit_count,
        height_offsets=height_count,
    )


def patch_packagedefinition(raw: bytes) -> bytes:
    header, plain = firstlight_config_crypt.decrypt_container(raw)
    patched_plain, count = re.subn(rb"patchlevel=\d+", f"patchlevel={PATCHLEVEL}".encode("ascii"), plain)

    if count == 0:
        raise RuntimeError("packagedefinition.txt did not contain any patchlevel entries")

    return firstlight_config_crypt.encrypt_container(patched_plain, header)


def find_chunk(hash_value: int, rpkgs: dict[str, bond_rpkg.Rpkg]) -> str | None:
    for chunk, rpkg in rpkgs.items():
        if hash_value in rpkg.by_hash:
            return chunk
    return None


def is_gameplay_camera_path(path: str) -> bool:
    path_lower = path.lower()

    if SHARED_GAMEPLAY_CAMERA_MARKER in path_lower:
        return not any(term in path_lower for term in SHARED_CAMERA_EXCLUDED_TERMS)

    if any(term in path_lower for term in VEHICLE_CAMERA_TERMS):
        if any(term in path_lower for term in VEHICLE_CAMERA_EXCLUDED_TERMS):
            return False
        return (
            "/_knt/scenes/missions/" in path_lower
            or "/_knt/scenes/locations/" in path_lower
            or "/_knt/scenes/globalbricks/" in path_lower
            or "/_knt/design/setpieces/" in path_lower
            or "/_knt/scenes/gyms/vehicle_templates_gym" in path_lower
            or "/_knt/scenes/gyms/boats_templates_gym" in path_lower
        )

    return False


def camera_targets(rpkgs: dict[str, bond_rpkg.Rpkg]) -> list[ResourceTarget]:
    if not HASH_PATHS.is_file():
        raise RuntimeError(f"Missing hash path map {HASH_PATHS}")

    targets: list[ResourceTarget] = []
    path_rows = json.loads(HASH_PATHS.read_text(encoding="utf-8"))
    for row in path_rows:
        path = row.get("path", "")
        if not is_gameplay_camera_path(path):
            continue

        hash_value = int(row["hash"], 16)
        chunk = find_chunk(hash_value, rpkgs)
        if chunk is None:
            continue

        targets.append(ResourceTarget(chunk=chunk, hash_value=hash_value, path=path))

    return targets


def build_targets(rpkgs: dict[str, bond_rpkg.Rpkg]) -> list[ResourceTarget]:
    by_hash: dict[int, ResourceTarget] = {}

    for target in camera_targets(rpkgs):
        by_hash[target.hash_value] = target

    for target in EXTRA_CONTEXT_TARGETS:
        by_hash[target.hash_value] = target

    return sorted(by_hash.values(), key=lambda item: (item.chunk, item.hash_value))


def build_output(
    game_root: Path,
    output_dir: Path,
    fov_scale: float,
    patch_number: int,
    orbit_scale: float = 1.0,
    height_offset: float = 0.0,
    include_packagedefinition: bool = True,
    copy_readme: bool = True,
) -> ResourcePatchStats:
    runtime = game_root / "Runtime"
    if not (runtime / "chunk0.rpkg").is_file():
        raise RuntimeError(f"Missing {runtime / 'chunk0.rpkg'}")
    if not (runtime / "chunk1.rpkg").is_file():
        raise RuntimeError(f"Missing {runtime / 'chunk1.rpkg'}")
    if not (runtime / "packagedefinition.txt").is_file():
        raise RuntimeError(f"Missing {runtime / 'packagedefinition.txt'}")

    rpkgs = {
        "chunk0": bond_rpkg.Rpkg(runtime / "chunk0.rpkg"),
        "chunk1": bond_rpkg.Rpkg(runtime / "chunk1.rpkg"),
    }

    work_dir = output_dir / "_build"
    runtime_out = output_dir / "Runtime"
    chunk_work = work_dir / "content"

    if output_dir.exists():
        shutil.rmtree(output_dir)

    runtime_out.mkdir(parents=True, exist_ok=True)
    chunk_work.mkdir(parents=True, exist_ok=True)

    replacements_by_chunk: dict[str, list[tuple[int, Path]]] = {"chunk0": [], "chunk1": []}
    patched_count = 0
    total_stats = ResourcePatchStats()

    for target in build_targets(rpkgs):
        rpkg = rpkgs[target.chunk]
        if target.hash_value not in rpkg.by_hash:
            raise RuntimeError(f"{target.hash_value:016X} is not present in {target.chunk}.rpkg")

        original = rpkg.extract(target.hash_value)
        try:
            patched, stats = patch_resource(original, target, fov_scale, orbit_scale, height_offset)
        except RuntimeError:
            if is_gameplay_camera_path(target.path):
                continue
            raise
        if not stats.changed:
            continue

        replacement_path = chunk_work / target.chunk / f"{target.hash_value:016X}.TEMP"
        replacement_path.parent.mkdir(parents=True, exist_ok=True)
        replacement_path.write_bytes(patched)
        replacements_by_chunk[target.chunk].append((target.hash_value, replacement_path))
        patched_count += 1
        total_stats = ResourcePatchStats(
            fov_values=total_stats.fov_values + stats.fov_values,
            orbit_radius_values=total_stats.orbit_radius_values + stats.orbit_radius_values,
            height_offsets=total_stats.height_offsets + stats.height_offsets,
        )

    if patched_count == 0:
        raise RuntimeError("No resources were patched")

    for chunk, replacements in replacements_by_chunk.items():
        if not replacements:
            continue
        out_name = runtime_out / f"{chunk}patch{patch_number}.rpkg"
        bond_rpkg.build_patch(runtime, chunk, out_name, replacements, patch_entries=[])

    if include_packagedefinition:
        patched_packagedef = patch_packagedefinition((runtime / "packagedefinition.txt").read_bytes())
        (runtime_out / "packagedefinition.txt").write_bytes(patched_packagedef)

    if copy_readme and README_SOURCE.is_file():
        shutil.copy2(README_SOURCE, output_dir / "README.txt")

    shutil.rmtree(work_dir, ignore_errors=True)
    print(
        f"Patched {patched_count} resources / "
        f"{total_stats.fov_values} FOV values / "
        f"{total_stats.orbit_radius_values} orbit radii / "
        f"{total_stats.height_offsets} height offsets"
    )
    return total_stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", type=Path, default=default_game_root())
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "dist" / PACKAGE_NAME)
    parser.add_argument("--scale", "--fov-scale", dest="fov_scale", type=float, default=PATCH_SCALE)
    parser.add_argument("--orbit-scale", type=float, default=1.0)
    parser.add_argument("--height-offset", type=float, default=0.0)
    parser.add_argument("--patch-number", type=int, default=PATCH_NUMBER)
    parser.add_argument("--rpkg-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not 0.4 <= args.fov_scale <= 3.0:
        raise SystemExit("--scale/--fov-scale must be between 0.4 and 3.0")
    if not 0.4 <= args.orbit_scale <= 1.6:
        raise SystemExit("--orbit-scale must be between 0.4 and 1.6")
    if not -0.75 <= args.height_offset <= 0.75:
        raise SystemExit("--height-offset must be between -0.75 and 0.75")
    if args.fov_scale == 1.0 and args.orbit_scale == 1.0 and args.height_offset == 0.0:
        raise SystemExit("At least one camera value must be changed")
    if not 0 <= args.patch_number <= 255:
        raise SystemExit("--patch-number must fit in one byte (0-255)")

    build_output(
        args.game_root.resolve(),
        args.output_dir.resolve(),
        args.fov_scale,
        args.patch_number,
        orbit_scale=args.orbit_scale,
        height_offset=args.height_offset,
        include_packagedefinition=not args.rpkg_only,
        copy_readme=not args.rpkg_only,
    )
    print(f"Built camera/FOV drop-in package at {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()

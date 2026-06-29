"""Programmatic FOV rebuild API for the GUI launcher."""

from __future__ import annotations

import io
import re
import runpy
import shutil
import tempfile
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path


REBUILDER_ROOT = Path(__file__).resolve().parent
PACKAGING_DIR = REBUILDER_ROOT / "packaging"
PATCH_NUMBER = 204

DEFAULT_TARGET_FOV = 40.0
REFERENCE_FOV_SCALE = 1.40
FOV_LABEL_SCALE_BASE = 90.0 / REFERENCE_FOV_SCALE

_BUILDER = runpy.run_path(str(PACKAGING_DIR / "007fl_build_less_zoom_dropin.py"))


@dataclass(frozen=True)
class RebuildResult:
    runtime: Path
    fov: float
    distance_percent: float
    height: float
    patched_resources: int
    fov_values: int
    orbit_radii: int
    height_offsets: int
    installed_files: tuple[str, ...]
    removed_patch_files: tuple[str, ...] = ()


class RebuildError(Exception):
    """Raised when validation or patching fails."""


def resolve_runtime(folder: Path) -> Path:
    folder = folder.resolve()
    if (folder / "chunk0.rpkg").is_file() and (folder / "chunk1.rpkg").is_file():
        return folder
    runtime = folder / "Runtime"
    if (runtime / "chunk0.rpkg").is_file() and (runtime / "chunk1.rpkg").is_file():
        return runtime
    raise RebuildError(
        "Could not find a valid Runtime folder. Select the game install folder "
        "or its Runtime subfolder (must contain chunk0.rpkg and chunk1.rpkg)."
    )


def validate_runtime(runtime: Path) -> None:
    required = ("chunk0.rpkg", "chunk1.rpkg", "packagedefinition.txt")
    missing = [name for name in required if not (runtime / name).is_file()]
    if missing:
        raise RebuildError(f"Missing required files in Runtime: {', '.join(missing)}")


def target_fov_to_scale(target_fov: float) -> float:
    if abs(target_fov - DEFAULT_TARGET_FOV) < 0.0001:
        return 1.0
    return round(target_fov / FOV_LABEL_SCALE_BASE, 6)


def distance_to_scale(distance_percent: float) -> float:
    return round(1.0 + distance_percent / 100.0, 6)


def copy_runtime_files(build_runtime: Path, runtime: Path) -> list[str]:
    patch_names = ("chunk0patch204.rpkg", "chunk1patch204.rpkg")
    copied: list[str] = []

    for name in patch_names:
        target = runtime / name
        if target.exists():
            target.unlink()

    for name in patch_names:
        source = build_runtime / name
        if source.is_file():
            shutil.copy2(source, runtime / name)
            copied.append(name)

    packagedefinition = build_runtime / "packagedefinition.txt"
    if not packagedefinition.is_file():
        raise RebuildError(f"Builder did not create {packagedefinition}")
    shutil.copy2(packagedefinition, runtime / "packagedefinition.txt")
    copied.append("packagedefinition.txt")
    return copied


def remove_patches(runtime: Path) -> list[str]:
    validate_runtime(runtime)
    removed: list[str] = []
    for name in ("chunk0patch204.rpkg", "chunk1patch204.rpkg"):
        target = runtime / name
        if target.exists():
            target.unlink()
            removed.append(name)
    return removed


def rebuild_and_install(
    game_or_runtime: Path,
    target_fov: float,
    distance_percent: float,
    height: float,
) -> RebuildResult:
    if not 30.0 <= target_fov <= 120.0:
        raise RebuildError("FOV must be between 30 and 120.")
    if not -60.0 <= distance_percent <= 60.0:
        raise RebuildError("Camera distance must be between -60 and 60 percent.")
    if not -0.75 <= height <= 0.75:
        raise RebuildError("Camera height must be between -0.75 and 0.75.")

    runtime = resolve_runtime(game_or_runtime)
    validate_runtime(runtime)
    game_root = runtime.parent

    fov_scale = target_fov_to_scale(target_fov)
    orbit_scale = distance_to_scale(distance_percent)
    height_offset = round(height, 6)

    if fov_scale == 1.0 and orbit_scale == 1.0 and height_offset == 0.0:
        removed = remove_patches(runtime)
        return RebuildResult(
            runtime=runtime,
            fov=target_fov,
            distance_percent=distance_percent,
            height=height,
            patched_resources=0,
            fov_values=0,
            orbit_radii=0,
            height_offsets=0,
            installed_files=(),
            removed_patch_files=tuple(removed),
        )

    output_dir = Path(tempfile.gettempdir()) / "007FL_Better_Camera_Main_GUI_Build"
    build_log = io.StringIO()
    with redirect_stdout(build_log):
        stats = _BUILDER["build_output"](
            game_root,
            output_dir,
            fov_scale,
            PATCH_NUMBER,
            orbit_scale=orbit_scale,
            height_offset=height_offset,
            include_packagedefinition=True,
            copy_readme=False,
        )
    copied = copy_runtime_files(output_dir / "Runtime", runtime)

    patched_count = 0
    match = re.search(r"Patched (\d+) resources", build_log.getvalue())
    if match:
        patched_count = int(match.group(1))

    return RebuildResult(
        runtime=runtime,
        fov=target_fov,
        distance_percent=distance_percent,
        height=height,
        patched_resources=patched_count,
        fov_values=stats.fov_values,
        orbit_radii=stats.orbit_radius_values,
        height_offsets=stats.height_offsets,
        installed_files=tuple(copied),
    )


def ensure_lz4() -> None:
    try:
        import lz4.block  # noqa: F401
    except ImportError as exc:
        raise RebuildError(
            "Missing Python package: lz4\n"
            "Install it with: py -3 -m pip install -r requirements.txt"
        ) from exc

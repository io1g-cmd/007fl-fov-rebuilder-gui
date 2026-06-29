#!/usr/bin/env python3
"""
Minimal RPKG v2 helper for 007 First Light.

This intentionally handles only the package layout seen in the launch build:
9-byte RPKGv2 header, 0x14-byte hash headers, and 0x14-byte resource
metadata records followed by the original reference table bytes.
"""

from __future__ import annotations

import argparse
import re
import struct
from dataclasses import dataclass
from pathlib import Path

try:
    import lz4.block
except ImportError as exc:  # pragma: no cover - environment guard
    raise SystemExit("Missing Python package: lz4") from exc


XOR_KEY = bytes([0xDC, 0x45, 0xA6, 0x9C, 0xD3, 0x72, 0x4C, 0xAB])
MAGIC_V2 = b"2KPR"


@dataclass(frozen=True)
class Entry:
    hash_value: int
    data_offset: int
    data_size_field: int
    resource_type: str
    reference_table: bytes
    reference_table_dummy: int
    size_final: int
    size_in_memory: int
    size_in_video_memory: int

    @property
    def compressed_size(self) -> int:
        return self.data_size_field & 0x3FFFFFFF

    @property
    def xored(self) -> bool:
        return bool(self.data_size_field & 0x80000000)

    @property
    def compressed(self) -> bool:
        return self.compressed_size != 0

    @property
    def stored_size(self) -> int:
        return self.compressed_size if self.compressed else self.size_final


class Rpkg:
    def __init__(self, path: Path):
        self.path = path
        with path.open("rb") as f:
            magic = f.read(4)
            if magic != MAGIC_V2:
                raise ValueError(f"{path} is not an RPKGv2 file")

            self.v2_header = f.read(9)
            self.hash_count, self.hash_table_size, self.resource_table_size = struct.unpack("<III", f.read(12))

            patch_count_pos = f.tell()
            patch_count_data = f.read(4)
            if len(patch_count_data) != 4:
                raise ValueError(f"Unexpected end of file in {path}")
            patch_count = struct.unpack("<I", patch_count_data)[0]

            # Patch packages have an extra patch-count u32 after the main header,
            # followed by zero or more deletion hashes. Detect them using the
            # same table-offset invariant that rpkg-cli uses.
            self.is_patch = False
            self.patch_entries: list[int] = []
            expected_patch_data_offset = 0x1D + patch_count * 8 + self.hash_table_size + self.resource_table_size

            if path.stat().st_size > (0x1D + patch_count * 8 + 8):
                f.seek(0x1D + patch_count * 8 + 8)
                data_offset_bytes = f.read(8)
                if len(data_offset_bytes) == 8:
                    first_data_offset = struct.unpack("<Q", data_offset_bytes)[0]
                    if first_data_offset == expected_patch_data_offset:
                        self.is_patch = True

            if self.is_patch:
                f.seek(patch_count_pos + 4)
                self.patch_entries = [struct.unpack("<Q", f.read(8))[0] for _ in range(patch_count)]
                hash_table_offset = f.tell()
            else:
                f.seek(patch_count_pos)
                hash_table_offset = f.tell()

            f.seek(hash_table_offset)
            hash_headers = [struct.unpack("<QQI", f.read(20)) for _ in range(self.hash_count)]

            resource_table_offset = hash_table_offset + self.hash_table_size
            f.seek(resource_table_offset)

            entries: list[Entry] = []
            for hash_value, data_offset, data_size_field in hash_headers:
                raw_type = f.read(4)
                if len(raw_type) != 4:
                    raise ValueError(f"Unexpected end of resource table in {path}")

                reference_table_size, size_final, size_in_memory, size_in_video_memory = struct.unpack("<IIII", f.read(16))
                reference_table = f.read(reference_table_size)
                entries.append(
                    Entry(
                        hash_value=hash_value,
                        data_offset=data_offset,
                        data_size_field=data_size_field,
                        resource_type=raw_type[::-1].decode("ascii", errors="replace"),
                        reference_table=reference_table,
                        reference_table_dummy=0,
                        size_final=size_final,
                        size_in_memory=size_in_memory,
                        size_in_video_memory=size_in_video_memory,
                    )
                )

            self.entries = entries
            self.by_hash = {entry.hash_value: entry for entry in entries}

    def extract(self, hash_value: int) -> bytes:
        entry = self.by_hash[hash_value]
        with self.path.open("rb") as f:
            f.seek(entry.data_offset)
            payload = bytearray(f.read(entry.stored_size))

        if entry.xored:
            for i in range(len(payload)):
                payload[i] ^= XOR_KEY[i % len(XOR_KEY)]

        data = bytes(payload)
        if entry.compressed:
            data = lz4.block.decompress(data, uncompressed_size=entry.size_final)

        return data


def parse_hash(text: str) -> int:
    stem = text.split(".", 1)[0]
    if stem.lower().startswith("0x"):
        stem = stem[2:]
    return int(stem, 16)


def find_rpkg(runtime: Path, chunk: str) -> Path:
    path = runtime / f"{chunk}.rpkg"
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def xor_payload(data: bytes) -> bytes:
    payload = bytearray(data)
    for i in range(len(payload)):
        payload[i] ^= XOR_KEY[i % len(XOR_KEY)]
    return bytes(payload)


def build_patch(runtime: Path, chunk: str, output: Path, replacements: list[tuple[int, Path]], patch_entries: list[int]) -> None:
    base = Rpkg(find_rpkg(runtime, chunk))
    output.parent.mkdir(parents=True, exist_ok=True)

    replacement_entries: list[tuple[Entry, bytes, int]] = []
    for hash_value, file_path in sorted(replacements, key=lambda item: item[0]):
        if hash_value not in base.by_hash:
            raise KeyError(f"{hash_value:016X} is not present in {base.path.name}")

        original = base.by_hash[hash_value]
        raw = file_path.read_bytes()

        # Match the original package's compression/XOR convention for this
        # resource. Some streamed resources, notably GFXV videos, are stored
        # uncompressed in base packages and should remain raw in patches.
        if original.compressed:
            payload = lz4.block.compress(raw, store_size=False)
            size_field = len(payload)
        else:
            payload = raw
            size_field = 0

        stored = xor_payload(payload) if original.xored else payload
        if original.xored:
            size_field |= 0x80000000

        rebuilt = Entry(
            hash_value=original.hash_value,
            data_offset=0,
            data_size_field=size_field,
            resource_type=original.resource_type,
            reference_table=original.reference_table,
            reference_table_dummy=0,
            size_final=len(raw),
            size_in_memory=len(raw),
            size_in_video_memory=original.size_in_video_memory,
        )
        replacement_entries.append((rebuilt, stored, len(raw)))

    hash_table_size = len(replacement_entries) * 0x14
    resource_table_size = sum(0x14 + len(entry.reference_table) for entry, _, _ in replacement_entries)
    patch_count = len(patch_entries)
    data_offset = 0x1D + patch_count * 8 + hash_table_size + resource_table_size

    v2_header = bytearray(base.v2_header)
    patch_match = re.search(r"patch(\d+)", output.name, flags=re.IGNORECASE)
    if patch_match:
        patch_number = int(patch_match.group(1))
        if not 0 <= patch_number <= 0xFF:
            raise ValueError(f"RPKGv2 patch number must fit in one byte: {patch_number}")
        v2_header[6] = patch_number

    hash_table = bytearray()
    resource_table = bytearray()
    payloads = bytearray()

    current_offset = data_offset
    for entry, stored, _ in replacement_entries:
        hash_table += struct.pack("<QQI", entry.hash_value, current_offset, entry.data_size_field)
        current_offset += len(stored)

        resource_table += entry.resource_type.encode("ascii")[::-1]
        resource_table += struct.pack(
            "<IIII",
            len(entry.reference_table),
            entry.size_final,
            entry.size_in_memory,
            entry.size_in_video_memory,
        )
        resource_table += entry.reference_table
        payloads += stored

    with output.open("wb") as f:
        f.write(MAGIC_V2)
        f.write(bytes(v2_header))
        f.write(struct.pack("<III", len(replacement_entries), hash_table_size, resource_table_size))
        f.write(struct.pack("<I", patch_count))
        for deleted_hash in patch_entries:
            f.write(struct.pack("<Q", deleted_hash))
        f.write(hash_table)
        f.write(resource_table)
        f.write(payloads)


def cmd_info(args: argparse.Namespace) -> None:
    rpkg = Rpkg(find_rpkg(args.runtime, args.chunk))
    for hash_text in args.hashes:
        hash_value = parse_hash(hash_text)
        entry = rpkg.by_hash[hash_value]
        print(
            f"{entry.hash_value:016X}.{entry.resource_type} "
            f"offset=0x{entry.data_offset:X} stored={entry.stored_size} final={entry.size_final} "
            f"refs={len(entry.reference_table)} compressed={entry.compressed} xored={entry.xored}"
        )


def cmd_extract(args: argparse.Namespace) -> None:
    rpkg = Rpkg(find_rpkg(args.runtime, args.chunk))
    args.output.mkdir(parents=True, exist_ok=True)
    for hash_text in args.hashes:
        hash_value = parse_hash(hash_text)
        entry = rpkg.by_hash[hash_value]
        out_path = args.output / f"{entry.hash_value:016X}.{entry.resource_type}"
        out_path.write_bytes(rpkg.extract(hash_value))
        print(out_path)


def cmd_make_patch(args: argparse.Namespace) -> None:
    replacements: list[tuple[int, Path]] = []
    for item in args.replace:
        if "=" not in item:
            raise ValueError(f"Replacement must be HASH=PATH, got {item!r}")
        hash_text, path_text = item.split("=", 1)
        replacements.append((parse_hash(hash_text), Path(path_text)))

    patch_entries = [parse_hash(value) for value in args.delete]
    build_patch(args.runtime, args.chunk, args.output, replacements, patch_entries)
    print(args.output)


def main() -> None:
    parser = argparse.ArgumentParser(description="007 First Light RPKG helper")
    parser.add_argument("--runtime", type=Path, default=Path(r"D:\SteamLibrary\steamapps\common\007 First Light\Runtime"))
    parser.add_argument("--chunk", default="chunk0")
    subparsers = parser.add_subparsers(dest="command", required=True)

    info = subparsers.add_parser("info")
    info.add_argument("hashes", nargs="+")
    info.set_defaults(func=cmd_info)

    extract = subparsers.add_parser("extract")
    extract.add_argument("hashes", nargs="+")
    extract.add_argument("--output", type=Path, required=True)
    extract.set_defaults(func=cmd_extract)

    make_patch = subparsers.add_parser("make-patch")
    make_patch.add_argument("--output", type=Path, required=True)
    make_patch.add_argument("--replace", action="append", default=[])
    make_patch.add_argument("--delete", action="append", default=[])
    make_patch.set_defaults(func=cmd_make_patch)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Decrypt and rebuild 007 First Light encrypted config files.

The launch build uses the same XTEA-style container for Retail/thumbs.dat and
Runtime/packagedefinition.txt, but with a First Light-specific header and key.
"""

from __future__ import annotations

import argparse
import binascii
import re
import struct
from pathlib import Path


MASK = 0xFFFFFFFF
DELTA = 0x9E3779B9
ROUNDS = 32

FIRST_LIGHT_HEADER = bytes.fromhex("B7E2EA00545B6B8711BD6FE84D6AD4BF")
FIRST_LIGHT_KEY = (0x71482CF0, 0x5FDC4B9F, 0x86CE569D, 0x0509FC1E)


def _mix(value: int) -> int:
    return ((((value << 4) & MASK) ^ (value >> 5)) + value) & MASK


def _decrypt_block(block: bytes, key: tuple[int, int, int, int]) -> bytes:
    v0, v1 = struct.unpack("<II", block)
    total = (DELTA * ROUNDS) & MASK

    for _ in range(ROUNDS):
        v1 = (v1 - (_mix(v0) ^ ((total + key[(total >> 11) & 3]) & MASK))) & MASK
        total = (total - DELTA) & MASK
        v0 = (v0 - (_mix(v1) ^ ((total + key[total & 3]) & MASK))) & MASK

    return struct.pack("<II", v0, v1)


def _encrypt_block(block: bytes, key: tuple[int, int, int, int]) -> bytes:
    v0, v1 = struct.unpack("<II", block)
    total = 0

    for _ in range(ROUNDS):
        v0 = (v0 + (_mix(v1) ^ ((total + key[total & 3]) & MASK))) & MASK
        total = (total + DELTA) & MASK
        v1 = (v1 + (_mix(v0) ^ ((total + key[(total >> 11) & 3]) & MASK))) & MASK

    return struct.pack("<II", v0, v1)


def decrypt_container(raw: bytes) -> tuple[bytes, bytes]:
    if len(raw) < 28 or (len(raw) - 20) % 8:
        raise ValueError("Input is not a valid First Light encrypted config container")

    header = raw[:16]
    expected_crc = struct.unpack("<I", raw[16:20])[0]
    encrypted = raw[20:]

    plain_padded = b"".join(
        _decrypt_block(encrypted[i : i + 8], FIRST_LIGHT_KEY)
        for i in range(0, len(encrypted), 8)
    )
    plain = plain_padded.rstrip(b"\0")
    actual_crc = binascii.crc32(plain) & MASK
    if actual_crc != expected_crc:
        raise ValueError(f"CRC mismatch: expected {expected_crc:08X}, got {actual_crc:08X}")

    return header, plain


def encrypt_container(plain: bytes, header: bytes = FIRST_LIGHT_HEADER) -> bytes:
    if len(header) != 16:
        raise ValueError("Header must be exactly 16 bytes")

    padding = (-len(plain)) % 8
    plain_padded = plain + (b"\0" * padding)
    encrypted = b"".join(
        _encrypt_block(plain_padded[i : i + 8], FIRST_LIGHT_KEY)
        for i in range(0, len(plain_padded), 8)
    )
    crc = binascii.crc32(plain) & MASK
    return header + struct.pack("<I", crc) + encrypted


def replace_scene_file(plain: bytes, scene: str) -> bytes:
    replacement = f"SCENE_FILE={scene}".encode("utf-8")
    return replace_config_line(plain, b"SCENE_FILE", replacement)


def replace_config_line(plain: bytes, key: bytes, replacement: bytes) -> bytes:
    lines = plain.splitlines(keepends=True)
    prefix = key + b"="

    for index, line in enumerate(lines):
        content = line.rstrip(b"\r\n")
        ending = line[len(content) :]
        if content.startswith(prefix):
            lines[index] = replacement + ending
            return b"".join(lines)

    ending = b"\r\n" if b"\r\n" in plain else b"\n"
    if plain and not plain.endswith((b"\n", b"\r")):
        plain += ending
    return plain + replacement + ending


def set_config_keys(plain: bytes, assignments: list[str]) -> bytes:
    for assignment in assignments:
        if "=" not in assignment:
            raise ValueError(f"Assignment must be KEY=VALUE: {assignment}")

        key_text, value = assignment.split("=", 1)
        if not key_text:
            raise ValueError("Config key cannot be empty")

        key = key_text.encode("utf-8")
        replacement = f"{key_text}={value}".encode("utf-8")
        plain = replace_config_line(plain, key, replacement)

    return plain


def set_config_keys_in_section(plain: bytes, section: str, assignments: list[str]) -> bytes:
    section_header = f"[{section}]".encode("utf-8").lower()
    lines = plain.splitlines(keepends=True)
    values: dict[bytes, bytes] = {}

    for assignment in assignments:
        if "=" not in assignment:
            raise ValueError(f"Assignment must be KEY=VALUE: {assignment}")

        key_text, value = assignment.split("=", 1)
        if not key_text:
            raise ValueError("Config key cannot be empty")
        values[key_text.encode("utf-8")] = f"{key_text}={value}".encode("utf-8")

    start = None
    end = len(lines)
    for index, line in enumerate(lines):
        content = line.strip().lower()
        if content == section_header:
            start = index
            continue
        if start is not None and index > start and content.startswith(b"[") and content.endswith(b"]"):
            end = index
            break

    if start is None:
        ending = b"\r\n" if b"\r\n" in plain else b"\n"
        if lines and not lines[-1].endswith((b"\n", b"\r")):
            lines[-1] += ending
        lines.append(f"[{section}]".encode("utf-8") + ending)
        start = len(lines) - 1
        end = len(lines)

    present: set[bytes] = set()
    for index in range(start + 1, end):
        content = lines[index].rstrip(b"\r\n")
        ending = lines[index][len(content) :]
        for key, replacement in values.items():
            if content.startswith(key + b"="):
                lines[index] = replacement + ending
                present.add(key)

    ending = b"\r\n" if b"\r\n" in plain else b"\n"
    insertions = [values[key] + ending for key in values if key not in present]
    if insertions:
        lines[end:end] = insertions

    return b"".join(lines)


def cmd_decrypt(args: argparse.Namespace) -> None:
    _, plain = decrypt_container(args.input.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(plain)


def cmd_encrypt(args: argparse.Namespace) -> None:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encrypt_container(args.input.read_bytes()))


def cmd_patch_scene(args: argparse.Namespace) -> None:
    header, plain = decrypt_container(args.input.read_bytes())
    patched = replace_scene_file(plain, args.scene)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encrypt_container(patched, header))

    scene_line = next(
        line.decode("utf-8", errors="replace")
        for line in patched.splitlines()
        if line.startswith(b"SCENE_FILE=")
    )
    print(scene_line)


def cmd_set(args: argparse.Namespace) -> None:
    header, plain = decrypt_container(args.input.read_bytes())
    patched = set_config_keys(plain, args.set)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encrypt_container(patched, header))

    keys = {assignment.split("=", 1)[0].encode("utf-8") for assignment in args.set}
    for line in patched.splitlines():
        if any(line.startswith(key + b"=") for key in keys):
            print(line.decode("utf-8", errors="replace"))


def cmd_set_section(args: argparse.Namespace) -> None:
    header, plain = decrypt_container(args.input.read_bytes())
    patched = set_config_keys_in_section(plain, args.section, args.set)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encrypt_container(patched, header))

    keys = {assignment.split("=", 1)[0].encode("utf-8") for assignment in args.set}
    in_section = False
    for line in patched.splitlines():
        stripped = line.strip()
        if stripped.lower() == f"[{args.section}]".encode("utf-8").lower():
            in_section = True
            print(line.decode("utf-8", errors="replace"))
            continue
        if in_section and stripped.startswith(b"[") and stripped.endswith(b"]"):
            break
        if in_section and any(line.startswith(key + b"=") for key in keys):
            print(line.decode("utf-8", errors="replace"))


def cmd_patchlevel(args: argparse.Namespace) -> None:
    header, plain = decrypt_container(args.input.read_bytes())

    if args.partition:
        partition_pattern = (
            rb"(@partition[^\r\n]*\bname="
            + re.escape(args.partition.encode("ascii"))
            + rb"\b[^\r\n]*\bpatchlevel=)\d+"
        )
        patched, count = re.subn(partition_pattern, rb"\g<1>" + str(args.level).encode("ascii"), plain)
    else:
        patched, count = re.subn(rb"patchlevel=\d+", f"patchlevel={args.level}".encode("ascii"), plain)

    if count == 0:
        raise ValueError("No patchlevel entries found")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encrypt_container(patched, header))
    target = f"partition {args.partition}" if args.partition else "all partitions"
    print(f"patched {count} patchlevel entries to {args.level} in {target}")


def cmd_info(args: argparse.Namespace) -> None:
    header, plain = decrypt_container(args.input.read_bytes())
    print(f"header={header.hex().upper()}")
    print(f"plain_size={len(plain)}")
    print(f"crc32={binascii.crc32(plain) & MASK:08X}")
    for line in plain.splitlines():
        if line.startswith(b"SCENE_FILE="):
            print(line.decode("utf-8", errors="replace"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    decrypt = subparsers.add_parser("decrypt", help="write decrypted plaintext")
    decrypt.add_argument("input", type=Path)
    decrypt.add_argument("output", type=Path)
    decrypt.set_defaults(func=cmd_decrypt)

    encrypt = subparsers.add_parser("encrypt", help="write encrypted container from plaintext")
    encrypt.add_argument("input", type=Path)
    encrypt.add_argument("output", type=Path)
    encrypt.set_defaults(func=cmd_encrypt)

    patch_scene = subparsers.add_parser("patch-scene", help="replace SCENE_FILE and write encrypted output")
    patch_scene.add_argument("input", type=Path)
    patch_scene.add_argument("output", type=Path)
    patch_scene.add_argument("--scene", required=True)
    patch_scene.set_defaults(func=cmd_patch_scene)

    set_parser = subparsers.add_parser("set", help="set one or more KEY=VALUE config lines")
    set_parser.add_argument("input", type=Path)
    set_parser.add_argument("output", type=Path)
    set_parser.add_argument("--set", action="append", required=True, metavar="KEY=VALUE")
    set_parser.set_defaults(func=cmd_set)

    set_section = subparsers.add_parser("set-section", help="set KEY=VALUE lines inside an INI section")
    set_section.add_argument("input", type=Path)
    set_section.add_argument("output", type=Path)
    set_section.add_argument("--section", required=True)
    set_section.add_argument("--set", action="append", required=True, metavar="KEY=VALUE")
    set_section.set_defaults(func=cmd_set_section)

    patchlevel = subparsers.add_parser("patchlevel", help="replace every packagedefinition patchlevel value")
    patchlevel.add_argument("input", type=Path)
    patchlevel.add_argument("output", type=Path)
    patchlevel.add_argument("--level", type=int, required=True)
    patchlevel.add_argument("--partition", help="limit patchlevel change to one @partition name")
    patchlevel.set_defaults(func=cmd_patchlevel)

    info = subparsers.add_parser("info", help="print basic decrypted metadata")
    info.add_argument("input", type=Path)
    info.set_defaults(func=cmd_info)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

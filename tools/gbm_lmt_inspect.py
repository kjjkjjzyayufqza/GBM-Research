#!/usr/bin/env python3
"""Inspect Gundam Breaker Mobile LMT v68 motion lists.

The layout is based on GBM's ``rMotionList::load`` and
``uModel::setupMotionParam`` implementations in ``libGUNS.so``. Relative
offsets are reported as file offsets because the runtime loader relocates them
against the start of the LMT allocation.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
from collections import Counter
from pathlib import Path
from typing import Any

from gbm_mod_inspect import parse_header


LMT_MAGIC = b"LMT\x00"
LMT_VERSION = 68
MOTION_RECORD_SIZE = 0x60
TRACK_RECORD_SIZE = 0x30

CODEC_NAMES = {
    1: "CONSTANT_1",
    2: "CONSTANT_2",
    3: "UNCOMPRESSED_TIMED_FLOAT4",
    4: "LINEARKEY_16",
    5: "LINEARKEY_8",
    6: "POLAR3KEY",
    7: "POLAR3KEY_32",
    8: "UNCOMPRESSED_FLOAT3",
    9: "UNCOMPRESSED_FLOAT4",
    10: "DIRECT_OR_RESERVED",
    11: "QUNIAXIAL_32_VARIANT_11",
    12: "QUNIAXIAL_32_VARIANT_12",
    13: "QUNIAXIAL_32_VARIANT_13",
    14: "QUATKEY_48",
    15: "QUATKEY_40",
}

USAGE_NAMES = {
    0: "JOINT_ROTATION",
    1: "JOINT_TRANSLATION",
    2: "JOINT_SCALE_OR_AUX",
    3: "ROOT_ROTATION",
    4: "ROOT_TRANSLATION",
    5: "JOINT_AUX_NO_SETUP",
}

PACKED_CODECS = {4, 5, 6, 7, 11, 12, 13}
QUATERNION_CODECS = {2, 6, 7, 11, 12, 13}


def checked_range(data: bytes, offset: int, size: int, label: str) -> None:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise ValueError(
            f"{label} range 0x{offset:x}..0x{offset + size:x} "
            f"exceeds file size 0x{len(data):x}"
        )


def finite_float(value: float) -> float | None:
    return value if math.isfinite(value) else None


def normalize_float4(value: tuple[float, float, float, float]) -> tuple[float, ...]:
    length = math.sqrt(sum(component * component for component in value))
    if length == 0.0:
        return (0.0, 0.0, 0.0, 1.0)
    return tuple(component / length for component in value)


def signed_14(value: int) -> int:
    value &= 0x3FFF
    return value - 0x4000 if value & 0x2000 else value


def decode_packed_key(
    data: bytes,
    codec: int,
    key_offset: int,
    auxiliary_offset: int,
) -> tuple[tuple[float, float, float, float], int]:
    if codec == 4:
        checked_range(data, key_offset, 8, "LINEARKEY_16 key")
        checked_range(data, auxiliary_offset, 32, "LINEARKEY_16 parameters")
        packed = struct.unpack_from("<4H", data, key_offset)
        parameters = struct.unpack_from("<8f", data, auxiliary_offset)
        value = tuple(
            parameters[4 + index]
            + parameters[index] * ((packed[index] - 8) / 65520.0)
            for index in range(3)
        ) + (1.0,)
        return value, packed[3]

    if codec == 5:
        checked_range(data, key_offset, 4, "LINEARKEY_8 key")
        checked_range(data, auxiliary_offset, 32, "LINEARKEY_8 parameters")
        packed = struct.unpack_from("<4B", data, key_offset)
        parameters = struct.unpack_from("<8f", data, auxiliary_offset)
        value = tuple(
            parameters[4 + index]
            + parameters[index] * ((packed[index] - 8) / 240.0)
            for index in range(3)
        ) + (1.0,)
        return value, packed[3]

    if codec == 6:
        checked_range(data, key_offset, 8, "POLAR3KEY key")
        packed = struct.unpack_from("<Q", data, key_offset)[0]
        value = (
            signed_14(packed >> 42) / 4096.0,
            signed_14(packed >> 28) / 4096.0,
            signed_14(packed >> 14) / 4096.0,
            signed_14(packed) / 4096.0,
        )
        return normalize_float4(value), packed >> 56

    if codec == 7:
        checked_range(data, key_offset, 4, "POLAR3KEY_32 key")
        checked_range(data, auxiliary_offset, 32, "POLAR3KEY_32 parameters")
        packed = struct.unpack_from("<I", data, key_offset)[0]
        parameters = struct.unpack_from("<8f", data, auxiliary_offset)
        quantized = (
            (packed >> 21) & 0x7F,
            (packed >> 14) & 0x7F,
            (packed >> 7) & 0x7F,
            packed & 0x7F,
        )
        value = tuple(
            parameters[4 + index]
            + parameters[index] * ((quantized[index] - 8) / 112.0)
            for index in range(4)
        )
        return normalize_float4(value), packed >> 28

    if codec in {11, 12, 13}:
        checked_range(data, key_offset, 4, "QUNIAXIAL_32 key")
        checked_range(data, auxiliary_offset, 32, "QUNIAXIAL_32 parameters")
        packed = struct.unpack_from("<I", data, key_offset)[0]
        parameters = struct.unpack_from("<8f", data, auxiliary_offset)
        low = packed & 0x3FFF
        high = (packed >> 14) & 0x3FFF
        value = [parameters[4], parameters[5], parameters[6], parameters[7]]
        variable_component = codec - 11
        value[variable_component] += (
            parameters[variable_component] * ((low - 8) / 16368.0)
        )
        value[3] += parameters[3] * ((high - 8) / 16368.0)
        return normalize_float4(tuple(value)), packed >> 28

    raise ValueError(f"packed codec {codec} is not implemented")


def decode_track_keys(
    data: bytes,
    track: dict[str, Any],
) -> list[tuple[int, tuple[float, float, float, float]]]:
    codec = track["codec"]
    inline_value = tuple(
        0.0 if value is None else float(value) for value in track["inline_value"]
    )
    if codec in {1, 2}:
        return [(0, inline_value)]
    if codec not in PACKED_CODECS:
        raise ValueError(f"codec {codec} is not implemented")

    stride = 8 if codec in {4, 6} else 4
    data_size = track["key_data_size_or_count"]
    key_data_offset = track["key_data_offset"]
    auxiliary_offset = track["auxiliary_offset"]
    checked_range(data, key_data_offset, data_size, f"codec {codec} key data")
    maximum_keys = data_size // stride
    if maximum_keys == 0:
        raise ValueError(f"codec {codec} track has no complete keys")

    keys: list[tuple[int, tuple[float, float, float, float]]] = []
    frame = 0
    for key_index in range(maximum_keys):
        value, frame_delta = decode_packed_key(
            data,
            codec,
            key_data_offset + key_index * stride,
            auxiliary_offset,
        )
        keys.append((frame, value))
        if frame_delta == 0:
            break
        frame += frame_delta
    return keys


def sample_track(
    keys: list[tuple[int, tuple[float, float, float, float]]],
    frame: float,
    quaternion: bool,
) -> tuple[float, float, float, float]:
    if len(keys) == 1 or frame <= keys[0][0]:
        return keys[0][1]
    if frame >= keys[-1][0]:
        return keys[-1][1]

    for index in range(len(keys) - 1):
        start_frame, start_value = keys[index]
        end_frame, end_value = keys[index + 1]
        if frame > end_frame:
            continue
        factor = (frame - start_frame) / (end_frame - start_frame)
        if quaternion:
            dot = sum(
                start_value[channel] * end_value[channel]
                for channel in range(4)
            )
            if dot < 0.0:
                end_value = tuple(-component for component in end_value)
            return normalize_float4(
                tuple(
                    start_value[channel] * (1.0 - factor)
                    + end_value[channel] * factor
                    for channel in range(4)
                )
            )
        return tuple(
            start_value[channel] * (1.0 - factor)
            + end_value[channel] * factor
            for channel in range(4)
        )
    return keys[-1][1]


def parse_usage_map(mod_path: Path) -> dict[int, int]:
    data = mod_path.read_bytes()
    header = parse_header(mod_path, data)
    usage_map_offset = (
        header.bone_section_offset
        + header.bone_count * 24
        + header.bone_count * 64
        + header.bone_count * 64
    )
    checked_range(data, usage_map_offset, 0x1000, "MOD joint-usage map")
    usage_map = data[usage_map_offset : usage_map_offset + 0x1000]
    return {
        usage_id: bone_index
        for usage_id, bone_index in enumerate(usage_map)
        if bone_index != 0xFF
    }


def decode_motion_tracks(
    path: Path,
    motion_index: int,
    mod_path: Path | None = None,
) -> dict[str, Any]:
    data = path.read_bytes()
    if len(data) < 8 or data[:4] != LMT_MAGIC:
        raise ValueError(f"{path} is not an LMT file")
    version, motion_count = struct.unpack_from("<HH", data, 4)
    if version != LMT_VERSION:
        raise ValueError(f"expected LMT version {LMT_VERSION}, got {version}")
    if not 0 <= motion_index < motion_count:
        raise ValueError(
            f"motion index {motion_index} is outside 0..{motion_count - 1}"
        )
    motion_offset = struct.unpack_from("<Q", data, 8 + motion_index * 8)[0]
    if motion_offset == 0:
        raise ValueError(f"motion index {motion_index} is null")
    track_offset, track_count, frame_count = struct.unpack_from(
        "<QII", data, motion_offset
    )
    usage_map = parse_usage_map(mod_path) if mod_path else None
    tracks = []
    for track_index in range(track_count):
        track = parse_track(
            data,
            track_offset + track_index * TRACK_RECORD_SIZE,
            usage_map,
        )
        track["index"] = track_index
        track["keys"] = decode_track_keys(data, track)
        tracks.append(track)
    return {
        "path": str(path),
        "motion_index": motion_index,
        "frame_count": frame_count,
        "track_count": track_count,
        "tracks": tracks,
    }


def parse_track(
    data: bytes,
    offset: int,
    usage_map: dict[int, int] | None,
) -> dict[str, Any]:
    checked_range(data, offset, TRACK_RECORD_SIZE, "LMT track")
    codec = data[offset]
    usage = data[offset + 1]
    joint_usage_id = struct.unpack_from("<i", data, offset + 4)[0]
    blend_weight = struct.unpack_from("<f", data, offset + 8)[0]
    key_data_size_or_count = struct.unpack_from("<I", data, offset + 0x0C)[0]
    key_data_offset = struct.unpack_from("<Q", data, offset + 0x10)[0]
    inline_value = struct.unpack_from("<4f", data, offset + 0x18)
    auxiliary_offset = struct.unpack_from("<Q", data, offset + 0x28)[0]

    mapped_bone = None
    if usage_map is not None and joint_usage_id >= 0:
        mapped_bone = usage_map.get(joint_usage_id)

    return {
        "offset": offset,
        "codec": codec,
        "codec_name": CODEC_NAMES.get(codec, f"UNKNOWN_{codec}"),
        "usage": usage,
        "usage_name": USAGE_NAMES.get(usage, f"UNKNOWN_{usage}"),
        "joint_usage_id": joint_usage_id,
        "mapped_mod_bone": mapped_bone,
        "blend_weight": finite_float(blend_weight),
        "key_data_size_or_count": key_data_size_or_count,
        "key_data_offset": key_data_offset,
        "inline_value": [finite_float(value) for value in inline_value],
        "auxiliary_offset": auxiliary_offset,
    }


def inspect_lmt(
    path: Path,
    mod_path: Path | None,
    include_tracks: bool,
) -> dict[str, Any]:
    data = path.read_bytes()
    if len(data) < 8:
        raise ValueError(f"{path} is too small for an LMT header")
    if data[:4] != LMT_MAGIC:
        raise ValueError(f"{path} does not start with LMT magic")

    version, motion_count = struct.unpack_from("<HH", data, 4)
    if version != LMT_VERSION:
        raise ValueError(f"expected LMT version {LMT_VERSION}, got {version}")
    checked_range(data, 8, motion_count * 8, "LMT motion-offset table")
    motion_offsets = struct.unpack_from(f"<{motion_count}Q", data, 8)
    usage_map = parse_usage_map(mod_path) if mod_path else None

    all_codecs: Counter[int] = Counter()
    all_usages: Counter[int] = Counter()
    mapped_bones: set[int] = set()
    unmapped_joint_usage_ids: set[int] = set()
    motions: list[dict[str, Any] | None] = []

    for motion_index, motion_offset in enumerate(motion_offsets):
        if motion_offset == 0:
            motions.append(None)
            continue
        checked_range(data, motion_offset, MOTION_RECORD_SIZE, "LMT motion")
        track_offset, track_count, frame_count = struct.unpack_from(
            "<QII", data, motion_offset
        )
        loop_frame = struct.unpack_from("<i", data, motion_offset + 0x10)[0]
        flags = struct.unpack_from("<I", data, motion_offset + 0x40)[0]
        auxiliary_offset = struct.unpack_from("<Q", data, motion_offset + 0x48)[0]
        checked_range(
            data,
            track_offset,
            track_count * TRACK_RECORD_SIZE,
            f"LMT motion {motion_index} track table",
        )

        tracks = [
            parse_track(
                data,
                track_offset + track_index * TRACK_RECORD_SIZE,
                usage_map,
            )
            for track_index in range(track_count)
        ]
        codec_counts = Counter(track["codec"] for track in tracks)
        usage_counts = Counter(track["usage"] for track in tracks)
        all_codecs.update(codec_counts)
        all_usages.update(usage_counts)

        for track in tracks:
            usage_id = track["joint_usage_id"]
            mapped_bone = track["mapped_mod_bone"]
            if mapped_bone is not None:
                mapped_bones.add(mapped_bone)
            elif usage_map is not None and usage_id >= 0:
                unmapped_joint_usage_ids.add(usage_id)

        motion = {
            "index": motion_index,
            "offset": motion_offset,
            "track_offset": track_offset,
            "track_count": track_count,
            "frame_count": frame_count,
            "loop_frame": loop_frame,
            "flags": flags,
            "auxiliary_offset": auxiliary_offset,
            "codec_counts": {
                CODEC_NAMES.get(codec, f"UNKNOWN_{codec}"): count
                for codec, count in sorted(codec_counts.items())
            },
            "usage_counts": {
                USAGE_NAMES.get(usage, f"UNKNOWN_{usage}"): count
                for usage, count in sorted(usage_counts.items())
            },
        }
        if include_tracks:
            motion["tracks"] = tracks
        motions.append(motion)

    usage_map_summary = None
    if usage_map is not None:
        usage_map_summary = {
            "mod": str(mod_path),
            "entry_count": len(usage_map),
            "standard_entries": {
                str(key): value for key, value in usage_map.items() if key < 4000
            },
            "special_entries": {
                str(key): value for key, value in usage_map.items() if key >= 4000
            },
            "mapped_bones_used_by_lmt": sorted(mapped_bones),
            "unmapped_joint_usage_ids": sorted(unmapped_joint_usage_ids),
        }

    return {
        "path": str(path),
        "file_size": len(data),
        "magic": "LMT\\0",
        "version": version,
        "motion_count": motion_count,
        "non_null_motion_count": sum(offset != 0 for offset in motion_offsets),
        "motion_record_size": MOTION_RECORD_SIZE,
        "track_record_size": TRACK_RECORD_SIZE,
        "codec_counts": {
            CODEC_NAMES.get(codec, f"UNKNOWN_{codec}"): count
            for codec, count in sorted(all_codecs.items())
        },
        "usage_counts": {
            USAGE_NAMES.get(usage, f"UNKNOWN_{usage}"): count
            for usage, count in sorted(all_usages.items())
        },
        "usage_map": usage_map_summary,
        "motions": motions,
        "notes": [
            "Types 1 and 2 return the inline float4 stored at track +0x18.",
            "Codec names 3 through 15 follow nMotion::calcMotionKey template dispatch.",
            "The exact packed-key bit layout still requires per-codec validation.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect a GBM LMT v68 file.")
    parser.add_argument("lmt", type=Path, help="Input .lmt file")
    parser.add_argument("--mod", type=Path, help="Optional matching MOD v7 file")
    parser.add_argument(
        "--include-tracks",
        action="store_true",
        help="Include every 0x30-byte track record in the JSON output",
    )
    parser.add_argument("-o", "--output", type=Path, help="Write JSON report")
    args = parser.parse_args()

    report = inspect_lmt(
        args.lmt.resolve(),
        args.mod.resolve() if args.mod else None,
        args.include_tracks,
    )
    output = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

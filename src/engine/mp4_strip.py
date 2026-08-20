# -*- coding: utf-8 -*-
"""mp4/mov box 级“去假轨”：删除 text/章节轨及其 chap 引用（无损，不动媒体数据）。

背景：部分后期工具会在 mp4 里写入一条 QuickTime text 轨（stsd 'text'，内含 encd
等假时长数据），并让音视频轨通过 tref/chap 引用它。ffmpeg 的 mov 封装器看到章节
引用会无条件复制该轨（-map/-dn/重编码均无法移除），只能从 moov 结构层面删除：
  1. 删除 handler 为 text（或含 gmhd 的 media）的 trak；
  2. 删除其余 trak 内的 tref（章节引用）box；
  3. 修正 mvhd 的 movie duration（Explorer 等按 mvhd 显示时长，后期工具常把它
     写成假字幕轨的时长）；
  4. 保持文件布局（新 moov 原位替换，剩余空间用 free box 填充），mdat 偏移不变，
     因此 stco 依然有效，媒体数据一个字节都不动。
"""

from __future__ import annotations

import struct
from pathlib import Path

_BOX_HEADER = 8


def _box_iter(data: bytes, start: int, end: int):
    """迭代 [start, end) 内的 box，产出 (box_start, box_end, box_type)。"""
    offset = start
    while offset + _BOX_HEADER <= end:
        size = struct.unpack_from(">I", data, offset)[0]
        box_type = data[offset + 4: offset + 8]
        header = _BOX_HEADER
        if size == 1:
            size = struct.unpack_from(">Q", data, offset + 8)[0]
            header = 16
        elif size == 0:
            size = end - offset
        if size < header or offset + size > end:
            break
        yield offset, offset + size, box_type
        offset += size


def _find_box(data: bytes, start: int, end: int, target: bytes) -> tuple[int, int] | None:
    for box_start, box_end, box_type in _box_iter(data, start, end):
        if box_type == target:
            return box_start, box_end
    return None


def _handler_of_trak(data: bytes, trak_start: int, trak_end: int) -> str | None:
    """读取 trak 内 mdia/hdlr 的 handler 类型（vide/soun/text/…）。"""
    mdia = _find_box(data, trak_start + _BOX_HEADER, trak_end, b"mdia")
    if not mdia:
        return None
    hdlr = _find_box(data, mdia[0] + _BOX_HEADER, mdia[1], b"hdlr")
    if not hdlr:
        return None
    # hdlr: size(4) type(4) version/flags(4) pre_defined(4) handler_type(4) …
    if hdlr[1] - hdlr[0] < 24:
        return None
    return data[hdlr[0] + 16: hdlr[0] + 20].decode("latin1", "replace")


def _trak_seconds(data: bytes, trak_start: int, trak_end: int) -> float:
    """读取 trak 内 mdhd 的时长（秒）；失败返回 0。"""
    mdia = _find_box(data, trak_start + _BOX_HEADER, trak_end, b"mdia")
    if not mdia:
        return 0.0
    mdhd = _find_box(data, mdia[0] + _BOX_HEADER, mdia[1], b"mdhd")
    if not mdhd or mdhd[1] - mdhd[0] < 32:
        return 0.0
    version = data[mdhd[0] + 8]
    base = mdhd[0] + 12
    if version == 1:
        timescale = struct.unpack_from(">I", data, base + 16)[0]
        duration = struct.unpack_from(">Q", data, base + 20)[0]
    else:
        timescale = struct.unpack_from(">I", data, base + 8)[0]
        duration = struct.unpack_from(">I", data, base + 12)[0]
    if not timescale:
        return 0.0
    return duration / timescale


def _patch_mvhd_duration(moov_data: bytes, seconds: float) -> bytes:
    """把 moov 内 mvhd 的 duration 改写为给定秒数（timescale 单位），返回新 moov。

    部分后期工具会把 movie 时长写成假字幕轨的时长，导致 Windows 资源管理器
    显示错误时长——删除假轨后必须同步修正 mvhd。
    """
    result = bytearray(moov_data)
    mvhd = _find_box(result, _BOX_HEADER, len(result), b"mvhd")
    if not mvhd:
        return moov_data
    version = result[mvhd[0] + 8]
    if version == 1:
        timescale = struct.unpack_from(">I", result, mvhd[0] + 12 + 16)[0]
        duration_offset = mvhd[0] + 12 + 20
    else:
        timescale = struct.unpack_from(">I", result, mvhd[0] + 12 + 8)[0]
        duration_offset = mvhd[0] + 12 + 12
    if not timescale:
        return moov_data
    new_duration = max(0, round(seconds * timescale))
    if version == 1:
        struct.pack_into(">Q", result, duration_offset, new_duration)
    else:
        struct.pack_into(">I", result, duration_offset, min(new_duration, 0xFFFFFFFF))
    return bytes(result)


def strip_tainted_tracks(source: Path, tainted_indexes: set[int], target: Path) -> tuple[bool, str]:
    """删除 source 中序号在 tainted_indexes 的 trak 及其 tref 引用，写入 target。

    返回 (ok, 说明/错误信息)。成功后 target 是完整可播放的文件，媒体数据不变。
    """
    try:
        data = source.read_bytes()
    except OSError as exc:
        return False, f"读取失败: {exc}"
    if not data:
        return False, "文件为空"

    moov = _find_box(data, 0, len(data), b"moov")
    if not moov:
        return False, "未找到 moov（可能不是 MP4/MOV 文件）"
    moov_start, moov_end = moov
    moov_data = data[moov_start: moov_end]
    moov_header = moov_data[:_BOX_HEADER]
    body_start = _BOX_HEADER

    traks = [
        (trak_start, trak_end)
        for trak_start, trak_end, box_type in _box_iter(moov_data, body_start, len(moov_data))
        if box_type == b"trak"
    ]
    if not traks:
        return False, "moov 中没有 trak"

    drop_indexes = {index for index in tainted_indexes if 0 <= index < len(traks)}
    if not drop_indexes:
        return False, "未找到需要删除的轨道"

    # 重建 moov 的全部子 box：非 trak 原样保留；目标 trak 删除；
    # 保留的 trak 去掉 tref（章节引用，指向已删除的轨）。
    rebuilt_all: list[bytes] = []
    kept_seconds: list[float] = []
    trak_pos = 0
    for box_start, box_end, box_type in _box_iter(moov_data, body_start, len(moov_data)):
        if box_type != b"trak":
            rebuilt_all.append(moov_data[box_start: box_end])
            continue
        index = trak_pos
        trak_pos += 1
        handler = _handler_of_trak(moov_data, box_start, box_end)
        # 双重保险：序号命中，或 handler 本身是 text 轨
        if index in drop_indexes or (handler or "").lower() == "text":
            continue
        kept_seconds.append(_trak_seconds(moov_data, box_start, box_end))
        chunk = moov_data[box_start: box_end]
        body = bytearray()
        removed_tref = False
        for sub_start, sub_end, sub_type in _box_iter(chunk, _BOX_HEADER, len(chunk)):
            if sub_type == b"tref":
                removed_tref = True
                continue
            body += chunk[sub_start: sub_end]
        if removed_tref:
            # 保留 trak 头部并修正 size（8 字节头 + 子 box）
            rebuilt_all.append(struct.pack(">I", _BOX_HEADER + len(body)) + chunk[4:_BOX_HEADER] + bytes(body))
        else:
            rebuilt_all.append(chunk)

    new_moov = moov_header + b"".join(rebuilt_all)
    new_moov = struct.pack(">I", len(new_moov)) + new_moov[4:]
    # 同步修正 mvhd 时长：以保留轨的最大时长为准（Explorer 等按 mvhd 显示）
    if kept_seconds and max(kept_seconds) > 0:
        new_moov = _patch_mvhd_duration(new_moov, max(kept_seconds))

    # 原位替换 moov，剩余空间补 free box（保持布局与 mdat 偏移不变，stco 依然有效）
    moov_len = moov_end - moov_start
    if len(new_moov) > moov_len:
        return False, "重建后 moov 变大（异常），已中止"
    padding = moov_len - len(new_moov)
    if padding > 8:
        new_moov += struct.pack(">I4s", padding, b"free") + b"\x00" * (padding - 8)
    elif padding:
        new_moov += b"\x00" * padding

    try:
        with open(target, "wb") as handle:
            handle.write(data[:moov_start])
            handle.write(new_moov)
            handle.write(data[moov_end:])
    except OSError as exc:
        return False, f"写入失败: {exc}"
    return True, f"已删除 {len(drop_indexes)} 条异常轨并移除章节引用"


def has_moov_container(suffix: str) -> bool:
    """判断扩展名是否走 moov 容器（box 级清洗适用）。"""
    return suffix.lower() in {".mp4", ".mov", ".m4a", ".m4v", ".3gp", ".f4v"}

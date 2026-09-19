"""视频剪辑核心：加载、裁剪、拼接、导出。"""
from __future__ import annotations

import os
from typing import Callable, Optional

from moviepy import VideoFileClip, concatenate_videoclips


def load_video(path: str) -> VideoFileClip:
    """加载视频文件。调用方负责 close()。"""
    return VideoFileClip(path)


def cut_clip(clip: VideoFileClip, start: float, end: float) -> VideoFileClip:
    """截取 [start, end] 秒片段。"""
    start = max(0.0, float(start))
    end = float(end)
    if end <= start:
        raise ValueError(f"结束时间 {end} 必须大于开始时间 {start}")
    return clip.subclipped(start, end)


def concat_clips(clips: list[VideoFileClip]) -> VideoFileClip:
    """拼接多段视频。"""
    if not clips:
        raise ValueError("没有可拼接的片段")
    return concatenate_videoclips(clips, method="compose")


def export_video(
    clip: VideoFileClip,
    out_path: str,
    audio_codec: str = "aac",
    bitrate: Optional[str] = None,
) -> str:
    """导出视频到磁盘。"""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    kwargs = {
        "codec": "libx264",
        "audio_codec": audio_codec,
        "preset": "medium",
        "logger": None,
        "threads": 4,
    }
    if bitrate:
        kwargs["bitrate"] = bitrate
    clip.write_videofile(out_path, **kwargs)
    return out_path

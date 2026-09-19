"""读取视频/音频元信息。"""
from __future__ import annotations

from dataclasses import dataclass

from moviepy import VideoFileClip, AudioFileClip


@dataclass
class VideoMeta:
    path: str
    duration: float          # 秒
    fps: float
    width: int
    height: int
    has_audio: bool


@dataclass
class AudioMeta:
    path: str
    duration: float          # 秒


def probe_video(path: str) -> VideoMeta:
    clip = VideoFileClip(path)
    try:
        return VideoMeta(
            path=path,
            duration=float(clip.duration or 0.0),
            fps=float(clip.fps or 25.0),
            width=int(clip.size[0]),
            height=int(clip.size[1]),
            has_audio=clip.audio is not None,
        )
    finally:
        clip.close()


def probe_audio(path: str) -> AudioMeta:
    clip = AudioFileClip(path)
    try:
        return AudioMeta(path=path, duration=float(clip.duration or 0.0))
    finally:
        clip.close()

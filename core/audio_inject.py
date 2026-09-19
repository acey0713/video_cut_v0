"""声音插入：在指定时间点把一段音频叠加到视频音轨上。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from moviepy import AudioFileClip, CompositeAudioClip
from moviepy.audio.AudioClip import AudioClip


@dataclass
class InjectSpec:
    """一次声音插入的描述。"""
    audio_path: str          # 插入的音频文件路径
    insert_at: float         # 在第几秒开始播放
    volume: float = 1.0      # 插入音频自身音量 0~2
    clip_start: float = 0.0  # 从插入音频的第几秒开始截
    clip_end: Optional[float] = None  # 截到第几秒，None 表示到结尾


def build_mixed_audio(
    original_audio: Optional[AudioClip],
    specs: list[InjectSpec],
    original_volume: float = 1.0,
) -> Optional[AudioClip]:
    """
    把原始音轨与多段插入音频混音叠加。

    - original_audio: 原视频音轨（可能为 None，表示原视频无声）
    - original_volume: 原音轨整体音量 0~2
    - specs: 每段插入音频的描述
    返回合成后的 AudioClip；若没有任何音轨则返回 None。
    """
    tracks: list[AudioClip] = []

    if original_audio is not None and original_volume > 0:
        tracks.append(original_audio.with_volume_scaled(original_volume))

    for spec in specs:
        insert = AudioFileClip(spec.audio_path)
        # 截取插入音频自身的片段
        cs = max(0.0, float(spec.clip_start))
        ce = float(spec.clip_end) if spec.clip_end is not None else insert.duration
        if ce > cs:
            insert = insert.subclipped(cs, ce)
        # 设置起始时间
        insert = insert.with_start(max(0.0, float(spec.insert_at)))
        # 设置音量
        if spec.volume != 1.0:
            insert = insert.with_volume_scaled(spec.volume)
        tracks.append(insert)

    if not tracks:
        return None
    if len(tracks) == 1:
        return tracks[0]
    return CompositeAudioClip(tracks)


def apply_audio_to_clip(video_clip, mixed_audio):
    """把合成音轨挂到视频上。"""
    if mixed_audio is None:
        return video_clip.without_audio() if hasattr(video_clip, "without_audio") else video_clip
    return video_clip.with_audio(mixed_audio)

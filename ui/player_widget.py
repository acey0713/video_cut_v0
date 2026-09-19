"""视频预览播放器：封装 QMediaPlayer + QVideoWidget + 控制条。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)


def _fmt_ms(ms: int) -> str:
    if ms < 0:
        ms = 0
    s = ms // 1000
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class PlayerWidget(QWidget):
    positionChanged = Signal(int)   # ms
    durationChanged = Signal(int)   # ms

    def __init__(self, parent=None):
        super().__init__(parent)

        self._media_player = QMediaPlayer(self)
        self._audio_out = QAudioOutput(self)
        self._media_player.setAudioOutput(self._audio_out)

        self._video_widget = QVideoWidget(self)
        self._video_widget.setMinimumHeight(360)
        self._video_widget.setStyleSheet("background: black;")
        self._media_player.setVideoOutput(self._video_widget)

        # 控制条
        self._btn_play = QPushButton("播放")
        self._btn_play.setFixedWidth(70)
        self._btn_play.clicked.connect(self.toggle_play)

        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(0, 0)
        self._slider.sliderMoved.connect(self._on_slider_moved)

        self._lbl_time = QLabel("00:00 / 00:00")
        self._lbl_time.setFixedWidth(130)
        self._lbl_time.setAlignment(Qt.AlignCenter)

        self._vol_slider = QSlider(Qt.Horizontal)
        self._vol_slider.setRange(0, 100)
        self._vol_slider.setValue(100)
        self._vol_slider.setFixedWidth(100)
        self._vol_slider.valueChanged.connect(self._on_volume_changed)

        ctrl = QHBoxLayout()
        ctrl.addWidget(self._btn_play)
        ctrl.addWidget(self._slider, 1)
        ctrl.addWidget(self._lbl_time)
        ctrl.addWidget(QLabel("音量"))
        ctrl.addWidget(self._vol_slider)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._video_widget, 1)
        layout.addLayout(ctrl)

        self._media_player.positionChanged.connect(self._on_position)
        self._media_player.durationChanged.connect(self._on_duration)
        self._media_player.playbackStateChanged.connect(self._on_state)

    # ---- public API ----
    def load(self, path: str):
        self._media_player.setSource(QUrl.fromLocalFile(path))

    def play(self):
        self._media_player.play()

    def pause(self):
        self._media_player.pause()

    def stop(self):
        self._media_player.stop()

    def position_ms(self) -> int:
        return self._media_player.position()

    def duration_ms(self) -> int:
        return self._media_player.duration()

    def seek_ms(self, ms: int):
        self._media_player.setPosition(int(ms))

    # ---- slots ----
    def toggle_play(self):
        if self._media_player.playbackState() == QMediaPlayer.PlayingState:
            self._media_player.pause()
        else:
            self._media_player.play()

    def _on_position(self, pos: int):
        if not self._slider.isSliderDown():
            self._slider.setValue(pos)
        self._lbl_time.setText(f"{_fmt_ms(pos)} / {_fmt_ms(self._media_player.duration())}")
        self.positionChanged.emit(pos)

    def _on_duration(self, dur: int):
        self._slider.setRange(0, max(0, dur))
        self.durationChanged.emit(dur)

    def _on_slider_moved(self, pos: int):
        self._media_player.setPosition(pos)

    def _on_volume_changed(self, v: int):
        self._audio_out.setVolume(v / 100.0)

    def _on_state(self, state):
        if state == QMediaPlayer.PlayingState:
            self._btn_play.setText("暂停")
        else:
            self._btn_play.setText("播放")

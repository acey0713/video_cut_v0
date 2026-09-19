"""剪辑面板：视频片段列表（拖入文件 + 拖动排序）+ 声音插入 + 原音音量。"""
from __future__ import annotations

import os
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core.audio_inject import InjectSpec
from core.metadata import probe_video

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".flv", ".wmv", ".webm", ".m4v"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


@dataclass
class Segment:
    path: str
    in_point: float
    out_point: float


@dataclass
class _AudioRow:
    audio_path: str
    insert_at: float
    volume: float


def _sec_spin(maximum: float = 86400.0) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setDecimals(2)
    s.setRange(0.0, maximum)
    s.setSuffix(" s")
    s.setFixedWidth(100)
    return s


class TimelineWidget(QWidget):
    segmentSelected = Signal(str)
    settingsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)   # 接受外部文件拖入
        self._segments: list[Segment] = []
        self._audio_rows: list[_AudioRow] = []
        self._current_pos_sec: callable = lambda: 0.0

        # ===== 视频片段区 =====
        self._btn_add_seg = QPushButton("+ 添加视频...")
        self._btn_remove_seg = QPushButton("删除选中")
        self._btn_set_in = QPushButton("当前位置设为入点")
        self._btn_set_out = QPushButton("当前位置设为出点")

        seg_btns = QHBoxLayout()
        seg_btns.addWidget(self._btn_add_seg)
        seg_btns.addWidget(self._btn_remove_seg)
        seg_btns.addStretch(1)
        seg_btns.addWidget(self._btn_set_in)
        seg_btns.addWidget(self._btn_set_out)

        # 片段列表：支持行内拖动排序
        self._seg_list = QListWidget()
        self._seg_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._seg_list.setDragDropMode(QAbstractItemView.InternalMove)
        self._seg_list.setDefaultDropAction(Qt.MoveAction)
        self._seg_list.setDragEnabled(True)
        # 注：不设 setAcceptDrops(False)，否则 InternalMove 失效。
        # 外部文件 URL 由父 widget (TimelineWidget) 的 dropEvent 统一接收。
        self._seg_list.setDropIndicatorShown(True)
        self._seg_list.currentRowChanged.connect(self._on_row_changed)
        # 拖动行后同步 self._segments 顺序
        self._seg_list.model().rowsMoved.connect(self._on_rows_moved)

        hint = QLabel("提示：可直接把视频文件拖到窗口任意位置；拖动列表中的行可调整拼接顺序。")
        hint.setStyleSheet("color: #888;")

        seg_layout = QVBoxLayout()
        seg_layout.addLayout(seg_btns)
        seg_layout.addWidget(self._seg_list)
        seg_layout.addWidget(hint)

        seg_group = QGroupBox("视频片段（按从上到下顺序拼接）")
        seg_group.setLayout(seg_layout)

        # ===== 声音插入区 =====
        self._btn_add_audio = QPushButton("+ 添加音频...")
        self._btn_add_audio.clicked.connect(self._on_add_audio_dialog)

        self._audio_list_layout = QVBoxLayout()
        self._audio_list_layout.setContentsMargins(4, 4, 4, 4)
        self._audio_list_layout.setSpacing(4)
        audio_list_container = QWidget()
        audio_list_container.setLayout(self._audio_list_layout)

        audio_box = QVBoxLayout()
        audio_box.addWidget(self._btn_add_audio)
        audio_box.addWidget(audio_list_container)

        audio_group = QGroupBox("声音插入（叠加在原音轨上，时间点基于拼接后的成片）")
        audio_group.setLayout(audio_box)

        # ===== 原音轨音量 =====
        self._orig_vol_slider = QSlider(Qt.Horizontal)
        self._orig_vol_slider.setRange(0, 200)
        self._orig_vol_slider.setValue(100)
        self._orig_vol_label = QLabel("1.00")
        self._orig_vol_slider.valueChanged.connect(
            lambda v: self._orig_vol_label.setText(f"{v / 100:.2f}")
        )
        vol_layout = QHBoxLayout()
        vol_layout.addWidget(QLabel("原音轨音量:"))
        vol_layout.addWidget(self._orig_vol_slider, 1)
        vol_layout.addWidget(self._orig_vol_label)

        root = QVBoxLayout(self)
        root.addWidget(seg_group)
        root.addWidget(audio_group)
        root.addLayout(vol_layout)

        self._btn_add_seg.clicked.connect(self._on_add_segment_dialog)
        self._btn_remove_seg.clicked.connect(self._on_remove_segment)
        self._btn_set_in.clicked.connect(self._set_in_from_player)
        self._btn_set_out.clicked.connect(self._set_out_from_player)

    # ---- 主窗口注入 ----
    def set_player_position_provider(self, fn: callable):
        self._current_pos_sec = fn

    # ===== 外部文件拖入 =====
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event: QDragMoveEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        if not event.mimeData().hasUrls():
            return
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        vids = [p for p in paths if os.path.splitext(p)[1].lower() in VIDEO_EXTS]
        auds = [p for p in paths if os.path.splitext(p)[1].lower() in AUDIO_EXTS]
        if vids:
            self._add_paths_as_segments(vids)
        if auds:
            for ap in auds:
                self._audio_rows.append(_AudioRow(audio_path=ap, insert_at=0.0, volume=1.0))
                self._append_audio_row(self._audio_rows[-1])
        if vids or auds:
            event.acceptProposedAction()
            self.settingsChanged.emit()

    # ---- 片段：从对话框选择 ----
    def _on_add_segment_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择视频文件", "",
            "视频文件 (*.mp4 *.mov *.avi *.mkv *.flv *.wmv *.webm);;所有文件 (*.*)",
        )
        if paths:
            self._add_paths_as_segments(paths)

    def _add_paths_as_segments(self, paths: list[str]):
        added = 0
        for p in paths:
            try:
                meta = probe_video(p)
            except Exception as e:
                QMessageBox.warning(self, "无法读取", f"{os.path.basename(p)}: {e}")
                continue
            self._segments.append(Segment(path=p, in_point=0.0, out_point=meta.duration))
            added += 1
        self._rebuild_seg_list()
        if added and self._segments:
            self._seg_list.setCurrentRow(len(self._segments) - 1)
        self.settingsChanged.emit()

    def _rebuild_seg_list(self):
        self._seg_list.blockSignals(True)
        self._seg_list.clear()
        for i, seg in enumerate(self._segments):
            text = (f"{i+1}. {os.path.basename(seg.path)}   "
                    f"[{seg.in_point:.2f}s ~ {seg.out_point:.2f}s]  "
                    f"({max(0.0, seg.out_point-seg.in_point):.2f}s)")
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, seg)   # 把 segment 绑在 item 上，拖动排序时跟着走
            item.setToolTip(seg.path)
            self._seg_list.addItem(item)
        self._seg_list.blockSignals(False)

    def _on_row_changed(self, row: int):
        item = self._seg_list.item(row) if row >= 0 else None
        if item is not None:
            seg = item.data(Qt.UserRole)
            if seg is not None:
                self.segmentSelected.emit(seg.path)

    def _on_rows_moved(self, *args):
        # 用户在列表里拖动了行：按新顺序重建 _segments
        new_order = []
        for i in range(self._seg_list.count()):
            seg = self._seg_list.item(i).data(Qt.UserRole)
            if seg is not None:
                new_order.append(seg)
        self._segments = new_order
        self._rebuild_seg_list()
        self.settingsChanged.emit()

    def _on_remove_segment(self):
        row = self._seg_list.currentRow()
        if row < 0:
            return
        del self._segments[row]
        self._rebuild_seg_list()
        if self._segments:
            self._seg_list.setCurrentRow(min(row, len(self._segments) - 1))
        self.settingsChanged.emit()

    def _set_in_from_player(self):
        row = self._seg_list.currentRow()
        if row < 0:
            return
        self._segments[row].in_point = float(self._current_pos_sec())
        self._rebuild_seg_list()
        self._seg_list.setCurrentRow(row)
        self.settingsChanged.emit()

    def _set_out_from_player(self):
        row = self._seg_list.currentRow()
        if row < 0:
            return
        self._segments[row].out_point = float(self._current_pos_sec())
        self._rebuild_seg_list()
        self._seg_list.setCurrentRow(row)
        self.settingsChanged.emit()

    # ---- 音频插入 ----
    def _on_add_audio_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择音频文件", "",
            "音频文件 (*.mp3 *.wav *.m4a *.aac *.flac *.ogg);;所有文件 (*.*)",
        )
        if not path:
            return
        row = _AudioRow(audio_path=path, insert_at=0.0, volume=1.0)
        self._audio_rows.append(row)
        self._append_audio_row(row)
        self.settingsChanged.emit()

    def _append_audio_row(self, row: _AudioRow):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel(os.path.basename(row.audio_path))
        lbl.setToolTip(row.audio_path)
        lbl.setFixedWidth(160)

        sp = _sec_spin()
        sp.setValue(row.insert_at)
        sp.valueChanged.connect(lambda v, r=row: setattr(r, "insert_at", float(v)))

        vol = QSlider(Qt.Horizontal)
        vol.setRange(0, 200)
        vol.setValue(int(row.volume * 100))
        vol.setFixedWidth(120)
        vol_lbl = QLabel(f"{row.volume:.2f}")
        vol_lbl.setFixedWidth(40)
        vol.valueChanged.connect(
            lambda v, r=row, l=vol_lbl: (setattr(r, "volume", v / 100.0), l.setText(f"{v/100:.2f}"))
        )

        btn_del = QPushButton("删除")
        btn_del.clicked.connect(lambda _, r=row, w=w: self._remove_audio_row(r, w))

        h.addWidget(lbl, 1)
        h.addWidget(QLabel("@"))
        h.addWidget(sp)
        h.addWidget(QLabel("音量"))
        h.addWidget(vol)
        h.addWidget(vol_lbl)
        h.addWidget(btn_del)
        self._audio_list_layout.addWidget(w)

    def _remove_audio_row(self, row: _AudioRow, w: QWidget):
        self._audio_rows.remove(row)
        self._audio_list_layout.removeWidget(w)
        w.deleteLater()
        self.settingsChanged.emit()

    # ---- 导出时取数据 ----
    def get_segments(self) -> list[Segment]:
        return list(self._segments)

    def get_inject_specs(self) -> list[InjectSpec]:
        return [
            InjectSpec(audio_path=r.audio_path, insert_at=r.insert_at, volume=r.volume)
            for r in self._audio_rows
        ]

    def get_original_volume(self) -> float:
        return self._orig_vol_slider.value() / 100.0

    def total_duration_sec(self) -> float:
        return sum(max(0.0, s.out_point - s.in_point) for s in self._segments)

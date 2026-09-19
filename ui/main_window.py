"""主窗口：菜单 + 播放器 + 片段时间线 + 后台导出（多片段拼接 + 音频叠加）。"""
from __future__ import annotations

import os
import traceback
from datetime import datetime

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core import editor
from core.audio_inject import apply_audio_to_clip, build_mixed_audio
from ui.player_widget import PlayerWidget
from ui.timeline_widget import Segment, TimelineWidget


class ExportWorker(QThread):
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, segments: list[Segment], specs, orig_vol: float, out_path: str, parent=None):
        super().__init__(parent)
        self.segments = segments
        self.specs = specs
        self.orig_vol = orig_vol
        self.out_path = out_path

    def run(self):
        opened = []
        final = None
        try:
            clips = []
            for seg in self.segments:
                vf = editor.load_video(seg.path)
                opened.append(vf)
                start = max(0.0, float(seg.in_point))
                end = float(seg.out_point) if seg.out_point > 0 else float(vf.duration)
                end = min(end, float(vf.duration))
                if end <= start:
                    continue
                clips.append(editor.cut_clip(vf, start, end))

            if not clips:
                raise RuntimeError("没有可用的视频片段")

            final = editor.concat_clips(clips)

            # 叠加音频
            mixed = build_mixed_audio(final.audio, self.specs, self.orig_vol)
            final = apply_audio_to_clip(final, mixed)

            editor.export_video(final, self.out_path)
            self.finished_ok.emit(self.out_path)
        except Exception as e:
            self.failed.emit(f"{e}\n\n{traceback.format_exc()}")
        finally:
            try:
                if final is not None:
                    final.close()
            except Exception:
                pass
            for c in opened:
                try:
                    c.close()
                except Exception:
                    pass


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("简易视频剪辑工具")
        self.resize(1100, 780)

        self._worker: ExportWorker | None = None

        self.player = PlayerWidget()
        self.timeline = TimelineWidget()
        self.timeline.set_player_position_provider(lambda: self.player.position_ms() / 1000.0)

        # 选中片段 → 播放器预览
        self.timeline.segmentSelected.connect(self._on_segment_selected)
        self.timeline.settingsChanged.connect(self._refresh_status)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.player)
        splitter.addWidget(self.timeline)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addWidget(splitter)
        self.setCentralWidget(central)

        self._build_menu()
        self._status = QLabel("未添加视频片段")
        self.statusBar().addWidget(self._status)

        # 右下角 author 标签
        self._author = QLabel("author: Acey")
        self._author.setStyleSheet("color: #888; padding-right: 8px;")
        self.statusBar().addPermanentWidget(self._author)

        # 整个窗口接受外部文件拖入，转发给 timeline
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        # 直接调用 timeline 的 dropEvent 处理
        self.timeline.dropEvent(event)

    def _build_menu(self):
        mb = self.menuBar()
        m_file = mb.addMenu("文件(&F)")

        act_add = m_file.addAction("添加视频片段...")
        act_add.setShortcut("Ctrl+O")
        act_add.triggered.connect(lambda: self.timeline._on_add_segment_dialog())

        act_export = m_file.addAction("导出视频...")
        act_export.setShortcut("Ctrl+E")
        act_export.triggered.connect(self._export)

        m_file.addSeparator()
        act_quit = m_file.addAction("退出")
        act_quit.triggered.connect(self.close)

        m_help = mb.addMenu("帮助(&H)")
        act_about = m_help.addAction("关于")
        act_about.triggered.connect(
            lambda: QMessageBox.information(
                self, "关于",
                "简易视频剪辑工具\n基于 PySide6 + moviepy\n功能：多片段拼接 + 裁剪 + 叠加音频"
            )
        )

    # ---- ----
    def _on_segment_selected(self, path: str):
        self.player.load(path)
        self._refresh_status()

    def _refresh_status(self):
        segs = self.timeline.get_segments()
        if not segs:
            self._status.setText("未添加视频片段")
            return
        total = self.timeline.total_duration_sec()
        names = ", ".join(os.path.basename(s.path) for s in segs)
        self._status.setText(f"共 {len(segs)} 段 · 总时长 {total:.2f}s   [{names}]")

    def _export(self):
        segs = self.timeline.get_segments()
        if not segs:
            QMessageBox.warning(self, "提示", "请先添加至少一个视频片段")
            return

        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output")
        os.makedirs(out_dir, exist_ok=True)
        default_name = "edited_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".mp4"
        default_path = os.path.join(out_dir, default_name)

        out_path, _ = QFileDialog.getSaveFileName(
            self, "导出视频", default_path, "MP4 视频 (*.mp4)"
        )
        if not out_path:
            return

        specs = self.timeline.get_inject_specs()
        orig_vol = self.timeline.get_original_volume()

        prog = QProgressDialog("正在导出，请稍候...", None, 0, 0, self)
        prog.setWindowTitle("导出中")
        prog.setWindowModality(Qt.WindowModal)
        prog.setCancelButton(None)
        prog.setAutoClose(False)
        prog.setAutoReset(False)
        prog.show()

        self._worker = ExportWorker(segs, specs, orig_vol, out_path, parent=self)
        self._worker.finished_ok.connect(lambda p: (prog.close(), QMessageBox.information(self, "导出完成", f"已保存到：\n{p}")))
        self._worker.failed.connect(lambda m: (prog.close(), QMessageBox.critical(self, "导出失败", m)))
        self._worker.start()

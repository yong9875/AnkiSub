# -*- coding: utf-8 -*-
"""
AnkiSub - FFmpeg Zero-Config Setup & Auto-Downloader
Provides a user-friendly setup wizard if FFmpeg is not found.
Supports:
1. One-click automatic download & unzip into AnkiSub/bin/ (zero env var setup).
2. Open bin folder in Windows Explorer for drag-and-drop.
3. Live re-detection.
"""

import os
import sys
import zipfile
import tempfile
import urllib.request
from typing import Optional

from aqt.qt import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QMessageBox, QThread, pyqtSignal, Qt, QUrl
)
from aqt.utils import showInfo, openFolder
from aqt import mw

from .ffmpeg_worker import is_ffmpeg_available, refresh_binary_paths, FFMPEG_PATH, FFPROBE_PATH

# Trusted pre-compiled portable FFmpeg releases
# Windows 64-bit portable build
WIN64_FFMPEG_URL = "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
# Fallback mirror / info link
MANUAL_DOWNLOAD_PAGE = "https://www.gyan.dev/ffmpeg/builds/"


class FFmpegDownloadThread(QThread):
    """Background thread to download and extract portable FFmpeg binaries."""
    progress_changed = pyqtSignal(int, str)  # percent, status_text
    download_finished = pyqtSignal(bool, str) # success, message

    def __init__(self, target_bin_dir: str):
        super().__init__()
        self.target_bin_dir = target_bin_dir
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        os.makedirs(self.target_bin_dir, exist_ok=True)
        temp_zip = None

        try:
            self.progress_changed.emit(5, "正在连接下载源...")
            url = WIN64_FFMPEG_URL
            
            # Create request with browser User-Agent
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            )

            with urllib.request.urlopen(req, timeout=30) as response:
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                
                # Create temp file
                fd, temp_zip = tempfile.mkstemp(suffix=".zip")
                os.close(fd)

                with open(temp_zip, 'wb') as f:
                    chunk_size = 128 * 1024  # 128KB
                    while True:
                        if self._is_cancelled:
                            self.download_finished.emit(False, "下载已取消")
                            return

                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)

                        if total_size > 0:
                            percent = int(5 + (downloaded / total_size) * 75)
                            mb_down = downloaded / (1024 * 1024)
                            mb_total = total_size / (1024 * 1024)
                            self.progress_changed.emit(percent, f"正在下载: {mb_down:.1f}MB / {mb_total:.1f}MB ({percent}%)")
                        else:
                            mb_down = downloaded / (1024 * 1024)
                            self.progress_changed.emit(40, f"正在下载: {mb_down:.1f}MB")

            if self._is_cancelled:
                self.download_finished.emit(False, "下载已取消")
                return

            self.progress_changed.emit(85, "下载完成，正在解压 ffmpeg 与 ffprobe...")
            
            # Extract only ffmpeg.exe and ffprobe.exe
            extracted_count = 0
            with zipfile.ZipFile(temp_zip, 'r') as zf:
                for file_info in zf.infolist():
                    fname = os.path.basename(file_info.filename).lower()
                    if fname in ('ffmpeg.exe', 'ffprobe.exe'):
                        target_file = os.path.join(self.target_bin_dir, fname)
                        with zf.open(file_info) as source, open(target_file, 'wb') as target:
                            target.write(source.read())
                        extracted_count += 1

            if extracted_count == 0:
                self.download_finished.emit(False, "压缩包中未找到 ffmpeg.exe 或 ffprobe.exe")
                return

            self.progress_changed.emit(100, "安装完成！")
            refresh_binary_paths()
            self.download_finished.emit(True, "FFmpeg 已成功安装到插件内部目录！")

        except Exception as e:
            self.download_finished.emit(False, f"下载或解压失败: {str(e)}")
        finally:
            if temp_zip and os.path.exists(temp_zip):
                try:
                    os.remove(temp_zip)
                except Exception:
                    pass


class FFmpegSetupDialog(QDialog):
    """Zero-configuration setup wizard dialog for missing FFmpeg."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AnkiSub - FFmpeg 环境配置向导")
        self.setMinimumWidth(560)
        self.target_bin_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin")
        self.download_thread: Optional[FFmpegDownloadThread] = None

        self._init_ui()
        self._check_status()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        # Title / Description
        title = QLabel("<h2>⚙️ 欢迎使用 AnkiSub</h2>")
        layout.addWidget(title)

        desc = QLabel(
            "AnkiSub 需要借助开源音视频工具 <b>FFmpeg</b> 进行音频无损切片和画面截图。<br>"
            "无需配置复杂的 Windows 环境变量，您只需选择以下最方便的一种方式："
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #455a64; line-height: 1.5; font-size: 13px;")
        layout.addWidget(desc)

        # Status box
        self.status_label = QLabel()
        self.status_label.setStyleSheet(
            "padding: 10px 14px; border-radius: 6px; font-weight: bold; background: #fff3e0; color: #e65100;"
        )
        layout.addWidget(self.status_label)

        # Progress bar (hidden initially)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.progress_text = QLabel("")
        self.progress_text.setStyleSheet("color: #1976d2; font-size: 12px;")
        self.progress_text.setVisible(False)
        layout.addWidget(self.progress_text)

        # Option 1: One-click auto download
        opt1_layout = QVBoxLayout()
        self.btn_auto_download = QPushButton("🚀 方式一：一键自动下载并配置（推荐）")
        self.btn_auto_download.setStyleSheet(
            "QPushButton { background: #1976d2; color: white; padding: 10px 16px; border-radius: 6px; font-weight: bold; font-size: 14px; }"
            "QPushButton:hover { background: #1565c0; }"
            "QPushButton:disabled { background: #b0bec5; }"
        )
        self.btn_auto_download.clicked.connect(self._start_download)
        opt1_layout.addWidget(self.btn_auto_download)

        opt1_tip = QLabel("自动从便携源下载 ffmpeg 与 ffprobe 并存入插件内部目录，无需重启软件。")
        opt1_tip.setStyleSheet("color: #78909c; font-size: 11px; margin-left: 4px;")
        opt1_layout.addWidget(opt1_tip)
        layout.addLayout(opt1_layout)

        # Option 2: Manual drag and drop
        opt2_layout = QVBoxLayout()
        btn_h = QHBoxLayout()
        self.btn_open_bin = QPushButton("📁 方式二：打开插件 bin 文件夹（离线拖入）")
        self.btn_open_bin.setStyleSheet("padding: 8px 14px; font-size: 13px;")
        self.btn_open_bin.clicked.connect(self._open_bin_folder)
        btn_h.addWidget(self.btn_open_bin)

        self.btn_recheck = QPushButton("🔄 放入后点此重新检测")
        self.btn_recheck.setStyleSheet("padding: 8px 14px; font-size: 13px;")
        self.btn_recheck.clicked.connect(self._check_status_manual)
        btn_h.addWidget(self.btn_recheck)
        opt2_layout.addLayout(btn_h)

        opt2_tip = QLabel("如果您已下载好 ffmpeg.exe 与 ffprobe.exe，点击打开文件夹直接复制进去即可。")
        opt2_tip.setStyleSheet("color: #78909c; font-size: 11px; margin-left: 4px;")
        opt2_layout.addWidget(opt2_tip)
        layout.addLayout(opt2_layout)

        # Footer close button
        layout.addSpacing(10)
        footer_layout = QHBoxLayout()
        footer_layout.addStretch()

        self.btn_done = QPushButton("完成并进入制卡")
        self.btn_done.setStyleSheet("padding: 8px 20px; font-size: 13px; font-weight: bold;")
        self.btn_done.clicked.connect(self.accept)
        self.btn_done.setEnabled(False)
        footer_layout.addWidget(self.btn_done)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        footer_layout.addWidget(self.btn_cancel)
        layout.addLayout(footer_layout)

    def _check_status(self) -> bool:
        ready = is_ffmpeg_available()
        if ready:
            self.status_label.setText("✅ 已成功检测到 FFmpeg！组件工作就绪，可以正常制卡。")
            self.status_label.setStyleSheet(
                "padding: 10px 14px; border-radius: 6px; font-weight: bold; background: #e8f5e9; color: #2e7d32;"
            )
            self.btn_done.setEnabled(True)
            self.btn_auto_download.setEnabled(False)
            self.btn_auto_download.setText("✅ FFmpeg 已就绪")
            return True
        else:
            self.status_label.setText("⚠️ 未检测到 FFmpeg。请点击下方按钮一键配置。")
            self.status_label.setStyleSheet(
                "padding: 10px 14px; border-radius: 6px; font-weight: bold; background: #fff3e0; color: #e65100;"
            )
            self.btn_done.setEnabled(False)
            self.btn_auto_download.setEnabled(True)
            return False

    def _check_status_manual(self):
        refresh_binary_paths()
        if self._check_status():
            QMessageBox.information(self, "检测成功", "FFmpeg 检测成功！您可以开始制作卡片了。")
        else:
            QMessageBox.warning(
                self, "未找到文件",
                f"在以下位置仍未检测到 ffmpeg.exe：\n{self.target_bin_dir}\n\n请确认已将 ffmpeg.exe 和 ffprobe.exe 复制到该文件夹中。"
            )

    def _open_bin_folder(self):
        os.makedirs(self.target_bin_dir, exist_ok=True)
        openFolder(self.target_bin_dir)

    def _start_download(self):
        self.btn_auto_download.setEnabled(False)
        self.btn_open_bin.setEnabled(False)
        self.btn_recheck.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_text.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_text.setText("准备开始下载...")

        self.download_thread = FFmpegDownloadThread(self.target_bin_dir)
        self.download_thread.progress_changed.connect(self._on_progress)
        self.download_thread.download_finished.connect(self._on_finished)
        self.download_thread.start()

    def _on_progress(self, percent: int, text: str):
        self.progress_bar.setValue(percent)
        self.progress_text.setText(text)

    def _on_finished(self, success: bool, msg: str):
        self.btn_open_bin.setEnabled(True)
        self.btn_recheck.setEnabled(True)
        if success:
            self._check_status()
            QMessageBox.information(self, "安装成功", msg)
        else:
            self.btn_auto_download.setEnabled(True)
            self.progress_text.setText(f"❌ {msg}")
            QMessageBox.warning(
                self, "下载遇到问题",
                f"{msg}\n\n建议点击【方式二：打开插件 bin 文件夹】，直接手动放入下载好的 ffmpeg.exe 与 ffprobe.exe。"
            )

    def reject(self):
        if self.download_thread and self.download_thread.isRunning():
            self.download_thread.cancel()
            self.download_thread.wait(2000)
        super().reject()


def ensure_ffmpeg(parent=None) -> bool:
    """Check if FFmpeg is available; if not, show the wizard dialog."""
    if is_ffmpeg_available():
        return True

    dlg = FFmpegSetupDialog(parent)
    dlg.exec()
    return is_ffmpeg_available()

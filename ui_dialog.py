# -*- coding: utf-8 -*-
"""
AnkiSub - UI Dialog (PyQt6)
Main graphical interface for video/subtitle selection, embedded stream probing,
preview table with selection, and batch slicing execution.
"""

import os
from typing import List, Dict, Optional

from aqt import mw
from aqt.qt import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox, QSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QFileDialog, QMessageBox, Qt, QAbstractItemView, QRadioButton
)

from .sub_parser import (
    parse_subtitle_file, parse_subtitles_from_text,
    merge_adjacent_subtitles, filter_noise_subtitles,
    align_bilingual_subtitles, ms_to_time, time_to_ms
)
from .ffmpeg_worker import (
    is_ffmpeg_available, probe_embedded_subtitles,
    extract_embedded_subtitle, BatchCutWorker, refresh_binary_paths
)
from .ffmpeg_downloader import ensure_ffmpeg, FFmpegSetupDialog


class AnkiSubDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AnkiSub - 影视切片制卡")
        self.setMinimumSize(920, 680)
        self.resize(980, 720)

        self.parsed_items: List[Dict] = []
        self.embedded_tracks: List[Dict] = []
        self.worker: Optional[BatchCutWorker] = None

        self._load_config()
        self._init_ui()
        self._check_ffmpeg()

    def _load_config(self):
        config = mw.addonManager.getConfig(__name__) or {}
        self.cfg_pad_before = config.get("audio_pad_before", 200)
        self.cfg_pad_after = config.get("audio_pad_after", 200)
        self.cfg_screenshot_width = config.get("screenshot_width", 320)
        self.cfg_merge_adjacent = config.get("merge_adjacent", True)
        self.cfg_merge_gap_ms = config.get("merge_gap_ms", 400)
        self.cfg_filter_noise = config.get("filter_noise", True)
        self.cfg_default_model = config.get("default_model", "AnkiSub (Audio+Image)")

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # 1. Top Section: File & Track Inputs
        input_group = QGroupBox("输入源与目标设置")
        input_layout = QGridLayout(input_group)
        input_layout.setColumnStretch(1, 1)

        # Video selector
        input_layout.addWidget(QLabel("视频文件:"), 0, 0)
        self.edit_video = QLineEdit()
        self.edit_video.setPlaceholderText("选择或拖入视频文件 (MP4, MKV, WEBM 等)...")
        input_layout.addWidget(self.edit_video, 0, 1)
        self.btn_browse_video = QPushButton("浏览...")
        self.btn_browse_video.clicked.connect(self._on_browse_video)
        input_layout.addWidget(self.btn_browse_video, 0, 2)

        # Subtitle 1 (Primary / Target Language)
        input_layout.addWidget(QLabel("主字幕 (原文):"), 1, 0)
        sub1_row = QHBoxLayout()
        self.combo_sub1_source = QComboBox()
        self.combo_sub1_source.addItems(["外挂字幕文件", "视频内嵌字幕轨"])
        self.combo_sub1_source.currentIndexChanged.connect(self._on_sub1_source_changed)
        sub1_row.addWidget(self.combo_sub1_source)

        self.edit_sub1 = QLineEdit()
        self.edit_sub1.setPlaceholderText("选择外挂字幕文件 (SRT, ASS, VTT)...")
        sub1_row.addWidget(self.edit_sub1)

        self.combo_sub1_embedded = QComboBox()
        self.combo_sub1_embedded.setVisible(False)
        sub1_row.addWidget(self.combo_sub1_embedded)

        input_layout.addLayout(sub1_row, 1, 1)
        self.btn_browse_sub1 = QPushButton("浏览...")
        self.btn_browse_sub1.clicked.connect(self._on_browse_sub1)
        input_layout.addWidget(self.btn_browse_sub1, 1, 2)

        # Subtitle 2 (Secondary / Translation)
        self.check_enable_sub2 = QCheckBox("启用双语 (译文):")
        self.check_enable_sub2.stateChanged.connect(self._on_sub2_toggle)
        input_layout.addWidget(self.check_enable_sub2, 2, 0)

        sub2_row = QHBoxLayout()
        self.combo_sub2_source = QComboBox()
        self.combo_sub2_source.addItems(["外挂字幕文件", "视频内嵌字幕轨"])
        self.combo_sub2_source.setEnabled(False)
        self.combo_sub2_source.currentIndexChanged.connect(self._on_sub2_source_changed)
        sub2_row.addWidget(self.combo_sub2_source)

        self.edit_sub2 = QLineEdit()
        self.edit_sub2.setPlaceholderText("可选：选择第二语言字幕文件...")
        self.edit_sub2.setEnabled(False)
        sub2_row.addWidget(self.edit_sub2)

        self.combo_sub2_embedded = QComboBox()
        self.combo_sub2_embedded.setVisible(False)
        self.combo_sub2_embedded.setEnabled(False)
        sub2_row.addWidget(self.combo_sub2_embedded)

        input_layout.addLayout(sub2_row, 2, 1)
        self.btn_browse_sub2 = QPushButton("浏览...")
        self.btn_browse_sub2.setEnabled(False)
        self.btn_browse_sub2.clicked.connect(self._on_browse_sub2)
        input_layout.addWidget(self.btn_browse_sub2, 2, 2)

        # Deck Selection: New Deck vs Existing Deck
        input_layout.addWidget(QLabel("目标牌组:"), 3, 0)
        deck_target_row = QHBoxLayout()
        self.radio_new_deck = QRadioButton("新建牌组:")
        self.radio_new_deck.setChecked(True)
        self.radio_new_deck.toggled.connect(self._on_deck_mode_changed)
        deck_target_row.addWidget(self.radio_new_deck)

        self.edit_new_deck = QLineEdit()
        self.edit_new_deck.setPlaceholderText("新建牌组名称 (选视频后自动填入电影名)...")
        deck_target_row.addWidget(self.edit_new_deck, 2)

        self.radio_existing_deck = QRadioButton("已有牌组:")
        self.radio_existing_deck.toggled.connect(self._on_deck_mode_changed)
        deck_target_row.addWidget(self.radio_existing_deck)

        self.combo_deck = QComboBox()
        self._populate_decks()
        self.combo_deck.setEnabled(False)
        deck_target_row.addWidget(self.combo_deck, 2)

        input_layout.addLayout(deck_target_row, 3, 1, 1, 2)

        # Model Selection
        input_layout.addWidget(QLabel("卡片模板:"), 4, 0)
        self.combo_model = QComboBox()
        self._populate_models()
        input_layout.addWidget(self.combo_model, 4, 1, 1, 2)

        main_layout.addWidget(input_group)

        # 2. Options Section
        opt_group = QGroupBox("参数微调")
        opt_layout = QHBoxLayout(opt_group)

        opt_layout.addWidget(QLabel("音频前缓冲:"))
        self.spin_pad_before = QSpinBox()
        self.spin_pad_before.setRange(0, 2000)
        self.spin_pad_before.setSingleStep(50)
        self.spin_pad_before.setValue(self.cfg_pad_before)
        self.spin_pad_before.setSuffix(" ms")
        opt_layout.addWidget(self.spin_pad_before)

        opt_layout.addWidget(QLabel("后缓冲:"))
        self.spin_pad_after = QSpinBox()
        self.spin_pad_after.setRange(0, 2000)
        self.spin_pad_after.setSingleStep(50)
        self.spin_pad_after.setValue(self.cfg_pad_after)
        self.spin_pad_after.setSuffix(" ms")
        opt_layout.addWidget(self.spin_pad_after)

        opt_layout.addWidget(QLabel("截图宽度:"))
        self.spin_img_width = QSpinBox()
        self.spin_img_width.setRange(320, 1920)
        self.spin_img_width.setSingleStep(80)
        self.spin_img_width.setValue(self.cfg_screenshot_width)
        self.spin_img_width.setSuffix(" px")
        opt_layout.addWidget(self.spin_img_width)

        self.check_filter_noise = QCheckBox("过滤背景音效标签")
        self.check_filter_noise.setChecked(self.cfg_filter_noise)
        opt_layout.addWidget(self.check_filter_noise)

        self.check_merge_adjacent = QCheckBox("合并临近碎句 (<=400ms)")
        self.check_merge_adjacent.setChecked(self.cfg_merge_adjacent)
        opt_layout.addWidget(self.check_merge_adjacent)

        opt_layout.addStretch()

        self.btn_ffmpeg_env = QPushButton("⚙️ FFmpeg 环境")
        self.btn_ffmpeg_env.setToolTip("查看或一键配置 FFmpeg 运行组件（无需配置环境变量）")
        self.btn_ffmpeg_env.clicked.connect(self._open_ffmpeg_setup)
        opt_layout.addWidget(self.btn_ffmpeg_env)

        main_layout.addWidget(opt_group)

        # 3. Action bar above Table
        table_action_layout = QHBoxLayout()
        self.btn_parse = QPushButton("🔍 解析字幕并预览")
        self.btn_parse.setStyleSheet("font-weight: bold; padding: 6px 16px;")
        self.btn_parse.clicked.connect(self._on_parse_subtitles)
        table_action_layout.addWidget(self.btn_parse)

        self.lbl_stats = QLabel("尚未解析字幕")
        table_action_layout.addWidget(self.lbl_stats)

        table_action_layout.addStretch()

        self.btn_select_all = QPushButton("全选")
        self.btn_select_all.clicked.connect(lambda: self._set_all_selection(True))
        table_action_layout.addWidget(self.btn_select_all)

        self.btn_deselect_all = QPushButton("全不选")
        self.btn_deselect_all.clicked.connect(lambda: self._set_all_selection(False))
        table_action_layout.addWidget(self.btn_deselect_all)

        self.btn_invert_select = QPushButton("反选")
        self.btn_invert_select.clicked.connect(self._invert_selection)
        table_action_layout.addWidget(self.btn_invert_select)

        main_layout.addLayout(table_action_layout)

        # 4. Preview Table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["选择", "序号", "时间范围", "原文", "译文"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        main_layout.addWidget(self.table, 1)

        # 5. Bottom Controls & Progress
        bottom_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        bottom_layout.addWidget(self.progress_bar, 1)

        self.btn_start = QPushButton("🚀 开始切片制卡")
        self.btn_start.setStyleSheet("font-weight: bold; font-size: 14px; padding: 8px 24px; background-color: #2e7d32; color: white;")
        self.btn_start.clicked.connect(self._on_start_cut)
        bottom_layout.addWidget(self.btn_start)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._on_cancel_worker)
        bottom_layout.addWidget(self.btn_cancel)

        main_layout.addLayout(bottom_layout)

    def _open_ffmpeg_setup(self):
        dlg = FFmpegSetupDialog(self)
        dlg.exec()

    def _check_ffmpeg(self):
        if not is_ffmpeg_available():
            ensure_ffmpeg(self)

    def _populate_decks(self):
        self.combo_deck.clear()
        decks = sorted(mw.col.decks.all_names_and_ids(), key=lambda d: d.name)
        for d in decks:
            self.combo_deck.addItem(d.name, d.id)

    def _populate_models(self):
        self.combo_model.clear()
        models = sorted(mw.col.models.all_names_and_ids(), key=lambda m: m.name)
        target_idx = 0
        for idx, m in enumerate(models):
            self.combo_model.addItem(m.name, m.id)
            if m.name == self.cfg_default_model:
                target_idx = idx
        self.combo_model.setCurrentIndex(target_idx)

    def _on_deck_mode_changed(self):
        is_new = self.radio_new_deck.isChecked()
        self.edit_new_deck.setEnabled(is_new)
        self.combo_deck.setEnabled(not is_new)

    def _on_browse_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择视频文件",
            "",
            "视频文件 (*.mp4 *.mkv *.webm *.avi *.mov *.flv *.ts);;所有文件 (*.*)"
        )
        if path:
            self.edit_video.setText(path)
            self._probe_video_subtitles(path)
            movie_title = os.path.splitext(os.path.basename(path))[0]
            if not self.edit_new_deck.text() or self.radio_new_deck.isChecked():
                self.edit_new_deck.setText(movie_title)

    def _probe_video_subtitles(self, video_path: str):
        """Probe video for embedded subtitle tracks."""
        self.embedded_tracks = probe_embedded_subtitles(video_path)
        self.combo_sub1_embedded.clear()
        self.combo_sub2_embedded.clear()

        if self.embedded_tracks:
            for t in self.embedded_tracks:
                item_label = f"轨道 {t['sub_index'] + 1} [{t['lang']}] {t['title']} ({t['codec']})"
                self.combo_sub1_embedded.addItem(item_label, t['sub_index'])
                self.combo_sub2_embedded.addItem(item_label, t['sub_index'])
            
            # Switch to embedded if external not specified
            if not self.edit_sub1.text():
                self.combo_sub1_source.setCurrentIndex(1)
        else:
            self.combo_sub1_source.setCurrentIndex(0)

    def _on_sub1_source_changed(self, idx: int):
        is_embedded = (idx == 1)
        self.edit_sub1.setVisible(not is_embedded)
        self.btn_browse_sub1.setVisible(not is_embedded)
        self.combo_sub1_embedded.setVisible(is_embedded)

    def _on_sub2_source_changed(self, idx: int):
        is_embedded = (idx == 1)
        self.edit_sub2.setVisible(not is_embedded)
        self.btn_browse_sub2.setVisible(not is_embedded)
        self.combo_sub2_embedded.setVisible(is_embedded)

    def _on_sub2_toggle(self, state: int):
        enabled = (state == Qt.CheckState.Checked.value or state == 2)
        self.combo_sub2_source.setEnabled(enabled)
        self.edit_sub2.setEnabled(enabled)
        self.combo_sub2_embedded.setEnabled(enabled)
        self.btn_browse_sub2.setEnabled(enabled)

    def _on_browse_sub1(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择主字幕文件",
            "",
            "所有字幕 (*.srt *.vtt *.ass *.ssa);;WebVTT 字幕 (*.vtt);;SubRip 字幕 (*.srt);;ASS/SSA 字幕 (*.ass *.ssa);;所有文件 (*.*)"
        )
        if path:
            self.edit_sub1.setText(path)

    def _on_browse_sub2(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择副字幕文件 (译文)",
            "",
            "所有字幕 (*.srt *.vtt *.ass *.ssa);;WebVTT 字幕 (*.vtt);;SubRip 字幕 (*.srt);;ASS/SSA 字幕 (*.ass *.ssa);;所有文件 (*.*)"
        )
        if path:
            self.edit_sub2.setText(path)

    def _get_sub_items(self, is_primary: bool) -> List[Dict]:
        """Fetch and parse subtitle items based on UI settings."""
        video_path = self.edit_video.text().strip()
        source_combo = self.combo_sub1_source if is_primary else self.combo_sub2_source
        is_embedded = (source_combo.currentIndex() == 1)

        if is_embedded:
            if not video_path or not os.path.exists(video_path):
                return []
            embedded_combo = self.combo_sub1_embedded if is_primary else self.combo_sub2_embedded
            track_idx = embedded_combo.currentData()
            if track_idx is None:
                return []
            srt_content = extract_embedded_subtitle(video_path, track_idx)
            if not srt_content:
                return []
            sub_format = "vtt" if "WEBVTT" in srt_content else "srt"
            return parse_subtitles_from_text(srt_content, sub_format)
        else:
            file_edit = self.edit_sub1 if is_primary else self.edit_sub2
            path = file_edit.text().strip()
            if not path or not os.path.exists(path):
                return []
            return parse_subtitle_file(path)

    def _on_parse_subtitles(self):
        video_path = self.edit_video.text().strip()
        if not video_path or not os.path.exists(video_path):
            QMessageBox.warning(self, "提示", "请先选择有效的视频文件！")
            return

        self.btn_parse.setEnabled(False)
        self.lbl_stats.setText("正在读取并解析字幕...")

        try:
            # 1. Parse primary
            primary_items = self._get_sub_items(is_primary=True)
            if not primary_items:
                QMessageBox.warning(self, "解析失败", "未能从主字幕中解析出有效内容，请检查字幕文件或选择正确的字幕轨。")
                self.btn_parse.setEnabled(True)
                self.lbl_stats.setText("解析失败")
                return

            # 2. Noise filter
            if self.check_filter_noise.isChecked():
                primary_items = filter_noise_subtitles(primary_items)

            # 3. Merge adjacent
            if self.check_merge_adjacent.isChecked():
                primary_items = merge_adjacent_subtitles(primary_items, self.cfg_merge_gap_ms)

            # 4. Secondary subtitles (Translation)
            secondary_items = []
            if self.check_enable_sub2.isChecked():
                secondary_items = self._get_sub_items(is_primary=False)
                if self.check_filter_noise.isChecked():
                    secondary_items = filter_noise_subtitles(secondary_items)

            # 5. Align
            self.parsed_items = align_bilingual_subtitles(primary_items, secondary_items)

            # 6. Populate Table
            self._render_table()

        finally:
            self.btn_parse.setEnabled(True)

    def _render_table(self):
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.parsed_items))

        for row, item in enumerate(self.parsed_items):
            # Checkbox item
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            check_item.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(row, 0, check_item)

            # Index
            idx_item = QTableWidgetItem(str(row + 1))
            idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 1, idx_item)

            # Time range
            time_str = f"{ms_to_time(item['start_ms'])} ~ {ms_to_time(item['end_ms'])}"
            time_item = QTableWidgetItem(time_str)
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 2, time_item)

            # Text
            text_item = QTableWidgetItem(item['text'])
            self.table.setItem(row, 3, text_item)

            # Translation
            trans_item = QTableWidgetItem(item.get('translation', ''))
            self.table.setItem(row, 4, trans_item)

        total = len(self.parsed_items)
        self.lbl_stats.setText(f"共解析出 {total} 句 (默认已全选)")

    def _set_all_selection(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                item.setCheckState(state)
        self._update_selected_count_label()

    def _invert_selection(self):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                new_state = Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked
                item.setCheckState(new_state)
        self._update_selected_count_label()

    def _update_selected_count_label(self):
        selected_count = sum(
            1 for r in range(self.table.rowCount())
            if self.table.item(r, 0) and self.table.item(r, 0).checkState() == Qt.CheckState.Checked
        )
        total = self.table.rowCount()
        self.lbl_stats.setText(f"共 {total} 句 (已选中 {selected_count} 句)")

    def _on_start_cut(self):
        if not is_ffmpeg_available():
            if not ensure_ffmpeg(self):
                return

        video_path = self.edit_video.text().strip()
        if not video_path or not os.path.exists(video_path):
            QMessageBox.warning(self, "错误", "视频文件无效或不存在！")
            return

        # Gather selected items
        selected_items = []
        for row in range(self.table.rowCount()):
            chk = self.table.item(row, 0)
            if chk and chk.checkState() == Qt.CheckState.Checked:
                selected_items.append(self.parsed_items[row])

        if not selected_items:
            QMessageBox.warning(self, "提示", "请至少勾选一条需要制卡的句子！")
            return

        if self.radio_new_deck.isChecked():
            deck_name = self.edit_new_deck.text().strip()
            if not deck_name:
                QMessageBox.warning(self, "提示", "请输入新建牌组的名称！")
                return
            deck_id = mw.col.decks.id(deck_name)
            self._populate_decks()
        else:
            deck_id = self.combo_deck.currentData()
            if not deck_id:
                deck_id = 1

        model_name = self.combo_model.currentText()

        # Update UI state for processing
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_parse.setEnabled(False)
        self.progress_bar.setValue(0)

        # Launch Worker Thread
        self.worker = BatchCutWorker(
            video_path=video_path,
            items=selected_items,
            deck_id=deck_id,
            model_name=model_name,
            audio_pad_before=self.spin_pad_before.value(),
            audio_pad_after=self.spin_pad_after.value(),
            screenshot_width=self.spin_img_width.value(),
            source_name=os.path.splitext(os.path.basename(video_path))[0]
        )
        self.worker.progress.connect(self._on_worker_progress)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.cancelled.connect(self._on_worker_cancelled)
        self.worker.start()

    def _on_worker_progress(self, current: int, total: int, text: str):
        pct = int(current / total * 100)
        self.progress_bar.setValue(pct)
        self.progress_bar.setFormat(f"正在处理 ({current}/{total}): {text}")

    def _on_worker_finished(self, success_cnt: int, fail_cnt: int, errors: List[str]):
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.btn_parse.setEnabled(True)
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat(f"完成！成功: {success_cnt}, 失败: {fail_cnt}")

        mw.reset()  # Refresh Anki reviewer / deck counters

        msg = f"制卡完成！\n\n成功生成: {success_cnt} 张卡片\n失败: {fail_cnt} 条"
        if errors:
            msg += "\n\n部分失败原因示例:\n" + "\n".join(errors[:5])
        QMessageBox.information(self, "切片制卡结果", msg)

    def _on_worker_cancelled(self):
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.btn_parse.setEnabled(True)
        self.progress_bar.setFormat("用户已取消操作")
        mw.reset()
        QMessageBox.information(self, "提示", "切片操作已中断。已生成的卡片已保存在牌组中。")

    def _on_cancel_worker(self):
        if self.worker and self.worker.isRunning():
            self.btn_cancel.setEnabled(False)
            self.progress_bar.setFormat("正在停止中...")
            self.worker.cancel()

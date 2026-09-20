# AnkiSub - Video & Audio Subtitle Slicer for Anki

<p align="center">
  <b>Fast, lightweight subtitle-based card generator for language immersion (Audio + Screenshot).</b><br>
  Designed for Anki 23.10 ~ 26.x+ (Qt6 / Python 3.9 ~ 3.13) | Windows, macOS, Linux
</p>

<p align="center">
  <a href="#english"><b>🇬🇧 English</b></a> | <a href="#chinese"><b>🇨🇳 简体中文</b></a>
</p>

---

<a id="english"></a>
## 🇬🇧 English Documentation

### What AnkiSub Does

AnkiSub is a clean, modern Anki add-on that turns movies, TV shows, and audiobooks into effective flashcards. Each card is packed with **crystal-clear 128kbps MP3 audio** and a **compact cover screenshot (JPG)**.

- **Cross-Platform Ready**: Generated media files are stored directly in your native `collection.media` folder. Once synced via AnkiWeb, your cards work seamlessly on **iOS (AnkiMobile)**, **Android (AnkiDroid)**, and **Desktop (Windows / macOS / Linux)** without any secondary conversion.
- **Wide Format Support**:
  - Video: `MP4`, `MKV`, `WEBM`, `AVI`, `MOV`, `TS`, `FLV`, etc.
  - Subtitles: `.srt`, `.vtt`, `.ass`, `.ssa`.
  - **Embedded Subtitles**: Directly reads and extracts internal subtitle tracks from MKV/MP4 files without requiring manual subtitle extraction tools.
- **Bilingual Subtitle Alignment**: Automatically matches primary dialogue (target language) with secondary dialogue (translation) using timestamp overlap analysis.
- **Smart Acoustic Padding & Cleaning**:
  - 200ms padding before and after each segment to prevent clipped audio.
  - Automatic filtering of sound effect tags such as `♪`, `[Music]`, `(Laughter)`, etc.
  - Merges adjacent dialogue fragments (gap $\le$ 400ms) into cohesive sentences.
- **Visual Preview & Flexible Decks**:
  - Interactive table previewing timestamps, original dialogue, and translations.
  - Batch selection with Select All, Deselect All, and Invert Selection.
  - "New Deck" mode (automatically names the deck after your movie file) or "Existing Deck" mode.
- **Thoughtful Card Template (`AnkiSub (Audio+Image)`)**:
  - **Front**: 320px compact screenshot + Left-aligned dialogue (21px font).
  - **Back**: Screenshot + dialogue + auto-playing MP3 audio + translation + optional `Words` and `Notes` fields.
  - **Editor Convenience**: `Words` and `Notes` fields are positioned directly below `Expression` for quick note-taking during reviews (shortcut: `E`).
  - Native Dark Mode support.
- **Zero-Config FFmpeg Experience**:
  - Automatically locates the FFmpeg binaries bundled with official Anki on Windows.
  - Supports portable drop-in via the add-on's `bin/` folder.
  - Includes a built-in one-click auto-downloader wizard if FFmpeg is missing—**no manual Windows PATH or environment variable editing required**.

---

### How to Use

1. In Anki, click the top menu bar: **Tools $\to$ AnkiSub 影视切片制卡...**
2. **Select your video file** (embedded subtitle tracks will be automatically listed).
3. **Select your subtitle source** (external file or embedded track; optionally enable bilingual translation).
4. Choose or create a target deck (defaults to the video filename).
5. Click **"🔍 解析字幕并预览 (Parse & Preview)"** to view and filter sentences.
6. Click **"🚀 开始切片制卡 (Start Slicing)"**. Media cutting runs asynchronously in the background.

---

### Installation

- **Via AnkiWeb**:
  1. Open Anki $\to$ **Tools** $\to$ **Add-ons** $\to$ **Get Add-ons...**
  2. Enter the AnkiSub Add-on code (released on AnkiWeb) and click OK.
- **Via Offline Package**:
  - Download `AnkiSub_v1.0.0_Windows_Full.ankiaddon` from GitHub Releases and double-click to install.

---

<p align="right"><a href="#english">⬆️ Back to Top</a></p>

<hr>

<a id="chinese"></a>
## 🇨🇳 简体中文说明

### AnkiSub 能做什么

**AnkiSub** 是一款轻量、现代化的影视与播客字幕切片制卡插件。它将影视对白高效转化为高价值的复习卡片，每张卡片均包含**高品质 128kbps MP3 原声音频**与**紧凑居中封面截图 (JPG)**。

- **多端无缝同步**：生成的媒体文件直接保存在 Anki 原生媒体库（`collection.media`）中。一键同步后，在 **iPhone / iPad (AnkiMobile)**、**安卓手机 (AnkiDroid)** 与 **电脑桌面端** 均可开箱即用，无需二次格式转换。
- **全格式与内嵌字幕支持**：
  - 视频支持：`MP4`, `MKV`, `WEBM`, `AVI`, `MOV`, `TS`, `FLV` 等主流格式。
  - 外挂字幕：`.srt`, `.vtt`, `.ass`, `.ssa`。
  - **内嵌字幕免提取**：直接读取 MKV / MP4 封装内的多语言字幕轨，省去繁琐的手动解包步骤。
- **双语智能对齐**：支持同时导入原文主字幕与译文次字幕，基于时间轴交集重叠算法自动精确配对。
- **智能防吃字与降噪**：
  - 默认前后增加 200ms 防吃字声学缓冲，发音清晰完整。
  - 自动过滤 `♪`、`[Music]`、`(Laughter)` 等背景音效噪声标签。
  - 智能合并时间间隔 $\le$ 400ms 的邻近碎句，保证语意连贯。
- **可视化预览与专属牌组**：
  - 切片前在表格中预览全部句子、时间戳、原文与译文，支持全选、全不选与反选。
  - 支持“新建牌组”与“已有牌组”一键切换，选择视频后**自动以影视文件名作为默认牌组名**。
- **精心设计的卡片模板 (`AnkiSub (Audio+Image)`)**：
  - **正面**：320px 紧凑高清截图 + 原文字幕（21px 优雅左对齐排版），专注听力或阅读理解。
  - **背面**：截图 + 原文字幕 + **翻面自动播放原声发音** + 中文翻译 + 专属生词与笔记字段。
  - **极速记录笔记**：在卡片编辑页面中，`Words`（生词）与 `Notes`（笔记）已排在 `Expression` 正下方，复习时按快捷键 `E` 即可秒速输入心得（未填写内容时在卡片上自动隐藏）。
  - 完美适配深色模式（Dark Mode）。
- **零门槛 FFmpeg 体验（彻底告别配置环境变量）**：
  - 自动识别 Windows 官方安装版 Anki 自带的 FFmpeg 组件，打开即用。
  - 内部保留 `bin/` 文件夹，支持免配 PATH 直接放入。
  - 若环境缺失，内置**【一键自动下载并配置向导】**，全程无需手动修改系统环境变量。

---

### 如何使用

1. 打开 Anki 顶部菜单栏：**工具 (Tools) $\to$ AnkiSub 影视切片制卡...**
2. **选择视频文件**（若含内嵌字幕将自动识别列出字幕轨）。
3. **选择字幕来源**（外挂文件或内嵌字幕轨，可选开启第二语言译文）。
4. 选择或新建目标牌组（默认自动预填视频名）。
5. 点击 **“🔍 解析字幕并预览”**，在列表中勾选想要制作的句子。
6. 点击 **“🚀 开始切片制卡”**，等待后台异步处理完成即可！

---

### 安装方式

- **方式一：通过 AnkiWeb 官方代码一键安装**
  - 打开 Anki $\to$ **工具** $\to$ **附加组件** $\to$ **获取插件...** $\to$ 输入 AnkiSub 插件代码。
- **方式二：离线全包版安装**
  - 在 GitHub Releases 下载 `AnkiSub_v1.0.0_Windows_Full.ankiaddon`，双击或在附加组件窗口中点击“从文件安装”即可。

---

<p align="right"><a href="#chinese">⬆️ 回到中文顶部</a> | <a href="#english">🇬🇧 Back to English Top</a></p>

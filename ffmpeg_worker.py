# -*- coding: utf-8 -*-
"""
AnkiSub - FFmpeg Worker & Media Processor
Handles locating FFmpeg/FFprobe, probing embedded subtitles,
extracting subtitle streams, and batch-cutting audio & screenshots via QThread.
"""

import os
import re
import json
import shutil
import subprocess
from typing import List, Dict, Optional, Tuple

from aqt.qt import QThread, pyqtSignal
from aqt import mw

# Windows flag to prevent black CMD windows from popping up
CREATE_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0


def find_binary(binary_name: str) -> Optional[str]:
    """Find executable path for ffmpeg or ffprobe."""
    # 1. Plugin internal bin directory (zero-config portable / auto-downloaded)
    addon_dir = os.path.dirname(os.path.abspath(__file__))
    ext = ".exe" if os.name == "nt" else ""
    local_bin = os.path.join(addon_dir, "bin", f"{binary_name}{ext}")
    if os.path.isfile(local_bin):
        return local_bin

    # 2. System PATH
    found = shutil.which(binary_name)
    if found:
        return found
    
    # 3. Anki bundled directory on Windows
    local_app_data = os.environ.get('LOCALAPPDATA', '')
    candidates = [
        os.path.join(local_app_data, 'Programs', 'Anki', 'ffmpeg', 'bin', f'{binary_name}.exe'),
        os.path.join(local_app_data, 'Programs', 'Anki', f'{binary_name}.exe'),
        rf'C:\Program Files\Anki\ffmpeg\bin\{binary_name}.exe',
        rf'C:\Program Files\Anki\{binary_name}.exe',
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
            
    return None


FFMPEG_PATH = find_binary("ffmpeg")
FFPROBE_PATH = find_binary("ffprobe")


def refresh_binary_paths() -> Tuple[Optional[str], Optional[str]]:
    """Refresh FFMPEG_PATH and FFPROBE_PATH dynamically."""
    global FFMPEG_PATH, FFPROBE_PATH
    FFMPEG_PATH = find_binary("ffmpeg")
    FFPROBE_PATH = find_binary("ffprobe")
    return FFMPEG_PATH, FFPROBE_PATH


def is_ffmpeg_available() -> bool:
    """Check if ffmpeg executable is ready."""
    refresh_binary_paths()
    return FFMPEG_PATH is not None and os.path.isfile(FFMPEG_PATH)


def probe_embedded_subtitles(video_path: str) -> List[Dict]:
    """
    Use ffprobe to inspect embedded subtitle streams in video file.
    Returns list of dicts: [{'stream_index': int, 'sub_index': int, 'title': str, 'lang': str, 'codec': str}]
    """
    ffprobe = FFPROBE_PATH or find_binary("ffprobe")
    if not ffprobe or not os.path.exists(video_path):
        return []

    cmd = [
        ffprobe,
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-select_streams", "s",
        video_path
    ]

    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore',
            creationflags=CREATE_NO_WINDOW
        )
        if res.returncode != 0 or not res.stdout:
            return []

        data = json.loads(res.stdout)
        streams = data.get("streams", [])
        results = []
        for idx, s in enumerate(streams):
            tags = s.get("tags", {})
            lang = tags.get("language", tags.get("lang", "und"))
            title = tags.get("title", f"Track {idx + 1}")
            codec = s.get("codec_name", "sub")
            results.append({
                'sub_index': idx,               # 0-indexed among subtitle streams (for 0:s:{sub_index})
                'stream_index': s.get('index'), # overall container stream index
                'title': title,
                'lang': lang,
                'codec': codec
            })
        return results
    except Exception as e:
        print(f"[AnkiSub] probe_embedded_subtitles error: {e}")
        return []


def extract_embedded_subtitle(video_path: str, sub_stream_index: int) -> Optional[str]:
    """
    Extract embedded subtitle stream into string content via ffmpeg.
    Uses SRT format output pipe, falling back to WebVTT if needed.
    """
    ffmpeg = FFMPEG_PATH or find_binary("ffmpeg")
    if not ffmpeg:
        return None

    for fmt in ["srt", "webvtt"]:
        cmd = [
            ffmpeg,
            "-y",
            "-i", video_path,
            "-map", f"0:s:{sub_stream_index}",
            "-f", fmt,
            "-"
        ]

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                creationflags=CREATE_NO_WINDOW
            )
            if res.returncode == 0 and res.stdout and res.stdout.strip():
                return res.stdout
        except Exception as e:
            print(f"[AnkiSub] extract_embedded_subtitle ({fmt}) error: {e}")
            
    return None


def sanitize_filename(name: str) -> str:
    """Sanitize string to be safe as file basename."""
    name = re.sub(r'[\\/*?:"<>|]', '_', name)
    name = re.sub(r'\s+', '_', name).strip('._')
    return name[:60] if len(name) > 60 else name


def cut_audio_and_image(
    video_path: str,
    start_ms: int,
    end_ms: int,
    base_filename: str,
    audio_pad_before_ms: int = 200,
    audio_pad_after_ms: int = 200,
    screenshot_width: int = 720,
    media_dir: Optional[str] = None
) -> Tuple[Optional[str], Optional[str]]:
    """
    Cuts audio to MP3 and takes screenshot at midpoint to JPG.
    Files are saved into media_dir (Anki collection.media).
    Returns (audio_filename, image_filename) or None on failure.
    """
    ffmpeg = FFMPEG_PATH or find_binary("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg executable not found!")

    if not media_dir:
        media_dir = mw.col.media.dir()

    # 1. Calculate audio cut time with padding
    pad_start_ms = max(0, start_ms - audio_pad_before_ms)
    pad_end_ms = end_ms + audio_pad_after_ms
    start_sec = pad_start_ms / 1000.0
    end_sec = pad_end_ms / 1000.0
    duration_sec = end_sec - start_sec

    # Midpoint for screenshot
    mid_sec = (start_ms + end_ms) / 2000.0

    audio_file = f"{base_filename}.mp3"
    image_file = f"{base_filename}.jpg"
    audio_path = os.path.join(media_dir, audio_file)
    image_path = os.path.join(media_dir, image_file)

    # Cut Audio
    # -ss before -i for fast seek
    cmd_audio = [
        ffmpeg, "-y",
        "-ss", f"{start_sec:.3f}",
        "-t", f"{duration_sec:.3f}",
        "-i", video_path,
        "-vn",
        "-c:a", "libmp3lame",
        "-b:a", "128k",
        "-ar", "44100",
        audio_path
    ]
    res_audio = subprocess.run(cmd_audio, capture_output=True, creationflags=CREATE_NO_WINDOW)
    if res_audio.returncode != 0 or not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
        return None, None

    # Cut Screenshot
    cmd_image = [
        ffmpeg, "-y",
        "-ss", f"{mid_sec:.3f}",
        "-i", video_path,
        "-vframes", "1",
        "-vf", f"scale='min({screenshot_width}\\,iw)':-2",
        "-q:v", "3",
        image_path
    ]
    res_image = subprocess.run(cmd_image, capture_output=True, creationflags=CREATE_NO_WINDOW)
    if res_image.returncode != 0 or not os.path.exists(image_path) or os.path.getsize(image_path) == 0:
        # If image fails, audio might still be valid, but image is None
        image_file = None

    return audio_file, image_file


class BatchCutWorker(QThread):
    """
    Background worker thread to perform media cutting and Anki card creation
    without freezing the user interface.
    """
    progress = pyqtSignal(int, int, str)       # (current_idx, total_count, current_text)
    finished = pyqtSignal(int, int, list)      # (success_count, fail_count, error_list)
    cancelled = pyqtSignal()

    def __init__(
        self,
        video_path: str,
        items: List[Dict],
        deck_id: int,
        model_name: str,
        audio_pad_before: int = 200,
        audio_pad_after: int = 200,
        screenshot_width: int = 720,
        source_name: str = ""
    ):
        super().__init__()
        self.video_path = video_path
        self.items = items
        self.deck_id = deck_id
        self.model_name = model_name
        self.audio_pad_before = audio_pad_before
        self.audio_pad_after = audio_pad_after
        self.screenshot_width = screenshot_width
        self.source_name = source_name
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        total = len(self.items)
        if total == 0:
            self.finished.emit(0, 0, [])
            return

        media_dir = mw.col.media.dir()
        video_base = sanitize_filename(os.path.splitext(os.path.basename(self.video_path))[0])
        model = mw.col.models.by_name(self.model_name)
        if not model:
            self.finished.emit(0, total, [f"找不到模板: {self.model_name}"])
            return

        success_count = 0
        fail_count = 0
        errors = []

        for idx, item in enumerate(self.items, 1):
            if self._is_cancelled:
                self.cancelled.emit()
                return

            text = item.get('text', '')
            trans = item.get('translation', '')
            start_ms = item['start_ms']
            end_ms = item['end_ms']

            display_preview = text[:30] + ('...' if len(text) > 30 else '')
            self.progress.emit(idx, total, display_preview)

            # Generate unique base filename for media
            base_filename = f"ankisub_{video_base}_{start_ms}_{end_ms}_{idx:04d}"

            try:
                audio_file, image_file = cut_audio_and_image(
                    self.video_path,
                    start_ms,
                    end_ms,
                    base_filename,
                    self.audio_pad_before,
                    self.audio_pad_after,
                    self.screenshot_width,
                    media_dir
                )

                if not audio_file:
                    fail_count += 1
                    errors.append(f"第 {idx} 句音视频切片失败: {display_preview}")
                    continue

                # Create Anki Note
                note = mw.col.new_note(model)
                
                # Check fields available in model
                field_names = mw.col.models.field_names(model)
                
                # Assign values to fields dynamically
                if "Expression" in field_names:
                    note["Expression"] = text
                elif len(field_names) > 0:
                    note[field_names[0]] = text

                if "Translation" in field_names and trans:
                    note["Translation"] = trans
                elif "Meaning" in field_names and trans:
                    note["Meaning"] = trans

                if "Words" in field_names:
                    note["Words"] = ""
                if "Notes" in field_names:
                    note["Notes"] = ""

                if "Audio" in field_names:
                    note["Audio"] = f"[sound:{audio_file}]"

                if "Image" in field_names and image_file:
                    note["Image"] = f'<img src="{image_file}">'

                if "Source" in field_names:
                    note["Source"] = self.source_name or video_base

                if "Time" in field_names:
                    from .sub_parser import ms_to_time
                    note["Time"] = f"{ms_to_time(start_ms)} - {ms_to_time(end_ms)}"

                mw.col.add_note(note, self.deck_id)
                success_count += 1

            except Exception as e:
                fail_count += 1
                errors.append(f"第 {idx} 句生成出错: {str(e)}")

        # Done batch
        self.finished.emit(success_count, fail_count, errors)

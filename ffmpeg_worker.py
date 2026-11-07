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
    # Square/curly brackets break Anki's [sound:...] tag parsing (the first ']' ends the tag),
    # so they are removed together with characters that are illegal in file names.
    name = re.sub(r'[\\/*?:"<>|\[\]{}【】#%&\'`]', '_', name)
    name = re.sub(r'\s+', '_', name)
    name = re.sub(r'_+', '_', name).strip('._')
    return name[:60] if len(name) > 60 else name


def extract_audio_envelope(video_path: str, sample_rate: int = 4000, frame_ms: int = 10) -> Optional[Tuple[list, list, int]]:
    """
    Fast, pure-Python audio energy envelope extractor via FFmpeg.
    Decodes audio to 16-bit mono PCM and calculates smoothed RMS/amplitude envelopes
    in 10ms frames. Runs at ~200x realtime (~1.2s for a 40-minute video) without external dependencies.
    """
    import array
    ffmpeg = FFMPEG_PATH or find_binary("ffmpeg")
    if not ffmpeg or not os.path.exists(video_path):
        return None

    cmd = [
        ffmpeg, "-v", "quiet",
        "-i", video_path,
        "-vn",
        "-ac", "1",
        "-ar", str(sample_rate),
        "-f", "s16le",
        "-"
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, creationflags=CREATE_NO_WINDOW)
        if res.returncode != 0 or not res.stdout:
            return None

        pcm = array.array('h')
        pcm.frombytes(res.stdout)
        samples_per_frame = sample_rate * frame_ms // 1000
        n_frames = len(pcm) // samples_per_frame
        if n_frames < 10:
            return None

        # Sample at 2000Hz equivalent for fast pure-python amplitude calculation
        step = max(1, samples_per_frame // 20)
        sub_pcm = pcm[::step]
        sub_per_frame = max(1, samples_per_frame // step)

        envelope = [
            sum(abs(x) for x in sub_pcm[i*sub_per_frame : (i+1)*sub_per_frame]) / float(sub_per_frame)
            for i in range(n_frames)
        ]

        prefix = [0.0] * (n_frames + 1)
        for i in range(n_frames):
            prefix[i + 1] = prefix[i] + envelope[i]

        return envelope, prefix, n_frames
    except Exception as e:
        print(f"[AnkiSub] extract_audio_envelope error: {e}")
        return None


def refine_timestamps_with_audio(video_path: str, items: List[Dict]) -> List[Dict]:
    """
    Snap sentence boundary timestamps to the nearest acoustic speech silence/pause.
    Eliminates trailing words and audio bleed at cut points without external AI dependencies.
    """
    if not items or len(items) < 2:
        return items

    env_data = extract_audio_envelope(video_path)
    if not env_data:
        return items

    envelope, prefix, n_frames = env_data
    frame_ms = 10

    def win_avg(center_f: int, half_w: int) -> float:
        lo = max(0, center_f - half_w)
        hi = min(n_frames, center_f + half_w + 1)
        return (prefix[hi] - prefix[lo]) / max(1, hi - lo)

    def find_best_pause(est_ms: int, min_ms: int, max_ms: int) -> Tuple[int, int]:
        lo_f = max(0, min_ms // frame_ms)
        hi_f = min(n_frames - 1, max_ms // frame_ms)
        est_f = est_ms // frame_ms
        if lo_f >= hi_f:
            return est_ms, est_ms

        max_val = max((win_avg(f, 7) for f in range(lo_f, hi_f + 1)), default=1.0)
        if max_val < 10.0:
            return est_ms, est_ms

        silence_thresh = max(150.0, min(420.0, max_val * 0.22))
        regions = []
        in_reg = False
        r_start = lo_f
        for f in range(lo_f, hi_f + 1):
            if envelope[f] < silence_thresh:
                if not in_reg:
                    in_reg = True
                    r_start = f
            else:
                if in_reg:
                    in_reg = False
                    if f - r_start >= 6:
                        regions.append((r_start, f - 1))
        if in_reg and (hi_f + 1 - r_start) >= 6:
            regions.append((r_start, hi_f))

        span = max(1, hi_f - lo_f)
        if regions:
            best_reg = None
            best_score = -1e9
            for r_s, r_e in regions:
                r_mid = (r_s + r_e) / 2.0
                r_dur_frames = (r_e - r_s + 1)
                dur_score = min(22.0, float(r_dur_frames)) / 20.0
                diff = r_mid - est_f
                weight = 2.2 if diff < -28 else 1.0
                dist_pen = weight * 1.1 * abs(diff) / span
                avg_e = (prefix[r_e + 1] - prefix[r_s]) / r_dur_frames / max_val
                score = dur_score - dist_pen - avg_e
                if score > best_score:
                    best_score = score
                    best_reg = (r_s, r_e)
            r_s, r_e = best_reg
            pause_start_ms = r_s * frame_ms
            pause_end_ms = (r_e + 1) * frame_ms
            margin = min(40, (pause_end_ms - pause_start_ms) // 3)
            return pause_start_ms + margin, pause_end_ms - margin

        best_f = est_f
        best_score = 1e9
        for f in range(lo_f, hi_f + 1):
            norm_e = win_avg(f, 5) / max_val
            dist_pen = 0.35 * abs(f - est_f) / span
            if norm_e + dist_pen < best_score:
                best_score = norm_e + dist_pen
                best_f = f
        mid = best_f * frame_ms
        return mid, mid

    for i in range(len(items) - 1):
        s_curr = items[i]
        s_next = items[i + 1]
        est_ms = (s_curr['end_ms'] + s_next['start_ms']) // 2
        radius = 550
        min_bound = max(est_ms - radius, s_curr['start_ms'] + int((s_curr['end_ms'] - s_curr['start_ms']) * 0.35))
        max_bound = min(est_ms + radius, s_next['end_ms'] - int((s_next['end_ms'] - s_next['start_ms']) * 0.35))
        prev_end, next_start = find_best_pause(est_ms, min_bound, max_bound)
        s_curr['end_ms'] = prev_end
        s_next['start_ms'] = next_start
        s_curr['_audio_refined'] = True
        s_next['_audio_refined'] = True

    return items


def cut_audio_and_image(
    video_path: str,
    start_ms: int,
    end_ms: int,
    base_filename: str,
    audio_pad_before_ms: int = 200,
    audio_pad_after_ms: int = 200,
    screenshot_width: int = 720,
    media_dir: Optional[str] = None,
    prev_end_ms: Optional[int] = None,
    next_start_ms: Optional[int] = None,
    is_audio_refined: bool = False
) -> Tuple[Optional[str], Optional[str]]:
    """
    Cuts audio to MP3 and takes screenshot at midpoint to JPG.
    Files are saved into media_dir (Anki collection.media).
    Returns (audio_filename, image_filename) or None on failure.
    Uses neighbor-aware padding to strictly prevent audio bleed into neighboring sentences.
    """
    ffmpeg = FFMPEG_PATH or find_binary("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg executable not found!")

    if not media_dir:
        media_dir = mw.col.media.dir()

    # 1. Calculate audio cut time with smart neighbor-clamped padding
    if is_audio_refined:
        # Already aligned to silence pause: use gentle 60ms padding
        eff_pad_b = min(60, audio_pad_before_ms)
        eff_pad_a = min(60, audio_pad_after_ms)
    else:
        eff_pad_b = audio_pad_before_ms
        eff_pad_a = audio_pad_after_ms

    if prev_end_ms is not None and prev_end_ms <= start_ms:
        gap_before = start_ms - prev_end_ms
        eff_pad_b = min(eff_pad_b, gap_before // 2)

    if next_start_ms is not None and next_start_ms >= end_ms:
        gap_after = next_start_ms - end_ms
        eff_pad_a = min(eff_pad_a, gap_after // 2)

    pad_start_ms = max(0, start_ms - eff_pad_b)
    pad_end_ms = end_ms + eff_pad_a
    start_sec = pad_start_ms / 1000.0
    end_sec = pad_end_ms / 1000.0
    duration_sec = max(0.1, end_sec - start_sec)

    # Midpoint for screenshot
    mid_sec = (start_ms + end_ms) / 2000.0

    audio_file = f"{base_filename}.mp3"
    image_file = f"{base_filename}.jpg"
    audio_path = os.path.join(media_dir, audio_file)
    image_path = os.path.join(media_dir, image_file)

    # Cut Audio: -ss before -i, -t after -i for fast accurate seek
    cmd_audio = [
        ffmpeg, "-y",
        "-ss", f"{start_sec:.3f}",
        "-i", video_path,
        "-t", f"{duration_sec:.3f}",
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

            prev_end_ms = self.items[idx - 2]['end_ms'] if idx > 1 else None
            next_start_ms = self.items[idx]['start_ms'] if idx < total else None
            is_refined = item.get('_audio_refined', False)

            try:
                audio_file, image_file = cut_audio_and_image(
                    self.video_path,
                    start_ms,
                    end_ms,
                    base_filename,
                    self.audio_pad_before,
                    self.audio_pad_after,
                    self.screenshot_width,
                    media_dir,
                    prev_end_ms=prev_end_ms,
                    next_start_ms=next_start_ms,
                    is_audio_refined=is_refined
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

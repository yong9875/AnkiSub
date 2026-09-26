# -*- coding: utf-8 -*-
"""
AnkiSub - Subtitle Parser
Supports SRT, VTT, ASS/SSA formats, tag cleaning, noise filtering,
adjacent line merging, and bilingual time alignment.
"""

import os
import re
import html
from typing import List, Dict, Optional, Tuple


def time_to_ms(time_str: str) -> int:
    """Convert timestamp (HH:MM:SS,mmm or HH:MM:SS.mmm or MM:SS.mmm or MM:SS) to milliseconds."""
    try:
        time_str = time_str.strip().replace(',', '.')
        parts = time_str.split(':')
        if len(parts) == 3:
            h = int(parts[0])
            m = int(parts[1])
            s_parts = parts[2].split('.')
            s = int(s_parts[0])
            ms = int(s_parts[1].ljust(3, '0')[:3]) if len(s_parts) > 1 else 0
            return h * 3600000 + m * 60000 + s * 1000 + ms
        elif len(parts) == 2:
            m = int(parts[0])
            s_parts = parts[1].split('.')
            s = int(s_parts[0])
            ms = int(s_parts[1].ljust(3, '0')[:3]) if len(s_parts) > 1 else 0
            return m * 60000 + s * 1000 + ms
    except (ValueError, IndexError):
        pass
    return 0


def ms_to_time(ms: int, sep: str = ':') -> str:
    """Convert milliseconds to HH:MM:SS.mmm format for display and FFmpeg."""
    if ms < 0:
        ms = 0
    h = ms // 3600000
    ms %= 3600000
    m = ms // 60000
    ms %= 60000
    s = ms // 1000
    millis = ms % 1000
    return f"{h:02d}{sep}{m:02d}{sep}{s:02d}.{millis:03d}"


def clean_text(text: str) -> str:
    """Remove formatting tags (ASS override tags, HTML/VTT tags) and normalize whitespace."""
    # Unescape HTML entities (e.g., &amp; -> &, &#39; -> ', &nbsp; -> ' ')
    text = html.unescape(text)
    # ASS tags: {\...}
    text = re.sub(r'\{[^\}]+\}', '', text)
    # HTML / WebVTT tags: <...> (including <v Roger>, <c.color>, <00:00.000>, <b>, </i>, <ruby>, <rt>, etc.)
    text = re.sub(r'<[^>]+>', '', text)
    # ASS newline escapes: \N or \n or \h (single or double escaped)
    text = re.sub(r'\\{1,2}[Nnh]', ' ', text)
    # Replace non-breaking spaces with regular space
    text = text.replace('\u00a0', ' ').replace('\u200b', '')
    # Normalize multiple newlines and spaces
    text = re.sub(r'\r\n|\r|\n', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def is_sound_effect(text: str) -> bool:
    """Check if the text represents only music, sound effects, or actor notes."""
    cleaned = text.strip()
    if not cleaned:
        return True
    
    # Check for music notes
    if any(ch in cleaned for ch in ['♪', '♫', '♬']):
        # If it's mostly music symbols or short text surrounded by music notes
        if re.match(r'^[♪♫♬\s\-\.]*$', cleaned) or (cleaned.startswith('♪') and cleaned.endswith('♪')):
            return True

    # Bracketed text only: [Applause], (Gunshot), （笑声）, 【音乐】
    if re.match(r'^(\[|\(|（|【|\{)[^\]\)）】\}]+(\]|\)|）|】|\})$', cleaned):
        return True

    lower = cleaned.lower()
    noise_keywords = [
        'laught', 'applause', 'music', 'cheering', 'gasp', 'groan', 'screaming',
        'sighs', 'snickers', 'chuckles', 'whimpering', 'pant', 'cough',
        '音乐', '掌声', '笑声', '叹气', '抽泣', '尖叫'
    ]
    for kw in noise_keywords:
        if lower.startswith(f"[{kw}") or lower.startswith(f"({kw}"):
            return True

    return False


# Regex to match subtitle timestamp lines: supports both HH:MM:SS.mmm and MM:SS.mmm
# with optional cue settings (e.g. line:0 position:20% align:start)
TIMESTAMP_RE = re.compile(
    r'^(?:.*?\s+)?((?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d+)?)\s*-->\s*((?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d+)?)'
)


def parse_vtt(content: str) -> List[Dict]:
    """
    Robust WebVTT subtitle parser.
    Supports WEBVTT headers, cue identifiers, cue settings, NOTE comment blocks,
    STYLE blocks, REGION blocks, variable-precision timestamps, and auto-deduplication
    for YouTube-style rolling / sliding-window captions.
    """
    raw_cues = []
    # Strip UTF-8 BOM and normalize line endings
    content = content.lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n')
    lines = content.split('\n')
    
    i = 0
    n = len(lines)
    
    # Skip WEBVTT header line if present
    if i < n and lines[i].strip().upper().startswith('WEBVTT'):
        i += 1
        
    in_note = False
    in_style = False
    in_region = False
    
    cur_start_ms = None
    cur_end_ms = None
    cur_text_lines = []
    
    def flush():
        nonlocal cur_start_ms, cur_end_ms, cur_text_lines
        if cur_start_ms is not None and cur_end_ms is not None and cur_text_lines:
            raw_cues.append({
                'start_ms': cur_start_ms,
                'end_ms': cur_end_ms,
                'lines': cur_text_lines
            })
        cur_start_ms = None
        cur_end_ms = None
        cur_text_lines = []
        
    while i < n:
        line = lines[i].strip()
        i += 1
        
        # Check for timestamp line FIRST before empty line check
        m = TIMESTAMP_RE.search(line)
        if m:
            flush()
            cur_start_ms = time_to_ms(m.group(1))
            cur_end_ms = time_to_ms(m.group(2))
            continue
            
        # Blank line
        if not line:
            in_note = False
            in_style = False
            in_region = False
            # Only flush if we have already captured text lines for the current cue
            if cur_text_lines:
                flush()
            continue
            
        # Metadata / block headers
        if line.upper().startswith('NOTE'):
            in_note = True
            flush()
            continue
        if line.upper().startswith('STYLE'):
            in_style = True
            flush()
            continue
        if line.upper().startswith('REGION'):
            in_region = True
            flush()
            continue
            
        if in_note or in_style or in_region:
            continue
            
        # Active cue text payload
        if cur_start_ms is not None:
            cur_text_lines.append(line)
            
    flush()
    
    if not raw_cues:
        return []

    # Check if this is a YouTube auto-caption rolling VTT (contains <c> or <HH:MM:SS.mmm> word timestamps)
    is_yt_rolling = any(
        any('<c>' in l or re.search(r'<\d{2}:\d{2}', l) for l in c['lines'])
        for c in raw_cues
    )

    items = []
    prev_text = ""
    for c in raw_cues:
        dur = c['end_ms'] - c['start_ms']
        if is_yt_rolling:
            # In YouTube auto-captions, ignore short flash cues (<= 50ms)
            if dur <= 50:
                continue
            # Pick the line with word tags (newly introduced text)
            new_lines = [l for l in c['lines'] if '<' in l] or c['lines']
        else:
            new_lines = c['lines']
            
        text = clean_text(' '.join(new_lines))
        if not text or c['start_ms'] >= c['end_ms']:
            continue
            
        # Avoid duplicate consecutive lines
        if text == prev_text:
            continue
            
        items.append({
            'start_ms': c['start_ms'],
            'end_ms': c['end_ms'],
            'text': text
        })
        prev_text = text

    return items


def parse_srt(content: str) -> List[Dict]:
    """Parse SubRip (SRT) format."""
    return parse_vtt(content)


def parse_srt_or_vtt(content: str) -> List[Dict]:
    """Parse SRT or WebVTT content."""
    return parse_vtt(content)


def parse_ass(content: str) -> List[Dict]:
    """Parse ASS/SSA subtitle content."""
    items = []
    in_events = False
    format_indices = {}
    
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith(';'):
            continue
        if line.lower() == '[events]':
            in_events = True
            continue
        elif line.startswith('[') and in_events:
            break
            
        if in_events:
            if line.startswith('Format:'):
                headers = [h.strip().lower() for h in line[7:].split(',')]
                format_indices = {h: idx for idx, h in enumerate(headers)}
            elif line.startswith('Dialogue:'):
                raw = line[9:].strip()
                # Dialogue: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
                # Text can contain commas, so split by format headers length - 1
                max_split = len(format_indices) - 1 if format_indices else 9
                parts = raw.split(',', max_split)
                
                if format_indices and 'start' in format_indices and 'end' in format_indices and 'text' in format_indices:
                    start_idx = format_indices['start']
                    end_idx = format_indices['end']
                    text_idx = format_indices['text']
                    if len(parts) > text_idx:
                        start_str = parts[start_idx]
                        end_str = parts[end_idx]
                        text_str = parts[text_idx]
                    else:
                        continue
                else:
                    if len(parts) >= 10:
                        start_str = parts[1]
                        end_str = parts[2]
                        text_str = parts[9]
                    else:
                        continue
                
                start_ms = time_to_ms(start_str)
                end_ms = time_to_ms(end_str)
                text = clean_text(text_str)
                if start_ms < end_ms and text:
                    items.append({
                        'start_ms': start_ms,
                        'end_ms': end_ms,
                        'text': text
                    })
    
    items.sort(key=lambda x: x['start_ms'])
    return items


def parse_subtitles_from_text(content: str, ext: str = "srt") -> List[Dict]:
    """Parse subtitle text based on file extension."""
    ext = ext.lower().lstrip('.')
    if ext in ['ass', 'ssa']:
        return parse_ass(content)
    elif ext in ['vtt', 'webvtt']:
        return parse_vtt(content)
    else:
        return parse_srt_or_vtt(content)


def parse_subtitle_file(filepath: str) -> List[Dict]:
    """Read and parse an external subtitle file (.srt, .vtt, .ass, .ssa)."""
    encodings = ['utf-8-sig', 'utf-8', 'gb18030', 'big5', 'shift_jis', 'cp1252', 'latin1']
    content = None
    for enc in encodings:
        try:
            with open(filepath, 'r', encoding=enc) as f:
                content = f.read()
                break
        except (UnicodeDecodeError, OSError):
            continue
            
    if content is None:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            
    ext = os.path.splitext(filepath)[1].lower().lstrip('.')
    return parse_subtitles_from_text(content, ext)


def merge_adjacent_subtitles(
    items: List[Dict],
    max_gap_ms: int = 400,
    max_duration_ms: int = 8000
) -> List[Dict]:
    """
    Merge short adjacent dialogue fragments into natural, complete phrases.
    Guards against over-merging by checking:
    1. Maximum phrase duration cap (default 8000ms / 8s).
    2. Sentence-ending punctuation (., ?, !, etc.).
    3. Rolling subtitle redundancy / duplicate prefix.
    """
    if not items:
        return []
        
    sentence_ends = ('.', '?', '!', '。', '？', '！', '…')
    merged = []
    current = items[0].copy()
    
    for next_item in items[1:]:
        gap = next_item['start_ms'] - current['end_ms']
        combined_dur = next_item['end_ms'] - current['start_ms']
        current_dur = current['end_ms'] - current['start_ms']
        ends_sentence = current['text'].rstrip().endswith(sentence_ends)
        
        # Merge if:
        # - Gap between segments is within threshold
        # - Total combined duration won't exceed max_duration_ms
        # - Current phrase is not already an ended sentence (unless it was a very brief utterance < 1.5s)
        can_merge = (
            0 <= gap <= max_gap_ms
            and combined_dur <= max_duration_ms
            and (not ends_sentence or current_dur < 1500)
        )
        
        if can_merge:
            next_text = next_item['text'].strip()
            # If next_text already includes current text (rolling caption artifact)
            if next_text.startswith(current['text']):
                current['text'] = next_text
            elif not current['text'].endswith(next_text):
                current['text'] = f"{current['text']} {next_text}".strip()
            current['end_ms'] = max(current['end_ms'], next_item['end_ms'])
        else:
            merged.append(current)
            current = next_item.copy()
            
    merged.append(current)
    return merged


def filter_noise_subtitles(items: List[Dict], min_duration_ms: int = 400) -> List[Dict]:
    """Filter out sound effects, music tags, and extremely short empty fragments."""
    filtered = []
    for item in items:
        duration = item['end_ms'] - item['start_ms']
        if duration < min_duration_ms:
            continue
        if is_sound_effect(item['text']):
            continue
        filtered.append(item)
    return filtered


def align_bilingual_subtitles(
    primary_items: List[Dict],
    secondary_items: List[Dict]
) -> List[Dict]:
    """
    Align primary subtitle items with secondary (translation) subtitle items
    based on overlapping timestamps.
    Returns a unified list of Dicts with 'text' (primary) and 'translation' (secondary).
    """
    if not secondary_items:
        # Single subtitle track only
        return [{
            'start_ms': item['start_ms'],
            'end_ms': item['end_ms'],
            'text': item['text'],
            'translation': ''
        } for item in primary_items]

    results = []
    for p in primary_items:
        p_start = p['start_ms']
        p_end = p['end_ms']
        p_dur = p_end - p_start
        
        matched_translations = []
        for s in secondary_items:
            # Calculate time overlap
            overlap = max(0, min(p_end, s['end_ms']) - max(p_start, s['start_ms']))
            if overlap > 0:
                # If overlap covers more than 20% of primary or secondary sentence, consider match
                s_dur = s['end_ms'] - s['start_ms']
                if overlap >= 0.2 * min(p_dur, s_dur) or overlap >= 300:
                    matched_translations.append(s['text'])
                    
        trans_text = ' / '.join(matched_translations) if matched_translations else ''
        results.append({
            'start_ms': p_start,
            'end_ms': p_end,
            'text': p['text'],
            'translation': trans_text
        })
        
    return results

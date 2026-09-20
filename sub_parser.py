# -*- coding: utf-8 -*-
"""
AnkiSub - Subtitle Parser
Supports SRT, VTT, ASS/SSA formats, tag cleaning, noise filtering,
adjacent line merging, and bilingual time alignment.
"""

import re
from typing import List, Dict, Optional, Tuple


def time_to_ms(time_str: str) -> int:
    """Convert timestamp (HH:MM:SS,mmm or HH:MM:SS.mmm or MM:SS.mmm) to milliseconds."""
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
    """Remove formatting tags (ASS override tags, HTML tags) and normalize whitespace."""
    # ASS tags: {\...}
    text = re.sub(r'\{[^\}]+\}', '', text)
    # HTML tags: <...>
    text = re.sub(r'<[^>]+>', '', text)
    # ASS newline escapes: \N or \n or \h (single or double escaped)
    text = re.sub(r'\\{1,2}[Nnh]', ' ', text)
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


def parse_srt_or_vtt(content: str) -> List[Dict]:
    """Parse SRT or WebVTT content."""
    items = []
    # Match blocks with timestamp: 00:00:00.000 --> 00:00:00.000
    pattern = re.compile(
        r'(\d{1,2}:\d{2}:\d{2}[,\.]\d{3}|\d{1,2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{3}|\d{1,2}:\d{2}[,\.]\d{3})[^\r\n]*\r?\n([\s\S]*?)(?=\r?\n\s*\r?\n|\Z)'
    )
    for match in pattern.finditer(content):
        start_str, end_str, text_block = match.groups()
        start_ms = time_to_ms(start_str)
        end_ms = time_to_ms(end_str)
        text = clean_text(text_block)
        if start_ms < end_ms and text:
            items.append({
                'start_ms': start_ms,
                'end_ms': end_ms,
                'text': text
            })
    return items


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
    else:
        return parse_srt_or_vtt(content)


def parse_subtitle_file(filepath: str) -> List[Dict]:
    """Read and parse an external subtitle file."""
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
            
    ext = filepath.split('.')[-1]
    return parse_subtitles_from_text(content, ext)


def merge_adjacent_subtitles(items: List[Dict], max_gap_ms: int = 400) -> List[Dict]:
    """
    Merge subtitles where the time gap between sentence end and next sentence start
    is less than or equal to max_gap_ms, combining fragments into complete phrases.
    """
    if not items:
        return []
        
    merged = []
    current = items[0].copy()
    
    for next_item in items[1:]:
        gap = next_item['start_ms'] - current['end_ms']
        # Check if they are adjacent and can be merged
        if 0 <= gap <= max_gap_ms:
            # Merge
            current['end_ms'] = max(current['end_ms'], next_item['end_ms'])
            current['text'] = f"{current['text']} {next_item['text']}".strip()
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

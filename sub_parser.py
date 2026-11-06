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


# Sentence terminators and common abbreviation whitelists to prevent false splits
SENTENCE_TERMINATORS = ('.', '?', '!', '。', '？', '！', '…')
# Title/prefix abbreviations: usually followed by a capitalized name or number (Dr. Smith, No. 1)
TITLE_ABBREVIATIONS = {
    'mr', 'mrs', 'ms', 'dr', 'prof', 'vs', 'vol', 'jr', 'sr', 'st',
    'approx', 'dept', 'fig', 'no'
}
# Unit/phrase abbreviations: mid-sentence before lowercase, but can end a sentence before uppercase
UNIT_ABBREVIATIONS = {
    'etc', 'eg', 'ie', 'inc', 'ltd', 'co', 'corp',
    'a.m', 'p.m', 'e.g', 'i.e', 'u.s', 'u.k'
}
ABBREVIATIONS = TITLE_ABBREVIATIONS | UNIT_ABBREVIATIONS

CAPITAL_SENTENCE_STARTERS = {
    'So', 'If', 'When', 'While', 'What', 'Why', 'How', 'Where',
    'This', 'That', 'These', 'Those', 'It', "It's", 'We', "We're", "We've",
    'You', "You're", "You've", 'They', "They're", 'He', 'She', 'But',
    'Now', 'Here', 'There', "Let's", "Don't"
}


def is_word_sentence_end(word: str, next_word: str = "", cur_word_count: int = 1) -> bool:
    """
    Check if a word finishes a complete grammatical sentence.
    Distinguishes abbreviations (Mr., Dr., 9:00 a.m. vs 11 a.m.. What...) and detects
    missing periods before capitalized sentence starters (e.g. YouTube censorship drops).
    """
    t = word.rstrip().rstrip('"\'”)』」')
    if not t:
        return False

    if t.endswith(SENTENCE_TERMINATORS):
        # Question/exclamation marks or double dots ("a.m..") always end a sentence
        if t.endswith(('?', '!', '？', '！')) or (t.endswith('..') and not t.endswith('...')):
            return True

        core = t.lower().rstrip('.?!。？！…')
        # "No." or "St." followed by a digit is a number prefix, not a sentence end
        if core in ('no', 'st') and next_word and next_word[:1].isdigit():
            return False

        if core in TITLE_ABBREVIATIONS:
            return False

        if core in UNIT_ABBREVIATIONS:
            if next_word:
                nw_clean = next_word.lstrip('"\'“([（【')
                if nw_clean and nw_clean[0].isupper():
                    return True
            return False

        # Multi-dot initialisms / abbreviations: e.g. a.m., p.m., u.s.
        if t.endswith('.') and re.match(r'^(?:[a-zA-Z]\.)+[a-zA-Z]?$', t[:-1]):
            if next_word:
                nw_clean = next_word.lstrip('"\'“([（【')
                if nw_clean and nw_clean[0].islower():
                    return False

        return True

    # Missing period before a Capitalized Sentence Starter (e.g. "and that's So much so that...")
    if cur_word_count >= 5 and next_word:
        if not t.endswith((',', ';', ':', '-', '—', '，', '；', '：')):
            nw_clean = next_word.rstrip(',.:;?!')
            if nw_clean in CAPITAL_SENTENCE_STARTERS and nw_clean.lower() != t.lower():
                return True

    return False


def ends_with_sentence_terminal(text: str) -> bool:
    """Check if text ends with a true sentence terminator, avoiding abbreviations like Dr. or Mr."""
    words = text.split()
    if not words:
        return False
    return is_word_sentence_end(words[-1], "", len(words))


# Regex to match subtitle timestamp lines: supports both HH:MM:SS.mmm and MM:SS.mmm
# with optional cue settings (e.g. line:0 position:20% align:start)
TIMESTAMP_RE = re.compile(
    r'^(?:.*?\s+)?((?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d+)?)\s*-->\s*((?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d+)?)'
)


# ---------------------------------------------------------------------------
# Cue normalization
# Turns raw subtitle cues into clean, non-overlapping, non-duplicated timed text
# segments. These segments are the "atoms" consumed by the Anki card segmenter
# (segment_for_anki). Parsing never merges or re-splits sentences by itself.
# ---------------------------------------------------------------------------

WORD_TS_RE = re.compile(r'<((?:\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{3})>')


def parse_vtt_word_level(raw_cues: List[Dict]) -> List[Dict]:
    """
    YouTube auto-captions / word-timestamped VTT (<00:00:01.234><c> word</c>).
    Returns one segment per newly spoken caption line. Each segment carries the
    exact word timings in seg['words'] so the card segmenter can cut between words.
    """
    segments = []
    for c in raw_cues:
        # Ignore 10ms-50ms flash transition cues
        if c['end_ms'] - c['start_ms'] <= 50:
            continue
        tag_lines = [l for l in c['lines'] if WORD_TS_RE.search(l) or '<c>' in l]
        if not tag_lines:
            continue
        line = tag_lines[-1]  # The newly spoken speech line
        tokens = WORD_TS_RE.split(line)
        words = []

        def add(text: str, t0: int, t1: int):
            ws = clean_text(text).split()
            if not ws:
                return
            step = max(0, t1 - t0) / len(ws)
            for k, w in enumerate(ws):
                words.append({
                    'word': w,
                    'start_ms': int(t0 + k * step),
                    'end_ms': int(t0 + (k + 1) * step)
                })

        first_end = time_to_ms(tokens[1]) if len(tokens) > 1 else c['end_ms']
        add(tokens[0], c['start_ms'], first_end)
        for k in range(1, len(tokens), 2):
            t_start = time_to_ms(tokens[k])
            if k + 2 < len(tokens):
                t_end = time_to_ms(tokens[k + 2])
            else:
                # Last word in a YouTube rolling cue: c['end_ms'] includes any silence
                # before the next cue, so cap the word's spoken duration to expose pauses.
                n_w = max(1, len(clean_text(tokens[k + 1]).split()))
                t_end = min(c['end_ms'], t_start + 500 * n_w)
            add(tokens[k + 1], t_start, t_end)

        if words:
            segments.append({
                'start_ms': words[0]['start_ms'],
                'end_ms': words[-1]['end_ms'],
                'text': ' '.join(w['word'] for w in words),
                'words': words
            })

    # De-overlap consecutive lines (screen linger)
    for a, b in zip(segments, segments[1:]):
        if a['start_ms'] < b['start_ms'] < a['end_ms']:
            a['end_ms'] = b['start_ms']
            lw = a['words'][-1]
            lw['end_ms'] = max(lw['start_ms'] + 1, min(lw['end_ms'], b['start_ms']))
    return segments


def normalize_cues(raw_cues: List[Dict]) -> List[Dict]:
    """
    Clean cue-based subtitles (SRT / VTT / roll-up captions) into timed line segments.

    - Removes screen-linger overlap (a line's speech ends when the next cue starts).
    - Removes roll-up / growing-caption duplicates (repeated first line or prefix).
    - Keeps every display line as its own segment ('cue' marks lines of one cue),
      so dialogue dashes and line breaks remain usable as boundary hints.
    """
    segs: List[Dict] = []
    n = len(raw_cues)
    prev_full = None
    prev_last_line = None

    for i, c in enumerate(raw_cues):
        s_ms, e_ms = c['start_ms'], c['end_ms']
        if i + 1 < n:
            nxt_start = raw_cues[i + 1]['start_ms']
            if s_ms < nxt_start < e_ms:
                e_ms = nxt_start

        raw_lines = c.get('lines')
        if raw_lines is None:
            raw_lines = str(c.get('text', '')).split('\n')
        lines = [t for t in (clean_text(x) for x in raw_lines) if t]
        if not lines or s_ms >= e_ms:
            continue
        full = ' '.join(lines)

        # Identical text repeated by consecutive cues -> extend previous segment
        if full == prev_full and segs and s_ms - segs[-1]['end_ms'] <= 300:
            segs[-1]['end_ms'] = max(segs[-1]['end_ms'], e_ms)
            continue

        orig_lines = lines
        if prev_full and len(full) > len(prev_full) and full.startswith(prev_full):
            # Growing caption: "A" -> "A B" -> "A B C"; only the new words are new speech
            rest = full[len(prev_full):].strip()
            lines = [rest] if rest else []
        elif prev_last_line and len(lines) >= 2 and lines[0] == prev_last_line:
            # Roll-up caption: first line repeats the previous cue's last line
            lines = lines[1:]
        prev_full = full
        prev_last_line = orig_lines[-1]
        if not lines:
            continue

        if segs and s_ms < segs[-1]['end_ms']:
            segs[-1]['end_ms'] = max(segs[-1]['start_ms'] + 1, s_ms)

        parts = []
        prev_orig_end = raw_cues[i - 1]['end_ms'] if i > 0 else None
        if len(lines) == 2 and prev_orig_end is not None and s_ms + 100 < prev_orig_end < e_ms - 100:
            # 2-line roll-up timing law: the previous cue's original end time marks the
            # moment the second line starts being spoken.
            parts = [(s_ms, prev_orig_end, lines[0]), (prev_orig_end, e_ms, lines[1])]
        else:
            total = sum(max(1, len(x)) for x in lines)
            cur = float(s_ms)
            for x in lines:
                d = (e_ms - s_ms) * max(1, len(x)) / total
                parts.append((int(round(cur)), int(round(cur + d)), x))
                cur += d

        for a, b, t in parts:
            if b > a:
                segs.append({'start_ms': a, 'end_ms': b, 'text': t, 'cue': i})

    return segs


def parse_vtt(content: str) -> List[Dict]:
    """
    Robust WebVTT subtitle parser.
    Supports WEBVTT headers, cue identifiers, cue settings, NOTE comment blocks,
    STYLE blocks, REGION blocks, variable-precision timestamps, and auto-reconstruction
    for YouTube-style word-timestamped captions.
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

    # YouTube auto-caption rolling VTT (contains <c> or <HH:MM:SS.mmm> word timestamps)
    is_yt_rolling = any(
        any('<c>' in l or WORD_TS_RE.search(l) for l in c['lines'])
        for c in raw_cues
    )
    if is_yt_rolling:
        segments = parse_vtt_word_level(raw_cues)
        if segments:
            return segments

    # Cue-based subtitles: clean, de-overlapped, de-duplicated line segments.
    # Sentence building / card sizing happens later in segment_for_anki().
    return normalize_cues(raw_cues)


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


def join_subtitle_texts(t1: str, t2: str) -> str:
    """Intelligently join subtitle texts respecting CJK characters without superfluous spaces."""
    t1 = t1.strip()
    t2 = t2.strip()
    if not t1:
        return t2
    if not t2:
        return t1
    c1 = t1[-1]
    c2 = t2[0]
    is_cjk = (
        ('\u4e00' <= c1 <= '\u9fff') or ('\u4e00' <= c2 <= '\u9fff') or
        ('\u3040' <= c1 <= '\u30ff') or ('\u3040' <= c2 <= '\u30ff') or
        ('\uac00' <= c1 <= '\ud7af') or ('\uac00' <= c2 <= '\ud7af')
    )
    if is_cjk:
        return f"{t1}{t2}"
    return f"{t1} {t2}"


# ---------------------------------------------------------------------------
# Anki card segmentation
#
# Goal: every card = one complete, self-contained utterance of a comfortable
# length for listening practice (about 2.5 - 8 s).
#
# Method: the subtitle stream is tokenized (words for spaced languages, phrase
# chunks for Chinese/Japanese). Every gap between two tokens is a candidate cut
# with a "cut cost" derived from punctuation, real silence between subtitle
# lines, dialogue dashes, capitalized sentence starters and language-specific
# hints (dangling English function words, Chinese sentence-final particles and
# discourse markers). A dynamic program then picks the globally cheapest set of
# cuts, where each card also pays a length cost (too short / too long) and pays
# for every good boundary it swallows. Result:
#   * complete sentences stay whole and are normally one per card;
#   * very short sentences ("Most people do.") join a neighbouring sentence;
#   * over-long sentences are split at the best clause boundary (comma, pause);
#   * unpunctuated subtitles (e.g. Chinese ASR subtitles) are grouped by pauses
#     and particles instead of collapsing into one giant block.
# ---------------------------------------------------------------------------

_CJK_CHAR_RE = re.compile(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]')
_HANGUL_RE = re.compile(r'[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]')
_CJK_SPLIT_RE = re.compile(
    r'[^，,。？！?!；;：:、…]+[，,。？！?!；;：:、…]*[」』”’）)】》]*|[，,。？！?!；;：:、…]+[」』”’）)】》]*'
)
_TERMINAL_CHARS = '.?!。？！…‼⁇'
_CLAUSE_CHARS = ';:；：—–'
_COMMA_CHARS = ',，、'
_CLOSING_CHARS = '"\'”’)）]】」』》'
_OPENING_CHARS = '"\'“‘(（[【「『《¿¡'
_FULLWIDTH_END = '，。？！、：；」』）】》…'

_EN_DANGLING = {
    'the', 'a', 'an', 'to', 'of', 'and', 'or', 'but', 'nor', 'in', 'on', 'at', 'for',
    'with', 'from', 'by', 'into', 'onto', 'about', 'my', 'your', 'his', 'her', 'its',
    'our', 'their', 'is', 'are', 'was', 'were', 'am', 'be', 'been', 'very', 'than',
    'because', 'if', 'as', 'i', 'we', 'they', 'he', 'she', "i'm", "you're", "we're",
    "they're", "i've", "i'll", "i'd", 'can', 'will', 'would', 'should', 'could',
    'must', 'whose', 'such', 'every', 'each', 'some', 'any', 'no', 'not', 'more',
    'most', 'less', 'kind', 'sort', 'lot', 'going', 'gonna', 'wanna', 'gotta'
}
_EN_INCOMPLETE_END = _EN_DANGLING - {'be', 'been', 'more', 'most', 'less', 'lot', 'some', 'any', 'no', 'not'}
_EN_CONJ_START = {
    'and', 'but', 'so', 'because', 'which', 'who', 'when', 'where', 'while', 'if',
    'then', 'or', 'although', 'though', 'since', 'unless', 'until', 'whereas', 'whether'
}
_EN_FINITE_VERBS = {
    'came', 'comes', 'went', 'goes', 'was', 'were', 'is', 'are', 'had', 'has', 'have',
    'made', 'makes', 'took', 'takes', 'did', 'does', 'felt', 'feels', 'happened', 'happens',
    'started', 'starts', 'ended', 'ends', 'led', 'leads', 'worked', 'works', 'became',
    'becomes', 'seemed', 'seems', 'got', 'gets', 'gave', 'gives', 'kept', 'keeps', 'left',
    'leaves', 'brought', 'brings', 'course', 'means', 'meant', 'helps', 'helped',
    'requires', 'allows', 'creates', 'causes', 'changed', 'changes', 'mattered', 'matters'
}
_EN_PARTICIPLE_CONT = {
    'knowing', 'responding', 'meaning', 'including', 'assuming', 'depending', 'according',
    'compared', 'based', 'resulting', 'leading', 'trying', 'hoping', 'wondering',
    'thinking', 'feeling', 'looking', 'using', 'having', 'being'
}
_EN_CLAUSE_SUBJECTS = {
    'i', 'you', 'we', 'they', 'he', 'she', 'it', 'there', 'the', 'a', 'an', 'this',
    'that', 'these', 'those', 'my', 'your', 'his', 'her', 'our', 'their', 'most',
    'many', 'some', 'all', 'people', 'everyone', 'anyone', 'no', 'one', 'what', 'who'
}
_EN_EXTRA_STARTERS = {
    'And', 'Because', 'Then', 'Well', 'Okay', 'OK', 'Yeah', 'Oh', 'Yes', 'No',
    'Look', 'Anyway', 'Also', 'Or', 'Like', 'Just', 'Right', 'Maybe', 'Actually',
    'Basically', 'Again', 'First', 'Second', 'Third', 'Finally', 'Plus', 'Instead',
    'Otherwise', 'However', 'Meanwhile', 'Still', 'Even', 'Hey', 'Hi', 'Hello',
    'Thanks', 'Please', 'Sorry', 'Wait', 'Listen', 'Remember', 'Imagine', 'Think'
}
_ZH_END_STRONG = set('啊嗯吧吗呀哦哈啦嘛呗哎噢喔哇嘞咯呐')
_ZH_END_WEAK = {'了': 0.7, '呢': 0.3}
_ZH_DISCOURSE_START = (
    '那么', '那我们', '那这个', '那', '所以', '因为', '但是', '可是', '不过', '然后',
    '我们来', '我们再', '我们看', '首先', '其次', '另外', '而且', '比如', '例如',
    '接下来', '最后', '如果', '其实', '嗯', '啊', '哎', '下面', '总之', '当然',
    '好的', '好了', '好我们', '是的', '没错', '还有', '同时', '于是', '后来'
)
_ZH_CONT_END = (
    '是', '和', '与', '在', '把', '被', '跟', '给', '对', '从', '向', '让', '这', '那',
    '个', '一', '能', '就', '要', '会', '很', '都', '也', '还', '到', '不', '没', '最',
    '非常', '比较', '因为', '所以', '如果', '但是', '然后', '而且', '就是', '能够',
    '可以', '我们', '你们', '他们', '这个', '那个', '一个', '叫做', '通过', '什么是'
)
_ZH_CONT_START = ('的', '吗', '呢', '吧', '们')
# Unpunctuated Chinese line: allow a cut after a sentence-final particle that is
# directly followed by a discourse marker, e.g. "列举出来了啊|所以呢这本书呢".
_ZH_INNER_SPLIT_RE = re.compile(
    r'(?<=[啊嗯吧嘛呀哦啦])(?=那么|那我们|所以|但是|可是|不过|然后|因为|如果|其实|'
    r'我们来|我们再|我们看|接下来|首先|另外|而且|比如)'
)

_INF = 1e9


def _is_cjk_text(t: str) -> bool:
    return bool(_CJK_CHAR_RE.search(t))


def _token_weight(t: str) -> float:
    cjk = len(_CJK_CHAR_RE.findall(t))
    hg = len(_HANGUL_RE.findall(t))
    lat = sum(1 for ch in t if ch.isalnum()) - cjk - hg
    return max(1.5, lat + 2.5 * (cjk + hg))


def _token_units(t: str) -> Tuple[int, int]:
    """Returns (display units, cjk units): CJK chars count individually, other words count 1."""
    cjk = len(_CJK_CHAR_RE.findall(t))
    rest = _CJK_CHAR_RE.sub(' ', t)
    other = 1 if any(ch.isalnum() for ch in rest) else 0
    return cjk + other, cjk


def _split_pieces(text: str) -> List[Tuple[str, str]]:
    """Split one subtitle line into (token, glue_before) pieces."""
    pieces: List[Tuple[str, str]] = []
    for ci, chunk in enumerate(text.split()):
        glue = ' ' if ci else ''
        if _is_cjk_text(chunk):
            subs = []
            for sub in (_CJK_SPLIT_RE.findall(chunk) or [chunk]):
                subs.extend(x for x in _ZH_INNER_SPLIT_RE.split(sub) if x)
            for k, sub in enumerate(subs):
                if k > 0 and pieces and not any(ch.isalnum() for ch in sub):
                    pieces[-1] = (pieces[-1][0] + sub, pieces[-1][1])
                    continue
                pieces.append((sub, glue if k == 0 else ''))
        else:
            pieces.append((chunk, glue))
    return pieces


def _tokenize_segments(segments: List[Dict]) -> List[Dict]:
    toks: List[Dict] = []
    for si, seg in enumerate(segments):
        s_ms, e_ms = int(seg['start_ms']), int(seg['end_ms'])
        cue = seg.get('cue', si)
        words = seg.get('words')
        if words:
            for k, w in enumerate(words):
                toks.append({
                    'text': w['word'], 'glue': ' ' if k else '',
                    'start': int(w['start_ms']), 'end': int(w['end_ms']),
                    'seg': si, 'cue': cue, 'cjk': _is_cjk_text(w['word']),
                    'timed': True
                })
            continue

        pieces = _split_pieces(seg['text'])
        if not pieces:
            continue
        spoken, pauses = [], []
        for k, (p, _) in enumerate(pieces):
            spoken.append(_token_weight(p))
            last = p.rstrip(_CLOSING_CHARS)[-1:]
            if k == len(pieces) - 1:
                pauses.append(0.0)
            elif last and last in _TERMINAL_CHARS:
                pauses.append(3.0)
            elif last and (last in _COMMA_CHARS or last in _CLAUSE_CHARS):
                pauses.append(1.5)
            else:
                pauses.append(0.0)
        total = sum(spoken) + sum(pauses)
        dur = max(1, e_ms - s_ms)
        cur = float(s_ms)
        for k, (p, glue) in enumerate(pieces):
            w_d = dur * spoken[k] / total
            toks.append({
                'text': p, 'glue': glue,
                'start': int(round(cur)),
                'end': e_ms if k == len(pieces) - 1 else int(round(cur + w_d)),
                'seg': si, 'cue': cue, 'cjk': _is_cjk_text(p), 'timed': False
            })
            cur += w_d + dur * pauses[k] / total
    return toks


def _clean_word(t: str) -> str:
    return re.sub(r"[^\w']", '', t.lower())


def _is_false_en_period(toks: List[Dict], b: int, gap: int) -> bool:
    """
    Detect ASR false mid-sentence periods/question marks where a single sentence
    was split across two capitalized clauses or fragments.
    """
    n = len(toks)
    a, tb_tok = toks[b], toks[b + 1]
    aw = _clean_word(a['text'])
    prev_aw = _clean_word(toks[b - 1]['text']) if b > 0 else ''
    nw = _clean_word(tb_tok['text'])
    nw2 = _clean_word(toks[b + 2]['text']) if b + 2 < n else ''

    # 1. Left side is syntactically incomplete ("to.", "to be. At this point", "and it was. The best...")
    if aw in _EN_INCOMPLETE_END:
        return True
    if prev_aw == 'to' and aw == 'be' and nw in {'at', 'in', 'on', 'with', 'for', 'from', 'by', 'a', 'an', 'the'}:
        return True
    if prev_aw in {"i'm", 'you', 'we', 'they', 'he', 'she', 'it'} and aw in {'just', 'only', 'also', 'still', 'even'}:
        return True
    if prev_aw in {'it', 'that', 'this', 'there'} and aw in {'was', 'is'} and b >= 2:
        prev2 = _clean_word(toks[b - 2]['text'])
        if prev2 in {'and', 'but', 'so', 'because', 'that'}:
            return True

    # 2. Incomplete question + 1-word completion ("What opportunities? Close.", "in the right? Question.", "enemy? Name?")
    if prev_aw == 'what' and nw in {'close', 'open', 'happen', 'happens', 'change', 'changes', 'matter', 'matters', 'work', 'works'}:
        return True
    if prev_aw == 'the' and aw in {'right', 'wrong', 'same', 'only', 'actual', 'main', 'first', 'next', 'last'} and nw in {'question', 'answer', 'thing', 'way', 'place', 'time', 'person', 'direction', 'one'}:
        return True
    if aw == 'enemy' and nw == 'name':
        return True

    if gap >= 800:
        return False

    # 3. Right side opens with a subordinate / participial / prepositional continuation
    if nw in _EN_PARTICIPLE_CONT and nw2 not in _EN_FINITE_VERBS:
        return True
    if nw == 'while' and nw2 and nw2 not in _EN_CLAUSE_SUBJECTS:
        return True
    if nw == 'out' and nw2 == 'of':
        return True
    if nw == 'at' and nw2 in {'this', 'that', 'the', 'a', 'an', 'least', 'most', 'first', 'last', 'all', 'once'}:
        return True
    if nw == 'after' and nw2 in {'this', 'that', 'a', 'an', 'the', 'all'}:
        # Short prepositional phrase ("After this buildup of tension or disease.")
        k = b + 1
        clause_w = 0
        has_comma = False
        while k < n and clause_w <= 9:
            clause_w += 1
            if any(ch in _COMMA_CHARS for ch in toks[k]['text']):
                has_comma = True
            if any(ch in _TERMINAL_CHARS for ch in toks[k]['text']):
                break
            k += 1
        if clause_w <= 8 and not has_comma:
            return True
    if nw in {'always', 'never', 'often', 'usually', 'sometimes', 'rarely', 'already'} and nw2 in _EN_FINITE_VERBS:
        return True
    if nw in {'today', 'tomorrow', 'yesterday', 'tonight', 'now', 'here', 'there'} and nw2 in {'and', 'or', 'but'}:
        return True
    if nw == 'that' and nw2 in _EN_FINITE_VERBS:
        return True
    if aw in {'everyone', 'everybody', 'someone', 'somebody', 'anyone', 'anybody', 'everything', 'something', 'anything', 'nothing', 'people', 'person', 'things', 'time', 'place', 'way'}:
        if nw in {'you', 'i', 'we', 'they', 'he', 'she'} and nw2 in {'told', 'said', 'know', 'knew', 'think', 'thought', 'want', 'wanted', 'need', 'needed', 'love', 'loved', 'hate', 'hated', 'met', 'saw', 'asked', 'called', 'gave', 'made', 'had', 'have', 'did', 'do', 'used', 'chose'}:
            return True

    return False


def _boundary_cost(toks: List[Dict], b: int, punctuated: bool = True) -> Tuple[float, bool]:
    """
    Cost of cutting between toks[b] and toks[b+1] (0 = perfect sentence boundary).
    punctuated=False means the whole track has (almost) no punctuation, e.g.
    YouTube auto-captions or Chinese ASR subtitles: pauses and lexical hints decide.
    """
    a, b_tok = toks[b], toks[b + 1]
    ta, tb = a['text'], b_tok['text']
    same_seg = a['seg'] == b_tok['seg']
    same_cue = a['cue'] == b_tok['cue']
    real_gap = (not same_seg) or (a['timed'] and b_tok['timed'])
    gap = b_tok['start'] - a['end'] if real_gap else 0
    cjk = a['cjk'] or b_tok['cjk']

    core = ta.rstrip(_CLOSING_CHARS)
    last = core[-1:]
    nb = tb.lstrip(_OPENING_CHARS)
    nb0 = nb[:1]
    next_is_lower = bool(nb0) and (('a' <= nb0 <= 'z') or nb0.isdigit())

    is_sentence = False
    has_punct = True
    if last and last in _TERMINAL_CHARS:
        if cjk and last in '。？！?!…':
            c, is_sentence = 0.0, True
        elif is_word_sentence_end(ta, tb, 1) and not (next_is_lower and last in '.…'):
            if not cjk and _is_false_en_period(toks, b, gap):
                c, is_sentence = 4.8, False
            else:
                # Slight tie-break preference for cue boundaries / real pauses over mid-cue splits
                c = 0.25 if same_seg else (0.0 if gap >= 150 else 0.1)
                is_sentence = True
        else:
            c = 3.5   # abbreviation / ellipsis continuing in lowercase
    elif last and last in _CLAUSE_CHARS:
        c = 1.8
    elif last and last in _COMMA_CHARS:
        c = 2.8
    else:
        has_punct = False
        if cjk:
            if not same_seg or not b_tok['glue']:
                c = 3.5                        # line boundary / particle+marker split point
            else:
                c = 2.8                        # a space inside a CJK line works like a comma
        elif not punctuated:
            c = 5.5 if (same_seg and not a['timed']) else 4.0   # unpunctuated captions: pauses decide
        elif a['timed'] and b_tok['timed']:
            c = 5.0
        else:
            c = 9.0 if same_seg else (5.5 if same_cue else 5.0)

    # Dialogue dash at the start of a new line: "- Hi." / "- Hello."
    if not same_seg and tb[:1] in '-–—':
        c = min(c, 0.8)
        is_sentence = True

    # Capitalized sentence starter right after an unpunctuated word
    if not has_punct and not cjk and not tb.isupper():
        w_next = nb.rstrip(',.:;?!')
        if w_next in CAPITAL_SENTENCE_STARTERS or w_next in _EN_EXTRA_STARTERS:
            c = min(c, 2.5)
        elif not punctuated:
            # all-lowercase auto captions: "so", "now", "okay", "but" often open a sentence
            w_cap = w_next[:1].upper() + w_next[1:]
            if w_cap in CAPITAL_SENTENCE_STARTERS or w_cap in _EN_EXTRA_STARTERS:
                c -= 0.8

    # Real silence between subtitle lines / words
    if not is_sentence:
        if gap >= 1500:
            c -= 3.0
            if not punctuated:
                is_sentence = True
        elif gap >= 700:
            c -= 2.2
        elif gap >= 300:
            c -= 1.3
        elif gap >= 120:
            c -= 0.6

    if not is_sentence:
        if cjk:
            if not has_punct:
                tail = core[-1:]
                if tail in _ZH_END_STRONG:
                    c -= 1.2
                elif tail in _ZH_END_WEAK:
                    c -= _ZH_END_WEAK[tail]
                elif core.endswith('的'):
                    c += 1.0
                elif core.endswith(_ZH_CONT_END):
                    c += 1.5
                if nb.startswith(_ZH_CONT_START):
                    c += 2.5
                elif nb.startswith(_ZH_DISCOURSE_START):
                    c -= 1.2
        else:
            aw = _clean_word(core)
            if aw in _EN_DANGLING:
                c += 3.0
            nw = _clean_word(nb)
            if has_punct:
                # Never split right before a 1-2 word tag question (", right?", ", you know?", ", isn't it?")
                if last in _COMMA_CHARS:
                    b2_text = toks[b + 2]['text'] if b + 2 < len(toks) else ''
                    if tb.rstrip(_CLOSING_CHARS).endswith('?') or (
                        b2_text.rstrip(_CLOSING_CHARS).endswith('?') and b + 2 < len(toks) and toks[b + 2]['seg'] == b_tok['seg']
                    ):
                        c += 4.0
                # Comma/semicolon + conjunction (", but", ", so", ", which", ", because") is a clean clause break
                if nw in _EN_CONJ_START:
                    c -= 0.9
            else:
                if punctuated and next_is_lower:
                    c += 1.0
                    if nw in _EN_CONJ_START:
                        c -= 2.2
                elif nw in _EN_CONJ_START:
                    c -= 1.2

    return max(0.0, c), is_sentence


def _join_tokens(toks: List[Dict], starts_sentence: bool = True) -> str:
    out = ''
    for k, t in enumerate(toks):
        if k == 0:
            out = t['text']
            continue
        if t['seg'] == toks[k - 1]['seg']:
            glue = t['glue']
        else:
            glue = '' if out[-1:] in _FULLWIDTH_END else ' '
        out += glue + t['text']
    out = out.strip()
    # Capitalize only real sentence starts, never a clause continued from the previous card
    if starts_sentence and out[:1].isascii() and out[:1].islower():
        out = out[0].upper() + out[1:]
    return out


def segment_for_anki(
    segments: List[Dict],
    max_duration_ms: int = 15000,
    ideal_min_ms: int = 2800,
    ideal_max_ms: Optional[int] = None,
    hard_gap_ms: int = 2500
) -> List[Dict]:
    """
    Re-segment normalized subtitle lines into Anki-friendly cards.
    Returns [{'start_ms', 'end_ms', 'text'}] sorted by time.
    """
    toks = _tokenize_segments([s for s in segments if s.get('text', '').strip()])
    n = len(toks)
    if n == 0:
        return []

    hard_max = max(4000, int(max_duration_ms or 15000))
    hi = (ideal_max_ms or min(8500, max(5000, int(hard_max * 0.50)))) / 1000.0
    lo = min(ideal_min_ms / 1000.0, hi / 2.0)

    # Boundary costs: cut[b] between toks[b] and toks[b+1]
    cut = [0.0] * max(0, n - 1)
    keep = [0.0] * max(0, n - 1)     # penalty for swallowing boundary b inside a card
    hard = [False] * max(0, n - 1)
    sent = [False] * max(0, n - 1)
    # Does this track use punctuation at all? (YouTube auto-captions / ASR often do not)
    seg_ids = {t['seg'] for t in toks}
    punct_segs = {t['seg'] for t in toks if any(ch in _TERMINAL_CHARS + _COMMA_CHARS for ch in t['text'])}
    punctuated = len(punct_segs) >= 0.15 * max(1, len(seg_ids))
    alpha, thresh = 0.375, 4.0
    for b in range(n - 1):
        c, sent[b] = _boundary_cost(toks, b, punctuated)
        cut[b] = c
        keep[b] = alpha * max(0.0, thresh - c)
        if toks[b]['seg'] != toks[b + 1]['seg'] and toks[b + 1]['start'] - toks[b]['end'] > hard_gap_ms:
            hard[b] = True

    # Short introductory headings/prompts ("Vision.", "Daily levers.", "Constraints?", "At 7:30 p.m.?")
    # should attach forward to the sentence/question they introduce rather than backward.
    _QUESTION_OPENERS = {
        'what', "what's", 'why', 'how', 'when', 'where', 'who', 'which',
        'am', 'is', 'are', 'do', 'does', 'did', 'can', 'could', 'would', 'should', 'if'
    }
    sent_starts = [0] + [b + 1 for b in range(n - 1) if sent[b]]
    sent_ends = [b for b in range(n - 1) if sent[b]] + [n - 1]
    for s_idx, e_idx in zip(sent_starts, sent_ends):
        s_len = e_idx - s_idx + 1
        if e_idx < n - 1 and s_len <= 5 and not toks[s_idx]['cjk']:
            w0 = _clean_word(toks[s_idx]['text'])
            w1 = _clean_word(toks[s_idx + 1]['text']) if s_idx + 1 <= e_idx else ''
            next_w0 = _clean_word(toks[e_idx + 1]['text'])
            is_time_or_step = (w0 == 'at' and w1[:1].isdigit()) or (s_len <= 3 and w0 in {
                'first', 'second', 'third', 'finally', 'step', 'number', 'question', 'point', "let's"
            })
            is_heading_before_q = s_len <= 3 and next_w0 in _QUESTION_OPENERS and not (
                w0 in {'you', 'most', 'so', 'and', 'but', 'yet'} and w1 in {'think', 'know', 'people', 'to'}
            )
            if is_time_or_step or is_heading_before_q:
                keep[e_idx] = 0.0
                if s_idx > 0:
                    keep[s_idx - 1] = max(keep[s_idx - 1], 2.0)

    keep_pref = [0.0] * n
    for b in range(n - 1):
        keep_pref[b + 1] = keep_pref[b] + keep[b]
    units_pref = [0] * (n + 1)
    cjk_pref = [0] * (n + 1)
    for k, t in enumerate(toks):
        u, cu = _token_units(t['text'])
        units_pref[k + 1] = units_pref[k] + u
        cjk_pref[k + 1] = cjk_pref[k] + cu

    def length_cost(i: int, j: int) -> float:
        d = (toks[j]['end'] - toks[i]['start']) / 1000.0
        cost = 0.0
        if d < lo:
            cost += 1.85 * (lo - d) ** 2
        elif d > hi:
            cost += 0.55 * (d - hi) ** 2
        units = units_pref[j + 1] - units_pref[i]
        cjk_units = cjk_pref[j + 1] - cjk_pref[i]
        if cjk_units * 2 > units:
            if units > 28:
                cost += 0.02 * (units - 28) ** 2
            if units <= 4:
                cost += 1.2
        else:
            if units > 25:
                cost += 0.02 * (units - 25) ** 2
            if units <= 2:
                cost += 1.2
            elif units == 3:
                cost += 0.4
        return cost

    best = [_INF] * (n + 1)
    back = [0] * (n + 1)
    best[0] = 0.0
    for j in range(n):
        for i in range(j, max(-1, j - 400), -1):
            if i < j:
                if hard[i]:
                    break
                if toks[j]['end'] - toks[i]['start'] > hard_max:
                    break
            if best[i] >= _INF:
                continue
            cost = (best[i] + length_cost(i, j) + (keep_pref[j] - keep_pref[i]) +
                    (cut[i - 1] if i > 0 else 0.0))
            if cost < best[j + 1]:
                best[j + 1] = cost
                back[j + 1] = i

    bounds = []
    j = n
    while j > 0:
        i = back[j]
        bounds.append((i, j - 1))
        j = i
    bounds.reverse()

    cards = []
    for i, j in bounds:
        text = _join_tokens(toks[i:j + 1], starts_sentence=(i == 0 or sent[i - 1] or hard[i - 1]))
        if text:
            cards.append({
                'start_ms': toks[i]['start'],
                'end_ms': max(toks[j]['end'], toks[i]['start'] + 1),
                'text': text
            })
    return cards


def merge_adjacent_subtitles(
    items: List[Dict],
    max_gap_ms: int = 400,
    max_duration_ms: int = 15000
) -> List[Dict]:
    """
    Smart sentence segmentation for Anki cards (the "smart segmentation" option).

    Kept under its historical name for compatibility. Complete sentences are
    preserved, very short sentences are combined with a neighbour, over-long
    sentences are split at clause boundaries, and unpunctuated subtitles
    (e.g. Chinese ASR subtitles) are grouped by pauses and particles.
    max_duration_ms is the hard upper limit of one card. max_gap_ms is kept for
    API compatibility; silences longer than max(2500, max_gap_ms) always split.
    """
    if not items:
        return []
    return segment_for_anki(
        items,
        max_duration_ms=max_duration_ms,
        hard_gap_ms=max(2500, int(max_gap_ms or 0))
    )


def filter_noise_subtitles(items: List[Dict], min_duration_ms: int = 400) -> List[Dict]:
    """
    Filter out sound effects / music tags and flash cues.
    Real speech is never dropped just for being short: short lines are joined
    to their neighbours by the card segmenter instead.
    """
    filtered = []
    for item in items:
        duration = item['end_ms'] - item['start_ms']
        if duration < min(min_duration_ms, 120):
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

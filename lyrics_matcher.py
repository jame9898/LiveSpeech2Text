# -*- coding: utf-8 -*-
"""
歌词匹配引擎
用于检测ASR输出是否匹配歌词库中的歌词，识别直播/视频中的背景音乐

v2.17: 增加状态机 — 连续多句命中同一首歌后自动锁定，锁定后高效匹配后续行
"""
import json
import re
import time
from pathlib import Path

try:
    from pypinyin import lazy_pinyin, Style
    HAS_PINYIN = True
except ImportError:
    HAS_PINYIN = False


class LyricsMatcher:
    """歌词匹配器：加载歌词库，有状态匹配，连续命中后锁定歌曲"""

    def __init__(self, lyrics_path=None):
        self.songs = []
        self._line_index = {}    # normalized_line -> [(song_idx, line_idx)]
        self._min_meaningful = 4
        self._reset_state()
        if lyrics_path:
            self.load(lyrics_path)

    def _reset_state(self):
        """重置匹配状态（每次新录制开始时调用）"""
        self._state = 'idle'           # 'idle' | 'suspecting' | 'locked'
        self._candidate_song_idx = None
        self._candidate_line_idx = None
        self._consecutive_hits = 0
        self._miss_streak = 0
        self._lock_threshold = 3       # 连续命中 >= 3 句 → 锁定
        self._unlock_miss_limit = 6    # 连续未命中 >= 6 次 → 解锁
        self._locked_song_title = None
        self._locked_line_progress = 0 # 锁定期已走过的行数

    def reset(self):
        """外部调用：重置状态（新录制开始）"""
        self._reset_state()

    def get_status(self):
        """返回当前匹配状态（供 server 查询）"""
        return {
            'state': self._state,
            'song_title': self._locked_song_title if self._state == 'locked' else (
                self.songs[self._candidate_song_idx]['title'] if self._candidate_song_idx is not None and self._state == 'suspecting' else None
            ),
            'consecutive_hits': self._consecutive_hits,
            'miss_streak': self._miss_streak,
        }

    def load(self, lyrics_path):
        path = Path(lyrics_path)
        if not path.exists():
            print(f"[LYRICS] 歌词库不存在: {lyrics_path}")
            return
        with open(path, 'r', encoding='utf-8') as f:
            self.songs = json.load(f)
        self._build_index()
        total_lines = sum(len(s.get('lines', [])) for s in self.songs)
        print(f"[LYRICS] 加载 {len(self.songs)} 首歌, {total_lines} 行歌词", flush=True)

    def reload(self, lyrics_path):
        self.songs = []
        self._line_index = {}
        self._reset_state()
        self.load(lyrics_path)

    def _build_index(self):
        self._line_index = {}
        for si, song in enumerate(self.songs):
            for li, line in enumerate(song.get('lines', [])):
                key = self._normalize(line)
                if len(key) >= self._min_meaningful:
                    self._line_index.setdefault(key, []).append((si, li))

    @staticmethod
    def _normalize(text):
        """标准化文本：去标点、去空格、小写"""
        t = re.sub(r'[^\w\u4e00-\u9fff]', '', text)
        return t.lower().strip()

    @staticmethod
    def _char_overlap(a, b):
        """计算两个字符串的字符bigram重叠度（保留顺序，杜绝乱序误匹配）"""
        if not a or not b or len(a) < 2 or len(b) < 2:
            return 0.0
        bigrams_a = {a[i:i+2] for i in range(len(a)-1)}
        bigrams_b = {b[i:i+2] for i in range(len(b)-1)}
        if not bigrams_a or not bigrams_b:
            return 0.0
        return len(bigrams_a & bigrams_b) / max(len(bigrams_a), len(bigrams_b))

    @staticmethod
    def _pinyin_overlap(a, b):
        """计算两个字符串的拼音bigram重叠度（保留顺序）"""
        if not HAS_PINYIN or not a or not b:
            return 0.0
        try:
            pa = lazy_pinyin(a, style=Style.NORMAL)
            pb = lazy_pinyin(b, style=Style.NORMAL)
            if len(pa) < 2 or len(pb) < 2:
                return 0.0
            bigrams_a = {'-'.join(pa[i:i+2]) for i in range(len(pa)-1)}
            bigrams_b = {'-'.join(pb[i:i+2]) for i in range(len(pb)-1)}
            if not bigrams_a or not bigrams_b:
                return 0.0
            return len(bigrams_a & bigrams_b) / max(len(bigrams_a), len(bigrams_b))
        except Exception:
            return 0.0

    def _match_one_line(self, norm, expected_lines=None):
        """
        核心匹配：检查 norm 是否匹配某一行歌词。
        如果 expected_lines 不为空（锁定状态），只在这些行中匹配。
        返回 (matched, info) — info 包含 song_idx, line_idx 等
        """
        if expected_lines:
            # 锁定状态：只在预期行附近搜索，大幅提升效率和准确度
            for si, li, key in expected_lines:
                # 子串匹配
                if norm in key or key in norm:
                    shorter = norm if len(norm) < len(key) else key
                    longer = key if len(norm) < len(key) else norm
                    if len(shorter) >= 4 and len(shorter) / len(longer) > 0.4:
                        song = self.songs[si]
                        return True, {'song_idx': si, 'line_idx': li,
                                      'title': song['title'], 'artist': song['artist'],
                                      'line': song['lines'][li], 'method': 'locked_substring'}
                # 锁定状态下放宽字符重叠阈值至 55%
                if len(norm) >= 4 and len(key) >= 4:
                    if abs(len(norm) - len(key)) <= max(len(norm), len(key)) * 0.35:
                        overlap = self._char_overlap(norm, key)
                        if overlap >= 0.55:
                            song = self.songs[si]
                            return True, {'song_idx': si, 'line_idx': li,
                                          'title': song['title'], 'artist': song['artist'],
                                          'line': song['lines'][li],
                                          'method': f'locked_char({overlap:.2f})'}
            return False, None

        # === 非锁定状态：全局搜索（4级递进） ===

        # 1. 精确匹配
        if norm in self._line_index:
            matches = self._line_index[norm]
            si, li = matches[0]
            song = self.songs[si]
            return True, {'song_idx': si, 'line_idx': li,
                          'title': song['title'], 'artist': song['artist'],
                          'line': song['lines'][li], 'method': 'exact'}

        # 2. 子串匹配
        for key, matches in self._line_index.items():
            if norm in key or key in norm:
                shorter = norm if len(norm) < len(key) else key
                longer = key if len(norm) < len(key) else norm
                if len(shorter) >= 4 and len(shorter) / len(longer) > 0.4:
                    si, li = matches[0]
                    song = self.songs[si]
                    return True, {'song_idx': si, 'line_idx': li,
                                  'title': song['title'], 'artist': song['artist'],
                                  'line': song['lines'][li], 'method': 'substring'}

        # 3. 字符bigram重叠度 >= 70%
        for key, matches in self._line_index.items():
            if len(norm) < 4 or len(key) < 4:
                continue
            if abs(len(norm) - len(key)) > max(len(norm), len(key)) * 0.35:
                continue
            overlap = self._char_overlap(norm, key)
            if overlap >= 0.70:
                si, li = matches[0]
                song = self.songs[si]
                return True, {'song_idx': si, 'line_idx': li,
                              'title': song['title'], 'artist': song['artist'],
                              'line': song['lines'][li], 'method': f'char_bigram({overlap:.2f})'}

        # 4. 拼音bigram重叠度 >= 75%
        if HAS_PINYIN:
            for key, matches in self._line_index.items():
                if len(norm) < 4 or len(key) < 4:
                    continue
                if abs(len(norm) - len(key)) > max(len(norm), len(key)) * 0.35:
                    continue
                overlap = self._pinyin_overlap(norm, key)
                if overlap >= 0.75:
                    si, li = matches[0]
                    song = self.songs[si]
                    return True, {'song_idx': si, 'line_idx': li,
                                  'title': song['title'], 'artist': song['artist'],
                                  'line': song['lines'][li], 'method': f'pinyin_bigram({overlap:.2f})'}

        return False, None

    def _get_expected_lines(self):
        """锁定状态下，生成后续预期行的列表（前瞻窗口约8行）"""
        if self._candidate_song_idx is None:
            return None
        song = self.songs[self._candidate_song_idx]
        total = len(song.get('lines', []))
        expected = []
        start = max(0, self._candidate_line_idx - 1)   # 向前看1行（ASR可能重复）
        end = min(total, self._candidate_line_idx + 8)  # 向后看8行
        for li in range(start, end):
            line = song['lines'][li]
            key = self._normalize(line)
            if len(key) >= self._min_meaningful:
                expected.append((self._candidate_song_idx, li, key))
        return expected

    # ---------- 状态机 ----------

    def _advance_state(self, matched, info):
        """根据匹配结果推进状态机，返回 (was_just_locked: bool)"""
        was_just_locked = False

        if matched and info:
            si = info['song_idx']
            li = info['line_idx']

            if self._state == 'idle':
                # 首次命中 → 进入 suspecting
                self._state = 'suspecting'
                self._candidate_song_idx = si
                self._candidate_line_idx = li
                self._consecutive_hits = 1
                self._miss_streak = 0

            elif self._state == 'suspecting':
                if si == self._candidate_song_idx:
                    # 同一首歌 → 累加命中
                    self._consecutive_hits += 1
                    self._candidate_line_idx = max(self._candidate_line_idx, li)
                    self._miss_streak = 0
                else:
                    # 不同歌 → 重新开始
                    self._candidate_song_idx = si
                    self._candidate_line_idx = li
                    self._consecutive_hits = 1
                    self._miss_streak = 0

                if self._consecutive_hits >= self._lock_threshold:
                    self._state = 'locked'
                    self._locked_song_title = self.songs[si]['title']
                    self._locked_line_progress = li
                    was_just_locked = True
                    print(f"[LYRICS] 🔒 锁定歌曲: {self._locked_song_title} (连续{self._consecutive_hits}句命中)", flush=True)

            elif self._state == 'locked':
                if si == self._candidate_song_idx:
                    self._consecutive_hits += 1
                    self._candidate_line_idx = max(self._candidate_line_idx, li)
                    self._locked_line_progress = max(self._locked_line_progress, li)
                    self._miss_streak = 0
                else:
                    # 锁定期匹配到其他歌 → 计为一次未命中
                    self._miss_streak += 1
            else:
                self._miss_streak = 0

        else:
            # 未匹配
            self._miss_streak += 1

            if self._state == 'locked':
                if self._miss_streak >= self._unlock_miss_limit:
                    print(f"[LYRICS] 🔓 解锁: {self._locked_song_title} (连续{self._miss_streak}次未命中)", flush=True)
                    self._reset_state()
            elif self._state == 'suspecting':
                if self._miss_streak >= 3:
                    self._reset_state()

        return was_just_locked

    # ---------- 主入口 ----------

    def match(self, text):
        """
        检查 text 是否匹配歌词库中的某一行。
        返回 (matched: bool, song_info: dict or None)
        song_info 额外包含:
          - 'state': 当前状态 ('suspecting' | 'locked' | 'idle')
          - 'consecutive_hits': 连续命中次数
          - 'just_locked': 是否刚刚锁定（即这是锁定后的第一句）
        """
        if not text or len(text) < self._min_meaningful:
            self._advance_state(False, None)
            return False, None

        norm = self._normalize(text)
        if len(norm) < self._min_meaningful:
            self._advance_state(False, None)
            return False, None

        # 锁定/猜测状态下，使用预期行窗口做高效匹配
        expected = self._get_expected_lines() if self._state in ('suspecting', 'locked') else None
        matched, info = self._match_one_line(norm, expected)

        # 如果锁定窗口内没匹配到，再做一次全局搜索（可能是ASR跳到后面的行）
        if not matched and self._state in ('suspecting', 'locked'):
            matched, info = self._match_one_line(norm, expected_lines=None)

        was_locked = self._advance_state(matched, info)

        if matched and info:
            info['state'] = self._state
            info['consecutive_hits'] = self._consecutive_hits
            info['just_locked'] = was_locked
        return matched, info


lyrics_matcher = LyricsMatcher()

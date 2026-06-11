# -*- coding: utf-8 -*-
"""
拼音纠错工具模块
拼音字典纠正 / 文本相似度比对
"""

import re
import json

try:
    from pypinyin import lazy_pinyin, Style
except ImportError:
    lazy_pinyin = None
    Style = None

from core import DICT_DIR


# ---- 关键词分类常量 ----

CATEGORIES = {
    'speaker': '主讲人',
    'topic': '话题',
    'other': '关键词',
}

CATEGORY_ICONS = {
    'speaker': '👤',
    'topic': '🏷',
    'other': '📌',
}


class PinyinCorrector:

    def __init__(self, keyword_store=None):
        self._loaded_topics = set()
        self.pinyin_corrections = {}
        self.load_pinyin_corrections()
        # Initialize kw_set from keyword_store if provided
        if keyword_store:
            self.kw_set = set()
            for cat_kws in keyword_store.values():
                if isinstance(cat_kws, (set, list)):
                    self.kw_set.update(cat_kws)
        else:
            self.kw_set = set()
        self.protected_phrases = set()
        self.correction_log = set()
        self.correction_records = []

    def reset_session(self):
        """重置会话状态：清空话题纠正、kw_set、日志等，重新加载基础词典"""
        self._loaded_topics.clear()
        self.pinyin_corrections.clear()
        self._sorted_pinyin_entries = None
        self.load_pinyin_corrections()
        self.kw_set.clear()
        self.protected_phrases.clear()
        self.correction_log.clear()
        self.correction_records.clear()
        print(f"[PINYIN] 会话重置，已重新加载拼音纠错词典: {len(self.pinyin_corrections)}条", flush=True)

    @staticmethod
    def _load_dict_file(path, label=""):
        """加载JSON词典文件的通用辅助方法，返回过滤后的条目字典"""
        if not path.exists():
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            entries = {k: v for k, v in data.items() if not k.startswith('__')}
            return entries
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, OSError) as e:
            print(f"[{label}] 加载词典失败 {path.name}: {e}", flush=True)
            return None

    def load_pinyin_corrections(self, topic=None):
        """加载拼音→正确文字 纠错词典（按话题加载对应词典文件）"""
        self._sorted_pinyin_entries = None  # 字典变更后清除缓存
        base_dir = DICT_DIR / 'corrections'
        base_dir.mkdir(exist_ok=True)

        # 话题特定纠错
        if topic:
            topic_lower = topic.lower().strip()
            if topic_lower in self._loaded_topics:
                return self.pinyin_corrections
            topic_path = base_dir / f'{topic_lower}.json'
            entries = self._load_dict_file(topic_path, "PINYIN")
            if entries is not None:
                count = len(entries)
                self.pinyin_corrections.update(entries)
                if count:
                    print(f"[PINYIN] 补充话题拼音纠正: {topic} ({topic_path.name}, +{count}条)", flush=True)
                self._loaded_topics.add(topic_lower)

        # 通用拼音纠正（旧路径 pinyin_corrections/general.json，兼容未迁移的通用词典）
        if '__general__' not in self._loaded_topics:
            general_path = DICT_DIR / 'pinyin_corrections' / 'general.json'
            if general_path.exists():
                entries = self._load_dict_file(general_path, "PINYIN")
                if entries is not None:
                    count = len(entries)
                    self.pinyin_corrections.update(entries)
                    if count:
                        print(f"[PINYIN] 加载通用拼音纠正: general.json (+{count}条)", flush=True)
            self._loaded_topics.add('__general__')

        return self.pinyin_corrections

    def sync_protected_from_keywords(self):
        """将已加载的 KW 关键词同步为受保护短语，防止纠正引擎修改已正确的关键词"""
        for kw in self.kw_set:
            if len(kw) >= 2:
                self.protected_phrases.add(kw)

    def apply_pinyin_dict_correction(self, text):
        if not self.pinyin_corrections or not text:
            return text, []

        # 缓存排序后的字典条目，避免每次调用都重新排序
        if not hasattr(self, '_sorted_pinyin_entries') or self._sorted_pinyin_entries is None:
            self._sorted_pinyin_entries = sorted(
                ((k, v) for k, v in self.pinyin_corrections.items() if not k.startswith('__')),
                key=lambda x: len(x[0].split()), reverse=True)
        sorted_entries = self._sorted_pinyin_entries

        use_tone = any(
            any(ch.isdigit() for ch in k) for k, v in sorted_entries
        )

        chars = list(text)
        py_list = []
        if lazy_pinyin is not None:
            py_style = Style.TONE3 if use_tone else Style.NORMAL
            for ch in chars:
                try:
                    py = lazy_pinyin(ch, style=py_style)
                    py_list.append(py[0].lower() if py else ch.lower())
                except (ValueError, TypeError, KeyError):
                    py_list.append(ch.lower())
        else:
            py_list = [ch.lower() for ch in chars]
        corrections = []
        result = []
        i = 0
        while i < len(chars):
            replaced = False
            for py_pattern, correct_text in sorted_entries:
                syllables = py_pattern.lower().split()
                n = len(syllables)
                if i + n > len(chars):
                    continue
                match = True
                for j in range(n):
                    key_syl = syllables[j]
                    text_syl = py_list[i + j]
                    if any(c.isdigit() for c in key_syl):
                        if key_syl != text_syl:
                            match = False
                            break
                    else:
                        # 单音节无调key不允许通过剥离声调来匹配：
                        # 例如 "hen"(无调) 不应匹配 "hen3"(很)，否则常见字会被误纠
                        if n == 1:
                            match = False
                            break
                        text_clean = ''.join(c for c in text_syl if not c.isdigit())
                        if key_syl != text_clean:
                            match = False
                            break
                if not match:
                    continue
                sub = ''.join(chars[i:i + n])
                is_protected = sub in self.kw_set or sub in self.protected_phrases
                if sub == correct_text:
                    # 已经是正确文本，无需纠正
                    result.append(sub)
                elif is_protected:
                    # 受保护的正确固定搭配，保留原样
                    result.append(sub)
                else:
                    corrections.append((sub, correct_text))
                    result.append(correct_text)
                i += n
                replaced = True
                break
            if not replaced:
                result.append(chars[i])
                i += 1
        corrected = ''.join(result)
        if corrections:
            print(f"    [PINYIN-DICT] {len(corrections)}处拼音纠正: {corrections[:5]}", flush=True)
        return corrected, corrections


def text_similarity(text1, text2):
    """计算两段文本的字符/拼音重叠度，判断是否为同一句话被ASR不同转写"""
    t1 = re.sub(r'[^\u4e00-\u9fff]', '', text1)
    t2 = re.sub(r'[^\u4e00-\u9fff]', '', text2)
    if not t1 or not t2:
        return 0.0
    if len(t1) < 2 or len(t2) < 2:
        return 0.0
    chars1, chars2 = set(t1), set(t2)
    char_overlap = len(chars1 & chars2) / max(len(chars1), len(chars2))
    if lazy_pinyin is not None:
        py1 = lazy_pinyin(t1, style=Style.NORMAL)
        py2 = lazy_pinyin(t2, style=Style.NORMAL)
        py_set1, py_set2 = set(py1), set(py2)
        py_overlap = len(py_set1 & py_set2) / max(len(py_set1), len(py_set2)) if py_set1 and py_set2 else 0
    else:
        py_overlap = 0
    return max(char_overlap, py_overlap)

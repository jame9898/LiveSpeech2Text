# -*- coding: utf-8 -*-
"""
拼音纠错工具模块
拼音相似度计算 / KW关键词纠错 / 拼音字典纠正
"""

import re
import json

try:
    from pypinyin import lazy_pinyin, Style
except ImportError:
    lazy_pinyin = None
    Style = None

from core import DICT_DIR


class PinyinCorrector:

    KW_MIN_LEN = 2
    KW_SIMILARITY_THRESHOLD = 0.90

    PHONETIC_MERGE = {
        ('z','zh'),('zh','z'),('c','ch'),('ch','c'),('s','sh'),('sh','s'),
        ('n','l'),('l','n'),('h','f'),('f','h'),('r','l'),('l','r'),
        ('an','ang'),('ang','an'),('en','eng'),('eng','en'),
        ('in','ing'),('ing','in'),
    }

    def __init__(self, keyword_store=None):
        self._loaded_topics = set()
        self._loaded_text_topics = set()
        self.pinyin_corrections = {}
        self.text_corrections = {}
        self.load_pinyin_corrections()
        self.load_text_corrections()
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
        """重置会话状态：清空话题纠正、kw_set、日志等，保留基础配置"""
        self._loaded_topics.clear()
        self._loaded_text_topics.clear()
        self.pinyin_corrections.clear()
        self.text_corrections.clear()
        self.load_pinyin_corrections()
        self.load_text_corrections()
        self.kw_set.clear()
        self.protected_phrases.clear()
        self.correction_log.clear()
        self.correction_records.clear()

    @staticmethod
    def split_pinyin(py):
        initials = ['zh','ch','sh','b','p','m','f','d','t','n','l',
                    'g','k','h','j','q','x','r','z','c','s','y','w']
        py_clean = py.rstrip('12345')
        for init in initials:
            if py_clean.startswith(init):
                return init, py_clean[len(init):]
        return '', py_clean

    def pinyin_similar(self, py1, py2):
        if py1 == py2:
            return True
        i1, f1 = self.split_pinyin(py1)
        i2, f2 = self.split_pinyin(py2)
        if (i1, i2) in self.PHONETIC_MERGE:
            return True
        if (f1, f2) in self.PHONETIC_MERGE:
            return True
        return False

    def get_pinyin_list(self, text):
        try:
            if lazy_pinyin is None:
                return list(text)
            return lazy_pinyin(text, style=Style.TONE3)
        except (ValueError, TypeError, KeyError):
            return list(text)

    def load_pinyin_corrections(self, topic=None):
        base_dir = DICT_DIR / 'pinyin_corrections'
        base_dir.mkdir(exist_ok=True)
        general_path = base_dir / 'general.json'
        if general_path.exists():
            try:
                with open(general_path, 'r', encoding='utf-8') as f:
                    self.pinyin_corrections.update(json.load(f))
            except FileNotFoundError:
                pass
            except (json.JSONDecodeError, OSError) as e:
                print(f"[PINYIN] 加载通用拼音纠正失败: {e}", flush=True)
        if topic:
            topic_lower = topic.lower().strip()
            if topic_lower in self._loaded_topics:
                return self.pinyin_corrections
            topic_path = base_dir / f'{topic_lower}.json'
            if topic_path.exists():
                try:
                    with open(topic_path, 'r', encoding='utf-8') as f:
                        self.pinyin_corrections.update(json.load(f))
                    print(f"[PINYIN] 加载话题拼音纠正: {topic} ({topic_path.name})", flush=True)
                    self._loaded_topics.add(topic_lower)
                except FileNotFoundError:
                    pass
                except (json.JSONDecodeError, OSError) as e:
                    print(f"[PINYIN] 加载话题拼音纠正失败 {topic}: {e}", flush=True)
        return self.pinyin_corrections

    def sync_protected_from_keywords(self):
        """将已加载的 KW 关键词同步为受保护短语，防止纠正引擎修改已正确的关键词"""
        for kw in self.kw_set:
            if len(kw) >= 2:
                self.protected_phrases.add(kw)

    def apply_pinyin_dict_correction(self, text):
        if not self.pinyin_corrections or not text:
            return text, []
        sorted_entries = sorted(
            ((k, v) for k, v in self.pinyin_corrections.items() if not k.startswith('__')),
            key=lambda x: len(x[0].split()), reverse=True)

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

    def load_text_corrections(self, topic=None):
        """加载英文/数字文本直接替换纠错字典（用于选手名、ID等非拼音可处理的词）"""
        base_dir = DICT_DIR / 'text_corrections'
        base_dir.mkdir(exist_ok=True)
        general_path = base_dir / 'general.json'
        if general_path.exists():
            try:
                with open(general_path, 'r', encoding='utf-8') as f:
                    self.text_corrections.update(json.load(f))
            except FileNotFoundError:
                pass
            except (json.JSONDecodeError, OSError) as e:
                print(f"[TEXT] 加载通用文本纠正失败: {e}", flush=True)
        if topic:
            topic_lower = topic.lower().strip()
            if topic_lower in self._loaded_text_topics:
                return self.text_corrections
            topic_path = base_dir / f'{topic_lower}.json'
            if topic_path.exists():
                try:
                    with open(topic_path, 'r', encoding='utf-8') as f:
                        self.text_corrections.update(json.load(f))
                    print(f"[TEXT] 加载话题文本纠正: {topic} ({topic_path.name})", flush=True)
                    self._loaded_text_topics.add(topic_lower)
                except (json.JSONDecodeError, OSError):
                    pass
        return self.text_corrections

    def apply_text_correction(self, text):
        """对英文/数字token做直接文本替换（大小写不敏感，整词匹配）"""
        if not self.text_corrections or not text:
            return text, []

        sorted_entries = sorted(
            ((k, v) for k, v in self.text_corrections.items() if not k.startswith('__')),
            key=lambda x: len(x[0]), reverse=True)

        corrections = []
        result = text

        for pattern, replacement in sorted_entries:
            if pattern == replacement:
                continue
            regex = re.compile(r'(?<![a-zA-Z0-9])' + re.escape(pattern) + r'(?![a-zA-Z0-9])', re.IGNORECASE)
            new_result, count = regex.subn(replacement, result)
            if count > 0:
                corrections.append((pattern, replacement))
                result = new_result

        if corrections:
            print(f"    [TEXT] {len(corrections)}处文本纠正: {corrections[:5]}", flush=True)
        return result, corrections
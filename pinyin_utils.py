# -*- coding: utf-8 -*-
"""
拼音工具模块
关键词管理 / 文本相似度比对
"""

import re

try:
    from pypinyin import lazy_pinyin, Style
except ImportError:
    lazy_pinyin = None
    Style = None


# ---- 关键词分类常量 ----

CATEGORIES = {
    'speaker': '主讲人',
    'other': '关键词',
}

CATEGORY_ICONS = {
    'speaker': '👤',
    'other': '📌',
}


class PinyinCorrector:

    def __init__(self, keyword_store=None):
        self.kw_set = set()
        # 缓存：关键词 → 拼音列表，避免每次纠正都重新转换
        self._kw_pinyin_cache = {}
        if keyword_store:
            for cat_kws in keyword_store.values():
                if isinstance(cat_kws, (set, list)):
                    self.kw_set.update(cat_kws)

    def reset_session(self):
        """重置会话状态：清空关键词集合和拼音缓存"""
        self.kw_set.clear()
        self._kw_pinyin_cache.clear()

    def _get_kw_pinyin(self, keyword):
        """获取关键词的拼音列表（带缓存）"""
        if keyword in self._kw_pinyin_cache:
            return self._kw_pinyin_cache[keyword]
        if lazy_pinyin is None:
            return None
        py = lazy_pinyin(keyword, style=Style.NORMAL)
        self._kw_pinyin_cache[keyword] = py
        return py

    def correct_with_keywords(self, text):
        """用关键词的拼音匹配纠正文本中的同音错误。

        逻辑：关键词→拼音，文本→逐字拼音，找到拼音匹配的位置→替换为关键词。
        例如：关键词"寅子"，ASR输出"银子" → 拼音都是 yin+zi → 替换为"寅子"。

        Returns:
            (corrected_text, corrections_list)
            corrections_list: [(original, corrected), ...]
        """
        if not self.kw_set or not text or lazy_pinyin is None:
            return text, []

        corrections = []

        # 提取文本中的中文字符及其位置和拼音
        # 只处理中文字符，跳过标点、英文等
        char_info = []  # [(index_in_text, char, pinyin), ...]
        for i, ch in enumerate(text):
            if '\u4e00' <= ch <= '\u9fff':
                py = lazy_pinyin(ch, style=Style.NORMAL)[0]
                char_info.append((i, ch, py))

        if not char_info:
            return text, []

        # 对每个关键词，在文本中查找拼音匹配
        for keyword in self.kw_set:
            kw_py = self._get_kw_pinyin(keyword)
            if not kw_py or len(kw_py) < 2:
                continue

            kw_len = len(kw_py)

            # 同一关键词可能出现多次，用 while 循环重复扫描直到没有新匹配
            while char_info and len(char_info) >= kw_len:
                found = False
                # 滑动窗口匹配拼音序列
                for start in range(len(char_info) - kw_len + 1):
                    # 检查拼音是否匹配
                    match = True
                    for j in range(kw_len):
                        if char_info[start + j][2] != kw_py[j]:
                            match = False
                            break

                    if not match:
                        continue

                    # 拼音匹配成功，检查原文是否已经是正确关键词
                    original = ''.join(char_info[start + k][1] for k in range(kw_len))
                    if original == keyword:
                        continue  # 已经正确，不需要纠正

                    # 执行替换
                    idx_start = char_info[start][0]
                    idx_end = char_info[start + kw_len - 1][0]
                    text = text[:idx_start] + keyword + text[idx_end + 1:]
                    corrections.append((original, keyword))

                    # 重建 char_info（文本长度可能变化）
                    char_info = []
                    for i, ch in enumerate(text):
                        if '\u4e00' <= ch <= '\u9fff':
                            py = lazy_pinyin(ch, style=Style.NORMAL)[0]
                            char_info.append((i, ch, py))

                    found = True
                    break  # 跳出 for，重新开始 while（文本已变化）

                if not found:
                    break  # 没有更多匹配，处理下一个关键词

        return text, corrections


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

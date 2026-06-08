# -*- coding: utf-8 -*-
"""
文本处理工具函数 - 从 server.py 提取的模块级函数
"""

import re

from pinyin_utils import lazy_pinyin, Style

# ---- 常量 ----

CN_NUM_MAP = {'零': '0', '一': '1', '二': '2', '三': '3', '四': '4',
              '五': '5', '六': '6', '七': '7', '八': '8', '九': '9'}

TITLE_STOP_WORDS = {'的', '了', '是', '在', '和', '有', '不', '这', '那', '也', '就', '都', '要', '会',
                    '我', '你', '他', '她', '它', '们', '个', '吗', '吧', '呢', '啊', '哦', '嗯',
                    '怎么', '什么', '为什么', '可以', '不能', '没有', '不是', '还是', '已经',
                    '一个', '这个', '那个', '哪个', '什么', '怎么', '这样', '那样',
                    '视频', '直播', '全集', '精彩', '高能', '日常', '第一', '第二', '第三',
                    '上集', '下集', '中集', '上期', '下期', '合集', '实况', '解说'}


# ---- 函数 ----

def extract_title_keywords(title):
    """从视频标题中提取有意义的专有名词/术语，用于ASR纠正"""
    stop_words = TITLE_STOP_WORDS
    keywords = set()
    cleaned = re.sub(r'[【】《》「」『』\[\]()（）""''「」]', ' ', title)
    cleaned = re.sub(r'[｜|\-—–/、，。,\.！!？?：:；;…]', ' ', cleaned)
    for word in cleaned.split():
        word = word.strip()
        if len(word) >= 2 and len(word) < 20 and word not in stop_words:
            if re.search(r'[\u4e00-\u9fff]', word) or word.isalpha():
                keywords.add(word)

    # 拆分中英混合词："m0NESY不敢相信" → "m0NESY" + "不敢相信"
    split_kws = set()
    for kw in list(keywords):
        if re.search(r'[\u4e00-\u9fff]', kw) and re.search(r'[a-zA-Z0-9]', kw):
            parts = re.split(
                r'(?<=[\u4e00-\u9fff])(?=[a-zA-Z0-9])|(?<=[a-zA-Z0-9])(?=[\u4e00-\u9fff])',
                kw)
            for part in parts:
                part = part.strip()
                if len(part) >= 2 and part not in stop_words:
                    split_kws.add(part)
        else:
            split_kws.add(kw)
    keywords = split_kws

    # 长中文短语再拆分为2-4字词（英文/数字短语不拆分，避免"m0NESY"→"m0N"等碎片）
    extra = set()
    for kw in list(keywords):
        if len(kw) >= 4 and re.search(r'[\u4e00-\u9fff]', kw):
            if re.search(r'[a-zA-Z0-9]', kw):
                continue
            for i in range(len(kw) - 1):
                for j in range(2, 5):
                    if i + j <= len(kw):
                        sub = kw[i:i + j]
                        if sub not in stop_words and len(sub) >= 2:
                            extra.add(sub)
    keywords.update(extra)
    return [w for w in keywords if len(w) >= 2 and w not in stop_words]


def normalize_letter_adjacent_numbers(text):
    chars = list(text)
    for i, ch in enumerate(chars):
        if ch in CN_NUM_MAP:
            before = chars[i - 1] if i > 0 else ''
            after = chars[i + 1] if i + 1 < len(chars) else ''
            if before.isalpha() and before.isascii():
                chars[i] = CN_NUM_MAP[ch]
            elif after.isalpha() and after.isascii():
                chars[i] = CN_NUM_MAP[ch]
    return ''.join(chars)


def levenshtein(s1, s2):
    """Levenshtein编辑距离"""
    if len(s1) < len(s2):
        return levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            cost = 0 if c1 == c2 else 1
            curr.append(min(curr[-1] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


def match_english_kw(text, keyword):
    """英文/数字关键词后备匹配：标准化+子串+编辑距离"""
    def _norm(s):
        s = s.lower()
        s = s.replace('0', 'o').replace('1', 'i').replace('3', 'e').replace('4', 'a')
        return s

    kw_norm = _norm(keyword)
    if len(kw_norm) < 1:
        return None
    tokens = re.findall(r'[a-zA-Z0-9]+', text)
    best_score = 0
    best_token = None

    for token in tokens:
        tok_norm = _norm(token)
        if len(tok_norm) < 1:
            continue

        # 子串包含
        if kw_norm in tok_norm or tok_norm in kw_norm:
            score = min(len(kw_norm), len(tok_norm)) / max(len(kw_norm), len(tok_norm))
            if score > best_score:
                best_score = score
                best_token = token

        # 编辑距离（容错ASR音译错误）
        if abs(len(tok_norm) - len(kw_norm)) <= 3:
            dist = levenshtein(tok_norm, kw_norm)
            sim = 1 - dist / max(len(tok_norm), len(kw_norm))
            if sim > best_score:
                best_score = sim
                best_token = token

    if best_token and best_score >= 0.70:
        return (best_token, best_score)
    return None


def dedup_overlap(prev_text, new_text):
    """去除相邻两段的重叠部分（新段包含旧段末尾的内容）"""
    if not prev_text or not new_text:
        return new_text

    # 找 prev_text 末尾和 new_text 开头的最长公共子串
    max_overlap = min(len(prev_text), len(new_text), 20)
    best_len = 0

    for overlap_len in range(max_overlap, 2, -1):
        suffix = prev_text[-overlap_len:]
        prefix = new_text[:overlap_len]
        if suffix == prefix:
            best_len = overlap_len
            break

    if best_len > 0:
        return new_text[best_len:].strip()

    # 模糊匹配：旧段末尾几个词是否在新段开头出现
    prev_tail = prev_text[-15:] if len(prev_text) >= 15 else prev_text
    if len(prev_tail) >= 4 and prev_tail in new_text[:len(new_text) // 2]:
        idx = new_text.find(prev_tail)
        return new_text[idx + len(prev_tail):].strip()

    return new_text


def dedup_chars(text):
    """移除流式ASR产生的字符级重复幻觉（如 那那→那、现现在→现在、落落地地→落地）。
    仅在重复密度 >15% 时触发，避免误删正常的叠词（慢慢、常常、高高兴兴等）。"""
    if not text or len(text) < 3:
        return text

    chinese = re.findall(r'[\u4e00-\u9fff]', text)
    if len(chinese) < 4:
        return text

    dup_count = 0
    for i in range(len(text) - 1):
        if text[i] == text[i + 1] and '\u4e00' <= text[i] <= '\u9fff':
            dup_count += 1

    dup_ratio = dup_count / len(chinese)
    if dup_ratio < 0.15 or dup_count < 3:
        return text

    result = []
    i = 0
    while i < len(text):
        if i + 1 < len(text) and text[i] == text[i + 1] and '\u4e00' <= text[i] <= '\u9fff':
            result.append(text[i])
            i += 2
        else:
            result.append(text[i])
            i += 1

    deduped = ''.join(result)
    if deduped != text:
        print(f"    [DEDUP] '{text[:40]}' → '{deduped[:40]}'", flush=True)
    return deduped


def log_fmt_time(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:05.2f}"
    return f"{m:02d}:{s:05.2f}"


def fmt_time(sec, page_type, video_offset):
    if page_type == 'live':
        m = int(sec // 60)
        s = sec % 60
        if m > 0:
            return f"T0+{m:02d}:{s:05.2f}"
        return f"T0+{s:05.2f}"
    abs_sec = sec + video_offset
    return log_fmt_time(abs_sec)


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
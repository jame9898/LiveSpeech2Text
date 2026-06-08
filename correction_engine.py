# -*- coding: utf-8 -*-
"""
智能纠错引擎 — 简化版
  实体纠正 → 拼音纠正 → 文本纠正（三步管线）
"""

import re
import json
from pathlib import Path

from core import DICT_DIR
from text_utils import levenshtein


# ============================================================
# 工具函数
# ============================================================

# leet-speak 归一化映射
LEET_MAP = {
    '0': 'o', '1': 'i', '2': 'z', '3': 'e', '4': 'a',
    '5': 's', '6': 'g', '7': 't', '8': 'b', '9': 'g',
    '@': 'a', '$': 's', '+': 't',
}


def normalize_leet(text):
    """对含字母+数字的 token 做 leet 归一化"""
    if not re.search(r'[a-zA-Z]', text) or not re.search(r'[0-9]', text):
        return text
    return ''.join(LEET_MAP.get(ch, ch.lower()) for ch in text.lower())


def similarity(a, b):
    """字符串相似度 0-1"""
    if not a or not b:
        return 0.0
    a, b = a.lower(), b.lower()
    if a == b:
        return 1.0
    a_norm = normalize_leet(a)
    b_norm = normalize_leet(b)
    if a_norm == b_norm:
        return 0.95
    dist = levenshtein(a_norm, b_norm)
    max_len = max(len(a_norm), len(b_norm))
    return 1.0 - dist / max_len


# ============================================================
# EntityRegistry — 实体注册表
# ============================================================

class EntityRegistry:
    """领域知识库：战队、选手、地图、术语及其别名
    支持按话题加载：dict/entities/{topic}.json
    """

    def __init__(self):
        self.teams = {}       # canonical → {aliases, players}
        self.players = {}     # canonical → {aliases, team}
        self.maps = {}        # canonical → {aliases}
        self.terms = {}       # canonical → {aliases}
        self._alias_index = {}  # alias → (type, canonical)
        self._loaded_topics = set()
        self._load()

    def _load(self):
        """初始加载：加载旧版 entity_data.json 兜底，话题实体由 load_topic() 按需加载"""
        legacy_path = DICT_DIR / 'entity_data.json'
        if legacy_path.exists():
            self._parse_entity_file(legacy_path)

    def reset(self):
        """重置所有实体数据，回到初始状态"""
        self.teams.clear()
        self.players.clear()
        self.maps.clear()
        self.terms.clear()
        self._alias_index.clear()
        self._loaded_topics.clear()
        self._load()

    def load_topic(self, topic):
        """按话题加载实体数据：dict/entities/{topic}.json"""
        topic_lower = topic.lower().strip()
        if topic_lower in self._loaded_topics:
            return
        path = DICT_DIR / 'entities' / f'{topic_lower}.json'
        if path.exists():
            self._parse_entity_file(path)
            self._loaded_topics.add(topic_lower)
            print(f"[ENTITY] 话题实体加载: {topic} ({path.name})", flush=True)

    def _parse_entity_file(self, path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        except (json.JSONDecodeError, OSError) as e:
            print(f"[ENTITY] 解析失败 {path.name}: {e}", flush=True)
            return

        before = len(self._alias_index)

        for team in data.get('teams', []):
            name = team['name']
            self.teams[name] = {
                'aliases': team.get('aliases', []),
                'players': team.get('players', []),
            }
            self._index_entity('team', name, team.get('aliases', []))

        for player in data.get('players', []):
            name = player['name']
            self.players[name] = {
                'aliases': player.get('aliases', []),
                'team': player.get('team', ''),
            }
            self._index_entity('player', name, player.get('aliases', []))

        for m in data.get('maps', []):
            name = m['name']
            self.maps[name] = {'aliases': m.get('aliases', [])}
            self._index_entity('map', name, m.get('aliases', []))

        for term in data.get('terms', []):
            name = term['name']
            self.terms[name] = {'aliases': term.get('aliases', [])}
            self._index_entity('term', name, term.get('aliases', []))

        added = len(self._alias_index) - before
        if added > 0:
            print(f"[ENTITY] 知识库加载: {len(self.teams)}队 {len(self.players)}人 "
                  f"{len(self.maps)}图 {len(self.terms)}术语 (+{added}条)", flush=True)

    def _index_entity(self, etype, canonical, aliases):
        self._alias_index[canonical.lower()] = (etype, canonical)
        for alias in aliases:
            self._alias_index[alias.lower()] = (etype, canonical)

    def lookup(self, text):
        """精确查找实体"""
        key = text.lower().strip()
        if key in self._alias_index:
            etype, canonical = self._alias_index[key]
            return {'type': etype, 'canonical': canonical, 'input': text}
        return None

    def fuzzy_lookup(self, text, min_score=0.70):
        """模糊查找：返回所有相似度 >= min_score 的实体"""
        results = []
        key = text.lower().strip()
        if len(key) < 2:
            return results

        for alias, (etype, canonical) in self._alias_index.items():
            if len(alias) < 2:
                continue
            sim = similarity(key, alias)
            if sim >= min_score:
                results.append({
                    'type': etype,
                    'canonical': canonical,
                    'matched_alias': alias,
                    'input': text,
                    'score': sim,
                })
        results.sort(key=lambda x: x['score'], reverse=True)
        return results


# ============================================================
# CorrectionEngine — 纠错引擎（简化版，三步管线）
# ============================================================

class CorrectionEngine:
    """
    简化纠错引擎
    三步管线：实体纠正 → 拼音纠正 → 文本纠正
    """

    def __init__(self):
        self.registry = EntityRegistry()

    def load_topic(self, topic):
        """按话题加载实体知识库"""
        self.registry.load_topic(topic)

    def reset_session(self):
        """重置会话状态：清空实体注册表"""
        self.registry.reset()

    def correct(self, text, pinyin_corrector=None):
        """
        主纠错入口（三步管线）
        Args:
            text: 输入文本
            pinyin_corrector: PinyinCorrector 实例（可选，用于拼音/文本纠错）
        Returns:
            (corrected_text, corrections)
            corrections 为 [[old, new], ...] 元组列表，直接可发送给前端渲染
        """
        if not text or not text.strip():
            return text, []

        corrections = []

        # ---- Step 1: 实体纠正（别名规范化 + 模糊实体匹配） ----
        text = self._correct_entities(text, corrections)

        # ---- Step 2: 拼音纠正（委托给 PinyinCorrector） ----
        if pinyin_corrector:
            text, pinyin_corrs = pinyin_corrector.apply_pinyin_dict_correction(text)
            corrections.extend(pinyin_corrs)

        # ---- Step 3: 文本纠正（英文/数字直接替换） ----
        if pinyin_corrector:
            text, text_corrs = pinyin_corrector.apply_text_correction(text)
            corrections.extend(text_corrs)

        return text, corrections

    def _correct_entities(self, text, corrections):
        """实体纠正：先别名规范化，再模糊匹配"""
        text = self._normalize_aliases(text, corrections)
        text = self._fuzzy_correct_entities(text, corrections)
        return text

    def _normalize_aliases(self, text, corrections):
        """将已知别名替换为规范名（跨语言不替换，保留原文语言）"""
        already_done = set()

        # 收集所有需要替换的别名（别名 ≠ 规范名），按长度降序避免部分匹配
        candidates = []
        for alias, (etype, canonical) in self.registry._alias_index.items():
            if canonical.lower() == alias.lower() and canonical == alias:
                continue
            if alias in already_done:
                continue
            already_done.add(alias)
            candidates.append((alias, canonical, etype))
        candidates.sort(key=lambda x: len(x[0]), reverse=True)

        for alias, canonical, etype in candidates:
            # 跨语言不替换：别名含中文而规范名纯英文时跳过，反之亦然
            _has_cjk = lambda s: bool(re.search(r'[\u4e00-\u9fff\u3400-\u4dbf]', s))
            if _has_cjk(alias) != _has_cjk(canonical):
                continue
            pattern = r'(?<![a-zA-Z0-9])' + re.escape(alias) + r'(?![a-zA-Z0-9])'
            new_text = re.sub(pattern, canonical, text, count=1, flags=re.IGNORECASE)
            if new_text != text:
                corrections.append((alias, canonical))
                text = new_text
                print(f"    [ALIAS] '{alias}' → '{canonical}'", flush=True)

        return text

    def _fuzzy_correct_entities(self, text, corrections):
        """模糊匹配并纠正未知 token"""
        tokens = re.findall(r'[a-zA-Z0-9]+|[\u4e00-\u9fff]{2,}', text)
        already_known = set()

        for token in tokens:
            token_lower = token.lower()
            if token_lower in already_known:
                continue
            already_known.add(token_lower)

            # 跳过已知实体
            if self.registry.lookup(token):
                continue

            # 跳过短 token
            if len(token) < 2:
                continue

            # 模糊查找
            fuzzy = self.registry.fuzzy_lookup(token, min_score=0.72)
            if fuzzy and fuzzy[0]['score'] >= 0.80:
                best = fuzzy[0]
                canonical = best['canonical']
                if canonical.lower() != token_lower:
                    pattern = r'(?<![a-zA-Z0-9])' + re.escape(token) + r'(?![a-zA-Z0-9])'
                    text = re.sub(pattern, canonical, text, count=1)
                    corrections.append((token, canonical))
                    print(f"    [FUZZY] '{token}' → '{canonical}' "
                          f"(score={best['score']:.2f})", flush=True)

        return text
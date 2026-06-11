# -*- coding: utf-8 -*-
"""
智能纠错引擎 — 简化版
  实体纠正 → 拼音纠正 → 文本纠正（三步管线）
"""

import json
from pathlib import Path

from core import DICT_DIR


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


# ============================================================
# CorrectionEngine — 纠错引擎（拼音字典纠正）
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

        # ---- 拼音纠正（委托给 PinyinCorrector） ----
        # 仅保留拼音纠正（覆盖平翘舌、前后鼻音、n/l、h/f、r/l 等常见发音错误）
        # 已跳过实体纠正和文本纠正，减少延迟
        if pinyin_corrector:
            text, pinyin_corrs = pinyin_corrector.apply_pinyin_dict_correction(text)
            corrections.extend(pinyin_corrs)

        return text, corrections
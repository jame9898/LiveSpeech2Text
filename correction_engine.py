# -*- coding: utf-8 -*-
"""
智能纠错引擎 — 比赛场景专用
  实体识别 · 模糊匹配 · 语法检查 · 置信度评分 · 纠错管线
"""

import re
import json
from pathlib import Path

from core import DICT_DIR
from text_utils import levenshtein

# ============================================================
# 常量
# ============================================================

# leet-speak 归一化映射
LEET_MAP = {
    '0': 'o', '1': 'i', '2': 'z', '3': 'e', '4': 'a',
    '5': 's', '6': 'g', '7': 't', '8': 'b', '9': 'g',
    '@': 'a', '$': 's', '+': 't',
}

# 常见 CS 句子模式（主语 + 动作）
CS_SENTENCE_PATTERNS = [
    (r'^(.+?)(?:的)?(?:打|玩|拿|起|用|丢|扔|扔了|买了|起了|拿了|架了|拉了|peek|rush|push|hold|defend|attack|rotate|smoke|flash|nade)(?:了|的|一下|一波|一个|一次|对方|对面)?', 'action'),
    (r'^(.+?)(?:在|去|到|往|从|回)(?:A|B|中路|小道|大道|连接|拱门|香蕉道|B洞|A大|A小|B大|B小|A门|B门|A区|B区|警家|匪家|CT家|T家|A包|B包|A点|B点|A平台|B平台|下水道|VIP|超市|工地|书房|锅炉房|管道|红楼梯|黄房|绿通|蓝箱|红箱)', 'movement'),
    (r'^(.+?)(?:被|把|给)(?:打|杀|狙|刀|电|烧|炸|闪|白|阴|偷)(?:了|死|掉)', 'passive'),
    (r'^(.+?)(?:残局|一打|二打|三打|四打|五打|eco|ECO|手枪局|长枪局|半起|强起|全起|混起)', 'situation'),
]

# 常见无意义主语（ASR 幻听/噪声词）
NONSENSE_SUBJECTS = {
    'the', 'a', 'an', 'is', 'was', 'are', 'were', 'be', 'been',
    'i', 'you', 'he', 'she', 'it', 'we', 'they',
    'this', 'that', 'these', 'those',
    'and', 'or', 'but', 'so', 'if', 'then', 'when',
    'to', 'of', 'in', 'on', 'at', 'for', 'with', 'by',
    '嗯', '啊', '哦', '呃', '额', '唔', '那个', '这个', '就是',
}


# ============================================================
# 工具函数
# ============================================================

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
    # leet 归一化后再比
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
    """比赛领域知识库：战队、选手、地图、术语及其别名
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
        """初始加载：仅加载旧版 entity_data.json 兜底，话题实体由 load_topic() 按需加载"""
        # 旧版兜底
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

    def get_all_entity_strings(self):
        """返回所有实体字符串（用于关键词匹配）"""
        return set(self._alias_index.keys())


# ============================================================
# GrammarChecker — 语法结构分析
# ============================================================

class GrammarChecker:
    """比赛场景语法结构检查：主语识别、主谓宾关系"""

    def __init__(self, registry):
        self.registry = registry

    def extract_subject(self, text):
        """从文本中提取主语"""
        if not text:
            return None

        # 尝试匹配 CS 句子模式
        for pattern, ptype in CS_SENTENCE_PATTERNS:
            m = re.match(pattern, text)
            if m:
                subject = m.group(1).strip()
                if subject and len(subject) >= 1:
                    return {'text': subject, 'pattern': ptype}

        # 简单启发式：取第一个逗号/空格前的词作为主语
        tokens = re.split(r'[，,。\.\s]+', text)
        if tokens:
            first = tokens[0].strip()
            if len(first) >= 1:
                return {'text': first, 'pattern': 'first_token'}

        return None

    def validate_subject(self, subject_text):
        """验证主语是否合理：是否为已知实体，或是否为合理的人名/队名"""
        if not subject_text or len(subject_text) < 1:
            return {'valid': False, 'reason': 'empty'}

        subj_lower = subject_text.lower().strip()

        # 无意义词
        if subj_lower in NONSENSE_SUBJECTS:
            return {'valid': False, 'reason': 'nonsense_word'}

        # 纯数字或纯标点
        if re.match(r'^[\d\W_]+$', subject_text):
            return {'valid': False, 'reason': 'numeric_or_punct'}

        # 已知实体
        entity = self.registry.lookup(subject_text)
        if entity:
            return {'valid': True, 'reason': 'known_entity', 'entity': entity}

        # 模糊匹配
        fuzzy = self.registry.fuzzy_lookup(subject_text, min_score=0.75)
        if fuzzy:
            best = fuzzy[0]
            return {
                'valid': True,
                'reason': 'fuzzy_match',
                'entity': best,
                'confidence': best['score'],
            }

        # 看起来像人名/队名（英文大写开头、中文2-4字等）
        if re.match(r'^[A-Z][a-z]+$', subject_text):
            return {'valid': True, 'reason': 'looks_like_name', 'suggestion': True}
        if re.match(r'^[\u4e00-\u9fff]{2,4}$', subject_text):
            return {'valid': True, 'reason': 'looks_like_cn_name', 'suggestion': True}

        # 默认：不太确定，但不拒绝
        return {'valid': True, 'reason': 'unknown', 'confidence': 0.5}

    def check(self, text):
        """完整的语法检查"""
        result = {
            'text': text,
            'subject': None,
            'issues': [],
            'score': 1.0,
        }

        subject = self.extract_subject(text)
        if subject:
            result['subject'] = subject
            validation = self.validate_subject(subject['text'])
            if not validation['valid']:
                result['issues'].append({
                    'type': 'subject',
                    'text': subject['text'],
                    'reason': validation['reason'],
                })
                result['score'] -= 0.2
            elif validation.get('suggestion'):
                result['issues'].append({
                    'type': 'subject_unknown',
                    'text': subject['text'],
                    'reason': '可能需要纠错',
                })
                result['score'] -= 0.05

        return result


# ============================================================
# ConfidenceScorer — 置信度评分
# ============================================================

class ConfidenceScorer:
    """纠错置信度评估"""

    HIGH = 0.90
    MEDIUM = 0.70
    LOW = 0.50

    def score_pinyin_correction(self, original, corrected, pinyin_match):
        """拼音纠错置信度"""
        if original == corrected:
            return 0.0
        # 精确拼音匹配 → 高置信度
        if pinyin_match:
            return 0.92
        return 0.75

    def score_text_correction(self, original, corrected, is_exact=False):
        """文本纠错置信度"""
        if original == corrected:
            return 0.0
        if is_exact:
            return 0.95
        sim = similarity(original.lower(), corrected.lower())
        if sim >= 0.90:
            return 0.85
        return max(0.60, sim)

    def score_entity_match(self, entity, score):
        """实体匹配置信度"""
        if score >= 0.95:
            return 0.98
        if score >= 0.85:
            return 0.90
        if score >= 0.70:
            return 0.75
        return score

    def should_auto_apply(self, confidence):
        """高置信度自动应用，低置信度仅建议"""
        return confidence >= self.HIGH

    def get_level(self, confidence):
        if confidence >= self.HIGH:
            return 'high'
        if confidence >= self.MEDIUM:
            return 'medium'
        return 'low'


# ============================================================
# CorrectionEngine — 纠错引擎（主入口）
# ============================================================

class CorrectionEngine:
    """
    智能纠错引擎
    整合：实体识别 → 拼音纠错 → 文本纠错 → 模糊匹配 → 语法检查 → 置信度评分
    """

    def __init__(self):
        self.registry = EntityRegistry()
        self.grammar = GrammarChecker(self.registry)
        self.scorer = ConfidenceScorer()
        self._stats = {'total': 0, 'corrected': 0, 'high_conf': 0}

    def load_topic(self, topic):
        """按话题加载实体知识库（CS2等）"""
        self.registry.load_topic(topic)

    def reset_session(self):
        """重置会话状态：清空实体注册表、纠错日志和统计"""
        self.registry.reset()
        self._stats = {'total': 0, 'corrected': 0, 'high_conf': 0}

    def correct(self, text, pinyin_corrector=None, context=None):
        """
        主纠错入口
        Args:
            text: 输入文本
            pinyin_corrector: PinyinCorrector 实例（可选，用于拼音纠错）
            context: 上下文信息（话题、历史文本等）
        Returns:
            {
                'text': 纠错后文本,
                'original': 原文,
                'corrections': [{type, original, corrected, confidence, reason}],
                'entities': [{type, canonical, position}],
                'grammar': {...},
                'stats': {...}
            }
        """
        if not text or not text.strip():
            return {'text': text, 'original': text, 'corrections': [],
                    'entities': [], 'grammar': {}, 'stats': {}}

        self._stats['total'] += 1
        original = text
        corrections = []
        entities_found = []

        # ---- 1. 实体识别 ----
        entities_found = self._recognize_entities(text)

        # ---- 1.5. 别名规范化（已知别名 → 规范名） ----
        text, alias_corrs = self._normalize_aliases(text)
        for orig, canonical, entity in alias_corrs:
            corrections.append({
                'type': 'alias',
                'original': orig,
                'corrected': canonical,
                'confidence': 0.95,
                'level': 'high',
                'entity': entity,
            })

        # ---- 2. 拼音纠错（委托给 PinyinCorrector） ----
        if pinyin_corrector:
            text, pinyin_corrs = pinyin_corrector.apply_pinyin_dict_correction(text)
            for orig, corr in pinyin_corrs:
                conf = self.scorer.score_pinyin_correction(orig, corr, True)
                corrections.append({
                    'type': 'pinyin',
                    'original': orig,
                    'corrected': corr,
                    'confidence': conf,
                    'level': self.scorer.get_level(conf),
                })

        # ---- 3. 文本纠错（英文/数字） ----
        if pinyin_corrector:
            text, text_corrs = pinyin_corrector.apply_text_correction(text)
            for orig, corr in text_corrs:
                conf = self.scorer.score_text_correction(orig, corr, True)
                corrections.append({
                    'type': 'text',
                    'original': orig,
                    'corrected': corr,
                    'confidence': conf,
                    'level': self.scorer.get_level(conf),
                })

        # ---- 4. 模糊实体匹配 ----
        text, fuzzy_corrs = self._fuzzy_correct_entities(text)
        for orig, corr, entity, score in fuzzy_corrs:
            conf = self.scorer.score_entity_match(entity, score)
            corrections.append({
                'type': 'entity_fuzzy',
                'original': orig,
                'corrected': corr,
                'confidence': conf,
                'level': self.scorer.get_level(conf),
                'entity': entity,
            })

        # ---- 5. 语法检查 ----
        grammar_result = self.grammar.check(text)

        # ---- 统计 ----
        if corrections:
            self._stats['corrected'] += 1
        high_conf = [c for c in corrections if c['confidence'] >= self.scorer.HIGH]
        if high_conf:
            self._stats['high_conf'] += len(high_conf)

        return {
            'text': text,
            'original': original,
            'corrections': corrections,
            'entities': entities_found,
            'grammar': grammar_result,
            'stats': dict(self._stats),
        }

    def _recognize_entities(self, text):
        """识别文本中的实体"""
        entities = []
        tokens = re.findall(r'[a-zA-Z0-9]+|[\u4e00-\u9fff]+', text)
        pos = 0
        for token in tokens:
            idx = text.find(token, pos)
            if idx >= 0:
                pos = idx + len(token)
            entity = self.registry.lookup(token)
            if entity:
                entities.append({
                    'type': entity['type'],
                    'canonical': entity['canonical'],
                    'text': token,
                    'position': idx,
                })
        return entities

    def _normalize_aliases(self, text):
        """将已知别名替换为规范名（如 safe→saffee, monesy→m0NESY, 小孩→m0NESY）"""
        corrections = []
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
            pattern = r'(?<![a-zA-Z0-9])' + re.escape(alias) + r'(?![a-zA-Z0-9])'
            new_text = re.sub(pattern, canonical, text, count=1, flags=re.IGNORECASE)
            if new_text != text:
                corrections.append((alias, canonical,
                    {'type': etype, 'canonical': canonical, 'input': alias}))
                text = new_text
                print(f"    [ALIAS] '{alias}' → '{canonical}'", flush=True)

        return text, corrections

    def _fuzzy_correct_entities(self, text):
        """模糊匹配并纠正未知 token"""
        corrections = []
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
                # 仅当相似度足够高且不是已有词时替换
                if canonical.lower() != token_lower:
                    # 整词替换（使用 lookbehind/lookahead 兼容中英文边界）
                    pattern = r'(?<![a-zA-Z0-9])' + re.escape(token) + r'(?![a-zA-Z0-9])'
                    text = re.sub(
                        pattern,
                        canonical,
                        text,
                        count=1,
                    )
                    corrections.append((token, canonical, best, best['score']))
                    print(f"    [FUZZY] '{token}' → '{canonical}' "
                          f"(score={best['score']:.2f})", flush=True)

        return text, corrections

    def suggest(self, text, pinyin_corrector=None):
        """仅提供纠错建议，不自动应用（用于低置信度场景）"""
        result = self.correct(text, pinyin_corrector)
        suggestions = []
        for c in result['corrections']:
            if c['confidence'] < self.scorer.HIGH:
                suggestions.append(c)
        return suggestions

    def get_stats(self):
        return dict(self._stats)


# ============================================================
# 全局实例
# ============================================================

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = CorrectionEngine()
    return _engine
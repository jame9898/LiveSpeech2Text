# -*- coding: utf-8 -*-
"""
话题关键词管理
根据话题标签自动匹配关键词，用于 ASR 纠正
"""
import json

from core import DICT_DIR


class TopicKeywordManager:
    def __init__(self):
        self.topics = {}
        self._load()

    def _load(self):
        path = DICT_DIR / 'topic_keywords.json'
        if not path.exists():
            print(f"[TOPIC] 话题库文件不存在: {path}")
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.topics = data.get('topics', {})
            print(f"[TOPIC] 话题关键词库加载: {len(self.topics)}个话题")
        except Exception as e:
            print(f"[TOPIC] 加载失败: {e}")

    def get_matched_topics(self, tags):
        matched = set()
        for tag in tags:
            tag_clean = tag.lower().strip().lstrip('#')
            for topic, topic_data in self.topics.items():
                aliases = topic_data.get('aliases', [])
                topic_lower = topic.lower()
                if tag_clean == topic_lower or tag == topic:
                    matched.add(topic)
                    break
                elif tag_clean == topic_lower.replace('#', ''):
                    matched.add(topic)
                    break
                else:
                    hit = False
                    for alias in aliases:
                        alias_lower = alias.lower().strip().lstrip('#')
                        if tag_clean == alias_lower:
                            hit = True
                            break
                        elif len(tag_clean) >= 2 and (tag_clean in alias_lower or alias_lower in tag_clean):
                            hit = True
                            break
                    if hit:
                        matched.add(topic)
                        break
        return matched

    def match_and_load(self, tags):
        """匹配标签并返回对应话题的关键词合集"""
        keywords = []
        matched_topics = self.get_matched_topics(tags)
        for topic in matched_topics:
            topic_data = self.topics[topic]
            kws = topic_data.get('keywords', [])
            keywords.extend(kws)
        return list(dict.fromkeys(keywords)), matched_topics


TOPIC_MANAGER = TopicKeywordManager()

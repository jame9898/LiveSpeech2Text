# -*- coding: utf-8 -*-
"""关键词联想扩展 — 大模型辅助生成相关词，提升ASR纠正准确率"""
import json

from core import DICT_DIR

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



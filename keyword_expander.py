# -*- coding: utf-8 -*-
"""关键词联想扩展 — 大模型辅助生成相关词，提升ASR纠正准确率"""
import json
import re
from pathlib import Path
from collections import OrderedDict

KW_DIR = Path(__file__).parent / "dict"
KW_DIR.mkdir(exist_ok=True)

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


class KeywordExpander:
    """关键词扩展器 — 本地同义词典 + 可选大模型API"""

    def __init__(self):
        self.synonym_cache = {}
        self._load_builtin_synonyms()

    def _load_builtin_synonyms(self):
        sf = KW_DIR / "synonyms.json"
        if sf.exists():
            try:
                with open(sf, 'r', encoding='utf-8') as f:
                    self.synonym_cache = json.load(f)
            except Exception:
                pass

    def expand(self, keyword, category='other', max_terms=8):
        """
        扩展关键词 → 返回相关词列表
        优先本地同义词库，再尝试大模型API
        """
        kw_lower = keyword.strip().lower()
        if not kw_lower or len(kw_lower) < 2:
            return []

        expanded = set()
        expanded.add(keyword.strip())

        # 1. 本地同义词库
        if kw_lower in self.synonym_cache:
            for syn in self.synonym_cache[kw_lower]:
                expanded.add(syn)

        # 2. 简单规则扩展（中文分词变体）
        rule_expanded = self._rule_expand(keyword)
        expanded.update(rule_expanded)

        return list(expanded)[:max_terms]

    def _rule_expand(self, keyword):
        """规则扩展：近音混淆、拆分组合、常见变体"""
        results = set()

        suffixes = ['的', '了', '是', '有', '人', '者', '性', '化', '学', '主义', '系统', '模型',
                    '问题', '方法', '技术', '理论', '原理', '工程', '科学', '研究', '发展', '经济']
        prefixes = ['大', '小', '高', '低', '新', '旧', '超', '微', '非', '反', '多', '单', '全', '半']

        for sfx in suffixes:
            if keyword.endswith(sfx) and len(keyword) > len(sfx) + 1:
                results.add(keyword[:-len(sfx)])

        for pfx in prefixes:
            if keyword.startswith(pfx) and len(keyword) > len(pfx) + 1:
                results.add(keyword[len(pfx):])

        confusion_pairs = {
            '图形': ['图像', '图形化'],
            '图像': ['图形', '图象'],
            '识别': ['辨识', '甄别'],
            '模型': ['模块', '模拟'],
            '数据': ['数字', '数据库'],
            '处理': ['梳理', '处置'],
            '分析': ['解析', '分解'],
            '检测': ['监测', '检查'],
            '计算': ['计数', '核算'],
            '学习': ['学期', '练习'],
            '智能': ['职能', '只能'],
            '网络': ['往路', '网格'],
            '算法': ['酸法', '算盘'],
            '系统': ['细统', '体系'],
            '服务': ['辅助', '服务器'],
            '应用': ['运用', '应用层'],
            '开发': ['开法', '研发'],
            '设计': ['涉及', '设置'],
            '管理': ['惯例', '整理'],
            '控制': ['空置', '指控'],
            '安全': ['暗权', '安检'],
            '支持': ['智齿', '支柱'],
            '功能': ['公能', '功用'],
            '结果': ['结构', '结合'],
            '过程': ['工程', '历程'],
            '语言': ['寓言', '语文'],
            '代码': ['带码', '编码'],
            '文件': ['稳健', '文档'],
            '生成': ['深层', '产生'],
            '训练': ['迅联', '教练'],
            '优化': ['有花', '油画'],
            '理解': ['礼节', '里解'],
            '自然': ['孜然', '自燃'],
            '信息': ['新戏', '讯息'],
            '知识': ['指示', '芝士'],
            '机器': ['极其', '激起'],
            '环境': ['幻境', '还经'],
            '框架': ['矿家', '股价'],
            '测试': ['侧试', '策士'],
            '部署': ['不熟', '部属'],
            '配置': ['培植', '配制'],
            '版本': ['斑本', '板本'],
            '更新': ['庚新', '更心'],
            '安装': ['暗装', '安状'],
            '运行': ['云行', '运形'],
            '启动': ['岂动', '起东'],
            '连接': ['廉洁', '连杰'],
            '通信': ['通新', '通讯'],
            '协议': ['写意', '挟义'],
            '接口': ['街口', '借壳'],
            '参数': ['灿树', '餐数'],
            '变量': ['变两', '辩量'],
            '函数': ['含树', '寒暑'],
            '对象': ['对向', '兑奖'],
            '类型': ['泪型', '类形'],
            '属性': ['鼠性', '熟悉'],
            '方法': ['芳法', '方华'],
            '事件': ['实践', '市建'],
            '线程': ['县城', '献成'],
            '进程': ['禁城', '金城'],
            '内存': ['内春', '内寸'],
            '存储': ['纯储', '存处'],
            '缓存': ['换存', '环存'],
            '索引': ['锁印', '所引'],
            '查询': ['茶寻', '差寻'],
            '排序': ['牌序', '徘序'],
            '加密': ['家密', '夹密'],
            '解密': ['街密', '借密'],
            '验证': ['眼正', '研证'],
            '授权': ['受权', '瘦拳'],
            '登录': ['灯录', '等路'],
            '注册': ['朱策', '住册'],
        }

        if keyword in confusion_pairs:
            results.update(confusion_pairs[keyword])

        for origin, variants in confusion_pairs.items():
            if keyword in variants:
                results.add(origin)
                results.update(variants)

        semantic_map = {
            'AI': ['人工智能', '机器学习', '深度学习', '神经网络'],
            '人工智能': ['AI', '机器学习', '深度学习', '大模型', 'GPT'],
            '大模型': ['LLM', 'GPT', 'ChatGPT', 'AI', '深度学习'],
            '云': ['云计算', '云端', '云服务', '云原生'],
            '5G': ['通信', '网络', '移动'],
            'IoT': ['物联网', '传感器', '智能设备'],
            '芯片': ['半导体', '处理器', '集成电路', 'CPU', 'GPU'],
            '新能源': ['光伏', '风电', '储能', '电池', '电动车'],
            '碳中和': ['碳排放', '减排', '绿色', '可再生能源'],
            '元宇宙': ['VR', 'AR', '虚拟现实', '数字孪生'],
            '区块链': ['Web3', '加密货币', '去中心化', '智能合约'],
            '直播': ['短视频', '带货', '流量', '主播'],
            '电商': ['平台', '物流', '供应链', '新零售'],
            '自动驾驶': ['无人驾驶', '辅助驾驶', '传感器', '激光雷达'],
            '机器人': ['自动化', '机械臂', '工业机器人', '人形机器人'],
            '量子': ['量子计算', '量子通信', '量子力学'],
            '基因': ['基因编辑', 'DNA', '生物技术', 'CRISPR'],
            '疫苗': ['mRNA', '免疫', '抗体', '临床试验'],
            '教育': ['培训', '学习', '学校', '课程', '教师'],
            '医疗': ['医院', '医生', '诊断', '治疗', '健康'],
            '金融': ['银行', '投资', '证券', '保险', '基金'],
            '房地产': ['房价', '楼市', '开发商', '物业'],
        }

        if keyword in semantic_map:
            results.update(semantic_map[keyword])
        for k, v in semantic_map.items():
            if keyword in v and keyword != k:
                results.add(k)
                results.update(v)

        return list(results)

    def llm_expand(self, keyword, category='other', api_config=None):
        """
        大模型联想扩展 — 远程API或本地模型
        返回: (success, expanded_keywords_list)
        """
        if not api_config:
            api_config = self._load_api_config()

        if not api_config:
            return False, []

        try:
            import urllib.request

            prompt = self._build_prompt(keyword, category)
            expanded = self._call_llm_api(api_config, prompt)
            if expanded:
                return True, expanded
            return False, []
        except Exception as e:
            print(f"[KW-EXPAND] LLM expansion failed: {e}")
            return False, []

    def _build_prompt(self, keyword, category):
        cat_name = CATEGORIES.get(category, '其他')
        return (
            f'你是一个中文关键词扩展助手。给定一个"{cat_name}"类关键词，请列出与其紧密相关的词、'
            f'同义词、常见ASR误识别变体（拼音相近但字不同的形式）。\n\n'
            f'关键词: {keyword}\n'
            f'类别: {cat_name}\n\n'
            f'请直接输出逗号分隔的相关词列表，不要解释。最多10个。'
        )

    def _call_llm_api(self, api_config, prompt):
        url = api_config.get('url', '')
        api_key = api_config.get('api_key', '')
        model = api_config.get('model', 'qwen2.5-7b-instruct')

        if not url:
            return []

        data = json.dumps({
            'model': model,
            'messages': [
                {'role': 'system', 'content': '你是一个简洁的关键词扩展助手。只输出相关词，不要解释。'},
                {'role': 'user', 'content': prompt}
            ],
            'max_tokens': 128,
            'temperature': 0.3,
        }).encode('utf-8')

        req = urllib.request.Request(url, data=data, method='POST')
        req.add_header('Content-Type', 'application/json')
        if api_key:
            req.add_header('Authorization', f'Bearer {api_key}')

        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            content = result.get('choices', [{}])[0].get('message', {}).get('content', '')
            words = re.split(r'[,，、\s]+', content.strip())
            return [w.strip() for w in words if len(w.strip()) >= 2]

    def _load_api_config(self):
        cf = KW_DIR / "llm_config.json"
        if cf.exists():
            try:
                with open(cf, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def save_api_config(self, url, api_key, model):
        config = {'url': url, 'api_key': api_key, 'model': model}
        cf = KW_DIR / "llm_config.json"
        with open(cf, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)


# 单例
expander = KeywordExpander()
# -*- coding: utf-8 -*-
"""
说话人画像系统 — 口音特征 + 方言矫正
根据说话人的方言口音特征，自动生成 ASR 矫正映射
平翘舌(zh↔z) / 前后鼻音(en↔eng) / n-l / h-f / r-l 等
"""
import json
import os
import re
from pathlib import Path
from collections import defaultdict

try:
    from pypinyin import lazy_pinyin, Style
    HAS_PINYIN = True
except ImportError:
    HAS_PINYIN = False

PROFILE_DIR = Path(__file__).parent / "dict"
PROFILE_DIR.mkdir(exist_ok=True)

DIALECT_TRAITS = {
    'ping_qiao': {'label': '平翘舌不分', 'desc': 'zh/ch/sh ↔ z/c/s'},
    'qian_hou_biyin': {'label': '前后鼻音不分', 'desc': 'en↔eng, in↔ing, an↔ang'},
    'n_l': {'label': 'n/l不分', 'desc': 'n ↔ l 混淆'},
    'h_f': {'label': 'h/f不分', 'desc': 'h ↔ f 混淆（闽/湘/粤语常见）'},
    'r_l': {'label': 'r/l不分', 'desc': 'r ↔ l 混淆（江淮/西南官话常见）'},
    'er_hua': {'label': '儿化音缺失', 'desc': '东北/西北方言儿化多，南方少'},
    'tone_mix': {'label': '声调混用', 'desc': '二声↔三声 等声调混淆'},
}

DIALECT_PRESETS = {
    'huabei': {'label': '华北/东北官话', 'traits': ['er_hua', 'tone_mix']},
    'xinan': {'label': '西南官话（川渝云贵）', 'traits': ['ping_qiao', 'qian_hou_biyin', 'n_l']},
    'jianghuai': {'label': '江淮官话（南京/安徽）', 'traits': ['n_l', 'r_l']},
    'wu': {'label': '吴语区（上海/苏南/浙江）', 'traits': ['ping_qiao', 'qian_hou_biyin', 'n_l', 'r_l']},
    'yue': {'label': '粤语区（广东/广西）', 'traits': ['ping_qiao', 'qian_hou_biyin', 'n_l', 'h_f']},
    'min': {'label': '闽语区（福建/台湾/潮汕）', 'traits': ['ping_qiao', 'qian_hou_biyin', 'n_l', 'h_f']},
    'xiang': {'label': '湘语区（湖南）', 'traits': ['ping_qiao', 'qian_hou_biyin', 'n_l', 'h_f']},
    'kejia': {'label': '客家话（赣南/闽西/粤东）', 'traits': ['ping_qiao', 'qian_hou_biyin', 'n_l']},
    'gan': {'label': '赣语区（江西）', 'traits': ['ping_qiao', 'qian_hou_biyin', 'n_l', 'h_f']},
    'jin': {'label': '晋语区（山西/陕北）', 'traits': ['ping_qiao', 'qian_hou_biyin', 'er_hua']},
    'standard': {'label': '标准普通话（无明显方言）', 'traits': []},
    'custom': {'label': '自定义方言特征', 'traits': ['ping_qiao', 'qian_hou_biyin', 'n_l', 'h_f', 'r_l', 'er_hua', 'tone_mix']},
}


class AccentCorrectionEngine:
    """口音矫正引擎 — 根据特征生成拼音混淆映射，用于纠正ASR错字"""

    def __init__(self):
        self._init_confusion_tables()

    def _init_confusion_tables(self):
        # 声母混淆组
        self.zh_z = {'zh':'z','ch':'c','sh':'s', 'z':'zh','c':'ch','s':'sh'}
        self.nl = {'n':'l', 'l':'n'}
        self.hf = {'h':'f', 'f':'h'}
        self.rl = {'r':'l', 'l':'r'}

        # 韵母混淆组
        self.en_eng = {'en':'eng','eng':'en'}
        self.in_ing = {'in':'ing','ing':'in'}
        self.an_ang = {'an':'ang','ang':'an'}

    def get_confusion_words(self, word, traits):
        """
        根据口音特征，生成 word 的所有可能混淆变体
        traits: set of trait keys like {'ping_qiao', 'qian_hou_biyin'}
        返回: [(confused_word, trait_desc), ...]
        """
        if not HAS_PINYIN or not word or len(word) < 2:
            return []

        results = []
        try:
            py_list = lazy_pinyin(word, style=Style.TONE3, neutral_tone_with_five=True)
        except Exception:
            return []

        for i, py in enumerate(py_list):
            if not py or not py[0].isalpha():
                continue
            initial, final = self._split_pinyin(py)

            new_pys = []

            # 平翘舌混淆
            if 'ping_qiao' in traits and initial in self.zh_z:
                new_initial = self.zh_z[initial]
                new_pys.append((new_initial + final if final else new_initial, '平翘舌'))
            elif 'ping_qiao' in traits and 'zh' in py and initial not in ('zh','ch','sh'):
                alt_py = py.replace('zh','z').replace('c','z')
                # 精确匹配：检查 pinyin 是否为 zh/ch/sh 开头
                if py[0] in ('z','c','s'):
                    alt_initial = self.zh_z.get(py[0], 'z')
                    new_pys.append((alt_initial + py[1:], '平翘舌'))

            # 前后鼻音混淆
            if 'qian_hou_biyin' in traits:
                mapped = self._replace_final(final, self.en_eng)
                if mapped != final:
                    new_pys.append((initial + mapped if initial else mapped, '前后鼻音'))
                mapped = self._replace_final(final, self.in_ing)
                if mapped != final:
                    new_pys.append((initial + mapped if initial else mapped, '前后鼻音'))
                mapped = self._replace_final(final, self.an_ang)
                if mapped != final:
                    new_pys.append((initial + mapped if initial else mapped, '前后鼻音'))

            # n/l 混淆
            if 'n_l' in traits and initial in self.nl:
                new_pys.append((self.nl[initial] + final if final else self.nl[initial], 'n/l'))

            # h/f 混淆
            if 'h_f' in traits and initial in self.hf:
                new_pys.append((self.hf[initial] + final if final else self.hf[initial], 'h/f'))

            # r/l 混淆
            if 'r_l' in traits and initial in self.rl:
                new_pys.append((self.rl[initial] + final if final else self.rl[initial], 'r/l'))

            # 始终生成声调变体，确保 correct_text 的搜索循环能执行
            # ASR 常将声调识别错（如天津话 dan4→dan1），依赖 _is_phonetic_match 的声调判断
            if initial and final:
                new_pys.append((initial + final, '声调'))

            for new_py, desc in new_pys:
                confused = word[:i] + '?' + word[i+1:]
                results.append((new_py, i, desc))

        return results

    def _split_pinyin(self, py):
        initials = ['zh','ch','sh','b','p','m','f','d','t','n','l','g','k','h',
                    'j','q','x','r','z','c','s','y','w']
        py_lower = py.rstrip('12345')
        for init in initials:
            if py_lower.startswith(init):
                return init, py_lower[len(init):]
        return '', py_lower

    def _replace_final(self, final, mapping):
        for k, v in mapping.items():
            if final.endswith(k):
                return final[:-len(k)] + v
        return final

    def generate_correction_map(self, traits, known_keywords=None):
        """
        生成完整纠错字典 {(wrong, correct): trait_desc, ...}
        只保留已知关键词可验证的纠错对，避免过度纠正
        """
        if not known_keywords:
            known_keywords = []

        correction_map = {}

        for kw in known_keywords:
            kw = kw.strip()
            if len(kw) < 2:
                continue
            confusions = self.get_confusion_words(kw, traits)
            for new_py, pos, desc in confusions:
                confused = kw[:pos] + new_py + kw[pos+1:]
                if confused != kw and len(confused) == len(kw):
                    correction_map[(kw, confused, pos)] = desc

        return correction_map

    def correct_text(self, text, traits, known_keywords=None):
        """
        用口音特征矫正文本
        返回: (corrected_text, corrections_made)
        """
        if not traits or not text:
            return text, []

        if not known_keywords:
            return text, []

        corrections = []
        corrected = text

        for kw in known_keywords:
            kw = kw.strip()
            if len(kw) < 2 or kw in corrected:
                continue
            confusions = self.get_confusion_words(kw, traits)
            for new_py, pos, desc in confusions:
                confused_chars = kw[:pos] + '[' + kw[pos] + ']' + kw[pos+1:]
                # 在文本中搜索可能的混淆
                if len(kw) <= len(corrected):
                    for i in range(len(corrected) - len(kw) + 1):
                        sub = corrected[i:i+len(kw)]
                        if self._is_phonetic_match(sub, kw, pos, traits):
                            corrected = corrected[:i] + kw + corrected[i+len(kw):]
                            corrections.append((sub, kw, desc))
                            break

        return corrected, corrections

    def _is_phonetic_match(self, sub, kw, pos, traits):
        """检查 sub 是否与 kw 仅有口音层面的差异（单字拼音相近）"""
        if not HAS_PINYIN or sub == kw:
            return False
        if len(sub) != len(kw):
            return False

        try:
            sub_py = lazy_pinyin(sub, style=Style.TONE3, neutral_tone_with_five=True)
            kw_py = lazy_pinyin(kw, style=Style.TONE3, neutral_tone_with_five=True)
        except Exception:
            return False

        if len(sub_py) != len(kw_py):
            return False

        # 除目标位置外，其余字拼音必须一致
        diff_count = 0
        diff_idx = -1
        for i in range(len(sub_py)):
            if sub_py[i] != kw_py[i]:
                diff_count += 1
                diff_idx = i

        if diff_count != 1:
            return False

        # 检查差异是否在口音混淆范围内
        s_init, s_final = self._split_pinyin(sub_py[diff_idx])
        k_init, k_final = self._split_pinyin(kw_py[diff_idx])

        # 声调不同但声母韵母相同：典型的ASR声调误识别
        # 如天津话"淡"(dan4)→"单"(dan1)，声母韵母完全一致仅声调不同
        if s_init == k_init and s_final == k_final:
            return True

        if 'ping_qiao' in traits:
            if s_init in self.zh_z and k_init in self.zh_z:
                if self.zh_z[s_init] == k_init and s_final == k_final:
                    return True
        if 'qian_hou_biyin' in traits:
            for mapping in [self.en_eng, self.in_ing, self.an_ang]:
                if s_init == k_init:
                    if self._replace_final(s_final, mapping) == k_final:
                        return True
                    if self._replace_final(k_final, mapping) == s_final:
                        return True
        if 'n_l' in traits:
            if (s_init=='n' and k_init=='l') or (s_init=='l' and k_init=='n'):
                if s_final == k_final:
                    return True
        if 'h_f' in traits:
            if (s_init=='h' and k_init=='f') or (s_init=='f' and k_init=='h'):
                if s_final == k_final:
                    return True
        if 'r_l' in traits:
            if (s_init=='r' and k_init=='l') or (s_init=='l' and k_init=='r'):
                if s_final == k_final:
                    return True

        return False


class SpeakerProfile:
    """单个说话人画像"""

    def __init__(self, speaker_id, label=None):
        self.id = speaker_id
        self.label = label or speaker_id
        self.language = '普通话'
        self.accent_region = ''
        self.accent_desc = ''
        self.birthplace = ''
        self.growth_environment = ''
        self.traits = set()
        self.dialect_mix = []
        self.platform_ids = {}
        self.catchphrases = []
        self.custom_notes = ''
        self.library_loaded = False

    def to_dict(self):
        return {
            'id': self.id,
            'label': self.label,
            'language': self.language,
            'accent_region': self.accent_region,
            'accent_desc': self.accent_desc,
            'birthplace': self.birthplace,
            'growth_environment': self.growth_environment,
            'traits': list(self.traits),
            'dialect_mix': self.dialect_mix,
            'platform_ids': self.platform_ids,
            'catchphrases': self.catchphrases,
            'custom_notes': self.custom_notes,
            'library_loaded': self.library_loaded,
        }

    @classmethod
    def from_dict(cls, d):
        p = cls(d['id'], d.get('label'))
        p.language = d.get('language', '普通话')
        p.accent_region = d.get('accent_region', '')
        p.accent_desc = d.get('accent_desc', '')
        p.birthplace = d.get('birthplace', '')
        p.growth_environment = d.get('growth_environment', '')
        p.traits = set(d.get('traits', []))
        p.dialect_mix = d.get('dialect_mix', [])
        p.platform_ids = d.get('platform_ids', {})
        p.catchphrases = d.get('catchphrases', [])
        p.custom_notes = d.get('custom_notes', '')
        p.library_loaded = d.get('library_loaded', False)
        return p

    def apply_preset(self, preset_key):
        preset = DIALECT_PRESETS.get(preset_key)
        if preset:
            self.traits = set(preset['traits'])
            self.language = preset['label']

    def load_from_library(self, lib_entry):
        """从声音画像库条目填充画像 — 简化版：名字/ID/口音特点/口头禅"""
        self.label = lib_entry.get('name', lib_entry.get('platform_id', self.label))
        self.accent_region = lib_entry.get('accent_region', '')
        self.accent_desc = lib_entry.get('accent_desc', '')
        self.traits = set(lib_entry.get('accent_traits', []))
        self.platform_ids = lib_entry.get('platform_ids', {}) or {lib_entry.get('platform_id', ''): lib_entry.get('platform_id', '')}
        self.catchphrases = lib_entry.get('catchphrases', [])
        self.language = lib_entry.get('primary_language', self.language)
        self.custom_notes = lib_entry.get('notes', '')
        self.library_loaded = True

    def get_trait_summary(self):
        if not self.traits:
            return '无明显方言特征'
        return ', '.join(DIALECT_TRAITS[t]['label'] for t in self.traits if t in DIALECT_TRAITS)


class VoiceProfileLibrary:
    """声音画像库 — 预置的人物口音特征数据库。
    根据姓名或平台ID快速查找人物的口音画像。"""

    def __init__(self):
        self.entries = {}
        self._load()

    def _load(self):
        pf = PROFILE_DIR / "voice_profile_library.json"
        if pf.exists():
            try:
                with open(pf, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.entries = data.get('profiles', {})
            except Exception:
                self.entries = {}

    def save(self):
        pf = PROFILE_DIR / "voice_profile_library.json"
        with open(pf, 'w', encoding='utf-8') as f:
            json.dump({'profiles': self.entries}, f, ensure_ascii=False, indent=2)

    def lookup_by_name(self, name):
        """通过姓名查找画像（精准匹配：网名key 或 真名name 或 platform_id）"""
        if not name:
            return None
        name = name.strip()
        if name in self.entries:
            return self.entries[name]
        for entry in self.entries.values():
            if entry.get('name', '') == name:
                return entry
            if entry.get('platform_id', '') == name:
                return entry
        return None

    def lookup_by_platform_id(self, platform, pid):
        """通过平台+ID查找画像（精准匹配）"""
        if not platform or not pid:
            return None
        for entry in self.entries.values():
            pids = entry.get('platform_ids', {})
            if pids.get(platform) == pid:
                return entry
            if entry.get('platform_id', '') == pid:
                return entry
        return None

    def lookup_any(self, query):
        """综合查找：先按姓名精准匹配，再按平台ID精准匹配"""
        if not query:
            return None
        query = query.strip()
        result = self.lookup_by_name(query)
        if result:
            return result
        for platform in ('bilibili', 'douyu', 'huya', 'douyin', 'kuaishou'):
            result = self.lookup_by_platform_id(platform, query)
            if result:
                return result
        return None

    def add_entry(self, name, **fields):
        """添加或更新画像条目"""
        entry = {'name': name}
        entry.update(fields)
        self.entries[name] = entry
        self.save()
        return entry

    def remove_entry(self, name):
        if name in self.entries:
            del self.entries[name]
            self.save()
            return True
        return False

    def list_all(self):
        return list(self.entries.values())


class SpeakerProfileManager:
    """说话人画像管理器 — 集成声音画像库自动加载"""

    def __init__(self):
        self.profiles = {}
        self.engine = AccentCorrectionEngine()
        self.library = VoiceProfileLibrary()
        self._load()

    def _load(self):
        pf = PROFILE_DIR / "speaker_profiles.json"
        if pf.exists():
            try:
                with open(pf, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for k, v in data.items():
                    self.profiles[k] = SpeakerProfile.from_dict(v)
            except Exception:
                pass

    def save(self):
        pf = PROFILE_DIR / "speaker_profiles.json"
        data = {k: v.to_dict() for k, v in self.profiles.items()}
        with open(pf, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_or_create(self, speaker_id, label=None):
        if speaker_id in self.profiles:
            return self.profiles[speaker_id]
        profile = SpeakerProfile(speaker_id, label or speaker_id)
        self.profiles[speaker_id] = profile
        loaded = self._auto_load_library(profile)
        if loaded:
            print(f"[PROFILE] 画像库命中: '{profile.label}' → "
                  f"{profile.accent_region} traits={profile.get_trait_summary()} "
                  f"catchphrases={profile.catchphrases}", flush=True)
        return profile

    def _auto_load_library(self, profile):
        """自动从声音画像库加载口音特征。返回命中的画像条目或None。"""
        queries = [profile.label, profile.id]
        if profile.birthplace:
            queries.insert(0, profile.birthplace)
        for q in queries:
            if not q or not q.strip():
                continue
            entry = self.library.lookup_any(q.strip())
            if entry:
                profile.load_from_library(entry)
                self.save()
                return entry
        return None

    def update(self, speaker_id, **updates):
        profile = self.get_or_create(speaker_id)
        for k, v in updates.items():
            if k == 'traits':
                profile.traits = set(v)
            elif hasattr(profile, k):
                setattr(profile, k, v)
        self.save()
        return profile

    def apply_preset(self, speaker_id, preset_key):
        profile = self.get_or_create(speaker_id)
        profile.apply_preset(preset_key)
        self.save()
        return profile

    def get_accent_traits(self, speaker_id):
        profile = self.profiles.get(speaker_id)
        if profile:
            return profile.traits
        return set()

    def get_all_loaded_traits(self):
        """多人场景：合并所有已加载画像的口音特征"""
        all_traits = set()
        for profile in self.profiles.values():
            if profile.library_loaded or profile.traits:
                all_traits.update(profile.traits)
        return all_traits

    def accent_correct(self, speaker_id, text, known_keywords=None):
        traits = self.get_accent_traits(speaker_id)
        if not traits:
            return text, []
        return self.engine.correct_text(text, traits, known_keywords)

    def accent_correct_all(self, text, known_keywords=None):
        """多人场景：用所有已加载人物的口音特征纠正文本"""
        traits = self.get_all_loaded_traits()
        if not traits:
            return text, []
        return self.engine.correct_text(text, traits, known_keywords)

    def get_catchphrases(self, speaker_label):
        """获取某个speaker在画像库中的口头禅列表"""
        entry = self.library.lookup_any(speaker_label)
        if entry:
            return entry.get('catchphrases', [])
        return []

    def add_catchphrases(self, speaker_label, keywords):
        """向画像库中添加口头禅，自动去重。返回新增数量。"""
        entry = self.library.lookup_any(speaker_label)
        if not entry:
            return 0
        existing = set(entry.get('catchphrases', []))
        new = [kw for kw in keywords if kw and len(kw) >= 2 and kw not in existing]
        if new:
            entry['catchphrases'] = entry.get('catchphrases', []) + new
            return len(new)
        return 0

    def save_library(self):
        """持久化画像库到磁盘"""
        self.library.save()


sp_manager = SpeakerProfileManager()


# ===== 城市→方言区域映射表 =====
REGION_MAP = {
    # 华北/东北官话
    '北京': 'huabei', '天津': 'huabei', '河北': 'huabei', '石家庄': 'huabei', '唐山': 'huabei',
    '保定': 'huabei', '邯郸': 'huabei', '廊坊': 'huabei', '沧州': 'huabei', '邢台': 'huabei',
    '衡水': 'huabei', '承德': 'huabei', '张家口': 'huabei', '秦皇岛': 'huabei',
    '黑龙江': 'huabei', '哈尔滨': 'huabei', '齐齐哈尔': 'huabei', '牡丹江': 'huabei',
    '佳木斯': 'huabei', '大庆': 'huabei', '鸡西': 'huabei', '鹤岗': 'huabei', '双鸭山': 'huabei',
    '吉林': 'huabei', '长春': 'huabei', '吉林市': 'huabei', '四平': 'huabei', '辽源': 'huabei',
    '通化': 'huabei', '白山': 'huabei', '松原': 'huabei', '白城': 'huabei', '延边': 'huabei',
    '辽宁': 'huabei', '沈阳': 'huabei', '大连': 'huabei', '鞍山': 'huabei', '抚顺': 'huabei',
    '本溪': 'huabei', '丹东': 'huabei', '锦州': 'huabei', '营口': 'huabei', '阜新': 'huabei',
    '辽阳': 'huabei', '盘锦': 'huabei', '铁岭': 'huabei', '朝阳': 'huabei', '葫芦岛': 'huabei',
    '内蒙古': 'huabei', '呼和浩特': 'huabei', '包头': 'huabei', '赤峰': 'huabei',
    '东北': 'huabei', '华北': 'huabei',
    # 西北 → 近似华北
    '陕西': 'huabei', '西安': 'huabei', '甘肃': 'huabei', '兰州': 'huabei',
    '宁夏': 'huabei', '银川': 'huabei', '青海': 'huabei', '西宁': 'huabei',
    '新疆': 'huabei', '乌鲁木齐': 'huabei',
    # 山东/河南 → 近似华北（中原官话）
    '山东': 'huabei', '济南': 'huabei', '青岛': 'huabei', '烟台': 'huabei',
    '威海': 'huabei', '潍坊': 'huabei', '淄博': 'huabei', '临沂': 'huabei',
    '河南': 'huabei', '郑州': 'huabei', '洛阳': 'huabei', '开封': 'huabei',
    '南阳': 'huabei', '新乡': 'huabei', '安阳': 'huabei', '商丘': 'huabei',

    # 西南官话（川渝云贵）
    '四川': 'xinan', '成都': 'xinan', '绵阳': 'xinan', '德阳': 'xinan', '宜宾': 'xinan',
    '泸州': 'xinan', '南充': 'xinan', '达州': 'xinan', '乐山': 'xinan', '自贡': 'xinan',
    '攀枝花': 'xinan', '广元': 'xinan', '遂宁': 'xinan', '内江': 'xinan', '广安': 'xinan',
    '眉山': 'xinan', '资阳': 'xinan', '雅安': 'xinan', '巴中': 'xinan', '凉山': 'xinan',
    '重庆': 'xinan',
    '云南': 'xinan', '昆明': 'xinan', '曲靖': 'xinan', '玉溪': 'xinan', '大理': 'xinan',
    '丽江': 'xinan', '昭通': 'xinan', '红河': 'xinan', '西双版纳': 'xinan',
    '贵州': 'xinan', '贵阳': 'xinan', '遵义': 'xinan', '六盘水': 'xinan', '安顺': 'xinan',
    '毕节': 'xinan', '铜仁': 'xinan', '黔东南': 'xinan', '黔南': 'xinan',
    '湖北': 'xinan', '武汉': 'xinan', '宜昌': 'xinan', '襄阳': 'xinan', '荆州': 'xinan',
    '十堰': 'xinan', '黄冈': 'xinan', '恩施': 'xinan', '鄂州': 'xinan', '孝感': 'xinan',
    '西南': 'xinan',

    # 江淮官话（南京/安徽/苏北）
    '江苏': 'jianghuai', '南京': 'jianghuai', '扬州': 'jianghuai', '镇江': 'jianghuai',
    '泰州': 'jianghuai', '盐城': 'jianghuai', '淮安': 'jianghuai', '连云港': 'jianghuai',
    '南通': 'jianghuai', '宿迁': 'jianghuai', '徐州': 'jianghuai',
    '安徽': 'jianghuai', '合肥': 'jianghuai', '芜湖': 'jianghuai', '蚌埠': 'jianghuai',
    '淮南': 'jianghuai', '马鞍山': 'jianghuai', '安庆': 'jianghuai', '滁州': 'jianghuai',
    '阜阳': 'jianghuai', '六安': 'jianghuai', '亳州': 'jianghuai', '宣城': 'jianghuai',
    '江淮': 'jianghuai',

    # 吴语区（上海/苏南/浙江）
    '上海': 'wu',
    '苏州': 'wu', '无锡': 'wu', '常州': 'wu',
    '浙江': 'wu', '杭州': 'wu', '宁波': 'wu', '温州': 'wu', '嘉兴': 'wu',
    '湖州': 'wu', '绍兴': 'wu', '金华': 'wu', '衢州': 'wu', '舟山': 'wu',
    '台州': 'wu', '丽水': 'wu',
    '吴语': 'wu', '江南': 'wu',

    # 粤语区（广东/广西/香港）
    '广东': 'yue', '广州': 'yue', '深圳': 'yue', '珠海': 'yue', '东莞': 'yue',
    '佛山': 'yue', '中山': 'yue', '惠州': 'yue', '江门': 'yue', '湛江': 'yue',
    '茂名': 'yue', '肇庆': 'yue', '清远': 'yue', '阳江': 'yue', '韶关': 'yue',
    '河源': 'yue', '梅州': 'yue', '潮州': 'yue', '揭阳': 'yue', '汕头': 'yue',
    '汕尾': 'yue', '云浮': 'yue',
    '广西': 'yue', '南宁': 'yue', '柳州': 'yue', '桂林': 'yue', '梧州': 'yue',
    '北海': 'yue', '玉林': 'yue', '贵港': 'yue',
    '香港': 'yue', '澳门': 'yue',
    '粤语': 'yue',

    # 闽语区（福建/台湾/潮汕）
    '福建': 'min', '福州': 'min', '厦门': 'min', '泉州': 'min', '漳州': 'min',
    '莆田': 'min', '三明': 'min', '南平': 'min', '龙岩': 'min', '宁德': 'min',
    '台湾': 'min', '台北': 'min', '台中': 'min', '高雄': 'min', '台南': 'min',
    '闽语': 'min', '闽南': 'min',

    # 湘语区（湖南）
    '湖南': 'xiang', '长沙': 'xiang', '株洲': 'xiang', '湘潭': 'xiang',
    '衡阳': 'xiang', '邵阳': 'xiang', '岳阳': 'xiang', '常德': 'xiang',
    '益阳': 'xiang', '郴州': 'xiang', '永州': 'xiang', '怀化': 'xiang',
    '娄底': 'xiang', '湘西': 'xiang',
    '湘语': 'xiang',

    # 客家话（赣南/闽西/粤东/台湾）
    '赣州': 'kejia', '龙岩客家': 'kejia', '梅县': 'kejia',
    '客家': 'kejia',

    # 赣语区（江西）
    '江西': 'gan', '南昌': 'gan', '九江': 'gan', '景德镇': 'gan', '萍乡': 'gan',
    '新余': 'gan', '鹰潭': 'gan', '宜春': 'gan', '上饶': 'gan', '吉安': 'gan',
    '抚州': 'gan',
    '赣语': 'gan',

    # 晋语区（山西/陕北）
    '山西': 'jin', '太原': 'jin', '大同': 'jin', '阳泉': 'jin', '长治': 'jin',
    '晋城': 'jin', '朔州': 'jin', '忻州': 'jin', '吕梁': 'jin', '晋中': 'jin',
    '临汾': 'jin', '运城': 'jin',
    '陕北': 'jin', '榆林': 'jin', '延安': 'jin',
    '晋语': 'jin',
}


def search_speaker_accent(name='', birthplace=''):
    """
    根据姓名/出生地自动推断口音特征
    返回: (success: bool, traits: list, description: str, accent_region: str)
    """
    if not name and not birthplace:
        return False, [], '', ''

    search_text = (name + ' ' + birthplace).strip()

    matched_region = None
    matched_key = ''
    matched_len = 0

    for location, region in REGION_MAP.items():
        if location in search_text:
            if len(location) > matched_len:
                matched_region = region
                matched_key = location
                matched_len = len(location)

    if not matched_region:
        return False, [], '未找到匹配的方言区域，请手动勾选口音特征', ''

    preset = DIALECT_PRESETS.get(matched_region)
    if not preset:
        return False, [], '', ''

    traits = preset['traits']
    label = preset['label']
    trait_names = [DIALECT_TRAITS[t]['label'] for t in traits if t in DIALECT_TRAITS]

    if trait_names:
        desc = f'📍 {matched_key} → {label}，口音特征: {", ".join(trait_names)}'
    else:
        desc = f'📍 {matched_key} → {label}，无明显方言特征'

    return True, traits, desc, matched_region


# ===== 话题关键词管理器 =====
class TopicKeywordManager:
    def __init__(self):
        self.topics = {}
        self._load()

    def _load(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dict', 'topic_keywords.json')
        if not os.path.exists(path):
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
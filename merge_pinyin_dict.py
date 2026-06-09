# -*- coding: utf-8 -*-
"""
将所有词典统一转换为 拼音→正确文字 格式，合并到 general.json
运行一次即可：python merge_pinyin_dict.py
"""
import json
import re
from pathlib import Path

try:
    from pypinyin import lazy_pinyin, Style
except ImportError:
    print("[ERROR] 需要安装 pypinyin: pip install pypinyin")
    exit(1)

DICT_DIR = Path(__file__).parent / "dict"
OUTPUT = DICT_DIR / "pinyin_corrections" / "general.json"
OUTPUT_CS2 = DICT_DIR / "corrections" / "cs2.json"
OUTPUT_DATACOM = DICT_DIR / "pinyin_corrections" / "datacom.json"


def to_pinyin(text):
    """将文本转为空格分隔拼音：中文→拼音，英文→原样保留（不分拆字母）"""
    if not text:
        return ""
    text = text.strip()
    # 完全不包含中文：直接返回小写原样
    if not is_chinese(text):
        return text.lower()

    # 中英混合：按中/英边界分割，中文部分转拼音，英文部分原样保留
    segments = re.split(r'([\u4e00-\u9fff]+)', text)
    parts = []
    for seg in segments:
        if not seg:
            continue
        if is_chinese(seg):
            # 纯中文段→拼音
            for ch in seg:
                py = lazy_pinyin(ch, style=Style.NORMAL)
                parts.append(py[0] if py else ch)
        else:
            # 英文/数字段→原样保留（不拆字母）
            clean = re.sub(r'[^a-zA-Z0-9]', '', seg).lower()
            if clean:
                parts.append(clean)
    return " ".join(parts)


def is_chinese(text):
    """判断文本是否含中文"""
    return bool(re.search(r'[\u4e00-\u9fff]', text))


def is_pinyin_key(text):
    """判断是否已经是拼音格式（空格分隔的小写字母）"""
    return bool(re.fullmatch(r'[a-z0-9]+( [a-z0-9]+)*', text, re.IGNORECASE))


def load_json(path):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def main():
    all_entries = {}       # general.json → 通用拼音
    cs2_entries = {}       # cs2.json → CS2话题专用拼音
    datacom_entries = {}   # datacom.json → 网络/通信术语
    stats = {"from_pinyin_correction": 0, "from_pinyin_cs2": 0,
             "from_correction": 0, "from_entities": 0,
             "skipped_empty": 0, "skipped_self": 0, "skipped_bad": 0,
             "conflict_resolved": 0}

    # ── correction.json 来源的关键词黑名单 ──
    correction_blacklist_values = {
        "RouterID", "Type", "RIP",
    }
    # 这些 specific key→value 对的拼音语义完全对不上
    correction_blacklist_pairs = {
        ("zhao cai li", "RouterID"),
        ("rao tai di", "RouterID"),
        ("rao tai ding", "RouterID"),
        ("dao tai di", "RouterID"),
        ("low-tidy", "RouterID"),
        ("wang shui", "网络设备"),
        ("ji gong", "提供"),
        ("nu biao", "路由表"),
        ("shou hong", "手工"),
        ("sha tiao", "下一跳"),
        ("tu po", "拓扑"),
        ("zhong tu", "冲突"),
        ("feng shuang", "封装"),
        ("wang lai", "网络"),
        ("dian lu kai xiao", "链路开销"),
        ("jin tan", "静态"),
        ("po wen", "报文"),
        ("chuan chu", "传输"),
        ("rui huo", "RIP"),
        ("tai bao", "Type"),
        ("ta bu", "Type"),
        ("type guo gao xiu", "他不够高效"),
        ("type shi avid zhi", "它不是IP地址"),
        ("lu you xing qi", "路游信息"),
        ("lu you hui guan", "路由回灌"),
        ("lu you xie", "路由协"),
    }

    def add_entry(pinyin_key, correct_text, source, target=None):
        if target is None:
            target = all_entries
        if not pinyin_key or not correct_text:
            stats["skipped_empty"] += 1
            return
        pinyin_key = pinyin_key.strip().lower()
        correct_text = correct_text.strip()

        # 格式清洗：连字符→空格，去掉多余空白
        pinyin_key = re.sub(r'[-_]+', ' ', pinyin_key)
        pinyin_key = re.sub(r'\s+', ' ', pinyin_key).strip()

        # 验证：key 不能含中文/表情
        if re.search(r'[\u4e00-\u9fff]', pinyin_key):
            stats["skipped_bad"] += 1
            return
        # 验证：value 不能含表情
        if re.search(r'[\U0001F300-\U0001F9FF\u2600-\u27BF]', correct_text):
            stats["skipped_bad"] += 1
            return
        # 验证：key 不能为空或纯数字
        if not pinyin_key or not re.search(r'[a-z]', pinyin_key):
            stats["skipped_bad"] += 1
            return

        if pinyin_key == correct_text.lower():
            stats["skipped_self"] += 1
            return

        # 黑名单检查
        if correct_text in correction_blacklist_values and source == "from_correction":
            if pinyin_key in target:
                stats["skipped_bad"] += 1
                return
        if (pinyin_key, correct_text) in correction_blacklist_pairs:
            stats["skipped_bad"] += 1
            return

        if pinyin_key in target:
            existing = target[pinyin_key]
            if existing != correct_text:
                print(f"  [CONFLICT] '{pinyin_key}': '{existing}' vs '{correct_text}' → 保留 '{correct_text}'")
                stats["conflict_resolved"] += 1
            target[pinyin_key] = correct_text
        else:
            target[pinyin_key] = correct_text
            stats[source] += 1

    # ── 1. pinyin_correction.json（已是拼音→文字格式）──
    data = load_json(DICT_DIR / "pinyin_correction.json")
    for k, v in data.items():
        if k.startswith("__"):
            continue
        add_entry(k, v, "from_pinyin_correction")

    # ── 2. pinyin_corrections/cs2.json（带调拼音→文字，同时保留去调版）→ 输出到 cs2.json ──
    data = load_json(DICT_DIR / "pinyin_corrections" / "cs2.json")
    for k, v in data.items():
        if k.startswith("__"):
            continue
        # 先添加原始带调版本
        add_entry(k, v, "from_pinyin_cs2", target=cs2_entries)
        # 再去调后添加无调版本（两个key都有效）
        # 但跳过单音节条目：单音节无调key（如"hen"）会误匹配常见字（如"很"hen3）
        clean_key = re.sub(r'[1-5]', '', k).strip()
        if clean_key != k and len(clean_key.split()) >= 2:
            add_entry(clean_key, v, "from_pinyin_cs2", target=cs2_entries)

    # ── 3. correction.json（网络/通信术语 → datacom.json，不混入 general.json）──
    data = load_json(DICT_DIR / "correction.json")
    for k, v in data.items():
        if k.startswith("__"):
            continue
        if is_pinyin_key(k):
            add_entry(k, v, "from_correction", target=datacom_entries)
        else:
            pinyin_key = to_pinyin(k)
            if pinyin_key:
                add_entry(pinyin_key, v, "from_correction", target=datacom_entries)

    # ── 4. text_corrections/cs2.json 已删除，不再读取 ──


    # ── 输出 general.json（仅通用拼音）──
    sorted_items = sorted(all_entries.items(), key=lambda x: len(x[0].split()), reverse=True)
    output = {
        "__rule__": "【规则】通用拼音→正确文字。仅跨话题通用条目。领域专用条目在 dict/corrections/ 下。由 merge_pinyin_dict.py 自动生成。",
        "__total__": len(sorted_items),
    }
    for k, v in sorted_items:
        output[k] = v

    OUTPUT.parent.mkdir(exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # ── 输出 cs2.json（CS2话题专用拼音）──
    cs2_sorted = sorted(cs2_entries.items(), key=lambda x: len(x[0].split()), reverse=True)
    cs2_output = {
        "__rule__": "【规则】CS2 统一纠正词典。选手/战队/地图/武器/战术全部合一。由 merge_pinyin_dict.py 自动生成。",
        "__total__": len(cs2_sorted),
    }
    for k, v in cs2_sorted:
        cs2_output[k] = v

    with open(OUTPUT_CS2, "w", encoding="utf-8") as f:
        json.dump(cs2_output, f, ensure_ascii=False, indent=2)

    # ── 输出 datacom.json（网络/通信术语）──
    datacom_sorted = sorted(datacom_entries.items(), key=lambda x: len(x[0].split()), reverse=True)
    datacom_output = {
        "__rule__": "【规则】网络/通信领域拼音→正确文字。仅在匹配到网络话题时加载。由 merge_pinyin_dict.py 自动生成。",
        "__total__": len(datacom_sorted),
    }
    for k, v in datacom_sorted:
        datacom_output[k] = v

    with open(OUTPUT_DATACOM, "w", encoding="utf-8") as f:
        json.dump(datacom_output, f, ensure_ascii=False, indent=2)

    print(f"\n===== 合并完成 =====")
    print(f"  general.json: {len(sorted_items)} 条 (通用拼音)")
    print(f"  cs2.json:     {len(cs2_sorted)} 条 (CS2话题专用)")
    print(f"  datacom.json: {len(datacom_sorted)} 条 (网络/通信术语)")
    print(f"  跳过(空/自映射/脏数据): {stats['skipped_empty']}/{stats['skipped_self']}/{stats['skipped_bad']}")
    if stats['conflict_resolved']:
        print(f"  冲突解决: {stats['conflict_resolved']}")
    print(f"  输出: {OUTPUT}")


if __name__ == "__main__":
    main()

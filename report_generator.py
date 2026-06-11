# -*- coding: utf-8 -*-
"""
报告生成模块 — 生成 Markdown 报告和结构化 JSON 日志
"""

import json
from datetime import datetime

from text_utils import log_fmt_time
from pinyin_utils import text_similarity


def _build_segment_data(segments, display_names, video_offset):
    """构建统一的 segment 数据，供报告和日志复用"""
    if display_names is None:
        display_names = {}

    # 按音频时间排序，确保报告输出按时间顺序（防御异步并发完成导致的乱序）
    sorted_segments = sorted(segments, key=lambda s: s.get('time', 0))

    seg_data = []
    for i, seg in enumerate(sorted_segments):
        sp = seg.get('speaker', 'Speaker0')
        seg_time = seg.get('time', 0)
        abs_t = seg_time + video_offset

        seg_data.append({
            'index': i,
            'speaker': sp,
            'speaker_name': display_names.get(sp, sp),
            'time': seg_time,
            'abs_time': abs_t,
            'duration': seg.get('duration', 0),
            'text': seg['text'],
            'vad_forced': seg.get('vad', {}).get('forced', False),
            'kw_corrected': seg.get('kw_corrected', False),
        })

    return seg_data, display_names


def generate_comprehensive_report(segments, speaker_profiles, keyword_history,
                                   total_audio_seconds, asr_model_name,
                                   page_type, video_offset,
                                   display_names=None,
                                   page_creator=None,
                                   session_start_time=None):
    """生成两板块结构化报告：对话正文 + 手动关键词"""
    lines = []
    seg_data, display_names = _build_segment_data(segments, display_names, video_offset)

    timestamp = (session_start_time.strftime('%Y-%m-%d %H:%M:%S')
                 if session_start_time
                 else datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    # ═══ 标题 ═══
    title = "实时语音识别报告"
    lines.append(f"# {title}")
    lines.append(f"")
    lines.append(f"**生成时间**: {timestamp}")
    lines.append(f"**类型**: {'直播' if page_type == 'live' else '视频'}")
    if page_creator:
        lines.append(f"**主讲人**: {page_creator}")
    lines.append(f"**录音时长**: {total_audio_seconds:.0f} 秒")
    lines.append(f"**识别句数**: {len(segments)}")
    if speaker_profiles:
        speaker_names = []
        for sp in speaker_profiles:
            label = sp.get('label', '?')
            name = (display_names or {}).get(label) or sp.get('alias') or label
            speaker_names.append(name)
        lines.append(f"**说话人**: {', '.join(speaker_names)}")
    if page_type == 'live':
        lines.append(f"**录制起点**: {timestamp}")
    lines.append(f"")
    lines.append("---")
    lines.append("")

    # ═══ 板块一：对话正文 ═══
    lines.append("## 一、对话正文")
    lines.append("")

    # 和网页/插件一致：每条一行，格式为 "时间 | 说话人 | 文本"
    lines.append("| 时间 | 说话人 | 内容 |")
    lines.append("|------|--------|------|")
    for sd in seg_data:
        name = sd['speaker_name']
        t = sd['time']
        if page_type == 'live':
            h, m, s = int(t // 3600), int((t % 3600) // 60), int(t % 60)
            time_str = f"{h:02d}:{m:02d}:{s:02d}"
        else:
            m, s = int(t // 60), int(t % 60)
            time_str = f"T0+{m:02d}:{s:02d}"
        text = sd['text'].replace('|', '\\|')
        lines.append(f"| `{time_str}` | **{name}** | {text} |")

    lines.append("")
    lines.append("---")
    lines.append("")

    # ═══ 板块二：手动添加关键词 ═══
    lines.append("## 二、手动添加关键词")
    lines.append("")
    if keyword_history:
        # 去重，保留首次添加时间
        seen_kw = {}
        for kw in keyword_history:
            word = kw.get('keyword', '')
            if word and word not in seen_kw:
                seen_kw[word] = kw.get('time', '')
        for word, t in seen_kw.items():
            lines.append(f"- `[{t}]` {word}")
    else:
        lines.append("*(无手动关键词)*")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"*报告由在线实时语音识别系统于 {timestamp} 自动生成*")

    return '\n'.join(lines)


def generate_structured_log(segments, speaker_profiles, keyword_history,
                             total_audio_seconds,
                             asr_model_name,
                             page_type, video_offset,
                             display_names=None,
                             page_creator=None):
    """生成结构化 JSON 日志，适合发给 AI 进行纠错分析"""
    seg_data, display_names = _build_segment_data(segments, display_names, video_offset)

    # 构建 speaker 名称映射（优先 display_names，其次 profile alias）
    speaker_names = {}
    for sp in speaker_profiles:
        label = sp.get('label', '')
        if label:
            speaker_names[label] = (display_names or {}).get(label) or sp.get('alias') or label

    log_segments = []
    for sd in seg_data:
        log_segments.append({
            'seq': sd['index'],
            'time': round(sd['abs_time'], 3),
            'time_str': log_fmt_time(sd['abs_time']),
            'asr_time': round(sd['time'], 3),
            'duration': round(sd['duration'], 3),
            'speaker': sd['speaker'],
            'speaker_name': sd['speaker_name'],
            'text': sd['text'],
            'vad_forced': sd['vad_forced'],
            'kw_corrected': sd['kw_corrected'],
        })

    # 关键词去重
    seen_kw = set()
    keywords_deduped = []
    for kw in keyword_history:
        word = kw.get('keyword', '')
        if word and word not in seen_kw:
            seen_kw.add(word)
            keywords_deduped.append({
                'keyword': word,
                'time': kw.get('time', ''),
                'category': kw.get('category', 'other'),
            })

    return json.dumps(dict(
        generated_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        title='实时语音识别日志',
        page_type=page_type,
        page_type_label='直播' if page_type == 'live' else '视频',
        video_offset_seconds=round(video_offset, 1),
        page_creator=page_creator or '',
        model=asr_model_name,
        duration_seconds=round(total_audio_seconds, 1),
        total_segments=len(segments),
        speakers=speaker_names,
        keywords_added=keywords_deduped,
        segments=log_segments,
    ), ensure_ascii=False, indent=2)


def merge_segments(segments):
    """合并相邻同 speaker 且间隔极短的片段（VAD 误切修复）"""
    if len(segments) < 2:
        return
    # 先按时间排序，确保相邻比较基于真实时序
    segments.sort(key=lambda s: s.get('time', 0))
    merged = []
    for seg in segments:
        if not merged:
            merged.append(dict(seg))
            continue
        prev = merged[-1]
        if prev['speaker'] == seg['speaker']:
            seg_time = seg.get('time', 0)
            prev_time = prev.get('time', 0)
            prev_dur = prev.get('duration', 0)
            gap = seg_time - (prev_time + prev_dur)
            if gap < 1.0:
                sim = text_similarity(prev['text'], seg['text'])
                if sim > 0.5:
                    prev['text'] = seg['text'] if len(seg['text']) > len(prev['text']) else prev['text']
                else:
                    prev['text'] = prev['text'].rstrip() + ' ' + seg['text']
                prev['duration'] = seg_time + seg.get('duration', 0) - prev_time
                prev['corrections'] = prev.get('corrections', []) + seg.get('corrections', [])
                prev['kw_corrected'] = prev.get('kw_corrected', False) or seg.get('kw_corrected', False)
                continue
        merged.append(dict(seg))
    segments.clear()
    segments.extend(merged)


def merge_short_trailing(segments):
    """合并被VAD强行切分的短片段：
    - VAD强制切分标记（当前段或前一段） + 同一说话人 + 间隔<1s → 合并
    - 当前段≤12字 + 同一说话人 + 间隔<1s + 单侧有句末标点 → 合并
    - 保留独立时间戳，只合并确认为误切的片段
    """
    if len(segments) < 2:
        return
    segments.sort(key=lambda s: s.get('time', 0))
    PUNCT_END = set('。？！!?')
    MAX_SHORT_LEN = 12

    merged = []
    for seg in segments:
        if not merged:
            merged.append(dict(seg))
            continue
        prev = merged[-1]
        text = seg.get('text', '').strip()
        prev_text = prev.get('text', '').strip()

        if not text or not prev_text:
            merged.append(dict(seg))
            continue

        # 检查时间间隔
        seg_time = seg.get('time', 0)
        prev_time = prev.get('time', 0)
        prev_dur = prev.get('duration', 0)
        gap = seg_time - (prev_time + prev_dur)
        if gap >= 1.0:
            merged.append(dict(seg))
            continue

        # 条件0：间隔≈0（VAD硬切分，两段连续语音被强制拆开）
        if prev.get('speaker') == seg.get('speaker') and gap < 0.15:
            prev['text'] = prev_text.rstrip() + ' ' + text.lstrip()
            prev['duration'] = seg_time + seg.get('duration', 0) - prev_time
            prev['corrections'] = prev.get('corrections', []) + seg.get('corrections', [])
            prev['kw_corrected'] = prev.get('kw_corrected', False) or seg.get('kw_corrected', False)
            continue

        # 条件1：VAD强制切分标记 + 同一说话人 → 无论长度和标点都合并
        # 注意：VAD forced标记在前一段（强制截断的段），当前段是其剩余部分
        cur_forced = seg.get('vad', {}).get('forced', False) or False
        prev_forced = prev.get('vad', {}).get('forced', False) or False
        if prev.get('speaker') == seg.get('speaker') and (cur_forced or prev_forced):
            prev['text'] = prev_text.rstrip() + ' ' + text.lstrip()
            prev['duration'] = seg_time + seg.get('duration', 0) - prev_time
            prev['corrections'] = prev.get('corrections', []) + seg.get('corrections', [])
            prev['kw_corrected'] = prev.get('kw_corrected', False) or seg.get('kw_corrected', False)
            continue

        # 条件2：当前段短 + 单侧有句末标点（标点不对称说明是误切）
        if prev.get('speaker') == seg.get('speaker') and len(text) <= MAX_SHORT_LEN:
            text_end_has = text[-1] in PUNCT_END
            prev_end_has = prev_text[-1] in PUNCT_END
            if text_end_has != prev_end_has:
                prev['text'] = prev_text.rstrip() + ' ' + text.lstrip()
                prev['duration'] = seg_time + seg.get('duration', 0) - prev_time
                prev['corrections'] = prev.get('corrections', []) + seg.get('corrections', [])
                prev['kw_corrected'] = prev.get('kw_corrected', False) or seg.get('kw_corrected', False)
                continue

        merged.append(dict(seg))

    segments.clear()
    segments.extend(merged)


def merge_semantic_continuation(segments, max_move_chars=10, max_gap_sec=3.0):
    """合并被VAD误切的一句话：当第二段开头有 ≤max_move_chars 字的内容
    与第一段结尾语义相通时（无论第一段结尾是逗号还是句号），将第二段开头这段
    "没头没尾"的文本拼接到第一段结尾，实现完整语义的合并。

    判断条件（全部满足才合并）：
    1. 同一说话人
    2. 间隔 < max_gap_sec
    3. 第二段开头 ≤ max_move_chars 字不含句末标点（。！？!?）
    4. 移动后第二段仍有剩余内容（不吞掉整个第二段）
    """
    if len(segments) < 2:
        return

    segments.sort(key=lambda s: s.get('time', 0))
    PUNCT_END = set('。！？!?')
    PUNCT_PAUSE = set('，,、；;：:')

    merged = []
    for seg in segments:
        if not merged:
            merged.append(dict(seg))
            continue

        prev = merged[-1]
        prev_text = prev.get('text', '').strip()
        cur_text = seg.get('text', '').strip()

        if not prev_text or not cur_text:
            merged.append(dict(seg))
            continue

        # 同一说话人
        if prev.get('speaker') != seg.get('speaker'):
            merged.append(dict(seg))
            continue

        # 间隔检查
        seg_time = seg.get('time', 0)
        prev_time = prev.get('time', 0)
        prev_dur = prev.get('duration', 0)
        gap = seg_time - (prev_time + prev_dur)
        if gap >= max_gap_sec:
            merged.append(dict(seg))
            continue

        # 第二段开头 ≤ max_move_chars 字
        if len(cur_text) <= max_move_chars:
            # 整个第二段都短，直接拼到第一段后面
            prev['text'] = prev_text.rstrip() + ' ' + cur_text.lstrip()
            prev['duration'] = seg_time + seg.get('duration', 0) - prev_time
            prev['corrections'] = prev.get('corrections', []) + seg.get('corrections', [])
            prev['kw_corrected'] = prev.get('kw_corrected', False) or seg.get('kw_corrected', False)
            continue

        # 极短片段（≤3字）即使带句号也可能是语义连续（如"安危。"、"知道吗。"）
        # 判断：片段≤3字 + 有句末标点 + 前一间隔<0.5s → 直接合并
        if len(cur_text) <= 3 and cur_text[-1] in PUNCT_END and gap < 0.5:
            prev['text'] = prev_text.rstrip() + ' ' + cur_text.lstrip()
            prev['duration'] = seg_time + seg.get('duration', 0) - prev_time
            prev['corrections'] = prev.get('corrections', []) + seg.get('corrections', [])
            prev['kw_corrected'] = prev.get('kw_corrected', False) or seg.get('kw_corrected', False)
            continue

        # 取第二段开头 ≤ max_move_chars
        move_candidate = cur_text[:max_move_chars]

        # 如果移动部分末尾有句末标点 → 说明是完整短句的开头，不合并
        if any(ch in PUNCT_END for ch in move_candidate):
            merged.append(dict(seg))
            continue

        # 在 move_candidate 中找到最后一个停顿标点处截断
        cut_idx = len(move_candidate)
        for i in range(len(move_candidate) - 1, 0, -1):
            if move_candidate[i] in PUNCT_PAUSE:
                cut_idx = i + 1
                break

        move_text = cur_text[:cut_idx].strip()
        if not move_text:
            merged.append(dict(seg))
            continue

        # 移动后第二段仍有内容
        remaining = cur_text[cut_idx:].strip()
        if not remaining:
            merged.append(dict(seg))
            continue

        # 执行合并：移动部分拼接到第一段结尾
        prev['text'] = prev_text.rstrip() + ' ' + move_text
        prev['duration'] = seg_time - prev_time + (cut_idx / max(len(cur_text), 1)) * seg.get('duration', 0)
        prev['corrections'] = prev.get('corrections', []) + seg.get('corrections', [])
        prev['kw_corrected'] = prev.get('kw_corrected', False) or seg.get('kw_corrected', False)

        # 第二段保留剩余部分
        new_seg = dict(seg)
        new_seg['text'] = remaining
        merged.append(new_seg)

    segments.clear()
    segments.extend(merged)

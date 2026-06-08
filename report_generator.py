# -*- coding: utf-8 -*-
"""
报告生成模块 — 生成 Markdown 报告和结构化 JSON 日志
"""

import json
from datetime import datetime

from text_utils import fmt_time, log_fmt_time, text_similarity


def _build_segment_data(segments, display_names, video_offset):
    """构建统一的 segment 数据，供报告和日志复用"""
    if display_names is None:
        display_names = {}

    seg_data = []
    for i, seg in enumerate(segments):
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
                                   correction_records, correction_log,
                                   total_audio_seconds, asr_model_name,
                                   loaded_topics, page_type, video_offset,
                                   session_active_speakers,
                                   display_names=None,
                                   min_speech_duration=0.5,
                                   page_creator=None):
    """生成三板块结构化报告：对话正文 + 手动关键词 + 纠正明细"""
    lines = []

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # ═══ 标题 ═══
    title = "实时语音识别报告"
    if loaded_topics:
        topic_names = ', '.join(sorted(loaded_topics))
        title += f" [{topic_names}]"
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

    seg_data, _ = _build_segment_data(segments, display_names, video_offset)

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

    # ═══ 板块三：纠正明细 ═══
    lines.append("## 三、纠正明细")
    lines.append("")
    if correction_records:
        kw_records = [r for r in correction_records if len(r) == 2]
        if kw_records:
            lines.append("| # | 原始输出 | 纠正为 |")
            lines.append("|---|----------|--------|")
            seen = set()
            idx = 0
            for orig, kw in kw_records:
                pk = (orig, kw)
                if pk in seen:
                    continue
                seen.add(pk)
                idx += 1
                lines.append(f"| {idx} | `{orig}` | **{kw}** |")
            lines.append("")
            lines.append(f"*共 {len(kw_records)} 处纠正，{len(seen)} 个不同词对*")
        else:
            lines.append("*(本次未触发任何纠正)*")
    else:
        lines.append("*(本次未触发任何纠正)*")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"*报告由在线实时语音识别系统于 {timestamp} 自动生成*")

    return '\n'.join(lines)


def generate_structured_log(segments, speaker_profiles, keyword_history,
                             correction_records, total_audio_seconds,
                             asr_model_name, loaded_topics,
                             page_type, video_offset,
                             session_active_speakers,
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

    kw_records = [r for r in correction_records if len(r) == 2]

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
        topics=sorted(list(loaded_topics)),
        model=asr_model_name,
        duration_seconds=round(total_audio_seconds, 1),
        total_segments=len(segments),
        speakers=speaker_names,
        keywords_added=keywords_deduped,
        keyword_corrections=[dict(original=r[0], corrected=r[1]) for r in kw_records],
        segments=log_segments,
    ), ensure_ascii=False, indent=2)


def merge_segments(segments):
    """合并相邻同 speaker 且间隔极短的片段（VAD 误切修复）"""
    if len(segments) < 2:
        return
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
                continue
        merged.append(dict(seg))
    segments.clear()
    segments.extend(merged)

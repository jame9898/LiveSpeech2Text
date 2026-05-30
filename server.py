# -*- coding: utf-8 -*-
"""
在线实时语音识别系统 - WebSocket Server
VAD断句 + OCR关键词纠错 + 说话人分离 (CAM++)
"""

STATUS_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ASR 实时识别</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: "Segoe UI", "Microsoft YaHei", sans-serif; background: #f6f8fa; color: #1f2328; padding: 24px; max-width: 1100px; }
h1 { font-size: 20px; margin-bottom: 6px; }
.sub { color: #656d76; font-size: 12px; margin-bottom: 12px; }
.ctrl-bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 14px; }
.status-wrap { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; }
.status-badge { display: inline-block; padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: bold; }
.status-badge.online { background: #dafbe1; color: #1a7f37; }
.status-badge.offline { background: #ffebe9; color: #cf222e; }
.status-badge.connecting { background: #fff8c5; color: #9a6700; }
.status-badge.recording { background: #ffebe9; color: #cf222e; animation: pulse 1.5s infinite; }
.status-badge.remote-recording { background: #fff8c5; color: #9a6700; }
.status-badge.ready { background: #dafbe1; color: #1a7f37; }
.status-badge.model { background: #f3f4f6; color: #656d76; padding: 3px 10px; font-weight: normal; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.6} }
.btn { border: 1px solid #d0d7de; border-radius: 6px; padding: 8px 16px; background: #f6f8fa; color: #1f2328; font-size: 13px; font-weight: 500; cursor: pointer; transition: all .15s; white-space: nowrap; }
.btn:hover:not(:disabled) { border-color: #0969da; color: #0969da; }
.btn:disabled { opacity: .4; cursor: not-allowed; }
.btn.primary { background: #1a7f37; border-color: #1a7f37; color: #fff; font-weight: 600; }
.btn.primary:hover:not(:disabled) { background: #14682c; border-color: #14682c; }
.btn.danger { background: #cf222e; border-color: #cf222e; color: #fff; font-weight: 600; }
.btn.danger:hover:not(:disabled) { background: #b51d28; border-color: #b51d28; }
.btn.accent { background: #0969da; border-color: #0969da; color: #fff; }
.btn.accent:hover:not(:disabled) { background: #0756af; border-color: #0756af; }
.kw-line { display: flex; gap: 6px; align-items: center; margin-bottom: 10px; }
.kw-line select { border: 1px solid #d0d7de; border-radius: 5px; padding: 5px 8px; font-size: 12px; background: #fff; color: #1f2328; outline: none; }
.kw-line input { flex: 1; border: 1px solid #d0d7de; border-radius: 5px; padding: 5px 10px; font-size: 12px; background: #fff; color: #1f2328; outline: none; transition: border-color .15s; }
.kw-line input:focus { border-color: #0969da; }
.kw-box { min-height: 22px; font-size: 11px; line-height: 1.8; display: flex; flex-wrap: wrap; gap: 3px; margin-bottom: 10px; }
.kw-tag { display: inline-block; padding: 1px 7px; border-radius: 3px; background: #ddf4ff; color: #0969da; font-size: 11px; border: 1px solid rgba(9,105,218,.15); }
.stats { display: flex; gap: 18px; font-size: 12px; color: #656d76; margin-bottom: 8px; }
#transcripts { background: #fff; border: 1px solid #d0d7de; border-radius: 8px; padding: 14px; min-height: 280px; max-height: 65vh; overflow-y: auto; font-size: 14px; line-height: 1.9; }
.item { padding: 7px 0; border-bottom: 1px solid #f0f0f0; animation: fadeIn 0.3s; }
.item:last-child { border-bottom: none; }
.ts { color: #656d76; font-size: 11px; margin-right: 8px; }
.speaker { color: #8250df; font-weight: bold; }
.corr-old { color: #cf222e; text-decoration: line-through; }
.corr-new { color: #1a7f37; font-weight: bold; }
.kw-mark { color: #0969da; font-weight: bold; }
.highlight { background: #fff8c5; padding: 1px 4px; border-radius: 3px; }
.gap-warn { color: #cf222e; font-size: 10px; font-weight: 700; margin-right: 4px; }
.kw-fixed { color: #9a6700; font-size: 10px; font-weight: 700; margin-right: 3px; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
.overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,.35); z-index: 9999; display: flex; align-items: center; justify-content: center; }
.overlay-box { background: #fff; border-radius: 12px; padding: 28px 32px; max-width: 480px; width: 92%; box-shadow: 0 8px 32px rgba(0,0,0,.2); }
.overlay-box h3 { font-size: 17px; margin-bottom: 16px; color: #1f2328; }
.overlay-box .field { margin-bottom: 12px; text-align: left; }
.overlay-box .field label { display: block; font-size: 12px; color: #656d76; margin-bottom: 4px; font-weight: 500; }
.overlay-box .field input, .overlay-box .field select { width: 100%; border: 1px solid #d0d7de; border-radius: 6px; padding: 8px 12px; font-size: 13px; background: #fff; color: #1f2328; outline: none; transition: border-color .15s; }
.overlay-box .field input:focus, .overlay-box .field select:focus { border-color: #0969da; }
.overlay-box .field .radios { display: flex; gap: 14px; padding: 6px 0; }
.overlay-box .field .radios label { display: inline-flex; align-items: center; gap: 5px; font-size: 13px; color: #1f2328; cursor: pointer; margin: 0; }
.overlay-box .hint { font-size: 11px; color: #8b949e; margin-bottom: 16px; padding: 8px 12px; background: #f6f8fa; border-radius: 6px; line-height: 1.5; }
.overlay-box .btns { display: flex; gap: 8px; justify-content: flex-end; }
.overlay-box .btns button { padding: 10px 24px; }
</style>
</head>
<body>
<h1>ASR 实时语音识别</h1>
<p class="sub">WebSocket ws://{host}:{port} &mdash; 无需插件，独立控制</p>

<div class="status-wrap">
    <span id="connStatus" class="status-badge offline">未连接</span>
    <span id="recStatus" class="status-badge ready">准备就绪</span>
    <span id="modelInfo" class="status-badge model" style="display:none"></span>
</div>

<div class="ctrl-bar">
    <button id="btnStart" class="btn primary">▶ 开始</button>
    <button id="btnStop" class="btn danger" disabled>⏹ 停止</button>
    <button id="btnClear" class="btn">🗑 清除</button>
    <button id="btnReport" class="btn">📄 报告</button>
    <button id="btnSave" class="btn">💾 保存</button>
    <button id="btnLog" class="btn">📋 日志</button>
</div>

<div class="kw-line">
    <select id="kwCat">
        <option value="speaker">主讲人</option>
        <option value="topic">话题</option>
        <option value="other">关键词</option>
    </select>
    <input id="kwInput" placeholder="输入词或短语，回车添加...">
    <button id="btnAddKw" class="btn accent">+ 添加</button>
</div>

<div class="kw-box" id="keywordsBox"></div>

<div class="stats">
    时长: <b id="statDur">0.0</b>秒 &nbsp;|&nbsp; 句数: <b id="statCnt">0</b>条 &nbsp;|&nbsp; 字数: <b id="statChar">0</b>字
</div>

<div id="transcripts"><em style="color:#656d76">等待识别结果...</em></div>

<div id="videoPrompt" class="overlay" style="display:none">
    <div class="overlay-box">
        <h3>📺 录制设置</h3>
        <div class="field">
            <label>页面类型</label>
            <div class="radios">
                <label><input type="radio" name="pageType" value="video" checked> 短视频</label>
                <label><input type="radio" name="pageType" value="live"> 直播</label>
            </div>
        </div>
        <div class="field" id="urlField">
            <label>视频页面地址（粘贴后自动新窗口打开，从头播放）</label>
            <input id="videoUrl" placeholder="https://www.bilibili.com/video/...">
        </div>
        <div class="field">
            <label>创作者 / 主播名称（可选，用于说话人识别）</label>
            <input id="creatorName" placeholder="如：张三">
        </div>
        <div class="field" style="display:none" id="platformDetected">
            <label>检测到平台</label>
            <input id="platformName" readonly style="background:#f6f8fa;color:#656d76">
        </div>
        <div class="hint" id="setupHint">💡 短视频：粘贴地址后自动在新窗口从头播放，确保完整采集</div>
        <div class="btns">
            <button id="btnSetupCancel" class="btn">取消</button>
            <button id="btnSetupConfirm" class="btn primary">✅ 开始录制</button>
        </div>
    </div>
</div>

<script>
(function() {
var CONN = document.getElementById('connStatus');
var REC = document.getElementById('recStatus');
var MODEL = document.getElementById('modelInfo');
var BOX = document.getElementById('transcripts');
var KWBOX = document.getElementById('keywordsBox');
var BTN_START = document.getElementById('btnStart');
var BTN_STOP = document.getElementById('btnStop');
var STAT_DUR = document.getElementById('statDur');
var STAT_CNT = document.getElementById('statCnt');
var STAT_CHAR = document.getElementById('statChar');
var PROMPT = document.getElementById('videoPrompt');

var ws = null;
var isRecording = false;
var audioCtx = null;
var mediaStream = null;
var reconnectTimer = null;
var reconnectAttempts = 0;
var segCount = 0;
var firstMsg = true;
var keywords = [];
var keywordStore = {};

function setConn(cls, text) {
    CONN.className = 'status-badge ' + cls;
    CONN.textContent = text;
}

function setRec(cls, text) {
    REC.className = 'status-badge ' + cls;
    REC.textContent = text;
}

function connect() {
    setConn('connecting', '连接中...');
    try {
        ws = new WebSocket('ws://' + location.host);
        ws.binaryType = 'arraybuffer';
        ws.onopen = function() {
            setConn('online', '已连接');
            reconnectAttempts = 0;
            if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
        };
        ws.onclose = function(e) {
            setConn('offline', '断开(' + (e.code||'?') + ')，5秒后重连');
            ws = null;
            if (isRecording) { cleanupAudio(); isRecording = false; updateBtns(); }
            if (!reconnectTimer) {
                var d = Math.min(2000 * Math.pow(1.5, reconnectAttempts), 30000);
                reconnectAttempts++;
                reconnectTimer = setTimeout(connect, d);
            }
        };
        ws.onerror = function() {
            setConn('offline', '连接失败');
            if (ws) { ws.close(); ws = null; }
        };
        ws.onmessage = function(e) {
            try { handleMsg(JSON.parse(e.data)); } catch(err) {}
        };
    } catch(err) {
        setConn('offline', '连接失败');
        var d = Math.min(2000 * Math.pow(1.5, reconnectAttempts), 30000);
        reconnectAttempts++;
        if (!reconnectTimer) reconnectTimer = setTimeout(connect, d);
    }
}

function send(d) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(d)); }

function handleMsg(d) {
    switch (d.type) {
        case 'welcome':
            MODEL.style.display = '';
            MODEL.textContent = '模型: ' + (d.model || '?');
            break;
        case 'status':
            if (d.status === 'recording') setRec('recording', '识别中...');
            else if (d.status === 'stopped') setRec('ready', '已停止');
            else if (d.status === 'cleared') clearUI();
            break;
        case 'recording_state':
            if (d.recording) {
                isRecording = true;
                updateBtns();
                setRec('remote-recording', '识别中...（其他端）');
            } else {
                if (!isRecording || (isRecording && BTN_START.disabled)) {
                    isRecording = false;
                    updateBtns();
                    setRec('ready', '准备就绪');
                }
            }
            break;
        case 'transcription':
            addSeg(d); updateStats(d);
            if (d.keywords) updateKeywords(d.keywords);
            break;
        case 'keywords_updated':
            if (d.keyword_store) keywordStore = d.keyword_store;
            if (d.keywords) updateKeywords(d.keywords);
            break;
        case 'report': showReport(d.content); break;
        case 'save_report': download(d.content, d.filename||'asr_report.md', 'text/markdown;charset=utf-8'); break;
        case 'save_log': download(d.content, d.filename||'asr_log.json', 'application/json;charset=utf-8'); break;
        case 'error': alert('错误: ' + d.message); break;
    }
}

function eHtml(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

function addSeg(d) {
    if (firstMsg) { BOX.innerHTML = ''; firstMsg = false; }
    segCount++;
    if (BOX.children.length >= 200) BOX.removeChild(BOX.firstChild);

    var div = document.createElement('div');
    div.className = 'item';

    if (d.gap_audio > 1.5 && segCount > 1) {
        div.innerHTML += '<span class="gap-warn">⚠漏' + d.gap_audio.toFixed(1) + 's</span>';
    }
    if (d.ocr_corrected) {
        div.innerHTML += '<span class="kw-fixed">[KW]</span>';
    }

    var segTime = d.seg_time !== undefined ? d.seg_time : d.duration;
    if (segTime !== undefined && segTime !== null) {
        var m = Math.floor(segTime / 60), s = (segTime % 60).toFixed(1);
        div.innerHTML += '<span class="ts">T+' + (m>0?m+':'+(s<10?'0':'')+s:s+'s') + '</span>';
    }
    if (d.speaker) {
        div.innerHTML += '<span class="speaker">[' + eHtml(d.speaker) + ']</span> ';
    }

    if (d.corrections && d.corrections.length > 0) {
        var txt = eHtml(d.original_text || d.text);
        for (var ci = 0; ci < d.corrections.length; ci++) {
            var c = d.corrections[ci], old = c[0], kw = c[1];
            var re = new RegExp(eHtml(old).replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&'), 'g');
            txt = txt.replace(re, '<span class="corr-new">' + eHtml(kw) + '</span>');
        }
        div.innerHTML += txt;
    } else if (d.text) {
        var t = d.text;
        t = t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
        t = t.replace(/<kw>(.*?)<\\/kw>/g, '<span class="kw-mark">$1</span>');
        t = t.replace(/<mark>(.*?)<\\/mark>/g, '<span class="highlight">$1</span>');
        t = t.replace(/<del>(.*?)<\\/del>/g, '<span class="corr-old">$1</span>');
        t = t.replace(/<ins>(.*?)<\\/ins>/g, '<span class="corr-new">$1</span>');
        div.innerHTML += t;
    }
    BOX.appendChild(div);
    BOX.scrollTop = BOX.scrollHeight;
}

function updateStats(d) {
    if (d.duration !== undefined) STAT_DUR.textContent = d.duration.toFixed(1);
    STAT_CNT.textContent = segCount + '条';
    STAT_CHAR.textContent = (d.full_text ? d.full_text.length : 0) + '字';
}

function updateKeywords(kws) {
    if (!kws) return;
    keywords = kws.slice();
    var html = '';
    if (keywordStore && Object.keys(keywordStore).length > 0) {
        var shown = {};
        for (var ci = 0; ci < 3; ci++) {
            var cat = ['speaker','topic','other'][ci];
            var words = keywordStore[cat];
            if (!words || !words.length) continue;
            for (var wi = 0; wi < words.length; wi++) {
                var w = words[wi];
                if (shown[w]) continue;
                shown[w] = true;
                html += '<span class="kw-tag">' + eHtml(w) + '</span>';
            }
        }
    } else {
        for (var i = Math.max(0, keywords.length - 20); i < keywords.length; i++) {
            html += '<span class="kw-tag">' + eHtml(keywords[i]) + '</span>';
        }
    }
    KWBOX.innerHTML = html || '<span style="color:#8b949e;font-size:11px">暂无关键词</span>';
}

function clearUI() {
    segCount = 0; firstMsg = true; keywords = []; keywordStore = {};
    BOX.innerHTML = '<em style="color:#656d76">等待识别结果...</em>';
    STAT_DUR.textContent = '0.0'; STAT_CNT.textContent = '0条'; STAT_CHAR.textContent = '0字';
    KWBOX.innerHTML = '';
    setRec('ready', '准备就绪');
}

function showReport(content) {
    BOX.innerHTML = '<div style="color:#1f2328;padding:4px 0;line-height:1.8;white-space:pre-wrap;font-size:13px">' +
        content.replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</div>';
}

function download(content, filename, mime) {
    var blob = new Blob([content], {type: mime});
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function updateBtns() {
    BTN_START.disabled = isRecording;
    BTN_STOP.disabled = !isRecording;
}

function detectPlatform(url) {
    if (/bilibili\.com/i.test(url)) return 'bilibili';
    if (/douyin\.com/i.test(url)) return 'douyin';
    if (/douyu\.com/i.test(url)) return 'douyu';
    if (/huya\.com/i.test(url)) return 'huya';
    if (/youtube\.com/i.test(url)) return 'youtube';
    if (/kuaishou\.com/i.test(url)) return 'kuaishou';
    if (/cc\.163\.com/i.test(url)) return 'net163';
    if (/egame\.qq\.com/i.test(url)) return 'egame';
    return 'web';
}

var videoUrlInput = document.getElementById('videoUrl');
videoUrlInput.addEventListener('input', function() {
    var url = videoUrlInput.value.trim();
    if (url && /^https?:\/\//.test(url)) {
        var pf = detectPlatform(url);
        var pfEl = document.getElementById('platformDetected');
        pfEl.style.display = '';
        document.getElementById('platformName').value = pf;
    } else {
        document.getElementById('platformDetected').style.display = 'none';
    }
});

var pageTypeRadios = document.querySelectorAll('input[name="pageType"]');
var urlField = document.getElementById('urlField');
var setupHint = document.getElementById('setupHint');
for (var ri = 0; ri < pageTypeRadios.length; ri++) {
    pageTypeRadios[ri].addEventListener('change', function() {
        if (this.value === 'live') {
            urlField.style.display = 'none';
            setupHint.textContent = '📡 直播模式：直接录制，无需重置视频进度';
        } else {
            urlField.style.display = '';
            setupHint.textContent = '💡 短视频：粘贴地址后自动在新窗口从头播放，确保完整采集';
        }
    });
}

async function doStartRec() {
    if (!ws || ws.readyState !== 1) { alert('服务未连接！请确保服务已启动'); return; }
    var url = document.getElementById('videoUrl').value.trim();
    var creator = document.getElementById('creatorName').value.trim();
    var pageType = document.querySelector('input[name="pageType"]:checked').value;
    var platform = document.getElementById('platformName').value || detectPlatform(url);

    if (pageType === 'video' && url && /^https?:\/\//.test(url)) {
        window.open(url, '_blank');
    }

    try {
        mediaStream = await navigator.mediaDevices.getDisplayMedia({audio: true, video: true});
        audioCtx = new AudioContext({sampleRate: 48000});
        var src = audioCtx.createMediaStreamSource(mediaStream);
        var proc = audioCtx.createScriptProcessor(8192, 1, 1);
        proc.onaudioprocess = function(e) {
            if (isRecording && ws && ws.readyState === 1) {
                ws.send(new Float32Array(e.inputBuffer.getChannelData(0)).buffer);
            }
        };
        src.connect(proc); proc.connect(audioCtx.destination);
        isRecording = true;
        send({type: 'start'});
        firstMsg = true; segCount = 0;
        updateBtns();
        setRec('recording', '识别中...');
        BOX.innerHTML = '<em style="color:#656d76">正在监听...</em>';

        if (creator || platform) {
            setTimeout(function() {
                send({type: 'page_creator', creator: creator, page_type: pageType, platform: platform});
                if (creator) {
                    send({type: 'keyword_add', keyword: creator, category: 'speaker'});
                }
            }, 1500);
        }
    } catch(e) {
        if (e.name !== 'AbortError') alert('屏幕共享失败: ' + (e.message || '用户取消'));
    }
}

function stopRec() {
    isRecording = false;
    send({type: 'stop'});
    cleanupAudio();
    updateBtns();
    setRec('ready', '已停止');
}

function cleanupAudio() {
    if (mediaStream) { mediaStream.getTracks().forEach(function(t){t.stop();}); mediaStream = null; }
    if (audioCtx) { audioCtx.close(); audioCtx = null; }
}

BTN_START.addEventListener('click', function() {
    PROMPT.style.display = '';
});

document.getElementById('btnSetupConfirm').addEventListener('click', function() {
    PROMPT.style.display = 'none';
    doStartRec();
});

document.getElementById('btnSetupCancel').addEventListener('click', function() {
    PROMPT.style.display = 'none';
});

BTN_STOP.addEventListener('click', stopRec);

document.getElementById('btnClear').addEventListener('click', function() {
    send({type: 'clear'}); clearUI();
});
document.getElementById('btnReport').addEventListener('click', function() {
    if (segCount===0) { alert('还没有识别内容'); return; }
    send({type: 'generate_report'});
});
document.getElementById('btnSave').addEventListener('click', function() {
    if (segCount===0) { alert('还没有识别内容'); return; }
    send({type: 'save_report'});
});
document.getElementById('btnLog').addEventListener('click', function() {
    if (segCount===0) { alert('还没有识别内容'); return; }
    send({type: 'save_log'});
});

document.getElementById('btnAddKw').addEventListener('click', function() {
    var kw = document.getElementById('kwInput').value.trim();
    var cat = document.getElementById('kwCat').value;
    if (kw) { send({type:'keyword_add', keyword:kw, category:cat}); document.getElementById('kwInput').value = ''; }
});
document.getElementById('kwInput').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') document.getElementById('btnAddKw').click();
});

connect();
setInterval(function() { if (!ws || ws.readyState !== 1) { if (!reconnectTimer) connect(); } }, 8000);
})();
</script>
</body>
</html>"""
import asyncio
import websockets
from websockets.http11 import Response, Headers
import json
import numpy as np
import soundfile as sf
import time
import logging
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
try:
    from pypinyin import lazy_pinyin, Style
except ImportError:
    lazy_pinyin = None
    Style = None
from core import MODELS_DIR
from keyword_expander import expander, CATEGORIES, CATEGORY_ICONS
from speaker_profile import sp_manager, DIALECT_TRAITS, DIALECT_PRESETS, search_speaker_accent, TOPIC_MANAGER
from lyrics_matcher import lyrics_matcher

DICT_DIR = Path(__file__).parent / 'dict'

LYRICS_PATH = DICT_DIR / "lyrics.json"
if LYRICS_PATH.exists():
    lyrics_matcher.load(str(LYRICS_PATH))

logging.getLogger('websockets.server').setLevel(logging.CRITICAL)
logging.getLogger('websockets').setLevel(logging.CRITICAL)

TEMP_DIR = Path(__file__).parent / "temp"
TEMP_DIR.mkdir(exist_ok=True)


class RealtimeASRServer:

    MUSIC_ZCR_THRESHOLD = 0.25
    MUSIC_ENERGY_EPSILON = 1e-6
    OCR_MIN_KW_LEN = 2
    OCR_SIMILARITY_THRESHOLD = 0.90
    PHONETIC_PARTIAL_MATCH = 0.6
    ENGLISH_MATCH_THRESHOLD = 0.70

    def __init__(self, asr_engine, correction_manager, host='localhost', port=8765):
        self.asr_engine = asr_engine
        self.correction_manager = correction_manager
        self.host = host
        self.port = port

        self.is_running = False
        self.client = None
        self.client_connected = False
        self.recording_ws = None
        self._current_handler_ws = None
        self._clients = set()
        self.executor = ThreadPoolExecutor(max_workers=8)

        self.full_text = ""
        self.segments = []
        self.keyword_store = {cat: set() for cat in CATEGORIES}
        self.ocr_keywords = set()
        self.last_ocr_text = ""
        self.correction_log = set()  # 记录被关键词纠正过的词，用于报告高亮
        self.correction_records = []  # 记录纠正明细 (原词, 纠正词)
        self._session_active_speakers = set()  # 本会话匹配了画像库的speaker名
        self._session_new_keywords = set()  # 本会话手动添加的关键词(用于自动保存到画像库)
        self._loaded_topics = set()  # 本会话已加载的话题

        self.pinyin_corrections = self._load_pinyin_corrections()

        # 说话人分离 (CAM++ 中英文通用声纹模型)
        print("[SPEAKER] Loading CAM++ speaker verification model...", flush=True)
        self.sv_pipeline = None
        try:
            import logging
            for _name in ["transformers", "diffusers", "huggingface_hub",
                          "datasets", "accelerate", "tokenizers", "modelscope"]:
                _lg = logging.getLogger(_name)
                _lg.handlers.clear()
                _lg.addHandler(logging.NullHandler())
                _lg.propagate = False

            from modelscope.pipelines import pipeline
            from modelscope.utils.constant import Tasks

            cam_model_id = 'iic/speech_campplus_sv_zh-cn_16k-common'
            cam_local = None
            cam_search_paths = [
                MODELS_DIR / 'hub' / 'models' / 'iic' / 'speech_campplus_sv_zh-cn_16k-common',
            ]
            for candidate in list(MODELS_DIR.glob('**/speech_campplus_sv_zh-cn_16k-common')):
                if not candidate.is_dir():
                    continue
                if candidate in cam_search_paths:
                    continue
                if '.___' in str(candidate):
                    continue
                cam_search_paths.insert(0, candidate)
            for p in cam_search_paths:
                if p.is_dir() and '.___' not in str(p):
                    cam_local = str(p)
                    print(f"[SPEAKER] CAM++ from project cache: {cam_local}", flush=True)
                    break

            if cam_local:
                self.sv_pipeline = pipeline(
                    task=Tasks.speaker_verification,
                    model=cam_local,
                )
            else:
                self.sv_pipeline = pipeline(
                    task=Tasks.speaker_verification,
                    model=cam_model_id,
                    model_revision='v1.0.0'
                )
            print("[SPEAKER] CAM++ model loaded", flush=True)
        except Exception as e:
            print(f"[SPEAKER] CAM++ load failed: {e}", flush=True)
            print("[SPEAKER] Speaker diarization disabled, ASR will still work", flush=True)
            self.sv_pipeline = None
        self.speaker_profiles = []
        self.last_speaker_id = 0
        self._last_speaker_label = 'Speaker0'
        self._host_speaker_label = None  # 本会话检测到的主播label

        DICT_DIR.mkdir(exist_ok=True)
        self._voiceprint_dir = DICT_DIR / 'voiceprints'
        self._voiceprint_dir.mkdir(exist_ok=True)

        # 加载历史保存的声纹
        self._load_saved_voice_profiles()

        # 音频缓冲区
        self.audio_buffer = []
        self.browser_sample_rate = 48000
        self.target_sample_rate = 16000
        self.max_buffer_seconds = 30
        self.max_buffer_size = 16000 * self.max_buffer_seconds
        self.vad_silence_threshold = 0.85

        self.vad_force_cut = self.asr_engine._config.get("model_settings", {}).get("vad_force_cut", True)
        self.min_speech_duration = self.asr_engine._config.get("model_settings", {}).get("min_speech_duration", 0.08)

        self._overlap_seconds = 0.2
        self._audio_tail = np.array([], dtype=np.float32)

        # 避免重复发送已识别的文本
        self.sent_texts = set()

        # 自适应VAD阈值
        self.speech_gaps = []
        self.adaptive_threshold = 1.35

        self.total_audio_seconds = 0
        self.transcription_count = 0
        self.last_segment_wall_time = 0
        self.last_segment_end_audio_time = 0

        self.ocr_history = []
        self.keyword_history = []

        # 页面信息（用于声纹智能命名）
        self._page_creator = None
        self._page_platform = None
        self._page_type = 'web'  # 'live' | 'video' | 'web'
        self._video_offset = 0  # 视频已播放时间偏移

        # 异步转录控制
        self.transcripts_in_flight = 0
        self.max_concurrent_transcripts = 2
        self.last_periodic_transcribe = 0

        # 连接稳定性
        self.last_activity = time.time()

        print(f"[VAD] vad_force_cut={self.vad_force_cut}", flush=True)

    def _resample_audio(self, audio_data, from_rate, to_rate):
        if from_rate == to_rate:
            return audio_data
        try:
            from scipy import signal
            return signal.resample_poly(audio_data.astype(np.float64), to_rate, from_rate).astype(np.float32)
        except ImportError:
            ratio = from_rate // to_rate
            return audio_data[::ratio].astype(np.float32)

    async def handler(self, websocket):
        self._current_handler_ws = websocket
        try:
            await websocket.send(json.dumps({
                'type': 'welcome',
                'message': 'Realtime ASR service connected',
                'model': self.asr_engine.model_name,
                'timestamp': datetime.now().isoformat()
            }, ensure_ascii=False))

            print(f"[WS] Client connected: {websocket.remote_address}")
            self.client = websocket
            self.client_connected = True
            self._clients.add(websocket)

            async for message in websocket:
                if isinstance(message, bytes):
                    await self.process_audio(message, websocket)
                elif isinstance(message, str):
                    await self.handle_control_message(json.loads(message), websocket)

        except websockets.exceptions.ConnectionClosedOK:
            print("[WS] Client disconnected normally")
        except websockets.exceptions.ConnectionClosedError as e:
            print(f"[WS] Client disconnected: {e}")
        except Exception as e:
            print(f"[WS] Error: {e}")
        finally:
            self._clients.discard(websocket)
            if self.client is websocket:
                self.client = None
                self.client_connected = False
            if self.recording_ws is websocket:
                self.recording_ws = None
                self.is_running = False
                print("[WS] Recording client disconnected")
            if self._current_handler_ws is websocket:
                self._current_handler_ws = None

    async def handle_control_message(self, msg, websocket):
        msg_type = msg.get('type')
        try:
            if msg_type == 'start':
                # 单录制互斥：已有一个页面在录音时，新页面拒绝
                if self.recording_ws and self.recording_ws is not websocket:
                    await self._send_to(websocket, {
                        'type': 'error',
                        'message': '另一个页面正在录音，请先停止后再试'
                    })
                    print(f"[WS] Start rejected: another client is recording")
                    return
                self.is_running = True
                self.recording_ws = websocket
                self.full_text = ""
                self.segments = []
                self.audio_buffer = []
                self.keyword_store = {cat: set() for cat in CATEGORIES}
                self.ocr_keywords = set()
                self.last_ocr_text = ""
                self.correction_log = set()
                self.correction_records = []
                self._session_active_speakers = set()
                self._session_new_keywords = set()
                self.sent_texts = set()
                self._audio_tail = np.array([], dtype=np.float32)
                self.last_speaker_id = 0
                self.total_audio_seconds = 0
                self.transcription_count = 0
                self.transcripts_in_flight = 0
                self.last_periodic_transcribe = 0
                self._pending_new = None
                self._last_speaker_label = 'Speaker0'
                self.last_segment_wall_time = 0
                self.last_segment_end_audio_time = 0
                self.keyword_history = []
                self.ocr_history = []
                lyrics_matcher.reset()
                await self._send_to(websocket, {
                    'type': 'status', 'status': 'recording',
                    'message': 'Started', 'model': self.asr_engine.model_name,
                    'keywords': list(self.ocr_keywords)
                })
                print("[WS] Recording started")
                for client in list(self._clients):
                    if client is not websocket:
                        try:
                            await self._send_to(client, {'type': 'recording_state', 'recording': True})
                        except Exception:
                            pass

            elif msg_type == 'stop':
                if self.recording_ws is websocket:
                    self.recording_ws = None
                self.is_running = False
                # Flush remaining buffer
                if len(self.audio_buffer) > 16000:
                    await self.transcribe_buffer(np.array(self.audio_buffer, dtype=np.float32))
                self._merge_segments()
                await self._send_to(websocket, {
                    'type': 'status', 'status': 'stopped',
                    'message': 'Stopped', 'full_text': self.full_text.strip(),
                    'segments': self.segments
                })
                # 自动保存手动关键词到画像库
                if self._session_active_speakers and self._session_new_keywords:
                    saved = 0
                    new_kws = self._session_new_keywords - set().union(*[
                        set(sp_manager.get_catchphrases(sp)) for sp in self._session_active_speakers
                    ])
                    for sp in self._session_active_speakers:
                        added = sp_manager.add_catchphrases(sp, list(new_kws))
                        saved += added
                    if saved:
                        sp_manager.save_library()
                        print(f"[WS] 💾 自动保存 {saved} 个新口头禅到画像库 (speakers={list(self._session_active_speakers)})", flush=True)
                print("[WS] Recording stopped")
                for client in list(self._clients):
                    if client is not websocket:
                        try:
                            await self._send_to(client, {'type': 'recording_state', 'recording': False})
                        except Exception:
                            pass

                # 保存声纹
                vp_result = self._save_voice_profiles()
                if vp_result:
                    await self._send_to(websocket, {
                        'type': 'voice_profiles_saved',
                        'profiles': vp_result
                    })

            elif msg_type == 'clear':
                self.full_text = ""
                self.segments = []
                self.audio_buffer = []
                self.keyword_store = {cat: set() for cat in CATEGORIES}
                self.ocr_keywords.clear()
                self.last_ocr_text = ""
                self.sent_texts = set()
                self.speaker_profiles = []
                self.last_speaker_id = 0
                self._pending_new = None
                self._last_speaker_label = 'Speaker0'
                self.last_segment_wall_time = 0
                self.last_segment_end_audio_time = 0
                self.total_audio_seconds = 0
                self.transcription_count = 0
                self.ocr_history = []
                self.keyword_history = []
                self._session_active_speakers = set()
                self._session_new_keywords = set()
                await self._send_to(websocket, {'type': 'status', 'status': 'cleared'})
                await self._send_to(websocket, {'type': 'keywords_updated', 'keywords': []})

            elif msg_type == 'update_keywords':
                keywords = msg.get('keywords', [])
                kcat = msg.get('category', 'other')
                if isinstance(keywords, list) and keywords:
                    added = set()
                    for kw in keywords:
                        kw = str(kw).strip()
                        if kw and len(kw) >= 2 and kw not in self.ocr_keywords:
                            self.keyword_store.setdefault(kcat, set()).add(kw)
                            self.ocr_keywords.add(kw)
                            added.add(kw)
                            self.keyword_history.append({'time': datetime.now().strftime('%H:%M:%S'), 'keyword': kw, 'category': kcat})
                    if added:
                        print(f"[KW] New keywords [{CATEGORIES.get(kcat, '关键词')}]: {list(added)[:10]}")

            elif msg_type == 'generate_report':
                await self.generate_and_send_report(websocket)

            elif msg_type == 'page_creator':
                self._page_creator = msg.get('creator')
                self._page_platform = msg.get('platform')
                self._page_type = msg.get('page_type', 'web')
                self._video_offset = msg.get('video_offset', 0)
                print(f"[WS] 页面信息: 创作者={self._page_creator} 平台={self._page_platform} 类型={self._page_type} 偏移={self._video_offset}s", flush=True)

            elif msg_type == 'load_vocab':
                tags = [msg.get('name', '')]
                if tags and tags[0]:
                    topic_kws, matched_topics = TOPIC_MANAGER.match_and_load(tags)
                    added = 0
                    for kw in topic_kws:
                        kw = kw.strip()
                        if kw and len(kw) >= 2 and kw not in self.ocr_keywords:
                            self.ocr_keywords.add(kw)
                            added += 1
                    for topic in matched_topics:
                        self.pinyin_corrections = self._load_pinyin_corrections(topic)
                    if added:
                        print(f"[WS] 🏷 话题匹配(vocab路由): {tags} → 加载{added}个关键词", flush=True)
                        await self._send_to(websocket, {
                            'type': 'keywords_updated',
                            'keywords': list(self.ocr_keywords),
                            'keyword_store': {c: list(v) for c, v in self.keyword_store.items() if v},
                            'categories': CATEGORIES,
                            'category_icons': CATEGORY_ICONS,
                            'topic_loaded': added,
                        })
                    else:
                        await self._send_to(websocket, {
                            'type': 'vocab_loaded',
                            'name': tags[0],
                            'count': 0,
                        })

            elif msg_type == 'new_speaker':
                name = msg.get('name', f'发言人{self.last_speaker_id}')
                for profile in self.speaker_profiles:
                    if profile['label'] == f"Speaker{msg.get('id', 0)}":
                        profile['alias'] = name
                        break

            elif msg_type == 'ping':
                await self._send_to(websocket, {'type': 'pong'})

            elif msg_type == 'keyword_add':
                keyword = msg.get('keyword', '').strip()
                cat = msg.get('category', 'other')
                if cat not in CATEGORIES:
                    cat = 'other'
                if keyword and len(keyword) >= 2:
                    self.keyword_store[cat].add(keyword)
                    self.ocr_keywords.add(keyword)
                    all_kws = self._get_all_keywords()
                    self.keyword_history.append({
                        'time': datetime.now().strftime('%H:%M:%S'),
                        'keyword': keyword, 'category': cat
                    })
                    icon = CATEGORY_ICONS.get(cat, '')
                    print(f"[WS] {icon}添加关键词 [{CATEGORIES[cat]}]: {keyword} (共{len(all_kws)}个)", flush=True)
                    self._session_new_keywords.add(keyword)
                    await self._send_to(websocket, {
                        'type': 'keywords_updated',
                        'keywords': list(self.ocr_keywords),
                        'keyword_store': {c: list(v) for c, v in self.keyword_store.items() if v},
                        'categories': CATEGORIES,
                        'category_icons': CATEGORY_ICONS,
                    })

                    if cat == 'speaker':
                        profile = sp_manager.get_or_create(keyword, keyword)
                        kw_loaded = 0
                        if profile.library_loaded:
                            self._session_active_speakers.add(keyword)
                        if profile.library_loaded and profile.catchphrases:
                            for cp in profile.catchphrases:
                                cp = cp.strip()
                                if cp and len(cp) >= 2 and cp not in self.ocr_keywords:
                                    self.ocr_keywords.add(cp)
                                    kw_loaded += 1
                            if kw_loaded:
                                print(f"[WS] 📢 '{profile.label}' 口头禅导入: {profile.catchphrases} ({kw_loaded}个，后台纠正)", flush=True)
                        await self._send_to(websocket, {
                            'type': 'speaker_profile_matched',
                            'keyword': keyword,
                            'library_matched': profile.library_loaded,
                            'profile_label': profile.label,
                            'accent_region': profile.accent_region,
                            'accent_desc': profile.accent_desc,
                        })
                        if kw_loaded:
                            await self._send_to(websocket, {
                                'type': 'keywords_updated',
                                'keywords': list(self.ocr_keywords),
                                'keyword_store': {c: list(v) for c, v in self.keyword_store.items() if v},
                                'categories': CATEGORIES,
                                'category_icons': CATEGORY_ICONS,
                            })

                    if cat == 'topic':
                        topic_kws, matched_topics = TOPIC_MANAGER.match_and_load([keyword])
                        topic_added = 0
                        for kw in topic_kws:
                            kw = kw.strip()
                            if kw and len(kw) >= 2 and kw not in self.ocr_keywords:
                                self.ocr_keywords.add(kw)
                                topic_added += 1
                        for topic in matched_topics:
                            self.pinyin_corrections = self._load_pinyin_corrections(topic)
                        if topic_added:
                            print(f"[WS] 🏷 自动匹配话题 '{keyword}' → 加载{topic_added}个专用词", flush=True)
                            await self._send_to(websocket, {
                                'type': 'keywords_updated',
                                'keywords': list(self.ocr_keywords),
                                'keyword_store': {c: list(v) for c, v in self.keyword_store.items() if v},
                                'categories': CATEGORIES,
                                'category_icons': CATEGORY_ICONS,
                                'topic_auto_loaded': {'name': keyword, 'count': topic_added},
                            })

            elif msg_type == 'topic_keywords_load':
                tags = msg.get('tags', [])
                if tags:
                    topic_kws, matched_topics = TOPIC_MANAGER.match_and_load(tags)
                    added = 0
                    for kw in topic_kws:
                        kw = kw.strip()
                        if kw and len(kw) >= 2 and kw not in self.ocr_keywords:
                            self.ocr_keywords.add(kw)
                            added += 1
                    for topic in matched_topics:
                        self.pinyin_corrections = self._load_pinyin_corrections(topic)
                    if added:
                        print(f"[WS] 🏷 话题匹配: {tags[:5]} → 加载{added}个关键词(后台纠正，不显示在面板)", flush=True)
                        await self._send_to(websocket, {
                            'type': 'keywords_updated',
                            'keywords': list(self.ocr_keywords),
                            'keyword_store': {c: list(v) for c, v in self.keyword_store.items() if v},
                            'categories': CATEGORIES,
                            'category_icons': CATEGORY_ICONS,
                            'topic_loaded': len(topic_kws),
                        })

            elif msg_type == 'video_title':
                title = msg.get('title', '').strip()
                if title:
                    extracted = self._extract_title_keywords(title)
                    added = 0
                    for kw in extracted:
                        if kw and len(kw) >= 2 and kw not in self.ocr_keywords:
                            self.ocr_keywords.add(kw)
                            added += 1
                    if added:
                        print(f"[WS] 📺 标题提取: '{title[:40]}' → {added}个关键词", flush=True)
                        await self._send_to(websocket, {
                            'type': 'keywords_updated',
                            'keywords': list(self.ocr_keywords),
                            'keyword_store': {c: list(v) for c, v in self.keyword_store.items() if v},
                            'categories': CATEGORIES,
                            'category_icons': CATEGORY_ICONS,
                        })

            elif msg_type == 'live_squad':
                members = msg.get('members', [])
                if members:
                    print(f"[WS] 👥 直播小队: {members}", flush=True)
                    profile_hits = []
                    profile_misses = []
                    for name in members:
                        name = name.strip()
                        if not name or len(name) < 2:
                            continue
                        # 加入 speaker 关键词（用于声纹纠正）
                        if name not in self.ocr_keywords:
                            self.ocr_keywords.add(name)
                            self.keyword_store.setdefault('speaker', set()).add(name)
                        # 尝试从画像库加载
                        profile = sp_manager.get_or_create(name, name)
                        if profile.library_loaded:
                            profile_hits.append(name)
                            self._session_active_speakers.add(name)
                            if profile.catchphrases:
                                added = 0
                                for cp in profile.catchphrases:
                                    cp = cp.strip()
                                    if cp and len(cp) >= 2 and cp not in self.ocr_keywords:
                                        self.ocr_keywords.add(cp)
                                        added += 1
                                if added:
                                    print(f"[WS] 📢 '{name}' 口头禅导入: {profile.catchphrases} ({added}个)", flush=True)
                        else:
                            profile_misses.append(name)

                    if profile_hits:
                        print(f"[WS] ✅ 画像库命中: {profile_hits}", flush=True)
                    if profile_misses:
                        print(f"[WS] 📝 未匹配画像库: {profile_misses}", flush=True)

                    await self._send_to(websocket, {
                        'type': 'keywords_updated',
                        'keywords': list(self.ocr_keywords),
                        'keyword_store': {c: list(v) for c, v in self.keyword_store.items() if v},
                        'categories': CATEGORIES,
                        'category_icons': CATEGORY_ICONS,
                    })
                    await self._send_to(websocket, {
                        'type': 'live_squad',
                        'members': members,
                        'profile_hits': profile_hits,
                        'profile_misses': profile_misses,
                    })

            elif msg_type == 'keyword_expand':
                keyword = msg.get('keyword', '').strip()
                cat = msg.get('category', 'other')
                use_llm = msg.get('use_llm', False)
                if keyword and len(keyword) >= 2:
                    local = expander.expand(keyword, cat)
                    all_terms = set(local)
                    llm_used = False
                    if use_llm:
                        success, llm_terms = expander.llm_expand(keyword, cat)
                        if success:
                            llm_used = True
                            all_terms.update(llm_terms)
                    for t in all_terms:
                        if len(t) >= 2:
                            self.keyword_store[cat].add(t)
                            self.ocr_keywords.add(t)
                    all_kws = self._get_all_keywords()
                    print(f"[WS] 🔮 关键词扩展: '{keyword}' → {list(all_terms)[:12]} (LLM={llm_used}, 总计{len(all_kws)}个)", flush=True)
                    await self._send_to(websocket, {
                        'type': 'keywords_updated',
                        'keywords': list(self.ocr_keywords),
                        'keyword_store': {c: list(v) for c, v in self.keyword_store.items() if v},
                        'categories': CATEGORIES,
                        'category_icons': CATEGORY_ICONS,
                        'expanded': list(all_terms),
                        'llm_used': llm_used,
                    })

            elif msg_type == 'speaker_profile_get':
                speaker_id = msg.get('speaker_id', self._last_speaker_label)
                profile = sp_manager.get_or_create(speaker_id)

                kw_loaded = 0
                if profile.library_loaded and profile.catchphrases:
                    for cp in profile.catchphrases:
                        cp = cp.strip()
                        if cp and len(cp) >= 2 and cp not in self.ocr_keywords:
                            self.ocr_keywords.add(cp)
                            self.keyword_store.setdefault('speaker', set()).add(cp)
                            kw_loaded += 1
                    if kw_loaded:
                        print(f"[WS] 📢 '{profile.label}' 口头禅导入: {profile.catchphrases} ({kw_loaded}个)", flush=True)

                await self._send_to(websocket, {
                    'type': 'speaker_profile',
                    'profile': profile.to_dict(),
                    'library_matched': profile.library_loaded,
                    'all_speakers': list(self.speaker_profiles.keys()),
                    'catchphrases_loaded': kw_loaded,
                })
                if kw_loaded:
                    await self._send_to(websocket, {
                        'type': 'keywords_updated',
                        'keywords': list(self.ocr_keywords),
                        'keyword_store': {c: list(v) for c, v in self.keyword_store.items() if v},
                        'categories': CATEGORIES,
                        'category_icons': CATEGORY_ICONS,
                    })

            elif msg_type == 'speaker_profile_update':
                speaker_id = msg.get('speaker_id', '')
                updates = msg.get('updates', {})
                if speaker_id:
                    profile = sp_manager.update(speaker_id, **updates)
                    await self._send_to(websocket, {
                        'type': 'speaker_profile',
                        'profile': profile.to_dict(),
                        'dialect_traits': DIALECT_TRAITS,
                        'dialect_presets': DIALECT_PRESETS,
                    })
                    print(f"[WS] 👤 更新说话人画像: {speaker_id} → {profile.label} traits={profile.get_trait_summary()}", flush=True)

            elif msg_type == 'speaker_accent_search':
                name = msg.get('name', '')
                birthplace = msg.get('birthplace', '')
                success, traits, description, accent_region = search_speaker_accent(name, birthplace)
                if success:
                    speaker_id = msg.get('speaker_id', self._last_speaker_label)
                    sp_manager.update(speaker_id, traits=traits, accent_region=accent_region, birthplace=birthplace)
                    print(f"[WS] 🔍 口音搜索: '{name or birthplace}' → {description}", flush=True)
                await self._send_to(websocket, {
                    'type': 'speaker_accent_result',
                    'success': success,
                    'traits': traits,
                    'description': description,
                    'accent_region': accent_region,
                })

            elif msg_type == 'speaker_rename':
                speaker_id = msg.get('speaker_id', '')
                new_label = msg.get('label', '')
                if speaker_id and new_label:
                    sp_manager.update(speaker_id, label=new_label)
                    # 同步重命名 speaker_profiles 列表中的显示名
                    for sp in self.speaker_profiles:
                        if sp == speaker_id:
                            self.speaker_profiles.remove(sp)
                            self.speaker_profiles.append(new_label)
                            break
                    print(f"[WS] 重命名: {speaker_id} → {new_label}", flush=True)
                    await self._send_to(websocket, {
                        'type': 'speaker_renamed',
                        'old_id': speaker_id,
                        'new_label': new_label,
                    })

            elif msg_type == 'save_report':
                self._merge_segments()
                report = self._generate_comprehensive_report()
                await self._send_to(websocket, {'type': 'save_report', 'content': report, 'filename': f'asr_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.md'})

            elif msg_type == 'save_log':
                self._merge_segments()
                log = self._generate_structured_log()
                await self._send_to(websocket, {'type': 'save_log', 'content': log, 'filename': f'asr_log_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'})

        except Exception as e:
            print(f"[WS] Control error: {e}")
            await self._send_to(websocket, {'type': 'error', 'message': str(e)})

    def _extract_keywords(self, text):
        text = re.sub(r'[^\w\s\u4e00-\u9fff]', ' ', text)
        words = text.split()
        stop_words = {'的', '了', '是', '在', '和', '有', '不', '这', '那', '也', '就', '都', '要', '会',
                      'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'to', 'of', 'in', 'for', 'on',
                      'and', 'or', 'but', 'with', 'it', 'that', 'this', 'I', 'you', 'he', 'she', 'we'}
        keywords = []
        for word in words:
            word = word.strip()
            if len(word) < 2 or word.lower() in stop_words:
                continue
            if re.search(r'[\u4e00-\u9fff]', word) or word.isalpha():
                keywords.append(word)
        return set(dict.fromkeys(keywords))

    def _extract_title_keywords(self, title):
        """从视频标题中提取有意义的专有名词/术语，用于ASR纠正"""
        stop_words = {'的', '了', '是', '在', '和', '有', '不', '这', '那', '也', '就', '都', '要', '会',
                      '我', '你', '他', '她', '它', '们', '个', '吗', '吧', '呢', '啊', '哦', '嗯',
                      '怎么', '什么', '为什么', '可以', '不能', '没有', '不是', '还是', '已经',
                      '一个', '这个', '那个', '哪个', '什么', '怎么', '这样', '那样',
                      '视频', '直播', '全集', '精彩', '高能', '日常', '第一', '第二', '第三',
                      '上集', '下集', '中集', '上期', '下期', '合集', '实况', '解说'}
        keywords = set()
        cleaned = re.sub(r'[【】《》「」『』\[\]()（）""''「」]', ' ', title)
        cleaned = re.sub(r'[｜|\-—–/、，。,\.！!？?：:；;…]', ' ', cleaned)
        for word in cleaned.split():
            word = word.strip()
            if len(word) >= 2 and len(word) < 20 and word not in stop_words:
                if re.search(r'[\u4e00-\u9fff]', word) or word.isalpha():
                    keywords.add(word)

        # 拆分中英混合词："m0NESY不敢相信" → "m0NESY" + "不敢相信"
        split_kws = set()
        for kw in list(keywords):
            if re.search(r'[\u4e00-\u9fff]', kw) and re.search(r'[a-zA-Z0-9]', kw):
                parts = re.split(
                    r'(?<=[\u4e00-\u9fff])(?=[a-zA-Z0-9])|(?<=[a-zA-Z0-9])(?=[\u4e00-\u9fff])',
                    kw)
                for part in parts:
                    part = part.strip()
                    if len(part) >= 2 and part not in stop_words:
                        split_kws.add(part)
            else:
                split_kws.add(kw)
        keywords = split_kws

        # 长中文短语再拆分为2-4字词（英文/数字短语不拆分，避免"m0NESY"→"m0N"等碎片）
        extra = set()
        for kw in list(keywords):
            if len(kw) >= 4 and re.search(r'[\u4e00-\u9fff]', kw):
                if re.search(r'[a-zA-Z0-9]', kw):
                    continue
                for i in range(len(kw) - 1):
                    for j in range(2, 5):
                        if i + j <= len(kw):
                            sub = kw[i:i+j]
                            if sub not in stop_words and len(sub) >= 2:
                                extra.add(sub)
        keywords.update(extra)
        return [w for w in keywords if len(w) >= 2 and w not in stop_words]

    def _get_all_keywords(self):
        """获取所有分类的去重关键词"""
        return list(self.ocr_keywords)

    async def process_audio(self, audio_data, websocket):
        if not self.is_running or websocket is not self.recording_ws:
            return
        try:
            audio_array = np.frombuffer(audio_data, dtype=np.float32)

            if self.browser_sample_rate != self.target_sample_rate:
                audio_array = self._resample_audio(
                    audio_array, self.browser_sample_rate, self.target_sample_rate)

            self.audio_buffer.extend(audio_array.tolist())

            # 每0.5秒检查一次是否可以转录
            buffer_dur = len(self.audio_buffer) / 16000
            if buffer_dur >= 0.5 and self.audio_buffer:
                # 用VAD检测是否有完整的语音段
                audio_seg, vad_info = self._vad_cut(np.array(self.audio_buffer, dtype=np.float32), 16000)

                if audio_seg is not None and len(audio_seg) > int(self.min_speech_duration * 16000):
                    await self.transcribe_buffer(audio_seg, vad_info)

                # 限制缓冲区大小
                if len(self.audio_buffer) > self.max_buffer_size:
                    self.audio_buffer = self.audio_buffer[-self.max_buffer_size:]

        except Exception as e:
            print(f"[WS] Audio error: {e}")
            import traceback
            traceback.print_exc()

    def _vad_cut(self, audio_data, sr):
        """
        自适应VAD：根据说话语速动态调整静音断句阈值
        - 说话快（间隙短）→ 阈值小（1秒），快速断句
        - 说话慢（间隙长）→ 阈值大（2-4秒），耐心等待不打断
        返回 (语音段, 是否检测到静音间隙)
        """
        frame_len = int(sr * 0.03)
        hop_len = int(sr * 0.01)
        n_frames = (len(audio_data) - frame_len) // hop_len + 1

        vad_info = {'silence': 1.35, 'forced': False, 'overlap': 1.35, 'chunk_dur': 0}

        min_dur_frames = int(self.min_speech_duration / 0.03)
        if n_frames < min_dur_frames:
            return None, vad_info

        energies = np.zeros(n_frames)
        for i in range(n_frames):
            start = i * hop_len
            frame = audio_data[start:start + frame_len]
            energies[i] = np.sqrt(np.mean(frame ** 2))

        threshold = np.median(energies) * 1.5 if np.median(energies) > 0 else 0.0005
        is_speech = energies > threshold

        # === 音乐/噪声检测：影响强制切分阈值 ===
        music_like = self._is_music_like(audio_data)
        vad_info['music_like'] = music_like
        if self.vad_force_cut:
            force_cut_sec = 6.0 if music_like else 3.9
            force_cut_size = 5.0 if music_like else 3.8
            desperate_sec = 8.0 if music_like else 5.0
        else:
            force_cut_sec = self.max_buffer_seconds
            force_cut_size = self.max_buffer_seconds
            desperate_sec = self.max_buffer_seconds

        # === 计算语音爆发间隙，更新自适应阈值 ===
        changes = np.diff(np.concatenate([[False], is_speech, [False]]).astype(int))
        starts = np.where(changes == 1)[0]   # 语音爆发开始帧
        ends = np.where(changes == -1)[0]     # 语音爆发结束帧
        ends = ends[:len(starts)]              # 对齐

        # 计算间隙（上一段结束到下一段开始）
        for i in range(1, len(starts)):
            gap = (starts[i] - ends[i-1]) * 0.01  # 转换为秒
            if 0.05 < gap < 10:  # 忽略太短和太长的异常间隙
                self.speech_gaps.append(gap)
                if len(self.speech_gaps) > 20:
                    self.speech_gaps.pop(0)

        min_silence_frames = int(self.adaptive_threshold / 0.01)
        min_speech_frames = max(1, int(self.min_speech_duration / 0.01))

        # === 找到完整语音段（末尾有足够静音）===
        if np.any(is_speech):
            last_speech_frame = np.where(is_speech)[0][-1]
            silence_after = n_frames - last_speech_frame
            first_speech_frame = np.where(is_speech)[0][0]
            speech_duration = (last_speech_frame - first_speech_frame + 1) * 0.01

            # 连续说话 > 2.5s 且有任意静音则切（不等满 silence_after）
            if self.vad_force_cut and speech_duration > 2.5 and silence_after >= int(0.3 / 0.01):
                cut_point = (last_speech_frame + 1) * hop_len
                speech_segment = audio_data[:cut_point]
                remaining_start = cut_point + int(0.3 * sr)
                remaining = audio_data[remaining_start:]
                self.audio_buffer = list(remaining) if len(remaining) > 0 else []
                self.speech_gaps = []
                self.adaptive_threshold = 1.35
                vad_info['chunk_dur'] = len(speech_segment) / sr
                vad_info['forced'] = False
                return speech_segment, vad_info

            if silence_after >= min_silence_frames:
                cut_point = (last_speech_frame + 1) * hop_len
                speech_segment = audio_data[:cut_point]
                speech_duration = len(speech_segment) / sr

                if speech_duration <= 1.2:
                    remaining_start = cut_point + min_silence_frames * hop_len
                else:
                    overlap_frames = int(1.5 / 0.01)
                    remaining_start = max(0, cut_point + min_silence_frames * hop_len - overlap_frames * hop_len)
                remaining = audio_data[remaining_start:]
                self.audio_buffer = list(remaining) if len(remaining) > 0 else []

                # 重置间隙统计
                self.speech_gaps = []
                self.adaptive_threshold = 1.35

                vad_info['chunk_dur'] = len(speech_segment) / sr
                vad_info['forced'] = False
                return speech_segment, vad_info

            # 缓冲区超过阈值且无静音间隙则强制切出
            buffer_dur = len(audio_data) / sr
            if buffer_dur > force_cut_sec:
                cut_samples = int(force_cut_size * sr)
                speech_segment = audio_data[:cut_samples]
                self.audio_buffer = list(audio_data[cut_samples:])
                vad_info['forced'] = True
                vad_info['chunk_dur'] = len(speech_segment) / sr
                return speech_segment, vad_info

        # 无语音检测但缓冲区已积压：可能是轻声说话/连续背景音，强制送出转写
        buffer_dur = len(audio_data) / sr
        if buffer_dur > desperate_sec:
            cut_samples = int(min(buffer_dur, 6.0) * sr)
            speech_segment = audio_data[:cut_samples]
            self.audio_buffer = list(audio_data[cut_samples:])
            vad_info['forced'] = True
            vad_info['chunk_dur'] = len(speech_segment) / sr
            return speech_segment, vad_info

        return None, vad_info

    async def transcribe_buffer(self, audio_data, vad_info=None):
        if self.transcripts_in_flight >= self.max_concurrent_transcripts:
            return
        self.transcripts_in_flight += 1

        if len(self._audio_tail) > 0:
            audio_data = np.concatenate([self._audio_tail, audio_data])

        tail_samples = int(self._overlap_seconds * 16000)
        if len(audio_data) > tail_samples:
            self._audio_tail = audio_data[-tail_samples:].copy()
        else:
            self._audio_tail = audio_data.copy()

        timestamp = int(time.time() * 1000)
        temp_path = TEMP_DIR / f'realtime_chunk_{timestamp}.wav'
        sf.write(str(temp_path), audio_data, 16000)

        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(
            self.executor, self._do_transcribe, str(temp_path))

        asyncio.ensure_future(self._handle_transcription(future, temp_path, audio_data, vad_info))

    async def _handle_transcription(self, future, temp_path, audio_data, vad_info=None):
        try:
            text = await future
            self.transcripts_in_flight -= 1

            if temp_path.exists():
                temp_path.unlink()

            if not text or not text.strip():
                return

            text = text.strip()

            if self.segments:
                prev = self.segments[-1]['text']
                before_dedup = text
                text = self._dedup_overlap(prev, text)
                if text != before_dedup:
                    removed = before_dedup[:len(before_dedup)-len(text)] if len(before_dedup) > len(text) else before_dedup
                    print(f"    [DEDUP] 与上段重叠去重: removed='{removed[:20]}' → kept='{text[:30]}'", flush=True)

            text = self._dedup_chars(text)

            if not text:
                return

            # 音乐/噪声检测
            music_like = self._is_music_like(audio_data)

            # 音乐/噪声场景下过滤英文幻听（如 "Oh.", "The.", "I'm sorry." 等）
            # 非音乐场景不按语言过滤，避免误丢弃真实外语/英语语音
            if music_like:
                chinese_count = len(re.findall(r'[\u4e00-\u9fff]', text))
                alpha_count = len(re.findall(r'[a-zA-Z]', text))
                if chinese_count == 0:
                    if alpha_count >= 2 and alpha_count < 20:
                        print(f"    [SKIP-MUSIC] '{text[:30]}' (无中文+短英文, 疑似音乐幻听)", flush=True)
                        return
                    if alpha_count < 2:
                        return

            if text in self.sent_texts:
                print(f"    [DEDUP-SENT] 完全重复: '{text[:30]}'", flush=True)
                return
            for prev in list(self.sent_texts):
                if prev in text and len(prev) > len(text) * 0.5:
                    print(f"    [DEDUP-SENT] 包含已发送: prev='{prev[:20]}' in text='{text[:30]}'", flush=True)
                    return
                if text in prev and len(text) > len(prev) * 0.5:
                    print(f"    [DEDUP-SENT] 替换更短: old='{prev[:20]}' ← new='{text[:30]}'", flush=True)
                    self.sent_texts.discard(prev)

            corrected = text
            original = corrected
            corrected, py_corrections = self._apply_pinyin_dict_correction(corrected)
            corrected, ocr_corrections = self._apply_ocr_correction(corrected)
            corrections = py_corrections + ocr_corrections
            ocr_applied = (original != corrected)
            if py_corrections:
                for old, new in py_corrections:
                    self.correction_log.add(new)
                    self.correction_records.append((old, new))

            # 口音矫正：仅当有实际口音特征加载时才启用
            loaded_count = sum(1 for p in sp_manager.profiles.values() if p.library_loaded or p.traits)
            all_traits = sp_manager.get_all_loaded_traits()
            if loaded_count > 0 and all_traits:
                if len(self.speaker_profiles) > 1 or loaded_count > 1:
                    accent_corrected, accent_corrections = sp_manager.accent_correct_all(
                        corrected, list(self.ocr_keywords))
                else:
                    accent_corrected, accent_corrections = sp_manager.accent_correct(
                        self._last_speaker_label, corrected, list(self.ocr_keywords))
            if accent_corrected != corrected:
                print(f"    [ACCENT] traits={sp_manager.get_all_loaded_traits() if loaded_count > 1 else sp_manager.get_accent_traits(self._last_speaker_label)}: '{corrected}' → '{accent_corrected}' ({len(accent_corrections)} corrections)", flush=True)
                corrections.extend([(old, new, desc) for old, new, desc in accent_corrections])
                for old, new, desc in accent_corrections:
                    self.correction_records.append(('accent', old, new, desc))
                corrected = accent_corrected
                ocr_applied = True

            # 歌词匹配：检测文本是否为歌词
            # 状态机追踪连续命中 → 锁定歌曲 → 锁定后高效匹配后续行
            lyrics_matched, lyrics_info = lyrics_matcher.match(corrected)
            if lyrics_matched:
                state = lyrics_info.get('state', 'idle')
                hits = lyrics_info.get('consecutive_hits', 1)
                just_locked = lyrics_info.get('just_locked', False)

                if state == 'locked':
                    # 已锁定歌曲，追加 🎶 并显示进度
                    prog = lyrics_info.get('line_idx', 0)
                    total = len(lyrics_matcher.songs[lyrics_info.get('song_idx', 0)].get('lines', []))
                    corrected = corrected.rstrip() + " 🎶"
                    if just_locked:
                        print(f"[WS] 🔒 {lyrics_info['title']} - {lyrics_info['artist']} 锁定! 自动加载 {total} 行歌词作为关键词", flush=True)
                        # 自动加载整首歌的歌词行作为 OCR 关键词，提升后续识别准确度
                        song = lyrics_matcher.songs[lyrics_info['song_idx']]
                        for line in song.get('lines', []):
                            clean = re.sub(r'[^\w\u4e00-\u9fff]', '', line)
                            if len(clean) >= 2:
                                self.ocr_keywords.add(clean)
                        print(f"[WS] 📋 已注入 {total} 行歌词关键词", flush=True)
                    else:
                        print(f"[WS] 🎶 [{hits}连] {lyrics_info['title']}: '{lyrics_info['line'][:30]}' [{lyrics_info['method']}]", flush=True)
                elif state == 'suspecting':
                    corrected = corrected.rstrip() + " 🎵"
                    print(f"[WS] 🎵 [{hits}/3→锁定] {lyrics_info['title']} - {lyrics_info['artist']}: '{lyrics_info['line'][:30]}' [{lyrics_info['method']}]", flush=True)
                else:
                    corrected = corrected.rstrip() + " 🎵"
                    print(f"[WS] 🎵 {lyrics_info['title']} - {lyrics_info['artist']}: '{lyrics_info['line'][:30]}' [{lyrics_info['method']}]", flush=True)

            sentences = self._split_sentences(corrected)
            if len(sentences) <= 1:
                await self._emit_segment(audio_data, corrected, ocr_applied, vad_info=vad_info, corrections=corrections, original_text=original if corrections else None)
            else:
                shared_speaker = None
                if len(audio_data) >= int(16000 * 1.5):
                    shared_speaker = await self._detect_speaker(audio_data)
                    self._last_speaker_label = shared_speaker
                seg_len = len(audio_data) // len(sentences)
                for i, sent in enumerate(sentences):
                    if not sent.strip():
                        continue
                    start = i * seg_len
                    end = start + seg_len if i < len(sentences) - 1 else len(audio_data)
                    sub_audio = audio_data[start:end]
                    if len(sub_audio) < 16000 * 0.3:
                        sub_audio = audio_data
                    await self._emit_segment(sub_audio, sent.strip(), ocr_applied, speaker_label=shared_speaker, vad_info=vad_info, corrections=corrections)

            status = f"[WS] [{self.transcription_count}]"
            if ocr_applied:
                status += " [KW]"
            print(f"{status} {corrected[:60]}...", flush=True)

            self.last_activity = time.time()

        except Exception as e:
            self.transcripts_in_flight -= 1
            print(f"[WS] Transcription error: {e}", flush=True)
            import traceback
            traceback.print_exc()
            await self.send({'type': 'error', 'message': str(e)})

    def _do_transcribe(self, temp_path):
        """在子线程中执行转写，避免阻塞事件循环"""
        return self.asr_engine.transcribe(temp_path)

    @staticmethod
    def _split_sentences(text):
        """
        按中文/英文标点分句，解决ASR一次返回多句的问题
        每句独立做 Speaker 检测
        注：逗号是句内停顿，不作为断句标志
        """
        import re
        parts = re.split(r'(?<=[。！？；\n])\s*|(?<=[.!?;])\s+', text)
        return [p.strip() for p in parts if p.strip()]

    async def _emit_segment(self, audio_data, text, ocr_applied=False, speaker_label=None, vad_info=None, corrections=None, original_text=None):
        """创建一条识别记录并发送到前端"""
        if not text or text in self.sent_texts:
            if text:
                print(f"    [DEDUP-EMIT] 已发送过: '{text[:30]}'", flush=True)
            return
        for prev in list(self.sent_texts):
            if prev in text and len(prev) > len(text) * 0.5:
                print(f"    [DEDUP-EMIT] 包含已发送: prev='{prev[:20]}' in '{text[:30]}'", flush=True)
                return

        # 如果调用方已提供 speaker_label（多句 chunk 共享），直接使用
        if speaker_label is not None:
            pass
        # 短音频不跑 VoiceEncoder（单字如"我""嗯"嵌入是噪声），直接用上一个说话人
        elif len(audio_data) < int(16000 * 0.5):
            speaker_label = self._last_speaker_label
        else:
            speaker_label = await self._detect_speaker(audio_data)
            self._last_speaker_label = speaker_label

        # 计算音频时间戳和gap
        seg_audio_time = self.total_audio_seconds
        seg_duration = len(audio_data) / 16000
        now_wall = time.time()

        gap_audio = 0.0
        gap_wall = 0.0
        if self.last_segment_wall_time > 0:
            gap_wall = now_wall - self.last_segment_wall_time
            gap_audio = seg_audio_time - self.last_segment_end_audio_time

        self.last_segment_wall_time = now_wall
        self.last_segment_end_audio_time = seg_audio_time + seg_duration

        seg_entry = {
            'text': text,
            'time': self.total_audio_seconds,
            'speaker': speaker_label,
            'duration': seg_duration,
            'ocr_corrected': ocr_applied,
            'vad': vad_info or {},
            'gap_audio': gap_audio,
            'gap_wall': gap_wall,
            'corrections': corrections or [],
        }
        self.segments.append(seg_entry)

        if speaker_label and speaker_label != "Speaker":
            display = f"[{speaker_label}] {text}"
        else:
            display = text

        self.full_text += display + " "
        self.sent_texts.add(text)
        self.total_audio_seconds += seg_duration
        self.transcription_count += 1

        await self.send({
            'type': 'transcription',
            'text': text,
            'speaker': speaker_label,
            'full_text': self.full_text.strip(),
            'timestamp': datetime.now().isoformat(),
            'duration': self.total_audio_seconds,
            'seg_time': seg_audio_time,
            'seg_dur': seg_duration,
            'gap_audio': gap_audio,
            'gap_wall': gap_wall,
            'keywords': list(self.ocr_keywords)[:10],
            'ocr_corrected': ocr_applied,
            'ocr_count': len(self.ocr_keywords),
            'corrections': corrections or [],
            'original_text': original_text or text,
            'is_host': speaker_label == self._host_speaker_label if speaker_label else False,
        })

    PHONETIC_MERGE = {
        ('z','zh'),('zh','z'),('c','ch'),('ch','c'),('s','sh'),('sh','s'),
        ('n','l'),('l','n'),('h','f'),('f','h'),('r','l'),('l','r'),
        ('an','ang'),('ang','an'),('en','eng'),('eng','en'),
        ('in','ing'),('ing','in'),
    }

    @staticmethod
    def _split_pinyin(py):
        initials = ['zh','ch','sh','b','p','m','f','d','t','n','l',
                    'g','k','h','j','q','x','r','z','c','s','y','w']
        py_clean = py.rstrip('12345')
        for init in initials:
            if py_clean.startswith(init):
                return init, py_clean[len(init):]
        return '', py_clean

    def _pinyin_similar(self, py1, py2):
        if py1 == py2:
            return True
        i1, f1 = self._split_pinyin(py1)
        i2, f2 = self._split_pinyin(py2)
        if (i1, i2) in self.PHONETIC_MERGE:
            return True
        if (f1, f2) in self.PHONETIC_MERGE:
            return True
        return False

    def _get_pinyin_list(self, text):
        try:
            if lazy_pinyin is None:
                return list(text)
            return lazy_pinyin(text, style=Style.TONE3)
        except (ValueError, TypeError, KeyError):
            return list(text)

    def _apply_ocr_correction(self, text):
        """用关键词纠正ASR近音错误。仅替换拼音相近的字符，杜绝 摩尔定律→摩韬定律 这类误替换。"""
        if not self.ocr_keywords or len(text) < 3:
            return text, []

        keywords = sorted(self.ocr_keywords, key=len, reverse=True)
        corrected = text
        corrections = []

        for kw in keywords:
            kw_len = len(kw)
            if kw_len < self.OCR_MIN_KW_LEN:
                continue
            if kw in corrected:
                continue

            kw_py = self._get_pinyin_list(kw)
            if not kw_py or len(kw_py) != kw_len:
                # Fallback: English/alphanumeric keywords (pinyin system can't handle them)
                if re.search(r'[a-zA-Z]', kw):
                    result = self._match_english_kw(corrected, kw)
                    if result:
                        sub, score = result
                        print(f"    [CORRECT-EN] '{sub}' -> '{kw}' (similarity={score:.2f})", flush=True)
                        corrections.append((sub, kw))
                        self.correction_log.add(kw)
                        self.correction_records.append((sub, kw))
                        corrected = corrected.replace(sub, kw, 1)
                continue

            best_pos = -1
            best_similar = -1
            best_sub = ""

            for i in range(len(corrected) - kw_len + 1):
                sub = corrected[i:i + kw_len]
                sub_py = self._get_pinyin_list(sub)
                if not sub_py or len(sub_py) != kw_len:
                    continue

                similar = 0
                total_diff = 0
                for sp, kp in zip(sub_py, kw_py):
                    if sp == kp:
                        similar += 1
                    elif self._pinyin_similar(sp, kp):
                        similar += self.PHONETIC_PARTIAL_MATCH
                    else:
                        total_diff += 1

                if total_diff > 0:
                    continue

                if similar > best_similar:
                    best_similar = similar
                    best_pos = i
                    best_sub = sub

            if best_pos >= 0 and best_similar >= kw_len * self.OCR_SIMILARITY_THRESHOLD and best_sub != kw:
                print(f"    [CORRECT] '{best_sub}' -> '{kw}' (phonetic_similar={best_similar:.1f}/{kw_len})", flush=True)
                corrections.append((best_sub, kw))
                self.correction_log.add(kw)
                self.correction_records.append((best_sub, kw))
                corrected = corrected[:best_pos] + kw + corrected[best_pos + kw_len:]

        return corrected, corrections

    def _load_pinyin_corrections(self, topic=None):
        corrections = {}
        base_dir = DICT_DIR / 'pinyin_corrections'
        base_dir.mkdir(exist_ok=True)
        general_path = base_dir / 'general.json'
        if general_path.exists():
            try:
                with open(general_path, 'r', encoding='utf-8') as f:
                    corrections.update(json.load(f))
            except (json.JSONDecodeError, OSError):
                pass
        if topic:
            topic_path = base_dir / f'{topic.lower()}.json'
            if topic_path.exists():
                try:
                    with open(topic_path, 'r', encoding='utf-8') as f:
                        corrections.update(json.load(f))
                    print(f"[PINYIN] 加载话题拼音纠正: {topic} ({topic_path.name})", flush=True)
                    self._loaded_topics.add(topic)
                except (json.JSONDecodeError, OSError):
                    pass
        return corrections

    def _apply_pinyin_dict_correction(self, text):
        if not self.pinyin_corrections or not text:
            return text, []
        sorted_entries = sorted(
            ((k, v) for k, v in self.pinyin_corrections.items() if not k.startswith('__')),
            key=lambda x: len(x[0].split()), reverse=True)

        use_tone = any(
            any(ch.isdigit() for ch in k) for k, v in sorted_entries
        )

        chars = list(text)
        py_list = []
        if lazy_pinyin is not None:
            py_style = Style.TONE3 if use_tone else Style.NORMAL
            for ch in chars:
                try:
                    py = lazy_pinyin(ch, style=py_style)
                    py_list.append(py[0].lower() if py else ch.lower())
                except (ValueError, TypeError, KeyError):
                    py_list.append(ch.lower())
        else:
            py_list = [ch.lower() for ch in chars]
        corrections = []
        result = []
        i = 0
        while i < len(chars):
            replaced = False
            for py_pattern, correct_text in sorted_entries:
                syllables = py_pattern.lower().split()
                n = len(syllables)
                if i + n > len(chars):
                    continue
                match = True
                for j in range(n):
                    key_syl = syllables[j]
                    text_syl = py_list[i + j]
                    if any(c.isdigit() for c in key_syl):
                        if key_syl != text_syl:
                            match = False
                            break
                    else:
                        text_clean = ''.join(c for c in text_syl if not c.isdigit())
                        if key_syl != text_clean:
                            match = False
                            break
                if not match:
                    continue
                sub = ''.join(chars[i:i + n])
                if sub != correct_text:
                    corrections.append((sub, correct_text))
                result.append(correct_text)
                i += n
                replaced = True
                break
            if not replaced:
                result.append(chars[i])
                i += 1
        corrected = ''.join(result)
        if corrections:
            print(f"    [PINYIN-DICT] {len(corrections)}处拼音纠正: {corrections[:5]}", flush=True)
        return corrected, corrections

    @staticmethod
    def _levenshtein(s1, s2):
        """Levenshtein编辑距离"""
        if len(s1) < len(s2):
            return RealtimeASRServer._levenshtein(s2, s1)
        if len(s2) == 0:
            return len(s1)
        prev = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            curr = [i + 1]
            for j, c2 in enumerate(s2):
                cost = 0 if c1 == c2 else 1
                curr.append(min(curr[-1] + 1, prev[j + 1] + 1, prev[j] + cost))
            prev = curr
        return prev[-1]

    @staticmethod
    def _match_english_kw(text, keyword):
        """英文/数字关键词后备匹配：标准化+子串+编辑距离"""
        def _norm(s):
            s = s.lower()
            s = s.replace('0', 'o').replace('1', 'i').replace('3', 'e').replace('4', 'a')
            return s

        kw_norm = _norm(keyword)
        if len(kw_norm) < 1:
            return None
        tokens = re.findall(r'[a-zA-Z0-9]+', text)
        best_score = 0
        best_token = None

        for token in tokens:
            tok_norm = _norm(token)
            if len(tok_norm) < 1:
                continue

            # 子串包含
            if kw_norm in tok_norm or tok_norm in kw_norm:
                score = min(len(kw_norm), len(tok_norm)) / max(len(kw_norm), len(tok_norm))
                if score > best_score:
                    best_score = score
                    best_token = token

            # 编辑距离（容错ASR音译错误）
            if abs(len(tok_norm) - len(kw_norm)) <= 3:
                dist = RealtimeASRServer._levenshtein(tok_norm, kw_norm)
                sim = 1 - dist / max(len(tok_norm), len(kw_norm))
                if sim > best_score:
                    best_score = sim
                    best_token = token

        if best_token and best_score >= RealtimeASRServer.ENGLISH_MATCH_THRESHOLD:
            return (best_token, best_score)
        return None

    @staticmethod
    def _dedup_overlap(prev_text, new_text):
        """去除相邻两段的重叠部分（新段包含旧段末尾的内容）"""
        if not prev_text or not new_text:
            return new_text

        # 找 prev_text 末尾和 new_text 开头的最长公共子串
        max_overlap = min(len(prev_text), len(new_text), 20)
        best_len = 0

        for overlap_len in range(max_overlap, 2, -1):
            suffix = prev_text[-overlap_len:]
            prefix = new_text[:overlap_len]
            if suffix == prefix:
                best_len = overlap_len
                break

        if best_len > 0:
            return new_text[best_len:].strip()

        # 模糊匹配：旧段末尾几个词是否在新段开头出现
        prev_tail = prev_text[-15:] if len(prev_text) >= 15 else prev_text
        if len(prev_tail) >= 4 and prev_tail in new_text[:len(new_text)//2]:
            idx = new_text.find(prev_tail)
            return new_text[idx + len(prev_tail):].strip()

        return new_text

    @staticmethod
    def _dedup_chars(text):
        """移除流式ASR产生的字符级重复幻觉（如 那那→那、现现在→现在、落落地地→落地）。
        仅在重复密度 >15% 时触发，避免误删正常的叠词（慢慢、常常、高高兴兴等）。"""
        if not text or len(text) < 3:
            return text

        chinese = re.findall(r'[\u4e00-\u9fff]', text)
        if len(chinese) < 4:
            return text

        dup_count = 0
        for i in range(len(text) - 1):
            if text[i] == text[i+1] and '\u4e00' <= text[i] <= '\u9fff':
                dup_count += 1

        dup_ratio = dup_count / len(chinese)
        if dup_ratio < 0.15 or dup_count < 3:
            return text

        result = []
        i = 0
        while i < len(text):
            if i + 1 < len(text) and text[i] == text[i+1] and '\u4e00' <= text[i] <= '\u9fff':
                result.append(text[i])
                i += 2
            else:
                result.append(text[i])
                i += 1

        deduped = ''.join(result)
        if deduped != text:
            print(f"    [DEDUP] '{text[:40]}' → '{deduped[:40]}'", flush=True)
        return deduped

    async def _detect_speaker(self, audio_data):
        """
        说话人识别 — 使用 CAM++ 声纹嵌入 (达摩院 3D-Speaker)
        CAM++ 在 200k 中文说话人 + VoxCeleb 英文数据集联合训练
        输出 192 维归一化向量，余弦相似度区分力远超 resemblyzer
        同一个人：余弦相似度 ≈ 0.60–0.95
        不同人：  余弦相似度 ≈ 0.05–0.30

        v2.9 改进：越用越灵敏
        - 灰色地带(0.30-0.60)：软更新声纹，不再浪费数据
        - 新人冷启动：3次确认 + 保存所有原始embedding，确认后取均值
        - 短句降至0.5s也跑声纹
        """
        MIN_DURATION = int(16000 * 0.5)
        if len(audio_data) < MIN_DURATION:
            audio_data = np.pad(audio_data, (0, MIN_DURATION - len(audio_data)))

        if self.sv_pipeline is None:
            if not self.speaker_profiles:
                self.speaker_profiles.append({
                    'embedding': np.zeros(192, dtype=np.float32),
                    'count': 1, 'label': 'Speaker0', 'quality': 0.0,
                })
            return 'Speaker0'

        timestamp = int(time.time() * 1000000)
        temp_path = TEMP_DIR / f'sp_{timestamp}.wav'
        sf.write(str(temp_path), audio_data.astype(np.float32), 16000)

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            self.executor,
            lambda: self.sv_pipeline([str(temp_path), str(temp_path)], output_emb=True))

        if temp_path.exists():
            temp_path.unlink()

        embedding = np.array(result['embs'][0])
        embedding = embedding / (np.linalg.norm(embedding) + 1e-8)

        if not self.speaker_profiles:
            self.speaker_profiles.append({
                'embedding': embedding.copy(),
                'count': 1,
                'label': 'Speaker0',
                'quality': 1.0,
            })
            print(f"[SPEAKER] 创建 Speaker0 (count=1)", flush=True)
            return 'Speaker0'

        SAME_THRESHOLD = 0.60
        NEW_THRESHOLD = 0.30
        REQUIRED_CONFIRMATIONS = 3

        best_score = -1.0
        best_idx = -1

        for i, profile in enumerate(self.speaker_profiles):
            score = float(np.dot(profile['embedding'], embedding))
            if score > best_score:
                best_score = score
                best_idx = i

        if best_score >= SAME_THRESHOLD:
            self._reset_pending_speaker()
            profile = self.speaker_profiles[best_idx]
            profile['embedding'] = (profile['embedding'] * profile['count'] + embedding) / (profile['count'] + 1)
            profile['count'] += 1
            profile['quality'] = min(1.0, profile['count'] / 30.0)
            if profile['count'] % 20 == 0:
                print(f"[SPEAKER] {profile['label']} 声纹成熟度: {profile['count']}样本 (quality={profile['quality']:.2f})", flush=True)
            return profile['label']

        if best_score < NEW_THRESHOLD:
            if not hasattr(self, '_pending_new') or self._pending_new is None:
                self._pending_new = {'count': 1, 'embeddings': [embedding.copy()]}
                print(f"[SPEAKER] 候选新人(1/{REQUIRED_CONFIRMATIONS}) score={best_score:.3f}", flush=True)
            else:
                self._pending_new['count'] += 1
                self._pending_new['embeddings'].append(embedding.copy())
                if self._pending_new['count'] >= REQUIRED_CONFIRMATIONS:
                    emb_list = self._pending_new['embeddings']
                    avg_emb = np.mean(emb_list, axis=0)
                    avg_emb = avg_emb / (np.linalg.norm(avg_emb) + 1e-8)
                    self.last_speaker_id += 1
                    label = f'Speaker{self.last_speaker_id}'
                    self.speaker_profiles.append({
                        'embedding': avg_emb,
                        'count': len(emb_list),
                        'label': label,
                        'quality': 0.1,
                    })
                    self._pending_new = None
                    print(f"[SPEAKER] 新角色确认: {label} (来自{len(emb_list)}个样本均值)", flush=True)
                    return label
                else:
                    print(f"[SPEAKER] 候选新人({self._pending_new['count']}/{REQUIRED_CONFIRMATIONS}) score={best_score:.3f}", flush=True)
            return self.speaker_profiles[best_idx]['label']

        # 灰色地带 (0.30 ~ 0.60)：软更新，不浪费数据
        # 相似度越高，更新权重越大
        weight = (best_score - NEW_THRESHOLD) / (SAME_THRESHOLD - NEW_THRESHOLD)
        weight = weight * 0.5  # 最大0.5的权重，防止污染
        profile = self.speaker_profiles[best_idx]
        total_weight = profile['count'] + weight
        profile['embedding'] = (profile['embedding'] * profile['count'] + embedding * weight) / total_weight
        profile['count'] += weight
        print(f"[SPEAKER] 灰色软更新 {profile['label']} score={best_score:.3f} weight={weight:.2f} count={profile['count']:.1f}", flush=True)
        self._reset_pending_speaker()
        return profile['label']

    def _reset_pending_speaker(self):
        if hasattr(self, '_pending_new'):
            self._pending_new = None

    def _is_music_like(self, audio_data):
        """检测音频是否更像音乐/噪声而非语音。
        语音有交替的高低能量（字间停顿），音乐/噪声能量更连续均匀。
        返回 True 表示疑似音乐/噪声。"""
        frame_len = int(16000 * 0.03)
        hop_len = int(16000 * 0.01)
        n_frames = max(1, (len(audio_data) - frame_len) // hop_len + 1)
        n_frames = min(n_frames, 100)

        energies = []
        for i in range(n_frames):
            start = i * hop_len
            frame = audio_data[start:start + frame_len]
            energies.append(np.sqrt(np.mean(frame ** 2) + 1e-12))

        energies = np.array(energies)
        if np.mean(energies) < self.MUSIC_ENERGY_EPSILON:
            return True

        cv = np.std(energies) / np.mean(energies)
        return cv < self.MUSIC_ZCR_THRESHOLD

    def _generate_comprehensive_report(self):
        """生成四板块结构化报告：正文 + OCR记录 + 关键词 + 技术附录"""
        lines = []

        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # ═══ 标题 ═══
        title = "实时语音识别报告"
        if self._loaded_topics:
            topic_names = ', '.join(sorted(self._loaded_topics))
            title += f" [{topic_names}]"
        lines.append(f"# {title}")
        lines.append(f"")
        lines.append(f"**生成时间**: {timestamp}")
        lines.append(f"**总时长**: {self.total_audio_seconds:.1f}秒")
        lines.append(f"**识别模型**: {self.asr_engine.model_name}")
        lines.append(f"**说话人数量**: {len(self.speaker_profiles)}")
        for sp in self.speaker_profiles:
            sp_count = sp.get('count', 0)
            sp_quality = sp.get('quality', 0)
            sp_label = sp.get('label', '?')
            lines.append(f"  - {sp_label}: {sp_count:.0f}个声纹样本 (成熟度={sp_quality:.0%})")
        lines.append(f"**识别句数**: {len(self.segments)}")
        if self._page_type == 'live':
            lines.append(f"**录制起点**: T0 = {timestamp}")
        lines.append(f"")
        lines.append("---")
        lines.append("")

        # ═══ 板块一：对话正文 ═══
        lines.append("## 一、对话正文")
        lines.append("")
        sp_map = {}
        for profile in self.speaker_profiles:
            sp_map[profile['label']] = profile.get('alias', profile['label'])
        current_speaker = None
        for i, seg in enumerate(self.segments):
            sp = seg.get('speaker', 'Speaker0')
            name = sp_map.get(sp, sp)
            seg_time = seg.get('time', 0)
            seg_dur = seg.get('duration', 0)
            vad = seg.get('vad', {})
            forced = '[强切]' if vad.get('forced') else ''
            kw_fixed = '[KW]' if seg.get('ocr_corrected') else ''

            if sp != current_speaker:
                lines.append(f"")
                lines.append(f"### {name}")
                current_speaker = sp

            if self._page_type == 'video':
                abs_sec = seg_time + self._video_offset
                time_prefix = f'`<span class="asr-ts" data-sec="{abs_sec:.2f}">[{self._fmt_time(seg_time)}]</span>`'
            else:
                time_prefix = f"`[{self._fmt_time(seg_time)}]`"
            annotations = ' '.join(filter(None, [forced, kw_fixed]))
            text = seg['text']
            if self.correction_log:
                for cw in sorted(self.correction_log, key=len, reverse=True):
                    if cw in text:
                        text = text.replace(cw, f'**{cw}**')
            if annotations:
                lines.append(f"- {time_prefix} {annotations} {text}  *({annotations})*")
            else:
                lines.append(f"- {time_prefix} {text}")

        lines.append("")
        lines.append("---")
        lines.append("")

        # ═══ 板块二：手动添加关键词 ═══
        lines.append("## 二、手动添加关键词")
        lines.append("")
        if self.keyword_history:
            for kw in self.keyword_history:
                lines.append(f"- `[{kw.get('time', '')}]` {kw.get('keyword', '')}")
        else:
            lines.append("*(无手动关键词)*")
        lines.append("")

        lines.append("---")
        lines.append("")

        # ═══ 板块三：关键词纠正明细 ═══
        lines.append("## 三、关键词纠正明细")
        lines.append("")
        if self.correction_records:
            kw_records = [r for r in self.correction_records if len(r) == 2]
            accent_records = [r for r in self.correction_records if len(r) == 4]

            if kw_records:
                lines.append("### 🔤 关键词/术语纠正 (拼音相似度)")
                lines.append("")
                lines.append("| # | 原始输出 | 纠正为 |")
                lines.append("|---|----------|--------|")
                seen = set()
                idx = 0
                for orig, kw in kw_records:
                    pk = (orig, kw)
                    if pk in seen: continue
                    seen.add(pk); idx += 1
                    lines.append(f"| {idx} | `{orig}` | **{kw}** |")
                lines.append("")
                lines.append(f"*共 {len(kw_records)} 处纠正，{len(seen)} 个不同词对*")
                lines.append("")

            if accent_records:
                lines.append("### 🗣 口音纠正 (方言特征)")
                lines.append("")
                lines.append("| # | 原文 | 纠正为 | 特征 |")
                lines.append("|---|------|--------|------|")
                seen = set()
                idx = 0
                for _, old, new, desc in accent_records:
                    pk = (old, new, desc)
                    if pk in seen: continue
                    seen.add(pk); idx += 1
                    lines.append(f"| {idx} | `{old}` | **{new}** | {desc} |")
                lines.append("")
                lines.append(f"*共 {len(accent_records)} 处纠正，{len(seen)} 个不同词对*")
                lines.append("")

            total_seen = len(set(
                (r[1], r[2]) if len(r) == 4 else (r[0], r[1]) for r in self.correction_records
            ))
            lines.append(f"*总计 {len(self.correction_records)} 处纠正，{total_seen} 个不同词对*")
        else:
            lines.append("*(本次未触发任何关键词纠正)*")
            lines.append("")
            lines.append("> 💡 提示：如果面板中已加载了大量关键词但此处无纠正记录，")
            lines.append("> 说明 ASR 直接正确识别了这些词，无需纠正。这是理想情况！")
        lines.append("")

        lines.append("---")
        lines.append("")

        # ═══ 板块四：技术附录 ═══
        lines.append("## 四、技术附录")
        lines.append("")
        lines.append("### VAD 语音活动检测")
        lines.append("")
        lines.append("| 参数 | 值 | 说明 |")
        lines.append("|------|----|------|")
        lines.append("| 静音断句阈值 | 1.35秒 | 连续静音超过此时间则断句，自适应语速动态调整 |")
        lines.append("| 强制切分时长 | 3.9秒 | 缓冲区无静音时最大等待时长，切出3.8秒 |")
        lines.append("| 前后重叠保留 | 1.5秒 | 切分时保留末尾音频到下一段保证上下文连续 |")
        lines.append("| 能量阈值倍数 | 2.0x | 以帧能量中位数的倍数区分语音/静音 |")
        lines.append(f"| 最小语音段 | {self.min_speech_duration:.02f}秒 | 低于此时长的语音片段被丢弃 |")
        lines.append("| 帧长度 | 30ms | 短时傅里叶分析窗口 |")
        lines.append("| 帧步长 | 10ms | 帧滑动步长 |")
        lines.append("")
        lines.append("### 说话人分离")
        lines.append("")
        lines.append("| 参数 | 值 | 说明 |")
        lines.append("|------|----|------|")
        lines.append("| 声纹方案 | CAM++ (3D-Speaker) | 192维归一化声纹嵌入，200k中文+VoxCeleb英文联合训练 |")
        lines.append("| 同人阈值(SAME) | ≥0.60 余弦相似度 | 高于此值判定为同一说话人，加权移动平均更新声纹 |")
        lines.append("| 新人阈值(NEW) | <0.30 余弦相似度 | 低于此值候选为新说话人 |")
        lines.append("| 灰色地带 | 0.30~0.60 | v2.9：软更新声纹，不浪费数据 |")
        lines.append("| 确认次数 | 连续3句 | v2.9：需连续3句均低于阈值才创建新角色 |")
        lines.append("| 新人冷启动 | 3样本均值 | v2.9：保存所有候选embedding，确认后取均值 |")
        lines.append("| 短音频跳过 | <0.5秒 | v2.9：降低阈值1.5s→0.5s，更多短句参与声纹积累 |")
        lines.append("| 多句共享 | ✅ | 同一ASR输出的多句子句共享说话人标签 |")
        lines.append("")
        lines.append("### 断句规则")
        lines.append("")
        lines.append("- **中文断句符**: `。！？；` （不含逗号，逗号为句内停顿）")
        lines.append("- **英文断句符**: `. ! ? ;`")
        lines.append("- **VAD优先**: 优先用静音检测做物理断句，物理断句后不再做标点拆分")
        lines.append("- **多句合并**: 同一音频块内多句共享VAD时间戳和说话人标签")
        lines.append("")
        lines.append("### 降噪与纠错")
        lines.append("")
        lines.append("| 机制 | 说明 |")
        lines.append("|------|------|")
        lines.append("| 拼音纠错 | 内置同音词/近音词映射表 |")
        lines.append("| 关键词辅助纠错 | 中文≥90%拼音相似(含近音)，英文≥70%相似度才触发替换 |")
        lines.append("| 口音矫正 | 根据说话人籍贯方言特征自动纠正ASR错字 |")
        lines.append("| 音乐/噪声过滤 | 能量变异系数<0.25且ASR产出<4字→丢弃，避免音乐/背景音被转录 |")
        lines.append("| 去重 | 跨句重复文本自动过滤 |")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(f"*报告由在线实时语音识别系统于 {timestamp} 自动生成*")

        return '\n'.join(lines)

    def _generate_structured_log(self):
        """生成结构化JSON日志，适合发给AI进行纠错分析"""
        sp_map = {}
        for profile in self.speaker_profiles:
            sp_map[profile['label']] = profile.get('alias', profile['label'])

        segments = []
        for i, seg in enumerate(self.segments):
            t = seg.get('time', 0)
            abs_t = t + self._video_offset
            segments.append({
                'seq': i,
                'time': round(abs_t, 3),
                'time_str': self._log_fmt_time(abs_t),
                'asr_time': round(t, 3),
                'duration': round(seg.get('duration', 0), 3),
                'speaker': seg.get('speaker', 'Speaker0'),
                'speaker_name': sp_map.get(seg.get('speaker', ''), seg.get('speaker', 'Speaker0')),
                'text': seg['text'],
                'vad_forced': seg.get('vad', {}).get('forced', False),
                'ocr_corrected': seg.get('ocr_corrected', False),
            })

        kw_records = [r for r in self.correction_records if len(r) == 2]
        accent_records = [r for r in self.correction_records if len(r) == 4]

        return json.dumps(dict(
            generated_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            title='实时语音识别日志',
            page_type=self._page_type,
            video_offset_seconds=round(self._video_offset, 1),
            topics=sorted(list(self._loaded_topics)),
            model=self.asr_engine.model_name if self.asr_engine else 'unknown',
            duration_seconds=round(self.total_audio_seconds, 1),
            total_segments=len(self.segments),
            speakers=sp_map,
            keywords_added=list(self.keyword_history),
            keyword_corrections=[dict(original=r[0], corrected=r[1]) for r in kw_records],
            accent_corrections=[dict(original=r[1], corrected=r[2], feature=r[3]) for r in accent_records],
            segments=segments,
        ), ensure_ascii=False, indent=2)

    @staticmethod
    def _log_fmt_time(sec):
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = sec % 60
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:05.2f}"
        return f"{m:02d}:{s:05.2f}"

    def _fmt_time(self, sec):
        if self._page_type == 'live':
            m = int(sec // 60)
            s = sec % 60
            if m > 0:
                return f"T0+{m:02d}:{s:05.2f}"
            return f"T0+{s:05.2f}"
        abs_sec = sec + self._video_offset
        return self._log_fmt_time(abs_sec)

    def _text_similarity(self, text1, text2):
        """计算两段文本的字符/拼音重叠度，判断是否为同一句话被ASR不同转写"""
        t1 = re.sub(r'[^\u4e00-\u9fff]', '', text1)
        t2 = re.sub(r'[^\u4e00-\u9fff]', '', text2)
        if not t1 or not t2:
            return 0.0
        if len(t1) < 2 or len(t2) < 2:
            return 0.0
        chars1, chars2 = set(t1), set(t2)
        char_overlap = len(chars1 & chars2) / max(len(chars1), len(chars2))
        if lazy_pinyin is not None:
            py1 = lazy_pinyin(t1, style=Style.NORMAL)
            py2 = lazy_pinyin(t2, style=Style.NORMAL)
            py_set1, py_set2 = set(py1), set(py2)
            py_overlap = len(py_set1 & py_set2) / max(len(py_set1), len(py_set2)) if py_set1 and py_set2 else 0
        else:
            py_overlap = 0
        return max(char_overlap, py_overlap)

    def _merge_segments(self):
        """合并相邻同speaker且间隔极短的片段（VAD误切修复，含拼音相似去重）"""
        if len(self.segments) < 2:
            return
        merged = []
        for seg in self.segments:
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
                    sim = self._text_similarity(prev['text'], seg['text'])
                    if sim > 0.5:
                        prev['text'] = seg['text'] if len(seg['text']) > len(prev['text']) else prev['text']
                    else:
                        prev['text'] = prev['text'].rstrip() + ' ' + seg['text']
                    prev['duration'] = seg_time + seg.get('duration', 0) - prev_time
                    prev['corrections'] = prev.get('corrections', []) + seg.get('corrections', [])
                    continue
            merged.append(dict(seg))
        self.segments = merged

    async def generate_and_send_report(self, websocket):
        self._merge_segments()
        report = self._generate_comprehensive_report()
        await self._send_to(websocket, {'type': 'report', 'content': report})

    def _resolve_speaker_name(self, profile, index):
        label = profile.get('label', f'Speaker{index}')
        alias = profile.get('alias')
        if alias:
            return alias
        entry = sp_manager.library.lookup_any(label)
        if entry:
            return entry.get('name', entry.get('platform_id', label))
        if index == 0 and self._page_creator:
            return f'主播_{self._page_creator}'
        return label

    def _load_saved_voice_profiles(self):
        """启动时加载历史保存的声纹向量作为初始 speaker_profiles。
        扫描 dict/voiceprints/ 下所有 metadata.json，加载最近一次会话的声纹。"""
        import glob as _glob
        meta_files = sorted(
            _glob.glob(str(self._voiceprint_dir / '*' / 'metadata.json')),
            reverse=True
        )
        if not meta_files:
            return

        latest_dir = Path(meta_files[0]).parent
        print(f"[VOICEPRINT] 加载历史声纹: {latest_dir.name}", flush=True)

        loaded_count = 0
        for npy_path in sorted(latest_dir.glob('*.npy')):
            name = npy_path.stem
            try:
                emb = np.load(str(npy_path))
                emb = emb / (np.linalg.norm(emb) + 1e-8)
            except Exception as e:
                print(f"[VOICEPRINT] 加载失败 {npy_path.name}: {e}", flush=True)
                continue

            self.speaker_profiles.append({
                'embedding': emb.copy(),
                'count': 15.0,
                'label': f'Speaker{self.last_speaker_id}',
                'quality': 0.5,
                'loaded_from': name,
            })
            self.last_speaker_id += 1
            loaded_count += 1

            if name.startswith('主播_'):
                self._host_speaker_label = f'Speaker{self.last_speaker_id - 1}'

        if loaded_count:
            print(f"[VOICEPRINT] 加载 {loaded_count} 个历史声纹", flush=True)
            if self._host_speaker_label:
                print(f"[VOICEPRINT] 主播标记: {self._host_speaker_label}", flush=True)

    def _save_voice_profiles(self):
        """保存本次会话积累的声纹向量。仅录音>=30分钟时保存。"""
        if self.total_audio_seconds < 1800:
            if self.speaker_profiles:
                profiles_with_data = [p for p in self.speaker_profiles if p.get('count', 0) >= 5]
                if profiles_with_data:
                    print(f"[VOICEPRINT] 录音时长仅{self.total_audio_seconds:.0f}s，不足30分钟，跳过保存", flush=True)
            return None

        if not self.speaker_profiles:
            return None

        session_dir = self._voiceprint_dir / datetime.now().strftime('%Y%m%d_%H%M%S')
        session_dir.mkdir(exist_ok=True)

        results = []

        for i, profile in enumerate(self.speaker_profiles):
            count = profile.get('count', 0)
            if count < 5:
                continue

            embedding = profile['embedding']
            label = profile.get('label', f'Speaker{i}')
            best_name = self._resolve_speaker_name(profile, i)

            npy_path = session_dir / f'{best_name}.npy'
            np.save(str(npy_path), embedding)

            results.append({
                'original_label': label,
                'saved_name': best_name,
                'samples': int(count),
                'quality': round(profile.get('quality', 0), 2),
                'file': str(npy_path.name),
            })

        if not results:
            return None

        meta = {
            'session_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'total_audio_seconds': self.total_audio_seconds,
            'page_creator': self._page_creator,
            'page_platform': self._page_platform,
            'total_speakers': len(self.speaker_profiles),
            'saved': len(results),
            'profiles': results,
        }
        meta_path = session_dir / 'metadata.json'
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        print(f"[VOICEPRINT] 保存 {len(results)}/{len(self.speaker_profiles)} 个声纹到 {session_dir.name}", flush=True)
        for r in results:
            print(f"  {r['original_label']} → {r['saved_name']} ({r['samples']}样本, quality={r['quality']})", flush=True)

        return results

    async def _send_to(self, websocket, message):
        try:
            await websocket.send(json.dumps(message, ensure_ascii=False))
        except Exception as e:
            print(f"[WS] Send failed: {e}")
            self._clients.discard(websocket)

    async def send(self, message):
        for ws in list(self._clients):
            await self._send_to(ws, message)

    async def start(self):
        page = STATUS_PAGE.replace("{host}", self.host).replace("{port}", str(self.port))
        async def process_request(connection, request):
            if request.headers.get("Upgrade", "").lower().strip() == "websocket":
                return None
            h = Headers()
            h['Content-Type'] = 'text/html; charset=utf-8'
            h['Connection'] = 'close'
            return Response(200, "OK", h, page.encode("utf-8"))

        print(f"\n[WS] WebSocket server: ws://{self.host}:{self.port}", flush=True)
        print(f"[WS] Status page:     http://{self.host}:{self.port}", flush=True)
        async with websockets.serve(
            self.handler, self.host, self.port,
            ping_interval=20, ping_timeout=60, close_timeout=10,
            max_size=2**24,
            process_request=process_request,
        ):
            print("[WS] Service ready", flush=True)
            await asyncio.Future()


_global_server = None

def run_server(asr_engine, correction_manager, host='localhost', port=8765):
    global _global_server
    server = RealtimeASRServer(asr_engine, correction_manager, host, port)
    _global_server = server
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        print("\n[WS] Stopped")
    except Exception as e:
        print(f"\n[WS] Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        _global_server = None
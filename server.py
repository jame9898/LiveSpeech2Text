# -*- coding: utf-8 -*-
"""
在线实时语音识别系统 - WebSocket Server
VAD断句 + KW关键词纠错 + 说话人分离 (CAM++)
"""

STATUS_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LiveSpeech2Text V1.0</title>
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
#transcripts { position:relative; background: #fff; border: 1px solid #d0d7de; border-radius: 8px; padding: 14px; min-height: 280px; max-height: 65vh; overflow-y: auto; font-size: 14px; line-height: 1.9; }
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
.page-info input:focus { border-color: #0969da; }
.toast { position: fixed; bottom: 24px; right: 24px; padding: 10px 18px; border-radius: 8px; color: #1f2328; font-size: 13px; z-index: 99999; animation: toastIn .3s ease; pointer-events: none; box-shadow: 0 4px 16px rgba(0,0,0,.12); max-width: 420px; }
.toast.ok { background: #dafbe1; border: 1px solid #1a7f37; color: #1a7f37; }
.toast.err { background: #ffebe9; border: 1px solid #cf222e; color: #cf222e; }
.toast.loading { background: #ddf4ff; border: 1px solid #0969da; color: #0969da; }
@keyframes toastIn { from { opacity:0; transform:translateY(12px) } to { opacity:1; transform:translateY(0) } }
.speaker-tag { display: inline-block; margin: 1px 3px 1px 0; padding: 1px 7px; border-radius: 3px; font-size: 11px; font-weight: 700; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
#partialArea { display:none; position:absolute; top:0; left:0; right:0; z-index:10; padding:6px 10px; font-size:14px; color:#656d76; font-style:italic; line-height:1.6; background:rgba(255,255,255,.92); border-bottom:1px solid #d0d7de; }
#partialArea .cursor { display: inline-block; width: 2px; height: 16px; background: #0969da; margin-left: 2px; vertical-align: text-bottom; animation: blink 0.8s infinite; }
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }

</style>
</head>
<body>
<h1>LiveSpeech2Text V1.0</h1>
<p class="sub">WebSocket ws://{host}:{port} &mdash; 无需插件，独立控制</p>

<div class="status-wrap">
    <span id="connStatus" class="status-badge offline">未连接</span>
    <span id="recStatus" class="status-badge ready">准备就绪</span>
    <span id="modelInfo" class="status-badge model" style="display:none"></span>
</div>

<div class="page-info" style="display:flex;gap:8px;align-items:center;margin-bottom:10px;flex-wrap:wrap">
    <input id="pageUrl" placeholder="视频/直播页面URL（选填）" style="flex:1;min-width:200px;border:1px solid #d0d7de;border-radius:5px;padding:5px 10px;font-size:12px;background:#fff;color:#1f2328;outline:none">
    <input id="pageCreator" placeholder="UP主/创作者名（选填）" style="width:160px;border:1px solid #d0d7de;border-radius:5px;padding:5px 10px;font-size:12px;background:#fff;color:#1f2328;outline:none">
    <span id="pagePlatform" style="font-size:11px;color:#656d76;white-space:nowrap"></span>
</div>

<div class="ctrl-bar">
    <button id="btnStart" class="btn primary">▶ 标签页</button>
    <button id="btnStartFull" class="btn" style="background:#58a6ff;border-color:#58a6ff;color:#fff">▶ 全屏</button>
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

<div id="transcripts"><div id="partialArea"></div><em style="color:#656d76">等待识别结果...</em></div>

<div class="stats">
    时长: <b id="statDur">0.0</b>秒 &nbsp;|&nbsp; 句数: <b id="statCnt">0</b>条 &nbsp;|&nbsp; 字数: <b id="statChar">0</b>字
</div>

<script>
(function() {
var CONN = document.getElementById('connStatus');
var REC = document.getElementById('recStatus');
var MODEL = document.getElementById('modelInfo');
var BOX = document.getElementById('transcripts');
var KWBOX = document.getElementById('keywordsBox');
var BTN_START = document.getElementById('btnStart');
var BTN_START_FULL = document.getElementById('btnStartFull');
var BTN_STOP = document.getElementById('btnStop');
var PARTIAL = document.getElementById('partialArea');
var STAT_DUR = document.getElementById('statDur');
var STAT_CNT = document.getElementById('statCnt');
var STAT_CHAR = document.getElementById('statChar');

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

var pageUrl = document.getElementById('pageUrl');
var pageCreator = document.getElementById('pageCreator');
var pagePlatform = document.getElementById('pagePlatform');
var kwInputEl = document.getElementById('kwInput');

var SP_COLORS = [
    {bg:'rgba(88,166,255,.12)',border:'#58a6ff',name:'#58a6ff'},
    {bg:'rgba(248,81,73,.12)',border:'#f85149',name:'#f85149'},
    {bg:'rgba(63,185,80,.12)',border:'#3fb950',name:'#3fb950'},
    {bg:'rgba(210,153,29,.12)',border:'#d2991d',name:'#d2991d'},
    {bg:'rgba(163,113,247,.12)',border:'#a371f7',name:'#a371f7'},
    {bg:'rgba(19,194,194,.12)',border:'#13c2c2',name:'#13c2c2'},
    {bg:'rgba(235,47,150,.12)',border:'#eb2f96',name:'#eb2f96'},
    {bg:'rgba(250,84,28,.12)',border:'#fa541c',name:'#fa541c'}
];
var speakerColors = {};

function setConn(cls, text) {
    CONN.className = 'status-badge ' + cls;
    CONN.textContent = text;
}

function setRec(cls, text) {
    REC.className = 'status-badge ' + cls;
    REC.textContent = text;
}

function toast(msg, type, duration) {
    if (duration === undefined) duration = 3000;
    var t = document.createElement('div');
    t.className = 'toast ' + (type || '');
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(function() { t.remove(); }, duration);
}

function connect() {
    console.log('[ASR] 开始连接 WebSocket: ws://' + location.host);
    setConn('connecting', '连接中...');
    try {
        ws = new WebSocket('ws://' + location.host);
        ws.binaryType = 'arraybuffer';
        ws.onopen = function() {
            console.log('[ASR] WebSocket 已连接');
            setConn('online', '已连接');
            reconnectAttempts = 0;
            if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
        };
        ws.onclose = function(e) {
            console.log('[ASR] WebSocket 断开, code=' + (e.code||'?') + ' reason=' + (e.reason||''));
            setConn('offline', '断开(' + (e.code||'?') + ')，5秒后重连');
            ws = null;
            if (isRecording) { cleanupAudio(); isRecording = false; updateBtns(); }
            if (!reconnectTimer) {
                var d = Math.min(2000 * Math.pow(1.5, reconnectAttempts), 30000);
                reconnectAttempts++;
                reconnectTimer = setTimeout(connect, d);
            }
        };
        ws.onerror = function(e) {
            console.log('[ASR] WebSocket 连接错误');
            setConn('offline', '连接失败');
            if (ws) { ws.close(); ws = null; }
        };
        ws.onmessage = function(e) {
            try { handleMsg(JSON.parse(e.data)); } catch(err) { console.log('[ASR] 消息解析错误:', err); }
        };
        console.log('[ASR] WebSocket 对象已创建, readyState=' + ws.readyState);
    } catch(err) {
        console.log('[ASR] WebSocket 创建失败:', err);
        setConn('offline', '连接失败');
        var d = Math.min(2000 * Math.pow(1.5, reconnectAttempts), 30000);
        reconnectAttempts++;
        if (!reconnectTimer) reconnectTimer = setTimeout(connect, d);
    }
}

function send(d) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(d)); }

function parsePageInfo() {
    var url = (pageUrl.value || '').trim();
    var creator = (pageCreator.value || '').trim();
    var platform = 'web';
    var pageType = 'web';
    if (url) {
        if (url.indexOf('bilibili.com/video/') !== -1 || url.indexOf('bilibili.com/bangumi/') !== -1) {
            platform = 'bilibili'; pageType = 'video';
        } else if (url.indexOf('live.bilibili.com') !== -1) {
            platform = 'bilibili'; pageType = 'live';
        } else if (url.indexOf('douyu.com/') !== -1 && url.indexOf('douyu.com/directory') === -1) {
            platform = 'douyu'; pageType = 'live';
        } else if (url.indexOf('huya.com/') !== -1 && /\\d/.test(url)) {
            platform = 'huya'; pageType = 'live';
        } else if (url.indexOf('youtube.com/watch') !== -1) {
            platform = 'youtube'; pageType = 'video';
        }
    }
    return {url: url, creator: creator, platform: platform, pageType: pageType};
}

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
                isRecording = false;
                updateBtns();
                setRec('ready', '准备就绪');
            }
            break;
        case 'transcription':
            addSeg(d); updateStats(d);
            if (d.keywords) updateKeywords(d.keywords);
            break;
        case 'partial':
            PARTIAL.style.display = 'block';
            PARTIAL.innerHTML = '<span style="color:#656d76;font-style:italic;">' + eHtml(d.text) + '</span><span class="cursor"></span>';
            break;
        case 'keywords_updated':
            if (d.keyword_store) keywordStore = d.keyword_store;
            if (d.keywords) updateKeywords(d.keywords);
            break;
        case 'report': showReport(d.content); break;
        case 'save_report': download(d.content, d.filename||'asr_report.md', 'text/markdown;charset=utf-8'); break;
        case 'save_log': download(d.content, d.filename||'asr_log.json', 'application/json;charset=utf-8'); break;
        case 'speaker_profile_matched':
            toast('✅ "' + d.keyword + '" → 画像库命中', 'ok', 4000);
            break;
        case 'page_creator':
            if (d.creator && !pageCreator.value) pageCreator.value = d.creator;
            if (d.platform) pagePlatform.textContent = '平台: ' + d.platform + ' (来自其他端)';
            break;
        case 'toast':
            toast(d.text, d.ok ? 'ok' : 'err', d.ms || 3000);
            break;
        case 'keyword_added':
            if (d.keyword && d.category) {
                if (!keywordStore[d.category]) keywordStore[d.category] = [];
                if (!keywordStore[d.category].includes(d.keyword)) keywordStore[d.category].push(d.keyword);
                toast('✅ 自动添加 "' + d.keyword + '" (' + (d.category==='speaker'?'主讲人':'关键词') + ')', 'ok', 4000);
            }
            break;
        case 'error': alert('错误: ' + d.message); break;
    }
}

function eHtml(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

function addSeg(d) {
    if (firstMsg) { BOX.innerHTML = ''; firstMsg = false; }
    PARTIAL.style.display = 'none'; PARTIAL.innerHTML = '';
    segCount++;
    if (BOX.children.length >= 200) BOX.removeChild(BOX.firstChild);

    var div = document.createElement('div');
    div.className = 'item';

    if (d.gap_audio > 1.5 && segCount > 1) {
        div.innerHTML += '<span class="gap-warn">⚠漏' + d.gap_audio.toFixed(1) + 's</span>';
    }
    if (d.kw_corrected) {
        div.innerHTML += '<span class="kw-fixed">[KW]</span>';
    }

    if (d.timestamp) {
        try {
            var dt = new Date(d.timestamp);
            div.innerHTML += '<span class="ts">' + String(dt.getHours()).padStart(2,'0') + ':' + String(dt.getMinutes()).padStart(2,'0') + ':' + String(dt.getSeconds()).padStart(2,'0') + '</span>';
        } catch(e) {
            var segTime = d.seg_time !== undefined ? d.seg_time : d.duration;
            if (segTime !== undefined && segTime !== null) {
                var m = Math.floor(segTime / 60), s = (segTime % 60).toFixed(1);
                div.innerHTML += '<span class="ts">T+' + (m>0?m+':'+(s<10?'0':'')+s:s+'s') + '</span>';
            }
        }
    }
    if (d.speaker) {
        var sp = d.speaker;
        if (!(sp in speakerColors)) {
            var m = sp.match(/\\d+/);
            speakerColors[sp] = m ? parseInt(m[0]) % SP_COLORS.length : 0;
        }
        var clr = SP_COLORS[speakerColors[sp]];
        div.innerHTML += '<span class="speaker-tag" style="background:' + clr.bg + ';border:1px solid ' + clr.border + ';color:' + clr.name + '">' + eHtml(sp) + '</span> ';
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
    segCount = 0; firstMsg = true; keywords = []; keywordStore = {}; speakerColors = {};
    BOX.innerHTML = '<em style="color:#656d76">等待识别结果...</em>';
    PARTIAL.style.display = 'none'; PARTIAL.innerHTML = '';
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
    BTN_START_FULL.disabled = isRecording;
    BTN_STOP.disabled = !isRecording;
}

async function doStartRec(mode) {
    if (!ws || ws.readyState !== 1) { alert('服务未连接！请确保服务已启动'); return; }

    var _info = parsePageInfo();
    if (_info.pageType === 'video') {
        if (!confirm('⚠️ 检测为视频页面\\n\\n请先将视频进度条拖回开头，然后点击"确定"继续录制。\\n\\n点击"取消"放弃录制。')) return;
    } else if (_info.pageType === 'live') {
        toast('📡 直播模式：将从当前时刻开始录制', 'loading', 3000);
    }

    try {
        var isTab = (mode === 'tab');
        var opts = isTab
            ? {audio: true, video: true, preferCurrentTab: true}
            : {audio: true, video: true};
        mediaStream = await navigator.mediaDevices.getDisplayMedia(opts);
        if (!mediaStream.getAudioTracks().length) {
            mediaStream.getTracks().forEach(function(t) { t.stop(); }); mediaStream = null;
            alert(isTab
                ? '标签页模式未获取到音频。\\n请在弹出的对话框中选择"Chrome标签页"，并确保该标签页正在播放音频。'
                : '未获取到音频轨道，请确保在分享对话框中勾选了"分享音频"。');
            return;
        }
        audioCtx = new AudioContext({sampleRate: 48000});
        var src = audioCtx.createMediaStreamSource(mediaStream);
        var proc = audioCtx.createScriptProcessor(8192, 1, 1);
        proc.onaudioprocess = function(e) {
            if (isRecording && ws && ws.readyState === 1) {
                ws.send(new Float32Array(e.inputBuffer.getChannelData(0)).buffer);
            }
        };
        src.connect(proc);
        proc.connect(audioCtx.destination);
        isRecording = true;
        send({type: 'start'});
        firstMsg = true;
        segCount = 0;
        updateBtns();
        setRec('recording', '识别中...');
        BOX.innerHTML = '<em style="color:#656d76">正在监听...</em>';

        setTimeout(function() {
            if (_info.creator) {
                send({type: 'page_creator', creator: _info.creator, platform: _info.platform, page_type: _info.pageType, video_offset: 0, url: _info.url});
                send({type: 'keyword_add', keyword: _info.creator, category: 'speaker'});
                toast('✅ 自动添加创作者: ' + _info.creator, 'ok', 4000);
            } else if (_info.platform !== 'web') {
                // 网页端无 creator，把 URL 发给服务端尝试自动提取 UP 主名
                send({type: 'page_creator', creator: '', platform: _info.platform, page_type: _info.pageType, video_offset: 0, url: _info.url});
            }
        }, 2000);
    } catch(e) {
        if (e.name !== 'AbortError') alert('屏幕共享失败: ' + (e.message || '用户取消'));
    }
}

function stopRec() {
    isRecording = false;
    send({type: 'stop'});
    if (mediaStream) { mediaStream.getTracks().forEach(function(t) { t.stop(); }); mediaStream = null; }
    if (audioCtx) { audioCtx.close(); audioCtx = null; }
    updateBtns();
    setRec('ready', '已停止');
}

function cleanupAudio() {
    if (mediaStream) { mediaStream.getTracks().forEach(function(t) { t.stop(); }); mediaStream = null; }
    if (audioCtx) { audioCtx.close(); audioCtx = null; }
}

BTN_START.addEventListener('click', function() { doStartRec('tab'); });
BTN_START_FULL.addEventListener('click', function() { doStartRec('full'); });

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


pageUrl.addEventListener('input', function() {
    var info = parsePageInfo();
    if (info.platform !== 'web') {
        pagePlatform.textContent = '平台: ' + info.platform + ' | 类型: ' + info.pageType;
    } else if (info.url) {
        pagePlatform.textContent = '未识别平台';
    } else {
        pagePlatform.textContent = '';
    }
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
import urllib.request
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from core import MODELS_DIR, DICT_DIR, silence_noisy_loggers
from keyword_expander import CATEGORIES, CATEGORY_ICONS
from speaker_profile import TOPIC_MANAGER
from speaker_manager import SpeakerManager
from text_utils import (
    extract_title_keywords,
    dedup_overlap, dedup_chars,
    normalize_letter_adjacent_numbers,
)
from pinyin_utils import PinyinCorrector
from correction_engine import CorrectionEngine
from vad_processor import VADProcessor
from report_generator import generate_comprehensive_report, generate_structured_log, merge_segments

logging.getLogger('websockets.server').setLevel(logging.CRITICAL)
logging.getLogger('websockets').setLevel(logging.CRITICAL)

TEMP_DIR = Path(__file__).parent / "temp"
TEMP_DIR.mkdir(exist_ok=True)


class RealtimeASRServer:

    def __init__(self, asr_engine, host='localhost', port=8765):
        self.asr_engine = asr_engine
        self.host = host
        self.port = port

        self.is_running = False
        self.client = None
        self.client_connected = False
        self.recording_ws = None
        self._current_handler_ws = None
        self._clients = set()
        threads = self.asr_engine._config.get("model_settings", {}).get("threads", 8)
        self.executor = ThreadPoolExecutor(max_workers=threads)

        self.full_text = ""
        self.segments = []
        self.keyword_store = {cat: set() for cat in CATEGORIES}
        self._session_new_keywords = set()  # 本会话手动添加的关键词(用于自动保存到画像库)

        self.pinyin_corrector = PinyinCorrector(
            keyword_store=self.keyword_store,
        )

        # 智能纠错引擎（实体识别、模糊匹配、语法检查、置信度评分）
        self.correction_engine = CorrectionEngine()

        # 说话人分离 (CAM++ 中英文通用声纹模型)
        print("[SPEAKER] Loading CAM++ speaker verification model...", flush=True)
        sv_pipeline = None
        try:
            silence_noisy_loggers()

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
                sv_pipeline = pipeline(
                    task=Tasks.speaker_verification,
                    model=cam_local,
                )
            else:
                sv_pipeline = pipeline(
                    task=Tasks.speaker_verification,
                    model=cam_model_id,
                    model_revision='v1.0.0'
                )
            print("[SPEAKER] CAM++ model loaded", flush=True)
        except Exception as e:
            print(f"[SPEAKER] CAM++ load failed: {e}", flush=True)
            print("[SPEAKER] Speaker diarization disabled, ASR will still work", flush=True)
            sv_pipeline = None

        DICT_DIR.mkdir(exist_ok=True)

        self.speaker_manager = SpeakerManager(
            sv_pipeline=sv_pipeline,
            executor=self.executor,
            dict_dir=DICT_DIR,
            temp_dir=TEMP_DIR,
        )

        # 音频缓冲区
        self._audio_buf = np.array([], dtype=np.float32)
        self.browser_sample_rate = 48000
        self.target_sample_rate = 16000
        self.max_buffer_seconds = 30
        self.max_buffer_size = 16000 * self.max_buffer_seconds
        self.vad_silence_threshold = self.asr_engine._config.get("model_settings", {}).get("vad_threshold", 0.85)

        self.vad_force_cut = self.asr_engine._config.get("model_settings", {}).get("vad_force_cut", True)
        self.vad_force_cut_sec = self.asr_engine._config.get("model_settings", {}).get("force_cut_sec", 3.8)
        self.min_speech_duration = self.asr_engine._config.get("model_settings", {}).get("min_speech_duration", 0.08)

        # 避免重复发送已识别的文本（上限防止长会话O(n²)退化）
        self.sent_texts = set()
        self._MAX_SENT_TEXTS = 300

        self.total_audio_seconds = 0
        self.speaker_manager.total_audio_seconds = 0
        self.transcription_count = 0
        self.last_segment_wall_time = 0
        self.last_segment_end_audio_time = 0

        self.keyword_history = []

        # 异步转录控制
        self.transcripts_in_flight = 0
        self.max_concurrent_transcripts = 2
        self.last_periodic_transcribe = 0
        self._partial_in_flight = False  # 防止CPU模式下partial堆积

        # 连接稳定性
        self.last_activity = time.time()

        print(f"[VAD] vad_force_cut={self.vad_force_cut}", flush=True)

        # 流式模式（伪流式：短chunk快速partial + 整句final修正）
        self._stream_seg_id = 0
        self._stream_last_partial = ""
        self._stream_partial_time = 0
        self._stream_partial_buf = []
        self._stream_partial_interval = 0.8
        self._stream_full_text = ""
        self._stream_last_corrected = ""

        self.vad_processor = VADProcessor(
            vad_silence_threshold=self.vad_silence_threshold,
            vad_force_cut=self.vad_force_cut,
            vad_force_cut_sec=self.vad_force_cut_sec,
            min_speech_duration=self.min_speech_duration,
            max_buffer_seconds=self.max_buffer_seconds,
        )

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
                self._audio_buf = np.array([], dtype=np.float32)
                self.keyword_store = {cat: set() for cat in CATEGORIES}
                self.pinyin_corrector.reset_session()
                self.correction_engine.reset_session()
                self.speaker_manager._session_active_speakers = set()
                self._session_new_keywords = set()
                self.sent_texts = set()
                self.speaker_manager.last_speaker_id = 0
                self.total_audio_seconds = 0
                self.speaker_manager.total_audio_seconds = 0
                self.transcription_count = 0
                self.transcripts_in_flight = 0
                self.last_periodic_transcribe = 0
                self.speaker_manager._pending_new = None
                self.speaker_manager._last_speaker_label = 'Speaker0'
                self.last_segment_wall_time = 0
                self.last_segment_end_audio_time = 0
                self.keyword_history = []
                self._stream_seg_id = 0
                self._stream_last_partial = ""
                self._stream_full_text = ""
                self._stream_last_corrected = ""
                self._stream_partial_time = 0
                self._stream_partial_buf = []
                self.speaker_manager._quick_recognized = False
                self.speaker_manager._quality_reported = False
                await self._send_to(websocket, {
                    'type': 'status', 'status': 'recording',
                    'message': 'Started', 'model': self.asr_engine.model_name,
                    'keywords': list(self.pinyin_corrector.kw_set)
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
                if len(self._audio_buf) > 16000:
                    await self.transcribe_buffer(self._audio_buf.copy())
                merge_segments(self.segments)
                await self._send_to(websocket, {
                    'type': 'status', 'status': 'stopped',
                    'message': 'Stopped', 'full_text': self.full_text.strip(),
                    'segments': self.segments
                })

                print("[WS] Recording stopped")
                for client in list(self._clients):
                    if client is not websocket:
                        try:
                            await self._send_to(client, {'type': 'recording_state', 'recording': False})
                        except Exception:
                            pass

            elif msg_type == 'clear':
                self.full_text = ""
                self.segments = []
                self._audio_buf = np.array([], dtype=np.float32)
                self.keyword_store = {cat: set() for cat in CATEGORIES}
                self.pinyin_corrector.kw_set.clear()
                self.sent_texts = set()
                self.speaker_manager.speaker_profiles = []
                self.speaker_manager.last_speaker_id = 0
                self.speaker_manager._pending_new = None
                self.speaker_manager._last_speaker_label = 'Speaker0'
                self.last_segment_wall_time = 0
                self.last_segment_end_audio_time = 0
                self.total_audio_seconds = 0
                self.speaker_manager.total_audio_seconds = 0
                self.transcription_count = 0
                self.keyword_history = []
                self.speaker_manager._session_active_speakers = set()
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
                        if kw and len(kw) >= 2 and kw not in self.pinyin_corrector.kw_set:
                            self.keyword_store.setdefault(kcat, set()).add(kw)
                            self.pinyin_corrector.kw_set.add(kw)
                            added.add(kw)
                            self.keyword_history.append({'time': datetime.now().strftime('%H:%M:%S'), 'keyword': kw, 'category': kcat})
                    if added:
                        print(f"[KW] New keywords [{CATEGORIES.get(kcat, '关键词')}]: {list(added)[:10]}")

            elif msg_type == 'generate_report':
                await self.generate_and_send_report(websocket)

            elif msg_type == 'page_creator':
                self.speaker_manager._page_creator = msg.get('creator')
                self.speaker_manager._page_platform = msg.get('platform')
                self.speaker_manager._page_type = msg.get('page_type', 'web')
                self.speaker_manager._video_offset = msg.get('video_offset', 0)

                print(f"[WS] 页面信息: 创作者={self.speaker_manager._page_creator} 平台={self.speaker_manager._page_platform} 类型={self.speaker_manager._page_type} 偏移={self.speaker_manager._video_offset}s", flush=True)

                # 网页端无 creator 但提供了 URL 时，尝试服务端抓取页面提取 UP 主名
                page_url = msg.get('url', '')
                if not msg.get('creator') and page_url:
                    asyncio.ensure_future(self._auto_detect_creator(page_url, websocket))

            elif msg_type == 'load_vocab':
                tags = [msg.get('name', '')]
                if tags and tags[0]:
                    added = await self._load_topic_keywords(tags)
                    if added:
                        await self._send_keywords_updated(websocket,
                            extra={'topic_loaded': added})
                    else:
                        await self._send_to(websocket, {
                            'type': 'vocab_loaded',
                            'name': tags[0],
                            'count': 0,
                        })

            elif msg_type == 'new_speaker':
                name = msg.get('name', f'发言人{self.speaker_manager.last_speaker_id}')
                for profile in self.speaker_manager.speaker_profiles:
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
                    self.pinyin_corrector.kw_set.add(keyword)
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
                        'keywords': list(self.pinyin_corrector.kw_set),
                        'keyword_store': {c: list(v) for c, v in self.keyword_store.items() if v},
                        'categories': CATEGORIES,
                        'category_icons': CATEGORY_ICONS,
                    })

                    if cat == 'speaker':
                        self.speaker_manager._session_active_speakers.add(keyword)

                    if cat == 'topic':
                        topic_added = await self._load_topic_keywords([keyword])
                        if topic_added:
                            print(f"[WS] 🏷 自动匹配话题 '{keyword}' → 加载{topic_added}个专用词", flush=True)
                            await self._send_keywords_updated(websocket,
                                extra={'topic_auto_loaded': {'name': keyword, 'count': topic_added}})

            elif msg_type == 'topic_keywords_load':
                tags = msg.get('tags', [])
                if tags:
                    added = await self._load_topic_keywords(tags)
                    if added:
                        print(f"[WS] 🏷 话题匹配: {tags[:5]} → 加载{added}个关键词(后台纠正，不显示在面板)", flush=True)
                        await self._send_keywords_updated(websocket,
                            extra={'topic_loaded': len(tags)})

            elif msg_type == 'video_title':
                title = msg.get('title', '').strip()
                if title:
                    extracted = extract_title_keywords(title)
                    added = 0
                    for kw in extracted:
                        if kw and len(kw) >= 2 and kw not in self.pinyin_corrector.kw_set:
                            self.pinyin_corrector.kw_set.add(kw)
                            added += 1
                    if added:
                        print(f"[WS] 📺 标题提取: '{title[:40]}' → {added}个关键词", flush=True)
                        await self._send_to(websocket, {
                            'type': 'keywords_updated',
                            'keywords': list(self.pinyin_corrector.kw_set),
                            'keyword_store': {c: list(v) for c, v in self.keyword_store.items() if v},
                            'categories': CATEGORIES,
                            'category_icons': CATEGORY_ICONS,
                        })

            elif msg_type == 'speaker_profile_get':
                speaker_id = msg.get('speaker_id', self.speaker_manager._last_speaker_label)
                await self._send_to(websocket, {
                    'type': 'speaker_profile',
                    'speaker_id': speaker_id,
                    'label': speaker_id,
                    'all_speakers': [p.get('label', '') for p in self.speaker_manager.speaker_profiles],
                })


            elif msg_type == 'speaker_rename':
                speaker_id = msg.get('speaker_id', '')
                new_label = msg.get('label', '')
                if speaker_id and new_label:
                    self.speaker_manager._speaker_display_names[speaker_id] = new_label
                    # 同步更新 speaker_profiles 中的 alias
                    for profile in self.speaker_manager.speaker_profiles:
                        if profile.get('label') == speaker_id:
                            profile['alias'] = new_label
                            break
                    print(f"[WS] 重命名: {speaker_id} → {new_label}", flush=True)
                    await self._send_to(websocket, {
                        'type': 'speaker_renamed',
                        'old_id': speaker_id,
                        'new_label': new_label,
                    })

            elif msg_type == 'save_report':
                merge_segments(self.segments)
                display_names = self.speaker_manager.get_all_display_names()
                report = generate_comprehensive_report(
                    self.segments, self.speaker_manager.speaker_profiles,
                    self.keyword_history, self.pinyin_corrector.correction_records,
                    self.pinyin_corrector.correction_log, self.total_audio_seconds,
                    self.asr_engine.model_name, self.pinyin_corrector._loaded_topics,
                    self.speaker_manager._page_type, self.speaker_manager._video_offset,
                    self.speaker_manager._session_active_speakers,
                    display_names=display_names,
                    min_speech_duration=self.min_speech_duration,
                    page_creator=self.speaker_manager._page_creator,
                )
                await self._send_to(websocket, {'type': 'save_report', 'content': report, 'filename': f'asr_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.md'})

            elif msg_type == 'save_log':
                merge_segments(self.segments)
                display_names = self.speaker_manager.get_all_display_names()
                log = generate_structured_log(
                    self.segments, self.speaker_manager.speaker_profiles,
                    self.keyword_history, self.pinyin_corrector.correction_records,
                    self.total_audio_seconds,
                    self.asr_engine.model_name if self.asr_engine else 'unknown',
                    self.pinyin_corrector._loaded_topics,
                    self.speaker_manager._page_type, self.speaker_manager._video_offset,
                    self.speaker_manager._session_active_speakers,
                    display_names=display_names,
                    page_creator=self.speaker_manager._page_creator,
                )
                await self._send_to(websocket, {'type': 'save_log', 'content': log, 'filename': f'asr_log_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'})

        except Exception as e:
            print(f"[WS] Control error: {e}")
            await self._send_to(websocket, {'type': 'error', 'message': str(e)})

    def _get_all_keywords(self):
        """获取所有分类的去重关键词"""
        return list(self.pinyin_corrector.kw_set)

    async def _load_topic_keywords(self, tags):
        """加载话题关键词、拼音/文本纠正、实体知识库（不发送消息，返回 added 计数）"""
        topic_kws, matched_topics = TOPIC_MANAGER.match_and_load(tags)
        added = 0
        for kw in topic_kws:
            kw = kw.strip()
            if kw and len(kw) >= 2 and kw not in self.pinyin_corrector.kw_set:
                self.pinyin_corrector.kw_set.add(kw)
                added += 1
        for topic in matched_topics:
            self.pinyin_corrector.load_pinyin_corrections(topic)
            self.pinyin_corrector.load_text_corrections(topic)
            self.correction_engine.load_topic(topic)
        self.pinyin_corrector.sync_protected_from_keywords()
        return added

    async def _send_keywords_updated(self, websocket, extra=None):
        """发送 keywords_updated 消息，附加可选 extra 字段"""
        msg = {
            'type': 'keywords_updated',
            'keywords': list(self.pinyin_corrector.kw_set),
            'keyword_store': {c: list(v) for c, v in self.keyword_store.items() if v},
            'categories': CATEGORIES,
            'category_icons': CATEGORY_ICONS,
        }
        if extra:
            msg.update(extra)
        await self._send_to(websocket, msg)

    async def process_audio(self, audio_data, websocket):
        if not self.is_running or websocket is not self.recording_ws:
            return
        try:
            audio_array = np.frombuffer(audio_data, dtype=np.float32)

            if self.browser_sample_rate != self.target_sample_rate:
                audio_array = self._resample_audio(
                    audio_array, self.browser_sample_rate, self.target_sample_rate)

            self._audio_buf = np.append(self._audio_buf, audio_array)

            # 每0.5秒做一次快速partial推理
            now = time.time()
            if now - self._stream_partial_time >= self._stream_partial_interval:
                self._stream_partial_time = now
                buf = self._audio_buf
                dur = len(buf) / 16000
                if dur >= 0.5:
                    asyncio.ensure_future(self._do_streaming_partial(buf.copy()))

            # 每0.5秒检查一次是否可以转录
            buffer_dur = len(self._audio_buf) / 16000
            if buffer_dur >= 0.5 and len(self._audio_buf) > 0:
                # 用VAD检测是否有完整的语音段
                audio_seg, remaining, vad_info = self.vad_processor.cut(self._audio_buf, 16000)
                if remaining is not None:
                    self._audio_buf = remaining if len(remaining) > 0 else np.array([], dtype=np.float32)

                if audio_seg is not None and len(audio_seg) > int(self.min_speech_duration * 16000):
                    await self.transcribe_buffer(audio_seg, vad_info)

                # 限制缓冲区大小
                if len(self._audio_buf) > self.max_buffer_size:
                    self._audio_buf = self._audio_buf[-self.max_buffer_size:]

        except Exception as e:
            print(f"[WS] Audio error: {e}")
            import traceback
            traceback.print_exc()

    async def _do_streaming_partial(self, audio_array):
        """流式模式：快速partial推理，结果发送到前端"""
        # 防止CPU模式下前一个partial尚未完成时堆积新请求
        if self._partial_in_flight:
            return
        self._partial_in_flight = True
        try:
            import numpy as np
            rms = np.sqrt(np.mean(np.asarray(audio_array, dtype=np.float32) ** 2))
            if rms < 0.005:
                return

            # 前置音乐/噪声检测：纯音乐/噪声直接跳过，不做ASR
            if self.vad_processor.is_music_like(audio_array):
                return

            loop = asyncio.get_event_loop()
            full_text = await loop.run_in_executor(
                self.executor, self.asr_engine.transcribe_array, audio_array, 16000)

            if not full_text or not full_text.strip():
                return

            full_text = full_text.strip()

            if full_text == self._stream_full_text:
                return

            self._stream_full_text = full_text

            # 智能纠错引擎：拼音纠错 + 文本纠错 + 实体识别 + 模糊匹配 + 语法检查 + 置信度评分
            eng_result = self.correction_engine.correct(full_text, pinyin_corrector=self.pinyin_corrector)
            corrected = eng_result['text']
            corrected = normalize_letter_adjacent_numbers(corrected)

            self._stream_last_corrected = corrected

            self._stream_seg_id += 1
            await self.send({
                'type': 'partial',
                'text': corrected,
                'seg_id': self._stream_seg_id,
            })
        except Exception as e:
            print(f"[WS] Partial error: {e}", flush=True)
            import traceback
            traceback.print_exc()
        finally:
            self._partial_in_flight = False

    async def transcribe_buffer(self, audio_data, vad_info=None):
        if self.transcripts_in_flight >= self.max_concurrent_transcripts:
            return

        # 前置音乐/噪声检测：纯音乐/噪声直接跳过，不做ASR
        if self.vad_processor.is_music_like(audio_data):
            return

        self.transcripts_in_flight += 1

        # 在完整ASR前先跑一次快速partial，给前端实时展示斜体字+字幕条
        if len(audio_data) / 16000 >= 0.2:
            await self._do_streaming_partial(audio_data.copy())

        timestamp = int(time.time() * 1000)
        temp_path = TEMP_DIR / f'realtime_chunk_{timestamp}.wav'
        try:
            sf.write(str(temp_path), audio_data, 16000)
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(
            self.executor, self._do_transcribe, str(temp_path))

        asyncio.ensure_future(self._handle_transcription(future, temp_path, audio_data, vad_info))

    async def _handle_transcription(self, future, temp_path, audio_data, vad_info=None):
        try:
            text = await future

            if not text or not text.strip():
                return

            text = text.strip()

            if self.segments:
                prev = self.segments[-1]['text']
                before_dedup = text
                text = dedup_overlap(prev, text)
                if text != before_dedup:
                    removed = before_dedup[:len(before_dedup)-len(text)] if len(before_dedup) > len(text) else before_dedup
                    print(f"    [DEDUP] 与上段重叠去重: removed='{removed[:20]}' → kept='{text[:30]}'", flush=True)

            text = dedup_chars(text)

            if not text:
                return

            if text in self.sent_texts:
                print(f"    [DEDUP-SENT] 完全重复: '{text[:30]}'", flush=True)
                return
            for prev in list(self.sent_texts):
                if prev in text and len(prev) > len(text) * 0.8:
                    print(f"    [DEDUP-SENT] 包含已发送: prev='{prev[:20]}' in text='{text[:30]}'", flush=True)
                    return
                if text in prev and len(text) > len(prev) * 0.8:
                    print(f"    [DEDUP-SENT] 替换更短: old='{prev[:20]}' ← new='{text[:30]}'", flush=True)
                    self.sent_texts.discard(prev)

            # 对完整ASR结果运行智能纠错引擎，得到最终纠正后文本
            # 此时partial（斜体字+字幕条）已展示过实时纠正版本，
            # speaker区域展示的是完整纠正后的最终版本（异步、慢一拍）
            original_text = text
            eng_result = self.correction_engine.correct(text, pinyin_corrector=self.pinyin_corrector)
            corrected = eng_result['text']
            corrected = normalize_letter_adjacent_numbers(corrected)
            corrections = eng_result.get('corrections', [])

            if not corrected or not corrected.strip():
                return

            # 先将最终纠正文本同步到斜体字+字幕条，确保三者（斜体/字幕/speaker）文字完全一致
            self._stream_seg_id += 1
            await self.send({
                'type': 'partial',
                'text': corrected,
                'seg_id': self._stream_seg_id,
            })

            await self._emit_segment(audio_data, corrected, True, vad_info=vad_info,
                                      corrections=corrections, original_text=original_text)
            status = f"[WS] [{self.transcription_count}] [SEG]"
            print(f"{status} {corrected[:60]}...", flush=True)

            self.last_activity = time.time()

        except Exception as e:
            print(f"[WS] Transcription error: {e}", flush=True)
            import traceback
            traceback.print_exc()
            await self.send({'type': 'error', 'message': str(e)})
        finally:
            self.transcripts_in_flight -= 1
            if temp_path.exists():
                temp_path.unlink()

    def _do_transcribe(self, temp_path):
        """在子线程中执行转写，避免阻塞事件循环"""
        return self.asr_engine.transcribe(temp_path)

    async def _emit_segment(self, audio_data, text, kw_applied=False, speaker_label=None, vad_info=None, corrections=None, original_text=None):
        """创建一条识别记录并发送到前端"""
        if not text or text in self.sent_texts:
            if text:
                print(f"    [DEDUP-EMIT] 已发送过: '{text[:30]}'", flush=True)
            return
        for prev in list(self.sent_texts):
            if prev in text and len(prev) > len(text) * 0.8:
                print(f"    [DEDUP-EMIT] 包含已发送: prev='{prev[:20]}' in '{text[:30]}'", flush=True)
                return

        # 如果调用方已提供 speaker_label（多句 chunk 共享），直接使用
        if speaker_label is not None:
            pass
        # 短音频不跑 VoiceEncoder（单字如"我""嗯"嵌入是噪声），直接用上一个说话人
        elif len(audio_data) < int(16000 * 0.5):
            speaker_label = self.speaker_manager._last_speaker_label
        # 极短文本片段（<5个中文字）：大概率是VAD强制切分产生的尾部碎片
        # 声纹嵌入在这么短的有效语音上几乎就是噪声，直接继承上一个说话人
        elif text and len(re.findall(r'[\u4e00-\u9fff]', text)) < 5:
            speaker_label = self.speaker_manager._last_speaker_label
            print(f"    [SPEAKER] 短文本片段({len(re.findall(r'[\u4e00-\u9fff]', text))}字) "
                  f"继承说话人: {speaker_label}", flush=True)
        else:
            speaker_label = await self.speaker_manager.detect_speaker(audio_data)
            self.speaker_manager._last_speaker_label = speaker_label

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

        display_name = self.speaker_manager.get_speaker_display(speaker_label)

        seg_entry = {
            'text': text,
            'time': self.total_audio_seconds,
            'speaker': speaker_label,
            'speaker_display': display_name,
            'duration': seg_duration,
            'kw_corrected': kw_applied,
            'timestamp': datetime.now().isoformat(),
            'vad': vad_info or {},
            'gap_audio': gap_audio,
            'gap_wall': gap_wall,
            'corrections': corrections or [],
        }
        self.segments.append(seg_entry)

        if display_name and display_name != "Speaker":
            display = f"[{display_name}] {text}"
        else:
            display = text

        self.full_text += display + " "
        if len(self.sent_texts) < self._MAX_SENT_TEXTS:
            self.sent_texts.add(text)
        self.total_audio_seconds += seg_duration
        self.speaker_manager.total_audio_seconds = self.total_audio_seconds
        self.transcription_count += 1

        await self.send({
            'type': 'transcription',
            'text': text,
            'speaker': display_name,
            'speaker_label': speaker_label,
            'full_text': self.full_text.strip(),
            'timestamp': datetime.now().isoformat(),
            'duration': self.total_audio_seconds,
            'seg_time': seg_audio_time,
            'seg_dur': seg_duration,
            'gap_audio': gap_audio,
            'gap_wall': gap_wall,
            'keywords': list(self.pinyin_corrector.kw_set)[:10],
            'kw_corrected': kw_applied,
            'kw_count': len(self.pinyin_corrector.kw_set),
            'corrections': corrections or [],
            'original_text': original_text or text,
            'is_host': speaker_label == self.speaker_manager._host_speaker_label if speaker_label else False,
        })

        # 句子已确定，重置partial状态准备下一句
        self._stream_last_partial = ""
        self._stream_full_text = ""
        self._stream_last_corrected = ""

    async def _auto_detect_creator(self, page_url, websocket):
        """通过平台 API 提取 UP 主 / 主播名（优先用 API，比 HTML 抓取可靠）"""
        try:
            creator = None
            loop = asyncio.get_event_loop()

            # ── B站视频: 用 bilibili API ──
            bv_match = re.search(r'(?:bilibili\.com/video/|BV)([A-Za-z0-9]{10,12})', page_url)
            if bv_match:
                bvid = 'BV' + bv_match.group(1) if not bv_match.group(0).startswith('BV') else bv_match.group(1)
                api_url = f'https://api.bilibili.com/x/web-interface/view?bvid={bvid}'
                data = await loop.run_in_executor(self.executor, self._fetch_json_api, api_url)
                if data and data.get('code') == 0:
                    owner = data.get('data', {}).get('owner', {})
                    creator = owner.get('name', '')
                    print(f"[WS] B站视频API: bvid={bvid} → owner={creator}", flush=True)

            # ── B站直播: 用 bilibili 直播 API ──
            if not creator:
                room_match = re.search(r'live\.bilibili\.com/(?:blanc/)?(\d+)', page_url)
                if room_match:
                    room_id = room_match.group(1)
                    api_url = f'https://api.live.bilibili.com/room/v1/Room/get_info?room_id={room_id}'
                    data = await loop.run_in_executor(self.executor, self._fetch_json_api, api_url)
                    if data and data.get('code') == 0:
                        anchor = data.get('data', {}).get('anchor_info', {}).get('base_info', {})
                        creator = anchor.get('uname', '')
                        print(f"[WS] B站直播API: room={room_id} → uname={creator}", flush=True)

            # ── 斗鱼直播 ──
            if not creator and 'douyu.com' in page_url:
                room_match = re.search(r'douyu\.com/(\d+)', page_url)
                if not room_match:
                    room_match = re.search(r'[?&]rid=(\d+)', page_url)
                if room_match:
                    room_id = room_match.group(1)
                    # 斗鱼 betard API
                    api_url = f'https://www.douyu.com/betard/{room_id}'
                    data = await loop.run_in_executor(self.executor, self._fetch_json_api, api_url)
                    api_name = ''
                    if data:
                        room_info = data.get('room', {}) or data.get('roomInfo', {})
                        api_name = room_info.get('nickname', '') or room_info.get('owner_name', '')
                        print(f"[WS] 斗鱼API: room={room_id} → {api_name}", flush=True)
                # 兜底：从 title 提取（斗鱼格式: "标题_主播名[分区]直播_斗鱼直播"）
                # 即使 API 有结果也跑一次 HTML，取更完整的名字
                html_name = ''
                html = await loop.run_in_executor(self.executor, self._fetch_page, page_url)
                if html:
                    title_match = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
                    if title_match:
                        t = title_match.group(1).strip()
                        # 取 _斗鱼直播 或 _正在直播 之前最后一段
                        m = re.search(r'[_\s]([^_\s]{2,30})_(?:斗鱼|正在)直播', t)
                        if m:
                            name = m.group(1).strip()
                            # 去掉尾部的游戏分区名+直播（如 "CS2直播", "英雄联盟直播"）
                            name = re.sub(r'(?:CS[:]?GO|CS2|VALORANT|APEX|PUBG|DOTA2?|LOL|CF|[A-Z]{2,6}|[\u4e00-\u9fff]{2,4})直播$', '', name, flags=re.IGNORECASE)
                            if 2 <= len(name) < 30:
                                html_name = name
                        if not html_name:
                            parts = [p for p in t.split('_') if p and len(p) >= 2 and '斗鱼' not in p and '正在' not in p and p != '直播']
                            if parts:
                                last = re.sub(r'(?:CS[:]?GO|CS2|VALORANT|APEX|PUBG|DOTA2?|LOL|CF|[A-Z]{2,6}|[\u4e00-\u9fff]{2,4})直播$', '', parts[-1], flags=re.IGNORECASE)
                                if 2 <= len(last) < 30:
                                    html_name = last
                # 取更长/更完整的名字
                creator = api_name
                if html_name and (not creator or len(html_name) > len(creator)):
                    creator = html_name
                    print(f"[WS] 斗鱼: 采用HTML标题更长的名字 '{html_name}' 替代API '{api_name}'", flush=True)

            # ── 虎牙直播 ──
            if not creator and 'huya.com' in page_url:
                html = await loop.run_in_executor(self.executor, self._fetch_page, page_url)
                if html:
                    # 虎牙 HTML 中有 window.HNF_GLOBAL_DATA = {...} 或 var TT_ROOM_DATA
                    hn_match = re.search(r'"nickName"\s*:\s*"([^"]+)"', html)
                    if not hn_match:
                        hn_match = re.search(r'"sNick"\s*:\s*"([^"]+)"', html)
                    if hn_match:
                        creator = hn_match.group(1)
                        print(f"[WS] 虎牙HTML: → {creator}", flush=True)
                    if not creator:
                        title_match = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
                        if title_match:
                            title = title_match.group(1).strip()
                            for sep in ['-', '_', '直播']:
                                if sep in title:
                                    parts = title.split(sep)
                                    c = parts[0].strip()
                                    if 2 <= len(c) <= 20:
                                        creator = c
                                        break
            if not creator:
                html = await loop.run_in_executor(self.executor, self._fetch_page, page_url)
                if html:
                    author_match = re.search(r'<meta\s+name="author"\s+content="([^"]+)"', html, re.IGNORECASE)
                    if author_match:
                        c = author_match.group(1).strip()
                        if c and c not in ('哔哩哔哩', 'bilibili', 'BILIBILI'):
                            creator = c
                    if not creator and 'live.bilibili.com' in page_url:
                        title_match = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
                        if title_match:
                            parts = title_match.group(1).strip().split(' - ', 1)
                            if len(parts[0]) >= 2 and len(parts[0]) <= 20:
                                creator = parts[0]

            if creator and creator != self.speaker_manager._page_creator:
                self.speaker_manager._page_creator = creator
                self.speaker_manager._session_active_speakers.add(creator)
                print(f"[WS] 自动识别创作者: {creator} (from {page_url[:60]})", flush=True)
                await self._send_to(websocket, {
                    'type': 'page_creator',
                    'creator': creator,
                    'platform': self.speaker_manager._page_platform,
                    'page_type': self.speaker_manager._page_type,
                    'video_offset': self.speaker_manager._video_offset,
                })
                await self._send_to(websocket, {
                    'type': 'keyword_added',
                    'keyword': creator,
                    'category': 'speaker',
                })
                await self._send_to(websocket, {
                    'type': 'toast',
                    'text': f'✅ 自动识别创作者: {creator}',
                    'ok': True,
                })
            else:
                print(f"[WS] 未识别到创作者 (URL={page_url[:60]})", flush=True)

        except Exception as e:
            print(f"[WS] 自动识别创作者失败: {e}", flush=True)

    def _fetch_json_api(self, url):
        """同步调用 JSON API（在 executor 线程中运行）"""
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://www.bilibili.com/',
            })
            with urllib.request.urlopen(req, timeout=8) as resp:
                return json.loads(resp.read().decode('utf-8', errors='ignore'))
        except Exception as e:
            print(f"[WS] API 调用失败: {e}", flush=True)
            return None

    def _fetch_page(self, url):
        """同步抓取页面 HTML（在 executor 线程中运行）"""
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml',
            })
            with urllib.request.urlopen(req, timeout=8) as resp:
                return resp.read().decode('utf-8', errors='ignore')
        except Exception as e:
            print(f"[WS] 抓取页面失败: {e}", flush=True)
            return None

    async def generate_and_send_report(self, websocket):
        merge_segments(self.segments)
        display_names = self.speaker_manager.get_all_display_names()
        report = generate_comprehensive_report(
            self.segments, self.speaker_manager.speaker_profiles,
            self.keyword_history, self.pinyin_corrector.correction_records,
            self.pinyin_corrector.correction_log, self.total_audio_seconds,
            self.asr_engine.model_name, self.pinyin_corrector._loaded_topics,
            self.speaker_manager._page_type, self.speaker_manager._video_offset,
            self.speaker_manager._session_active_speakers,
            display_names=display_names,
            min_speech_duration=self.min_speech_duration,
            page_creator=self.speaker_manager._page_creator,
        )
        await self._send_to(websocket, {'type': 'report', 'content': report})

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
            path = request.path if hasattr(request, 'path') else '/'
            print(f"[WS] HTTP request: {path}", flush=True)
            if request.headers.get("Upgrade", "").lower().strip() == "websocket":
                print(f"[WS] WebSocket upgrade request", flush=True)
                return None
            h = Headers()
            h['Content-Type'] = 'text/html; charset=utf-8'
            h['Connection'] = 'close'
            print(f"[WS] Serving status page ({len(page)} bytes)", flush=True)
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

def run_server(asr_engine, host='localhost', port=8765):
    global _global_server
    server = RealtimeASRServer(asr_engine, host, port)
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

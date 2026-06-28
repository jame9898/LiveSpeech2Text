// ==UserScript==
// @name         LiveSpeech2Text V1.0
// @namespace    asr-panel-v3
// @version      1.0
// @description  视频页面内嵌语音识别面板 — VAD断句 + 说话人分离 + 口音矫正
// @match        *://*.bilibili.com/*
// @match        *://*.douyu.com/*
// @match        *://*.huya.com/*
// @match        *://*.youtube.com/*
// @match        *://*.douyin.com/*
// @match        *://*.cc.163.com/*
// @match        *://*.egame.qq.com/*
// @grant        GM_addStyle
// @grant        GM_getValue
// @grant        GM_xmlhttpRequest
// @grant        unsafeWindow
// @connect      localhost
// @connect      127.0.0.1
// ==/UserScript==

(function() {
'use strict';



const LAUNCH_URL = 'asr-launcher://start';
const RECONNECT_BASE = 2000;
const RECONNECT_MAX = 30000;
const MAX_SEGMENTS = 200;
const WS_URLS = ['ws://localhost:8765', 'ws://127.0.0.1:8765'];
const PING_INTERVAL = 20000;

const SP_COLORS = [
    {bg:'rgba(88,166,255,.12)',border:'#58a6ff',name:'#58a6ff'},
    {bg:'rgba(248,81,73,.12)',border:'#f85149',name:'#f85149'},
    {bg:'rgba(63,185,80,.12)',border:'#3fb950',name:'#3fb950'},
    {bg:'rgba(210,153,29,.12)',border:'#d2991d',name:'#d2991d'},
    {bg:'rgba(163,113,247,.12)',border:'#a371f7',name:'#a371f7'},
    {bg:'rgba(19,194,194,.12)',border:'#13c2c2',name:'#13c2c2'},
    {bg:'rgba(235,47,150,.12)',border:'#eb2f96',name:'#eb2f96'},
    {bg:'rgba(250,84,28,.12)',border:'#fa541c',name:'#fa541c'},
];

function eHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

if (document.getElementById('asr-panel-v3')) return;
if (unsafeWindow.self !== unsafeWindow.top) return;

let isRecording = false, audioCtx = null, mediaStream = null;
let reconnectTimer = null, reconnectAttempts = 0;
let segCount = 0, lastWelcomeTime = 0;
let keywords = [], keywordStore = {};
let speakerColors = {}, matchedSpeakers = new Set();
let autoAddedSpeakers = new Set();
let savedW = 420, savedH = 680;
let heartbeatTimer = null, pingTimer = null;
let _panelInjected = false, _eventsBound = false;
let _lastUrl = location.href, _panelClosedByUser = false;
let lastSpeakerId = 'Speaker0';
let _pendingSegs = [];

// WebSocket via Web Worker (bypasses CSP)
const _WS_WORKER_CODE = 'const U=["ws://localhost:8765","ws://127.0.0.1:8765"];let s=null,a=0,t=null,ok=0;function c(i){if(i>=U.length){p("s",{ok:0,msg:"无法连接"});a++;t=setTimeout(function(){c(0)},Math.min(2000*Math.pow(1.5,a),30000));return}try{s=new WebSocket(U[i]);s.binaryType="arraybuffer";s.onopen=function(){ok=1;p("s",{ok:1});a=0;if(t){clearTimeout(t);t=null}};s.onmessage=function(e){p("m",e.data)};s.onclose=function(e){p("s",{ok:0,msg:"断开 ("+(e.code||"?")+")"});s=null;a++;var n=ok?0:(i+1);t=setTimeout(function(){c(n)},Math.min(2000*Math.pow(1.5,a),30000))};s.onerror=function(){p("s",{ok:0,msg:"无法连接"});if(s){s.close();s=null}}}catch(e){p("s",{ok:0,msg:"无法连接"});a++;t=setTimeout(function(){c(i+1)},Math.min(2000*Math.pow(1.5,a),30000))}}function p(y,d){try{self.postMessage({t:y,d:d})}catch(e){}}self.onmessage=function(e){var m=e.data;if(m.t==="c"){c(0)}else if(m.t==="s"){if(s&&s.readyState===1){try{s.send(m.d)}catch(e){}}}else if(m.t==="x"){if(t){clearTimeout(t);t=null}a=0;if(s){try{s.close()}catch(e){}s=null}}};';
let _wsWorker = null, _wsReady = false;
function _wsInit() {
    if (_wsWorker) return;
    try {
        var blob = new Blob([_WS_WORKER_CODE], {type: 'application/javascript'});
        _wsWorker = new Worker(URL.createObjectURL(blob));
        _wsWorker.onmessage = function(e) {
            var m = e.data;
            if (m.t === 's') {
                if (m.d.ok) {
                    _wsReady = true;
                    setConn(true);
                    reconnectAttempts = 0;
                    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
                    pingTimer = setInterval(function() { _wsSend(JSON.stringify({type:'ping'})); }, PING_INTERVAL);
                } else {
                    _wsReady = false;
                    setConn(false, String.fromCharCode(0x1F534)+' '+m.d.msg);
                    if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
                }
            } else if (m.t === 'm') {
                try { onMsg(JSON.parse(typeof m.d === 'string' ? m.d : new TextDecoder().decode(new Uint8Array(m.d)))); } catch(x) {}
            }
        };
    } catch(e) {
        L('Worker init failed: ' + e.message);
    }
}
function _wsSend(data) {
    if (_wsWorker && _wsReady) {
        _wsWorker.postMessage({t: 's', d: data});
    }
}
function _wsSendBinary(buffer) {
    if (_wsWorker && _wsReady) {
        _wsWorker.postMessage({t: 's', d: buffer}, [buffer]);
    }
}
function _wsClose() {
    if (_wsWorker) {
        _wsWorker.postMessage({t: 'x'});
        _wsWorker.terminate();
        _wsWorker = null;
    }
    _wsReady = false;
}

function isVideoPage() {
    const u = location.href;

    if (u.includes('bilibili.com')) {
        if (u.includes('/video/') || u.includes('bangumi/play')) return _hasInteractiveVideo();
        if (u.includes('live.bilibili.com')) {
            // B站直播房间页：URL含数字ID或blanc/数字ID时返回true
            // 首页(live.bilibili.com/) 和 目录页(/p/eden/area等) 不显示插件
            if (/live\.bilibili\.com\/(\d+|blanc\/\d+|blackboard\/)/.test(u)) return true;
            return false;
        }
        return false;
    }

    if (u.includes('douyu.com')) {
        if (u.includes('/directory') || u.includes('/topic') || u.includes('/myFollow')) return false;
        // 房间页：www.douyu.com/房间号
        if (/douyu\.com\/(\d+)/.test(u)) return true;
        // 首页等：不显示插件
        return false;
    }

    if (u.includes('youtube.com')) {
        if (u.includes('/watch') || u.includes('/shorts/') || u.includes('/live/')) return _hasInteractiveVideo();
        return false;
    }

    if (u.includes('huya.com')) {
        if (u.includes('/topic') || u.includes('/user') || u.includes('/myFollow') || u.includes('/directory')) return false;
        const m = u.match(/huya\.com\/([^/?#]+)/);
        if (m && m[1]) return true;
        return false;
    }

    if (u.includes('douyin.com') || u.includes('v.douyin.com')) return _hasInteractiveVideo();

    if (u.includes('cc.163.com/') || u.includes('egame.qq.com/')) return _hasInteractiveVideo();

    return false;
}

function _hasInteractiveVideo() {
    const vs = document.querySelectorAll('video');
    for (const v of vs) {
        if (v.src || (v.querySelector('source') && v.querySelector('source').src)) return true;
        if (v.duration > 0 || v.readyState >= 1) return true;
        if (v.networkState >= 1) return true;
    }
    return false;
}

var detectCreator, detectTitle;
{ // inject platform-specific detection functions
    detectCreator = function() {
        const u = location.href;
        if (u.includes('bilibili.com/video/')) {
            const sels = [
                '[class*="up-name"]','.up-name','.username',
                '[class*="up-detail"] a','[class*="video-info"] [class*="name"]',
                '[class*="owner-name"]','[class*="author-name"]',
                'a[href*="space.bilibili.com"]'
            ];
            for (const sel of sels) {
                const el = document.querySelector(sel);
                if (el) { const t = el.textContent.trim(); if (t.length>=2&&t.length<30&&!t.includes('关注')&&!t.includes('粉丝')) return t; }
            }
            const ma = document.querySelector('meta[name="author"]');
            if (ma) { const v = ma.getAttribute('content'); if (v&&v.length>=2&&v.length<30) return v; }
            // 尝试所有 space.bilibili.com 链接
            const spaceLinks = document.querySelectorAll('a[href*="space.bilibili.com"]');
            for (const link of spaceLinks) {
                const t = link.textContent.trim();
                if (t.length>=2&&t.length<30&&!t.includes('关注')&&!t.includes('粉丝')) return t;
            }
            return null;
        }
        if (u.includes('live.bilibili.com')) {
            // B站直播：尝试多种选择器获取主播名
            const sels = [
                '[class*="room-owner"]','[class*="anchor-name"]','[class*="host-name"]',
                '[class*="up-name"]','.username','[class*="live-skin"] [class*="name"]',
                '[class*="anchor-info"] [class*="name"]','[class*="room-info"] [class*="name"]',
                'a[href*="space.bilibili.com"]'
            ];
            for (const sel of sels) {
                const el = document.querySelector(sel);
                if (el) { const t = el.textContent.trim(); if (t.length>=2&&t.length<30&&!t.includes('关注')&&!t.includes('粉丝')&&!t.includes('直播')) return t; }
            }
            // 尝试所有 space.bilibili.com 链接
            const spaceLinks = document.querySelectorAll('a[href*="space.bilibili.com"]');
            for (const link of spaceLinks) {
                const t = link.textContent.trim();
                if (t.length>=2&&t.length<30&&!t.includes('关注')&&!t.includes('粉丝')&&!t.includes('直播')) return t;
            }
            // 尝试从页面标题提取主播名
            const title = document.querySelector('title');
            if (title) {
                const t = title.textContent.trim();
                const m = t.match(/^(.+?)[的之]?直播/);
                if (m && m[1].length>=2 && m[1].length<30) return m[1].trim();
                const m2 = t.match(/^(.+?)[-—–\\s]+/);
                if (m2 && m2[1].length>=2 && m2[1].length<30) return m2[1].trim();
                const m3 = t.match(/^(.+?)_/);
                if (m3 && m3[1].length>=2 && m3[1].length<30) return m3[1].trim();
            }
            return null;
        }
        if (u.includes('douyu.com/')&&!u.includes('douyu.com/directory')) {
            // 斗鱼主播名：优先从 anchorName 类名的 H3 标签提取（F12 可见，最可靠）
            // 实际类名格式: anchorName__6NXv9（小写 a 开头，带 hash 后缀）
            const anchorH3 = document.querySelector('h3[class*="anchorName"]');
            if (anchorH3) {
                const t = anchorH3.textContent.trim();
                if (t.length >= 2 && t.length < 30) return t;
            }
            // 备用：其他常见选择器
            const sels = [
                '[class*="anchorName"]','[class*="AnchorName"]','[class*="anchor-name"]',
                '[class*="host-name"]','[class*="room-owner"]','[class*="anchor-info"] [class*="name"]',
                '.Title-titleName','.title-name','[class*="host-info"]','[class*="room-title"]'
            ];
            for (const sel of sels) {
                const el = document.querySelector(sel);
                if (el) { const t = el.textContent.trim(); if (t.length>=2&&t.length<30&&!t.includes('关注')&&!t.includes('粉丝')&&!t.includes('直播')) return t; }
            }
            // 兜底：从页面标题提取（斗鱼格式: "标题_主播名[分区]直播_斗鱼直播"）
            const tEl = document.querySelector('title');
            if (tEl) {
                const t = tEl.textContent.trim();
                // 提取 _斗鱼直播 或 _正在直播 之前最后一段
                const m = t.match(/[_\s]([^_\s]{2,30})_(?:斗鱼|正在)直播/);
                if (m) {
                    let name = m[1].trim();
                    // 去掉尾部的游戏分区名+直播（如 "CS2直播", "英雄联盟直播"）
                    name = name.replace(/(?:CS[:]?GO|CS2|VALORANT|APEX|PUBG|DOTA2?|LOL|CF|[A-Z]{2,6}|[\u4e00-\u9fff]{2,4})直播$/i, '');
                    if (name.length>=2 && name.length<30) return name;
                }
                // 直接分割，取倒数第二段
                const parts = t.split('_').filter(p => p && p.length>=2 && !p.includes('斗鱼') && !p.includes('正在') && p !== '直播');
                if (parts.length > 0) {
                    let last = parts[parts.length - 1];
                    last = last.replace(/(?:CS[:]?GO|CS2|VALORANT|APEX|PUBG|DOTA2?|LOL|CF|[A-Z]{2,6}|[\u4e00-\u9fff]{2,4})直播$/i, '');
                    if (last.length >= 2 && last.length < 30) return last;
                }
            }
            return null;
        }
        if (u.includes('huya.com/')&&/\d+/.test(u)) {
            const sels = [
                '[class*="host-name"]','[class*="anchor-name"]','[class*="author-name"]',
                '[class*="host-info"] [class*="name"]','[class*="room-info"] [class*="name"]',
                '#J_anchorName','.host-title','.anchor-title','[class*="live-title"] [class*="name"]'
            ];
            for (const sel of sels) {
                const el = document.querySelector(sel);
                if (el) { const t = el.textContent.trim(); if (t.length>=2&&t.length<30&&!t.includes('关注')&&!t.includes('粉丝')&&!t.includes('直播')) return t; }
            }
            // 兜底：从页面标题提取
            const tEl = document.querySelector('title');
            if (tEl) {
                const t = tEl.textContent.trim();
                const m = t.match(/^(.+?)[的之\-—–_]?直播间/);
                if (m && m[1].length>=2 && m[1].length<30) return m[1].trim();
                const m2 = t.match(/^(.+?)[-—–_]/);
                if (m2 && m2[1].length>=2 && m2[1].length<30) return m2[1].trim();
            }
            return null;
        }
        return null;
    };
    detectTitle = function() {
        if (!location.href.includes('bilibili.com/video/')) return '';
        const sels = ['h1[data-title]','h1.video-title','[class*="video-title"]','meta[property="og:title"]'];
        for (const sel of sels) {
            const el = document.querySelector(sel);
            if (el) {
                const t = (el.getAttribute('content')||el.getAttribute('data-title')||el.textContent||'').trim();
                if (t.length>=4&&t.length<200&&!t.includes('哔哩哔哩')) return t;
            }
        }
        const te = document.querySelector('title');
        if (te) { const t=te.textContent.trim(); const i=t.lastIndexOf('_哔哩哔哩'); if(i>0) return t.substring(0,i).trim(); }
        return '';
    };
}

function injectPanel() {
    if (_panelInjected||_panelClosedByUser) return;
    document.body.appendChild(p);
    _panelInjected = true;
    bindEvents();
    connect();
}

function removePanel() {
    if (!_panelInjected) return;
    if (isRecording) stopRec();
    cleanup();
    if (p.parentNode) p.parentNode.removeChild(p);
    _wsClose();
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    _hideSubtitle();
    _panelInjected = false;
}

if (!document.getElementById('asr-style-v3')) {
    const s = document.createElement('style');
    s.id = 'asr-style-v3';
    s.textContent = `
#asr-v3{position:fixed!important;right:10px;top:10px;width:420px;height:680px;
    background:#0d1117;border:1px solid #30363d;border-radius:12px;
    box-shadow:0 8px 32px rgba(0,0,0,.7);z-index:2147483647!important;
    display:flex!important;flex-direction:column;overflow:hidden;
    font:13px -apple-system,'Microsoft YaHei',sans-serif;color:#c9d1d9;
    resize:both;min-width:300px;min-height:400px;contain:layout style}
.asr3-hdr{padding:12px 16px;background:linear-gradient(135deg,#1a1f2e,#161b22);
    display:flex;justify-content:space-between;align-items:center;
    cursor:move;user-select:none;border-bottom:1px solid #30363d}
.asr3-hdr b{font-size:13px;font-weight:600;color:#c9d1d9}
.asr3-hdr .btns{display:flex;gap:4px}
.asr3-hdr button{background:rgba(255,255,255,.06);border:1px solid #30363d;color:#8b949e;
    padding:3px 10px;border-radius:5px;cursor:pointer;font-size:12px;transition:all .15s}
.asr3-hdr button:hover{background:rgba(255,255,255,.1);color:#c9d1d9}
.asr3-body{flex:1;display:flex;flex-direction:column;padding:10px 12px;overflow:hidden;gap:6px}
.asr3-bar{text-align:center;padding:5px 8px;border-radius:5px;font-size:11px;font-weight:500}
.asr3-bt1{flex:1;padding:9px 8px;border:1px solid #30363d;border-radius:7px;color:#c9d1d9;
    cursor:pointer;font-size:13px;font-weight:500;background:#21262d;transition:all .15s}
.asr3-bt1:hover:not(:disabled){border-color:#58a6ff;color:#58a6ff;transform:translateY(-1px)}
.asr3-bt1:disabled{opacity:.35;cursor:not-allowed}
.asr3-bt2{flex:1;padding:7px;border:1px dashed #30363d;border-radius:6px;color:#8b949e;
    cursor:pointer;font-size:12px;background:transparent;transition:all .15s}
.asr3-bt2:hover:not(:disabled){border-color:#58a6ff;color:#58a6ff}
.asr3-bt2:disabled{opacity:.35;cursor:not-allowed}
.asr3-text-box{flex:1;background:rgba(255,255,255,.018);border:1px solid #21262d;border-radius:8px;overflow:hidden}
.asr3-text-scroll{height:100%;overflow-y:auto;padding:8px 10px;line-height:1.65;font-size:13px;color:#b0b8c0;contain:layout style}
.asr3-text-scroll::-webkit-scrollbar{width:5px}
.asr3-text-scroll::-webkit-scrollbar-thumb{background:#30363d;border-radius:4px}
.asr3-seg{padding:6px 10px;margin:3px 0;border-radius:5px;border-left:3px solid #58a6ff;
    background:rgba(88,166,255,.05);will-change:transform,opacity}
.asr3-sp-label{display:inline-block;font-size:11px;font-weight:600;margin-right:4px;padding:0 5px;border-radius:3px}
.asr3-kw{display:inline-block;margin:2px 3px 2px 0;padding:1px 6px;border-radius:3px;
    background:rgba(88,166,255,.1);color:#58a6ff;font-size:11px;border:1px solid rgba(88,166,255,.15)}
.asr3-corr-new{color:#3fb950;font-weight:700}
.asr3-corr-old{text-decoration:line-through;color:#f85149;font-size:11px;margin:0 2px}
@keyframes asr3-in{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:translateY(0)}}
.asr3-in{animation:asr3-in .12s ease}
.asr3-toast{position:fixed;bottom:80px;right:20px;padding:8px 14px;border-radius:6px;
    color:#c9d1d9;font-size:12px;z-index:999999;animation:asr3-toast-in .25s ease;
    pointer-events:none;background:rgba(22,27,34,.96);border:1px solid #30363d;
    backdrop-filter:blur(8px);box-shadow:0 4px 16px rgba(0,0,0,.5)}
.asr3-toast.ok{border-color:#3fb950}
.asr3-toast.err{border-color:#f85149}
.asr3-toast.loading{border-color:#58a6ff}
@keyframes asr3-toast-in{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
@keyframes asr3-blink{0%,100%{opacity:1}50%{opacity:0}}
#asr3-sub{position:fixed!important;z-index:2147483646!important;
    background:rgba(0,0,0,.82);backdrop-filter:blur(6px);
    border-radius:8px;padding:10px 20px;text-align:center;
    color:#fff;font-size:18px;font-weight:600;line-height:1.5;
    letter-spacing:1px;display:none;pointer-events:auto;cursor:move;
    text-shadow:0 1px 3px rgba(0,0,0,.6);
    transition:opacity .25s;min-height:36px;user-select:none}
.asr3-sel,.asr3-inp{border:1px solid #30363d;border-radius:5px;padding:4px 6px;font-size:11px;
    background:#0d1117;color:#c9d1d9;outline:none;transition:border-color .15s}
.asr3-sel:focus,.asr3-inp:focus{border-color:#58a6ff}
`;
    document.head.appendChild(s);
}

const p = document.createElement('div');
p.id = 'asr-panel-v3';
p.innerHTML = `<div id="asr-v3">
    <div class="asr3-hdr"><b>🎤 LiveSpeech2Text V1.0</b>
        <span class="btns">
            <button id="asr3-sub-btn" title="显示/隐藏字幕条" style="font-size:12px">💬</button>
            <button id="asr3-launch" title="一键启动本地服务" style="background:rgba(63,185,80,.15);border-color:#3fb950;color:#3fb950">🟢</button>
            <button id="asr3-min">─</button>
            <button id="asr3-close">✕</button>
        </span></div>
    <div class="asr3-body">
        <div id="asr3-conn" class="asr3-bar" style="background:rgba(248,81,73,.1);color:#f85149">🔴 未连接</div>
        <div id="asr3-st" class="asr3-bar" style="background:rgba(63,185,80,.06);color:#3fb950">准备就绪</div>
        <div style="display:flex;gap:5px">
            <button id="asr3-start" class="asr3-bt1" style="background:#3fb950;border-color:#3fb950;color:#fff">▶ 标签页</button>
            <button id="asr3-start-full" class="asr3-bt1" style="background:#58a6ff;border-color:#58a6ff;color:#fff">▶ 全屏</button>
            <button id="asr3-stop" class="asr3-bt1" style="background:#f85149;border-color:#f85149;color:#fff" disabled>⏹ 停止</button></div>
        <div style="display:flex;gap:4px">
            <button id="asr3-clr" class="asr3-bt2">🗑 清除</button>
            <button id="asr3-rpt" class="asr3-bt2">📄 报告</button>
            <button id="asr3-save" class="asr3-bt2">💾 保存</button>
            <button id="asr3-log" class="asr3-bt2">📋 日志</button></div>
        <div id="asr3-kws" style="min-height:18px;max-height:46px;overflow-y:auto;font-size:11px;line-height:1.8;contain:layout style"></div>
        <div style="display:flex;gap:4px">
            <select id="asr3-cat" class="asr3-sel" style="max-width:72px">
                <option value="speaker">主讲人</option>
                <option value="other">关键词</option></select>
            <input id="asr3-inp" class="asr3-inp" placeholder="输入词或短语..." style="flex:1">
            <button id="asr3-add" style="padding:3px 8px;border:0;border-radius:5px;background:#58a6ff;color:#fff;cursor:pointer;font-size:11px;white-space:nowrap">+ 添加</button></div>
        <div style="font-size:11px;color:#8b949e;display:flex;justify-content:space-between">
            <span id="asr3-tm">0.0秒</span><span id="asr3-cnt">0条 | 0字</span></div>
        <div class="asr3-text-box" style="position:relative">
        <div id="asr3-partial" style="display:none;position:absolute;top:0;left:0;right:0;z-index:10;padding:6px 10px;font-size:13px;color:#8b949e;font-style:italic;line-height:1.5;background:rgba(13,17,23,.92);backdrop-filter:blur(4px);border-bottom:1px solid #21262d"></div>
        <div id="asr3-txt" class="asr3-text-scroll">
            <div style="text-align:center;color:#484f58;padding-top:40px">
                <p style="font-size:28px;margin-bottom:10px">🎤</p>
                <p>点击「开始」启动识别</p>
                <p style="font-size:10px;margin-top:4px">选择「整个屏幕」共享</p></div></div></div></div></div>`;

const sub = document.createElement('div');
sub.id = 'asr3-sub';
sub.innerHTML = '<span id="asr3-sub-txt"></span><span id="asr3-sub-cur" style="display:inline-block;width:2px;height:18px;background:#fff;margin-left:2px;vertical-align:middle;animation:asr3-blink 0.8s infinite"></span>';
document.body.appendChild(sub);

var _subVisible = true;
var _subUserPos = null;

function _findVideoPlayer() {
    const vs = document.querySelectorAll('video');
    for (const v of vs) {
        if (v.offsetWidth > 300 && v.offsetHeight > 200) return v;
    }
    return null;
}

function _repositionSub() {
    const vp = _findVideoPlayer();
    if (_subUserPos) {
        sub.style.left = _subUserPos.left + 'px';
        sub.style.top = _subUserPos.top + 'px';
        sub.style.bottom = 'auto';
        return;
    }
    if (vp) {
        const rect = vp.getBoundingClientRect();
        const w = Math.round(rect.width * 0.618);
        sub.style.width = Math.max(w, 200) + 'px';
        sub.style.left = Math.round(rect.left + (rect.width - w) / 2) + 'px';
        sub.style.bottom = (window.innerHeight - rect.bottom + 60) + 'px';
        sub.style.top = 'auto';
    } else {
        sub.style.width = Math.round(window.innerWidth * 0.5) + 'px';
        sub.style.left = Math.round(window.innerWidth * 0.25) + 'px';
        sub.style.bottom = '80px';
        sub.style.top = 'auto';
    }
}

function _showSubtitle(text) {
    // 仅当前可见标签页才显示字幕条，避免多页面同时显示
    if (!_subVisible || document.hidden) return;
    _repositionSub();
    $('asr3-sub-txt').textContent = text;
    sub.style.display = 'block';
}

function _hideSubtitle() {
    sub.style.display = 'none';
    $('asr3-sub-txt').textContent = '';
}

// 标签页切到后台时自动隐藏字幕条
document.addEventListener('visibilitychange', function() {
    if (document.hidden) {
        _hideSubtitle();
    }
});

function _toggleSubtitle() {
    _subVisible = !_subVisible;
    const btn = $('asr3-sub-btn');
    if (btn) {
        btn.textContent = _subVisible ? '💬' : '🚫';
        btn.style.opacity = _subVisible ? '1' : '0.5';
        btn.title = _subVisible ? '隐藏字幕条' : '显示字幕条';
    }
    if (!_subVisible) {
        _hideSubtitle();
    }
    toast(_subVisible ? '💬 字幕条已开启' : '🚫 字幕条已关闭', _subVisible ? 'ok' : '', 1500);
}

(function(){
    var dragging = false, sx = 0, sy = 0;
    sub.onmousedown = function(e) {
        if (e.target.tagName === 'BUTTON') return;
        dragging = true;
        sx = e.clientX - sub.offsetLeft;
        sy = e.clientY - sub.offsetTop;
        e.preventDefault();
    };
    document.addEventListener('mousemove', function(e) {
        if (!dragging) return;
        _subUserPos = {left: e.clientX - sx, top: e.clientY - sy};
        sub.style.left = _subUserPos.left + 'px';
        sub.style.top = _subUserPos.top + 'px';
        sub.style.bottom = 'auto';
    });
    document.addEventListener('mouseup', function() { dragging = false; });
})();

function _ensurePanel() {
    if (_panelClosedByUser) return false;
    if (!isVideoPage()) return false;
    if (document.getElementById('asr-panel-v3')) return true;
    if (p.parentNode === null && isVideoPage()) { document.body.appendChild(p); _panelInjected = true; bindEvents(); connect(); }
    return document.getElementById('asr-panel-v3') !== null;
}

setInterval(() => {
    if (_ensurePanel() && _pendingSegs.length > 0) {
        const segs = _pendingSegs.splice(0);
        segs.forEach(s => addSeg(s.text,s.speaker,s.ocrFixed,s.ocrCount,s.segTime,s.segDur,s.gapAudio,s.corrections,s.isHost,s.originalText));
    }
}, 1000);

window.addEventListener('resize', () => {
    if (sub.style.display === 'block') _repositionSub();
});

function $(id) { return document.getElementById(id); }
function L(m) { console.log('[ASR] '+m); }

function bindEvents() {
    if (_eventsBound) return;
    _eventsBound = true;
    const bind = (id, fn) => { const el = $(id); if (el) el.onclick = fn; };

    bind('asr3-close', () => { _panelClosedByUser=true; cleanup(); _wsClose(); p.remove(); _pendingSegs.length = 0; });
    bind('asr3-min', () => {
        const m = $('asr-v3');
        if (!m) return;
        const b = m.querySelector('.asr3-body');
        if (b.style.display === 'none') {
            b.style.display = ''; m.style.height = savedH+'px'; m.style.width = savedW+'px';
            m.style.resize = 'both'; m.style.minHeight = '400px'; m.style.minWidth = '300px';
            $('asr3-min').textContent = '─';
        } else {
            savedW = m.offsetWidth; savedH = m.offsetHeight;
            b.style.display = 'none'; m.style.height = 'auto'; m.style.width = savedW+'px';
            m.style.resize = 'none'; m.style.minHeight = '0'; m.style.minWidth = '0';
            $('asr3-min').textContent = '□';
        }
    });
    bind('asr3-start', () => startRec('tab'));
    bind('asr3-start-full', () => startRec('full'));
    bind('asr3-stop', stopRec);
    bind('asr3-clr', () => { send({type:'clear'}); clearUI(); });
    bind('asr3-rpt', () => send({type:'generate_report'}));
    bind('asr3-save', () => { if (segCount===0) { alert('还没有识别内容，无法保存'); return; } send({type:'save_report'}); });
    bind('asr3-log', () => { if (segCount===0) { alert('还没有识别内容，无法导出日志'); return; } send({type:'save_log'}); });
    bind('asr3-sub-btn', _toggleSubtitle);
    bind('asr3-launch', () => {
        toast('🚀 正在启动本地服务...', 'loading', 5000);
        try {
            window.open(LAUNCH_URL, '_blank');
            setTimeout(() => {
                if (_wsReady) toast('✅ 服务启动成功！已连接', 'ok', 3000);
                else toast('⏳ 服务启动中，请等待连接...', 'loading', 6000);
            }, 5000);
        } catch(e) { toast('❌ 启动失败: '+e.message, 'err', 5000); }
    });
    bind('asr3-add', () => {
        const inp = $('asr3-inp'); if (!inp) return;
        const kw = inp.value.trim();
        const cat = ($('asr3-cat')||{}).value||'other';
        if (kw) { send({type:'keyword_add',keyword:kw,category:cat}); inp.value=''; }
    });
    const inp = $('asr3-inp');
    if (inp) {
        inp.onkeydown = e => { if (e.key==='Enter') $('asr3-add')?.click(); };
    }
    (function(){
        const hdr = p.querySelector('.asr3-hdr'), el = $('asr-v3');
        if (!hdr||!el) return;
        let d=false,ox=0,oy=0;
        hdr.onmousedown = e => { if(e.target.tagName==='BUTTON') return; d=true; const r=el.getBoundingClientRect(); ox=e.clientX-r.left; oy=e.clientY-r.top; e.preventDefault(); };
        document.addEventListener('mousemove', e => { if(!d) return; el.style.right='auto'; el.style.left=(e.clientX-ox)+'px'; el.style.top=Math.max(0,e.clientY-oy)+'px'; });
        document.addEventListener('mouseup', () => { d=false; });
    })();
}

function cleanup() {
    if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null; }
    if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
    isRecording = false;
}

function connect() {
    setConn(false, '⏳ 连接中...');
    _wsInit();
    _wsWorker.postMessage({t: 'c'});
}

function setConn(ok, reason) {
    const el = $('asr3-conn');
    if (!el) return;
    if (ok) {
        el.style.background = 'rgba(63,185,80,.1)'; el.style.color = '#3fb950';
        el.textContent = '🟢 已连接';
    } else {
        el.style.background = 'rgba(248,81,73,.1)'; el.style.color = '#f85149';
        el.textContent = reason || '🔴 未连接';
    }
    const lb = $('asr3-launch');
    if (lb) lb.style.display = ok ? 'none' : '';
}

function send(d) { _wsSend(JSON.stringify(d)); }

function onMsg(data) {
    switch(data.type) {
        case 'welcome':
            if (Date.now()-lastWelcomeTime>5000) $('asr3-st').textContent = '模型: '+(data.model||'?')+' | 就绪';
            lastWelcomeTime = Date.now(); break;
        case 'status':
            const st = $('asr3-st');
            if (data.status==='recording') { st.style.background='rgba(248,81,73,.08)'; st.style.color='#f85149'; st.textContent='🔴 识别中...'; }
            if (data.status==='stopped'&&data.full_text) showReport(data.full_text);
            if (data.status==='cleared') clearUI();
            if (data.status==='stopped') _hideSubtitle();
            break;
        case 'recording_state':
            if (data.recording) {
                isRecording = true;
                $('asr3-start').disabled = true; $('asr3-start-full').disabled = true;
                $('asr3-stop').disabled = false;
                const rst = $('asr3-st');
                rst.style.background = 'rgba(248,81,73,.08)';
                rst.style.color = '#f85149';
                rst.textContent = '🔴 识别中...（网页端）';
            } else {
                if (!isRecording) {
                    $('asr3-start').disabled = false; $('asr3-start-full').disabled = false;
                    $('asr3-stop').disabled = true;
                    const rst = $('asr3-st');
                    rst.style.background = 'rgba(63,185,80,.06)';
                    rst.style.color = '#3fb950';
                    rst.textContent = '准备就绪';
                    _hideSubtitle();
                }
            }
            break;
        case 'transcription':
            addSeg(data.text,data.speaker,data.kw_corrected,data.kw_count,data.seg_time,data.seg_dur,data.gap_audio,data.corrections,data.is_host,data.original_text,data.timestamp);
            updStats(data);
            if (data.keywords) updKws(data.keywords, keywordStore);
            break;
        case 'partial':
            var p = $('asr3-partial');
            if (p) { p.style.display = 'block'; p.innerHTML = '<span style="color:#8b949e;font-style:italic;">' + eHtml(data.text) + '</span><span class="asr3-cursor" style="display:inline-block;width:2px;height:14px;background:#58a6ff;margin-left:2px;vertical-align:middle;animation:asr3-blink 0.8s infinite"></span>'; }
            _showSubtitle(data.text);
            break;
        case 'keywords_updated':
            if (data.keyword_store) keywordStore = data.keyword_store;
            updKws(data.keywords, data.keyword_store);
            break;
        case 'report': showReport(data.content); break;
        case 'save_report': downloadReport(data.content, data.filename); break;
        case 'save_log': downloadLog(data.content, data.filename); break;
        case 'speaker_profile_matched':
            if (data.library_matched) { matchedSpeakers.add(data.keyword); toast('✅ "'+data.keyword+'" → 画像库命中','ok',4000); }
            else toast('📝 "'+data.keyword+'" 未匹配画像库','loading',5000);
            updKws(keywords, keywordStore); break;
        case 'error':
            L('⚠️ '+data.message);
            $('asr3-st').textContent = '错误: '+data.message;
            $('asr3-st').style.background = 'rgba(248,81,73,.12)';
            $('asr3-st').style.color = '#f85149';
            isRecording = false; $('asr3-start').disabled = false; $('asr3-start-full').disabled = false; $('asr3-stop').disabled = true;
            _hideSubtitle();
            break;
    }
}

function getSpeakerColor(speaker) {
    if (!speaker) return null;
    const m = speaker.match(/\d+/);
    const id = m ? parseInt(m[0]) % SP_COLORS.length : 0;
    if (!(speaker in speakerColors)) speakerColors[speaker] = id;
    return SP_COLORS[speakerColors[speaker]];
}

function addSeg(text, speaker, ocrFixed, ocrCount, segTime, segDur, gapAudio, corrections, isHost, originalText, timestamp) {
    if (_panelClosedByUser) return;  // 用户已关闭面板，直接丢弃，防止 _pendingSegs 无限增长
    if (!_ensurePanel()) { if (_pendingSegs.length < 50) _pendingSegs.push({text,speaker,ocrFixed,ocrCount,segTime,segDur,gapAudio,corrections,isHost,originalText}); return; }
    const box = $('asr3-txt');
    if (!box) { if (_pendingSegs.length < 50) _pendingSegs.push({text,speaker,ocrFixed,ocrCount,segTime,segDur,gapAudio,corrections,isHost,originalText}); return; }
    var pp = $('asr3-partial'); if (pp) { pp.style.display = 'none'; pp.innerHTML = ''; }
    _hideSubtitle();
    if (segCount === 0) box.textContent = '';
    segCount++;

    while (box.children.length >= MAX_SEGMENTS) box.removeChild(box.firstChild);
    if (speaker && speaker !== lastSpeakerId) lastSpeakerId = speaker;
    const clr = getSpeakerColor(speaker||'');

    const div = document.createElement('div');
    div.className = 'asr3-seg asr3-in';
    if (clr) { div.style.background = clr.bg; div.style.borderLeftColor = clr.border; }

    if (timestamp) {
        const ts = document.createElement('span');
        ts.style.cssText = 'font-size:10px;color:#484f58;margin-right:5px;font-family:monospace';
        try {
            const d = new Date(timestamp);
            ts.textContent = d.getHours().toString().padStart(2,'0')+':'+d.getMinutes().toString().padStart(2,'0')+':'+d.getSeconds().toString().padStart(2,'0');
        } catch(e) {
            ts.textContent = 'T+'+segTime.toFixed(1)+'s';
        }
        div.appendChild(ts);
    }

    if (speaker) {
        const lbl = document.createElement('span');
        lbl.className = 'asr3-sp-label';
        lbl.textContent = speaker;
        if (clr) { lbl.style.color = clr.name; lbl.style.background = clr.border+'22'; }
        div.appendChild(lbl);
    }
    if (ocrFixed && (!corrections || corrections.length===0)) {
        const bd = document.createElement('span');
        bd.style.cssText = 'font-size:10px;color:#d2991d;margin-right:3px;font-weight:700';
        bd.textContent = '[KW]';
        div.appendChild(bd);
    }

    if (corrections && corrections.length > 0) {
        console.log('[ASR] corrections:', corrections.length, 'originalText:', (originalText||'').substring(0,30), 'text:', (text||'').substring(0,30));
        let dt = eHtml(originalText||text);
        for (let c of corrections) {
            const old = c[0], kw = c[1];
            const re = new RegExp(eHtml(old).replace(/[.*+?^${}()|[\]\\]/g,'\\$&'),'g');
            dt = dt.replace(re, '<span class="asr3-corr-new">'+eHtml(kw)+'</span>');
        }
        const ts = document.createElement('span');
        ts.innerHTML = dt;
        div.appendChild(ts);
    } else {
        div.appendChild(document.createTextNode(originalText || text));
    }
    box.appendChild(div);

    requestAnimationFrame(() => { box.scrollTop = box.scrollHeight; });
}

function showReport(txt) {
    const el = $('asr3-txt');
    if (!el) return;
    el.innerHTML = '<div style="color:#c9d1d9;padding:4px 0;line-height:1.8;white-space:pre-wrap">'+txt+'</div>';
}

function downloadReport(content, filename) {
    const blob = new Blob([content],{type:'text/markdown;charset=utf-8'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = filename||'asr_report.md';
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function downloadLog(content, filename) {
    const blob = new Blob([content],{type:'application/json;charset=utf-8'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = filename||'asr_log.json';
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function updStats(data) {
    const t=$('asr3-tm'), c=$('asr3-cnt');
    if (t) t.textContent = (data.duration||0).toFixed(1)+'秒';
    if (c) c.textContent = segCount+'条 | '+(data.full_text?data.full_text.length:0)+'字';
}

function updKws(kws, ks) {
    if (kws) keywords = [...new Set([...kws])];
    const box = $('asr3-kws');
    if (!box) return;
    if (ks && Object.keys(ks).length > 0) {
        const cc = {speaker:'#3fb950', other:'#58a6ff'};
        let h = '';
        const shown = new Set();
        for (let cat of ['speaker','other']) {
            const words = ks[cat]; if (!words||!words.length) continue;
            for (let w of words) {
                if (shown.has(w)) continue; shown.add(w);
                const esc = eHtml(w);
                let icon = '', extra = '';
                if (cat==='speaker') {
                    icon='\u{1f464} ';
                    if (matchedSpeakers.has(w)) extra=' title="\u753b\u50cf\u5e93\u5df2\u5339\u914d"';
                    else extra=' title="\u672a\u5339\u914d\u753b\u50cf\u5e93" style="opacity:0.55"';
                }
                h += '<span class="asr3-kw" style="border-color:'+(cc[cat]||'#888')+'"'+extra+'>'+icon+esc+'</span>';
            }
        }
        box.innerHTML = h || '<span style="color:#484f58">\u6682\u65e0\u5206\u7c7b\u5173\u952e\u8bcd</span>';
    } else {
        box.innerHTML = keywords.slice(-20).map(k => '<span class="asr3-kw">'+eHtml(k)+'</span>').join('');
    }
}

function clearUI() {
    segCount = 0; keywords = []; speakerColors = {}; matchedSpeakers = new Set();
    autoAddedSpeakers = new Set(); keywordStore = {};
    const el = $('asr3-txt');
    if (el) el.innerHTML = '<div style="text-align:center;color:#484f58;padding-top:40px"><p style="font-size:28px">🗑</p><p>已清除</p></div>';
    $('asr3-tm').textContent = '0.0秒'; $('asr3-cnt').textContent = '0条 | 0字'; $('asr3-kws').innerHTML = '';
    var pp = $('asr3-partial'); if (pp) { pp.style.display = 'none'; pp.innerHTML = ''; }
    _hideSubtitle();
}

async function startRec(mode) {
    if (!_wsReady) { alert('服务未连接！请启动 start.bat'); return; }
    try {
        const isTab = (mode === 'tab');
        const opts = isTab
            ? {audio:true, video:true, preferCurrentTab:true}
            : {audio:true, video:true};
        mediaStream = await navigator.mediaDevices.getDisplayMedia(opts);
        if (!mediaStream.getAudioTracks().length) {
            mediaStream.getTracks().forEach(t=>t.stop()); mediaStream = null;
            alert(isTab
                ? '标签页模式未获取到音频。\n请在弹出的对话框中选择"Chrome标签页"，并确保该标签页正在播放音频。'
                : '未获取到音频轨道，请确保在分享对话框中勾选了"分享音频"。');
            return;
        }
        audioCtx = new AudioContext({sampleRate:48000});
        const src = audioCtx.createMediaStreamSource(mediaStream);
        const proc = audioCtx.createScriptProcessor(8192,1,1);
        proc.onaudioprocess = e => {
            if (isRecording && _wsReady) _wsSendBinary(new Float32Array(e.inputBuffer.getChannelData(0)).buffer);
        };
        src.connect(proc); proc.connect(audioCtx.destination);
        isRecording = true;
        send({type:'start'});

        const pu = location.href;
        const pt = (pu.includes('live.bilibili.com')||pu.includes('douyu.com/')||pu.includes('huya.com/'))?'live':(pu.includes('bilibili.com/video/')||pu.includes('youtube.com/watch'))?'video':'web';
        let vo = 0;
        if (pt==='video') {
            const vs = document.querySelectorAll('video');
            for (const v of vs) { if (v.duration&&v.currentTime>0) { vo=v.currentTime; v.currentTime=0; break; } }
        }

        setTimeout(async () => {
            const cr = detectCreator();
            const platform_ = (()=>{
                const u=location.href; if(u.includes('bilibili')) return 'bilibili';
                if(u.includes('douyu')) return 'douyu'; if(u.includes('huya')) return 'huya'; return 'web';
            })();
            // 始终发送 page_creator（带 URL），即使客户端未检测到也让服务端兜底
            send({type:'page_creator',creator:cr||'',page_type:pt,video_offset:vo,platform:platform_,url:location.href});
            if (cr&&!autoAddedSpeakers.has(cr)) {
                autoAddedSpeakers.add(cr);
                if (!keywordStore||!keywordStore['speaker']||!keywordStore['speaker'].includes(cr)) {
                    send({type:'keyword_add',keyword:cr,category:'speaker'});
                    toast('🎤 自动识别创作者: '+cr,'ok',4000);
                }
            }
            const title = detectTitle();
            if (title&&title.length>=4) send({type:'video_title',title:title});
        }, 2000);

        $('asr3-start').disabled = true; $('asr3-start-full').disabled = true; $('asr3-stop').disabled = false;
    } catch(e) { L('Record err: '+e.message); if (e.name!=='AbortError') alert('授权失败: '+(e.message||'用户取消')); }
}

function stopRec() {
    isRecording = false;
    send({type:'stop'});
    if (mediaStream) { mediaStream.getTracks().forEach(t=>t.stop()); mediaStream = null; }
    if (audioCtx) { audioCtx.close(); audioCtx = null; }
    $('asr3-start').disabled = false; $('asr3-start-full').disabled = false; $('asr3-stop').disabled = true;
    _hideSubtitle();
}

function toast(msg, type, duration) {
    if (duration===undefined) duration=2500;
    const t = document.createElement('div');
    t.className = 'asr3-toast '+(type||'');
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => { t.remove(); }, duration);
}

L('LiveSpeech2Text V1.0 loaded');
if (isVideoPage()) injectPanel();

setInterval(() => {
    const url = location.href;
    if (url !== _lastUrl) {
        _lastUrl = url; _panelClosedByUser = false;
        if (isVideoPage()) injectPanel(); else removePanel();
    }
    if (!_panelInjected && !_panelClosedByUser && isVideoPage()) injectPanel();
}, 2000);
})();

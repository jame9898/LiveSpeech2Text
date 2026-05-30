// ==UserScript==
// @name         实时语音识别面板 v1.0
// @namespace    asr-panel-v3
// @version      1.0
// @description  视频页面内嵌语音识别面板 — 高性能优化版 · VAD断句 + 说话人分离 + 口音矫正
// @match        *://*/*
// @grant        none
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
if (window.self !== window.top) return;

let ws = null, isRecording = false, audioCtx = null, mediaStream = null;
let reconnectTimer = null, reconnectAttempts = 0;
let segCount = 0, lastWelcomeTime = 0;
let keywords = [], keywordStore = {};
let speakerColors = {}, matchedSpeakers = new Set();
let autoAddedSpeakers = new Set(), autoLoadedTopics = new Set();
let savedW = 420, savedH = 680;
let heartbeatTimer = null, pingTimer = null;
let _panelInjected = false, _eventsBound = false;
let _lastUrl = location.href, _panelClosedByUser = false;
let lastSpeakerId = 'Speaker0';
let _pendingSegs = [];

function isVideoPage() {
    const u = location.href;
    const pats = ['/video/','/watch','/play/','/tv/','/live/','bilibili.com/bangumi/play',
        'youtube.com/shorts/','v.douyin.com/','live.bilibili.com',
        'douyu.com/','huya.com/','cc.163.com/','egame.qq.com/'];
    for (const p of pats) if (u.includes(p)) return true;
    const vs = document.querySelectorAll('video');
    for (const v of vs) {
        if (v.muted) continue;
        if (v.src || (v.querySelector('source') && v.querySelector('source').src)) return true;
        if (v.duration > 0 || v.readyState >= 2) return true;
    }
    return false;
}

function detectCreator() { /* same as v2 */ return null; }
function detectTags() { return []; }
function detectTitle() { return ''; }
async function detectLiveSquad() { return []; }

{ // inject original detection functions
    const _ddc = detectCreator, _ddt = detectTags, _ddti = detectTitle, _ddls = detectLiveSquad;
    detectCreator = function() {
        const u = location.href;
        if (u.includes('bilibili.com/video/')) {
            const sels = ['[class*="up-name"]','.up-name','.username','[class*="up-detail"] a','a[href*="space.bilibili.com"]'];
            for (const sel of sels) {
                const el = document.querySelector(sel);
                if (el) { const t = el.textContent.trim(); if (t.length>=2&&t.length<30&&!t.includes('关注')&&!t.includes('粉丝')) return t; }
            }
            const ma = document.querySelector('meta[name="author"]');
            if (ma) { const v = ma.getAttribute('content'); if (v&&v.length>=2&&v.length<30) return v; }
            return null;
        }
        if (u.includes('douyu.com/')&&!u.includes('douyu.com/directory')) {
            const sels = ['[class*="Title-anchorName"]','[class*="AnchorName"]','[class*="anchor-name"]'];
            for (const sel of sels) { const el = document.querySelector(sel); if (el) { const t=el.textContent.trim(); if(t.length>=2&&t.length<30) return t; } }
            return null;
        }
        if (u.includes('huya.com/')&&/\d+/.test(u)) {
            const sels = ['[class*="host-name"]','[class*="anchor-name"]'];
            for (const sel of sels) { const el = document.querySelector(sel); if (el) { const t=el.textContent.trim(); if(t.length>=2&&t.length<30) return t; } }
            return null;
        }
        return null;
    };
    detectTags = function() {
        const tags = [], u = location.href;
        if (!u.includes('bilibili.com/video/')) return tags;
        const sels = ['.video-tag','.tag-link','[class*="video-tag"]','[class*="tag-area"] a'];
        const skip = ['关注','粉丝','投稿','视频','专栏','直播','展开','收起','更多'];
        for (const sel of sels) {
            document.querySelectorAll(sel).forEach(el => {
                const t = el.textContent.trim();
                if (t&&t.length>=1&&t.length<20&&!tags.includes(t)&&!skip.some(w=>t.includes(w))) tags.push(t);
            });
        }
        return tags;
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
    detectLiveSquad = async function() {
        const u = location.href;

        if (u.includes('douyu.com/') && /\d+/.test(u)) {
            const members = [], seen = new Set();
            try {
                const roomId = u.match(/\/(\d+)/);
                if (roomId) {
                    const r = await fetch(`https://www.douyu.com/betard/${roomId[1]}`, {credentials:'omit'});
                    const j = await r.json();
                    if (j.room && j.room.owner_name) {
                        seen.add(j.room.owner_name);
                        members.push(j.room.owner_name);
                    }
                }
            } catch(e) {}
            try {
                const sels = ['[class*="Title-anchorName"]','[class*="AnchorName"]',
                    '[class*="anchor-name"]','[class*="anchorName"]','[class*="host-name"]'];
                for (const sel of sels) {
                    const el = document.querySelector(sel);
                    if (el) {
                        const t = el.textContent.trim();
                        if (t.length>=2&&t.length<30&&!seen.has(t)) { seen.add(t); members.push(t); }
                    }
                }
            } catch(e) {}
            return members;
        }

        if (u.includes('huya.com/') && /\d+/.test(u)) {
            const members = [], seen = new Set();
            try {
                const sels = ['[class*="host-name"]','[class*="anchor-name"]',
                    '[class*="host-info"] [class*="name"]','[class*="live-title"] [class*="name"]'];
                for (const sel of sels) {
                    const el = document.querySelector(sel);
                    if (el) {
                        const t = el.textContent.trim();
                        if (t.length>=2&&t.length<30&&!seen.has(t)) { seen.add(t); members.push(t); }
                    }
                }
            } catch(e) {}
            return members;
        }

        if (!u.includes('live.bilibili.com')) return [];
        const members = [], seen = new Set();
        const BL = new Set(['哔哩哔哩','bilibili','友情链接','加入我们','服务协议','隐私政策','联系我们','关于我们',
            '帮助中心','意见反馈','下载APP','首页','直播','推荐','热门','番剧','关注','粉丝','人气',
            '正在直播','直播中','未开播','已结束','房间','主播','开播','下播','互动','礼物','弹幕',
            'PK','胜','负','守护','舰长','提督','总督','大航海','勋章','活动','公告','加载中','更多','万','亿']);
        function looksUser(t) {
            if (!t||t.length<2||t.length>20||BL.has(t)) return false;
            for (const b of BL) if (t===b||t.includes(b)) return false;
            if (/^\d+$/.test(t)||/^[\s\u3000-\u303f\uff00-\uffef]+$/u.test(t)) return false;
            return true;
        }
        try {
            const roomId = location.pathname.split('/').pop().replace(/[^0-9]/g,'');
            if (roomId) {
                const r = await fetch(`https://api.live.bilibili.com/xlive/web-room/v1/index/getRoomBaseInfo?req_biz=web_room_componet&room_ids=${roomId}`,{credentials:'omit'});
                const j = await r.json();
                if (j.code===0&&j.data&&j.data.by_room_ids) {
                    const rd = j.data.by_room_ids[Object.keys(j.data.by_room_ids)[0]];
                    if (rd&&rd.uname&&looksUser(rd.uname)&&!seen.has(rd.uname)) { seen.add(rd.uname); members.push(rd.uname); }
                }
            }
        } catch(e) {}
        try {
            const np = window.__NEPTUNE_IS_MY_WAIFU__;
            if (np) {
                const bi = np.baseInfoRes?.data||np.roomInfoRes?.data||{};
                const ri = bi.room_info||bi.anchor_info||{};
                if (ri.uname&&looksUser(ri.uname)&&!seen.has(ri.uname)) { seen.add(ri.uname); members.push(ri.uname); }
                if (np.pkInfoRes?.data) {
                    const pk = np.pkInfoRes.data;
                    (pk.anchor_list||pk.anchors||[]).forEach(a=>{
                        const n=a.uname||a.name||'';
                        if (n&&looksUser(n)&&!seen.has(n)) { seen.add(n); members.push(n); }
                    });
                }
            }
        } catch(e) {}
        return members;
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
    if (ws) { ws.close(); ws = null; }
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
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
.asr3-sel,.asr3-inp{border:1px solid #30363d;border-radius:5px;padding:4px 6px;font-size:11px;
    background:#0d1117;color:#c9d1d9;outline:none;transition:border-color .15s}
.asr3-sel:focus,.asr3-inp:focus{border-color:#58a6ff}
`;
    document.head.appendChild(s);
}

const p = document.createElement('div');
p.id = 'asr-panel-v3';
p.innerHTML = `<div id="asr-v3">
    <div class="asr3-hdr"><b>🎤 实时语音识别 v1.0</b>
        <span class="btns">
            <button id="asr3-launch" title="一键启动本地服务" style="background:rgba(63,185,80,.15);border-color:#3fb950;color:#3fb950">🟢</button>
            <button id="asr3-min">─</button>
            <button id="asr3-close">✕</button>
        </span></div>
    <div class="asr3-body">
        <div id="asr3-conn" class="asr3-bar" style="background:rgba(248,81,73,.1);color:#f85149">🔴 未连接</div>
        <div id="asr3-st" class="asr3-bar" style="background:rgba(63,185,80,.06);color:#3fb950">准备就绪</div>
        <div style="display:flex;gap:5px">
            <button id="asr3-start" class="asr3-bt1" style="background:#3fb950;border-color:#3fb950;color:#fff">▶ 开始</button>
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
                <option value="topic">话题</option>
                <option value="other">关键词</option></select>
            <input id="asr3-inp" class="asr3-inp" placeholder="输入词或短语..." style="flex:1">
            <button id="asr3-add" style="padding:3px 8px;border:0;border-radius:5px;background:#58a6ff;color:#fff;cursor:pointer;font-size:11px;white-space:nowrap">+ 添加</button>
            <button id="asr3-expand" style="padding:3px 8px;border:0;border-radius:5px;background:#d2991d;color:#fff;cursor:pointer;font-size:11px;white-space:nowrap;display:none">🔮 联想</button></div>
        <div style="font-size:11px;color:#8b949e;display:flex;justify-content:space-between">
            <span id="asr3-tm">0.0秒</span><span id="asr3-cnt">0条 | 0字</span></div>
        <div class="asr3-text-box"><div id="asr3-txt" class="asr3-text-scroll">
            <div style="text-align:center;color:#484f58;padding-top:40px">
                <p style="font-size:28px;margin-bottom:10px">🎤</p>
                <p>点击「开始」启动识别</p>
                <p style="font-size:10px;margin-top:4px">选择「整个屏幕」共享</p></div></div></div></div></div>`;

function _ensurePanel() {
    if (_panelClosedByUser) return false;
    if (!isVideoPage()) return false;
    if (document.getElementById('asr-panel-v3')) return true;
    if (p.parentNode === null && isVideoPage()) { document.body.appendChild(p); _panelInjected = true; }
    return document.getElementById('asr-panel-v3') !== null;
}

setInterval(() => {
    if (_ensurePanel() && _pendingSegs.length > 0) {
        const segs = _pendingSegs.splice(0);
        segs.forEach(s => addSeg(s.text,s.speaker,s.ocrFixed,s.ocrCount,s.segTime,s.segDur,s.gapAudio,s.corrections,s.isHost,s.originalText));
    }
}, 1000);

function $(id) { return document.getElementById(id); }
function L(m) { console.log('[ASR] '+m); }

function bindEvents() {
    if (_eventsBound) return;
    _eventsBound = true;
    const bind = (id, fn) => { const el = $(id); if (el) el.onclick = fn; };

    bind('asr3-close', () => { _panelClosedByUser=true; cleanup(); p.remove(); });
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
    bind('asr3-start', startRec);
    bind('asr3-stop', stopRec);
    bind('asr3-clr', () => { send({type:'clear'}); clearUI(); });
    bind('asr3-rpt', () => send({type:'generate_report'}));
    bind('asr3-save', () => { if (segCount===0) { alert('还没有识别内容，无法保存'); return; } send({type:'save_report'}); });
    bind('asr3-log', () => { if (segCount===0) { alert('还没有识别内容，无法导出日志'); return; } send({type:'save_log'}); });
    bind('asr3-launch', () => {
        toast('🚀 正在启动本地服务...', 'loading', 5000);
        try {
            window.open(LAUNCH_URL, '_blank');
            setTimeout(() => {
                if (ws&&ws.readyState===1) toast('✅ 服务启动成功！已连接', 'ok', 3000);
                else toast('⏳ 服务启动中，请等待连接...', 'loading', 6000);
            }, 5000);
        } catch(e) { toast('❌ 启动失败: '+e.message, 'err', 5000); }
    });
    bind('asr3-add', () => {
        const inp = $('asr3-inp'); if (!inp) return;
        const kw = inp.value.trim();
        const cat = ($('asr3-cat')||{}).value||'other';
        if (kw) { send({type:'keyword_add',keyword:kw,category:cat}); inp.value=''; $('asr3-expand').style.display='none'; }
    });
    const inp = $('asr3-inp');
    if (inp) {
        inp.onkeydown = e => { if (e.key==='Enter') $('asr3-add')?.click(); };
        inp.oninput = () => { $('asr3-expand').style.display = inp.value.trim().length>=2 ? '' : 'none'; };
    }
    bind('asr3-expand', () => {
        const inp = $('asr3-inp'); if (!inp) return;
        const kw = inp.value.trim();
        const cat = ($('asr3-cat')||{}).value||'other';
        if (!kw) return;
        const btn = $('asr3-expand'); if (!btn) return;
        btn.disabled = true; btn.textContent = '⏳ 联想中...';
        send({type:'keyword_expand',keyword:kw,category:cat,use_llm:false});
        inp.value = '';
        setTimeout(() => { btn.disabled=false; btn.textContent='🔮 联想'; btn.style.display='none'; }, 3000);
    });

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

function connect(tryIdx) {
    if (tryIdx === undefined) tryIdx = 0;
    if (tryIdx >= WS_URLS.length) {
        setConn(false, '🔴 无法连接');
        if (!reconnectTimer) reconnectTimer = setTimeout(() => connect(0), Math.min(RECONNECT_BASE*Math.pow(1.5,reconnectAttempts),RECONNECT_MAX));
        reconnectAttempts++;
        return;
    }
    const url = WS_URLS[tryIdx];
    try {
        ws = new WebSocket(url);
        ws.onopen = () => {
            setConn(true);
            reconnectAttempts = 0;
            if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
            pingTimer = setInterval(() => send({type:'ping'}), PING_INTERVAL);
        };
        ws.onmessage = e => { try { onMsg(JSON.parse(e.data)); } catch(x){} };
        ws.onclose = e => {
            setConn(false, '🔴 断开 ('+(e.code||'?')+')');
            if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
            ws = null;
            if (!_panelInjected) return;
            const delay = Math.min(RECONNECT_BASE*Math.pow(1.5,reconnectAttempts),RECONNECT_MAX);
            reconnectAttempts++;
            if (!reconnectTimer) reconnectTimer = setTimeout(() => connect(0), delay);
        };
        ws.onerror = () => {
            setConn(false, '🔴 无法连接');
            if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
            ws?.close();
        };
    } catch(e) {
        const delay = Math.min(RECONNECT_BASE*Math.pow(1.5,reconnectAttempts),RECONNECT_MAX);
        reconnectAttempts++;
        if (!reconnectTimer) reconnectTimer = setTimeout(() => connect(0), delay);
    }
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

function send(d) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(d)); }

function onMsg(data) {
    switch(data.type) {
        case 'welcome':
            if (Date.now()-lastWelcomeTime>5000) $('asr3-st').textContent = '模型: '+(data.model||'?')+' | 就绪';
            lastWelcomeTime = Date.now(); break;
        case 'status':
            const st = $('asr3-st');
            if (data.status==='recording') { st.style.background='rgba(248,81,73,.08)'; st.style.color='#f85149'; st.textContent='🔴 识别中...'; }
            if (data.status==='stopped'&&data.full_text) showReport(data.full_text);
            if (data.status==='cleared') clearUI(); break;
        case 'recording_state':
            if (data.recording) {
                isRecording = true;
                $('asr3-start').disabled = true;
                $('asr3-stop').disabled = false;
                const rst = $('asr3-st');
                rst.style.background = 'rgba(248,81,73,.08)';
                rst.style.color = '#f85149';
                rst.textContent = '🔴 识别中...（网页端）';
            } else {
                if (!isRecording) {
                    $('asr3-start').disabled = false;
                    $('asr3-stop').disabled = true;
                    const rst = $('asr3-st');
                    rst.style.background = 'rgba(63,185,80,.06)';
                    rst.style.color = '#3fb950';
                    rst.textContent = '准备就绪';
                }
            }
            break;
        case 'transcription':
            addSeg(data.text,data.speaker,data.ocr_corrected,data.ocr_count,data.seg_time,data.seg_dur,data.gap_audio,data.corrections,data.is_host,data.original_text);
            updStats(data);
            if (data.keywords) updKws(data.keywords, keywordStore); break;
        case 'keywords_updated':
            if (data.keyword_store) keywordStore = data.keyword_store;
            updKws(data.keywords, data.keyword_store);
            if (data.topic_auto_loaded&&data.topic_auto_loaded.count>0) {}
            break;
        case 'report': showReport(data.content); break;
        case 'save_report': downloadReport(data.content, data.filename); break;
        case 'save_log': downloadLog(data.content, data.filename); break;
        case 'speaker_profile_matched':
            if (data.library_matched) { matchedSpeakers.add(data.keyword); toast('✅ "'+data.keyword+'" → 画像库命中','ok',4000); }
            else toast('📝 "'+data.keyword+'" 未匹配画像库','loading',5000);
            updKws(keywords, keywordStore); break;
        case 'voice_profiles_saved':
            if (data.profiles&&data.profiles.length>0) toast('💾 声纹已保存: '+data.profiles.map(p=>p.saved_name).join(', '),'ok',5000);
            break;
        case 'error':
            L('⚠️ '+data.message);
            $('asr3-st').textContent = '错误: '+data.message;
            $('asr3-st').style.background = 'rgba(248,81,73,.12)';
            $('asr3-st').style.color = '#f85149';
            isRecording = false; $('asr3-start').disabled = false; $('asr3-stop').disabled = true;
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

function addSeg(text, speaker, ocrFixed, ocrCount, segTime, segDur, gapAudio, corrections, isHost, originalText) {
    if (!_ensurePanel()) { _pendingSegs.push({text,speaker,ocrFixed,ocrCount,segTime,segDur,gapAudio,corrections,isHost,originalText}); return; }
    const box = $('asr3-txt');
    if (!box) { _pendingSegs.push({text,speaker,ocrFixed,ocrCount,segTime,segDur,gapAudio,corrections,isHost,originalText}); return; }
    if (segCount === 0) box.textContent = '';
    segCount++;

    while (box.children.length >= MAX_SEGMENTS) box.removeChild(box.firstChild);
    if (speaker && speaker !== lastSpeakerId) lastSpeakerId = speaker;
    const clr = getSpeakerColor(speaker||'');

    const div = document.createElement('div');
    div.className = 'asr3-seg asr3-in';
    if (clr) { div.style.background = clr.bg; div.style.borderLeftColor = clr.border; }

    if (segTime !== undefined && segTime !== null) {
        const ts = document.createElement('span');
        ts.style.cssText = 'font-size:10px;color:#484f58;margin-right:5px;font-family:monospace';
        ts.textContent = 'T+'+segTime.toFixed(1)+'s';
        div.appendChild(ts);
    }

    if (gapAudio !== undefined && gapAudio > 1.5 && segCount > 1) {
        const gb = document.createElement('span');
        gb.style.cssText = 'font-size:10px;color:#f85149;margin-right:4px;font-weight:700';
        gb.textContent = '⚠漏'+gapAudio.toFixed(1)+'s';
        gb.title = '距上段音频间隔 '+gapAudio.toFixed(1)+'秒';
        div.appendChild(gb);
    }

    if (speaker) {
        const lbl = document.createElement('span');
        lbl.className = 'asr3-sp-label';
        lbl.textContent = speaker;
        if (clr) { lbl.style.color = clr.name; lbl.style.background = clr.border+'22'; }
        div.appendChild(lbl);
    }
    if (isHost) {
        const crown = document.createElement('span');
        crown.style.cssText = 'font-size:11px;margin-left:2px;color:#d2991d;font-weight:700';
        crown.textContent = '👑主播';
        crown.title = '本直播间主播';
        div.appendChild(crown);
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
        div.appendChild(document.createTextNode(text));
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
        const cc = {speaker:'#3fb950', topic:'#d2991d', other:'#58a6ff'};
        let h = '';
        const shown = new Set();
        for (let cat of ['speaker','topic','other']) {
            const words = ks[cat]; if (!words||!words.length) continue;
            for (let w of words) {
                if (shown.has(w)) continue; shown.add(w);
                const esc = eHtml(w);
                let icon = '', extra = '';
                if (cat==='speaker') {
                    icon='\u{1f464} ';
                    if (matchedSpeakers.has(w)) extra=' title="\u753b\u50cf\u5e93\u5df2\u5339\u914d"';
                    else extra=' title="\u672a\u5339\u914d\u753b\u50cf\u5e93" style="opacity:0.55"';
                } else if (cat==='topic') {
                    icon='\u{1f4d6} ';
                    extra=' title="\u8bdd\u9898" style="border-style:solid"';
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
    autoAddedSpeakers = new Set(); autoLoadedTopics = new Set(); keywordStore = {};
    const el = $('asr3-txt');
    if (el) el.innerHTML = '<div style="text-align:center;color:#484f58;padding-top:40px"><p style="font-size:28px">🗑</p><p>已清除</p></div>';
    $('asr3-tm').textContent = '0.0秒'; $('asr3-cnt').textContent = '0条 | 0字'; $('asr3-kws').innerHTML = '';
}

async function startRec() {
    if (!ws||ws.readyState!==1) { alert('服务未连接！请启动 start.bat'); return; }
    try {
        mediaStream = await navigator.mediaDevices.getDisplayMedia({audio:true,video:true});
        audioCtx = new AudioContext({sampleRate:48000});
        const src = audioCtx.createMediaStreamSource(mediaStream);
        const proc = audioCtx.createScriptProcessor(8192,1,1);
        proc.onaudioprocess = e => {
            if (isRecording&&ws&&ws.readyState===1) ws.send(new Float32Array(e.inputBuffer.getChannelData(0)).buffer);
        };
        src.connect(proc); proc.connect(audioCtx.destination);
        isRecording = true;
        send({type:'start'});

        const pu = location.href;
        const pt = pu.includes('live.bilibili.com')?'live':(pu.includes('bilibili.com/video/')||pu.includes('youtube.com/watch'))?'video':'web';
        let vo = 0;
        if (pt==='video') {
            const vs = document.querySelectorAll('video');
            for (const v of vs) { if (v.duration&&v.currentTime>0) { vo=v.currentTime; v.currentTime=0; break; } }
        }

        setTimeout(async () => {
            const cr = detectCreator();
            if (cr) {
                send({type:'page_creator',creator:cr,page_type:pt,video_offset:vo,platform:(()=>{
                    const u=location.href; if(u.includes('bilibili')) return 'bilibili';
                    if(u.includes('douyu')) return 'douyu'; if(u.includes('huya')) return 'huya'; return 'web';
                })()});
            }
            if (cr&&!autoAddedSpeakers.has(cr)) {
                autoAddedSpeakers.add(cr);
                if (!keywordStore||!keywordStore['speaker']||!keywordStore['speaker'].includes(cr)) {
                    send({type:'keyword_add',keyword:cr,category:'speaker'});
                    toast('🎤 自动识别创作者: '+cr,'ok',4000);
                }
            }
            const tags = detectTags();
            if (tags.length>0) {
                const nt = tags.filter(t=>!autoLoadedTopics.has(t));
                if (nt.length>0) { nt.forEach(t=>autoLoadedTopics.add(t)); send({type:'topic_keywords_load',tags:nt}); }
            }
            const title = detectTitle();
            if (title&&title.length>=4) send({type:'video_title',title:title});
            const sm = await detectLiveSquad();
            if (sm.length>0) send({type:'live_squad',members:sm});
        }, 2000);

        $('asr3-start').disabled = true; $('asr3-stop').disabled = false;
    } catch(e) { L('Record err: '+e.message); if (e.name!=='AbortError') alert('授权失败: '+(e.message||'用户取消')); }
}

function stopRec() {
    isRecording = false;
    send({type:'stop'});
    if (mediaStream) { mediaStream.getTracks().forEach(t=>t.stop()); mediaStream = null; }
    if (audioCtx) { audioCtx.close(); audioCtx = null; }
    $('asr3-start').disabled = false; $('asr3-stop').disabled = true;
}

function toast(msg, type, duration) {
    if (duration===undefined) duration=2500;
    const t = document.createElement('div');
    t.className = 'asr3-toast '+(type||'');
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => { t.remove(); }, duration);
}

L('v1.0 loaded');
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

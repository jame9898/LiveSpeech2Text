# -*- coding: utf-8 -*-
"""
创作者识别器 — 从 B站/斗鱼/虎牙/YouTube 页面 URL 提取 UP 主或主播名
"""
import re
import json
import time
import html as html_mod
import urllib.request


class CreatorDetector:
    """从平台 URL 自动检测创作者名"""

    @staticmethod
    def parse_platform_info(page_url):
        """返回 (platform, page_type) 从 URL 推断平台"""
        u = page_url.lower() if page_url else ""
        if 'bilibili.com/video/' in u or 'bilibili.com/bangumi/' in u:
            return 'bilibili', 'video'
        if 'live.bilibili.com' in u:
            # 直播房间页（含数字ID）才算
            if not re.search(r'live\.bilibili\.com/(\d+|blanc/\d+|blackboard/)', u):
                return 'web', 'web'
            return 'bilibili', 'live'
        if 'douyu.com/' in u:
            if re.search(r'douyu\.com/(\d+)', u):
                return 'douyu', 'live'
            return 'web', 'web'
        if 'huya.com/' in u and re.search(r'\d', page_url):
            return 'huya', 'live'
        if 'youtube.com/watch' in u:
            return 'youtube', 'video'
        return 'web', 'web'

    async def detect_creator(self, page_url, loop=None):
        """返回 (creator_name_or_None, platform, page_type)"""
        platform, page_type = self.parse_platform_info(page_url)

        if loop is None:
            import asyncio
            loop = asyncio.get_running_loop()

        creator = await self._do_detect(page_url, platform, loop)
        return creator, platform, page_type

    async def _do_detect(self, page_url, platform, loop):
        """按平台 API 顺序尝试提取创作者名"""
        creator = None

        # ---- B站视频 API ----
        bv_match = re.search(r'(?:bilibili\.com/video/|BV)([A-Za-z0-9]{10,12})', page_url)
        if bv_match:
            bvid = ('BV' + bv_match.group(1)) if not bv_match.group(0).startswith('BV') else bv_match.group(1)
            data = await loop.run_in_executor(None, self._fetch_json, f'https://api.bilibili.com/x/web-interface/view?bvid={bvid}')
            if data and data.get('code') == 0:
                owner = data.get('data', {}).get('owner', {})
                creator = owner.get('name', '')
                if creator:
                    return creator

        # ---- B站直播 API ----
        room_match = re.search(r'live\.bilibili\.com/(?:blanc/)?(\d+)', page_url)
        if room_match and not creator:
            data = await loop.run_in_executor(None, self._fetch_json,
                f'https://api.live.bilibili.com/room/v1/Room/get_info?room_id={room_match.group(1)}')
            if data and data.get('code') == 0:
                anchor = data.get('data', {}).get('anchor_info', {}).get('base_info', {})
                creator = anchor.get('uname', '')

        # ---- 斗鱼 ----
        # 优先级：betard API > douyucdn API > HTML anchorName H3 > HTML 标题解析
        # API 返回的 nickname 字段是最可靠的（诊断实测4个房间全部正确）
        # anchorName H3 仅在 SSR 直出时存在，不可靠
        if platform == 'douyu' and not creator:
            rid = None
            rm = re.search(r'douyu\.com/(\d+)', page_url)
            if rm:
                rid = rm.group(1)
            else:
                rm2 = re.search(r'[?&]rid=(\d+)', page_url)
                if rm2:
                    rid = rm2.group(1)

            if rid:
                # 策略1：betard API（返回 nickname 字段，实测最准确）
                data = await loop.run_in_executor(
                    None, self._fetch_json,
                    f'https://www.douyu.com/betard/{rid}')
                if data:
                    ri = data.get('room', {}) or data.get('roomInfo', {})
                    if isinstance(ri, dict):
                        creator = ri.get('nickname', '') or ri.get('owner_name', '')
                        if creator:
                            print(f"[CREATOR] 斗鱼 betard API: {creator}", flush=True)
                            return creator

                # 策略2：open.douyucdn.cn API
                data = await loop.run_in_executor(
                    None, self._fetch_json,
                    f'http://open.douyucdn.cn/api/RoomApi/room/{rid}')
                if data and data.get('error') == 0:
                    room_data = data.get('data', {})
                    creator = room_data.get('owner_name', '') or room_data.get('nickname', '')
                    if creator:
                        print(f"[CREATOR] 斗鱼 douyucdn API: {creator}", flush=True)
                        return creator

            # 策略3+4：HTML 页面解析（anchorName H3 + 标题兜底，共用一次抓取）
            creator = await self._detect_douyu_from_html(page_url, loop)
            if creator:
                return creator

        # ---- 虎牙 ----
        if platform == 'huya' and not creator:
            html = await loop.run_in_executor(None, self._fetch_page, page_url)
            if html:
                hn = re.search(r'"nickName"\s*:\s*"([^"]+)"', html) or re.search(r'"sNick"\s*:\s*"([^"]+)"', html)
                if hn:
                    creator = hn.group(1)
                if not creator:
                    t = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
                    if t:
                        title = t.group(1).strip()
                        for sep in ['-', '_', '直播']:
                            if sep in title:
                                c = title.split(sep)[0].strip()
                                if 2 <= len(c) <= 20:
                                    creator = c
                                    break

        # ---- 兜底 ----
        if not creator:
            html = await loop.run_in_executor(None, self._fetch_page, page_url)
            if html:
                am = re.search(r'<meta\s+name="author"\s+content="([^"]+)"', html, re.IGNORECASE)
                if am:
                    c = am.group(1).strip()
                    if c and c not in ('哔哩哔哩', 'bilibili', 'BILIBILI'):
                        creator = c
                if not creator and 'live.bilibili.com' in page_url.lower():
                    t = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
                    if t:
                        parts = t.group(1).strip().split(' - ', 1)
                        if len(parts[0]) >= 2 and len(parts[0]) <= 20:
                            creator = parts[0]

        return creator

    async def _detect_douyu_from_html(self, page_url, loop):
        """从斗鱼HTML页面提取主播名（anchorName H3 + 内嵌 JSON + 标题兜底，共用一次抓取）"""
        html = await loop.run_in_executor(None, self._fetch_page, page_url)
        if not html:
            return None

        # 策略A：anchorName H3 标签（SSR 直出时才有）
        anchor_match = re.search(
            r'<h3\s+class="[^"]*anchorName[^"]*"[^>]*>([^<]+)</h3>',
            html
        )
        if anchor_match:
            name = html_mod.unescape(anchor_match.group(1).strip())
            if 2 <= len(name) <= 30:
                print(f"[CREATOR] 斗鱼 anchorName H3 提取: {name}", flush=True)
                return name

        # 策略B：页面内嵌 JSON 中的 nickname 字段
        category_words = ['主机', '网游', '手游', '单机', '娱乐', '颜值', '户外', '赛事', '交友', '科技', '音乐', '舞蹈']
        json_matches = re.findall(r'"nickname"\s*:\s*"([^"]+)"', html)
        for nick in json_matches:
            nick = nick.strip()
            if not (2 <= len(nick) <= 30):
                continue
            if '\\u' in nick:
                continue
            if any(cat in nick and len(nick) <= 4 for cat in category_words):
                continue
            print(f"[CREATOR] 斗鱼 JSON nickname 提取: {nick}", flush=True)
            return nick

        # 策略C：从页面标题提取（格式: "标题_主播名直播_斗鱼直播" 或 "主播名直播-斗鱼直播"）
        t = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
        if t:
            title = t.group(1).strip()
            # 尝试多种标题格式
            patterns = [
                # "xxx_主播名直播_斗鱼直播" 或 "xxx_主播名_正在直播"
                r'[_\s]([^_\s]{2,30})[_\s](?:斗鱼|正在)[_\s]?直播',
                # "主播名直播_斗鱼直播"
                r'^([^_\s]{2,30})直播[_\s]',
                # "xxx - 主播名 - 斗鱼直播"
                r'[-–—]\s*([^-–—]{2,30})\s*[-–—]\s*斗鱼',
                # "主播名_xxx_斗鱼直播" (取第一段)
                r'^([^_\s]{2,30})[_\s]',
            ]
            for pat in patterns:
                m = re.search(pat, title)
                if m:
                    name = m.group(1).strip()
                    # 清洗：去掉尾部游戏分区名+"直播"（如"主机区"、"CSGO"等）
                    name = re.sub(
                        r'(?:主机区?|CS[:]?GO|CS2|VALORANT|APEX|PUBG|DOTA2?|LOL|CF'
                        r'|[A-Z]{2,6}|[\u4e00-\u9fff]{2,4})直播$',
                        '', name, flags=re.IGNORECASE)
                    # 再清洗：纯尾部游戏分区名（无"直播"后缀）
                    name = re.sub(
                        r'(?:主机区|动作区|单机区|网游区|手游区|娱乐区)$',
                        '', name)
                    if 2 <= len(name) < 30 and '斗鱼' not in name:
                        return name

            # 兜底：按 _ 或 - 分割取可能的片段
            for sep in ['_', '-', '—', '–']:
                parts = [p.strip() for p in title.split(sep)
                         if p.strip() and 2 <= len(p.strip()) <= 30
                         and '斗鱼' not in p and '直播' not in p]
                if len(parts) >= 2:
                    # 优先取非游戏名的片段（含中文且不含全大写英文的）
                    for p in parts:
                        if re.search(r'[\u4e00-\u9fff]', p):
                            return p
                    return parts[0]

        # 策略3：从 og:title 等 meta 标签提取
        og = re.search(
            r'<meta\s+property="og:title"\s+content="([^"]+)"',
            html, re.IGNORECASE)
        if og:
            og_title = og.group(1).strip()
            for sep in ['_', '-', '—', '–']:
                if sep in og_title:
                    parts = [p.strip() for p in og_title.split(sep)
                             if p.strip() and 2 <= len(p.strip()) <= 30
                             and '斗鱼' not in p]
                    if parts:
                        return parts[0]

        return None

    @staticmethod
    def _fetch_json(url, retries=2, timeout=8):
        last_err = None
        for attempt in range(retries + 1):
            try:
                req = urllib.request.Request(url, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Referer': 'https://www.bilibili.com/',
                })
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return json.loads(resp.read().decode('utf-8', errors='ignore'))
            except Exception as e:
                last_err = e
                if attempt < retries:
                    wait = 0.5 * (2 ** attempt)  # 0.5s, 1.0s 指数退避
                    print(f"[CREATOR] API {url[:50]} retry {attempt+1}/{retries} after {wait:.1f}s: {e}", flush=True)
                    time.sleep(wait)
        print(f"[CREATOR] API {url[:50]} failed after {retries+1} attempts: {last_err}", flush=True)
        return None

    @staticmethod
    def _fetch_page(url, retries=1, timeout=8):
        last_err = None
        for attempt in range(retries + 1):
            try:
                req = urllib.request.Request(url, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'text/html,application/xhtml+xml',
                })
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read().decode('utf-8', errors='ignore')
            except Exception as e:
                last_err = e
                if attempt < retries:
                    wait = 0.5 * (2 ** attempt)
                    print(f"[CREATOR] page {url[:50]} retry {attempt+1}/{retries}: {e}", flush=True)
                    time.sleep(wait)
        print(f"[CREATOR] page {url[:50]} failed after {retries+1} attempts: {last_err}", flush=True)
        return None
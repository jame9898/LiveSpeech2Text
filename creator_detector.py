# -*- coding: utf-8 -*-
"""
创作者识别器 — 从 B站/斗鱼/虎牙/YouTube 页面 URL 提取 UP 主或主播名
"""
import re
import json
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
        if platform == 'douyu' and not creator:
            rm = re.search(r'douyu\.com/(\d+)', page_url) or re.search(r'[?&]rid=(\d+)', page_url)
            if rm:
                data = await loop.run_in_executor(None, self._fetch_json, f'https://www.douyu.com/betard/{rm.group(1)}')
                if data:
                    ri = data.get('room', {}) or data.get('roomInfo', {})
                    creator = ri.get('nickname', '') or ri.get('owner_name', '')
            if not creator:
                html = await loop.run_in_executor(None, self._fetch_page, page_url)
                if html:
                    t = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
                    if t:
                        title = t.group(1).strip()
                        m = re.search(r'[_\s]([^_\s]{2,30})_(?:斗鱼|正在)直播', title)
                        if m:
                            name = re.sub(r'(?:CS[:]?GO|CS2|VALORANT|APEX|PUBG|DOTA2?|LOL|CF|[A-Z]{2,6}|[\u4e00-\u9fff]{2,4})直播$', '', m.group(1).strip(), flags=re.IGNORECASE)
                            if 2 <= len(name) < 30:
                                creator = name
                        if not creator:
                            parts = [p for p in title.split('_') if p and len(p) >= 2 and '斗鱼' not in p and '正在' not in p and p != '直播']
                            if parts:
                                last = re.sub(r'(?:CS[:]?GO|CS2|VALORANT|APEX|PUBG|DOTA2?|LOL|CF|[A-Z]{2,6}|[\u4e00-\u9fff]{2,4})直播$', '', parts[-1], flags=re.IGNORECASE)
                                if 2 <= len(last) < 30:
                                    creator = last

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

    @staticmethod
    def _fetch_json(url):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://www.bilibili.com/',
            })
            with urllib.request.urlopen(req, timeout=8) as resp:
                return json.loads(resp.read().decode('utf-8', errors='ignore'))
        except Exception as e:
            print(f"[CREATOR] API {url[:50]} failed: {e}", flush=True)
            return None

    @staticmethod
    def _fetch_page(url):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml',
            })
            with urllib.request.urlopen(req, timeout=8) as resp:
                return resp.read().decode('utf-8', errors='ignore')
        except Exception as e:
            print(f"[CREATOR] page {url[:50]} failed: {e}", flush=True)
            return None
"""
PymChat 适配器 for AstrBot
使用 curl 调用 PymChat API，并使用简洁温暖风格的自定义 HTML 模板
"""
import json
import re
import subprocess
import asyncio
from typing import Dict, Any, Optional, List
from urllib.parse import quote

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Star, Context
from astrbot.api import logger

# 简洁温暖风格模板 - 像手写的笔记一样自然
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Ma+Shan+Zheng&family=Noto+Sans+SC:wght@300;400;500&display=swap');
        
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Noto Sans SC', sans-serif;
            background: #fefefe;
            margin: 0;
            padding: 30px;
            display: flex;
            justify-content: center;
        }
        
        .note {
            width: 460px;
            background: #fff;
            padding: 28px 32px;
            border-radius: 2px;
            box-shadow: 0 2px 18px rgba(0,0,0,0.08);
            position: relative;
        }
        
        .note::before {
            content: "";
            position: absolute;
            top: 0; left: 0; right: 0;
            height: 4px;
            background: #e8e8e8;
        }
        
        .title {
            font-size: 22px;
            font-weight: 500;
            color: #222;
            margin-bottom: 22px;
            display: flex;
            align-items: center;
            gap: 8px;
            padding-bottom: 14px;
            border-bottom: 1px solid #f0f0f0;
        }
        
        .title .tag {
            font-size: 11px;
            color: #999;
            font-weight: 300;
            letter-spacing: 1px;
        }
        
        .item {
            padding: 11px 0;
            border-bottom: 1px solid #f5f5f5;
        }
        
        .item:last-child { border-bottom: none; }
        
        .item .who {
            font-size: 12px;
            color: #888;
            margin-bottom: 3px;
        }
        
        .item .what {
            font-size: 15px;
            color: #333;
            line-height: 1.6;
        }
        
        .item .when {
            font-size: 11px;
            color: #bbb;
            margin-top: 3px;
            text-align: right;
        }
        
        .section-title {
            font-size: 11px;
            color: #bbb;
            letter-spacing: 2px;
            text-transform: uppercase;
            margin: 20px 0 10px;
        }
        
        .cmd-line {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            padding: 7px 0;
            border-bottom: 1px dashed #f0f0f0;
        }
        
        .cmd-line:last-child { border-bottom: none; }
        
        .cmd-name {
            font-size: 14px;
            color: #444;
            font-weight: 400;
        }
        
        .cmd-desc {
            font-size: 13px;
            color: #aaa;
        }
        
        .status-row {
            display: flex;
            justify-content: space-between;
            padding: 9px 0;
            border-bottom: 1px solid #f8f8f8;
        }
        
        .status-key { font-size: 13px; color: #999; }
        .status-val { font-size: 14px; color: #333; font-weight: 400; }
        
        .footer {
            margin-top: 22px;
            padding-top: 14px;
            border-top: 1px solid #f0f0f0;
            font-size: 11px;
            color: #ccc;
            text-align: center;
            letter-spacing: 1px;
        }
        
        .content-box {
            padding: 14px;
            background: #fafafa;
            border-radius: 4px;
            font-size: 14px;
            color: #555;
            line-height: 1.8;
            white-space: pre-wrap;
        }
    </style>
</head>
<body>
    <div class="note">
        <div class="title">
            {{ icon }} {{ title }}
            <span class="tag">pymchat</span>
        </div>
        
        {% if mode == 'list' %}
            {% for item in items %}
            <div class="item">
                <div class="who">{{ item.sender }}</div>
                <div class="what">{{ item.content }}</div>
                {% if item.time %}<div class="when">{{ item.time }}</div>{% endif %}
            </div>
            {% endfor %}
        {% elif mode == 'help' %}
            {% for group in help_groups %}
            <div class="section-title">{{ group.name }}</div>
            {% for cmd in group.cmds %}
            <div class="cmd-line">
                <span class="cmd-name">{{ cmd.name }}</span>
                <span class="cmd-desc">{{ cmd.desc }}</span>
            </div>
            {% endfor %}
            {% endfor %}
        {% elif mode == 'status' %}
            {% for row in status_rows %}
            <div class="status-row">
                <span class="status-key">{{ row.key }}</span>
                <span class="status-val">{{ row.val }}</span>
            </div>
            {% endfor %}
        {% else %}
            <div class="content-box">{{ content }}</div>
        {% endif %}
        
        <div class="footer">v2.0 · pymchat for astrbot</div>
    </div>
</body>
</html>
"""

class PymChatPlugin(Star):
    def __init__(self, context: Context, config: Dict[str, Any]):
        super().__init__(context)
        self.config = config
        self.api_key: str = config.get("api_key", "")
        self.username: str = config.get("username", "")
        self.password: str = config.get("password", "")
        self.debug: bool = config.get("debug_mode", False)
        self.base_url: str = "https://chat.qplm.xyz"

        if self.username and self.password and not self.api_key:
            asyncio.create_task(self._auto_login_on_start())

    async def _auto_login_on_start(self):
        await self._auto_login()

    async def _auto_login(self) -> bool:
        url = f"{self.base_url}/api/login.php"
        payload = json.dumps({"username": self.username, "password": self.password})
        cmd = ["curl", "-s", "-X", "POST", url, "-H", "Content-Type: application/json", "-d", payload]
        try:
            result = await self._run_curl(cmd)
            if result.get("status") == 200:
                api_key = result.get("data", {}).get("api_key", "")
                if api_key:
                    self.api_key = api_key
                    self.config["api_key"] = api_key
                    if hasattr(self.config, 'save_config'): self.config.save_config()
                    return True
            return False
        except Exception: return False

    async def _run_curl(self, cmd: List[str]) -> Dict[str, Any]:
        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await process.communicate()
        return json.loads(stdout.decode('utf-8').strip())

    async def _call_pymchat_api(self, action: str, **kwargs) -> Dict[str, Any]:
        query_parts = [f"api_key={self.api_key}", f"action={action}"]
        for k, v in kwargs.items(): query_parts.append(f"{k}={quote(str(v))}")
        url = f"{self.base_url}/api/ac.php?" + "&".join(query_parts)
        return await self._run_curl(["curl", "-s", url])

    async def _render(self, event: AstrMessageEvent, title: str, icon: str, **kwargs):
        data = {"title": title, "icon": icon, **kwargs}
        options = {"omit_background": False}
        url = await self.html_render(HTML_TEMPLATE, data, options=options)
        return event.image_result(url)

    @filter.command("pymchat")
    async def pymchat_help(self, event: AstrMessageEvent):
        help_groups = [
            {"name": "发消息", "cmds": [{"name": "send <内容>", "desc": "发送到公共频道"}, {"name": "get [数量]", "desc": "查看最近消息"}]},
            {"name": "私信", "cmds": [{"name": "send_private <ID> <内容>", "desc": "给某人发私信"}, {"name": "get_private [数量]", "desc": "查看私信"}]},
            {"name": "社交", "cmds": [{"name": "friends", "desc": "好友列表"}, {"name": "add_friend <ID>", "desc": "添加好友"}]},
            {"name": "其他", "cmds": [{"name": "status", "desc": "看看插件状态"}]}
        ]
        yield await self._render(event, "帮助", "📖", mode="help", help_groups=help_groups)

    @filter.command("pymchat send")
    async def pymchat_send(self, event: AstrMessageEvent):
        content = event.message_str.replace("/pymchat send", "").strip()
        if not content: return
        result = await self._call_pymchat_api("send_message", content=content)
        if result.get("status") == 200:
            yield await self._render(event, "已发送", "✅", content=f"消息「{content}」已投递到公共频道")
        else: yield event.plain_result(f"失败了: {result.get('message')}")

    @filter.command("pymchat get")
    async def pymchat_get(self, event: AstrMessageEvent):
        result = await self._call_pymchat_api("get_messages", type="public", limit=5)
        if result.get("status") == 200:
            msgs = result.get("data", {}).get("messages", [])
            items = [{"sender": m.get("sdn", m.get("sn", "匿名")), "content": m.get("content", ""), "time": m.get("time", "")} for m in msgs]
            yield await self._render(event, "最近消息", "💬", mode="list", items=items)
        else: yield event.plain_result("获取失败了")

    @filter.command("pymchat send_private")
    async def pymchat_send_private(self, event: AstrMessageEvent):
        content = event.message_str.replace("/pymchat send_private", "").strip()
        parts = content.split(maxsplit=1)
        if len(parts) < 2: return
        result = await self._call_pymchat_api("send_message", recipient_id=parts[0], content=parts[1])
        if result.get("status") == 200:
            yield await self._render(event, "私信已发", "📩", content=f"发给 {parts[0]} 的私信：「{parts[1]}」")
        else: yield event.plain_result("发送失败")

    @filter.command("pymchat get_private")
    async def pymchat_get_private(self, event: AstrMessageEvent):
        result = await self._call_pymchat_api("get_messages", type="private", limit=5)
        if result.get("status") == 200:
            msgs = result.get("data", {}).get("messages", [])
            items = [{"sender": m.get("sdn", "匿名"), "content": m.get("content", ""), "time": m.get("time", "")} for m in msgs]
            yield await self._render(event, "私信", "✉️", mode="list", items=items)
        else: yield event.plain_result("获取失败了")

    @filter.command("pymchat friends")
    async def pymchat_friends(self, event: AstrMessageEvent):
        result = await self._call_pymchat_api("get_friends")
        if result.get("status") == 200:
            friends = result.get("data", {}).get("friends", [])
            items = [{"sender": f.get("display_name", "某用户"), "content": f"ID: {f.get('id')}"} for f in friends]
            yield await self._render(event, "好友", "👥", mode="list", items=items)
        else: yield event.plain_result("获取失败了")

    @filter.command("pymchat status")
    async def pymchat_status(self, event: AstrMessageEvent):
        status_rows = [
            {"key": "API Key", "val": "✅ 已配置" if self.api_key else "❌ 未配置"},
            {"key": "用户名", "val": self.username or "未设置"},
            {"key": "调试模式", "val": "开" if self.debug else "关"}
        ]
        yield await self._render(event, "状态", "📱", mode="status", status_rows=status_rows)

def register():
    return PymChatPlugin
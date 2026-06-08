"""
PymChat 适配器 for AstrBot
使用 curl 调用 PymChat API，并使用赛博朋克毛玻璃风格的自定义 HTML 模板
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

# 赛博朋克毛玻璃风格模板
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Noto+Sans+SC:wght@400;700&display=swap');
        
        :root {
            --bg-gradient: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
            --accent-cyan: #00f2fe;
            --accent-purple: #7000ff;
            --accent-pink: #ff00c1;
            --glass-bg: rgba(255, 255, 255, 0.05);
            --glass-border: rgba(255, 255, 255, 0.1);
            --text-primary: #ffffff;
            --text-secondary: #b0b0b0;
        }

        body {
            font-family: 'Noto Sans SC', sans-serif;
            margin: 0;
            padding: 40px;
            background: var(--bg-gradient);
            display: flex;
            justify-content: center;
            align-items: flex-start;
            min-height: 100vh;
            color: var(--text-primary);
        }

        .container {
            width: 500px;
            background: var(--glass-bg);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid var(--glass-border);
            border-radius: 24px;
            box-shadow: 0 20px 50px rgba(0, 0, 0, 0.5);
            overflow: hidden;
            position: relative;
        }

        .container::before {
            content: "";
            position: absolute;
            top: 0; left: 0; right: 0; height: 4px;
            background: linear-gradient(90deg, var(--accent-cyan), var(--accent-purple), var(--accent-pink));
        }

        .header {
            padding: 30px 30px 20px;
            display: flex;
            align-items: center;
            gap: 15px;
        }

        .header-icon {
            font-size: 32px;
            background: rgba(255, 255, 255, 0.1);
            width: 60px; height: 60px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 16px;
            border: 1px solid var(--glass-border);
        }

        .header-info h1 {
            margin: 0;
            font-size: 24px;
            letter-spacing: 1px;
            text-transform: uppercase;
        }

        .header-info p {
            margin: 5px 0 0;
            font-size: 12px;
            color: var(--accent-cyan);
            font-family: 'JetBrains Mono', monospace;
            opacity: 0.8;
        }

        .content {
            padding: 0 30px 30px;
        }

        .list-item {
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--glass-border);
            border-radius: 16px;
            padding: 15px;
            margin-bottom: 12px;
            transition: all 0.3s ease;
        }

        .list-item:hover {
            background: rgba(255, 255, 255, 0.08);
            transform: translateY(-2px);
        }

        .list-item .label {
            font-size: 11px;
            color: var(--accent-cyan);
            text-transform: uppercase;
            margin-bottom: 5px;
            display: block;
            font-weight: bold;
        }

        .list-item .value {
            font-size: 16px;
            line-height: 1.5;
        }

        .list-item .meta {
            margin-top: 8px;
            font-size: 11px;
            color: var(--text-secondary);
            display: flex;
            justify-content: space-between;
        }

        .group-title {
            font-size: 14px;
            color: var(--text-secondary);
            margin: 20px 0 10px;
            padding-left: 5px;
            border-left: 2px solid var(--accent-purple);
        }

        .cmd-box {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0;
            border-bottom: 1px solid var(--glass-border);
        }

        .cmd-name {
            font-family: 'JetBrains Mono', monospace;
            color: var(--accent-cyan);
            font-size: 14px;
        }

        .cmd-desc {
            font-size: 13px;
            color: var(--text-secondary);
        }

        .footer {
            padding: 20px;
            text-align: center;
            font-size: 10px;
            color: var(--text-secondary);
            letter-spacing: 2px;
            opacity: 0.5;
            background: rgba(0, 0, 0, 0.2);
        }

        .status-row {
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid var(--glass-border);
        }

        .status-key {
            color: var(--text-secondary);
            font-size: 14px;
        }

        .status-val {
            color: var(--accent-cyan);
            font-family: 'JetBrains Mono', monospace;
            font-size: 14px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="header-icon">{{ icon }}</div>
            <div class="header-info">
                <h1>{{ title }}</h1>
                <p>PYMCHAT_PROTOCOL_V2.0</p>
            </div>
        </div>
        <div class="content">
            {% if mode == 'list' %}
                {% for item in items %}
                <div class="list-item">
                    <span class="label">{{ item.sender }}</span>
                    <div class="value">{{ item.content }}</div>
                    {% if item.time %}
                    <div class="meta">
                        <span>STATUS: RECEIVED</span>
                        <span>{{ item.time }}</span>
                    </div>
                    {% endif %}
                </div>
                {% endfor %}
            {% elif mode == 'help' %}
                {% for group in help_groups %}
                <div class="group-title">{{ group.name }}</div>
                {% for cmd in group.cmds %}
                <div class="cmd-box">
                    <span class="cmd-name">/{{ cmd.name }}</span>
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
                <div class="list-item">
                    <span class="label">SYSTEM_LOG</span>
                    <div class="value" style="white-space: pre-wrap;">{{ content }}</div>
                </div>
            {% endif %}
        </div>
        <div class="footer">ENCRYPTED END-TO-END CONNECTION</div>
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

    async def _render_result(self, event: AstrMessageEvent, title: str, icon: str, **kwargs):
        data = {"title": title, "icon": icon, **kwargs}
        options = {"full_page": False, "omit_background": True}
        url = await self.html_render(HTML_TEMPLATE, data, options=options)
        return event.image_result(url)

    @filter.command("pymchat")
    async def pymchat_help(self, event: AstrMessageEvent):
        help_groups = [
            {"name": "COMMANDS", "cmds": [{"name": "pymchat send", "desc": "发送消息"}, {"name": "pymchat get", "desc": "拉取消息"}]},
            {"name": "PRIVATE", "cmds": [{"name": "pymchat send_private", "desc": "发私信"}, {"name": "pymchat get_private", "desc": "收私信"}]},
            {"name": "SYSTEM", "cmds": [{"name": "pymchat friends", "desc": "好友"}, {"name": "pymchat status", "desc": "状态"}]}
        ]
        yield await self._render_result(event, "Command List", "🛡️", mode="help", help_groups=help_groups)

    @filter.command("pymchat send")
    async def pymchat_send(self, event: AstrMessageEvent):
        content = event.message_str.replace("/pymchat send", "").strip()
        if not content: return
        result = await self._call_pymchat_api("send_message", content=content)
        if result.get("status") == 200:
            yield await self._render_result(event, "Transmission Success", "🚀", content=f"DATA SENT:\n{content}")
        else: yield event.plain_result(f"ERROR: {result.get('message')}")

    @filter.command("pymchat get")
    async def pymchat_get(self, event: AstrMessageEvent):
        result = await self._call_pymchat_api("get_messages", type="public", limit=5)
        if result.get("status") == 200:
            msgs = result.get("data", {}).get("messages", [])
            items = [{"sender": m.get("sdn", "ANONYMOUS"), "content": m.get("content", ""), "time": m.get("time", "")} for m in msgs]
            yield await self._render_result(event, "Incoming Stream", "📥", mode="list", items=items)

    @filter.command("pymchat send_private")
    async def pymchat_send_private(self, event: AstrMessageEvent):
        content = event.message_str.replace("/pymchat send_private", "").strip()
        parts = content.split(maxsplit=1)
        if len(parts) < 2: return
        result = await self._call_pymchat_api("send_message", recipient_id=parts[0], content=parts[1])
        if result.get("status") == 200:
            yield await self._render_result(event, "Secure Message Sent", "🔐", content=f"TARGET: {parts[0]}")

    @filter.command("pymchat get_private")
    async def pymchat_get_private(self, event: AstrMessageEvent):
        result = await self._call_pymchat_api("get_messages", type="private", limit=5)
        if result.get("status") == 200:
            msgs = result.get("data", {}).get("messages", [])
            items = [{"sender": m.get("sdn", "ANONYMOUS"), "content": m.get("content", ""), "time": m.get("time", "")} for m in msgs]
            yield await self._render_result(event, "Private Stream", "🔒", mode="list", items=items)

    @filter.command("pymchat friends")
    async def pymchat_friends(self, event: AstrMessageEvent):
        result = await self._call_pymchat_api("get_friends")
        if result.get("status") == 200:
            friends = result.get("data", {}).get("friends", [])
            items = [{"sender": f.get("display_name", "USER"), "content": f"ID: {f.get('id')}"} for f in friends]
            yield await self._render_result(event, "Contact List", "👥", mode="list", items=items)

    @filter.command("pymchat status")
    async def pymchat_status(self, event: AstrMessageEvent):
        status_rows = [
            {"key": "KEY_STATUS", "val": "AUTHORIZED" if self.api_key else "UNAUTHORIZED"},
            {"key": "USER_ID", "val": self.username or "GUEST"},
            {"key": "DEBUG_MODE", "val": str(self.debug).upper()}
        ]
        yield await self._render_result(event, "System Status", "📊", mode="status", status_rows=status_rows)

def register():
    return PymChatPlugin
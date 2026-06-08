"""
PymChat 适配器 for AstrBot
使用 curl 调用 PymChat API，并使用自定义 HTML 模板进行美化渲染
"""
import json
import re
import subprocess
import asyncio
from typing import Dict, Any, Optional, List

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Star, Context
from astrbot.api import logger

# 自定义美化模板 (基于 Jinja2)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <style>
        :root {
            --primary-color: #4facfe;
            --secondary-color: #00f2fe;
            --bg-dark: #1e1e2e;
            --text-main: #cdd6f4;
            --text-sub: #a6adc8;
            --card-bg: rgba(30, 30, 46, 0.9);
        }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            display: flex;
            justify-content: center;
            background-color: transparent;
        }
        .card {
            background: var(--card-bg);
            border-radius: 16px;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
            border: 1px solid rgba(255, 255, 255, 0.1);
            width: 450px;
            overflow: hidden;
            backdrop-filter: blur(8px);
        }
        .header {
            background: linear-gradient(135deg, var(--primary-color) 0%, var(--secondary-color) 100%);
            padding: 15px 20px;
            color: white;
            font-size: 20px;
            font-weight: bold;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .content {
            padding: 20px;
            color: var(--text-main);
            line-height: 1.6;
        }
        .item-list {
            list-style: none;
            padding: 0;
            margin: 0;
        }
        .item {
            padding: 10px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            display: flex;
            flex-direction: column;
            gap: 4px;
        }
        .item:last-child { border-bottom: none; }
        .sender {
            color: var(--primary-color);
            font-weight: 600;
            font-size: 14px;
        }
        .msg-text {
            font-size: 16px;
            word-wrap: break-word;
        }
        .time {
            font-size: 12px;
            color: var(--text-sub);
            text-align: right;
        }
        .footer {
            padding: 10px 20px;
            background: rgba(0, 0, 0, 0.1);
            color: var(--text-sub);
            font-size: 12px;
            text-align: center;
        }
        .cmd-group {
            margin-bottom: 15px;
        }
        .cmd-title {
            color: var(--secondary-color);
            font-size: 14px;
            font-weight: bold;
            margin-bottom: 5px;
            border-left: 3px solid var(--secondary-color);
            padding-left: 8px;
        }
        .cmd-item {
            font-size: 14px;
            padding-left: 12px;
            margin-bottom: 2px;
        }
    </style>
</head>
<body>
    <div class="card">
        <div class="header">
            <span>{{ icon }}</span>
            <span>{{ title }}</span>
        </div>
        <div class="content">
            {% if mode == 'list' %}
                <div class="item-list">
                    {% for item in items %}
                    <div class="item">
                        <span class="sender">{{ item.sender }}</span>
                        <span class="msg-text">{{ item.content }}</span>
                        {% if item.time %}<span class="time">{{ item.time }}</span>{% endif %}
                    </div>
                    {% endfor %}
                </div>
            {% elif mode == 'help' %}
                {% for group in help_groups %}
                <div class="cmd-group">
                    <div class="cmd-title">{{ group.name }}</div>
                    {% for cmd in group.cmds %}
                    <div class="cmd-item"><b>{{ cmd.name }}</b>: {{ cmd.desc }}</div>
                    {% endfor %}
                </div>
                {% endfor %}
            {% else %}
                <div class="msg-text">{{ content }}</div>
            {% endif %}
        </div>
        <div class="footer">PymChat Adapter v2.0 • AstrBot 驱动</div>
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
        logger.info("检测到未配置 API Key，正在尝试自动登录...")
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
        from urllib.parse import quote
        for k, v in kwargs.items(): query_parts.append(f"{k}={quote(str(v))}")
        url = f"{self.base_url}/api/ac.php?" + "&".join(query_parts)
        return await self._run_curl(["curl", "-s", url])

    async def _render_result(self, event: AstrMessageEvent, title: str, icon: str, **kwargs):
        """渲染美化后的图片并返回结果对象"""
        data = {"title": title, "icon": icon, **kwargs}
        url = await self.html_render(HTML_TEMPLATE, data)
        # 修复：正确调用 event 对象的 image_result 方法
        return event.image_result(url)

    @filter.command("pymchat")
    async def pymchat_help(self, event: AstrMessageEvent):
        help_groups = [
            {"name": "📬 消息", "cmds": [{"name": "send <内容>", "desc": "发公共消息"}, {"name": "get [数]", "desc": "取公共消息"}]},
            {"name": "💬 私信", "cmds": [{"name": "send_private <ID> <内容>", "desc": "发私信"}, {"name": "get_private [数]", "desc": "取私信"}]},
            {"name": "👥 社交", "cmds": [{"name": "friends", "desc": "好友列表"}, {"name": "add_friend <ID>", "desc": "加好友"}]},
            {"name": "⚙️ 系统", "cmds": [{"name": "status", "desc": "查看状态"}]}
        ]
        yield await self._render_result(event, "PymChat 指令帮助", "📚", mode="help", help_groups=help_groups)

    @filter.command("pymchat send")
    async def pymchat_send(self, event: AstrMessageEvent):
        content = event.message_str.replace("/pymchat send", "").strip()
        if not content:
            yield event.plain_result("❌ 用法: pymchat send <内容>")
            return
        result = await self._call_pymchat_api("send_message", content=content)
        if result.get("status") == 200:
            yield await self._render_result(event, "操作成功", "✅", content=f"消息已发送到公共聊天室：<br>{content}")
        else:
            yield event.plain_result(f"❌ 失败: {result.get('message')}")

    @filter.command("pymchat get")
    async def pymchat_get(self, event: AstrMessageEvent):
        limit = 10
        parts = event.message_str.strip().split()
        if len(parts) >= 3 and parts[2].isdigit(): limit = int(parts[2])
        result = await self._call_pymchat_api("get_messages", type="public", limit=limit)
        if result.get("status") == 200:
            msgs = result.get("data", {}).get("messages", [])
            items = [{"sender": m.get("sdn", m.get("sn", "未知")), "content": m.get("content", ""), "time": m.get("time", "")} for m in msgs]
            yield await self._render_result(event, "最新公共消息", "📨", mode="list", items=items)
        else: yield event.plain_result("❌ 获取失败")

    @filter.command("pymchat send_private")
    async def pymchat_send_private(self, event: AstrMessageEvent):
        content = event.message_str.replace("/pymchat send_private", "").strip()
        parts = content.split(maxsplit=1)
        if len(parts) < 2:
            yield event.plain_result("❌ 用法: pymchat send_private <ID> <内容>")
            return
        uid, msg = parts[0], parts[1]
        result = await self._call_pymchat_api("send_message", recipient_id=uid, content=msg)
        if result.get("status") == 200:
            yield await self._render_result(event, "发送成功", "✅", content=f"已对用户 {uid} 发送私信。")
        else: yield event.plain_result("❌ 失败")

    @filter.command("pymchat get_private")
    async def pymchat_get_private(self, event: AstrMessageEvent):
        result = await self._call_pymchat_api("get_messages", type="private", limit=10)
        if result.get("status") == 200:
            msgs = result.get("data", {}).get("messages", [])
            items = [{"sender": m.get("sdn", m.get("sn", "未知")), "content": m.get("content", ""), "time": m.get("time", "")} for m in msgs]
            yield await self._render_result(event, "最新私信", "💬", mode="list", items=items)
        else: yield event.plain_result("❌ 获取失败")

    @filter.command("pymchat friends")
    async def pymchat_friends(self, event: AstrMessageEvent):
        result = await self._call_pymchat_api("get_friends")
        if result.get("status") == 200:
            friends = result.get("data", {}).get("friends", [])
            items = [{"sender": f.get("display_name", f.get("username", "未知")), "content": f"ID: {f.get('id', '')}"} for f in friends]
            yield await self._render_result(event, "好友列表", "👥", mode="list", items=items)
        else: yield event.plain_result("❌ 获取失败")

    @filter.command("pymchat status")
    async def pymchat_status(self, event: AstrMessageEvent):
        status_text = f"API Key: {'已配置' if self.api_key else '未配置'}<br>用户名: {self.username or '未设置'}<br>调试模式: {'开启' if self.debug else '关闭'}"
        yield await self._render_result(event, "插件状态", "📊", content=status_text)

def register():
    return PymChatPlugin
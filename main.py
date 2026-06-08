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

# 自定义美化模板 (简洁朴素风格，去除AI味)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, "Microsoft YaHei", sans-serif;
            background: white;
            padding: 0;
            margin: 0;
        }
        .container {
            width: 100%;
            max-width: 480px;
            border: 1px solid #e0e0e0;
        }
        .title-bar {
            background: #f5f5f5;
            border-bottom: 1px solid #e0e0e0;
            padding: 12px 16px;
            font-size: 16px;
            font-weight: bold;
            color: #333;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .body { padding: 16px; color: #333; font-size: 14px; line-height: 1.8; }
        .item {
            padding: 10px 0;
            border-bottom: 1px solid #f0f0f0;
        }
        .item:last-child { border-bottom: none; }
        .item-header { display: flex; justify-content: space-between; margin-bottom: 4px; }
        .item-name { font-weight: bold; color: #1a1a1a; }
        .item-time { color: #999; font-size: 12px; }
        .item-content { color: #555; word-break: break-all; }
        .section { margin-bottom: 16px; }
        .section-title {
            font-size: 13px;
            color: #888;
            border-bottom: 1px dashed #e0e0e0;
            padding-bottom: 6px;
            margin-bottom: 8px;
        }
        .cmd { display: flex; gap: 12px; margin-bottom: 4px; font-size: 14px; }
        .cmd-name { color: #0066cc; min-width: 140px; }
        .cmd-desc { color: #666; }
        .status-row { display: flex; justify-content: space-between; padding: 6px 0; }
        .status-key { color: #888; }
        .status-val { color: #333; font-weight: 500; }
    </style>
</head>
<body>
    <div class="container">
        <div class="title-bar">{{ icon }} {{ title }}</div>
        <div class="body">
            {% if mode == 'list' %}
                {% for item in items %}
                <div class="item">
                    <div class="item-header">
                        <span class="item-name">{{ item.sender }}</span>
                        {% if item.time %}<span class="item-time">{{ item.time }}</span>{% endif %}
                    </div>
                    <div class="item-content">{{ item.content }}</div>
                </div>
                {% endfor %}
            {% elif mode == 'help' %}
                {% for group in help_groups %}
                <div class="section">
                    <div class="section-title">{{ group.name }}</div>
                    {% for cmd in group.cmds %}
                    <div class="cmd">
                        <span class="cmd-name">{{ cmd.name }}</span>
                        <span class="cmd-desc">{{ cmd.desc }}</span>
                    </div>
                    {% endfor %}
                </div>
                {% endfor %}
            {% elif mode == 'status' %}
                {% for row in status_rows %}
                <div class="status-row">
                    <span class="status-key">{{ row.key }}</span>
                    <span class="status-val">{{ row.val }}</span>
                </div>
                {% endfor %}
            {% else %}
                <div class="item-content">{{ content }}</div>
            {% endif %}
        </div>
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
        url = await self.html_render(HTML_TEMPLATE, data, options={"omit_background": True})
        return event.image_result(url)

    @filter.command("pymchat")
    async def pymchat_help(self, event: AstrMessageEvent):
        help_groups = [
            {"name": "消息指令", "cmds": [{"name": "send <内容>", "desc": "发送公共消息"}, {"name": "get [数量]", "desc": "获取公共消息"}]},
            {"name": "私信指令", "cmds": [{"name": "send_private <ID> <内容>", "desc": "发送私信"}, {"name": "get_private [数量]", "desc": "获取私信"}]},
            {"name": "社交指令", "cmds": [{"name": "friends", "desc": "查看好友列表"}, {"name": "add_friend <ID>", "desc": "添加好友"}]},
            {"name": "系统指令", "cmds": [{"name": "status", "desc": "查看插件状态"}]}
        ]
        yield await self._render_result(event, "PymChat 帮助", "?", mode="help", help_groups=help_groups)

    @filter.command("pymchat send")
    async def pymchat_send(self, event: AstrMessageEvent):
        content = event.message_str.replace("/pymchat send", "").strip()
        if not content:
            yield event.plain_result("用法: pymchat send <内容>")
            return
        result = await self._call_pymchat_api("send_message", content=content)
        if result.get("status") == 200:
            yield await self._render_result(event, "发送成功", "O", content=f"已发送消息：{content}")
        else:
            yield event.plain_result(f"发送失败: {result.get('message')}")

    @filter.command("pymchat get")
    async def pymchat_get(self, event: AstrMessageEvent):
        limit = 10
        parts = event.message_str.strip().split()
        if len(parts) >= 3 and parts[2].isdigit(): limit = int(parts[2])
        result = await self._call_pymchat_api("get_messages", type="public", limit=limit)
        if result.get("status") == 200:
            msgs = result.get("data", {}).get("messages", [])
            items = [{"sender": m.get("sdn", m.get("sn", "未知")), "content": m.get("content", ""), "time": m.get("time", "")} for m in msgs]
            yield await self._render_result(event, "公共消息", "~", mode="list", items=items)
        else: yield event.plain_result("获取失败")

    @filter.command("pymchat send_private")
    async def pymchat_send_private(self, event: AstrMessageEvent):
        content = event.message_str.replace("/pymchat send_private", "").strip()
        parts = content.split(maxsplit=1)
        if len(parts) < 2:
            yield event.plain_result("用法: pymchat send_private <ID> <内容>")
            return
        uid, msg = parts[0], parts[1]
        result = await self._call_pymchat_api("send_message", recipient_id=uid, content=msg)
        if result.get("status") == 200:
            yield await self._render_result(event, "发送成功", "O", content=f"已对用户 {uid} 发送私信")
        else: yield event.plain_result("发送失败")

    @filter.command("pymchat get_private")
    async def pymchat_get_private(self, event: AstrMessageEvent):
        result = await self._call_pymchat_api("get_messages", type="private", limit=10)
        if result.get("status") == 200:
            msgs = result.get("data", {}).get("messages", [])
            items = [{"sender": m.get("sdn", m.get("sn", "未知")), "content": m.get("content", ""), "time": m.get("time", "")} for m in msgs]
            yield await self._render_result(event, "私信", "@", mode="list", items=items)
        else: yield event.plain_result("获取失败")

    @filter.command("pymchat friends")
    async def pymchat_friends(self, event: AstrMessageEvent):
        result = await self._call_pymchat_api("get_friends")
        if result.get("status") == 200:
            friends = result.get("data", {}).get("friends", [])
            items = [{"sender": f.get("display_name", f.get("username", "未知")), "content": f"ID: {f.get('id', '')}"} for f in friends]
            yield await self._render_result(event, "好友列表", "+", mode="list", items=items)
        else: yield event.plain_result("获取失败")

    @filter.command("pymchat status")
    async def pymchat_status(self, event: AstrMessageEvent):
        status_rows = [
            {"key": "API Key", "val": "已配置" if self.api_key else "未配置"},
            {"key": "用户名", "val": self.username or "未设置"},
            {"key": "调试模式", "val": "开启" if self.debug else "关闭"}
        ]
        yield await self._render_result(event, "状态", "i", mode="status", status_rows=status_rows)

def register():
    return PymChatPlugin
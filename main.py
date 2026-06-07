import asyncio
import json
import os
import time
from typing import Dict, Any, List, Optional

import aiohttp
from astrbot.api.all import *
from astrbot.api import logger
from astrbot.api.message_components import *


class PymChatClient:
    """PymChat API 客户端封装"""
    BASE_URL = "https://chat.qplm.xyz/api/ac.php"
    LOGIN_URL = "https://chat.qplm.xyz/api/login.php"
    GROUP_BASE_URL = "https://chat.qplm.xyz/qunliao/api.php"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.user_id: Optional[str] = None
        self.last_message_time: float = 0
        self.min_interval: float = 3.0
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def _request(self, method: str, url: str, params: dict = None, data: dict = None) -> Optional[dict]:
        try:
            async with self.session.request(method, url, params=params, json=data) as resp:
                result = await resp.json()
                if resp.status == 429:
                    logger.warning("触发速率限制 (429)，等待 150 秒")
                    await asyncio.sleep(150)
                    return None
                if result.get("status") == 200:
                    return result.get("data") or result
                else:
                    logger.error(f"API 错误: {result}")
                    return None
        except Exception as e:
            logger.error(f"请求异常: {e}")
            return None

    async def login(self, username: str, password: str) -> bool:
        data = {"username": username, "password": password}
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(self.LOGIN_URL, json=data) as resp:
                    result = await resp.json()
                    if result.get("status") == 200:
                        self.api_key = result["data"]["api_key"]
                        self.user_id = result["data"].get("user_id")
                        logger.info(f"登录成功，用户ID: {self.user_id}")
                        return True
                    else:
                        logger.error(f"登录失败: {result}")
                        return False
            except Exception as e:
                logger.error(f"登录异常: {e}")
                return False

    async def ensure_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()

    async def _get(self, params: dict) -> Optional[dict]:
        await self.ensure_session()
        return await self._request("GET", self.BASE_URL, params=params)

    async def _post(self, params: dict) -> bool:
        await self.ensure_session()
        now = time.time()
        if now - self.last_message_time < self.min_interval:
            await asyncio.sleep(self.min_interval - (now - self.last_message_time))
        result = await self._request("POST", self.BASE_URL, params=params)
        self.last_message_time = time.time()
        return result is not None

    # ------------------- 公共消息 -------------------
    async def get_public_messages(self, limit: int = 20, last_id: Optional[str] = None) -> List[Dict]:
        params = {
            "api_key": self.api_key,
            "action": "get_messages",
            "type": "public",
            "limit": limit
        }
        if last_id:
            params["last_id"] = last_id
        data = await self._get(params)
        if data and "messages" in data:
            return data["messages"]
        return []

    async def send_public_message(self, content: str) -> bool:
        params = {
            "api_key": self.api_key,
            "action": "send_message",
            "content": content,
            "recipient_id": "all"
        }
        return await self._post(params)

    # ------------------- 私聊 -------------------
    async def send_private_message(self, content: str, recipient_id: str) -> bool:
        params = {
            "api_key": self.api_key,
            "action": "send_message",
            "content": content,
            "recipient_id": recipient_id
        }
        return await self._post(params)

    async def get_private_messages(self, with_user_id: str = None, limit: int = 20) -> List[Dict]:
        params = {
            "api_key": self.api_key,
            "action": "get_messages",
            "type": "private",
            "limit": limit
        }
        if with_user_id:
            params["with_user_id"] = with_user_id
        data = await self._get(params)
        if data and "messages" in data:
            return data["messages"]
        return []

    # ------------------- 好友系统 -------------------
    async def get_friends(self, page: int = 1, per_page: int = 100) -> List[Dict]:
        params = {
            "api_key": self.api_key,
            "action": "get_friends",
            "page": page,
            "per_page": per_page
        }
        data = await self._get(params)
        if data and "friends" in data:
            return data["friends"]
        return []

    async def add_friend(self, user_id: str, message: str = "") -> bool:
        params = {
            "api_key": self.api_key,
            "action": "add_friend",
            "user_id": user_id,
            "message": message
        }
        return await self._post(params)

    async def accept_friend(self, request_id: str) -> bool:
        params = {
            "api_key": self.api_key,
            "action": "accept_friend",
            "request_id": request_id
        }
        return await self._post(params)

    async def delete_friend(self, friend_id: str) -> bool:
        params = {
            "api_key": self.api_key,
            "action": "delete_friend",
            "friend_id": friend_id
        }
        return await self._post(params)

    async def get_friend_requests(self) -> List[Dict]:
        params = {
            "api_key": self.api_key,
            "action": "get_friend_requests"
        }
        data = await self._get(params)
        if data and "requests" in data:
            return data["requests"]
        return []

    # ------------------- 群聊 -------------------
    async def get_group_messages(self, group_id: str, limit: int = 20) -> List[Dict]:
        params = {
            "api_key": self.api_key,
            "action": "get_messages",
            "group_id": group_id,
            "limit": limit
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(self.GROUP_BASE_URL, params=params) as resp:
                result = await resp.json()
                if result.get("status") == 200 and "messages" in result.get("data", {}):
                    return result["data"]["messages"]
                return []

    async def send_group_message(self, content: str, group_id: str) -> bool:
        params = {
            "api_key": self.api_key,
            "action": "send_message",
            "group_id": group_id,
            "content": content
        }
        now = time.time()
        if now - self.last_message_time < self.min_interval:
            await asyncio.sleep(self.min_interval - (now - self.last_message_time))
        async with aiohttp.ClientSession() as session:
            async with session.post(self.GROUP_BASE_URL, params=params) as resp:
                self.last_message_time = time.time()
                result = await resp.json()
                return result.get("status") == 200

    # ------------------- 个人信息 -------------------
    async def get_profile(self) -> Optional[Dict]:
        params = {
            "api_key": self.api_key,
            "action": "get_profile"
        }
        return await self._get(params)

    async def update_profile(self, display_name: str = None, bio: str = None) -> bool:
        params = {
            "api_key": self.api_key,
            "action": "update_profile"
        }
        if display_name:
            params["display_name"] = display_name
        if bio:
            params["bio"] = bio
        return await self._post(params)


@register("pymchat", "Your Name", "PymChat 聊天室插件，支持公共聊天室、私聊、好友系统、群聊", "1.1.0", "https://github.com/yourusername/astrbot_plugin_pymchat")
class PymChatPlugin(Plugin):
    def __init__(self, context: Context):
        super().__init__(context)
        self.config = self._load_config()
        self.client: Optional[PymChatClient] = None
        self.bot_name: Optional[str] = None
        self.running: bool = False
        self.poll_task: Optional[asyncio.Task] = None
        self.last_msg_id: Optional[str] = None

        # 配置参数
        self.username = self.config.get("username", "")
        self.password = self.config.get("password", "")
        self.api_key = self.config.get("api_key", "")
        self.bot_name_config = self.config.get("bot_name", "")
        self.trigger_keywords = [kw.strip() for kw in self.config.get("trigger_keywords", "bot").split(",")]
        self.system_prompt = self.config.get("system_prompt", "你是一个友好的 AI 助手，请用中文回答问题。")
        self.poll_interval = self.config.get("poll_interval", 3)
        self.auto_reconnect = self.config.get("auto_reconnect", True)
        self.enable_private_chat = self.config.get("enable_private_chat", True)
        self.enable_group_chat = self.config.get("enable_group_chat", False)
        self.max_message_length = self.config.get("max_message_length", 500)

    def _load_config(self) -> dict:
        try:
            config = self.context.get_plugin_config()
            if config:
                return config
        except:
            pass
        config_file = os.path.join(os.path.dirname(__file__), "config.json")
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    async def initialize(self):
        logger.info("PymChat 插件初始化中...")
        self.client = PymChatClient(api_key=self.api_key if self.api_key else None)
        if not self.client.api_key and self.username and self.password:
            success = await self.client.login(self.username, self.password)
            if not success:
                logger.error("PymChat 登录失败，插件将无法正常工作")
                return
        elif self.client.api_key:
            profile = await self.client.get_profile()
            if not profile:
                logger.warning("提供的 api_key 无效，请检查配置")
                return
            self.client.user_id = profile.get("user_id")
        else:
            logger.error("未提供 api_key 或用户名密码，PymChat 插件无法启动")
            return

        if self.bot_name_config:
            self.bot_name = self.bot_name_config
        else:
            profile = await self.client.get_profile()
            if profile:
                self.bot_name = profile.get("display_name") or profile.get("username")
            else:
                self.bot_name = "Bot"

        logger.info(f"PymChat 机器人昵称: {self.bot_name}")
        self.running = True
        self.poll_task = asyncio.create_task(self._poll_messages())
        logger.info("PymChat 插件已启动")

    async def _poll_messages(self):
        while self.running:
            try:
                messages = await self.client.get_public_messages(limit=20, last_id=self.last_msg_id)
                if messages:
                    for msg in reversed(messages):
                        if self._should_handle_message(msg):
                            await self._handle_pymchat_message(msg)
                        self.last_msg_id = msg.get("id")
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"轮询消息异常: {e}")
                if self.auto_reconnect:
                    await asyncio.sleep(5)
                else:
                    break

    def _should_handle_message(self, msg: Dict) -> bool:
        sender_id = msg.get("user_id")
        if sender_id == self.client.user_id:
            return False
        content = msg.get("content", "")
        if content.startswith(f"@{self.bot_name}"):
            return True
        for kw in self.trigger_keywords:
            if content.startswith(kw) or f" {kw}" in content:
                return True
        return False

    async def _handle_pymchat_message(self, msg: Dict):
        content = msg.get("content", "")
        sender_name = msg.get("display_name") or msg.get("username", "用户")
        if content.startswith(f"@{self.bot_name}"):
            question = content[len(f"@{self.bot_name}"):].strip()
        else:
            for kw in self.trigger_keywords:
                if content.startswith(kw):
                    question = content[len(kw):].strip()
                    break
                elif f" {kw}" in content:
                    parts = content.split(kw, 1)
                    question = parts[1].strip() if len(parts) > 1 else ""
                    break
            else:
                question = content

        if not question:
            return

        try:
            llm_provider = self.context.get_llm_provider()
            if llm_provider:
                prompt = f"{self.system_prompt}\n用户 {sender_name} 说: {question}\n请回复:"
                response = await llm_provider.text_chat(prompt, session_id=f"pymchat_{self.client.user_id}")
                reply_text = response.get("content", "抱歉，我无法生成回复。")
            else:
                reply_text = f"收到你的消息: {question}"
        except Exception as e:
            logger.error(f"AI 回复生成失败: {e}")
            reply_text = "处理消息时出错，请稍后再试。"

        if len(reply_text) > self.max_message_length:
            reply_text = reply_text[:self.max_message_length]
        success = await self.client.send_public_message(reply_text)
        if success:
            logger.info(f"回复消息给 {sender_name}: {reply_text}")
        else:
            logger.error("发送回复失败")

    # ------------------- 命令 -------------------
    @command_group("pymchat")
    def pymchat(self):
        pass

    @pymchat.command("status")
    async def status_cmd(self, event: AstrMessageEvent):
        status_lines = [
            "📊 **PymChat 状态**",
            f"👤 机器人昵称: {self.bot_name or '未设置'}",
            f"🔑 API Key: {'✅ 已配置' if self.client and self.client.api_key else '❌ 未配置'}",
            f"🌐 状态: {'🟢 运行中' if self.running else '🔴 已停止'}",
            f"🔄 自动重连: {'✅' if self.auto_reconnect else '❌'}",
            f"💬 私聊功能: {'✅' if self.enable_private_chat else '❌'}",
            f"👥 群聊功能: {'✅' if self.enable_group_chat else '❌'}",
            f"⏱️ 轮询间隔: {self.poll_interval}秒",
            f"📏 最大消息长度: {self.max_message_length}",
            f"🔑 触发关键词: {', '.join(self.trigger_keywords)}"
        ]
        yield event.plain_result("\n".join(status_lines))

    @pymchat.command("sync_nickname")
    async def sync_nickname(self, event: AstrMessageEvent):
        if not self.client:
            yield event.plain_result("❌ 客户端未初始化")
            return
        profile = await self.client.get_profile()
        if profile:
            self.bot_name = profile.get("display_name") or profile.get("username")
            yield event.plain_result(f"✅ 昵称已同步: {self.bot_name}")
        else:
            yield event.plain_result("❌ 同步失败，请检查 API 连接")

    @pymchat.command("send_public")
    async def send_public(self, event: AstrMessageEvent, *content):
        message = " ".join(content)
        if not message:
            yield event.plain_result("消息内容不能为空")
            return
        if len(message) > self.max_message_length:
            yield event.plain_result(f"消息过长，最大 {self.max_message_length} 字符")
            return
        success = await self.client.send_public_message(message)
        if success:
            yield event.plain_result("✅ 公共消息已发送")
        else:
            yield event.plain_result("❌ 发送失败")

    @pymchat.command("send_private")
    async def send_private(self, event: AstrMessageEvent, user_id: str, *content):
        if not self.enable_private_chat:
            yield event.plain_result("私聊功能未启用")
            return
        message = " ".join(content)
        if not message:
            yield event.plain_result("消息内容不能为空")
            return
        if len(message) > self.max_message_length:
            yield event.plain_result(f"消息过长，最大 {self.max_message_length} 字符")
            return
        success = await self.client.send_private_message(message, user_id)
        if success:
            yield event.plain_result(f"✅ 私信已发送给用户 {user_id}")
        else:
            yield event.plain_result("❌ 发送失败，请检查用户ID或是否为好友")

    @pymchat.command("friends")
    async def list_friends(self, event: AstrMessageEvent):
        friends = await self.client.get_friends()
        if not friends:
            yield event.plain_result("暂无好友")
            return
        lines = ["👥 **好友列表**"]
        for f in friends:
            name = f.get("display_name") or f.get("username")
            lines.append(f"- {name} (ID: {f.get('user_id')})")
        yield event.plain_result("\n".join(lines))

    @pymchat.command("add_friend")
    async def add_friend_cmd(self, event: AstrMessageEvent, user_id: str, *message):
        msg = " ".join(message) if message else "你好，我是机器人，请求添加好友。"
        success = await self.client.add_friend(user_id, msg)
        if success:
            yield event.plain_result(f"✅ 好友申请已发送给用户 {user_id}")
        else:
            yield event.plain_result("❌ 发送好友申请失败")

    @pymchat.command("friend_requests")
    async def friend_requests(self, event: AstrMessageEvent):
        requests = await self.client.get_friend_requests()
        if not requests:
            yield event.plain_result("暂无好友申请")
            return
        lines = ["📨 **好友申请列表**"]
        for req in requests:
            lines.append(f"- 来自 {req.get('from_user_name')} (ID: {req.get('from_user_id')})，申请ID: {req.get('request_id')}")
        yield event.plain_result("\n".join(lines))

    @pymchat.command("accept_friend")
    async def accept_friend_cmd(self, event: AstrMessageEvent, request_id: str):
        success = await self.client.accept_friend(request_id)
        if success:
            yield event.plain_result("✅ 已同意好友申请")
        else:
            yield event.plain_result("❌ 操作失败")

    @pymchat.command("delete_friend")
    async def delete_friend_cmd(self, event: AstrMessageEvent, friend_id: str):
        success = await self.client.delete_friend(friend_id)
        if success:
            yield event.plain_result("✅ 已删除好友")
        else:
            yield event.plain_result("❌ 删除失败")

    @pymchat.command("group")
    async def group_chat(self, event: AstrMessageEvent, group_id: str, *content):
        if not self.enable_group_chat:
            yield event.plain_result("群聊功能未启用")
            return
        message = " ".join(content)
        if not message:
            yield event.plain_result("消息内容不能为空")
            return
        success = await self.client.send_group_message(message, group_id)
        if success:
            yield event.plain_result(f"✅ 群消息已发送至 {group_id}")
        else:
            yield event.plain_result("❌ 发送失败")

    async def terminate(self):
        self.running = False
        if self.poll_task:
            self.poll_task.cancel()
            try:
                await self.poll_task
            except:
                pass
        if self.client and self.client.session:
            await self.client.session.close()
        logger.info("PymChat 插件已停止")
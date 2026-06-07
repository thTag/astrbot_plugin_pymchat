import asyncio
import json
import os
import time
from typing import Dict, List, Optional, Union

import aiohttp
from astrbot.api import logger
from astrbot.api.star import Context, Star, register
from astrbot.api.event import AstrMessageEvent, filter


class PymChatClient:
    """PymChat API 客户端封装"""
    BASE_URL = "https://chat.qplm.xyz/api/ac.php"
    LOGIN_URL = "https://chat.qplm.xyz/api/login.php"
    GROUP_BASE_URL = "https://chat.qplm.xyz/qunliao/api.php"

    def __init__(self, api_key: Optional[str] = None, debug: bool = False):
        self.api_key = api_key
        self.user_id: Optional[str] = None
        self.last_message_time: float = 0
        self.min_interval: float = 3.0
        self.session: Optional[aiohttp.ClientSession] = None
        self.debug = debug

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def _request(self, method: str, url: str, params: dict = None, data: dict = None) -> Optional[dict]:
        # 过滤掉值为 None 的参数，避免 aiohttp 报错
        if params:
            params = {k: v for k, v in params.items() if v is not None}
        if data:
            data = {k: v for k, v in data.items() if v is not None}

        if self.debug:
            logger.debug(f"[PymChat] 请求: {method} {url}")
            logger.debug(f"[PymChat] 参数: {params}")
            if data:
                logger.debug(f"[PymChat] 数据: {data}")

        try:
            async with self.session.request(method, url, params=params, json=data) as resp:
                result = await resp.json()
                if self.debug:
                    logger.debug(f"[PymChat] 响应状态: {resp.status}")
                    logger.debug(f"[PymChat] 响应内容: {result}")

                if resp.status == 429:
                    logger.warning("触发速率限制 (429)，等待 150 秒")
                    await asyncio.sleep(150)
                    return {"error": True, "code": 429, "message": "Rate limited"}
                if result.get("status") == 200:
                    return result.get("data") or result
                else:
                    error_code = result.get("code", resp.status)
                    error_msg = result.get("message", result.get("error", "未知错误"))
                    logger.error(f"API 错误 (code={error_code}): {error_msg}")
                    return {"error": True, "code": error_code, "message": error_msg}
        except Exception as e:
            logger.error(f"请求异常: {e}")
            if self.debug:
                logger.exception("详细错误堆栈:")
            return {"error": True, "code": -1, "message": str(e)}

    async def login(self, username: str, password: str) -> bool:
        data = {"username": username, "password": password}
        if self.debug:
            logger.debug(f"[PymChat] 尝试登录: username={username}")
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(self.LOGIN_URL, json=data) as resp:
                    result = await resp.json()
                    if self.debug:
                        logger.debug(f"[PymChat] 登录响应: {result}")
                    if result.get("status") == 200:
                        self.api_key = result["data"]["api_key"]
                        self.user_id = result["data"].get("user_id")
                        logger.info(f"登录成功，用户ID: {self.user_id}")
                        return True
                    else:
                        error_msg = result.get("message", "登录失败")
                        logger.error(f"登录失败: {error_msg}")
                        return False
            except Exception as e:
                logger.error(f"登录异常: {e}")
                if self.debug:
                    logger.exception("登录详细错误:")
                return False

    async def ensure_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
            if self.debug:
                logger.debug("[PymChat] 创建新的 HTTP 会话")

    async def _get(self, params: dict) -> Optional[dict]:
        await self.ensure_session()
        return await self._request("GET", self.BASE_URL, params=params)

    async def _post(self, params: dict) -> Union[bool, dict]:
        await self.ensure_session()
        now = time.time()
        if now - self.last_message_time < self.min_interval:
            wait = self.min_interval - (now - self.last_message_time)
            if self.debug:
                logger.debug(f"[PymChat] 速率限制，等待 {wait:.2f} 秒")
            await asyncio.sleep(wait)
        result = await self._request("POST", self.BASE_URL, params=params)
        self.last_message_time = time.time()
        # 如果结果是错误字典，返回它；否则返回 bool (True 表示成功)
        if isinstance(result, dict) and result.get("error"):
            return result
        return result is not None

    # ------------------- 公共消息 -------------------
    async def get_public_messages(self, limit: int = 20, last_id: Optional[str] = None) -> List[Dict]:
        params = {
            "api_key": self.api_key,
            "action": "get_messages",
            "type": "public",
            "limit": limit,
            "last_id": last_id
        }
        if self.debug:
            logger.debug(f"[PymChat] 获取公共消息，last_id={last_id}")
        data = await self._get(params)
        if isinstance(data, dict) and data.get("error"):
            logger.error(f"获取公共消息错误: {data.get('message')}")
            return []
        if data and "messages" in data:
            return data["messages"]
        return []

    async def send_public_message(self, content: str) -> bool:
        if self.debug:
            logger.debug(f"[PymChat] 发送公共消息: {content[:50]}...")
        params = {
            "api_key": self.api_key,
            "action": "send_message",
            "content": content,
            "recipient_id": "all"
        }
        result = await self._post(params)
        if isinstance(result, dict) and result.get("error"):
            logger.error(f"发送公共消息失败: {result.get('message')}")
            return False
        return result

    # ------------------- 私聊 -------------------
    async def send_private_message(self, content: str, recipient_id: str) -> bool:
        if self.debug:
            logger.debug(f"[PymChat] 发送私信给 {recipient_id}: {content[:50]}...")
        params = {
            "api_key": self.api_key,
            "action": "send_message",
            "content": content,
            "recipient_id": recipient_id
        }
        result = await self._post(params)
        if isinstance(result, dict) and result.get("error"):
            logger.error(f"发送私信失败: {result.get('message')}")
            return False
        return result

    async def get_private_messages(self, with_user_id: str = None, limit: int = 20) -> List[Dict]:
        params = {
            "api_key": self.api_key,
            "action": "get_messages",
            "type": "private",
            "limit": limit,
            "with_user_id": with_user_id
        }
        if self.debug:
            logger.debug(f"[PymChat] 获取与 {with_user_id} 的私聊消息")
        data = await self._get(params)
        if isinstance(data, dict) and data.get("error"):
            logger.error(f"获取私聊消息错误: {data.get('message')}")
            return []
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
        if self.debug:
            logger.debug(f"[PymChat] 获取好友列表，page={page}")
        data = await self._get(params)
        if isinstance(data, dict) and data.get("error"):
            logger.error(f"获取好友列表错误: {data.get('message')}")
            return []
        if data and "friends" in data:
            return data["friends"]
        return []

    async def add_friend(self, user_id: str, message: str = "") -> bool:
        if self.debug:
            logger.debug(f"[PymChat] 发送好友申请给 {user_id}, 附加消息: {message}")
        params = {
            "api_key": self.api_key,
            "action": "add_friend",
            "user_id": user_id,
            "message": message
        }
        result = await self._post(params)
        if isinstance(result, dict) and result.get("error"):
            logger.error(f"添加好友失败: {result.get('message')}")
            return False
        return result

    async def accept_friend(self, request_id: str) -> bool:
        if self.debug:
            logger.debug(f"[PymChat] 同意好友申请: {request_id}")
        params = {
            "api_key": self.api_key,
            "action": "accept_friend",
            "request_id": request_id
        }
        result = await self._post(params)
        if isinstance(result, dict) and result.get("error"):
            logger.error(f"同意好友申请失败: {result.get('message')}")
            return False
        return result

    async def delete_friend(self, friend_id: str) -> bool:
        if self.debug:
            logger.debug(f"[PymChat] 删除好友: {friend_id}")
        params = {
            "api_key": self.api_key,
            "action": "delete_friend",
            "friend_id": friend_id
        }
        result = await self._post(params)
        if isinstance(result, dict) and result.get("error"):
            logger.error(f"删除好友失败: {result.get('message')}")
            return False
        return result

    async def get_friend_requests(self) -> List[Dict]:
        params = {
            "api_key": self.api_key,
            "action": "get_friend_requests"
        }
        data = await self._get(params)
        if isinstance(data, dict) and data.get("error"):
            logger.error(f"获取好友申请错误: {data.get('message')}")
            return []
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
        if self.debug:
            logger.debug(f"[PymChat] 发送群消息到 {group_id}: {content[:50]}...")
        params = {
            "api_key": self.api_key,
            "action": "send_message",
            "group_id": group_id,
            "content": content
        }
        now = time.time()
        if now - self.last_message_time < self.min_interval:
            wait = self.min_interval - (now - self.last_message_time)
            if self.debug:
                logger.debug(f"[PymChat] 群发速率限制，等待 {wait:.2f} 秒")
            await asyncio.sleep(wait)
        async with aiohttp.ClientSession() as session:
            async with session.post(self.GROUP_BASE_URL, params=params) as resp:
                self.last_message_time = time.time()
                result = await resp.json()
                return result.get("status") == 200

    # ------------------- 个人信息 -------------------
    async def get_profile(self) -> Optional[Dict]:
        if self.debug:
            logger.debug("[PymChat] 获取个人信息")
        params = {
            "api_key": self.api_key,
            "action": "get_profile"
        }
        result = await self._get(params)
        if isinstance(result, dict) and result.get("error"):
            logger.error(f"获取个人信息失败: {result.get('message')} (code={result.get('code')})")
            return None
        return result

    async def update_profile(self, display_name: str = None, bio: str = None) -> bool:
        if self.debug:
            logger.debug(f"[PymChat] 更新个人信息: display_name={display_name}, bio={bio}")
        params = {
            "api_key": self.api_key,
            "action": "update_profile",
            "display_name": display_name,
            "bio": bio
        }
        result = await self._post(params)
        if isinstance(result, dict) and result.get("error"):
            logger.error(f"更新个人信息失败: {result.get('message')}")
            return False
        return result


@register("pymchat", "Your Name", "PymChat 聊天室插件，支持公共聊天室、私聊、好友系统、群聊", "1.2.0", "https://github.com/yourusername/astrbot_plugin_pymchat")
class PymChatPlugin(Star):
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
        self.debug = self.config.get("debug_mode", False)

        logger.info(f"PymChat 插件初始化，调试模式: {'开启' if self.debug else '关闭'}")

    def _load_config(self) -> dict:
        try:
            config = self.context.get_plugin_config()
            if config:
                return config
        except AttributeError:
            logger.warning("当前框架版本不支持 get_plugin_config()，尝试读取本地配置文件。")
        except Exception as e:
            logger.error(f"读取插件配置失败: {e}")

        config_file = os.path.join(os.path.dirname(__file__), "config.json")
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    async def initialize(self):
        logger.info("PymChat 插件初始化中...")
        self.client = PymChatClient(api_key=self.api_key if self.api_key else None, debug=self.debug)
        if not self.client.api_key and self.username and self.password:
            logger.info("使用用户名密码登录获取 API Key...")
            success = await self.client.login(self.username, self.password)
            if not success:
                logger.error("PymChat 登录失败，插件将无法正常工作")
                return
        elif self.client.api_key:
            logger.info("使用提供的 API Key 验证...")
            profile = await self.client.get_profile()
            if not profile:
                logger.warning("提供的 api_key 无效，请检查配置")
                return
            self.client.user_id = profile.get("user_id")
            if self.debug:
                logger.debug(f"API Key 验证成功，用户ID: {self.client.user_id}")
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
        logger.info("开始轮询公共聊天室消息...")
        while self.running:
            try:
                if self.debug:
                    logger.debug(f"[轮询] 获取消息，last_msg_id={self.last_msg_id}")
                messages = await self.client.get_public_messages(limit=20, last_id=self.last_msg_id)
                if messages:
                    if self.debug:
                        logger.debug(f"[轮询] 获取到 {len(messages)} 条新消息")
                    for msg in reversed(messages):
                        if self._should_handle_message(msg):
                            if self.debug:
                                logger.debug(f"[轮询] 需要处理的消息: {msg.get('content', '')[:50]}")
                            await self._handle_pymchat_message(msg)
                        self.last_msg_id = msg.get("id")
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"轮询消息异常: {e}")
                if self.debug:
                    logger.exception("轮询详细错误:")
                if self.auto_reconnect:
                    logger.info("5秒后自动重连...")
                    await asyncio.sleep(5)
                else:
                    break

    def _should_handle_message(self, msg: Dict) -> bool:
        sender_id = msg.get("user_id")
        if sender_id == self.client.user_id:
            if self.debug:
                logger.debug(f"[消息判断] 忽略自己的消息: {msg.get('content', '')[:30]}")
            return False
        content = msg.get("content", "")
        if content.startswith(f"@{self.bot_name}"):
            if self.debug:
                logger.debug(f"[消息判断] @机器人触发: {content}")
            return True
        for kw in self.trigger_keywords:
            if content.startswith(kw) or f" {kw}" in content:
                if self.debug:
                    logger.debug(f"[消息判断] 关键词 '{kw}' 触发: {content}")
                return True
        if self.debug:
            logger.debug(f"[消息判断] 忽略消息: {content[:30]}")
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
            if self.debug:
                logger.debug("[消息处理] 消息内容为空，忽略")
            return

        logger.info(f"收到来自 {sender_name} 的问题: {question}")
        if self.debug:
            logger.debug(f"[消息处理] 完整消息原始内容: {content}")

        try:
            llm_provider = self.context.get_llm_provider()
            if llm_provider:
                prompt = f"{self.system_prompt}\n用户 {sender_name} 说: {question}\n请回复:"
                if self.debug:
                    logger.debug(f"[LLM] 请求 prompt: {prompt[:200]}...")
                response = await llm_provider.text_chat(prompt, session_id=f"pymchat_{self.client.user_id}")
                reply_text = response.get("content", "抱歉，我无法生成回复。")
                if self.debug:
                    logger.debug(f"[LLM] 回复内容: {reply_text[:200]}...")
            else:
                reply_text = f"收到你的消息: {question}"
                logger.warning("未配置 LLM 提供者，使用简单回显")
        except Exception as e:
            logger.error(f"AI 回复生成失败: {e}")
            if self.debug:
                logger.exception("LLM 调用异常:")
            reply_text = "处理消息时出错，请稍后再试。"

        if len(reply_text) > self.max_message_length:
            reply_text = reply_text[:self.max_message_length]
            if self.debug:
                logger.debug(f"[消息处理] 回复被截断至 {self.max_message_length} 字符")

        success = await self.client.send_public_message(reply_text)
        if success:
            logger.info(f"已回复 {sender_name}: {reply_text[:100]}...")
        else:
            logger.error("发送回复失败")

    # ------------------- 命令 -------------------
    @filter.command("pymchat")
    async def pymchat_status(self, event: AstrMessageEvent):
        """查看 PymChat 插件状态"""
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
            f"🔑 触发关键词: {', '.join(self.trigger_keywords)}",
            f"🐛 调试模式: {'✅ 开启' if self.debug else '❌ 关闭'}"
        ]
        yield event.plain_result("\n".join(status_lines))

    @filter.command("pymchat_sync")
    async def sync_nickname(self, event: AstrMessageEvent):
        """同步昵称到 AstrBot"""
        if not self.client:
            yield event.plain_result("❌ 客户端未初始化")
            return
        if self.debug:
            logger.debug("[命令] 执行同步昵称")
        profile = await self.client.get_profile()
        if profile:
            self.bot_name = profile.get("display_name") or profile.get("username")
            logger.info(f"昵称已同步: {self.bot_name}")
            yield event.plain_result(f"✅ 昵称已同步: {self.bot_name}")
        else:
            # 此时 profile 为 None，但日志中已经有详细错误信息
            # 我们从 client 最近的错误中获取信息？目前 client 没有存储最后错误，所以直接提示
            yield event.plain_result("❌ 同步失败，请检查 API 连接。详细信息请查看日志输出中的错误码和消息。")

    @filter.command("pymchat_send")
    async def send_public(self, event: AstrMessageEvent, *content):
        """手动发送公共消息：/pymchat_send <消息内容>"""
        message = " ".join(content)
        if not message:
            yield event.plain_result("消息内容不能为空")
            return
        if len(message) > self.max_message_length:
            yield event.plain_result(f"消息过长，最大 {self.max_message_length} 字符")
            return
        if self.debug:
            logger.debug(f"[命令] 发送公共消息: {message}")
        success = await self.client.send_public_message(message)
        if success:
            logger.info(f"手动发送公共消息成功: {message[:50]}...")
            yield event.plain_result("✅ 公共消息已发送")
        else:
            logger.error("手动发送公共消息失败")
            yield event.plain_result("❌ 发送失败")

    @filter.command("pymchat_send_private")
    async def send_private(self, event: AstrMessageEvent, user_id: str, *content):
        """发送私信：/pymchat_send_private <用户ID> <消息内容>"""
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
        if self.debug:
            logger.debug(f"[命令] 发送私信给 {user_id}: {message[:50]}...")
        success = await self.client.send_private_message(message, user_id)
        if success:
            logger.info(f"私信已发送给 {user_id}: {message[:50]}...")
            yield event.plain_result(f"✅ 私信已发送给用户 {user_id}")
        else:
            logger.error(f"发送私信给 {user_id} 失败")
            yield event.plain_result("❌ 发送失败，请检查用户ID或是否为好友")

    @filter.command("pymchat_friends")
    async def list_friends(self, event: AstrMessageEvent):
        """查看好友列表"""
        if self.debug:
            logger.debug("[命令] 获取好友列表")
        friends = await self.client.get_friends()
        if not friends:
            yield event.plain_result("暂无好友")
            return
        lines = ["👥 **好友列表**"]
        for f in friends:
            name = f.get("display_name") or f.get("username")
            lines.append(f"- {name} (ID: {f.get('user_id')})")
        if self.debug:
            logger.debug(f"获取到 {len(friends)} 个好友")
        yield event.plain_result("\n".join(lines))

    @filter.command("pymchat_add_friend")
    async def add_friend_cmd(self, event: AstrMessageEvent, user_id: str, *message):
        """发送好友申请：/pymchat_add_friend <用户ID> [附加消息]"""
        msg = " ".join(message) if message else "你好，我是机器人，请求添加好友。"
        if self.debug:
            logger.debug(f"[命令] 发送好友申请给 {user_id}, 附加消息: {msg}")
        success = await self.client.add_friend(user_id, msg)
        if success:
            logger.info(f"好友申请已发送给 {user_id}")
            yield event.plain_result(f"✅ 好友申请已发送给用户 {user_id}")
        else:
            logger.error(f"发送好友申请给 {user_id} 失败")
            yield event.plain_result("❌ 发送好友申请失败")

    @filter.command("pymchat_friend_requests")
    async def friend_requests(self, event: AstrMessageEvent):
        """查看好友申请列表"""
        if self.debug:
            logger.debug("[命令] 获取好友申请列表")
        requests = await self.client.get_friend_requests()
        if not requests:
            yield event.plain_result("暂无好友申请")
            return
        lines = ["📨 **好友申请列表**"]
        for req in requests:
            lines.append(f"- 来自 {req.get('from_user_name')} (ID: {req.get('from_user_id')})，申请ID: {req.get('request_id')}")
        if self.debug:
            logger.debug(f"获取到 {len(requests)} 个好友申请")
        yield event.plain_result("\n".join(lines))

    @filter.command("pymchat_accept_friend")
    async def accept_friend_cmd(self, event: AstrMessageEvent, request_id: str):
        """同意好友申请：/pymchat_accept_friend <申请ID>"""
        if self.debug:
            logger.debug(f"[命令] 同意好友申请: {request_id}")
        success = await self.client.accept_friend(request_id)
        if success:
            logger.info(f"已同意好友申请: {request_id}")
            yield event.plain_result("✅ 已同意好友申请")
        else:
            logger.error(f"同意好友申请 {request_id} 失败")
            yield event.plain_result("❌ 操作失败")

    @filter.command("pymchat_delete_friend")
    async def delete_friend_cmd(self, event: AstrMessageEvent, friend_id: str):
        """删除好友：/pymchat_delete_friend <好友ID>"""
        if self.debug:
            logger.debug(f"[命令] 删除好友: {friend_id}")
        success = await self.client.delete_friend(friend_id)
        if success:
            logger.info(f"已删除好友: {friend_id}")
            yield event.plain_result("✅ 已删除好友")
        else:
            logger.error(f"删除好友 {friend_id} 失败")
            yield event.plain_result("❌ 删除失败")

    @filter.command("pymchat_group")
    async def group_chat(self, event: AstrMessageEvent, group_id: str, *content):
        """发送群消息：/pymchat_group <群号> <消息内容> (需启用群聊功能)"""
        if not self.enable_group_chat:
            yield event.plain_result("群聊功能未启用")
            return
        message = " ".join(content)
        if not message:
            yield event.plain_result("消息内容不能为空")
            return
        if self.debug:
            logger.debug(f"[命令] 发送群消息到 {group_id}: {message[:50]}...")
        success = await self.client.send_group_message(message, group_id)
        if success:
            logger.info(f"群消息已发送至 {group_id}: {message[:50]}...")
            yield event.plain_result(f"✅ 群消息已发送至 {group_id}")
        else:
            logger.error(f"发送群消息到 {group_id} 失败")
            yield event.plain_result("❌ 发送失败")

    @filter.command("pymchat_debug")
    async def toggle_debug(self, event: AstrMessageEvent, *args):
        """切换调试模式：/pymchat_debug [on/off] 或不带参数查看当前状态"""
        if args:
            cmd = args[0].lower()
            if cmd == "on":
                self.debug = True
                if self.client:
                    self.client.debug = True
                logger.info("调试模式已开启")
                yield event.plain_result("🐛 调试模式已开启")
                return
            elif cmd == "off":
                self.debug = False
                if self.client:
                    self.client.debug = False
                logger.info("调试模式已关闭")
                yield event.plain_result("🐛 调试模式已关闭")
                return
        status = "开启" if self.debug else "关闭"
        yield event.plain_result(f"🐛 当前调试模式: {status}\n使用 /pymchat_debug on 开启，/pymchat_debug off 关闭")

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
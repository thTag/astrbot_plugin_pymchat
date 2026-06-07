import asyncio
import time
from typing import Dict, List, Optional, Tuple

import aiohttp
from astrbot.api import logger, AstrBotConfig
from astrbot.api.star import Context, Star, register
from astrbot.api.event import AstrMessageEvent, filter


class APIError(Exception):
    def __init__(self, code: int, message: str, http_status: int = 0):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(f"[{code}] {message}")


class PymChatClient:
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

    def _clean_params(self, params: dict) -> dict:
        return {k: v for k, v in params.items() if v is not None}

    async def _request(self, method: str, url: str, params: dict = None, data: dict = None) -> Tuple[bool, Optional[dict], Optional[APIError]]:
        if params is None:
            params = {}
        params = self._clean_params(params)

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
                    return False, None, APIError(429, "触发速率限制，请稍后再试", 429)

                if result.get("status") != 200:
                    error_code = result.get("code", resp.status)
                    error_msg = result.get("message", result.get("error", "未知错误"))
                    logger.error(f"API 错误 (code={error_code}): {error_msg}")
                    return False, None, APIError(error_code, error_msg, resp.status)

                return True, result.get("data") or result, None

        except aiohttp.ClientError as e:
            logger.error(f"网络请求异常: {e}")
            if self.debug:
                logger.exception("详细网络错误:")
            return False, None, APIError(0, f"网络错误: {str(e)}", 0)
        except Exception as e:
            logger.error(f"请求异常: {e}")
            if self.debug:
                logger.exception("详细错误堆栈:")
            return False, None, APIError(0, f"内部错误: {str(e)}", 0)

    async def login(self, username: str, password: str) -> Tuple[bool, Optional[str], Optional[APIError]]:
        data = {"username": username, "password": password}
        logger.info(f"尝试登录 PymChat，用户名: {username}")
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
                        return True, self.api_key, None
                    else:
                        error_code = result.get("code", resp.status)
                        error_msg = result.get("message", "登录失败")
                        logger.error(f"登录失败: {error_msg} (code={error_code})")
                        return False, None, APIError(error_code, error_msg, resp.status)
            except Exception as e:
                logger.error(f"登录异常: {e}")
                if self.debug:
                    logger.exception("登录详细错误:")
                return False, None, APIError(0, f"登录异常: {str(e)}", 0)

    async def ensure_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
            if self.debug:
                logger.debug("[PymChat] 创建新的 HTTP 会话")

    async def _get(self, params: dict) -> Tuple[bool, Optional[dict], Optional[APIError]]:
        await self.ensure_session()
        if not self.api_key:
            return False, None, APIError(401, "API Key 未设置，请检查配置", 401)
        return await self._request("GET", self.BASE_URL, params=params)

    async def _post(self, params: dict) -> Tuple[bool, Optional[dict], Optional[APIError]]:
        await self.ensure_session()
        if not self.api_key:
            return False, None, APIError(401, "API Key 未设置，请检查配置", 401)

        now = time.time()
        if now - self.last_message_time < self.min_interval:
            wait = self.min_interval - (now - self.last_message_time)
            if self.debug:
                logger.debug(f"[PymChat] 速率限制，等待 {wait:.2f} 秒")
            await asyncio.sleep(wait)
        success, data, error = await self._request("POST", self.BASE_URL, params=params)
        self.last_message_time = time.time()
        return success, data, error

    # ------------------- 公共消息 -------------------
    async def get_public_messages(self, limit: int = 20, last_id: Optional[str] = None) -> Tuple[bool, List[Dict], Optional[APIError]]:
        params = {
            "api_key": self.api_key,
            "action": "get_messages",
            "type": "public",
            "limit": limit,
            "last_id": last_id
        }
        success, data, error = await self._get(params)
        if success and data and "messages" in data:
            return True, data["messages"], None
        elif success:
            return True, [], None
        else:
            return False, [], error

    async def send_public_message(self, content: str) -> Tuple[bool, Optional[APIError]]:
        params = {
            "api_key": self.api_key,
            "action": "send_message",
            "content": content,
            "recipient_id": "all"
        }
        success, _, error = await self._post(params)
        return success, error

    # ------------------- 私聊 -------------------
    async def send_private_message(self, content: str, recipient_id: str) -> Tuple[bool, Optional[APIError]]:
        params = {
            "api_key": self.api_key,
            "action": "send_message",
            "content": content,
            "recipient_id": recipient_id
        }
        success, _, error = await self._post(params)
        return success, error

    async def get_private_messages(self, with_user_id: str = None, limit: int = 20) -> Tuple[bool, List[Dict], Optional[APIError]]:
        params = {
            "api_key": self.api_key,
            "action": "get_messages",
            "type": "private",
            "limit": limit,
            "with_user_id": with_user_id
        }
        success, data, error = await self._get(params)
        if success and data and "messages" in data:
            return True, data["messages"], None
        elif success:
            return True, [], None
        else:
            return False, [], error

    # ------------------- 好友 -------------------
    async def get_friends(self, page: int = 1, per_page: int = 100) -> Tuple[bool, List[Dict], Optional[APIError]]:
        params = {
            "api_key": self.api_key,
            "action": "get_friends",
            "page": page,
            "per_page": per_page
        }
        success, data, error = await self._get(params)
        if success and data and "friends" in data:
            return True, data["friends"], None
        elif success:
            return True, [], None
        else:
            return False, [], error

    async def add_friend(self, user_id: str, message: str = "") -> Tuple[bool, Optional[APIError]]:
        params = {
            "api_key": self.api_key,
            "action": "add_friend",
            "user_id": user_id,
            "message": message
        }
        success, _, error = await self._post(params)
        return success, error

    async def accept_friend(self, request_id: str) -> Tuple[bool, Optional[APIError]]:
        params = {
            "api_key": self.api_key,
            "action": "accept_friend",
            "request_id": request_id
        }
        success, _, error = await self._post(params)
        return success, error

    async def delete_friend(self, friend_id: str) -> Tuple[bool, Optional[APIError]]:
        params = {
            "api_key": self.api_key,
            "action": "delete_friend",
            "friend_id": friend_id
        }
        success, _, error = await self._post(params)
        return success, error

    async def get_friend_requests(self) -> Tuple[bool, List[Dict], Optional[APIError]]:
        params = {
            "api_key": self.api_key,
            "action": "get_friend_requests"
        }
        success, data, error = await self._get(params)
        if success and data and "requests" in data:
            return True, data["requests"], None
        elif success:
            return True, [], None
        else:
            return False, [], error

    # ------------------- 群聊 -------------------
    async def get_group_messages(self, group_id: str, limit: int = 20) -> Tuple[bool, List[Dict], Optional[APIError]]:
        if not self.api_key:
            return False, [], APIError(401, "API Key 未设置", 401)
        params = {
            "api_key": self.api_key,
            "action": "get_messages",
            "group_id": group_id,
            "limit": limit
        }
        params = self._clean_params(params)
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(self.GROUP_BASE_URL, params=params) as resp:
                    result = await resp.json()
                    if result.get("status") == 200 and "messages" in result.get("data", {}):
                        return True, result["data"]["messages"], None
                    else:
                        error_msg = result.get("message", "获取群消息失败")
                        return False, [], APIError(result.get("code", resp.status), error_msg, resp.status)
            except Exception as e:
                logger.error(f"获取群消息异常: {e}")
                return False, [], APIError(0, f"网络错误: {str(e)}", 0)

    async def send_group_message(self, content: str, group_id: str) -> Tuple[bool, Optional[APIError]]:
        if not self.api_key:
            return False, APIError(401, "API Key 未设置", 401)
        params = {
            "api_key": self.api_key,
            "action": "send_message",
            "group_id": group_id,
            "content": content
        }
        params = self._clean_params(params)
        now = time.time()
        if now - self.last_message_time < self.min_interval:
            wait = self.min_interval - (now - self.last_message_time)
            if self.debug:
                logger.debug(f"[PymChat] 群发速率限制，等待 {wait:.2f} 秒")
            await asyncio.sleep(wait)
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(self.GROUP_BASE_URL, params=params) as resp:
                    self.last_message_time = time.time()
                    result = await resp.json()
                    if result.get("status") == 200:
                        return True, None
                    else:
                        error_msg = result.get("message", "发送群消息失败")
                        return False, APIError(result.get("code", resp.status), error_msg, resp.status)
            except Exception as e:
                logger.error(f"发送群消息异常: {e}")
                return False, APIError(0, f"网络错误: {str(e)}", 0)

    # ------------------- 个人信息 -------------------
    async def get_profile(self) -> Tuple[bool, Optional[Dict], Optional[APIError]]:
        params = {
            "api_key": self.api_key,
            "action": "get_profile"
        }
        return await self._get(params)

    async def update_profile(self, display_name: str = None, bio: str = None) -> Tuple[bool, Optional[APIError]]:
        params = {
            "api_key": self.api_key,
            "action": "update_profile",
            "display_name": display_name,
            "bio": bio
        }
        success, _, error = await self._post(params)
        return success, error


@register("pymchat", "Your Name", "PymChat 聊天室插件，支持公共聊天室、私聊、好友系统、群聊", "1.3.0", "https://github.com/yourusername/astrbot_plugin_pymchat")
class PymChatPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        # 配置由框架自动注入，内容为 _conf_schema.json 定义的字段
        self.config = config
        self.client: Optional[PymChatClient] = None
        self.bot_name: Optional[str] = None
        self.running: bool = False
        self.poll_task: Optional[asyncio.Task] = None
        self.last_msg_id: Optional[str] = None
        self.init_error: Optional[str] = None

        # 从 config 中读取配置（支持字典方法）
        self.username = self.config.get("username", "")
        self.password = self.config.get("password", "")
        self.api_key = self.config.get("api_key", "")
        self.bot_name_config = self.config.get("bot_name", "")
        raw_keywords = self.config.get("trigger_keywords", "bot")
        self.trigger_keywords = [kw.strip() for kw in raw_keywords.split(",")] if isinstance(raw_keywords, str) else ["bot"]
        self.system_prompt = self.config.get("system_prompt", "你是一个友好的 AI 助手，请用中文回答问题。")
        self.poll_interval = self.config.get("poll_interval", 3)
        self.auto_reconnect = self.config.get("auto_reconnect", True)
        self.enable_private_chat = self.config.get("enable_private_chat", True)
        self.enable_group_chat = self.config.get("enable_group_chat", False)
        self.max_message_length = self.config.get("max_message_length", 500)
        self.debug = self.config.get("debug_mode", False)

        logger.info(f"PymChat 插件初始化，调试模式: {'开启' if self.debug else '关闭'}")
        logger.info(f"配置摘要: username={self.username}, api_key={'已设置' if self.api_key else '未设置'}, trigger={self.trigger_keywords}")

    async def _do_initialize(self):
        """执行认证和启动准备"""
        self.init_error = None
        logger.info("开始 PymChat 认证...")
        self.client = PymChatClient(api_key=self.api_key if self.api_key else None, debug=self.debug)

        auth_success = False
        if self.api_key:
            logger.info("使用提供的 API Key 验证...")
            success, profile, error = await self.client.get_profile()
            if success:
                self.client.user_id = profile.get("user_id")
                auth_success = True
                logger.info(f"API Key 验证成功，用户ID: {self.client.user_id}")
            else:
                err_msg = f"API Key 无效: {error.message if error else '未知错误'}"
                logger.error(err_msg)
                self.init_error = err_msg
        elif self.username and self.password:
            logger.info(f"尝试使用用户名密码登录: {self.username}")
            success, api_key, error = await self.client.login(self.username, self.password)
            if success:
                self.api_key = api_key
                self.client.api_key = api_key
                auth_success = True
                logger.info("用户名密码登录成功，已获取 API Key")
            else:
                err_msg = f"登录失败: {error.message if error else '未知错误'}"
                logger.error(err_msg)
                self.init_error = err_msg
        else:
            err_msg = "未提供 api_key 或用户名密码，无法认证"
            logger.error(err_msg)
            self.init_error = err_msg

        if not auth_success:
            logger.error("PymChat 认证失败，插件将保持停止状态。")
            return False

        # 获取机器人昵称
        if self.bot_name_config:
            self.bot_name = self.bot_name_config
        else:
            success, profile, error = await self.client.get_profile()
            if success and profile:
                self.bot_name = profile.get("display_name") or profile.get("username")
            else:
                self.bot_name = "Bot"

        logger.info(f"PymChat 机器人昵称: {self.bot_name}")
        return True

    async def initialize(self):
        """插件启动时的初始化"""
        success = await self._do_initialize()
        if success:
            self.running = True
            self.poll_task = asyncio.create_task(self._poll_messages())
            logger.info("PymChat 插件已启动并开始轮询")
        else:
            self.running = False
            logger.warning("PymChat 插件启动失败，请检查配置后使用 /pymchat_reload 重试")

    async def _poll_messages(self):
        logger.info("开始轮询公共聊天室消息...")
        while self.running:
            try:
                if self.debug:
                    logger.debug(f"[轮询] 获取消息，last_msg_id={self.last_msg_id}")
                success, messages, error = await self.client.get_public_messages(limit=20, last_id=self.last_msg_id)
                if not success:
                    logger.error(f"轮询消息失败: {error.message if error else '未知错误'}")
                    if self.auto_reconnect:
                        await asyncio.sleep(5)
                        continue
                    else:
                        break
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
        if not self.client:
            return False
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

        success, error = await self.client.send_public_message(reply_text)
        if success:
            logger.info(f"已回复 {sender_name}: {reply_text[:100]}...")
        else:
            logger.error(f"发送回复失败: {error.message if error else '未知错误'}")

    # ------------------- 命令 -------------------
    @filter.command("pymchat")
    async def pymchat_status(self, event: AstrMessageEvent):
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
        if self.init_error:
            status_lines.append(f"⚠️ 初始化失败原因: {self.init_error}")
        yield event.plain_result("\n".join(status_lines))

    @filter.command("pymchat_reload")
    async def reload_plugin(self, event: AstrMessageEvent):
        """重新加载配置并尝试重新初始化（无需重启机器人）"""
        yield event.plain_result("🔄 正在重新加载配置并尝试初始化...")
        # 停止当前轮询
        self.running = False
        if self.poll_task:
            self.poll_task.cancel()
            try:
                await self.poll_task
            except:
                pass
        if self.client and self.client.session:
            await self.client.session.close()

        # 从框架重新获取配置（注意：config 对象不会自动更新，需要重新读取）
        # 但 AstrBotConfig 实例在插件生命周期内不会自动更新，所以这里直接使用 self.config 中的值已经是最新的
        # 如果框架支持热更新，可以调用 self.config.load()，但为了可靠，重新从 self.config 读取配置值
        self.username = self.config.get("username", "")
        self.password = self.config.get("password", "")
        self.api_key = self.config.get("api_key", "")
        self.bot_name_config = self.config.get("bot_name", "")
        raw_keywords = self.config.get("trigger_keywords", "bot")
        self.trigger_keywords = [kw.strip() for kw in raw_keywords.split(",")] if isinstance(raw_keywords, str) else ["bot"]
        self.system_prompt = self.config.get("system_prompt", "你是一个友好的 AI 助手，请用中文回答问题。")
        self.poll_interval = self.config.get("poll_interval", 3)
        self.auto_reconnect = self.config.get("auto_reconnect", True)
        self.enable_private_chat = self.config.get("enable_private_chat", True)
        self.enable_group_chat = self.config.get("enable_group_chat", False)
        self.max_message_length = self.config.get("max_message_length", 500)
        self.debug = self.config.get("debug_mode", False)

        logger.info(f"配置已重新加载: username={self.username}, api_key={'已设置' if self.api_key else '未设置'}")
        success = await self._do_initialize()
        if success:
            self.running = True
            self.poll_task = asyncio.create_task(self._poll_messages())
            yield event.plain_result("✅ 重新初始化成功，插件已启动")
        else:
            yield event.plain_result(f"❌ 重新初始化失败: {self.init_error}")

    @filter.command("pymchat_sync")
    async def sync_nickname(self, event: AstrMessageEvent):
        if not self.client:
            yield event.plain_result("❌ 客户端未初始化，请先使用 /pymchat_reload 尝试重新初始化")
            return
        if self.debug:
            logger.debug("[命令] 执行同步昵称")
        success, profile, error = await self.client.get_profile()
        if success and profile:
            self.bot_name = profile.get("display_name") or profile.get("username")
            logger.info(f"昵称已同步: {self.bot_name}")
            yield event.plain_result(f"✅ 昵称已同步: {self.bot_name}")
        else:
            if error:
                error_detail = f"错误码 {error.code}: {error.message}"
                logger.error(f"同步昵称失败: {error_detail}")
                yield event.plain_result(f"❌ 同步失败：{error_detail}")
            else:
                logger.error("同步昵称失败: 未知错误")
                yield event.plain_result("❌ 同步失败，未知错误")

    @filter.command("pymchat_send")
    async def send_public(self, event: AstrMessageEvent, *content):
        if not self.client:
            yield event.plain_result("❌ 客户端未初始化")
            return
        message = " ".join(content)
        if not message:
            yield event.plain_result("消息内容不能为空")
            return
        if len(message) > self.max_message_length:
            yield event.plain_result(f"消息过长，最大 {self.max_message_length} 字符")
            return
        if self.debug:
            logger.debug(f"[命令] 发送公共消息: {message}")
        success, error = await self.client.send_public_message(message)
        if success:
            logger.info(f"手动发送公共消息成功: {message[:50]}...")
            yield event.plain_result("✅ 公共消息已发送")
        else:
            error_msg = f"发送失败: {error.message}" if error else "发送失败"
            logger.error(error_msg)
            yield event.plain_result(f"❌ {error_msg}")

    @filter.command("pymchat_send_private")
    async def send_private(self, event: AstrMessageEvent, user_id: str, *content):
        if not self.client:
            yield event.plain_result("❌ 客户端未初始化")
            return
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
        success, error = await self.client.send_private_message(message, user_id)
        if success:
            logger.info(f"私信已发送给 {user_id}: {message[:50]}...")
            yield event.plain_result(f"✅ 私信已发送给用户 {user_id}")
        else:
            error_msg = f"发送失败: {error.message}" if error else "发送失败"
            logger.error(error_msg)
            yield event.plain_result(f"❌ {error_msg}")

    @filter.command("pymchat_friends")
    async def list_friends(self, event: AstrMessageEvent):
        if not self.client:
            yield event.plain_result("❌ 客户端未初始化")
            return
        if self.debug:
            logger.debug("[命令] 获取好友列表")
        success, friends, error = await self.client.get_friends()
        if not success:
            error_msg = f"获取好友列表失败: {error.message}" if error else "获取失败"
            logger.error(error_msg)
            yield event.plain_result(f"❌ {error_msg}")
            return
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
        if not self.client:
            yield event.plain_result("❌ 客户端未初始化")
            return
        msg = " ".join(message) if message else "你好，我是机器人，请求添加好友。"
        if self.debug:
            logger.debug(f"[命令] 发送好友申请给 {user_id}, 附加消息: {msg}")
        success, error = await self.client.add_friend(user_id, msg)
        if success:
            logger.info(f"好友申请已发送给 {user_id}")
            yield event.plain_result(f"✅ 好友申请已发送给用户 {user_id}")
        else:
            error_msg = f"发送好友申请失败: {error.message}" if error else "发送失败"
            logger.error(error_msg)
            yield event.plain_result(f"❌ {error_msg}")

    @filter.command("pymchat_friend_requests")
    async def friend_requests(self, event: AstrMessageEvent):
        if not self.client:
            yield event.plain_result("❌ 客户端未初始化")
            return
        if self.debug:
            logger.debug("[命令] 获取好友申请列表")
        success, requests, error = await self.client.get_friend_requests()
        if not success:
            error_msg = f"获取好友申请失败: {error.message}" if error else "获取失败"
            logger.error(error_msg)
            yield event.plain_result(f"❌ {error_msg}")
            return
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
        if not self.client:
            yield event.plain_result("❌ 客户端未初始化")
            return
        if self.debug:
            logger.debug(f"[命令] 同意好友申请: {request_id}")
        success, error = await self.client.accept_friend(request_id)
        if success:
            logger.info(f"已同意好友申请: {request_id}")
            yield event.plain_result("✅ 已同意好友申请")
        else:
            error_msg = f"同意好友申请失败: {error.message}" if error else "操作失败"
            logger.error(error_msg)
            yield event.plain_result(f"❌ {error_msg}")

    @filter.command("pymchat_delete_friend")
    async def delete_friend_cmd(self, event: AstrMessageEvent, friend_id: str):
        if not self.client:
            yield event.plain_result("❌ 客户端未初始化")
            return
        if self.debug:
            logger.debug(f"[命令] 删除好友: {friend_id}")
        success, error = await self.client.delete_friend(friend_id)
        if success:
            logger.info(f"已删除好友: {friend_id}")
            yield event.plain_result("✅ 已删除好友")
        else:
            error_msg = f"删除好友失败: {error.message}" if error else "删除失败"
            logger.error(error_msg)
            yield event.plain_result(f"❌ {error_msg}")

    @filter.command("pymchat_group")
    async def group_chat(self, event: AstrMessageEvent, group_id: str, *content):
        if not self.client:
            yield event.plain_result("❌ 客户端未初始化")
            return
        if not self.enable_group_chat:
            yield event.plain_result("群聊功能未启用")
            return
        message = " ".join(content)
        if not message:
            yield event.plain_result("消息内容不能为空")
            return
        if self.debug:
            logger.debug(f"[命令] 发送群消息到 {group_id}: {message[:50]}...")
        success, error = await self.client.send_group_message(message, group_id)
        if success:
            logger.info(f"群消息已发送至 {group_id}: {message[:50]}...")
            yield event.plain_result(f"✅ 群消息已发送至 {group_id}")
        else:
            error_msg = f"发送失败: {error.message}" if error else "发送失败"
            logger.error(error_msg)
            yield event.plain_result(f"❌ {error_msg}")

    @filter.command("pymchat_debug")
    async def toggle_debug(self, event: AstrMessageEvent, *args):
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
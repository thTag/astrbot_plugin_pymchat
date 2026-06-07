# 修改后的 main.py
from astrbot.api.star import Context, Star, register
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api import logger
from .adapter.adapter import PymChatAdapter

@register(
    "astrbot_plugin_pymchat",
    "叹点",
    "PymChat 平台适配器插件",
    "1.0.0",
    "https://github.com/thTag/astrbot_plugin_pymchat"
)
class PymChatPlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context, config)
        self.adapter = None
        self._adapter_instance = None

    async def on_load(self):
        """插件加载时注册平台适配器"""
        try:
            platform_manager = self.context.get_platform_manager()
            platform_manager.register_adapter("pymchat", PymChatAdapter)
            logger.info("[PymChat] 平台适配器注册成功")
        except Exception as e:
            logger.error(f"[PymChat] 平台适配器注册失败: {e}")

    async def on_unload(self):
        """插件卸载时清理"""
        if self._adapter_instance:
            await self._adapter_instance.stop()
        logger.info("[PymChat] 插件已卸载")

    # ✅ 修正控制指令
    @filter.command("pc")
    async def control_pymchat(self, event: AstrMessageEvent):
        """控制 PymChat 适配器（指令已改为 pc）
        用法：
        /pc status   - 查看适配器状态
        /pc reload   - 重新登录获取API Key
        """
        # 获取插件配置并初始化适配器实例（如果尚未初始化）
        if not self._adapter_instance:
            config = self.get_star_config()
            self._adapter_instance = PymChatAdapter(config)
            await self._adapter_instance.start()

        args = event.get_args()
        if not args:
            yield event.plain_result("用法：/pc status 或 /pc reload")
            return
        cmd = args[0].lower()
        if cmd == "status":
            if self._adapter_instance and self._adapter_instance._running:
                yield event.plain_result("✅ PymChat 适配器运行中")
            else:
                yield event.plain_result("❌ PymChat 适配器未运行")
        elif cmd == "reload":
            if self._adapter_instance:
                self._adapter_instance.api_key = None
                await self._adapter_instance._ensure_valid_api_key()
                yield event.plain_result("✅ 已重新登录，API Key已刷新")
            else:
                yield event.plain_result("❌ 适配器未初始化")
        else:
            yield event.plain_result(f"未知命令: {cmd}")
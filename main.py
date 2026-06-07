from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.star.star_handler import star_handlers_handler
from .adapter.pymchat_adapter import PymChatAdapter

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
        if self.adapter:
            await self.adapter.stop()
        logger.info("[PymChat] 插件已卸载")

    @star_handlers_handler.command("pymchat")
    async def control_pymchat(self, event):
        """控制 PymChat 适配器
        用法：
        /pymchat status   - 查看适配器状态
        """
        args = event.get_args()
        if not args:
            yield event.reply("用法：/pymchat status")
            return
        cmd = args[0].lower()
        if cmd == "status":
            if self.adapter and self.adapter._running:
                yield event.reply("✅ PymChat 适配器运行中")
            else:
                yield event.reply("❌ PymChat 适配器未运行")
        else:
            yield event.reply(f"未知命令: {cmd}")
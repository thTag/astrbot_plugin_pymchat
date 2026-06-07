from astrbot.api.star import Star, Context, register
from astrbot.api import logger
from .adapter import PymChatAdapter

@register(
    "astrbot_plugin_pymchat",
    "叹号大帝",
    "PymChat 平台适配器",
    "1.0.0",
    "https://github.com/thTag/astrbot_plugin_pymchat"
)
class PymChatPlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context, config)

    async def on_load(self):
        try:
            platform_manager = self.context.get_platform_manager()
            platform_manager.register_adapter("pymchat", PymChatAdapter)
            logger.info("[PymChat] 平台适配器注册成功")
        except Exception as e:
            logger.error(f"[PymChat] 平台适配器注册失败: {e}")

    async def on_unload(self):
        logger.info("[PymChat] 插件已卸载")
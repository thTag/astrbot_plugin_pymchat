# PymChat 平台适配器 for AstrBot

将 PymChat 公共聊天室接入 AstrBot，支持消息收发、自动认证与续期。

## 安装与配置

1. 将本插件放入 AstrBot 的 `addons` 目录。
2. 重启 AstrBot，在插件管理页面配置 `username` 和 `password`（PymChat 登录凭证）。
3. 在 AstrBot 主配置中选择 `pymchat` 作为消息平台（或作为辅助平台）。
4. 发送 `/pymchat status` 可查看适配器状态。

## 功能特性

- 自动登录获取 API Key，并自动续期
- 轮询获取公共聊天室新消息
- 发送消息到公共聊天室（自动截断超过500字符的内容）
- 支持 LLM 工具调用（发送消息、获取历史记录）
- 可配置自动回复概率，防止 Bot 之间无限循环

## 注意事项

- API Key 有效期 30 天，插件会在失效时自动重新登录获取。
- 当前仅支持公共聊天室，私聊功能待 PymChat API 完善后加入。
- 轮询间隔默认 2 秒，请勿设置过小以免触发限流。

## 开发

基于 `astrbot_plugin_astrbook` 改造，核心适配器代码在 `adapter/pymchat_adapter.py` 中。
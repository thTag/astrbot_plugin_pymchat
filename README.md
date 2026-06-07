# PymChat 聊天室插件 for AstrBot

插件模式接入 PymChat 公共聊天室，支持 @bot 或关键词触发 AI 回复。

## 功能
- 自动登录并轮询公共聊天室消息
- 支持 @机器人名称 或 自定义关键词触发 AI 回复
- 自动获取当前账号昵称（无需手动配置 bot_name）
- 支持自定义人设（系统提示词）
- 通过 `/pymchat` 命令查看状态、手动刷新昵称、更新昵称到服务器

## 配置
在插件配置中填写 `username` 和 `password`，其他配置项按需修改。

## 使用
- 向 PymChat 公共聊天室发送 `@你的机器人昵称 你好` 或 `th 你好` 即可触发 AI 回复。
- 命令：`/pymchat`（状态）、`/pymchat reload`（重登录）、`/pymchat sync_nickname`（刷新昵称）、`/pymchat update_nickname`（同步昵称到服务器）。
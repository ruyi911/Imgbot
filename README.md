# Imgbot

一实例、一机器人、一群组的 Telegram 照片行为登记机器人。

它不会下载或保存绑定群组的照片，只记录用户在已绑定群组发送单图或相册的行为。机器人会引用原消息发送可配置 HTML 文案和 URL 按钮；超级管理员通过机器人私聊完成群组绑定、配置和按印度时间导出。

## 已实现功能

- 一个 `BOT_INSTANCE_ID` 同时最多绑定一个群组。
- 任意用户可通过 `/getid` 查询自己的 TG ID 和当前命令消息 ID，不经过管理员校验。
- 绑定时验证机器人和操作者都是目标群管理员，并在最终确认时再次验证。
- 仅接受绑定群的照片，其他群消息不会写入业务表。
- 单图逐次保留；同一 `media_group_id` 相册合并为一次记录并只回复一次。
- 不保存群内照片或其 Telegram 文件标识；首页图片仅保存 Telegram `file_id`，用于再次展示该首页图片。
- 数据库幂等，重复 Update 不会重复记录。
- 后台回复队列、单群保守限速、Telegram `429` 延迟重试。
- 所有私聊用户发送 `/start` 都会收到一条可配置的首页消息：图片、HTML 文案和 URL 按钮位于同一消息框；首页文案最多 1024 个字符。管理员随后还会收到管理面板。
- 管理面板一级入口可分别配置“首页媒体”“首页文案”“首页按钮”。首页图片由管理员直接发送给机器人，新的图片立即覆盖旧图片；发送 `CLEAR` 可删除图片。
- 私聊修改群内登记回复文案与 URL 按钮。
- 超级管理员可新增、查看和删除普通管理员；普通管理员的 TG ID 和可选名称保存在数据库中。
- 普通管理员可执行群组绑定、文案、按钮、导出和解除绑定，但看不到运行统计、
  重新验证权限及管理员管理入口。
- 按今天、昨天、最近 7 天或自定义印度时间导出 CSV/XLSX。
- 导出成功或失败后自动清理会话状态并返回 `/start` 首页。
- CSV/XLSX 防止昵称或用户名触发 Excel 公式。
- 解除绑定保留全部历史记录及审计日志。

## BotFather 和群权限

1. 用 `@BotFather` 为每个群创建一个独立机器人并保存 Token。
2. 将机器人加入目标群并设为管理员。
3. 至少允许机器人读取群消息和发送消息。若需要机器人删除非照片消息，当前版本尚未实现该功能，不要授予不必要的删除权限。
4. 将超级管理员的数字 TG ID 放入 `SUPER_ADMIN_IDS`。支持多个 ID，使用英文逗号分隔，
   例如 `SUPER_ADMIN_IDS=123456789,987654321`，逗号两侧允许空格。
5. 启动后私聊机器人发送 `/start`，点击“绑定群组”，输入类似 `-1001234567890` 的群 ID。

超级管理员由 `SUPER_ADMIN_IDS` 配置，不可在 Telegram 界面中删除。超级管理员可在
“管理员管理”中输入第一行数字 TG ID、第二行可选名称新增普通管理员；新增后，对方私聊机器人发送 `/start`
即可进入管理首页。

“重新验证权限”用于主动检查机器人和当前超级管理员是否仍是绑定群的管理员。它适合在
群主调整管理员、机器人被重新加入、发送回复异常或怀疑权限被撤销时使用，不会修改数据。

本机器人只记录照片消息，但“禁止成员发送其他类型消息”仍应由 Telegram 群权限完成。
如果群权限禁止普通成员发送文字，普通成员无法在群里发出 `/getid`，可以改为私聊机器人发送。

## 本地开发

需要 Python 3.12+：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
cp .env.example .env
.venv/bin/python -m imgbot.main
```

测试和静态检查：

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
```

## Docker 部署一个实例

复制并填写环境文件，特别是 Token、实例 ID、超级管理员 ID 和数据库密码：

```bash
cp .env.example .env.bot01
docker compose -p imgbot01 --env-file .env.bot01 up -d --build
```

每个 Compose project 默认拥有独立 PostgreSQL 数据卷。部署三个机器人时使用三个文件和三个 project 名称：

```bash
docker compose -p imgbot01 --env-file .env.bot01 up -d --build
docker compose -p imgbot02 --env-file .env.bot02 up -d --build
docker compose -p imgbot03 --env-file .env.bot03 up -d --build
```

三个环境文件中的 `BOT_TOKEN`、`BOT_INSTANCE_ID` 和 `POSTGRES_PASSWORD` 应分别配置。部署时不要把真实 `.env` 文件提交到版本库。

## 私聊按钮配置格式

首页按钮与群内登记回复按钮分别配置，但格式相同。

每行：

```text
行|列|按钮文字|URL
```

示例：

```text
1|1|参加其他活动|https://example.com/events
2|1|VIP群|https://t.me/example_vip
2|2|官方频道|https://t.me/example
```

每行最多两个按钮。发送 `CLEAR` 清空全部按钮。

## 时间规则

- 业务时区固定配置为 `Asia/Kolkata`（UTC+05:30）。
- 用户筛选和导出显示都使用印度时间。
- 数据库字段使用带时区时间，避免服务器部署时区影响业务结果。
- 自定义范围的结束分钟包含在结果中，例如 `23:59` 会查询到 `23:59:59.999...`。

## 当前边界

- 匿名管理员以群身份发送照片时，Telegram 不提供真实个人 TG ID，记录会保留群身份但个人 TG ID 为空。
- 机器人加入前的历史消息无法通过普通 Bot API 自动补录。
- 当前使用 long polling；单机部署足够。需要多副本时应改为 webhook 并增加分布式任务锁。
- 首版启动时自动创建表。后续修改生产库结构前应补充 Alembic 迁移，不应依赖 `create_all` 修改已有表。

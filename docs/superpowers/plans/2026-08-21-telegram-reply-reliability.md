# Telegram Reply Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保留“单 ReplyWorker + 三 Bot round-robin”架构的前提下，确保 Telegram 短暂断网、timeout、connection reset 或 Worker 短暂中断时，回复任务不会永久停留或静默丢失，并在有限重试后形成可见的失败记录。

**Architecture:** 数据库是回复任务状态的唯一事实来源。Worker 原子领取 `PENDING/RETRYING` 任务并写入带 lease 的 `SENDING`，Telegram 网络错误按有限指数退避重新入队，429 独立遵循 `retry_after`，确定性不可重试错误进入 `FAILED`。本阶段仍只有一个发送 task，但领取锁、attempt guard 与 lease 不依赖单 Worker 假设，后续可扩展 per-bot worker。

**Tech Stack:** Python 3.12、asyncio、aiogram 3、aiohttp、SQLAlchemy async、PostgreSQL 17、pytest、pytest-asyncio、ruff、Docker Compose。

**Spec:** 当前任务要求；历史证据 `/Users/momo/.codex/attachments/9da66252-db9a-497e-b6d9-e2fafa147288/pasted-text.txt`

## Global Constraints

- 本阶段不实现 3 个并行发送 Worker。
- 不改变图片登记、模板渲染、Bot round-robin、群组限速等业务逻辑。
- 网络失败总共最多尝试 3 次（首次发送 + 2 次重试）；退避时间固定为 1、2 秒。
- 重试只写入 `next_retry_at` 并释放 Worker，不在当前任务中等待；可领取的新 `PENDING` 始终优先于已到期的旧 `RETRYING`。
- `TelegramRetryAfter` 与 `TelegramNetworkError` 必须分开处理。
- Telegram 已接收但客户端未收到响应时无法保证 exactly-once；必须记录此不确定性，不得宣称绝不重复。
- 所有数据库完成/失败写入必须带当前 attempt 条件，拒绝过期执行者覆盖新状态。
- 现有用户改动必须保留；不做无关重构。

---

### Task 1: 持久化发送 lease 与错误分类

**Files:**
- Modify: `src/imgbot/models.py`
- Modify: `src/imgbot/db.py`
- Test: `tests/test_db_migrations.py`

**Interfaces:**
- Produces: `Submission.sending_started_at: datetime | None`、`Submission.reply_error_type: str | None`、队列索引 `ix_submissions_reply_queue`。

- [ ] **Step 1: 写失败测试**：从缺少新列的旧 `submissions` 表启动 `Database.create_schema()`，断言新增两列并可重复执行。
- [ ] **Step 2: 运行红灯**：`.venv/bin/pytest tests/test_db_migrations.py -q`；预期因列不存在失败。
- [ ] **Step 3: 最小实现**：增加 ORM 字段；按 SQLite/PostgreSQL 方言执行兼容 `ALTER TABLE`，仅在依赖列存在时创建队列索引。
- [ ] **Step 4: 运行绿灯**：`.venv/bin/pytest tests/test_db_migrations.py -q`。
- [ ] **Step 5: 提交**：`git add src/imgbot/models.py src/imgbot/db.py tests/test_db_migrations.py && git commit -m "fix: persist reply delivery lease metadata"`。

### Task 2: 原子领取、lease 回收与过期写入保护

**Files:**
- Modify: `src/imgbot/service.py`
- Test: `tests/test_service_database.py`

**Interfaces:**
- Produces: `next_pending_reply(now, *, sending_lease_seconds=90) -> Submission | None`。
- Produces: `mark_reply_sent(..., expected_attempt: int) -> bool`。
- Produces: `mark_reply_failed(..., error_type: str, expected_attempt: int, retryable: bool = True) -> ReplyStatus | None`。

- [ ] **Step 1: 写失败测试**：创建过期 `SENDING`，断言下一轮回收并重新领取；旧 attempt 的 `mark_reply_sent` 返回 `False`，当前 attempt 才可写 `SENT`。
- [ ] **Step 2: 运行红灯**：`.venv/bin/pytest tests/test_service_database.py::test_expired_sending_lease_is_reclaimed_and_stale_writer_is_rejected -q`。
- [ ] **Step 3: 最小实现**：事务内回收过期 lease，使用 `FOR UPDATE OF submissions SKIP LOCKED` 领取，递增 attempt 并记录 `sending_started_at`；状态写入按 `id + SENDING + expected_attempt` 限定。
- [ ] **Step 4: 运行绿灯**：重复运行目标测试。
- [ ] **Step 5: 写失败测试**：连续制造 3 次网络失败，断言前 2 次为 `RETRYING` 且延迟为 1/2 秒，第 3 次为 `FAILED`，并保留 `reply_error`、`reply_error_type`。
- [ ] **Step 6: 运行红灯**：运行该单测，确认旧实现允许超过 3 次或产生 4/8 秒退避。
- [ ] **Step 7: 最小实现并运行绿灯**：实现有限退避及错误字段持久化。
- [ ] **Step 8: 写失败测试**：先制造一个已到期的旧 `RETRYING`，再新增 `PENDING`，断言下一次领取新任务；同一状态内仍按 `sent_at, id` 排序。
- [ ] **Step 9: 最小实现并运行绿灯**：领取排序使用 `PENDING` 优先级、`sent_at`、`id`，重试延迟只持久化到 `next_retry_at`。
- [ ] **Step 10: 提交**：提交 service 与数据库行为测试。

### Task 3: Worker 网络错误分类与有界阻塞

**Files:**
- Modify: `src/imgbot/config.py`
- Modify: `src/imgbot/main.py`
- Modify: `src/imgbot/worker.py`
- Modify: `.env.example`
- Modify: `compose.yaml`
- Test: `tests/test_config.py`
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes: Task 2 的 guarded 状态写入接口。
- Produces: `REPLY_REQUEST_TIMEOUT_SECONDS=3`、`REPLY_SENDING_LEASE_SECONDS=90`。

- [ ] **Step 1: 写失败测试**：`TelegramNetworkError` 调用传入 `request_timeout=3`，写回 `retryable=True` 和 1 秒级首轮退避。
- [ ] **Step 2: 运行红灯**：`.venv/bin/pytest tests/test_worker.py::test_network_error_uses_bounded_backoff_without_sleeping_worker -q`。
- [ ] **Step 3: 最小实现**：为三个 Bot 分别创建 timeout=3 秒的独立 `AiohttpSession`，Worker 发送再次显式传入同一 timeout；分类 `RetryAfter`、network/server/raw network、确定性 API 错误，网络错误标记 `*_UNCERTAIN` 并有限重试。
- [ ] **Step 4: 写并运行边界测试**：确认 `TelegramEntityTooLarge` 虽继承网络异常也立即 `FAILED`；确认 `TelegramBadRequest` 不重试。
- [ ] **Step 5: 写失败测试**：让 `next_pending_reply()` 首次抛异常，断言 Worker 外层循环仍继续处理下一轮；`CancelledError` 必须继续传播。
- [ ] **Step 6: 最小实现并运行绿灯**：增加外层 supervisor、heartbeat 与 active submission 日志。
- [ ] **Step 7: 配置测试**：断言 lease 至少比 request timeout 多 5 秒，非法组合启动失败。
- [ ] **Step 8: 提交**：提交 Worker、配置及测试。

### Task 4: FAILED 可见且保持终态

**Files:**
- Modify: `src/imgbot/service.py`
- Modify: `src/imgbot/handlers/admin.py`
- Modify: `src/imgbot/keyboards.py`
- Test: `tests/test_service_database.py`
- Test: `tests/test_admin_handlers.py`

**Interfaces:**
- Produces: statistics 中 `pending`、`sending`、`failed`、`oldest_queued_at`。

- [ ] **Step 1: 写失败测试**：统计页显示失败数量，但不出现人工重试入口。
- [ ] **Step 2: 运行红灯**：运行目标测试，确认旧页面仍带重试按钮。
- [ ] **Step 3: 最小实现**：保留失败数量和错误字段，移除批量重新入队方法、按钮与回调。
- [ ] **Step 4: 运行绿灯**：运行 service/admin 目标测试。
- [ ] **Step 5: 提交**：提交管理界面与测试。

### Task 5: 文档与最终验证

**Files:**
- Modify: `README.md`

**Interfaces:**
- Documents: timeout、lease、错误分类、重试次数、FAILED 审计终态、网络响应不确定导致的潜在重复。

- [ ] **Step 1: 更新运行文档**：说明新增环境变量和可靠性边界，明确本阶段仍是一个 Worker。
- [ ] **Step 2: 运行完整测试**：`.venv/bin/pytest -q`，必须零失败。
- [ ] **Step 3: 运行静态检查**：`.venv/bin/ruff check .`、`.venv/bin/python -m compileall -q src tests`、`git diff --check`。
- [ ] **Step 4: 验证 Compose**：`docker compose --env-file .env.bot01 config --quiet`。
- [ ] **Step 5: 验证 PostgreSQL SQL 形态**：编译领取语句并确认包含 `FOR UPDATE OF submissions SKIP LOCKED`。
- [ ] **Step 6: 报告边界**：区分本地测试通过与尚未部署；不得把测试替代真实 Telegram 故障注入和生产迁移验收。

## Self-Review

- Spec coverage: 覆盖网络有限重试、429 独立处理、SENDING 恢复、单 Worker timeout、FAILED 可见终态、状态竞争保护及未来 per-bot worker 兼容；明确排除本阶段并行发送和人工补发。
- Placeholder scan: 无 TBD、TODO 或未定义接口。
- Type consistency: Worker 调用的 `expected_attempt`、`error_type`、`sending_lease_seconds` 与 service 接口一致。

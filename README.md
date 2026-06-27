# WhatsApp Repair AI Backend

本项目是维修 WhatsApp 群组 AI 工具的本地后端。影刀 RPA 负责操作 WhatsApp Web，本后端负责入库、附件归档、DeepSeek 分析、本地 Excel 导出和提醒任务管理。

## Architecture

```text
影刀 RPA
  -> WhatsApp Web 抓消息/下载附件/发提醒
  -> 本地 FastAPI 后端
  -> SQLite + 本地归档 + DeepSeek + 本地 Excel
```

影刀只做网页自动化；复杂业务逻辑都在后端。

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

编辑 `.env`，填入新的 DeepSeek key、本地数据目录和 `YINGDAO_ENTRY_COMMAND`。业务调度配置统一放在 `config/customer_settings.json`。不要把真实 key 写入代码、README 或提交记录。

客户电脑本地部署建议设置：

```env
DATA_ROOT=C:\Users\test\data
WHATSAPP_GROUP_NAME=维修工作群
AUTO_ANALYZE_ON_INGEST=true
AUTO_EXPORT_ON_INGEST=true
AUTO_PIPELINE_BACKGROUND=true
AUTO_SYNC_FEISHU_ON_INGEST=false
```

DeepSeek 仍然由 `DEEPSEEK_API_KEY` 控制；配置了 key 就调用真实 AI，没有 key 时使用规则兜底分析。

初始化数据库：

```bash
python scripts/init_db.py
```

启动服务：

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

正式运行前至少检查这两个本地文件：

```text
.env
config/customer_settings.json
```

## Yingdao Integration

影刀流程调用这些接口：

- `POST /api/whatsapp/messages`：提交抓到的 WhatsApp 消息。
- `GET /api/whatsapp/download-jobs`：获取需要下载附件的消息。
- `POST /api/whatsapp/attachments`：提交附件下载结果。
- `GET /api/automation/next`：领取一个到点的自动化任务，无任务时返回 `job: null`。
- `POST /api/automation/report`：影刀执行后回报 `success / failed / skipped`。
- `GET /api/reminders/pending`：获取待发送提醒。
- `POST /api/reminders/result`：提交提醒发送结果。

详细字段见：

- `docs/yingdao_flows.md`：影刀和后端接口总览。
- `docs/yingdao_today_scan.md`：当天全量增量扫描、附件两步下载和验收步骤。
- `docs/first_real_yingdao_test.md`：第一轮真实群小范围测试流程。

正式运行建议改成“每 1 分钟拉起一次影刀入口流”。入口流只做一件事：

1. 调 `GET /api/automation/next` 领取任务。
2. 无任务立即退出。
3. `scan_cycle` 时打开指定群，执行消息采集和附件下载。
4. `reminder_cycle` 时先调 `/api/followups/run`，再按站点过滤拉 `/api/reminders/pending` 并发送。
5. 调 `POST /api/automation/report` 回写结果。

后端负责按 `config/customer_settings.json` 计算什么时候该扫哪个群、什么时候该发哪个群对应站点的提醒。影刀不再自己判断时间。

不用影刀时，可以先用示例 payload 验证 `/api/whatsapp/messages`：

```bash
.venv/bin/python scripts/send_yingdao_payload.py fixtures/yingdao_today_messages_example.json
```

## Local Storage

正式交付默认不需要飞书。维修记录和运行状态保存在 SQLite，附件按日期和地点归档到本地目录，并自动导出每日 Excel。

推荐目标电脑使用独立数据目录：

```env
DATA_ROOT=C:\Users\test\data
```

只配置 `DATA_ROOT` 时，后端会自动使用这些子目录：

```text
database\   SQLite 数据库
downloads\  影刀临时下载目录
logs\       后端和影刀日志
backups\    数据库备份
YYYY\MM\DD\ 按日期、地点归档附件和 Excel
```

更详细的客户电脑目录和打包部署建议见 `docs/local_customer_deployment.md`。

飞书集成代码仍保留为可选能力；默认保持 `AUTO_SYNC_FEISHU_ON_INGEST=false`，不需要配置飞书参数。

## DeepSeek

DeepSeek 使用 OpenAI-compatible chat completions 接口。默认模型是 `deepseek-v4-flash`，可通过 `DEEPSEEK_MODEL` 修改。

如果没有配置 `DEEPSEEK_API_KEY`，系统仍可完成消息入库、附件归档和基础规则判断，但 AI 摘要和复杂匹配质量会下降。

## Local Files

默认目录：

```text
data/      SQLite 数据库
archive/   归档后的照片和 PDF
downloads/ 影刀下载临时目录
```

这些目录被 `.gitignore` 忽略。

## Mock Pipeline

当前可以用 mock WhatsApp 消息跑通本地链路：

```bash
cd /Users/mac/Desktop/ai_projects/whatsapp
.venv/bin/python scripts/run_mock_pipeline.py
curl http://127.0.0.1:8000/api/status
curl 'http://127.0.0.1:8000/api/runs/recent?limit=10'
```

Mock 输入文件在 `fixtures/mock_whatsapp_messages.json`。后续在另一台已配置影刀的电脑上运行时，影刀直接调用同一套本地 HTTP 接口，不需要接飞书。

影刀提交 WhatsApp 消息到 `POST /api/whatsapp/messages` 后，后端会自动从管理人员的高置信派工消息中生成任务。默认派工管理人员：

```text
Dicky Company
Rex Atl
Ono atl
```

`Henry atl` 的消息默认作为追问和缺资料跟踪，不生成新任务。管理人员名单可通过 `.env` 调整：

```env
DISPATCH_MANAGER_SENDERS=Dicky Company,Rex Atl,Ono atl
FOLLOWUP_MANAGER_SENDERS=Henry atl
```

人员职责和任务来源判断规则见 `docs/role_task_source_analysis.md`。原则是：只从高置信派工消息生成任务，Henry 的追问和普通同事的完成汇报优先作为任务追踪、验收和证据。

也可以在本地管理页面手动维护人员角色和处理原则：

```text
http://127.0.0.1:8000/admin/settings
```

当前支持的角色：

- `派工人员`：其明确派工消息可自动生成正式任务。
- `跟进/验收`：其追问和缺资料消息优先作为任务追踪事件。
- `维修执行`：主要提供工作结果、照片和维修报告 PDF。
- `问题上报`：普通成员发现问题时先生成待确认线索，不直接变成正式任务。
- `管理查看`：用于后续管理界面权限和筛选。

如果管理页面里配置了派工/跟进人员，系统会优先使用数据库中的启用人员和别名；未配置时继续使用 `.env` 默认值。

普通成员发现的问题会先进入待确认问题线索，不会直接变成正式任务。系统会继续扫描后续聊天记录；如果后续出现派工人员对同一地点/同一问题的明确安排，系统会自动把问题线索转成正式任务并关联到 `work_schedules`。

管理人员也可以在设置页的“待确认问题”中做备用处理：

```text
待确认问题 -> 系统自动转任务 / 备用手动转任务 / 忽略 / 关闭
```

对应接口：

```bash
curl 'http://127.0.0.1:8000/api/issues?status=pending&limit=20'
curl -X POST 'http://127.0.0.1:8000/api/issues/{issue_id}/convert' ...
curl -X POST 'http://127.0.0.1:8000/api/issues/{issue_id}/ignore' ...
curl -X POST 'http://127.0.0.1:8000/api/issues/{issue_id}/close' ...
```

Henry 的历史未回复、缺 PDF、缺照片、问跟进结果等消息会保存到 `task_events`，用于沉淀跟进规则和追踪证据。正式运行时，系统不依赖 Henry 继续发言，而是由自动跟进接口扫描每日任务和维修汇报后生成提醒。查看最近任务事件：

```bash
curl 'http://127.0.0.1:8000/api/task-events/recent?limit=20'
```

每日工作编程可先用结构化 mock 数据导入，模拟影刀 OCR 后的结果：

```bash
curl -X POST http://127.0.0.1:8000/api/schedules/import \
  -H 'Content-Type: application/json' \
  --data-binary @fixtures/mock_daily_work_schedules.json
```

发送单条模拟 WhatsApp 消息并自动执行入库、分析、本地记录保存和提醒生成：

```bash
.venv/bin/python scripts/send_mock_message.py "Sam" "商场L 工程部要求检查 panic alarm，已测试正常，但维修报告 PDF 后补。"
```

脚本默认只输出一行摘要。完整运行摘要会保存到 SQLite 的 `run_records` 表：

```bash
curl 'http://127.0.0.1:8000/api/runs/recent?limit=10'
```

检查每日工作编程中仍未见 WhatsApp 完成回复的任务：

```bash
curl -X POST 'http://127.0.0.1:8000/api/schedules/check-unreplied?work_date=2026-06-10'
```

推荐给影刀或定时任务使用的统一自动跟进接口：

```bash
curl -X POST 'http://127.0.0.1:8000/api/followups/run?work_date=2026-06-10&limit=100'
```

## Automation Scheduling

自动调度现在由后端按 `config/customer_settings.json` 动态计算，不再依赖进程内常驻 scheduler 线程。关键点：

- `scan`：按 `interval_minutes + start_offset_seconds` 生成当天时间槽。
- `reminder`：按 `days_of_week + times` 生成固定提醒时间槽。
- `related_site_ids`：决定该群 reminder job 只处理哪些地点。
- 配置文件改动后，无需重启后端；后端会在下一次请求时自动刷新。

Windows 推荐部署方式：

- 计划任务 A：开机或登录时运行 `scripts\start_backend.bat`
- 计划任务 B：每 1 分钟运行一次 `scripts\run_yingdao_poll.bat`

部署前先跑：

```bash
.venv/bin/python scripts/check_config.py --mode all
```

该接口会同时检查：

- 每日工作编程中有任务但 WhatsApp 未见完成回复的记录。
- 已有维修汇报中仍缺照片、维修报告 PDF、路线图或明确工作结果的记录。
- 已存在 `pending` 或 `sent` 提醒的维修记录不会重复创建提醒。

维修记录会同时保存：

- `completion_status`：业务状态，例如 `已完成`、`资料不足`、`需要跟进`、`未回复`。
- `completion_score`：0-100 完成度分数，用于排序和区分严重程度。
- `completion_level`：`高`、`较高`、`中`、`较低`、`低`。

状态和分数的分工：

- 工作完成但缺 PDF/照片：通常是 `资料不足`，分数按缺失程度扣减。
- 工作未完成、需要报价、等主管/客户确认：优先是 `需要跟进`。
- 当天计划任务没有 WhatsApp 完成回复：是 `未回复`，分数为 0。
- 有明确结果、完整照片记录和维修报告 PDF：是 `已完成`，高分且不生成提醒。

SQLite 只保存附件文件名、路径、hash 和类型，不保存图片/PDF 二进制内容。附件原文件保存在 `archive/`：

```sql
SELECT original_filename, archive_filename, archive_path, attachment_type
FROM attachments
ORDER BY id DESC
LIMIT 10;
```

等价 HTTP 接口：

```bash
curl -X POST http://127.0.0.1:8000/api/mock/whatsapp/message \
  -H 'Content-Type: application/json' \
  -d '{"sender":"Sam","text":"商场L 工程部要求检查 panic alarm，已测试正常，但维修报告 PDF 后补。"}'
```

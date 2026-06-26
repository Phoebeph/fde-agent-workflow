# 影刀流程对接说明

本后端不直接控制 WhatsApp Web。影刀负责浏览器操作，并通过 HTTP 调用本后端。

## Flow 1: whatsapp_collect_today_messages

影刀动作：

1. 打开 WhatsApp Web。
2. 进入指定维修群组。
3. 上滑加载消息，直到看到当天 00:00 附近或当天日期分隔线。
4. 从当天第一条开始抓取消息。
5. 每 100-300 条消息分批调用本地接口。

接口：

```http
POST http://127.0.0.1:8000/api/whatsapp/messages
Content-Type: application/json
```

Body:

```json
{
  "group_name": "维修工作群",
  "messages": [
    {
      "sender": "Kei",
      "sent_at": "2026-06-10 18:21",
      "text": "商场LY 例检完成",
      "external_message_id": "维修工作群|Kei|2026-06-10 18:21|商场LY 例检完成|0",
      "has_attachments": false,
      "attachment_hints": [],
      "raw_payload": {
        "source": "yingdao",
        "flow_name": "whatsapp_collect_today_messages",
        "scan_date": "2026-06-10"
      }
    }
  ]
}
```

返回结果会包含：

- `messages`：WhatsApp 消息入库结果。
- `dispatch_schedules`：从管理人员高置信派工消息中自动生成的任务。
- `dispatch_schedules.issue_records`：普通成员上报的问题线索，状态为待确认，不直接生成正式任务。
- `dispatch_schedules.auto_converted_issues`：后续派工消息自动确认并转成正式任务的问题线索。
- `dispatch_schedules.followup_events`：跟进、追问、缺资料等任务事件。

影刀不需要判断业务含义，只要稳定提交原始消息。后端负责去重、派工识别、问题线索、维修汇报分析和提醒生成。

`external_message_id` 优先使用 WhatsApp 内部消息 ID。拿不到内部 ID 时，建议影刀生成：

```text
群名|发送人|消息时间|正文前80字|附件数量
```

更详细的当天全量扫描、附件下载和验收步骤见 `docs/yingdao_today_scan.md`。

当前默认只把 `Dicky Company`、`Rex Atl`、`Ono atl` 的明确派工消息生成任务。`Henry atl` 的历史追问消息只作为后续任务追踪和规则样本，不会生成新任务。正式跟进由后端自动检查任务和汇报后生成提醒，不依赖 Henry 继续发言。

如果管理页面已经配置了人员角色，后端会优先使用管理页面中的启用人员和别名；未配置时才使用 `.env` 默认名单。

详细角色划分和任务来源规则见 `docs/role_task_source_analysis.md`。

普通成员发现的问题会先进入待确认线索。后续如果派工人员在群里明确安排同一地点/同一问题，后端会自动把该线索转成正式任务并关联到 `work_schedules`。

管理人员也可以在本地管理页面查看和备用处理：

```text
http://127.0.0.1:8000/admin/settings
```

处理方式：

```text
系统自动转任务：派工人员后续确认安排时自动完成
备用转任务：特殊情况下手动确认安排给某位同事，写入 work_schedules
忽略：确认暂不需要处理
关闭：问题已处理或无需继续跟进
```

Henry 的追问、缺资料和未回复消息会写入任务事件表。查看最近任务事件：

```http
GET http://127.0.0.1:8000/api/task-events/recent?limit=20
```

高置信派工消息需要同时具备：

- 管理人员发言
- 明确 `@` 指派同事
- 明确地点或项目
- 有 `call`、`过去看看`、`安排`、`明早`、`urgent` 等派工动作

也可以手动从最近消息重新扫描派工任务：

```http
POST http://127.0.0.1:8000/api/schedules/discover-from-messages?limit=100
```

## Flow 2: whatsapp_download_attachments

影刀先获取待下载任务：

```http
GET http://127.0.0.1:8000/api/whatsapp/download-jobs?limit=50
```

下载完成后回传：

```http
POST http://127.0.0.1:8000/api/whatsapp/attachments
Content-Type: application/json
```

Body:

```json
{
  "message_fingerprint": "sha256-from-download-job",
  "attachment_type": "pdf",
  "staff_name": "Kei",
  "site": "商场LY",
  "work_type": "maintenance",
  "work_date": "2026-06-10"
}
```

`original_filename` 和 `temp_path` 可选；后端会在下载目录中自动定位最新匹配文件，并为图片/PDF 生成或保留合适的原始文件名。

附件扫描和附件下载分两步：扫描阶段只提交 `has_attachments` 和 `attachment_hints`，下载阶段再按 `message_fingerprint` 找回 WhatsApp 消息并下载文件。

SQLite 只保存附件文件名、路径、hash 和类型，不保存图片/PDF 二进制内容。

## Flow 3: whatsapp_send_reminders

影刀发送提醒前，先让后端按日期生成本轮待提醒事项：

```http
POST http://127.0.0.1:8000/api/followups/run?work_date=2026-06-10&limit=100
```

该接口会检查两类问题：

- `work_schedules` 中当天有安排，但没有匹配到 WhatsApp 完成汇报。
- `repair_records` 中已有汇报，但状态仍是 `未回复`、`资料不足` 或 `需要跟进`。

后端会自动去重；同一条维修记录已有 `pending` 或 `sent` 提醒时，不会重复创建新提醒。

后端生成维修记录时会写入 `completion_status`、`completion_score`、`completion_level`。后续如果提醒很多，影刀或管理界面可以按 `completion_score` 从低到高优先处理，低分代表更需要马上跟进。

影刀获取待发送提醒：

```http
GET http://127.0.0.1:8000/api/reminders/pending?limit=20
```

发送后回传：

```http
POST http://127.0.0.1:8000/api/reminders/result
Content-Type: application/json
```

Body:

```json
{
  "reminder_id": 1,
  "status": "sent",
  "result_payload": {
    "group_name": "维修工作群",
    "sent_text": "@Kei 请补充：照片记录"
  }
}
```

## Flow 4: schedule_ocr_import

如果排班只提供 PDF/图片，建议用影刀 OCR 或人工校验后，把结构化结果提交给后端：

```http
POST http://127.0.0.1:8000/api/schedules/import
Content-Type: application/json
```

Body:

```json
{
  "rows": [
    {
      "work_date": "2026-06-10",
      "shift": "A.M.",
      "staff_name": "Kei",
      "site": "商场LY",
      "task_text": "例检",
      "source_file": "每天工作編程.pdf",
      "ocr_confidence": 0.92,
      "review_status": "confirmed"
    }
  ]
}
```

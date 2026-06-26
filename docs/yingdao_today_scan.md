# 影刀扫描 WhatsApp Web 当天群消息实施说明

本说明用于配置影刀第一版真实 WhatsApp Web 采集流程。后端不直接控制 WhatsApp Web；影刀只负责打开群、加载当天消息、抽取字段、下载附件和发送提醒。

## 总流程

```text
影刀定时扫描当天群消息
  -> POST /api/whatsapp/messages
  -> 后端去重、入库、识别派工/问题线索/跟进事件
  -> GET /api/whatsapp/download-jobs
  -> 影刀下载图片/PDF 到 downloads/
  -> POST /api/whatsapp/attachments
  -> 后端归档附件并只保存元数据
  -> POST /api/followups/run
  -> GET /api/reminders/pending
  -> 影刀发送提醒并回传发送结果
```

第一版建议每 5 分钟运行一次，每次扫描当天全部消息。重复提交没有关系，后端会按消息指纹去重。

## 流程一：whatsapp_collect_today_messages

影刀流程名建议：`whatsapp_collect_today_messages`。

### 操作步骤

1. 打开 `https://web.whatsapp.com`，复用已登录账号。
2. 搜索并进入目标维修群。
3. 上滑加载消息，直到看到当天 00:00 附近或当天日期分隔线。
4. 从当天第一条消息开始，按页面顺序读取消息气泡。
5. 每 100-300 条消息分批调用后端接口。

### 每条消息抽取字段

```json
{
  "sender": "Brian",
  "sent_at": "2026-06-13 10:25",
  "text": "商场52 控制室 CCTV mon 又闪，客户说需要处理。",
  "external_message_id": "维修工作群|Brian|2026-06-13 10:25|商场52 控制室 CCTV mon 又闪，客户说需要处理。|0",
  "has_attachments": false,
  "attachment_hints": [],
  "raw_payload": {
    "source": "yingdao",
    "flow_name": "whatsapp_collect_today_messages",
    "scan_date": "2026-06-13",
    "group_name": "维修工作群"
  }
}
```

字段要求：

- `sender`：WhatsApp 显示的发送人名称。
- `sent_at`：尽量转为 `YYYY-MM-DD HH:mm`。如果 WhatsApp 只显示 `10:25`，影刀用扫描日期补齐年月日。
- `text`：消息正文。图片/PDF 没有正文时可以为空字符串。
- `external_message_id`：优先使用 WhatsApp 内部消息 ID；拿不到时用 `群名|发送人|消息时间|正文前80字|附件数量`。
- `has_attachments`：消息包含图片、PDF、视频或文档时为 `true`。
- `attachment_hints`：只记录附件提示，不在扫描阶段下载。
- `raw_payload`：保存影刀流程名、扫描日期、页面定位信息等轻量调试信息，不保存截图或大段 HTML。

附件提示示例：

```json
[
  {"type": "image", "label": "图片"},
  {"type": "pdf", "label": "PDF"}
]
```

### 调用后端

```http
POST http://127.0.0.1:8000/api/whatsapp/messages
Content-Type: application/json
```

```json
{
  "group_name": "维修工作群",
  "messages": [
    {
      "sender": "Brian",
      "sent_at": "2026-06-13 10:25",
      "text": "商场52 控制室 CCTV mon 又闪，客户说需要处理。",
      "external_message_id": "维修工作群|Brian|2026-06-13 10:25|商场52 控制室 CCTV mon 又闪，客户说需要处理。|0",
      "has_attachments": false,
      "attachment_hints": [],
      "raw_payload": {
        "source": "yingdao",
        "flow_name": "whatsapp_collect_today_messages",
        "scan_date": "2026-06-13"
      }
    }
  ]
}
```

后端返回中的重点字段：

- `messages.inserted`：本次新增消息数。
- `messages.skipped`：重复消息数。
- `dispatch_schedules.schedules`：自动识别出的正式派工任务。
- `dispatch_schedules.issue_records`：普通成员上报的问题线索。
- `dispatch_schedules.auto_converted_issues`：后续派工消息自动确认并转成正式任务的问题。
- `dispatch_schedules.followup_events`：跟进、催资料、验收类事件。

注意：派工人员和跟进人员以管理页面配置为准；如果管理页面已有人员配置，系统会优先使用管理页面角色，不再使用 `.env` 默认名单。管理页面地址：

```text
http://127.0.0.1:8000/admin/settings
```

## 消息抽取策略

优先使用 WhatsApp Web 页面元素，不建议第一版直接 OCR 全屏。

建议抽取顺序：

1. 消息气泡容器。
2. 气泡所属方向和发送人文本。
3. 气泡内时间文本。
4. 消息正文文本。
5. 图片缩略图、PDF 文件块、文档图标、视频缩略图。

如果 WhatsApp 页面结构变化导致某些字段取不到：

- `sender` 取不到时，先跳过该条，不要把未知发送人写入正式数据。
- `sent_at` 取不到时，先跳过该条或写入影刀能明确判断的时间。
- `text` 取不到但有附件时，可以提交空文本加 `has_attachments=true`。
- OCR 只作为兜底，并在 `raw_payload.extract_method` 标记为 `ocr_fallback`。

## 推荐运行方式：早上回填 + 白天增量

客户希望影刀一天中持续扫描 WhatsApp 群消息时，建议拆成两个节奏：

1. 每天 08:00 后做一次初始化回填：滚动到 `今天` 分隔线附近，边滚动边采集当天已经出现的消息，并提交到后端。
2. 白天每 5 分钟做一次增量扫描：滚动到底部，读取最近可见消息，建议取最近 80 条。

增量扫描取 80 条比 30-50 条更稳，因为 WhatsApp 群在短时间内可能连续发照片、PDF、补充说明和短标签。后端会按消息指纹去重，所以重复提交最近 80 条不会重复生成维修记录或提醒。

参考代码见：

```text
scripts/yingdao_whatsapp_scan.py
```

扫描阶段只提交消息和附件提示：

```json
{
  "发送者": "num5",
  "消息内容": "The SOUI Tv wall 正常",
  "时间": "24/6/2026 上午10:51",
  "external_message_id": "yingdao_xxxxx",
  "has_attachments": false,
  "attachment_hints": []
}
```

附件消息必须带 `external_message_id`。后续下载附件时，影刀可以用 `external_message_id` 或 `message_fingerprint` 回传给后端。

## 流程二：whatsapp_download_attachments

影刀流程名建议：`whatsapp_download_attachments`。

### 获取待下载任务

```http
GET http://127.0.0.1:8000/api/whatsapp/download-jobs?limit=50
```

每个任务会包含 `message_fingerprint`、`external_message_id`、发送人、时间、正文、附件提示等信息。影刀按这些信息回到 WhatsApp Web 找到对应消息。

后端只会在消息已经完成 AI 分析后才返回附件下载任务。这样附件回传时，后端已经知道维修记录里的地点，可以把图片/PDF 归档到 `DATA_ROOT\年\月\日\地点\`。其中日期优先使用 WhatsApp 消息发送日期，而不是消息正文里的实际工作日期。

### 下载和回传

1. 在 WhatsApp Web 找到对应消息。
2. 点击图片/PDF/文档并下载到项目 `downloads/` 目录。
3. 每下载一个文件，调用一次附件回传接口。

```http
POST http://127.0.0.1:8000/api/whatsapp/attachments
Content-Type: application/json
```

```json
{
  "external_message_id": "yingdao_xxxxx",
  "attachment_type": "pdf",
  "staff_name": "Brian",
  "site": "商场52",
  "work_type": "maintenance",
  "work_date": "2026-06-13"
}
```

`original_filename` 和 `temp_path` 现在都可以省略。省略时，后端会：

- 优先用 WhatsApp 消息发送日期和发送人生成默认图片文件名。
- PDF 如果下载目录中的真实文件名可用，则保留原文件名；否则生成 `日期_发送人_pdf`。
- 在 `DOWNLOADS_ROOT` 下递归扫描最新下载文件，并按消息日期和地点归档到最终目录。

后端会把文件归档到：

```text
archive/YYYY/MM/DD/site/
```

SQLite 只保存文件名、路径、hash、类型和关联消息 ID，不保存图片/PDF 二进制内容。

## 流程三：自动跟进和提醒

建议影刀每天多次调用自动跟进接口，例如 12:00、16:00、19:00、22:00：

```http
POST http://127.0.0.1:8000/api/followups/run?work_date=2026-06-13&limit=100
```

获取待发送提醒：

```http
GET http://127.0.0.1:8000/api/reminders/pending?limit=20
```

发送后回传：

```http
POST http://127.0.0.1:8000/api/reminders/result
Content-Type: application/json
```

```json
{
  "reminder_id": 1,
  "status": "sent",
  "result_payload": {
    "group_name": "维修工作群",
    "sent_text": "@Brian 请补充：维修报告 PDF"
  }
}
```

## 第一轮验收命令

确认后端运行：

```bash
curl http://127.0.0.1:8000/health
```

不用影刀，先用示例 payload 测试：

```bash
.venv/bin/python scripts/send_yingdao_payload.py fixtures/yingdao_today_messages_example.json
```

脚本摘要中的 `issues=新增/识别总数`、`followups=新增/识别总数` 用于区分新插入记录和重复识别记录。

查看最近消息：

```bash
curl 'http://127.0.0.1:8000/api/whatsapp/messages/recent?limit=20'
```

查看系统状态：

```bash
curl 'http://127.0.0.1:8000/api/status'
```

查看附件下载任务：

```bash
curl 'http://127.0.0.1:8000/api/whatsapp/download-jobs?limit=20'
```

重复运行同一个 payload，`messages.skipped` 应增加，`messages.inserted` 不应重复增加同一批消息。

## 风险和处理

- WhatsApp Web DOM 可能变化：影刀流程要把选择器集中维护，并保留 OCR 兜底。
- 当天消息很多：按 100-300 条分批提交，避免一次 HTTP 请求太大。
- 页面加载漏消息：每 5 分钟重复扫描当天全部消息，依靠后端去重修正。
- 附件下载慢：扫描和下载拆成两个流程，避免消息采集中断。
- 发送人名称不统一：在管理页面维护人员别名和角色。

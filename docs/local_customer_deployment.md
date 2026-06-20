# 客户电脑本地部署目录建议

本项目可以不接飞书，直接在客户电脑本地保存维修记录、附件归档和提醒队列。影刀负责操作 WhatsApp Web：采集消息、下载附件、发送提醒；后端负责数据清洗、AI 分析、SQLite 入库、附件改名归档和生成提醒内容。

## 推荐目录

```text
C:\AI-Repair-system\
  app\                         后端代码
```

客户数据根目录建议独立放在：

```text
C:\Users\test\data\
  database\
    whatsapp_repair.db          SQLite 主数据库，保存消息、维修记录、提醒、附件索引
  2026\
    06\
      19\
        2026-06-19_维修与提醒总表.xlsx
        The_SOUI\
          2026-06-19_The_SOUI_维修与提醒表.xlsx
          2026-06-19_The_SOUI_num5_maintenance_image_xxxxx.jpg
          2026-06-19_The_SOUI_num5_maintenance_pdf_xxxxx.pdf
  downloads\
    yingdao\                    影刀临时下载目录，文件回传后由后端复制到正式日期/地点目录
  logs\
    backend.log                 后端运行日志
    yingdao.log                 影刀流程日志
  backups\
    whatsapp_repair_YYYYMMDD.db 数据库备份
```

`.env` 建议设置：

```text
DATA_ROOT=C:\Users\test\data
FEISHU_MOCK_MODE=true
```

如果只配置 `DATA_ROOT`，后端会自动使用：

```text
DATABASE_PATH=C:\Users\test\data\database\whatsapp_repair.db
ARCHIVE_ROOT=C:\Users\test\data
DOWNLOADS_ROOT=C:\Users\test\data\downloads\yingdao
EXPORTS_ROOT=C:\Users\test\data
LOGS_ROOT=C:\Users\test\data\logs
BACKUPS_ROOT=C:\Users\test\data\backups
```

后端启动时会自动创建这些目录，客户电脑不需要手工逐个建立目录。

即使不使用飞书，`FEISHU_MOCK_MODE=true` 仍可作为本地分析结果表使用，方便通过 `/api/mock/feishu/records` 查看 AI 输出。

## 本地数据分工

- `raw_messages`：WhatsApp 原始消息。
- `repair_records`：清洗后的维修记录；目标是一条实际工作事项一行。
- `attachments`：附件索引，只保存文件路径、hash、类型，不把图片/PDF 二进制写进数据库。
- `reminders`：待影刀发送的 WhatsApp 提醒内容。
- `DATA_ROOT\年\月\日\地点\`：真正保存 photo record、维修报告 PDF、其他附件和地点维修与提醒表。
- `DATA_ROOT\年\月\日\YYYY-MM-DD_维修与提醒总表.xlsx`：当天所有地点的综合检查表。

## 综合导出文件建议

建议每天导出一个综合 Excel：

```text
C:\Users\test\data\2026\06\19\2026-06-19_维修与提醒总表.xlsx
```

建议包含 3 个 sheet：

- `维修记录`：日期、同事、地点、工作类型、AI摘要、维修结果、完成状态、待办事项、WhatsApp消息时间。
- `附件检查`：维修记录 ID、是否需要 photo record、是否需要维修报告 PDF、已归档文件名、本地归档路径、缺失资料。
- `提醒记录`：提醒对象、提醒原因、提醒内容、状态、发送时间、是否已解决。

这样客户日后只查一个文件，就能同时看到工作记录、附件是否齐全、哪些提醒已经发过。

每个地点目录也会生成一份地点表：

```text
C:\Users\test\data\2026\06\19\The_SOUI\2026-06-19_The_SOUI_维修与提醒表.xlsx
```

## 影刀流程

### 1. 采集 WhatsApp 消息

影刀读取维修群当天消息，调用：

```http
POST /api/whatsapp/messages
```

如果消息有图片/PDF，必须传：

```json
{
  "has_attachments": true,
  "attachment_hints": [
    {"type": "image", "label": "现场照片"},
    {"type": "pdf", "label": "维修报告"}
  ]
}
```

### 2. AI 分析

调用：

```http
POST /api/analyze/run
```

后端会生成本地 `repair_records`，并把补充句合并到对应维修事项。例如 `Checklist已签` 不会单独成行，而是并入对应例检记录。

### 3. 下载附件

影刀获取待下载任务：

```http
GET /api/whatsapp/download-jobs?limit=50
```

下载到 `downloads/yingdao/` 后，逐个回传：

```http
POST /api/whatsapp/attachments
```

如果影刀没有传 `site/staff_name/work_type/work_date`，后端会尝试使用已分析出的维修记录字段自动命名归档文件。

附件正式归档目录为：

```text
DATA_ROOT\年\月\日\地点\
```

例如：

```text
C:\Users\test\data\2026\06\19\The_SOUI\2026-06-19_The_SOUI_num5_maintenance_image_xxxxx.jpg
```

### 4. 导出每日 Excel

当天分析和附件回传后，调用：

```http
POST /api/exports/daily?work_date=2026-06-19
```

后端会生成：

```text
C:\Users\test\data\2026\06\19\2026-06-19_维修与提醒总表.xlsx
C:\Users\test\data\2026\06\19\The_SOUI\2026-06-19_The_SOUI_维修与提醒表.xlsx
```

### 5. 发送提醒

后端生成提醒后，影刀读取：

```http
GET /api/reminders/pending?limit=20
```

影刀用客户 WhatsApp 账号把 `content` 发回群里，发送成功后调用：

```http
POST /api/reminders/result
```

## 备份建议

每天收工后备份：

```text
C:\Users\test\data\database\whatsapp_repair.db
C:\Users\test\data\2026\
```

`downloads\` 是临时目录，可以定期清理；`年\月\日\地点\` 下的正式附件和 Excel 不要清理。

# 客户电脑本地部署目录建议

本项目可以不接飞书，直接在客户电脑本地保存维修记录、附件归档和提醒队列。影刀负责操作 WhatsApp Web：采集消息、下载附件、发送提醒；后端负责数据清洗、AI 分析、SQLite 入库、附件改名归档和生成提醒内容。

## 推荐目录

```text
C:\AI-Repair-system\
  app\                         后端代码
  data\
    whatsapp_repair.db          SQLite 主数据库，保存消息、维修记录、提醒、附件索引
  archive\
    2026\
      06\
        The_SOUI\
          2026-06-19_The_SOUI_num5_maintenance_image_xxxxx.jpg
          2026-06-19_The_SOUI_num5_maintenance_pdf_xxxxx.pdf
  downloads\
    yingdao\                    影刀临时下载目录，文件回传后由后端复制到 archive
  exports\
    daily\                      后续导出的每日维修记录 CSV/XLSX
    reminders\                  后续导出的提醒记录
  logs\
    backend.log                 后端运行日志
    yingdao.log                 影刀流程日志
  backups\
    whatsapp_repair_YYYYMMDD.db 数据库备份
```

`.env` 建议设置：

```text
DATABASE_PATH=./data/whatsapp_repair.db
ARCHIVE_ROOT=./archive
FEISHU_MOCK_MODE=true
```

即使不使用飞书，`FEISHU_MOCK_MODE=true` 仍可作为本地分析结果表使用，方便通过 `/api/mock/feishu/records` 查看 AI 输出。

## 本地数据分工

- `raw_messages`：WhatsApp 原始消息。
- `repair_records`：清洗后的维修记录；目标是一条实际工作事项一行。
- `attachments`：附件索引，只保存文件路径、hash、类型，不把图片/PDF 二进制写进数据库。
- `reminders`：待影刀发送的 WhatsApp 提醒内容。
- `archive/`：真正保存 photo record、维修报告 PDF、其他附件。

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

### 4. 发送提醒

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
data\whatsapp_repair.db
archive\
```

`downloads\` 是临时目录，可以定期清理；`archive\` 不要清理。

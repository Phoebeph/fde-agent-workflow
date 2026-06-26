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
    backend.log                 后端运行日志，包含附件回传 422/400/404/500 错误
    yingdao.log                 影刀流程日志
  backups\
    whatsapp_repair_YYYYMMDD.db 数据库备份
```

`.env` 建议设置：

```text
DATA_ROOT=C:\Users\test\data
AUTO_ANALYZE_ON_INGEST=true
AUTO_EXPORT_ON_INGEST=true
AUTO_PIPELINE_BACKGROUND=true
AUTO_SYNC_FEISHU_ON_INGEST=false
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

后端启动后会自动写入：

```text
C:\Users\test\data\logs\backend.log
```

如果附件同步失败，优先查看 `backend.log`。常见记录包括附件接口 422 字段校验错误、400 本地文件不存在、404 消息引用找不到，以及未捕获异常堆栈。影刀流程自己的操作日志仍建议写入 `yingdao.log`。

正式本地部署不需要配置飞书，也不需要开启 `FEISHU_MOCK_MODE`。维修记录以 `repair_records`、每日 Excel 和本地附件归档为准。

自动流程开关说明：

- `AUTO_ANALYZE_ON_INGEST=true`：影刀成功提交 WhatsApp 消息后，后端自动分析新消息。
- `AUTO_EXPORT_ON_INGEST=true`：分析完成后，后端自动生成当天 Excel。
- `AUTO_PIPELINE_BACKGROUND=true`：自动分析在后台执行，避免影刀等待 DeepSeek 返回太久。
- `AUTO_SYNC_FEISHU_ON_INGEST=false`：本地部署不写飞书。

## 本地数据分工

- `raw_messages`：WhatsApp 原始消息。
- `repair_records`：清洗后的维修记录；目标是一条实际工作事项一行。
- `attachments`：附件索引，只保存文件路径、hash、类型，不把图片/PDF 二进制写进数据库。
- `reminders`：待影刀发送的 WhatsApp 提醒内容。
- `sites`：客户自定义地点词库，包含地点名称、别名/关键词、说明和启用状态。
- `DATA_ROOT\年\月\日\地点\`：真正保存 photo record、维修报告 PDF、其他附件和地点维修与提醒表。
- `DATA_ROOT\年\月\日\YYYY-MM-DD_维修与提醒总表.xlsx`：当天所有地点的综合检查表。

## 综合导出文件建议

建议每天导出一个综合 Excel：

```text
C:\Users\test\data\2026\06\19\2026-06-19_维修与提醒总表.xlsx
```

建议包含 3 个 sheet：

- `维修记录`：归档日期、实际工作日期、备注、同事、地点、工作类型、AI摘要、维修结果、完成状态、待办事项、WhatsApp消息时间。
- `附件检查`：维修记录 ID、归档日期、实际工作日期、是否需要 photo record、是否需要维修报告 PDF、已归档文件名、本地归档路径、缺失资料。
- `提醒记录`：归档日期、实际工作日期、提醒对象、提醒原因、提醒内容、状态、发送时间、是否已解决。

这样客户日后只查一个文件，就能同时看到工作记录、附件是否齐全、哪些提醒已经发过。

如果 6 月 20 日 WhatsApp 才汇报 6 月 17 日或 6 月 18 日的工作，文件仍放在：

```text
C:\Users\test\data\2026\06\20\
```

Excel 里会同时显示 `归档日期` 和 `实际工作日期`，并在 `备注` 中标记：

```text
2026-06-20 记录的其他日期工作：实际工作日期 2026-06-17
```

每个地点目录也会生成一份地点表：

```text
C:\Users\test\data\2026\06\19\The_SOUI\2026-06-19_The_SOUI_维修与提醒表.xlsx
```

## 影刀流程

## 地点词库配置

客户可以打开：

```text
http://127.0.0.1:8000/admin/settings
```

在 `地点词库` 里维护地点名称和别名/关键词，例如：

| 地点名称 | 别名/关键词 | 说明 |
|---|---|---|
| 淺水灣 | 浅水湾, Repulse Bay | 项目地点 |
| LPP | LPP Free Access, L212D, L322, L323B | LPP 内不同房间/门点 |
| 君大 | 君大6座, 6座G/F | 项目地点 |
| CCC | 6樓上6m, 6號閘機 | CCC 内部位置 |

分析时后端会优先使用地点词库补全 `site`，并在 DeepSeek 漏拆时按命中的地点补维修记录。

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

### 2. 自动 AI 分析和导出

影刀成功调用 `POST /api/whatsapp/messages` 后，后端会自动：

1. 识别派工/跟进类消息并保存排班。
2. 分析新收到的维修汇报消息，生成本地 `repair_records`。
3. 按 WhatsApp 消息发送日期自动生成当天综合 Excel 和各地点 Excel。

例如 `Checklist已签` 不会单独成行，而是并入对应例检记录。

如果需要排错或重跑，仍可手动调用：

```http
POST /api/analyze/run
POST /api/exports/daily?work_date=2026-06-19
```

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

附件回传成功后，后端会把对应 WhatsApp 消息标记为重新分析，并自动更新当天 Excel，使 `附件检查` sheet 里显示最新归档路径。

附件正式归档目录为：

```text
DATA_ROOT\年\月\日\地点\
```

例如：

```text
C:\Users\test\data\2026\06\19\The_SOUI\2026-06-19_The_SOUI_num5_maintenance_image_xxxxx.jpg
```

### 4. 查看每日 Excel

消息分析完成、附件回传完成后，后端会自动生成或更新：

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

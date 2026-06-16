# Mock Pipeline

本阶段 WhatsApp 和飞书使用 mock data，DeepSeek 保持真实可用：`.env` 里有 `DEEPSEEK_API_KEY` 时调用 DeepSeek，没有 key 时使用规则兜底。

## 配置

```env
FEISHU_MOCK_MODE=true
WHATSAPP_GROUP_NAME=Mock维修工作群
```

不要在代码或文档里写真实 key。用本机交互脚本填写：

```bash
.venv/bin/python scripts/configure_env.py
```

## 运行

```bash
cd /Users/mac/Desktop/ai_projects/whatsapp
.venv/bin/python scripts/init_db.py
.venv/bin/python scripts/import_rules.py /Users/mac/Desktop/工作規則.xlsx
.venv/bin/python scripts/run_mock_pipeline.py
```

## 查看结果

```bash
curl http://127.0.0.1:8000/api/status
curl 'http://127.0.0.1:8000/api/whatsapp/messages/recent?limit=10'
curl http://127.0.0.1:8000/api/mock/feishu/records
curl http://127.0.0.1:8000/api/reminders/pending
```

## 单条消息模拟

运行服务后，可以发送一条模拟 WhatsApp 消息。系统会自动执行：

1. 保存 raw WhatsApp 消息。
2. 调用 DeepSeek 或规则兜底分析。
3. 写入 mock 飞书记录。
4. 生成提醒任务。

```bash
.venv/bin/python scripts/send_mock_message.py "Sam" "商场L 工程部要求检查 panic alarm，已测试正常，但维修报告 PDF 后补。"
```

默认终端只显示一行摘要，例如：

```text
OK run_id=run_xxx sender=Sam status=需要跟进 record=mock_rec_xxx reminders=1
```

运行摘要保存在 SQLite 的 `run_records` 表：

```bash
curl 'http://127.0.0.1:8000/api/runs/recent?limit=10'
```

接口地址：

```http
POST /api/mock/whatsapp/message
```

Body:

```json
{
  "sender": "Sam",
  "text": "商场L 工程部要求检查 panic alarm，已测试正常，但维修报告 PDF 后补。"
}
```

## 替换真实 API

- WhatsApp：把 `fixtures/mock_whatsapp_messages.json` 换成影刀调用 `POST /api/whatsapp/messages`。
- 飞书：把 `FEISHU_MOCK_MODE=false`，配置飞书 App 和多维表格参数。
- DeepSeek：保持 `.env` 的 `DEEPSEEK_API_KEY`，无需改业务代码。

## 附件保存

图片和 PDF 不保存到 SQLite。数据库只保存：

- 原始文件名
- 归档文件名
- 归档路径
- 类型
- hash
- 文件大小

文件本体继续保存在 `archive/YYYY/MM/site/`。

## 每日任务完成度检查

测试阶段可以先把影刀 OCR 后的每日工作编程结构化结果导入后端：

```bash
curl -X POST http://127.0.0.1:8000/api/schedules/import \
  -H 'Content-Type: application/json' \
  --data-binary @fixtures/mock_daily_work_schedules.json
```

系统分析 WhatsApp 回复时会按同事、日期、地点和任务内容匹配每日任务，再根据附件和规则判断：

- 已完成
- 资料不足
- 需要跟进
- 未回复

检查当天计划任务中仍未匹配到 WhatsApp 完成回复的任务：

```bash
curl -X POST 'http://127.0.0.1:8000/api/schedules/check-unreplied?work_date=2026-06-10'
```

未回复任务会写入维修记录、mock 飞书总汇记录，并生成提醒。

# 第一轮真实群消息测试

目标：用影刀从真实 WhatsApp 维修群先抓少量可见消息验证字段，再扩展为当天全量增量扫描，确认消息能入库、重复提交能去重、附件能生成下载任务。

## 1. 启动后端

```bash
cd /Users/mac/Desktop/ai_projects/whatsapp
screen -S whatsapp_repair_backend -X quit 2>/dev/null || true
screen -dmS whatsapp_repair_backend bash -lc 'cd /Users/mac/Desktop/ai_projects/whatsapp && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/whatsapp_repair_backend.log 2>&1'
curl http://127.0.0.1:8000/health
```

## 2. 配置 `.env`

不要把密钥贴到聊天或文档里。在本机终端运行：

```bash
cd /Users/mac/Desktop/ai_projects/whatsapp
.venv/bin/python scripts/configure_env.py
.venv/bin/python scripts/check_config.py
```

填写新生成的 DeepSeek key、WhatsApp 群名和本地数据目录。飞书不是必需项，正式本地部署保持 `AUTO_SYNC_FEISHU_ON_INGEST=false`。

## 3. 影刀流程：第一轮可见消息验证

影刀流程名称建议：`whatsapp_collect_today_messages_first_test`

流程步骤：

1. 打开 Chrome 或内置浏览器。
2. 进入 `https://web.whatsapp.com`。
3. 扫码登录或复用已登录状态。
4. 打开维修 WhatsApp 群组。
5. 第一轮只抓当前屏幕可见的最近 5-20 条消息。
6. 对每条消息提取：
   - `sender`
   - `sent_at`
   - `text`
   - `has_attachments`
   - `attachment_hints`
   - `external_message_id`
   - `raw_payload`
7. 调用：

```http
POST http://127.0.0.1:8000/api/whatsapp/messages
Content-Type: application/json
```

Body 格式见 `docs/yingdao_flows.md` 和 `docs/yingdao_today_scan.md`。

## 4. 验证入库

影刀调用完成后，在终端运行：

```bash
curl http://127.0.0.1:8000/api/status
curl 'http://127.0.0.1:8000/api/whatsapp/messages/recent?limit=10'
curl 'http://127.0.0.1:8000/api/whatsapp/download-jobs?limit=10'
```

验收结果：

- `raw_messages` 数量增加。
- `messages/recent` 能看到真实群消息的发送人、时间和文字。
- 重复运行同一批消息时，新增数量不会重复增加。
- 有图片/PDF 的消息会出现在 `download-jobs`。

## 5. 影刀流程：当天全量扫描

第一轮字段正确后，把流程改成当天全量：

1. 打开目标维修群。
2. 上滑加载，直到看到当天 00:00 附近或当天日期分隔线。
3. 从当天第一条开始按顺序抽取消息。
4. 每 100-300 条分批调用 `POST /api/whatsapp/messages`。
5. 影刀每 5 分钟运行一次，重复扫描当天全部消息。

验收结果：

- 后端能看到真实发送人、时间、正文。
- 派工消息能生成 `work_schedules`。
- 普通成员问题能生成 `issue_records`。
- 后续派工确认能自动把问题线索转成正式任务。
- 附件消息能进入 `download-jobs`。

## 6. 影刀流程：下载附件

流程名称建议：`whatsapp_download_attachments_first_test`

流程步骤：

1. 调用 `GET /api/whatsapp/download-jobs?limit=10`。
2. 按返回的 `message_fingerprint` 找到对应 WhatsApp 消息。
3. 点击图片/PDF 下载。
4. 下载到项目的 `downloads/` 目录。
5. 调用 `POST /api/whatsapp/attachments` 回传下载结果。

验收结果：

- `archive/` 出现按规则重命名的附件。
- `GET /api/status` 中 `attachments` 数量增加。

## 7. 分析、本地保存和提醒

配置 DeepSeek 后运行：

```bash
curl -X POST http://127.0.0.1:8000/api/analyze/run \
  -H 'Content-Type: application/json' \
  -d '{"limit":20,"sync_feishu":false}'
```

验收结果：

- `repair_records` 数量增加。
- 当天本地 Excel 生成或更新。
- 缺资料记录会生成 `reminders`。

也可以运行自动跟进：

```bash
curl -X POST 'http://127.0.0.1:8000/api/followups/run?work_date=2026-06-13&limit=100'
curl 'http://127.0.0.1:8000/api/reminders/pending?limit=20'
```

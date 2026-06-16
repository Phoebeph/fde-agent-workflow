from __future__ import annotations

import json
import mimetypes
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


class FeishuError(RuntimeError):
    pass


class FeishuClient:
    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        app_token: str,
        table_id: str,
        base_url: str = "https://open.feishu.cn",
        upload_parent_type: str = "bitable_file",
        upload_parent_node: str = "",
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.app_token = app_token
        self.table_id = table_id
        self.base_url = base_url.rstrip("/")
        self.upload_parent_type = upload_parent_type
        self.upload_parent_node = upload_parent_node
        self._tenant_token: str | None = None
        self._tenant_token_expires_at = 0.0

    @property
    def enabled(self) -> bool:
        return all([self.app_id, self.app_secret, self.app_token, self.table_id])

    def create_record(self, fields: dict[str, Any]) -> str:
        data = self._request_json(
            "POST",
            f"/open-apis/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/records",
            {"fields": fields},
        )
        try:
            return data["data"]["record"]["record_id"]
        except KeyError as exc:
            raise FeishuError("Feishu create record response missing record_id") from exc

    def update_record(self, record_id: str, fields: dict[str, Any]) -> None:
        self._request_json(
            "PUT",
            f"/open-apis/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/records/{record_id}",
            {"fields": fields},
        )

    def upload_file(self, path: str | Path) -> dict[str, Any]:
        if not self.upload_parent_node:
            raise FeishuError("FEISHU_UPLOAD_PARENT_NODE is required for file upload")
        file_path = Path(path)
        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError(f"upload file not found: {file_path}")

        fields = {
            "file_name": file_path.name,
            "parent_type": self.upload_parent_type,
            "parent_node": self.upload_parent_node,
            "size": str(file_path.stat().st_size),
        }
        files = {"file": file_path}
        return self._request_multipart(
            "POST",
            "/open-apis/drive/v1/medias/upload_all",
            fields,
            files,
        )

    def fields_for_repair_record(
        self,
        message: dict[str, Any],
        analysis: dict[str, Any],
        attachments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        matched_schedule = analysis.get("matched_schedule") or {}
        plan_text = ""
        if isinstance(matched_schedule, dict):
            plan_text = str(matched_schedule.get("task_text") or "")
        return {
            "日期": analysis.get("work_date") or message.get("sent_at", "")[:10],
            "同事": analysis.get("staff_name") or message.get("sender"),
            "地点": analysis.get("site", ""),
            "计划任务": plan_text,
            "工作类型": analysis.get("work_type", ""),
            "WhatsApp原文": message.get("text", ""),
            "AI摘要": analysis.get("summary", ""),
            "维修结果": analysis.get("result", ""),
            "完成状态": analysis.get("completion_status", "待人工确认"),
            "完成分数": analysis.get("completion_score", 0),
            "完成等级": analysis.get("completion_level", ""),
            "缺失资料": "、".join(analysis.get("missing_items", [])),
            "待办事项": "、".join(analysis.get("next_actions", [])),
            "计划匹配状态": analysis.get("schedule_match_status", ""),
            "AI判断说明": _judgement_note(analysis),
            "附件文件名": "\n".join(item.get("archive_filename", "") for item in attachments),
            "本地归档路径": "\n".join(item.get("archive_path", "") for item in attachments),
            "WhatsApp消息时间": message.get("sent_at", ""),
        }

    def _tenant_access_token(self) -> str:
        now = time.time()
        if self._tenant_token and now < self._tenant_token_expires_at - 60:
            return self._tenant_token
        data = self._request_json(
            "POST",
            "/open-apis/auth/v3/tenant_access_token/internal",
            {"app_id": self.app_id, "app_secret": self.app_secret},
            auth=False,
        )
        token = data.get("tenant_access_token")
        if not token:
            raise FeishuError("Feishu tenant_access_token response missing token")
        self._tenant_token = token
        self._tenant_token_expires_at = now + int(data.get("expire", 7200))
        return token

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        auth: bool = True,
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if auth:
            headers["Authorization"] = f"Bearer {self._tenant_access_token()}"
        body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")[:500]
            raise FeishuError(f"Feishu HTTP {exc.code}: {text}") from exc
        except urllib.error.URLError as exc:
            raise FeishuError(f"Feishu request failed: {exc.reason}") from exc

        code = data.get("code", 0)
        if code != 0:
            raise FeishuError(f"Feishu API error {code}: {data.get('msg', '')}")
        return data

    def _request_multipart(
        self,
        method: str,
        path: str,
        fields: dict[str, str],
        files: dict[str, Path],
    ) -> dict[str, Any]:
        boundary = f"----whatsapprepair{uuid.uuid4().hex}"
        body = _encode_multipart(boundary, fields, files)
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={
                "Authorization": f"Bearer {self._tenant_access_token()}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")[:500]
            raise FeishuError(f"Feishu upload HTTP {exc.code}: {text}") from exc
        except urllib.error.URLError as exc:
            raise FeishuError(f"Feishu upload failed: {exc.reason}") from exc
        code = data.get("code", 0)
        if code != 0:
            raise FeishuError(f"Feishu upload API error {code}: {data.get('msg', '')}")
        return data


def _encode_multipart(boundary: str, fields: dict[str, str], files: dict[str, Path]) -> bytes:
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                str(value).encode(),
                b"\r\n",
            ]
        )
    for name, path in files.items():
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"; filename="{path.name}"\r\n'.encode(),
                f"Content-Type: {mime}\r\n\r\n".encode(),
                path.read_bytes(),
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks)


def _judgement_note(analysis: dict[str, Any]) -> str:
    status = analysis.get("completion_status", "")
    score = analysis.get("completion_score")
    level = analysis.get("completion_level", "")
    missing = "、".join(analysis.get("missing_items", []) or [])
    next_actions = "、".join(analysis.get("next_actions", []) or [])
    parts = [f"状态：{status}"] if status else []
    if score is not None:
        parts.append(f"完成度：{score}分/{level}")
    if missing:
        parts.append(f"缺失：{missing}")
    if next_actions:
        parts.append(f"待办：{next_actions}")
    return "；".join(parts)

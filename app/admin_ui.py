from __future__ import annotations


def admin_settings_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>维修群 AI 设置</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --line: #d9dee7;
      --text: #1f2937;
      --muted: #697586;
      --accent: #146c5f;
      --accent-weak: #e4f3ef;
      --danger: #b42318;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    header {
      height: 56px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 24px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      position: sticky;
      top: 0;
      z-index: 2;
    }
    h1 { font-size: 18px; margin: 0; font-weight: 650; }
    main {
      max-width: 1180px;
      margin: 0 auto;
      padding: 20px;
      display: grid;
      gap: 18px;
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }
    h2 { font-size: 16px; margin: 0 0 12px; }
    .grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }
    label { display: grid; gap: 6px; color: var(--muted); font-size: 12px; }
    input, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      font: inherit;
      color: var(--text);
      background: #fff;
    }
    textarea { min-height: 74px; resize: vertical; }
    .roles {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 4px;
    }
    .role {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 9px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
    }
    .role input { width: auto; }
    .actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    button {
      border: 1px solid var(--accent);
      background: var(--accent);
      color: #fff;
      border-radius: 6px;
      padding: 9px 12px;
      font: inherit;
      cursor: pointer;
    }
    button.secondary {
      background: #fff;
      color: var(--accent);
    }
    button.danger {
      border-color: var(--danger);
      color: var(--danger);
      background: #fff;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 12px;
    }
    th, td {
      border-bottom: 1px solid var(--line);
      text-align: left;
      padding: 10px 8px;
      vertical-align: top;
    }
    th {
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
      background: #fbfcfd;
    }
    .pill {
      display: inline-block;
      margin: 0 4px 4px 0;
      padding: 3px 7px;
      border-radius: 999px;
      background: var(--accent-weak);
      color: var(--accent);
      font-size: 12px;
    }
    .muted { color: var(--muted); }
    .status { min-height: 20px; color: var(--muted); }
    .status.error { color: var(--danger); }
    @media (max-width: 780px) {
      header { padding: 0 14px; }
      main { padding: 14px; }
      .grid { grid-template-columns: 1fr; }
      table { display: block; overflow-x: auto; white-space: nowrap; }
    }
  </style>
</head>
<body>
  <header>
    <h1>维修群 AI 设置</h1>
    <div class="actions">
      <button class="secondary" id="refreshBtn">刷新</button>
    </div>
  </header>
  <main>
    <section>
      <h2>人员角色</h2>
      <form id="staffForm">
        <input type="hidden" id="staffId">
        <div class="grid">
          <label>姓名
            <input id="name" required placeholder="例如 Dicky">
          </label>
          <label>WhatsApp 显示名
            <input id="whatsappName" placeholder="例如 Dicky Company">
          </label>
          <label>别名，用逗号分隔
            <input id="aliases" placeholder="例如 Dicky, Dicky Company">
          </label>
          <label>飞书名称
            <input id="feishuName" placeholder="可选">
          </label>
          <label>提醒时 @ 名称
            <input id="mentionName" placeholder="例如 @Dicky">
          </label>
          <label>备注
            <input id="notes" placeholder="例如 主要派工人员">
          </label>
        </div>
        <div class="roles" id="roles"></div>
        <label class="role" style="width:max-content;margin-top:10px;">
          <input id="isActive" type="checkbox" checked> 启用
        </label>
        <div class="actions" style="margin-top:12px;">
          <button type="submit">保存人员</button>
          <button type="button" class="secondary" id="clearFormBtn">清空</button>
        </div>
      </form>
      <div class="status" id="staffStatus"></div>
      <table>
        <thead>
          <tr>
            <th>姓名</th>
            <th>WhatsApp/别名</th>
            <th>角色</th>
            <th>状态</th>
            <th>备注</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody id="staffRows"></tbody>
      </table>
    </section>

    <section>
      <h2>处理原则</h2>
      <div class="grid">
        <label>正式任务来源原则
          <textarea id="taskSourcePolicy"></textarea>
        </label>
        <label>普通成员问题处理原则
          <textarea id="ordinaryIssuePolicy"></textarea>
        </label>
        <label>待确认问题提醒小时数
          <input id="reminderHours" type="number" min="1" max="168">
        </label>
        <label>待确认问题关闭天数
          <input id="closeDays" type="number" min="1" max="90">
        </label>
      </div>
      <div class="actions" style="margin-top:12px;">
        <button id="savePrinciplesBtn">保存原则</button>
      </div>
      <div class="status" id="principlesStatus"></div>
    </section>

    <section>
      <h2>待确认问题</h2>
      <p class="muted">系统会扫描后续派工消息，自动把匹配的问题转成正式任务。这里的手动转任务只是备用操作。</p>
      <div class="actions">
        <button class="secondary" id="loadIssuesBtn">刷新问题</button>
      </div>
      <div class="status" id="issuesStatus"></div>
      <table>
        <thead>
          <tr>
            <th>日期</th>
            <th>上报人</th>
            <th>地点</th>
            <th>问题内容</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody id="issueRows"></tbody>
      </table>
    </section>
  </main>
  <script>
    const roleOptions = [
      ["dispatch_manager", "派工人员"],
      ["followup_manager", "跟进/验收"],
      ["technician", "维修执行"],
      ["issue_reporter", "问题上报"],
      ["viewer", "管理查看"]
    ];
    let staff = [];
    let issues = [];

    function $(id) { return document.getElementById(id); }
    function setStatus(id, text, isError = false) {
      const el = $(id);
      el.textContent = text || "";
      el.classList.toggle("error", isError);
    }
    async function api(path, options = {}) {
      const response = await fetch(path, {
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        ...options
      });
      if (!response.ok) throw new Error(await response.text());
      return response.json();
    }
    function renderRoleInputs(selected = []) {
      $("roles").innerHTML = roleOptions.map(([value, label]) => `
        <label class="role">
          <input type="checkbox" name="role" value="${value}" ${selected.includes(value) ? "checked" : ""}>
          ${label}
        </label>
      `).join("");
    }
    function roleLabels(values) {
      return values.map(value => {
        const found = roleOptions.find(item => item[0] === value);
        return `<span class="pill">${found ? found[1] : value}</span>`;
      }).join("") || '<span class="muted">未设置</span>';
    }
    function renderStaffRows() {
      $("staffRows").innerHTML = staff.map(item => `
        <tr>
          <td>${item.name}</td>
          <td>
            <div>${item.whatsapp_name || ""}</div>
            <div class="muted">${(item.aliases || []).join(", ")}</div>
          </td>
          <td>${roleLabels(item.roles || [])}</td>
          <td>${item.is_active ? "启用" : "停用"}</td>
          <td>${item.notes || ""}</td>
          <td class="actions">
            <button class="secondary" type="button" onclick="editStaff(${item.id})">编辑</button>
            <button class="danger" type="button" onclick="toggleStaff(${item.id}, ${!item.is_active})">${item.is_active ? "停用" : "启用"}</button>
          </td>
        </tr>
      `).join("");
    }
    function renderIssueRows() {
      $("issueRows").innerHTML = issues.map(item => `
        <tr>
          <td>${item.work_date || ""}</td>
          <td>${item.reported_by || ""}</td>
          <td>${item.site || ""}</td>
          <td>
            <div>${item.issue_summary || item.issue_text || ""}</div>
            <div class="muted">${item.raw_text || ""}</div>
          </td>
          <td>${item.status || ""}</td>
          <td class="actions">
            <button class="secondary" type="button" onclick="convertIssue(${item.id})">备用转任务</button>
            <button class="secondary" type="button" onclick="ignoreIssue(${item.id})">忽略</button>
            <button class="danger" type="button" onclick="closeIssue(${item.id})">关闭</button>
          </td>
        </tr>
      `).join("") || '<tr><td colspan="6" class="muted">暂无待确认问题</td></tr>';
    }
    function formRoles() {
      return Array.from(document.querySelectorAll('input[name="role"]:checked')).map(el => el.value);
    }
    function clearForm() {
      $("staffForm").reset();
      $("staffId").value = "";
      $("isActive").checked = true;
      renderRoleInputs([]);
    }
    window.editStaff = function(id) {
      const item = staff.find(row => row.id === id);
      if (!item) return;
      $("staffId").value = item.id;
      $("name").value = item.name || "";
      $("whatsappName").value = item.whatsapp_name || "";
      $("aliases").value = (item.aliases || []).join(", ");
      $("feishuName").value = item.feishu_name || "";
      $("mentionName").value = item.mention_name || "";
      $("notes").value = item.notes || "";
      $("isActive").checked = Boolean(item.is_active);
      renderRoleInputs(item.roles || []);
      window.scrollTo({ top: 0, behavior: "smooth" });
    };
    window.toggleStaff = async function(id, isActive) {
      try {
        await api(`/api/admin/staff/${id}/active`, {
          method: "PATCH",
          body: JSON.stringify({ is_active: isActive })
        });
        await loadStaff();
      } catch (error) {
        setStatus("staffStatus", error.message, true);
      }
    };
    window.convertIssue = async function(id) {
      const item = issues.find(row => row.id === id);
      if (!item) return;
      const staffName = window.prompt("安排给哪位同事？", "");
      if (!staffName) return;
      const workDate = window.prompt("任务日期？", item.work_date || new Date().toISOString().slice(0, 10));
      if (!workDate) return;
      const site = window.prompt("地点？", item.site || "");
      const taskText = window.prompt("任务内容？", item.issue_summary || item.issue_text || "");
      if (!taskText) return;
      try {
        await api(`/api/issues/${id}/convert`, {
          method: "POST",
          body: JSON.stringify({
            staff_name: staffName,
            work_date: workDate,
            site,
            task_text: taskText,
            note: "由管理页面确认转任务"
          })
        });
        await loadIssues();
        setStatus("issuesStatus", "已转为正式任务");
      } catch (error) {
        setStatus("issuesStatus", error.message, true);
      }
    };
    window.ignoreIssue = async function(id) {
      const note = window.prompt("忽略原因？", "暂不需要处理");
      if (note === null) return;
      try {
        await api(`/api/issues/${id}/ignore`, {
          method: "POST",
          body: JSON.stringify({ note })
        });
        await loadIssues();
        setStatus("issuesStatus", "已忽略问题");
      } catch (error) {
        setStatus("issuesStatus", error.message, true);
      }
    };
    window.closeIssue = async function(id) {
      const note = window.prompt("关闭原因？", "已处理或无需继续跟进");
      if (note === null) return;
      try {
        await api(`/api/issues/${id}/close`, {
          method: "POST",
          body: JSON.stringify({ note })
        });
        await loadIssues();
        setStatus("issuesStatus", "已关闭问题");
      } catch (error) {
        setStatus("issuesStatus", error.message, true);
      }
    };
    async function loadStaff() {
      const data = await api("/api/admin/staff");
      staff = data.staff;
      renderStaffRows();
    }
    async function loadIssues() {
      const data = await api("/api/issues?status=pending&limit=50");
      issues = data.issues;
      renderIssueRows();
    }
    async function loadPrinciples() {
      const data = await api("/api/admin/principles");
      const map = Object.fromEntries(data.principles.map(item => [item.key, item.value]));
      $("taskSourcePolicy").value = map.task_source_policy || "";
      $("ordinaryIssuePolicy").value = map.ordinary_issue_policy || "";
      $("reminderHours").value = map.unconfirmed_issue_reminder_hours || 24;
      $("closeDays").value = map.unconfirmed_issue_close_days || 7;
    }
    async function refreshAll() {
      setStatus("staffStatus", "");
      setStatus("principlesStatus", "");
      setStatus("issuesStatus", "");
      await Promise.all([loadStaff(), loadPrinciples(), loadIssues()]);
    }
    $("staffForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        await api("/api/admin/staff", {
          method: "POST",
          body: JSON.stringify({
            name: $("name").value,
            id: $("staffId").value ? Number($("staffId").value) : null,
            whatsapp_name: $("whatsappName").value || null,
            aliases: $("aliases").value,
            roles: formRoles(),
            feishu_name: $("feishuName").value || null,
            mention_name: $("mentionName").value || null,
            is_active: $("isActive").checked,
            notes: $("notes").value
          })
        });
        clearForm();
        await loadStaff();
        setStatus("staffStatus", "已保存人员设置");
      } catch (error) {
        setStatus("staffStatus", error.message, true);
      }
    });
    $("savePrinciplesBtn").addEventListener("click", async () => {
      try {
        await api("/api/admin/principles", {
          method: "PUT",
          body: JSON.stringify({
            principles: {
              task_source_policy: $("taskSourcePolicy").value,
              ordinary_issue_policy: $("ordinaryIssuePolicy").value,
              unconfirmed_issue_reminder_hours: Number($("reminderHours").value || 24),
              unconfirmed_issue_close_days: Number($("closeDays").value || 7)
            }
          })
        });
        await loadPrinciples();
        setStatus("principlesStatus", "已保存处理原则");
      } catch (error) {
        setStatus("principlesStatus", error.message, true);
      }
    });
    $("clearFormBtn").addEventListener("click", clearForm);
    $("refreshBtn").addEventListener("click", refreshAll);
    $("loadIssuesBtn").addEventListener("click", loadIssues);
    renderRoleInputs([]);
    refreshAll().catch(error => setStatus("staffStatus", error.message, true));
  </script>
</body>
</html>"""

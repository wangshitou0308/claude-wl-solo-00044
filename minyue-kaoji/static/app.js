/* 民乐考级纸件与赴考脚注核对 —— 原生 JS */
"use strict";

let STATE = null;
let editingClauseId = null;
let viewingRunId = null;      // 结论页正在看的 run（null = 最新）

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const api = async (method, url, body) => {
  const res = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `请求失败 ${res.status}`);
  return data;
};

const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const SEV_LABEL = { fail: "不通过", warn: "提醒", ok: "通过", pending: "待确认" };
const SEV_ORDER = { fail: 0, pending: 1, warn: 2, ok: 3 };
const STATUS_LABEL = { ok: "已备齐", partial: "部分", missing: "未备齐" };

/* ------------------------------------------------------------- 初始化 */

async function refresh() {
  STATE = await api("GET", "/api/state");
  renderVersionBar();
  renderClauses();
  renderChildren();
  renderChecks();
  renderChecklist();
}

function renderVersionBar() {
  const a = STATE.active_version;
  if (!a) {
    $("#versionBar").innerHTML = `<b>尚无启用简章</b>　<button class="mini" onclick="createBlankVersion()">新建第一版</button>`;
    return;
  }
  $("#versionBar").innerHTML =
    `当前依据：<b>${esc(a.title)}</b>　发布：${esc(a.published || "未填")}　` +
    `发布方：${esc(a.issuer || "未填")}　版本 #${a.id}　` +
    `共 ${STATE.clauses.length} 条脚注`;
}

window.createBlankVersion = async function () {
  const title = prompt("简章版本名称", "新简章 v?");
  if (!title) return;
  await api("POST", "/api/versions", { title });
  await refresh();
};

/* ------------------------------------------------------------- 页签 */

$$(".tabs button").forEach(btn => btn.addEventListener("click", () => {
  $$(".tabs button").forEach(b => b.classList.remove("active"));
  $$(".tab").forEach(t => t.classList.remove("active"));
  btn.classList.add("active");
  $(`#tab-${btn.dataset.tab}`).classList.add("active");
  if (btn.dataset.tab === "checklist") renderChecklist();
}));

/* ------------------------------------------------------------- 简章条款 */

const CAT_SPECS = {
  instrument: [
    { key: "instruments", label: "开考乐种（逗号分隔）", type: "list" },
    { key: "uncertain", label: "范围有不明项", type: "bool" },
  ],
  level: [
    { key: "min", label: "最低级别", type: "int" },
    { key: "max", label: "最高级别", type: "int" },
    { key: "instruments", label: "适用乐种（空=全部，逗号分隔）", type: "list" },
    { key: "uncertain", label: "范围有不明项", type: "bool" },
  ],
  skip: [
    { key: "levels", label: "适用报考级别区间（起,止）", type: "pair" },
    { key: "instruments", label: "适用乐种（空=全部）", type: "list" },
    { key: "need_level", label: "须持证书最低级别（留空=所跳前一级）", type: "int" },
    { key: "need_original", label: "须出示证书原件", type: "bool" },
    { key: "extra_required", label: "须加试前一级曲目", type: "bool" },
    { key: "uncertain", label: "本条款有不明项，结论保留待确认", type: "bool" },
  ],
  photo: [
    { key: "size", label: "尺寸（如 二寸）", type: "text" },
    { key: "count", label: "张数", type: "int" },
    { key: "background", label: "底色（蓝/红/白）", type: "text" },
    { key: "color", label: "彩色/黑白", type: "text" },
    { key: "uncertain", label: "规格有不明项", type: "bool" },
  ],
  form: [
    { key: "copies", label: "纸表份数", type: "int" },
    { key: "require_sign", label: "须监护人签字", type: "bool" },
    { key: "require_seal", label: "须报名点盖章", type: "bool" },
    { key: "uncertain", label: "签章要求有不明项", type: "bool" },
  ],
  id_copy: [
    { key: "doc", label: "证件类型（户口本/身份证/护照）", type: "text" },
    { key: "copies", label: "复印件份数", type: "int" },
    { key: "need_original", label: "原件须到场核验", type: "bool" },
    { key: "uncertain", label: "份数要求有不明项", type: "bool" },
  ],
  slot: [
    { key: "lead_minutes", label: "提前到场分钟", type: "int" },
    { key: "late_minutes", label: "迟到弃考分钟", type: "int" },
  ],
  entrance: [
    { key: "name", label: "入口名称（须与孩子“入口”一致，如 北门）", type: "text" },
    { key: "open_after", label: "开放时刻（HH:MM）", type: "text" },
  ],
  route: [
    { key: "pairs", label: "入口对与步行分钟（每行：入口A,入口B,分钟）", type: "pairs" },
  ],
  note: [],
};

function renderClauses() {
  const list = $("#clauseList");
  if (!STATE.clauses.length) {
    list.innerHTML = `<p class="hint">尚无条款。在右侧录入简章上的乐种、级别、跳级、照片、签章、证件份数、候考时段、入口与步行脚注。</p>`;
  } else {
    list.innerHTML = STATE.clauses.map(c => `
      <div class="clause-item" onclick="editClause(${c.id})">
        <span class="x" onclick="event.stopPropagation();delClause(${c.id})">删除</span>
        <div class="top">
          <span class="ref">${esc(c.ref)}</span>
          <span class="cat">${esc(STATE.categories[c.category])}</span>
          <b>${esc(c.title)}</b>
        </div>
        <div class="body">${esc(c.body)}</div>
      </div>`).join("");
  }
  renderClauseForm();
}

window.editClause = function (id) {
  editingClauseId = id;
  renderClauseForm();
};

function renderClauseForm() {
  const f = $("#clauseForm");
  const c = editingClauseId ? STATE.clauses.find(x => x.id === editingClauseId) : null;
  $("#clauseFormTitle").textContent = c ? `编辑条款 ${c.ref}` : "新增条款";
  const sp = c?.spec || {};
  f.innerHTML = `
    <div class="row2">
      <div><label>类别</label>
        <select name="category">
          ${Object.entries(STATE.categories).map(([k, v]) =>
            `<option value="${k}" ${c?.category === k ? "selected" : ""}>${v}</option>`).join("")}
        </select></div>
      <div><label>公告依据编号</label><input name="ref" value="${esc(c?.ref || "")}" placeholder="如 TJ-01"></div>
    </div>
    <label>标题</label><input name="title" value="${esc(c?.title || "")}">
    <label>原文摘录（家长照简章抄录）</label><textarea name="body">${esc(c?.body || "")}</textarea>
    <div id="specFields"></div>
    <label>排序（小在前）</label><input name="sort_order" type="number" value="${c?.sort_order ?? 0}">
    <div class="actions">
      <button type="submit" class="primary">${c ? "保存修改（旧结论将失效）" : "加入简章"}</button>
      ${c ? `<button type="button" onclick="editingClauseId=null;renderClauseForm()">取消编辑</button>` : ""}
    </div>`;

  const catSel = f.querySelector("[name=category]");
  const drawSpec = () => {
    const defs = CAT_SPECS[catSel.value] || [];
    $("#specFields").innerHTML = defs.map(d => specInput(d, sp[d.key])).join("");
  };
  catSel.addEventListener("change", drawSpec);
  drawSpec();

  f.onsubmit = async e => {
    e.preventDefault();
    const fd = new FormData(f);
    const category = fd.get("category");
    const payload = {
      category,
      ref: fd.get("ref").trim(),
      title: fd.get("title").trim(),
      body: fd.get("body"),
      sort_order: Number(fd.get("sort_order") || 0),
      spec: collectSpec(category, f),
    };
    if (!payload.ref || !payload.title) return alert("依据编号和标题必填");
    try {
      if (c) await api("PATCH", `/api/clauses/${c.id}`, payload);
      else {
        const av = STATE.active_version;
        if (!av) return alert("请先新建简章版本");
        payload.version_id = av.id;
        await api("POST", "/api/clauses", payload);
      }
      editingClauseId = null;
      await refresh();
    } catch (err) { alert(err.message); }
  };
}

function specInput(d, val) {
  const name = `spec_${d.key}`;
  if (d.type === "bool")
    return `<label><input type="checkbox" name="${name}" ${val ? "checked" : ""}> ${d.label}</label>`;
  if (d.type === "int")
    return `<label>${d.label}<input type="number" name="${name}" value="${val ?? ""}"></label>`;
  if (d.type === "list")
    return `<label>${d.label}<input name="${name}" value="${esc((val || []).join("，"))}"></label>`;
  if (d.type === "pair")
    return `<label>${d.label}<input name="${name}" value="${esc((val || []).join(","))}"></label>`;
  if (d.type === "pairs")
    return `<label>${d.label}<textarea name="${name}">${esc((val || []).map(p => p.join(",")).join("\n"))}</textarea></label>`;
  return `<label>${d.label}<input name="${name}" value="${esc(val ?? "")}"></label>`;
}

function collectSpec(cat, form) {
  const out = {};
  for (const d of CAT_SPECS[cat] || []) {
    const el = form.querySelector(`[name=spec_${d.key}]`);
    if (!el) continue;
    if (d.type === "bool") { if (el.checked) out[d.key] = true; }
    else if (d.type === "int") { if (el.value !== "") out[d.key] = Number(el.value); }
    else if (d.type === "list") {
      const v = el.value.split(/[，,]/).map(s => s.trim()).filter(Boolean);
      if (v.length) out[d.key] = v;
    } else if (d.type === "pair") {
      const v = el.value.split(/[，,]/).map(s => s.trim()).filter(Boolean).map(Number);
      if (v.length === 2) out[d.key] = v;
    } else if (d.type === "pairs") {
      out[d.key] = el.value.split("\n").map(l => l.split(/[，,]/).map(s => s.trim()))
        .filter(p => p.length === 3 && p[2] !== "" && !isNaN(Number(p[2])))
        .map(p => [p[0], p[1], Number(p[2])]);
    } else if (el.value !== "") out[d.key] = el.value;
  }
  return out;
}

window.delClause = async function (id) {
  if (!confirm("删除该条款？旧核对结论将失效。")) return;
  await api("DELETE", `/api/clauses/${id}`);
  await refresh();
};

$("#newVersionBlankBtn").onclick = () => createBlankVersion();
$("#newVersionBtn").onclick = async () => {
  const a = STATE.active_version;
  if (!a) return createBlankVersion();
  const title = prompt("新版简章名称（将复制当前全部条款，请按新公告逐条修订）",
    a.title.replace(/（改版）.*$/, "") + "（改版）");
  if (!title) return;
  await api("POST", `/api/versions/${a.id}/duplicate`, { title });
  await refresh();
  alert("已创建改版并激活。所有旧核对结论已标记失效，请改完条款后重新核对。");
};

/* ------------------------------------------------------------- 孩子卡片 */

function renderChildren() {
  const wrap = $("#childCards");
  if (!STATE.children.length) {
    wrap.innerHTML = `<p class="hint">还没有孩子档案，点上方“添加孩子”。</p>`;
    return;
  }
  wrap.innerHTML = STATE.children.map(childCard).join("");
}

function childCard(ch) {
  return `
  <div class="card child-card" data-cid="${ch.id}">
    <div class="subhead">
      <h3>${esc(ch.name)} <span class="tag">装袋顺序 #${ch.bag_order}</span></h3>
      <div><button class="mini" onclick="editChild(${ch.id})">改档案</button>
           <button class="mini danger" onclick="delChild(${ch.id})">删除</button></div>
    </div>
    <div class="hint">${esc(ch.instrument || "未填乐种")} ·
      ${ch.apply_level != null ? ch.apply_level + " 级" : "级别未填"} ·
      ${ch.skip_from ? `${ch.skip_from} 级跳报` : "逐级报考"} ·
      ${esc(ch.exam_date || "日期未填")} ${esc(ch.slot_start || "")}–${esc(ch.slot_end || "")} ·
      ${esc(ch.entrance || "入口未填")}</div>

    ${miniSection("已有证书", ch.certs.map(r => `
      <div class="rowline">
        <span class="grow">${esc(r.instrument)} ${r.level} 级 · ${esc(r.issuer || "发证单位未填")}</span>
        <label><input type="checkbox" ${r.has_original ? "checked" : ""}
          onchange="patchSub('certs',${r.id},{has_original:this.checked})"> 有原件</label>
        <button class="mini danger" onclick="delSub('certs',${r.id})">删</button>
      </div>`).join(""),
      `addInline('certs',${ch.id},['乐种','级别(数字)','发证单位(可空)'])`)}

    ${miniSection("曲目（加试请勾“跳级加试”）", ch.pieces.map(r => `
      <div class="rowline">
        <span class="grow">${esc(r.title)} ${r.is_extra ? '<span class="tag">加试</span>' : ""}</span>
        <label><input type="checkbox" ${r.is_extra ? "checked" : ""}
          onchange="patchSub('pieces',${r.id},{is_extra:this.checked})"> 加试</label>
        <label><input type="checkbox" ${r.ready ? "checked" : ""}
          onchange="patchSub('pieces',${r.id},{ready:this.checked})"> 已练成</label>
        <button class="mini danger" onclick="delSub('pieces',${r.id})">删</button>
      </div>`).join(""),
      `addInline('pieces',${ch.id},['曲名'])`)}

    ${miniSection("纸件材料", ch.materials.map(materialRow).join(""),
      `addMaterial(${ch.id})`)}

    ${miniSection("同行成人候考安排", ch.windows.map(w => `
      <div class="rowline">
        <span class="grow">${esc(w.adult_name)} ${esc(w.start)}–${esc(w.end)} @ ${esc(w.entrance || ch.entrance)}</span>
        <button class="mini" onclick="editWindow(${w.id},${ch.id})">改</button>
        <button class="mini danger" onclick="delSub('windows',${w.id})">删</button>
      </div>`).join(""),
      `editWindow(null,${ch.id})`)}
  </div>`;
}

function miniSection(title, rowsHtml, addCall) {
  return `<div class="section-mini"><h4>${title}</h4>
    ${rowsHtml || `<p class="hint">（无）</p>`}
    <button class="mini" onclick="${addCall}">＋ 添加</button></div>`;
}

function materialRow(m) {
  return `
  <div class="rowline" style="border-bottom:1px dotted #eee;padding-bottom:6px;margin-bottom:6px;">
    <span class="grow">
      ${m.checked ? "✅" : "⬜"} <b>${esc(m.label)}</b>
      <span class="status-pill ${m.status}">${STATUS_LABEL[m.status]}</span>
      ${m.uses_original ? `<span class="tag">占用原件：${esc(m.uses_original)}</span>` : ""}
      ${m.hold_start ? `交验 ${esc(m.hold_start)}–${esc(m.hold_end)} @ ${esc(m.location || "入口")}` : ""}
    </span>
    <button class="mini" onclick="editMaterial(${m.id})">编辑</button>
    <button class="mini" onclick="toggleChecked(${m.id},${m.checked ? 0 : 1})">${m.checked ? "取消勾选" : "勾选已装袋"}</button>
    <button class="mini danger" onclick="delSub('materials',${m.id})">删</button>
  </div>`;
}

window.toggleChecked = async (id, checked) => {
  await api("PATCH", `/api/materials/${id}`, { checked: !!checked });
  await refresh();
};

$("#addChildBtn").onclick = () => editChild(null);

window.editChild = function (id) {
  const ch = id ? STATE.children.find(c => c.id === id) : {};
  const fields = [
    ["name", "姓名", "text"], ["instrument", "乐种（古筝/二胡/…）", "text"],
    ["apply_level", "报考级别", "number"], ["skip_from", "从几级跳报（逐级留空）", "number"],
    ["exam_date", "考试日期", "date"], ["slot_start", "候考开始 HH:MM", "text"],
    ["slot_end", "候考结束 HH:MM", "text"], ["entrance", "候考入口（北门/南门）", "text"],
    ["exam_number", "准考证号", "text"], ["birth_date", "出生日期", "date"],
    ["id_type", "证件类型", "text"], ["id_number", "证件号码", "text"],
    ["guardian", "监护人", "text"], ["bag_order", "装袋顺序", "number"],
  ];
  openModal(`<h2>${id ? "修改" : "添加"}孩子</h2>
    <form id="childForm" class="form">
      ${fields.map(([k, l, t]) => `
        <label>${l}</label><input name="${k}" type="${t}" value="${esc(ch[k] ?? "")}">`).join("")}
      <div class="actions"><button class="primary" type="submit">保存</button>
      <button type="button" onclick="closeModal()">取消</button></div>
    </form>`);
  $("#childForm").onsubmit = async e => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const p = {};
    for (const [k] of fields) {
      let v = fd.get(k);
      if (["apply_level", "skip_from", "bag_order"].includes(k))
        v = v === "" ? null : Number(v);
      p[k] = v;
    }
    if (!p.name) return alert("姓名必填");
    if (id) await api("PATCH", `/api/children/${id}`, p);
    else await api("POST", "/api/children", p);
    closeModal();
    await refresh();
  };
};

window.delChild = async id => {
  if (!confirm("删除该孩子及其全部材料记录？")) return;
  await api("DELETE", `/api/children/${id}`);
  await refresh();
};

window.addInline = async function (table, cid, labels) {
  const vals = prompt(`输入：${labels.join(" / ")}`);
  if (!vals) return;
  const parts = vals.split(/[，,\/]/).map(s => s.trim());
  const body = table === "certs"
    ? { instrument: parts[0], level: Number(parts[1]) || null, issuer: parts[2] || "", has_original: true }
    : { title: parts[0], is_extra: false, ready: true };
  await api("POST", `/api/children/${cid}/${table}`, body);
  await refresh();
};

window.addMaterial = function (cid) { editMaterial(null, cid); };

window.editMaterial = function (id, forcedCid) {
  const m = id ? STATE.children.flatMap(c => c.materials).find(x => x.id === id)
               : { child_id: forcedCid, mtype: "other", status: "missing", copies: 1 };
  let detail = {};
  try { detail = JSON.parse(m.detail || "{}"); } catch { detail = {}; }
  openModal(`<h2>${id ? "编辑材料" : "自加材料"}</h2>
    <form id="matForm" class="form">
      <label>名称</label><input name="label" value="${esc(m.label || "")}">
      <div class="row3">
        <div><label>类型</label>
          <select name="mtype">
            ${["form", "photo", "cert", "id_copy", "other"].map(t =>
              `<option value="${t}" ${m.mtype === t ? "selected" : ""}>
                ${{ form: "纸表", photo: "照片", cert: "证书", id_copy: "证件复印", other: "其他" }[t]}</option>`).join("")}
          </select></div>
        <div><label>状态</label>
          <select name="status">
            ${["ok", "partial", "missing"].map(s =>
              `<option value="${s}" ${m.status === s ? "selected" : ""}>${STATUS_LABEL[s]}</option>`).join("")}
          </select></div>
        <div><label>份数</label><input type="number" name="copies" value="${m.copies ?? 1}"></div>
      </div>
      <label>占用原件名（兄妹共用件填同一名称才会判占用，如 户口本原件、证书(二胡6级)；不占用留空）</label>
      <input name="uses_original" value="${esc(m.uses_original || "")}">
      <div class="row3">
        <div><label>交验起</label><input name="hold_start" value="${esc(m.hold_start || "")}" placeholder="07:45"></div>
        <div><label>交验止</label><input name="hold_end" value="${esc(m.hold_end || "")}" placeholder="08:00"></div>
        <div><label>交验地点/入口</label><input name="location" value="${esc(m.location || "")}"></div>
      </div>
      <div id="detailBox"></div>
      <div class="actions"><button class="primary" type="submit">保存</button>
      <button type="button" onclick="closeModal()">取消</button></div>
    </form>`);
  const drawDetail = () => {
    const t = $("#matForm [name=mtype]").value;
    let html = "";
    if (t === "form") {
      html = ["name", "instrument", "apply_level", "exam_number", "birth_date",
        "id_number", "guardian"].map(k =>
        `<div><label>纸表上的${{ name: "姓名", instrument: "乐种", apply_level: "报考级别",
          exam_number: "准考证号", birth_date: "出生日期", id_number: "证件号码",
          guardian: "监护人" }[k]}</label><input data-d="${k}" value="${esc(detail[k] ?? "")}"></div>`).join("");
      html = `<label>纸表已填字段（用于与报考登记比对矛盾）</label><div class="row2">${html}</div>
        <div class="row2">
        <label><input type="checkbox" data-d="signed" ${detail.signed !== false ? "checked" : ""}> 已签字</label>
        <label><input type="checkbox" data-d="sealed" ${detail.sealed !== false ? "checked" : ""}> 已盖章</label></div>`;
    } else if (t === "photo") {
      html = `<label>照片底色（蓝/红/白）</label><input data-d="background" value="${esc(detail.background || "")}">`;
    }
    $("#detailBox").innerHTML = html;
  };
  $("#matForm [name=mtype]").addEventListener("change", drawDetail);
  drawDetail();
  $("#matForm").onsubmit = async e => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const det = {};
    $$("#detailBox [data-d]").forEach(el => {
      const k = el.dataset.d;
      if (el.type === "checkbox") det[k] = el.checked;
      else if (el.value !== "") det[k] = k === "apply_level" ? Number(el.value) : el.value;
    });
    const body = {
      label: fd.get("label"), mtype: fd.get("mtype"), status: fd.get("status"),
      copies: Number(fd.get("copies") || 1), uses_original: fd.get("uses_original"),
      hold_start: fd.get("hold_start"), hold_end: fd.get("hold_end"),
      location: fd.get("location"), detail: JSON.stringify(det),
    };
    if (!body.label) return alert("名称必填");
    if (id) await api("PATCH", `/api/materials/${id}`, body);
    else await api("POST", `/api/children/${m.child_id}/materials`, body);
    closeModal();
    await refresh();
  };
};

window.editWindow = function (id, cid) {
  const w = id ? STATE.children.flatMap(c => c.windows).find(x => x.id === id) : {};
  const ch = STATE.children.find(c => c.id === cid);
  openModal(`<h2>${id ? "修改" : "添加"}同行安排</h2>
    <form id="winForm" class="form">
      <label>同行成人</label><input name="adult_name" value="${esc(w.adult_name || "")}" placeholder="如 林建国（爸爸）">
      <div class="row3">
        <div><label>起</label><input name="start" value="${esc(w.start || "")}" placeholder="07:40"></div>
        <div><label>止</label><input name="end" value="${esc(w.end || "")}" placeholder="08:10"></div>
        <div><label>入口（留空=孩子入口）</label><input name="entrance" value="${esc(w.entrance || ch?.entrance || "")}"></div>
      </div>
      <div class="actions"><button class="primary" type="submit">保存</button>
      <button type="button" onclick="closeModal()">取消</button></div>
    </form>`);
  $("#winForm").onsubmit = async e => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = Object.fromEntries(fd.entries());
    if (!body.adult_name || !body.start || !body.end) return alert("成人与时段必填");
    if (id) await api("PATCH", `/api/windows/${id}`, body);
    else await api("POST", `/api/children/${cid}/windows`, body);
    closeModal();
    await refresh();
  };
};

window.patchSub = (t, id, body) =>
  api("PATCH", `/api/${t}/${id}`, body).then(refresh);
window.delSub = async (t, id) => {
  await api("DELETE", `/api/${t}/${id}`);
  await refresh();
};

$("#syncMaterialsBtn").onclick = async () => {
  try {
    const r = await api("POST", "/api/children/sync-materials");
    await refresh();
    alert(r.added.length ? `已新增 ${r.added.length} 项：\n` + r.added.join("\n")
                         : "清单已按简章校准，无新增项。");
  } catch (e) { alert(e.message); }
};

/* ------------------------------------------------------------- 核对结论 */

$("#runCheckBtn").onclick = async () => {
  try {
    await api("POST", "/api/checks");
    viewingRunId = null;
    await refresh();
  } catch (e) { alert(e.message); }
};

function activeRun() {
  if (!STATE.runs.length) return null;
  if (viewingRunId) return STATE.runs.find(r => r.id === viewingRunId) || STATE.runs[0];
  return STATE.runs[0];
}

function renderChecks() {
  const run = activeRun();
  const meta = $("#checkMeta");
  const banner = $("#staleBanner");
  if (!run) {
    $("#findings").innerHTML = `<p class="hint">尚未核对。先在①②录好简章与材料，再点上方按钮。</p>`;
    $("#originalPanel").innerHTML = "";
    $("#runHistory").innerHTML = "";
    meta.textContent = "";
    banner.classList.add("hidden");
    return;
  }
  const stale = run.staleness !== "fresh";
  meta.textContent = `第 ${run.id} 次核对 · ${run.created_at}`;
  banner.classList.toggle("hidden", !stale);
  banner.innerHTML = staleText(run.staleness);

  const sorted = [...run.findings].sort(
    (a, b) => SEV_ORDER[a.severity] - SEV_ORDER[b.severity]);
  const grouped = Object.groupBy ? Object.groupBy(sorted, f => f.severity) : null;
  const counts = { fail: 0, pending: 0, warn: 0, ok: 0 };
  sorted.forEach(f => counts[f.severity]++);
  meta.textContent += `　不通过 ${counts.fail} · 待确认 ${counts.pending} · 提醒 ${counts.warn} · 通过 ${counts.ok}`;

  $("#findings").innerHTML = sorted.map(f => {
    const stamp = stale ? `<span class="stale-stamp">已失效·仅留档</span>` : "";
    return `<div class="finding ${f.severity} ${stale ? "stale" : ""}">
      <span class="sev">${SEV_LABEL[f.severity]}</span>${esc(f.message)}${stamp}
      ${f.cites.length ? `<div class="cites">公告依据：${f.cites.map(c =>
        `<b>${esc(c.ref)}</b>《${esc(c.title)}`).join("；")}</div>` : ""}
    </div>`;
  }).join("");

  $("#originalPanel").innerHTML = run.carried_originals.length
    ? run.carried_originals.map(o => {
        const pairs = (run.original_pairs || []).filter(p => p.original === o);
        return `<div class="orig-chain-item">🔑 <b>${esc(o)}</b>` +
          (pairs.length ? pairs.map(p => ` <div class="hint">被 ${p.windows.map(w =>
            `${esc(w.name)} ${w.start}–${w.end} @${esc(w.location)}`).join(" ／ ")}</div>`).join("")
                        : ` <span class="hint">仅一份材料占用</span>`) +
          `</div>`; }).join("")
    : `<p class="hint">未登记需要携带的原件。</p>`;

  $("#runHistory").innerHTML = STATE.runs.map(r => `
    <div class="run-hist-item" onclick="viewingRunId=${r.id};renderChecks();renderChecklist()">
      #${r.id} ${r.created_at}
      ${r.staleness === "fresh" ? '<span class="status-pill ok">现行有效</span>'
        : r.staleness === "old_version" ? '<span class="status-pill missing">旧版结论</span>'
        : '<span class="status-pill partial">已失效</span>'}
      <span class="hint">${r.findings.filter(f => f.severity === "fail").length} 不通过</span>
    </div>`).join("");
}

function staleText(kind) {
  return {
    stale_data: "⚠ 报考信息或材料在上次核对之后发生变化，以上旧结论已失效，请重新核对。",
    stale_version: "⚠ 简章条款在上次核对之后被修改，以上旧结论已失效，请重新核对。",
    old_version: "⚠ 该结论依据的简章版本已不是当前启用版本（改版后旧结论一律失效）。",
  }[kind] || "";
}

/* ------------------------------------------------------------- 清单 + 时间带 */

function renderChecklist() {
  const sheets = $("#checklistSheets");
  const run = activeRun();
  const findByKey = (cid, key) => run
    ? run.findings.filter(f => f.child_id === cid && f.req_key === key)
    : [];

  if (!STATE.children.length) {
    sheets.innerHTML = "";
    return;
  }
  sheets.innerHTML = STATE.children.map(ch => {
    const mats = [...ch.materials].sort((a, b) => a.bag_order - b.bag_order);
    return `<div class="sheet">
      <h3>装袋清单 · ${esc(ch.name)}</h3>
      <div class="meta">${esc(ch.instrument)} ${ch.apply_level ?? "?"} 级${ch.skip_from ? `（${ch.skip_from} 级跳报）` : ""}
        · ${esc(ch.exam_date)} ${esc(ch.slot_start)}–${esc(ch.slot_end)} · ${esc(ch.entrance)}
        · 准考证 ${esc(ch.exam_number || "未填")}</div>
      <table>
        <thead><tr><th class="box">✓</th><th>材料</th><th>状态/份数</th>
        <th>占用原件 / 交验</th><th>公告依据与提示</th></tr></thead>
        <tbody>${mats.map(m => {
          const fs = run ? run.findings.filter(f =>
            f.child_id === ch.id && (f.req_key === m.req_key ||
            (f.rule === "original" && f.message.includes(m.uses_original)))) : [];
          const bad = fs.filter(f => f.severity === "fail");
          const refs = [...new Set(fs.flatMap(f => f.cites.map(c => c.ref)))];
          return `<tr>
            <td class="box">${m.checked ? "✅" : "☐"}</td>
            <td>${esc(m.label)} ${m.req_key ? "" : '<span class="tag">自加</span>'}</td>
            <td><span class="status-pill ${m.status}">${STATUS_LABEL[m.status]}</span>
                ×${m.copies}</td>
            <td>${m.uses_original ? `🔑 ${esc(m.uses_original)}` : ""}
                ${m.hold_start ? `<br><span class="hint">${esc(m.hold_start)}–${esc(m.hold_end)} @${esc(m.location || ch.entrance)}</span>` : ""}</td>
            <td>${refs.map(r => `<span class="cite">${esc(r)}</span>`).join(" ")}
                ${bad.length ? `<div class="cite">⚠ ${esc(bad[0].message.split("：").slice(-1)[0])}</div>` : ""}</td>
          </tr>`;
        }).join("")}</tbody>
      </table>
    </div>`;
  }).join("");

  renderEarliest(run);
  renderTimeline(run);
}

function renderEarliest(run) {
  const band = $("#earliestBand");
  if (!run) { band.className = "earliest-band none"; band.innerHTML =
    `<span class="clock">—</span> 尚未核对，无法标出最早冲突。`; return; }
  const fails = run.findings.filter(f => f.severity === "fail");
  if (!fails.length) {
    band.className = "earliest-band none";
    band.innerHTML = `<span class="clock">✓</span> 现行核对无不通过项；仍请注意“待确认”条款与提醒。`;
    return;
  }
  const e = run.earliest_conflict;
  band.className = "earliest-band";
  band.innerHTML = `<span class="clock">⏑ ${e ? e.time : "!"}</span>
    <div><b>当天最早冲突点：${e ? esc(e.label) : "（未关联到时刻）"}</b><br>
    <span class="hint">应携原件：${(run.carried_originals || []).map(esc).join("、") || "无"}
    · 共 ${fails.length} 条不通过，出发前按③逐条处理。</span></div>`;
}

/* ----------------------------------------------------------- SVG 时间带 */

function renderTimeline(run) {
  const svg = $("#timeline");
  const kids = STATE.children;
  if (!kids.length) { svg.innerHTML = ""; return; }

  const events = [];
  kids.forEach(ch => {
    if (ch.slot_start && ch.slot_end) events.push({ start: ch.slot_start, end: ch.slot_end, lane: ch.id,
      type: "slot", label: `${ch.name} 候考`, loc: ch.entrance });
    ch.windows.forEach(w => { if (w.start && w.end) events.push({
      start: w.start, end: w.end, lane: ch.id, type: "window",
      label: w.adult_name, loc: w.entrance || ch.entrance }); });
    ch.materials.forEach(m => { if (m.uses_original && m.hold_start && m.hold_end)
      events.push({ start: m.hold_start, end: m.hold_end, lane: ch.id,
        type: "original", label: m.uses_original, loc: m.location || ch.entrance,
        original: m.uses_original }); });
  });
  const mins = events.flatMap(e => [toM(e.start), toM(e.end)]).filter(v => v != null);
  if (!mins.length) { svg.innerHTML = `<text x="20" y="40" fill="#766f62">填写候考时段后在此显示时间带</text>`; return; }
  const t0 = Math.min(...mins) - 20, t1 = Math.max(...mins) + 20;

  const W = 960, H = 120 + kids.length * 86;
  const padL = 120, padR = 30, top = 54;
  const bandH = Math.max(H, 300);
  svg.setAttribute("viewBox", `0 0 ${W} ${bandH}`);
  const x = m => padL + (m - t0) / (t1 - t0) * (W - padL - padR);
  const NS = "http://www.w3.org/2000/svg";
  const el = (tag, attrs, txt) => {
    const n = document.createElementNS(NS, tag);
    Object.entries(attrs || {}).forEach(([k, v]) => n.setAttribute(k, v));
    if (txt != null) n.textContent = txt;
    return n;
  };
  svg.innerHTML = "";

  // 小时网格
  const firstHour = Math.ceil(t0 / 60) * 60;
  for (let t = firstHour; t <= t1; t += 30) {
    svg.appendChild(el("line", {
      x1: x(t), y1: top - 8, x2: x(t), y2: bandH - 30,
      stroke: t % 60 === 0 ? "#d8cfbe" : "#eee8db", "stroke-width": 1 }));
    svg.appendChild(el("text", {
      x: x(t), y: top - 14, "font-size": 12, fill: "#766f62", "text-anchor": "middle" },
      `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`));
  }

  // 入口开放竖线
  const entrances = STATE.clauses.filter(c => c.category === "entrance");
  entrances.forEach(c => {
    const sp = c.spec;
    const tm = toM(sp.open_after);
    if (tm == null) return;
    svg.appendChild(el("line", {
      x1: x(tm), y1: top - 8, x2: x(tm), y2: bandH - 30,
      stroke: "#1e6b3b", "stroke-width": 1.4, "stroke-dasharray": "5 4" }));
    svg.appendChild(el("text", {
      x: x(tm) + 3, y: top - 22, "font-size": 11, fill: "#1e6b3b" },
      `${sp.name || c.title} ${sp.open_after} 开放`));
  });

  const failCids = new Set((run?.findings || []).filter(f => f.severity === "fail").map(f => f.child_id));
  const laneY = {};
  kids.forEach((ch, i) => {
    const y = top + 12 + i * 86;
    laneY[ch.id] = y;
    svg.appendChild(el("text", {
      x: 12, y: y + 24, "font-size": 15, "font-weight": 700,
      fill: failCids.has(ch.id) ? "#b3261e" : "#23201b" }, ch.name));
    svg.appendChild(el("text", {
      x: 12, y: y + 44, "font-size": 11, fill: "#766f62" },
      `${ch.instrument || ""} ${ch.apply_level ?? ""}级`));
    const baseY = y;
    events.filter(e => e.lane === ch.id).forEach((e, j) => {
      const s = toM(e.start), en = toM(e.end);
      if (s == null || en == null) return;
      const yy = baseY + j * 22;
      const color = { slot: "#9c3a2e", window: "#a5803e", original: "#1e5e8a" }[e.type];
      svg.appendChild(el("rect", {
        x: x(s), y: yy, width: Math.max(3, x(en) - x(s)), height: 17, rx: 4,
        fill: color, opacity: 0.82 }));
      svg.appendChild(el("text", {
        x: x(s) + 4, y: yy + 13, "font-size": 10.5, fill: "#fff" },
        `${e.label} @${e.loc || ""}`));
    });
  });

  // 原件/成人跨兄妹连线（同 original 或同一成人）
  const linkPairs = [];
  const byOrig = {};
  events.filter(e => e.type === "original").forEach(e =>
    (byOrig[e.original] ||= []).push(e));
  Object.entries(byOrig).filter(([, es]) => new Set(es.map(e => e.lane)).size > 1)
    .forEach(([key, es]) => linkPairs.push({ key, kind: "original", events: es }));
  const byAdult = {};
  events.filter(e => e.type === "window").forEach(e =>
    (byAdult[e.label] ||= []).push(e));
  Object.entries(byAdult).filter(([, es]) => new Set(es.map(e => e.lane)).size > 1)
    .forEach(([key, es]) => linkPairs.push({ key, kind: "window", events: es }));

  const failMsgs = (run?.findings || []).filter(f => f.severity === "fail")
    .map(f => f.message);
  linkPairs.forEach(({ events: es, key: linkKey, kind: linkKind }) => {
    es.forEach((e, i) => {
      if (!i) return;
      const p = es[i - 1];
      const x1 = x(toM(p.end)), y1 = laneY[p.lane] + 8;
      const x2 = x(toM(e.start)), y2 = laneY[e.lane] + 8;
      const mid = (x1 + x2) / 2;
      const path = `M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}`;
      const conflict = failMsgs.some(m => m.includes(linkKey));
      svg.appendChild(el("path", {
        d: path, fill: "none", stroke: conflict ? "#b3261e" : "#1e6b3b",
        "stroke-width": 1.6, "stroke-dasharray": "4 3" }));
    });
  });

  // 最早冲突标记
  if (run?.earliest_conflict) {
    const tm = toM(run.earliest_conflict.time);
    if (tm != null) {
      svg.appendChild(el("line", {
        x1: x(tm), y1: top - 8, x2: x(tm), y2: bandH - 30,
        stroke: "#b3261e", "stroke-width": 2.2 }));
      svg.appendChild(el("polygon", {
        points: `${x(tm) - 6},${top - 6} ${x(tm) + 6},${top - 6} ${x(tm)},${top + 4}`,
        fill: "#b3261e" }));
      svg.appendChild(el("text", {
        x: x(tm) + 8, y: 18, "font-size": 13, "font-weight": 700, fill: "#b3261e" },
        `最早冲突 ${run.earliest_conflict.time} ${run.earliest_conflict.label}`));
    }
  }

  // 图例
  [["#9c3a2e", "孩子候考"], ["#a5803e", "成人陪护"], ["#1e5e8a", "原件交验"],
   ["#1e6b3b", "入口开放"], ["#b3261e", "冲突"]].forEach(([c, t], i) => {
    svg.appendChild(el("rect", { x: 130 + i * 130, y: 10, width: 14, height: 10, fill: c }));
    svg.appendChild(el("text", { x: 148 + i * 130, y: 19, "font-size": 11, fill: "#555" }, t));
  });
}

function toM(hhmm) {
  if (!hhmm) return null;
  const m = String(hhmm).match(/^(\d{1,2}):(\d{2})$/);
  return m ? Number(m[1]) * 60 + Number(m[2]) : null;
}

/* ------------------------------------------------------------- 模态/杂项 */

function openModal(html) {
  $("#modalCard").innerHTML = html;
  $("#modal").classList.remove("hidden");
}
function closeModal() { $("#modal").classList.add("hidden"); }
window.closeModal = closeModal;
$("#modal").addEventListener("click", e => { if (e.target.id === "modal") closeModal(); });

$("#printBtn").onclick = () => window.print();

refresh().catch(e => alert("初始化失败：" + e.message));

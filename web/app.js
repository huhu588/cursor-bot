"use strict";

// 与 Python 侧 Api 通过 window.pywebview.api 通信；批量领取用并发池并行驱动，逐行更新状态。

let accounts = [];
let groups = [];
let groupFilter = "";
let tagAccountId = null;
const rowState = {}; // id -> { outcome/unlocked/percent/detail/team/... }
const selected = new Set(); // 勾选的账号 id；为空表示对全部生效
let busy = false;

const $ = (id) => document.getElementById(id);

function api() {
  return window.pywebview && window.pywebview.api;
}

function toast(msg, ms = 2200) {
  const el = $("toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (el.hidden = true), ms);
}

function setStatus(text) {
  const el = $("statusText");
  if (el) el.textContent = text || "就绪";
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

function fmtPercent(p) {
  if (p == null || isNaN(p)) return "";
  const v = Math.max(0, Number(p));
  return (v < 1 && v > 0 ? v.toFixed(2) : v.toFixed(1)) + "%";
}

function fmtUsd(v) {
  if (v == null || isNaN(v)) return "";
  const n = Number(v);
  return "$" + (n >= 100 ? n.toFixed(0) : n.toFixed(2));
}

function fmtReset(v) {
  if (v == null || v === "") return "";
  let d;
  if (typeof v === "number" || /^\d+$/.test(String(v))) {
    let n = Number(v);
    if (n < 1e12) n *= 1000; // 秒 -> 毫秒
    d = new Date(n);
  } else {
    d = new Date(v);
  }
  if (isNaN(d.getTime())) return "";
  const p2 = (x) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())} ${p2(d.getHours())}:${p2(d.getMinutes())}`;
}

// bot 额度是周期性重置的：给出距下次重置的倒计时。
function fmtResetRelative(v) {
  if (v == null || v === "") return "";
  let d;
  if (typeof v === "number" || /^\d+$/.test(String(v))) {
    let n = Number(v);
    if (n < 1e12) n *= 1000;
    d = new Date(n);
  } else {
    d = new Date(v);
  }
  if (isNaN(d.getTime())) return "";
  const ms = d.getTime() - Date.now();
  if (ms <= 0) return "可重置";
  const totalHours = Math.floor(ms / 3600000);
  const days = Math.floor(totalHours / 24);
  const hours = totalHours % 24;
  if (days > 0) return `还剩 ${days}天${hours}小时`;
  const mins = Math.floor((ms % 3600000) / 60000);
  return `还剩 ${hours}小时${mins}分`;
}

// 本周期起始在 24 小时内 → 视为「今天刚重置」。
function isJustReset(v) {
  if (v == null || v === "") return false;
  let d;
  if (typeof v === "number" || /^\d+$/.test(String(v))) {
    let n = Number(v);
    if (n < 1e12) n *= 1000;
    d = new Date(n);
  } else {
    d = new Date(v);
  }
  if (isNaN(d.getTime())) return false;
  const ms = Date.now() - d.getTime();
  return ms >= 0 && ms <= 24 * 3600000;
}

// 领取/刷新拿到真实邮箱后回写行 label（并持久化到 Python 侧）。
function applyEmail(id, email) {
  if (!email || !String(email).includes("@")) return;
  const a = accounts.find((x) => x.id === id);
  if (!a || a.email === email) return;
  a.email = email;
  const bridge = api();
  if (bridge && bridge.set_email) bridge.set_email(id, email);
}

function accountTitle(a) {
  const nick = String(a.label || "").trim();
  if (nick && nick !== a.id) return nick;
  if (a.email && String(a.email).includes("@")) return a.email;
  return a.id;
}

function accountSub(a) {
  const nick = String(a.label || "").trim();
  const email = String(a.email || "").trim();
  if (nick && nick !== a.id && email && nick !== email) return email;
  return a.id;
}

function visibleAccounts() {
  if (!groupFilter) return accounts;
  if (groupFilter === "__none__") return accounts.filter((a) => !String(a.group || "").trim());
  return accounts.filter((a) => String(a.group || "") === groupFilter);
}

function previewSave() {
  if (api()) return;
  try {
    localStorage.setItem("infinity-preview-store", JSON.stringify({ accounts, groups, rowState }));
  } catch (e) {
    /* ignore */
  }
}

function fillGroupFilter() {
  const sel = $("groupFilter");
  if (!sel) return;
  const current = groupFilter;
  const opts = [`<option value="">全部分组</option>`, `<option value="__none__">未分组</option>`];
  groups.forEach((g) => {
    opts.push(`<option value="${esc(g)}">${esc(g)}</option>`);
  });
  sel.innerHTML = opts.join("");
  sel.value = groups.includes(current) || current === "" || current === "__none__" ? current : "";
  groupFilter = sel.value;
}

function fillGroupSelect(selectEl, selected) {
  if (!selectEl) return;
  const value = selected || "";
  const opts = [`<option value="">未分组</option>`];
  groups.forEach((g) => opts.push(`<option value="${esc(g)}">${esc(g)}</option>`));
  selectEl.innerHTML = opts.join("");
  selectEl.value = groups.includes(value) ? value : "";
}

// 只记忆有意义的稳定状态；run/bad 不落盘，避免重开显示"处理中/失败"。
const PERSIST_KINDS = new Set(["ok", "idle", "card"]);
let persistTimer = null;
function schedulePersist() {
  clearTimeout(persistTimer);
  persistTimer = setTimeout(() => {
    const clean = {};
    for (const [id, st] of Object.entries(rowState)) {
      if (st && PERSIST_KINDS.has(st.kind)) clean[id] = st;
    }
    const bridge = api();
    if (bridge && bridge.save_status) bridge.save_status(clean);
  }, 400);
}

function statusCell(st) {
  if (!st) return `<span class="pill idle">待领取</span>`;
  switch (st.kind) {
    case "run":
      return `<span class="pill run">处理中…</span>`;
    case "ok":
      return `<span class="pill ok" title="${esc(st.detail || "")}">${esc(st.label || "已开通")}</span>`;
    case "card":
      return `<span class="pill warn" title="${esc(st.detail || "")}">需绑卡</span>`;
    case "bad":
      return `<span class="pill bad" title="${esc(st.detail || "")}">${esc(st.label || "失败")}</span>`;
    case "idle":
      return `<span class="pill idle" title="${esc(st.detail || "")}">${esc(st.label || "未开通")}</span>`;
    default:
      return `<span class="pill idle">待领取</span>`;
  }
}

function fmtCents(cents) {
  if (cents == null || isNaN(Number(cents))) return "—";
  const n = Number(cents) / 100;
  return "$" + (Math.abs(n) >= 100 ? n.toFixed(0) : n.toFixed(2));
}

function quotaBar(percent, usedCents, limitCents, label) {
  if (percent == null && usedCents == null && limitCents == null) return "";
  const v = Math.min(100, Math.max(0, Number(percent) || 0));
  const hasUsed = usedCents != null;
  const hasLimit = limitCents != null;
  // used 缺失但 limit 有值时显示「— / $150」；两者都缺失时只显示百分比。
  let amount = "";
  if (hasUsed || hasLimit) {
    amount = " " + esc(fmtCents(usedCents));
    if (hasLimit) amount += " / " + esc(fmtCents(limitCents));
  }
  const pct = percent != null ? " · " + esc(fmtPercent(percent)) : "";
  return `<div class="hint">${esc(label)}${amount}${pct}</div><div class="bar ${usageToneClass(percent)}"><i style="width:${v}%"></i></div>`;
}

function quotaCell(st) {
  if (!st) return `<span class="hint">—</span>`;
  let html = "";
  if (st.percent != null) {
    const v = Math.min(100, Math.max(0, Number(st.percent)));
    const fresh = isJustReset(st.periodStart) ? ` <span class="tag-reset">刚重置</span>` : "";
    html += `<div class="mono">Bot 周用量 ${esc(fmtPercent(st.percent))}${fresh}</div><div class="bar ${usageToneClass(st.percent)}"><i style="width:${v}%"></i></div>`;
    const reset = fmtReset(st.nextReset);
    if (reset) {
      const rel = fmtResetRelative(st.nextReset);
      html += `<div class="hint">重置 ${esc(reset)}${rel ? "（" + esc(rel) + "）" : ""}</div>`;
    }
  }
  html += quotaBar(st.apiPercent, st.apiSpendCents, st.apiLimitCents, "API");
  html += quotaBar(st.autoPercent, st.autoSpendCents, st.autoLimitCents, "Auto");
  if (st.periodSpendUsd != null) {
    html += `<div class="hint mono">本周期 ${esc(fmtUsd(st.periodSpendUsd))}</div>`;
  }
  if (st.spendUsd != null || st.teamPercent != null) {
    const pct = st.teamPercent != null ? st.teamPercent : st.totalPercent;
    const bits = [];
    if (st.spendUsd != null) bits.push(`本月 ${esc(fmtUsd(st.spendUsd))}`);
    if (pct != null) bits.push(`月用量 ${esc(fmtPercent(pct))}`);
    if (bits.length) html += `<div class="hint">${bits.join(" · ")}</div>`;
  }
  if (!html && st.totalPercent != null) {
    html += `<div class="hint mono">总用量 ${esc(fmtPercent(st.totalPercent))}</div>`;
  }
  return html || `<span class="hint">—</span>`;
}

function membershipLabel(m) {
  const map = { free: "Free", pro: "Pro", pro_plus: "Pro+", "pro-plus": "Pro+", ultra: "Ultra", enterprise: "企业", team: "Team", business: "Business" };
  return map[String(m).toLowerCase()] || String(m);
}

function planCell(st) {
  if (!st) return `<span class="hint">—</span>`;
  const parts = [];
  if (st.unlimited) parts.push(`<span class="pill ok">无限</span>`);
  else if (st.membership) parts.push(`<span class="pill info">${esc(membershipLabel(st.membership))}</span>`);
  if (st.tierLabel) parts.push(`<span class="pill amount" title="Cursor 档位标签（非美元金额）">档 ${esc(st.tierLabel)}</span>`);
  if (st.teamId) parts.push(`<span class="pill idle">团队</span>`);
  return parts.length ? parts.join(" ") : `<span class="hint">—</span>`;
}

function render() {
  const tbody = $("rows");
  const shown = visibleAccounts();
  tbody.innerHTML = shown
    .map((a) => {
      const st = rowState[a.id];
      const title = accountTitle(a);
      const sub = accountSub(a);
      const checked = selected.has(a.id) ? " checked" : "";
      const active = a.active ? `<span class="pill info">本机</span>` : "";
      const groupName = String(a.group || "").trim();
      const groupPill = groupName ? ` <span class="pill pill-group">${esc(groupName)}</span>` : "";
      const noRefresh =
        a.hasRefresh === false
          ? ` <span class="pill idle pill-norefresh" title="未导入 refresh token，token 过期后需重新切号">无 refresh</span>`
          : "";
      return `<tr data-id="${esc(a.id)}" class="${a.active ? "is-active" : ""}">
        <td class="col-chk"><input type="checkbox" class="rowchk" data-id="${esc(a.id)}"${checked}${busy ? " disabled" : ""} /></td>
        <td>
          <div class="mail">${esc(title)} ${groupPill}${active}${noRefresh}</div>
          <div class="uid">${esc(sub)}</div>
        </td>
        <td>${planCell(st)}</td>
        <td>${statusCell(st)}</td>
        <td>${quotaCell(st)}</td>
        <td class="col-act">
          <button class="btn tiny" data-act="tag" data-id="${esc(a.id)}"${busy ? " disabled" : ""}>改名</button>
          <button class="btn tiny" data-act="detail" data-id="${esc(a.id)}"${busy ? " disabled" : ""}>详情</button>
          <button class="btn tiny primary" data-act="claim" data-id="${esc(a.id)}"${busy ? " disabled" : ""}>领取</button>
          <button class="btn tiny" data-act="switch" data-id="${esc(a.id)}"${busy ? " disabled" : ""}>切号</button>
          <button class="btn tiny" data-act="browser" data-id="${esc(a.id)}"${busy ? " disabled" : ""}>网页领取</button>
          <button class="btn tiny danger" data-act="remove" data-id="${esc(a.id)}"${busy ? " disabled" : ""}>移除</button>
        </td>
      </tr>`;
    })
    .join("");
  const empty = $("emptyHint");
  if (!accounts.length) {
    empty.hidden = false;
    empty.textContent = "还没有账号。粘贴 token 或导入 JSON 后点「添加到列表」。";
  } else if (!shown.length) {
    empty.hidden = false;
    empty.textContent = "当前分组没有账号。可换筛选，或点「改名」把账号放进该组。";
  } else {
    empty.hidden = true;
  }
  $("countPill").textContent = (groupFilter ? shown.length + "/" : "") + accounts.length + " 个";
  syncSelectAll();
  updateStats();
  previewSave();
}

function syncSelectAll() {
  const all = $("chkAll");
  if (!all) return;
  const rows = visibleAccounts();
  const n = rows.length;
  const sel = rows.filter((a) => selected.has(a.id)).length;
  all.checked = n > 0 && sel === n;
  all.indeterminate = sel > 0 && sel < n;
}

function updateStats() {
  let done = 0;
  for (const a of accounts) {
    const st = rowState[a.id];
    if (st && st.kind === "ok") done += 1;
  }
  if (accounts.length) setStatus(`${accounts.length} 个账号 · 已开通 ${done}`);
}

const SITE_RENT_URL = "https://infinity-site.cc-infinity.shop/";

async function openExternal(url) {
  const target = (url || "").trim();
  if (!target) return;
  const bridge = api();
  if (bridge && bridge.open_external_url) {
    try {
      const res = await bridge.open_external_url(target);
      if (res && res.ok) return;
      toast((res && res.error) || "无法打开链接");
      return;
    } catch (e) {
      toast("无法打开链接：" + String(e));
      return;
    }
  }
  window.open(target, "_blank", "noopener,noreferrer");
}

// 标记「处理中」时保留旧字段（额度等）并把稳定状态存到 baseKind/baseLabel，
// 这样查询失败或 unlocked 未知时能回退到之前的「已开通 / 需绑卡」。
function markRun(id) {
  const prev = rowState[id];
  if (!prev) {
    rowState[id] = { kind: "run" };
  } else if (prev.kind === "run") {
    rowState[id] = { ...prev };
  } else {
    rowState[id] = { ...prev, kind: "run", baseKind: prev.kind, baseLabel: prev.label };
  }
}

// 取某行的稳定状态（去掉 run 标记与 baseKind/baseLabel）；没有则返回 null。
function stableState(id) {
  const st = rowState[id];
  if (!st) return null;
  if (st.kind !== "run") return st;
  const { baseKind, baseLabel, ...rest } = st;
  return baseKind ? { ...rest, kind: baseKind, label: baseLabel } : null;
}

function applyClaim(id, res) {
  const prev = stableState(id) || {};
  // 只覆盖领取结果相关字段，额度字段（percent / apiSpendCents 等）保留。
  const { kind: _k, label: _l, teamId: _t, detail: _d, url: _u, ...keep } = prev;
  if (!res) {
    rowState[id] = { ...keep, kind: "bad", label: "无响应" };
    return;
  }
  applyEmail(id, res.email);
  if (res.outcome === "already") {
    // 只有 already 分支会带回 percent；为 null 时不要把旧的周用量抹掉。
    const pct = res.percent != null ? { percent: res.percent } : {};
    rowState[id] = { ...keep, kind: "ok", label: "已开通", ...pct, teamId: res.teamId };
  } else if (res.outcome === "activated") {
    rowState[id] = { ...keep, kind: "ok", label: "已开通" };
  } else if (res.outcome === "team_ok") {
    rowState[id] = { ...keep, kind: "ok", label: "团队已开通", teamId: res.teamId };
  } else if (res.outcome === "card_required") {
    rowState[id] = { ...keep, kind: "card", detail: res.detail || "需验证信用卡", url: res.url || "" };
  } else {
    rowState[id] = { ...keep, kind: "bad", label: "失败", detail: res.detail || "未知原因" };
  }
  schedulePersist();
}

// 依赖账期（billing period）的额度字段；后端拿不到账期时这些字段整体为 null。
const PERIOD_FIELDS = [
  "apiSpendCents",
  "autoSpendCents",
  "apiLimitCents",
  "autoLimitCents",
  "apiPercent",
  "autoPercent",
  "overageUsedCents",
  "overageLimitCents",
  "overageUnlimited",
  "periodSpendUsd",
  "totalPercent",
  "apiSpendDerived",
  "autoSpendDerived",
  "usageAvailable",
];

function applyStatus(id, res) {
  const prev = stableState(id);
  if (!res || res.error) {
    // 查询失败不能盖掉已知的「已开通 / 需绑卡」，只把错误写进 detail（pill 的 title 会显示）。
    const err = (res && res.error) || "";
    rowState[id] = prev ? { ...prev, detail: err || "查询失败" } : { kind: "bad", label: "查询失败", detail: err };
    return;
  }
  applyEmail(id, res.email);
  let kind = "idle";
  let label = "状态未知";
  if (res.unlocked === true) {
    kind = "ok";
    label = "已开通";
  } else if (res.unlocked === false) {
    if (prev && prev.kind === "card") {
      kind = "card";
      label = prev.label;
    } else {
      kind = "idle";
      label = "未开通";
    }
  } else if (prev) {
    // 后端 usage 失败时 unlocked 为 null：保留原状态。
    kind = prev.kind;
    label = prev.label;
  }
  const next = {
    ...(prev || {}),
    kind,
    label,
    percent: res.percent,
    nextReset: res.nextReset,
    periodStart: res.periodStart,
    teamId: res.teamId,
    membership: res.membership,
    unlimited: res.unlimited,
    tierLabel: res.tierLabel,
    spendUsd: res.spendUsd,
    teamPercent: res.teamPercent,
  };
  // 账期字段：usageAvailable 为 true 表示后端本次拿到了账期，null 才允许覆盖；
  // 否则（null/false）说明没拿到，缺失的字段保留列表里已有的值。
  const periodOk = res.usageAvailable === true;
  for (const k of PERIOD_FIELDS) {
    next[k] = res[k] != null || periodOk ? res[k] : prev ? prev[k] : undefined;
  }
  rowState[id] = next;
  schedulePersist();
}

async function claimOne(id) {
  markRun(id);
  render();
  let res;
  try {
    res = await api().claim_one(id);
    applyClaim(id, res);
  } catch (e) {
    applyClaim(id, { outcome: "error", detail: String(e) });
  }
  render();
  return res;
}

async function statusOne(id) {
  markRun(id);
  render();
  try {
    applyStatus(id, await api().status_one(id));
  } catch (e) {
    applyStatus(id, { error: String(e) });
  }
  render();
}

async function detectLocal() {
  toast("正在读取本机 Cursor 登录账号…");
  try {
    const res = await api().detect_local_account();
    if (!res || !res.ok) {
      toast("探测失败：" + ((res && res.error) || "未知原因"));
      return;
    }
    accounts = res.accounts || [];
    render();
    toast("已探测本机账号：" + (res.email || res.id || "本机"));
    if (res.id) statusOne(res.id);
  } catch (e) {
    toast("探测失败：" + String(e));
  }
}

let pendingSwitchId = "";
let detailAccountId = "";

function hideSwitch() {
  $("switchMask").hidden = true;
  pendingSwitchId = "";
}

function askSwitch(id) {
  if (busy) {
    toast("正在处理，请稍候");
    return;
  }
  const a = accounts.find((x) => x.id === id);
  const mail = (a && a.label) || id;
  pendingSwitchId = id;
  $("switchTarget").textContent = mail;
  const src = $("resetMidChk");
  const dest = $("switchResetMid");
  if (src && dest) dest.checked = !!src.checked;
  // list_accounts 可能不带 hasRefresh；只有明确为 false 才提示。
  const hint = $("switchRefreshHint");
  if (hint) hint.hidden = !(a && a.hasRefresh === false);
  $("switchMask").hidden = false;
}

async function confirmSwitch() {
  const id = pendingSwitchId;
  if (!id) return hideSwitch();
  if (busy) {
    toast("正在处理，请稍候");
    return;
  }
  const resetMid = !!($("switchResetMid") && $("switchResetMid").checked);
  const src = $("resetMidChk");
  if (src) src.checked = resetMid;
  hideSwitch();
  // 切号全程置 busy：表格按钮随 render 禁用，避免重复并发切号。
  busy = true;
  render();
  toast(resetMid ? "正在切号并重置机器码，Cursor 将自动重启…" : "正在切号，Cursor 将自动重启…");
  try {
    const res = await api().switch_account(id, resetMid);
    if (res && res.ok) {
      if (res.accounts) accounts = res.accounts;
      let msg = `已切换到 ${res.email || id}`;
      if (res.resetMachineId) msg += "（已重置机器码）";
      if (res.machineIdFileWritten === false) msg += "，但 machineid 文件写入失败";
      if (res.hasRefresh === false) msg += "（无 refresh，token 过期后需重新切号）";
      toast(msg, 4000);
    } else {
      toast("切号失败：" + ((res && res.error) || "未知原因"), 4000);
    }
  } catch (e) {
    toast("切号失败：" + String(e), 4000);
  } finally {
    busy = false;
    render();
  }
}

function hideDetail() {
  $("detailMask").hidden = true;
  detailAccountId = "";
}

function usageToneClass(percent) {
  const v = Number(percent) || 0;
  if (v >= 100) return "bad";
  if (v >= 80) return "warn";
  return "ok";
}

function renderDetail(data, loading) {
  const body = $("detailBody");
  if (loading) {
    body.textContent = "正在读取额度与模型用量…";
    return;
  }
  if (!data || !data.ok) {
    body.innerHTML = `<p class="detail-error">${esc((data && data.error) || "加载失败")}</p>`;
    return;
  }
  const st = data.status || {};
  const u = data.usage || {};
  const membership = data.membership || st.membership || "—";
  const validity = data.tokenExpired ? "已过期" : data.tokenExpiresAt ? "有效" : "未知";
  const validityCls = data.tokenExpired ? "bad" : data.tokenExpiresAt ? "ok" : "idle";
  const models = u.perModel || [];
  const maxCents = models.reduce((m, x) => Math.max(m, Number(x.totalCents) || 0), 0);
  const modelRows = models.length
    ? models
        .map((m) => {
          const cents = Number(m.totalCents) || 0;
          const w = maxCents > 0 ? (cents / maxCents) * 100 : 0;
          const tokens = (Number(m.inputTokens) || 0) + (Number(m.outputTokens) || 0);
          return `<div class="model-row">
            <div class="bar"><i style="width:${w}%"></i></div>
            <span class="mono">${esc(fmtCents(cents))}</span>
            <span class="model-name" title="${esc(m.modelIntent || "")}">${esc(m.modelIntent || "unknown")}${tokens ? " · " + tokens.toLocaleString() + " tok" : ""}</span>
          </div>`;
        })
        .join("")
    : `<p class="hint">${u.available ? "本周期暂无按模型明细" : "用量接口暂不可用"}</p>`;
  const cur = stableState(data.id);
  let sandSt;
  if (st.unlocked === true) sandSt = { kind: "ok", label: "已开通" };
  else if (st.unlocked === false) sandSt = cur && cur.kind === "card" ? cur : { kind: "idle", label: "未开通" };
  else sandSt = cur || { kind: "idle", label: "状态未知" };
  // 后端拿不到精确花费、按百分比反推金额时标「(估)」。
  const estTag = (flag) => (flag ? ` <small class="est-tag" title="按百分比反推">(估)</small>` : "");
  body.innerHTML = `
    <div class="detail-row"><span>邮箱</span><strong>${esc(data.email || "")}</strong></div>
    <div class="detail-row"><span>套餐</span><span class="pill info">${esc(membershipLabel(membership) || membership)}</span>${data.active ? ' <span class="pill info">本机</span>' : ""}</div>
    <div class="detail-row"><span>Token</span><code class="token-preview">${esc(data.tokenPreview || "—")}</code> <span class="pill ${validityCls}">${esc(validity)}</span></div>
    <div class="detail-row"><span>Sand</span>${statusCell(sandSt)}</div>
    <div class="quota-glance">
      <div><span>API</span><strong>${esc(fmtCents(u.apiSpendCents ?? st.apiSpendCents))}${estTag(u.apiSpendDerived ?? st.apiSpendDerived)}</strong><em>${esc(fmtPercent(u.apiPercent ?? st.apiPercent))}</em></div>
      <div><span>Auto</span><strong>${esc(fmtCents(u.autoSpendCents ?? st.autoSpendCents))}${estTag(u.autoSpendDerived ?? st.autoSpendDerived)}</strong><em>${esc(fmtPercent(u.autoPercent ?? st.autoPercent))}</em></div>
      <div><span>超额</span><strong>${esc(fmtCents(u.overageUsedCents ?? st.overageUsedCents))}</strong><em>${u.overageUnlimited ? "无限" : esc(fmtCents(u.overageLimitCents ?? st.overageLimitCents))}</em></div>
    </div>
    ${quotaBar(u.apiPercent ?? st.apiPercent, u.apiSpendCents ?? st.apiSpendCents, u.apiLimitCents ?? st.apiLimitCents, "API")}
    ${quotaBar(u.autoPercent ?? st.autoPercent, u.autoSpendCents ?? st.autoSpendCents, u.autoLimitCents ?? st.autoLimitCents, "Auto")}
    ${st.percent != null ? `<div class="hint">Bot 周用量 ${esc(fmtPercent(st.percent))}</div><div class="bar ${usageToneClass(st.percent)}"><i style="width:${Math.min(100, Math.max(0, Number(st.percent) || 0))}%"></i></div>` : ""}
    <h3 class="detail-sub">按模型花费</h3>
    <div class="model-list">${modelRows}</div>
    ${u.error ? `<p class="detail-error">${esc(u.error)}</p>` : ""}
  `;
  applyStatus(data.id, st);
}

// 请求代次：先开 A 再开 B 时，A 的晚到响应必须丢弃，否则会画错并污染 rowState[A]。
let detailSeq = 0;

async function openDetail(id) {
  if (busy) {
    toast("正在处理，请稍候");
    return;
  }
  const seq = ++detailSeq;
  detailAccountId = id;
  $("detailMask").hidden = false;
  renderDetail(null, true);
  let data;
  try {
    data = await api().account_detail(id);
  } catch (e) {
    data = { ok: false, error: String(e) };
  }
  if (seq !== detailSeq || detailAccountId !== id) return;
  renderDetail(data, false);
  if (data && data.ok) render();
}

async function openLogin(id) {
  toast("正在打开浏览器并注入登录，请稍候…");
  try {
    const res = await api().open_login(id);
    if (res && res.ok) {
      toast(`已在 ${res.browser === "edge" ? "Edge" : "Chrome"} 打开领取页，请在浏览器里手动完成`);
    } else {
      toast("打开失败：" + ((res && res.error) || "未知原因"));
    }
  } catch (e) {
    toast("打开失败：" + String(e));
  }
}

function targetIds() {
  // 有勾选就只处理勾选的，否则处理全部。
  return selected.size ? accounts.filter((a) => selected.has(a.id)).map((a) => a.id) : accounts.map((a) => a.id);
}

function readConcurrency() {
  const el = $("concInput");
  let n = parseInt(el && el.value, 10);
  if (isNaN(n)) n = 3;
  return Math.min(10, Math.max(1, n));
}

async function runBatch(kind) {
  if (busy || accounts.length === 0) return;
  const ids = targetIds();
  if (ids.length === 0) {
    toast("没有可处理的账号");
    return;
  }
  const conc = readConcurrency();
  busy = true;
  render();
  const wrap = $("progressWrap");
  const bar = $("progressBar");
  const text = $("progressText");
  wrap.hidden = false;
  const total = ids.length;
  const label = kind === "claim" ? "领取" : "刷新";
  let done = 0;
  let next = 0;
  bar.style.width = "0%";
  text.textContent = `${label} 0/${total}（并发 ${conc}）`;

  async function worker() {
    while (next < ids.length) {
      const id = ids[next++];
      markRun(id);
      render();
      try {
        if (kind === "claim") applyClaim(id, await api().claim_one(id));
        else applyStatus(id, await api().status_one(id));
      } catch (e) {
        if (kind === "claim") applyClaim(id, { outcome: "error", detail: String(e) });
        else applyStatus(id, { error: String(e) });
      }
      done += 1;
      bar.style.width = ((done / total) * 100).toFixed(1) + "%";
      text.textContent = `${label} ${done}/${total}（并发 ${conc}）`;
      render();
    }
  }

  const workers = [];
  for (let i = 0; i < Math.min(conc, total); i++) workers.push(worker());
  await Promise.all(workers);

  bar.style.width = "100%";
  text.textContent = `完成 ${done}/${total}`;
  busy = false;
  render();
  setTimeout(() => (wrap.hidden = true), 1500);
  toast(`${label}完成：${total} 个${selected.size ? "（仅选中）" : ""}`);
}

async function importFiles() {
  const res = await api().import_files();
  accounts = res.accounts || [];
  render();
  toast(res.added ? `导入 ${res.added} 个账号` : "未识别到账号");
}

async function addText() {
  const text = $("tokenInput").value.trim();
  if (!text) {
    toast("先粘贴 token 或 JSON");
    return;
  }
  const res = await api().import_text(text);
  accounts = res.accounts || [];
  $("tokenInput").value = "";
  render();
  toast(res.added ? `添加 ${res.added} 个账号` : "未识别到有效 token");
}

async function clearAll() {
  accounts = await api().clear_accounts();
  for (const k of Object.keys(rowState)) delete rowState[k];
  selected.clear();
  api().save_status({});
  render();
  toast("已清空");
}

function renderGroupList() {
  const ul = $("groupList");
  if (!ul) return;
  if (!groups.length) {
    ul.innerHTML = `<li class="hint">还没有分组。在上方输入名称后点「新建」。</li>`;
    return;
  }
  ul.innerHTML = groups
    .map(
      (g) => `<li>
        <span class="g-name">${esc(g)}</span>
        <button class="btn tiny" type="button" data-gact="rename" data-name="${esc(g)}">重命名</button>
        <button class="btn tiny danger" type="button" data-gact="remove" data-name="${esc(g)}">删除</button>
      </li>`
    )
    .join("");
}

function openTag(id) {
  const a = accounts.find((x) => x.id === id);
  if (!a) return;
  tagAccountId = id;
  $("tagTarget").textContent = accountSub(a);
  $("tagNameInput").value = a.label && a.label !== a.id ? a.label : "";
  fillGroupSelect($("tagGroupSelect"), a.group || "");
  $("tagMask").hidden = false;
  const input = $("tagNameInput");
  if (input) input.focus();
}

function hideTag() {
  $("tagMask").hidden = true;
  tagAccountId = null;
}

async function saveTag() {
  const id = tagAccountId;
  if (!id) return hideTag();
  const name = $("tagNameInput").value.trim();
  const group = $("tagGroupSelect").value;
  const bridge = api();
  try {
    if (bridge && bridge.set_label) {
      const res = await bridge.set_label(id, name);
      if (res && res.accounts) accounts = res.accounts;
    } else {
      const a = accounts.find((x) => x.id === id);
      if (a) a.label = name;
    }
  } catch (e) {
    toast("保存名称失败：" + String(e));
    return;
  }
  await assignGroup(id, group);
  hideTag();
  toast("已保存标签");
}

async function assignGroup(id, group) {
  const bridge = api();
  if (bridge && bridge.set_group) {
    const res = await bridge.set_group(id, group || "");
    if (res && res.accounts) accounts = res.accounts;
    if (res && res.groups) groups = res.groups;
  } else {
    const a = accounts.find((x) => x.id === id);
    if (a) a.group = group || "";
    if (group && !groups.includes(group)) groups.push(group);
  }
  fillGroupFilter();
  render();
}

function openGroups() {
  renderGroupList();
  $("groupMask").hidden = false;
}

function hideGroups() {
  $("groupMask").hidden = true;
}

async function addGroup() {
  const name = $("groupNewInput").value.trim();
  if (!name) {
    toast("先填写分组名");
    return;
  }
  const bridge = api();
  if (bridge && bridge.add_group) {
    const res = await bridge.add_group(name);
    if (!res || !res.ok) {
      toast((res && res.error) || "新建失败");
      return;
    }
    groups = res.groups || groups;
    if (res.accounts) accounts = res.accounts;
  } else if (!groups.includes(name)) {
    groups.push(name);
  }
  $("groupNewInput").value = "";
  fillGroupFilter();
  renderGroupList();
  render();
  toast("已新建分组");
}

async function renameGroup(old) {
  const next = window.prompt("新的分组名称", old);
  if (next == null) return;
  const name = String(next).trim();
  if (!name) {
    toast("名称不能为空");
    return;
  }
  const bridge = api();
  if (bridge && bridge.rename_group) {
    const res = await bridge.rename_group(old, name);
    if (!res || !res.ok) {
      toast((res && res.error) || "重命名失败");
      return;
    }
    groups = res.groups || groups;
    if (res.accounts) accounts = res.accounts;
  } else {
    groups = groups.map((g) => (g === old ? name : g));
    accounts.forEach((a) => {
      if (a.group === old) a.group = name;
    });
  }
  if (groupFilter === old) groupFilter = name;
  fillGroupFilter();
  renderGroupList();
  render();
}

async function removeGroup(name) {
  if (!window.confirm(`删除分组「${name}」？其中的账号会变为未分组，账号本身不会被删除。`)) return;
  const bridge = api();
  if (bridge && bridge.remove_group) {
    const res = await bridge.remove_group(name);
    groups = (res && res.groups) || groups.filter((g) => g !== name);
    if (res && res.accounts) accounts = res.accounts;
  } else {
    groups = groups.filter((g) => g !== name);
    accounts.forEach((a) => {
      if (a.group === name) a.group = "";
    });
  }
  if (groupFilter === name) groupFilter = "";
  fillGroupFilter();
  renderGroupList();
  render();
}

function onTableClick(e) {
  const btn = e.target.closest("button[data-act]");
  if (!btn || busy) return;
  const id = btn.getAttribute("data-id");
  const act = btn.getAttribute("data-act");
  if (act === "remove") {
    api()
      .remove_account(id)
      .then((list) => {
        accounts = list || [];
        delete rowState[id];
        selected.delete(id);
        schedulePersist();
        render();
      });
  } else if (act === "browser") {
    openLogin(id);
  } else if (act === "switch") {
    askSwitch(id);
  } else if (act === "detail") {
    openDetail(id);
  } else if (act === "claim") {
    claimOne(id);
  } else if (act === "tag") {
    openTag(id);
  }
}

function onTableChange(e) {
  const chk = e.target.closest("input.rowchk");
  if (!chk) return;
  const id = chk.getAttribute("data-id");
  if (chk.checked) selected.add(id);
  else selected.delete(id);
  syncSelectAll();
}

function onSelectAll(e) {
  const rows = visibleAccounts();
  if (e.target.checked) rows.forEach((a) => selected.add(a.id));
  else rows.forEach((a) => selected.delete(a.id));
  render();
}

async function refreshPatch() {
  const pill = $("patchPill");
  const info = $("patchInfo");
  const detail = $("patchDetail");
  const adminHint = $("patchAdminHint");
  const bridge = api();
  if (!bridge || !bridge.patch_status) {
    pill.className = "pill idle";
    pill.textContent = "未连接";
    info.textContent = "尚未连接到本机服务，请稍候或重开软件。";
    return;
  }
  pill.className = "pill idle";
  pill.textContent = "检测中…";
  // inspect_status 要扫描 Cursor 安装目录里上百 MB 的 JS，首次可能要几十秒。
  info.textContent = "正在扫描 Cursor 安装目录（首次约 10-60 秒）…";
  detail.hidden = true;
  detail.innerHTML = "";
  adminHint.hidden = true;
  let res;
  try {
    res = await bridge.patch_status();
  } catch (e) {
    pill.className = "pill bad";
    pill.textContent = "检测失败";
    info.textContent = "检测失败：" + String(e);
    setStatus(info.textContent);
    return;
  }
  if (!res || !res.ok) {
    pill.className = "pill bad";
    pill.textContent = "未检测到 Cursor";
    info.textContent = (res && res.error) || "未找到本机 Cursor 安装。";
    setStatus(info.textContent);
    if (res && res.needsElevation) {
      adminHint.hidden = false;
      adminHint.textContent = "打补丁需管理员权限；点「打补丁」将自动请求 UAC。";
    }
    return;
  }
  const installed = !!res.installed;
  const streamOk = !!res.streamOk;
  const ideLeft = Number(res.ideLeft || 0);
  const externalMarkers = Number(res.externalMarkers || 0);
  // 判定与 patch_status.bat 一致：已安装且 Stream 完整、无 IDE 残留、无外部标记才算完整。
  const verdictOk = res.verdict ? res.verdict === "OK" : streamOk && ideLeft === 0 && externalMarkers === 0;
  if (!installed) {
    pill.className = "pill idle";
    pill.textContent = "未打补丁";
  } else if (verdictOk) {
    pill.className = "pill ok";
    pill.textContent = "补丁完整";
  } else {
    pill.className = "pill warn";
    pill.textContent = "补丁不完整";
  }
  info.textContent = `Cursor ${res.version || "?"} · ${res.path || ""}${res.toolVersion ? ` · 补丁工具 v${res.toolVersion}` : ""}`;
  setStatus(info.textContent);
  const compat = $("patchCompat");
  if (compat) {
    const versions = Array.isArray(res.supportedVersions) && res.supportedVersions.length
      ? res.supportedVersions.join(" / ")
      : "3.17.21 / 3.18.9 / 3.18.25 / 3.19.7";
    compat.textContent = `适配 Cursor ${versions}（按本机版本自动选锚点，旧版不卸）`;
  }
  const verLabel = $("appVersionLabel");
  if (verLabel && res.toolVersion) verLabel.textContent = res.toolVersion;
  const lines = [];
  const s = res.stream || {};
  if (installed) {
    lines.push(
      `<li class="${streamOk ? "ok" : "warn"}">Stream / 工具调用：${
        streamOk ? "就绪（含 move_exec → Agent 工具执行）" : "未完整（需重新打补丁）"
      }</li>`
    );
    if (!streamOk) {
      lines.push(
        `<li class="warn">标记：route=${s.route || 0} runtime=${s.runtime || 0} moveExec=${s.moveExec || 0} execBridge=${s.execBridge || 0} direct=${s.direct || 0}</li>`
      );
    }
    if (ideLeft > 0) {
      lines.push(`<li class="warn">残留 IDE 匹配 ${ideLeft} 处（需重新打补丁）</li>`);
    }
    if (externalMarkers > 0) {
      lines.push(`<li class="warn">检测到其他工具留下的标记 ${externalMarkers} 处</li>`);
    }
  }
  const dns = res.dns || {};
  const dnsLineClass = dns.hijacked && !dns.hostsInstalled ? "bad" : dns.ready ? "ok" : "warn";
  lines.push(
    `<li class="${dnsLineClass}">DNS：${
      dns.hijacked
        ? `疑似劫持（系统 ${dns.systemIp || "?"} ≠ DoH ${dns.dohIp || "?"}）`
        : "解析正常"
    } · hosts ${dns.hostsInstalled ? "已修复" : "未写入"} · Node 注入 ${dns.nodeMarkers || 0} 处</li>`
  );
  if (lines.length) {
    detail.innerHTML = lines.join("");
    detail.hidden = false;
  }
  if (res.needsElevation) {
    adminHint.hidden = false;
    adminHint.textContent = "当前非管理员；打补丁 / 修复 DNS 将弹出 UAC（与 patch_install.bat 相同逻辑）。";
  } else if (res.admin) {
    adminHint.hidden = false;
    adminHint.textContent = "已具备管理员权限，补丁将直接写入本机 Cursor。";
  }
  const btnDns = $("btnDnsFix");
  if (btnDns) btnDns.disabled = !!(dns.hostsInstalled && !dns.hijacked);
}

function setPatchBusy(busy) {
  $("btnPatch").disabled = busy;
  $("btnRestore").disabled = busy;
  const btnDns = $("btnDnsFix");
  if (btnDns) btnDns.disabled = busy;
  const btnReport = $("btnPatchReport");
  if (btnReport) btnReport.disabled = busy;
}

// 把后端返回的 {text, tone} 状态行（等价脚本 print_banner）渲染进补丁卡片的详情列表。
function renderPatchLines(lines) {
  const detail = $("patchDetail");
  if (!Array.isArray(lines) || !lines.length) return;
  const cls = { ok: "ok", warn: "warn", bad: "bad", info: "info" };
  detail.innerHTML = lines
    .map((l) => `<li class="${cls[l.tone] || ""}">${esc(l.text || "")}</li>`)
    .join("");
  detail.hidden = false;
}

// 失败时：toast 报错，并把后端 hint 写进管理员提示区。
function showPatchFailure(prefix, res) {
  toast(prefix + ((res && res.error) || ""));
  const adminHint = $("patchAdminHint");
  if (res && res.hint) {
    adminHint.hidden = false;
    adminHint.textContent = res.hint;
  }
}

// 补丁 / 回退共用：桥接异常也要恢复按钮；失败提示必须在 refreshPatch 之后写，否则会被它清掉。
async function runPatchAction(call, startMsg, okMsg, failPrefix) {
  setPatchBusy(true);
  toast(startMsg);
  let res;
  try {
    res = await call();
  } catch (e) {
    res = { ok: false, error: String(e) };
  } finally {
    setPatchBusy(false);
  }
  try {
    await refreshPatch();
  } catch (e) {
    /* 状态刷新失败不影响结果提示 */
  }
  if (res && res.ok) {
    toast(okMsg(res), 4000);
    renderPatchLines(res.lines);
  } else {
    showPatchFailure(failPrefix, res);
  }
}

async function doPatch() {
  await runPatchAction(
    () => api().apply_patch(),
    "正在打补丁（含 DNS + 工具调用链路），可能弹出 UAC…",
    (res) => (res.verdict === "OK" ? "补丁完成，请完全退出后重开 Cursor 再对话" : "补丁已写入但状态不完整，请查看补丁情况"),
    "打补丁失败："
  );
}

async function doRestore() {
  await runPatchAction(
    () => api().restore_patch(),
    "正在回退补丁，可能弹出 UAC…",
    () => "已回退，Cursor 将自动重启",
    "回退失败："
  );
}

function hideReport() {
  $("reportMask").hidden = true;
}

function renderReport(data) {
  const pre = $("reportText");
  const pill = $("reportVerdict");
  if (!data || !data.ok) {
    pill.className = "pill bad";
    pill.textContent = "检测失败";
    pre.textContent = (data && data.error) || "未找到本机 Cursor 安装。";
    return;
  }
  const ok = data.verdict === "OK";
  const notInstalled = data.verdict === "NOT_INSTALLED";
  if (notInstalled) {
    pill.className = "pill idle";
    pill.textContent = "status: NOT_INSTALLED";
  } else {
    pill.className = ok ? "pill ok" : "pill warn";
    pill.textContent = ok ? "status: OK" : "status: INCOMPLETE";
  }
  const rows = Array.isArray(data.rows) ? data.rows : [];
  const lines = Array.isArray(data.lines) ? data.lines : [];
  const html = rows.map(([k, v]) => `${esc(k)}: ${esc(v)}`);
  const verdictClass = ok ? "ok" : notInstalled ? "info" : "warn";
  html.push(`<span class="${verdictClass}">status: ${esc(data.verdict || "")}</span>`);
  html.push("");
  lines.forEach((l) => html.push(`<span class="${esc(l.tone || "info")}">${esc(l.text || "")}</span>`));
  pre.innerHTML = html.join("\n");
  pre.dataset.plain = data.text || "";
}

async function openReport() {
  const mask = $("reportMask");
  const pill = $("reportVerdict");
  const pre = $("reportText");
  mask.hidden = false;
  pill.className = "pill idle";
  pill.textContent = "检测中…";
  pre.textContent = "正在检测（需扫描 Cursor 安装目录，可能要几十秒）…";
  pre.dataset.plain = "";
  const bridge = api();
  let data;
  try {
    data = bridge.patch_report ? await bridge.patch_report() : { ok: false, error: "当前版本不支持" };
  } catch (e) {
    data = { ok: false, error: String(e) };
  }
  renderReport(data);
}

async function copyReport() {
  const pre = $("reportText");
  const text = pre.dataset.plain || pre.textContent || "";
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    toast("已复制补丁情况");
  } catch (e) {
    // pywebview 下 clipboard API 可能不可用，退回 textarea + execCommand。
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const done = document.execCommand && document.execCommand("copy");
    document.body.removeChild(ta);
    toast(done ? "已复制补丁情况" : "复制失败，请手动选择文本复制");
  }
}

async function doDnsFix() {
  const bridge = api();
  await runPatchAction(
    () => (bridge.apply_dns_fix ? bridge.apply_dns_fix() : Promise.resolve({ ok: false, error: "当前版本不支持" })),
    "正在写入 hosts DNS 修复，可能弹出 UAC…",
    () => "DNS hosts 已修复",
    "DNS 修复失败："
  );
}

function showHelp() {
  $("helpMask").hidden = false;
}

function hideHelp() {
  $("helpMask").hidden = true;
  if ($("helpHide").checked) {
    const bridge = api();
    if (bridge && bridge.set_settings) {
      bridge.get_settings().then((s) => {
        bridge.set_settings({ ...(s || {}), hideHelp: true });
      });
    }
  }
}

async function doSetPath() {
  const path = $("cursorPathInput").value.trim();
  toast("正在设置 Cursor 路径…");
  try {
    const res = await api().set_cursor_path(path);
    toast(res && res.ok ? (path ? "已设置路径" : "已恢复自动检测") : "设置失败：" + ((res && res.error) || "路径无效"));
  } catch (e) {
    toast("设置失败：" + String(e));
  }
  refreshPatch();
}

async function boot() {
  $("btnDetectLocal").addEventListener("click", detectLocal);
  $("btnImportFile").addEventListener("click", importFiles);
  $("btnAddText").addEventListener("click", addText);
  $("btnClear").addEventListener("click", clearAll);
  $("btnClaimAll").addEventListener("click", () => runBatch("claim"));
  $("btnRefresh").addEventListener("click", () => runBatch("status"));
  $("btnPatch").addEventListener("click", doPatch);
  $("btnRestore").addEventListener("click", doRestore);
  const btnDnsFix = $("btnDnsFix");
  if (btnDnsFix) btnDnsFix.addEventListener("click", doDnsFix);
  $("btnSetPath").addEventListener("click", doSetPath);
  $("switchOk").addEventListener("click", confirmSwitch);
  $("detailRefresh").addEventListener("click", () => {
    if (detailAccountId && !busy) openDetail(detailAccountId);
  });
  $("detailSwitch").addEventListener("click", () => {
    // hideDetail() 会清空 detailAccountId，必须先取出再关闭。
    const id = detailAccountId;
    if (!id) return;
    hideDetail();
    askSwitch(id);
  });
  $("resetMidChk").addEventListener("change", () => {
    const bridge = api();
    if (bridge && bridge.set_settings) {
      bridge.get_settings().then((s) => {
        bridge.set_settings({ ...(s || {}), resetMachineId: !!$("resetMidChk").checked });
      });
    }
  });
  refreshPatch();

  try {
    const [list, status, groupNames] = await Promise.all([
      api().list_accounts(),
      api().load_status(),
      api().list_groups ? api().list_groups() : Promise.resolve([]),
    ]);
    accounts = list || [];
    groups = Array.isArray(groupNames) ? groupNames : [];
    fillGroupFilter();
    if (status) {
      const ids = new Set(accounts.map((a) => a.id));
      for (const [id, st] of Object.entries(status)) {
        if (ids.has(id)) rowState[id] = st;
      }
    }
    render();
  } catch (e) {
    render();
  }

  try {
    const s = await api().get_settings();
    if (s && s.resetMachineId && $("resetMidChk")) $("resetMidChk").checked = true;
    if (!s || !s.hideHelp) showHelp();
  } catch (e) {
    showHelp();
  }
}

function greetingLabel(d = new Date()) {
  const h = d.getHours();
  if (h < 11) return "早安";
  if (h < 18) return "午安";
  return "晚安";
}

function formatGreetDate(d = new Date()) {
  return d.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "short",
  });
}

function setActiveNav(id) {
  document.querySelectorAll(".nav-item[data-nav]").forEach((el) => {
    el.classList.toggle("is-active", el.getAttribute("data-nav") === id);
  });
}

function openReportPreview() {
  const mask = $("reportMask");
  const pill = $("reportVerdict");
  const pre = $("reportText");
  mask.hidden = false;
  pill.className = "pill idle";
  pill.textContent = "预览";
  pre.textContent = "静态预览：应用内会在此显示与 patch_status.bat 相同的补丁情况报告。";
  pre.dataset.plain = pre.textContent;
}

function seedPreview() {
  try {
    const raw = localStorage.getItem("infinity-preview-store");
    if (raw) {
      const data = JSON.parse(raw);
      if (Array.isArray(data.accounts) && data.accounts.length) {
        accounts = data.accounts;
        groups = Array.isArray(data.groups) ? data.groups : [];
        Object.assign(rowState, data.rowState || {});
        fillGroupFilter();
        render();
        setStatus("静态预览（已恢复本地标签/分组）");
        return;
      }
    }
  } catch (e) {
    /* ignore */
  }
  accounts = [
    { id: "user_preview_01", label: "演示号", email: "demo@example.com", group: "测试", active: true, hasRefresh: false },
    { id: "user_preview_02", label: "", email: "work@example.com", group: "", hasRefresh: true },
  ];
  groups = ["测试", "工作"];
  rowState.user_preview_01 = {
    kind: "ok",
    label: "已开通",
    membership: "pro",
    percent: 18.4,
    apiPercent: 12,
    autoPercent: 6,
  };
  fillGroupFilter();
  render();
  setStatus("静态预览");
}

function initChrome() {
  const tag = $("greetTag");
  if (tag) tag.textContent = greetingLabel();
  const dateEl = $("greetDate");
  if (dateEl) dateEl.textContent = formatGreetDate();

  document.querySelectorAll("[data-nav]").forEach((el) => {
    el.addEventListener("click", (e) => {
      const id = el.getAttribute("data-nav");
      const target = document.getElementById(id);
      if (!target) return;
      e.preventDefault();
      target.scrollIntoView({ behavior: "smooth", block: "start" });
      setActiveNav(id);
    });
  });

  const stack = document.querySelector(".stack");
  const sections = ["cardWelcome", "patchCard", "importCard", "accountCard"]
    .map((id) => document.getElementById(id))
    .filter(Boolean);
  if (stack && "IntersectionObserver" in window && sections.length) {
    const io = new IntersectionObserver(
      (entries) => {
        const vis = entries
          .filter((x) => x.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (vis && vis.target && vis.target.id) setActiveNav(vis.target.id);
      },
      { root: stack, threshold: 0.28 }
    );
    sections.forEach((s) => io.observe(s));
  }

  const btnHelp = $("btnHelp");
  if (btnHelp) btnHelp.addEventListener("click", showHelp);
  if ($("helpOk")) $("helpOk").addEventListener("click", hideHelp);
  const btnRent = $("btnRentPlatform");
  if (btnRent) btnRent.addEventListener("click", () => openExternal(SITE_RENT_URL));
  document.querySelectorAll("a.ext-link").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.preventDefault();
      openExternal(el.getAttribute("data-url") || el.getAttribute("href"));
    });
  });
  if ($("reportClose")) $("reportClose").addEventListener("click", hideReport);
  if ($("reportMask")) {
    $("reportMask").addEventListener("click", (e) => {
      if (e.target === $("reportMask")) hideReport();
    });
  }
  if ($("reportCopy")) $("reportCopy").addEventListener("click", copyReport);
  if ($("reportRefresh")) {
    $("reportRefresh").addEventListener("click", () => {
      if (api()) openReport();
    });
  }
  if ($("btnPatchReport")) {
    $("btnPatchReport").addEventListener("click", () => {
      if (api()) openReport();
      else openReportPreview();
    });
  }
  if ($("rows")) {
    $("rows").addEventListener("click", onTableClick);
    $("rows").addEventListener("change", onTableChange);
  }
  if ($("chkAll")) $("chkAll").addEventListener("change", onSelectAll);
  if ($("groupFilter")) {
    $("groupFilter").addEventListener("change", () => {
      groupFilter = $("groupFilter").value;
      render();
    });
  }
  if ($("btnGroups")) $("btnGroups").addEventListener("click", openGroups);
  if ($("groupClose")) $("groupClose").addEventListener("click", hideGroups);
  if ($("groupAdd")) $("groupAdd").addEventListener("click", addGroup);
  if ($("groupNewInput")) {
    $("groupNewInput").addEventListener("keydown", (e) => {
      if (e.key === "Enter") addGroup();
    });
  }
  if ($("groupList")) {
    $("groupList").addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-gact]");
      if (!btn) return;
      const name = btn.getAttribute("data-name") || "";
      if (btn.getAttribute("data-gact") === "rename") renameGroup(name);
      else if (btn.getAttribute("data-gact") === "remove") removeGroup(name);
    });
  }
  if ($("tagOk")) $("tagOk").addEventListener("click", saveTag);
  if ($("tagCancel")) $("tagCancel").addEventListener("click", hideTag);
  if ($("tagNameInput")) {
    $("tagNameInput").addEventListener("keydown", (e) => {
      if (e.key === "Enter") saveTag();
    });
  }
  if ($("tagMask")) {
    $("tagMask").addEventListener("click", (e) => {
      if (e.target === $("tagMask")) hideTag();
    });
  }
  if ($("groupMask")) {
    $("groupMask").addEventListener("click", (e) => {
      if (e.target === $("groupMask")) hideGroups();
    });
  }

  // 关闭类操作不依赖 Python 侧，放在这里绑定：即使后端未就绪或初始化失败，弹层也关得掉。
  if ($("detailClose")) $("detailClose").addEventListener("click", hideDetail);
  if ($("detailMask")) {
    $("detailMask").addEventListener("click", (e) => {
      if (e.target === $("detailMask")) hideDetail();
    });
  }
  if ($("switchCancel")) $("switchCancel").addEventListener("click", hideSwitch);
  if ($("switchMask")) {
    $("switchMask").addEventListener("click", (e) => {
      if (e.target === $("switchMask")) hideSwitch();
    });
  }
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    hideDetail();
    hideSwitch();
    hideTag();
    hideGroups();
    hideReport();
  });
}

let booted = false;

function bootOnce() {
  if (booted) return;
  booted = true;
  boot().catch((e) => {
    setStatus("初始化失败：" + String(e));
    toast("初始化失败：" + String(e), 6000);
  });
}

// pywebviewready 可能在本脚本执行前就已派发（Edge WebView2 注入时机不定），
// 只靠事件监听会永远等不到 → boot 不跑 → 补丁检测卡在「检测中」、弹层按钮全部未绑定。
// 因此事件与轮询并存；只有确认等不到 API 才退回静态预览，避免把预览假账号灌进真实应用。
function waitForApi(timeoutMs = 20000) {
  const started = Date.now();
  const tick = () => {
    if (window.pywebview && window.pywebview.api) {
      bootOnce();
      return;
    }
    if (Date.now() - started > timeoutMs) {
      if (!booted) seedPreview();
      return;
    }
    setTimeout(tick, 100);
  };
  tick();
}

window.addEventListener("pywebviewready", bootOnce);
initChrome();
waitForApi();

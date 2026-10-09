const $ = (sel) => document.querySelector(sel);

const state = {
  items: [],
  picked: new Set(),
};

function setStatus(msg, isError = false) {
  const el = $("#status");
  el.textContent = msg || "";
  el.classList.toggle("error", Boolean(isError));
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || `请求失败 ${res.status}`);
  }
  return data;
}

function trackLabel(track) {
  if (track === "conflict") return "冲突";
  if (track === "warm") return "温馨";
  return track || "其它";
}

function mediaUrl(rel) {
  return `/media/${rel.split("/").map(encodeURIComponent).join("/")}`;
}

function renderItem(it) {
  const id = Number(it.id);
  const checked = state.picked.has(id) ? "checked" : "";
  const imgs = it.local_images || [];
  const thumb = imgs.length
    ? `<img class="thumb" src="${mediaUrl(imgs[0])}" alt="" loading="lazy" />`
    : `<div class="thumb-empty">${it.need_manual ? "需手补素材" : "暂无本地图"}</div>`;
  const badge = it.need_manual ? `<span class="badge">需手补</span>` : "";
  return `
    <label class="item">
      <input type="checkbox" data-id="${id}" ${checked} />
      ${thumb}
      <div>
        <h3>【${trackLabel(it.track)}】${escapeHtml(it.title || "")}</h3>
        <p class="summary">${escapeHtml(it.summary || "（无摘要）")}</p>
        <div class="foot">
          <span>${escapeHtml(it.source_name || "")}</span>
          <span>${formatTime(it.published_at)}</span>
          ${badge}
          ${it.link ? `<a href="${escapeAttr(it.link)}" target="_blank" rel="noopener">原文</a>` : ""}
        </div>
      </div>
    </label>
  `;
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function escapeAttr(s) {
  return escapeHtml(s).replaceAll("'", "&#39;");
}

function formatTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleString("zh-CN", { hour12: false });
  } catch {
    return iso;
  }
}

function renderLists() {
  const conflict = state.items.filter((x) => x.track === "conflict");
  const warm = state.items.filter((x) => x.track === "warm");
  const other = state.items.filter((x) => x.track !== "conflict" && x.track !== "warm");

  const cEl = $("#conflict-list");
  const wEl = $("#warm-list");
  cEl.innerHTML = conflict.length
    ? `<p class="track-label conflict">冲突 · ${conflict.length}</p>${conflict.map(renderItem).join("")}`
    : "";
  wEl.innerHTML =
    (warm.length ? `<p class="track-label warm">温馨 · ${warm.length}</p>${warm.map(renderItem).join("")}` : "") +
    (other.length ? `<p class="track-label">其它 · ${other.length}</p>${other.map(renderItem).join("")}` : "");

  $("#empty-hint").hidden = state.items.length > 0;
  $("#pick-count").textContent = `已选 ${state.picked.size} 条`;

  document.querySelectorAll('input[type="checkbox"][data-id]').forEach((box) => {
    box.addEventListener("change", () => {
      const id = Number(box.dataset.id);
      if (box.checked) state.picked.add(id);
      else state.picked.delete(id);
      $("#pick-count").textContent = `已选 ${state.picked.size} 条`;
    });
  });
}

function renderResult(data) {
  const panel = $("#result-panel");
  if (!data || !data.has_result && !data.script_douyin) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  $("#script-douyin").textContent = data.script_douyin || "";
  $("#note-xhs").textContent = data.note_xhs || "";

  const mediaEl = $("#result-media");
  const media = data.media || [];
  if (!media.length) {
    mediaEl.innerHTML = `<p class="hint">暂无素材清单</p>`;
    return;
  }
  mediaEl.innerHTML = media
    .map((m) => {
      const imgs = m.local_images || [];
      const imgHtml = imgs.length
        ? imgs.map((rel) => `<img src="${mediaUrl(rel)}" alt="" loading="lazy" />`).join("")
        : `<div class="thumb-empty">${m.need_manual ? "需手补" : "无图"}</div>`;
      return `<div class="media-card"><strong>#${m.id}</strong>${imgHtml}<p class="summary">${escapeHtml(
        m.title || ""
      )}</p></div>`;
    })
    .join("");
}

async function loadToday() {
  const info = await api("/api/today");
  $("#today-date").textContent = info.date;
  return info;
}

async function loadCandidates() {
  const data = await api("/api/candidates");
  state.items = data.items || [];
  // keep picks that still exist
  const ids = new Set(state.items.map((x) => Number(x.id)));
  state.picked = new Set([...state.picked].filter((id) => ids.has(id)));
  renderLists();
}

async function loadResult() {
  const data = await api("/api/result");
  if (data.has_result) renderResult(data);
}

async function onCollect() {
  const btn = $("#btn-collect");
  btn.disabled = true;
  setStatus("正在采集（外网源请挂梯子，可能要一两分钟）…");
  try {
    const data = await api("/api/collect", { method: "POST", body: "{}" });
    state.items = data.items || [];
    state.picked = new Set();
    renderLists();
    setStatus(`采集完成，共 ${data.count} 条`);
  } catch (err) {
    setStatus(String(err.message || err), true);
  } finally {
    btn.disabled = false;
  }
}

async function onProduce() {
  if (!state.picked.size) {
    setStatus("请先勾选至少一条新闻", true);
    return;
  }
  const btn = $("#btn-produce");
  btn.disabled = true;
  setStatus("正在生成文案并下载素材（调内网模型，请稍候）…");
  try {
    const payload = {
      picked: [...state.picked].sort((a, b) => a - b),
      tone: $("#tone").value.trim(),
      duration: $("#duration").value.trim() || "45s",
      extra_notes: $("#extra_notes").value.trim(),
    };
    const data = await api("/api/produce", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    renderResult({ ...data, has_result: true });
    await loadCandidates();
    setStatus("文案已生成");
  } catch (err) {
    setStatus(String(err.message || err), true);
  } finally {
    btn.disabled = false;
  }
}

function bindCopy() {
  document.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-copy");
      const text = document.getElementById(id)?.textContent || "";
      try {
        await navigator.clipboard.writeText(text);
        setStatus("已复制到剪贴板");
      } catch {
        setStatus("复制失败，请手动选择文本", true);
      }
    });
  });
}

async function boot() {
  $("#btn-collect").addEventListener("click", onCollect);
  $("#btn-refresh").addEventListener("click", async () => {
    try {
      await loadCandidates();
      setStatus("列表已刷新");
    } catch (err) {
      setStatus(String(err.message || err), true);
    }
  });
  $("#btn-produce").addEventListener("click", onProduce);
  bindCopy();

  try {
    const info = await loadToday();
    await loadCandidates();
    if (info.has_result) await loadResult();
    setStatus(
      info.has_candidates
        ? `已有今日候选 ${info.candidate_count} 条，可直接勾选生成`
        : "还没有候选，点「采集今天」开始"
    );
  } catch (err) {
    setStatus(String(err.message || err), true);
  }
}

boot();

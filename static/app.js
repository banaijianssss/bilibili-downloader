const $ = (sel) => document.querySelector(sel);
const view = $("#view");
const state = {
  route: "home",
  kind: "video",
  query: "",
  page: 1,
  video: null,
  playMode: "compat",
  poll: null,
  media: "muxed",
  formatId: null,
  formatLabel: "",
  selectedPages: new Set(),
  subs: true,
  cover: true,
  es: null,
};

function toast(text) {
  const el = $("#toast");
  el.textContent = text;
  el.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove("show"), 2800);
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

function card(item) {
  const btn = document.createElement("button");
  btn.className = "card";
  btn.innerHTML = `
    <div class="thumb" style="background-image:url('${item.pic}')">
      <span class="badge">${item.duration || ""}</span>
    </div>
    <div class="card-body">
      <h3>${escapeHtml(item.title)}</h3>
      <div class="sub"><span>${escapeHtml(item.author || "")}</span><span>${item.play || ""} 播放</span></div>
    </div>`;
  btn.onclick = () => openVideo(item.bvid);
  return btn;
}

function upCard(user) {
  const btn = document.createElement("button");
  btn.className = "card up-card";
  btn.innerHTML = `
    <img alt="" src="${user.face}" />
    <div>
      <h3>${escapeHtml(user.name)}</h3>
      <p>${user.fans} 粉丝 · ${user.videos} 稿件</p>
      <p>${escapeHtml(user.sign || "")}</p>
    </div>`;
  btn.onclick = () => openUp(user.mid, user.name);
  return btn;
}

function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function setNav(route) {
  document.querySelectorAll(".nav button[data-view]").forEach((b) => {
    b.classList.toggle("active", b.dataset.view === route);
  });
}

async function renderHome() {
  state.route = "home";
  setNav("home");
  view.innerHTML = `
    <div class="hero">
      <div>
        <h2>今日热门</h2>
        <p>点击卡片解析分 P。播放优先浏览器可解的最高 H.264；下载取账号可用的最高画质。</p>
      </div>
      <div class="meta-row" id="engine"></div>
    </div>
    <div class="grid" id="grid">${skeleton(8)}</div>`;
  const health = await api("/api/health");
  $("#engine").textContent = health.engine;
  const data = await api("/api/popular");
  const grid = $("#grid");
  grid.innerHTML = "";
  data.items.forEach((item) => grid.appendChild(card(item)));
}

function skeleton(n) {
  return Array.from({ length: n }, () => '<div class="skel"></div>').join("");
}

async function renderSearch(page = 1) {
  state.route = "search";
  state.page = page;
  setNav("search");
  view.innerHTML = `
    <div class="tabs">
      <button class="chip ${state.kind === "video" ? "on" : ""}" data-kind="video">视频</button>
      <button class="chip ${state.kind === "up" ? "on" : ""}" data-kind="up">UP 主</button>
    </div>
    <div class="grid" id="grid">${skeleton(8)}</div>
    <div class="pager" id="pager"></div>`;
  view.querySelectorAll("[data-kind]").forEach((b) => {
    b.onclick = () => { state.kind = b.dataset.kind; renderSearch(1); };
  });
  const data = await api(`/api/search?q=${encodeURIComponent(state.query)}&kind=${state.kind}&page=${page}`);
  const grid = $("#grid");
  grid.innerHTML = "";
  if (!data.items.length) {
    grid.innerHTML = '<div class="empty">没有结果。可以换个关键词，或直接粘贴 BV 号。</div>';
    return;
  }
  data.items.forEach((item) => grid.appendChild(state.kind === "up" ? upCard(item) : card(item)));
  $("#pager").innerHTML = `
    <button class="ghost" ${page <= 1 ? "disabled" : ""} id="prev">上一页</button>
    <button class="ghost" id="next">下一页</button>`;
  $("#prev").onclick = () => renderSearch(page - 1);
  $("#next").onclick = () => renderSearch(page + 1);
}

async function openUp(mid, name) {
  state.route = "up";
  setNav("search");
  view.innerHTML = `
    <div class="hero"><div><h2>${escapeHtml(name || "UP 主")}</h2><p id="up-meta">正在读取空间…</p></div></div>
    <div class="grid" id="grid">${skeleton(8)}</div>
    <div class="pager" id="pager"></div>`;
  const data = await api(`/api/up/${mid}?pn=${state.page || 1}`);
  $("#up-meta").textContent = `${data.profile.fans} 粉丝 · ${data.profile.sign || ""} ${data.note ? " · " + data.note : ""}`;
  const grid = $("#grid");
  grid.innerHTML = "";
  data.items.forEach((item) => grid.appendChild(card(item)));
  $("#pager").innerHTML = `<button class="ghost" id="more">更多稿件</button>`;
  $("#more").onclick = async () => {
    state.page = (state.page || 1) + 1;
    const more = await api(`/api/up/${mid}?pn=${state.page}`);
    more.items.forEach((item) => grid.appendChild(card(item)));
  };
}

async function openVideo(bvid, page = 1) {
  state.route = "video";
  setNav("search");
  view.innerHTML = `<div class="hero"><div><h2>正在解析 ${escapeHtml(bvid)}</h2><p>yt-dlp 正在协商 DASH 分轨，通常需要几秒。</p></div></div>`;
  const data = await api(`/api/video/${bvid}?page=${page}`);
  state.video = data;
  state.selectedPages = new Set([data.page]);
  const multi = (data.pages || []).length > 1;
  view.innerHTML = `
    <div class="theater">
      <section class="player-shell">
        <div class="stage">
          <video id="player" controls playsinline poster="${data.pic}"></video>
          <audio id="audio"></audio>
        </div>
        <div class="player-bar">
          <button class="ghost" id="play-compat">兼容最高画质</button>
          <button class="ghost" id="play-best">尝试绝对最高</button>
          <div class="grow" id="play-label">准备播放…</div>
        </div>
      </section>
      <aside class="panel">
        <h3>${escapeHtml(data.title)}</h3>
        <div class="sub"><span>${escapeHtml(data.author)}</span><span>${data.play} 播放</span></div>
        <div class="desc">${escapeHtml(data.desc)}</div>
        ${data.cookie ? "" : '<div class="notice" style="margin-top:12px">未登录。播放和下载会被限制在游客清晰度。1080P+ / 4K 请先在「账号与画质」扫码登录。</div>'}
        <div class="section-title">分 P</div>
        <div class="pages" id="pages"></div>
        ${multi ? `<div class="batch-bar">
          <button class="ghost" id="sel-all" type="button">全选分P</button>
          <button class="ghost" id="sel-none" type="button">清空</button>
          <button class="primary" id="dl-all" type="button">全部下载</button>
        </div>` : ""}
        <div class="section-title">可用流 · 点击选择</div>
        <div class="formats" id="formats"></div>
        <div class="section-title">下载类型</div>
        <div class="pages" id="media-modes">
          <button type="button" class="format on" data-media="muxed">音视频</button>
          <button type="button" class="format" data-media="video">纯视频</button>
          <button type="button" class="format" data-media="audio">纯音频</button>
        </div>
        <div class="dl-opts">
          <label><input type="checkbox" id="opt-cover" ${state.cover ? "checked" : ""}/> 封面</label>
          <label><input type="checkbox" id="opt-subs" ${state.subs ? "checked" : ""}/> 字幕（若有）</label>
        </div>
        <div class="actions">
          <button class="primary" id="dl">下载</button>
          ${multi ? '<button class="ghost" id="dl-selected" type="button">下载勾选分P</button>' : ""}
          <button class="ghost" id="open-up">UP 空间</button>
        </div>
      </aside>
    </div>`;
  data.pages.forEach((p) => {
    const b = document.createElement("button");
    const on = p.page === data.page;
    b.className = "format" + (on ? " on" : "");
    b.type = "button";
    b.dataset.page = p.page;
    if (multi) {
      b.innerHTML = `<span class="page-check">${state.selectedPages.has(p.page) ? "☑" : "☐"}</span> P${p.page} ${escapeHtml(p.part || "")}`;
      b.onclick = (ev) => {
        if (ev.shiftKey || ev.altKey) {
          openVideo(bvid, p.page);
          return;
        }
        if (state.selectedPages.has(p.page)) state.selectedPages.delete(p.page);
        else state.selectedPages.add(p.page);
        if (p.page !== data.page) {
          // keep current play page; just refresh checkmarks
          renderPageChecks();
        } else {
          renderPageChecks();
        }
      };
      b.ondblclick = () => openVideo(bvid, p.page);
    } else {
      b.textContent = `P${p.page} ${p.part}`;
      b.onclick = () => openVideo(bvid, p.page);
    }
    $("#pages").appendChild(b);
  });
  const videoFormats = data.formats.filter((f) => f.has_video).slice(0, 10);
  if (videoFormats.length) {
    const keep = videoFormats.find((f) => f.format_id === state.formatId);
    const pick = keep || videoFormats[0];
    state.formatId = pick.format_id;
    state.formatLabel = formatLabel(pick);
  } else {
    state.formatId = null;
    state.formatLabel = "";
  }
  videoFormats.forEach((f) => {
    const b = document.createElement("button");
    b.className = "format" + (f.format_id === state.formatId ? " on" : "");
    b.type = "button";
    b.dataset.formatId = f.format_id;
    b.textContent = formatLabel(f);
    b.onclick = () => {
      state.formatId = f.format_id;
      state.formatLabel = formatLabel(f);
      document.querySelectorAll("#formats .format").forEach((el) => {
        el.classList.toggle("on", el.dataset.formatId === String(state.formatId));
      });
      updateDownloadButton();
    };
    $("#formats").appendChild(b);
  });
  state.media = state.media || "muxed";
  document.querySelectorAll("#media-modes .format").forEach((btn) => {
    btn.classList.toggle("on", btn.dataset.media === state.media);
    btn.onclick = () => {
      state.media = btn.dataset.media;
      document.querySelectorAll("#media-modes .format").forEach((b) => {
        b.classList.toggle("on", b.dataset.media === state.media);
      });
      updateDownloadButton();
    };
  });
  const coverEl = $("#opt-cover");
  const subsEl = $("#opt-subs");
  if (coverEl) coverEl.onchange = () => { state.cover = coverEl.checked; };
  if (subsEl) subsEl.onchange = () => { state.subs = subsEl.checked; };
  updateDownloadButton();
  $("#dl").onclick = () => downloadCurrent([data.page]);
  if ($("#dl-selected")) $("#dl-selected").onclick = () => {
    const pages = [...state.selectedPages].sort((a, b) => a - b);
    if (!pages.length) { toast("请先勾选分 P"); return; }
    downloadCurrent(pages);
  };
  if ($("#dl-all")) $("#dl-all").onclick = () => {
    const pages = data.pages.map((p) => p.page);
    downloadCurrent(pages, true);
  };
  if ($("#sel-all")) $("#sel-all").onclick = () => {
    data.pages.forEach((p) => state.selectedPages.add(p.page));
    renderPageChecks();
  };
  if ($("#sel-none")) $("#sel-none").onclick = () => {
    state.selectedPages.clear();
    renderPageChecks();
  };
  $("#open-up").onclick = () => data.mid && openUp(data.mid, data.author);
  $("#play-compat").onclick = () => startPlay("compat");
  $("#play-best").onclick = () => startPlay("best");
  startPlay("compat");
}

function renderPageChecks() {
  document.querySelectorAll("#pages .format").forEach((b) => {
    const p = Number(b.dataset.page);
    const check = b.querySelector(".page-check");
    if (check) check.textContent = state.selectedPages.has(p) ? "☑" : "☐";
  });
}

function bindSync(video, audio) {
  const sync = () => {
    if (!audio.src) return;
    if (Math.abs(audio.currentTime - video.currentTime) > 0.35) audio.currentTime = video.currentTime;
  };
  video.onplay = () => audio.play().catch(() => {});
  video.onpause = () => audio.pause();
  video.onseeking = sync;
  video.ontimeupdate = sync;
  video.onratechange = () => { audio.playbackRate = video.playbackRate; };
  video.onvolumechange = () => { audio.volume = video.volume; audio.muted = video.muted; };
}

async function startPlay(mode) {
  const data = state.video;
  if (!data) return;
  const label = $("#play-label");
  label.textContent = "拉取播放地址…";
  const stream = await api(`/api/play/${data.bvid}?page=${data.page}&mode=${mode}`);
  const video = $("#player");
  const audio = $("#audio");
  bindSync(video, audio);
  video.src = stream.video;
  if (stream.audio) audio.src = stream.audio;
  else audio.removeAttribute("src");
  label.textContent = `${stream.label}${stream.browser_ok ? "" : " · 编码可能无法在浏览器解码"}`;
  video.play().catch(() => {});
}

function formatLabel(f) {
  if (!f) return "";
  const fps = f.fps ? Math.round(f.fps) + "帧 " : "";
  return `${f.height || "?"}P ${fps}${f.codec || ""} ${f.tbr || 0}kbps`.replace(/\s+/g, " ").trim();
}

function updateDownloadButton() {
  const el = $("#dl");
  if (!el) return;
  const labels = { muxed: "音视频", video: "纯视频", audio: "纯音频" };
  const media = state.media || "muxed";
  if (media === "audio") {
    el.textContent = "下载纯音频";
    return;
  }
  const q = state.formatLabel || "最高画质";
  const kind = labels[media] || "";
  el.textContent = media === "muxed" ? `下载 ${q}` : `下载${kind} ${q}`;
}

async function downloadCurrent(pages, allPages) {
  const data = state.video;
  const media = state.media || "muxed";
  const labels = { muxed: "音视频", video: "纯视频", audio: "纯音频" };
  const payload = {
    bvid: data.bvid,
    title: data.title,
    media,
    subs: !!state.subs,
    cover: !!state.cover,
  };
  if (allPages) {
    payload.all_pages = true;
    payload.pages = (data.pages || []).map((p) => p.page);
  } else if (pages && pages.length > 1) {
    payload.pages = pages;
  } else {
    payload.page = (pages && pages[0]) || data.page;
  }
  if (media !== "audio" && state.formatId) {
    payload.format_id = state.formatId;
  }
  const result = await api("/api/download", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const count = result.count || 1;
  const q = media === "audio" ? "" : (state.formatLabel ? ` · ${state.formatLabel}` : "");
  toast(count > 1
    ? `已加入 ${count} 个${labels[media] || media}下载任务${q}`
    : `已加入${labels[media] || media}下载队列${q}`);
  openDrawer();
  return result;
}

function statusLabel(s) {
  const map = {
    queued: "排队中",
    running: "准备中",
    downloading: "下载中",
    muxing: "封装中",
    finishing: "收尾中",
    done: "完成",
    error: "失败",
    cancelled: "已取消",
    interrupted: "已中断",
  };
  return map[s] || s;
}

function renderJobsList(items, historyItems) {
  const box = $("#jobs");
  const list = (items || []).slice();
  if (!list.length && !(historyItems || []).length) {
    box.innerHTML = '<div class="empty">还没有任务。</div>';
    return;
  }
  box.innerHTML = list.map((j) => {
    const canCancel = ["queued", "running", "downloading", "muxing", "finishing"].includes(j.status);
    const canRetry = ["error", "interrupted", "cancelled"].includes(j.status);
    return `
    <div class="job" data-id="${j.id}">
      <h4>${escapeHtml(j.title)} · P${j.page}${j.media_label ? " · " + escapeHtml(j.media_label) : ""}</h4>
      <div class="bar"><span style="width:${j.progress || 0}%"></span></div>
      <div class="meta"><span>${statusLabel(j.status)} ${j.speed || ""} ${j.eta || ""}</span><span>${j.progress || 0}%</span></div>
      ${j.error ? `<div class="meta err">${escapeHtml(j.error)}</div>` : ""}
      <div class="job-actions">
        ${j.status === "done" ? `<a href="/api/files/${j.id}">保存到本地</a>` : ""}
        ${canCancel ? `<button class="ghost tiny" data-cancel="${j.id}" type="button">取消</button>` : ""}
        ${canRetry ? `<button class="ghost tiny" data-retry="${j.id}" type="button">重试</button>` : ""}
      </div>
    </div>`;
  }).join("");
  if ((historyItems || []).length) {
    box.insertAdjacentHTML("beforeend", `<div class="section-title">历史文件</div>` + historyItems.slice(0, 8).map((h) => `
      <div class="job"><h4>${escapeHtml(h.title)}${h.media_label ? " · " + escapeHtml(h.media_label) : ""}</h4><div class="meta"><a href="/api/files/${h.id}">${escapeHtml(h.file)}</a></div></div>
    `).join(""));
  }
  box.querySelectorAll("[data-cancel]").forEach((btn) => {
    btn.onclick = async () => {
      try {
        await api(`/api/jobs/${btn.dataset.cancel}/cancel`, { method: "POST" });
        toast("已取消");
        refreshJobs();
      } catch (e) { toast(e.message); }
    };
  });
  box.querySelectorAll("[data-retry]").forEach((btn) => {
    btn.onclick = async () => {
      try {
        await api(`/api/jobs/${btn.dataset.retry}/retry`, { method: "POST" });
        toast("已重新排队");
        refreshJobs();
      } catch (e) { toast(e.message); }
    };
  });
}

let _jobsCache = [];
let _historyCache = [];

async function refreshJobs() {
  const [jobs, history] = await Promise.all([api("/api/jobs"), api("/api/history")]);
  _jobsCache = jobs.items || [];
  _historyCache = history.items || [];
  renderJobsList(_jobsCache, _historyCache);
}

function startJobStream() {
  stopJobStream();
  if (!window.EventSource) {
    state.poll = setInterval(refreshJobs, 1200);
    return;
  }
  try {
    const es = new EventSource("/api/jobs/stream");
    state.es = es;
    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data.type === "snapshot") {
          _jobsCache = data.items || [];
          renderJobsList(_jobsCache, _historyCache);
        } else if (data.type === "job" && data.job) {
          const idx = _jobsCache.findIndex((j) => j.id === data.job.id);
          if (idx >= 0) _jobsCache[idx] = data.job;
          else _jobsCache.unshift(data.job);
          renderJobsList(_jobsCache, _historyCache);
        }
      } catch (_) {}
    };
    es.onerror = () => {
      stopJobStream();
      state.poll = setInterval(refreshJobs, 1500);
    };
  } catch (_) {
    state.poll = setInterval(refreshJobs, 1200);
  }
}

function stopJobStream() {
  if (state.es) {
    try { state.es.close(); } catch (_) {}
    state.es = null;
  }
  clearInterval(state.poll);
  state.poll = null;
}

function openDrawer() {
  $("#drawer").classList.add("show");
  $("#drawer-back").classList.add("show");
  refreshJobs().then(() => startJobStream());
}
function closeDrawer() {
  $("#drawer").classList.remove("show");
  $("#drawer-back").classList.remove("show");
  stopJobStream();
}

async function refreshAccount() {
  let profile = { logged_in: false };
  try { profile = await api("/api/login/status"); } catch (_) {}
  const on = !!profile.logged_in;
  const expired = !!(profile.expired || profile.status === "expired");
  const refreshed = !!(profile.refreshed || profile.status === "refreshed");
  $("#cookie-dot").classList.toggle("off", !on);
  $("#cookie-dot").classList.toggle("warn", expired);
  if (on) {
    $("#cookie-label").textContent = `${profile.name}${profile.vip ? " · 大会员" : ""}${refreshed ? " · 已续期" : ""}`;
  } else if (expired) {
    $("#cookie-label").textContent = "需重新扫码";
  } else {
    $("#cookie-label").textContent = "游客画质";
  }
  const acc = $("#login-account");
  if (on) {
    acc.innerHTML = `${profile.face ? `<img alt="" src="${escapeHtml(profile.face)}" referrerpolicy="no-referrer" />` : ""}
      <div><strong>${escapeHtml(profile.name)}</strong><div class="muted">${profile.vip ? escapeHtml(profile.vip_label || "大会员") : "普通账号"} · UID ${profile.mid}${refreshed ? " · Cookie 已自动续期" : ""}</div></div>`;
  } else if (expired) {
    acc.innerHTML = `<div class="notice">登录已失效，需重新扫码。自动续期失败或不支持时请点击下方「扫码登录」。</div>`;
  } else {
    acc.innerHTML = `<span class="muted">当前未登录（游客画质）。</span>`;
  }
  $("#logout").hidden = !on;
  $("#qr-login").textContent = on ? "重新扫码登录" : "扫码登录";
  return profile;
}

const qr = { key: "", timer: null, deadline: 0 };

function stopQr() {
  clearTimeout(qr.timer);
  qr.timer = null;
  qr.key = "";
}

async function startQrLogin() {
  stopQr();
  const wrap = $("#qr-wrap");
  const tip = $("#qr-tip");
  wrap.hidden = false;
  $("#qr").innerHTML = "";
  tip.textContent = "正在获取二维码…";
  $("#qr-login").disabled = true;
  try {
    const data = await api("/api/login/qr");
    $("#qr").innerHTML = data.svg;
    tip.textContent = "请用哔哩哔哩手机 App 扫描二维码";
    qr.key = data.key;
    qr.deadline = Date.now() + (data.ttl || 180) * 1000;
    pollQr(data.key);
  } catch (err) {
    tip.textContent = err.message;
  } finally {
    $("#qr-login").disabled = false;
  }
}

async function pollQr(key) {
  if (qr.key !== key) return;
  if (Date.now() > qr.deadline) {
    $("#qr-tip").textContent = "二维码已过期，请点击「重新扫码登录」";
    stopQr();
    return;
  }
  try {
    const r = await api(`/api/login/qr/poll?key=${encodeURIComponent(key)}`);
    if (qr.key !== key) return;
    if (r.status === "done") {
      stopQr();
      $("#qr-wrap").hidden = true;
      toast("扫码登录成功");
      await refreshAccount();
      return;
    }
    if (r.status === "expired" || r.status === "error") {
      $("#qr-tip").textContent = r.message + "，请点击「重新扫码登录」";
      stopQr();
      return;
    }
    $("#qr-tip").textContent = r.message;
  } catch (err) {
    $("#qr-tip").textContent = err.message;
  }
  qr.timer = setTimeout(() => pollQr(key), 1500);
}

async function boot() {
  await refreshAccount();
  renderHome().catch((err) => {
    view.innerHTML = `<div class="empty">${escapeHtml(err.message)}</div>`;
  });
}

$("#search-form").onsubmit = async (e) => {
  e.preventDefault();
  const q = $("#q").value.trim();
  if (!q) return;
  if (/BV[0-9A-Za-z]+|av\d+|bilibili\.com|b23\.tv/i.test(q)) {
    try {
      const resolved = await api(`/api/resolve?q=${encodeURIComponent(q)}`);
      openVideo(resolved.bvid);
      return;
    } catch (err) {
      toast(err.message);
    }
  }
  state.query = q;
  state.kind = "video";
  renderSearch(1).catch((err) => toast(err.message));
};
document.querySelectorAll(".nav button[data-view]").forEach((b) => {
  b.onclick = () => {
    if (b.dataset.view === "home") renderHome();
    if (b.dataset.view === "search") {
      if (!state.query) { view.innerHTML = '<div class="empty">在顶部搜索视频或 UP 主。</div>'; setNav("search"); }
      else renderSearch(state.page || 1);
    }
    if (b.dataset.view === "tasks") openDrawer();
  };
});
$("#open-tasks").onclick = openDrawer;
$("#close-drawer").onclick = closeDrawer;
$("#drawer-back").onclick = closeDrawer;
$("#open-settings").onclick = () => { $("#settings-back").classList.add("show"); refreshAccount(); };
$("#close-settings").onclick = () => { stopQr(); $("#qr-wrap").hidden = true; $("#settings-back").classList.remove("show"); };
$("#qr-login").onclick = startQrLogin;
$("#logout").onclick = async () => {
  stopQr();
  $("#qr-wrap").hidden = true;
  await api("/api/login/logout", { method: "POST" });
  toast("已退出登录");
  await refreshAccount();
  boot();
};
$("#save-settings").onclick = async () => {
  await api("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sessdata: $("#sessdata").value, cookie: $("#cookie").value }),
  });
  $("#settings-back").classList.remove("show");
  toast("Cookie 已保存，重新打开视频后生效");
  boot();
};
boot();

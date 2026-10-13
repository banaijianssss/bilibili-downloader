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
        <div class="section-title">可用流 · 点击选择</div>
        <div class="formats" id="formats"></div>
        <div class="section-title">下载类型</div>
        <div class="pages" id="media-modes">
          <button type="button" class="format on" data-media="muxed">音视频</button>
          <button type="button" class="format" data-media="video">纯视频</button>
          <button type="button" class="format" data-media="audio">纯音频</button>
        </div>
        <div class="actions">
          <button class="primary" id="dl">下载</button>
          <button class="ghost" id="open-up">UP 空间</button>
        </div>
      </aside>
    </div>`;
  data.pages.forEach((p) => {
    const b = document.createElement("button");
    b.className = "format" + (p.page === data.page ? " on" : "");
    b.textContent = `P${p.page} ${p.part}`;
    b.onclick = () => openVideo(bvid, p.page);
    $("#pages").appendChild(b);
  });
  const videoFormats = data.formats.filter((f) => f.has_video).slice(0, 10);
  // Default to highest available stream (list is height-desc from API)
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
  updateDownloadButton();
  $("#dl").onclick = () => downloadCurrent();
  $("#open-up").onclick = () => data.mid && openUp(data.mid, data.author);
  $("#play-compat").onclick = () => startPlay("compat");
  $("#play-best").onclick = () => startPlay("best");
  startPlay("compat");
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

async function downloadCurrent() {
  const data = state.video;
  const media = state.media || "muxed";
  const labels = { muxed: "音视频", video: "纯视频", audio: "纯音频" };
  const payload = { bvid: data.bvid, page: data.page, title: data.title, media };
  if (media !== "audio" && state.formatId) {
    payload.format_id = state.formatId;
  }
  const job = await api("/api/download", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const q = media === "audio" ? "" : (state.formatLabel ? ` · ${state.formatLabel}` : "");
  toast(`已加入${labels[media] || media}下载队列${q}`);
  openDrawer();
  return job;
}

function openDrawer() {
  $("#drawer").classList.add("show");
  $("#drawer-back").classList.add("show");
  refreshJobs();
  clearInterval(state.poll);
  state.poll = setInterval(refreshJobs, 1200);
}
function closeDrawer() {
  $("#drawer").classList.remove("show");
  $("#drawer-back").classList.remove("show");
  clearInterval(state.poll);
}

async function refreshJobs() {
  const [jobs, history] = await Promise.all([api("/api/jobs"), api("/api/history")]);
  const box = $("#jobs");
  const items = jobs.items.slice().reverse();
  if (!items.length && !history.items.length) {
    box.innerHTML = '<div class="empty">还没有任务。</div>';
    return;
  }
  box.innerHTML = items.map((j) => `
    <div class="job">
      <h4>${escapeHtml(j.title)} · P${j.page}${j.media_label ? " · " + escapeHtml(j.media_label) : ""}</h4>
      <div class="bar"><span style="width:${j.progress || 0}%"></span></div>
      <div class="meta"><span>${j.status} ${j.speed || ""} ${j.eta || ""}</span><span>${j.progress || 0}%</span></div>
      ${j.error ? `<div class="meta">${escapeHtml(j.error)}</div>` : ""}
      ${j.status === "done" ? `<div class="meta"><a href="/api/files/${j.id}">保存到本地</a></div>` : ""}
    </div>`).join("");
  if (history.items.length) {
    box.insertAdjacentHTML("beforeend", `<div class="section-title">历史文件</div>` + history.items.slice(0, 8).map((h) => `
      <div class="job"><h4>${escapeHtml(h.title)}${h.media_label ? " · " + escapeHtml(h.media_label) : ""}</h4><div class="meta"><a href="/api/files/${h.id}">${escapeHtml(h.file)}</a></div></div>
    `).join(""));
  }
}

async function refreshAccount() {
  let profile = { logged_in: false };
  try { profile = await api("/api/login/status"); } catch (_) {}
  const on = !!profile.logged_in;
  $("#cookie-dot").classList.toggle("off", !on);
  $("#cookie-label").textContent = on
    ? `${profile.name}${profile.vip ? " · 大会员" : ""}`
    : (profile.expired ? "登录已失效" : "游客画质");
  const acc = $("#login-account");
  if (on) {
    acc.innerHTML = `${profile.face ? `<img alt="" src="${escapeHtml(profile.face)}" referrerpolicy="no-referrer" />` : ""}
      <div><strong>${escapeHtml(profile.name)}</strong><div class="muted">${profile.vip ? escapeHtml(profile.vip_label || "大会员") : "普通账号"} · UID ${profile.mid}</div></div>`;
  } else {
    acc.innerHTML = `<span class="muted">${profile.expired ? "登录已失效，请重新扫码。" : "当前未登录（游客画质）。"}</span>`;
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

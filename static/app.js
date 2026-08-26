const state = {
  view: "overview",
  dashboard: null,
  videos: [],
  candidates: [],
  jobs: [],
  modules: null,
  selectedVideo: null,
};

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function fmt(value) {
  const n = Number(value || 0);
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(Math.round(n));
}

function fileUrl(path) {
  if (!path) return "";
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  return `/files/${encodeURIComponent(path).replaceAll("%2F", "/")}`;
}

function setView(view) {
  state.view = view;
  document.querySelectorAll(".nav").forEach((btn) => btn.classList.toggle("active", btn.dataset.view === view));
  document.querySelectorAll(".view").forEach((el) => el.classList.remove("active"));
  $(`${view}View`).classList.add("active");
  const titles = {
    overview: ["总览", "多账号采集、爆款分析、样品风险和分段复刻。"],
    collect: ["采集", "从 TikTok 链接、CSV 或 JSON 采集视频数据并立即筛选。"],
    videos: ["视频库", "选择视频后上传产品图，发起 Seedance 分段复刻。"],
    samples: ["样品达人", "按样品领取、回传视频、成交和 GMV 计算风险。"],
    jobs: ["复刻任务", "查看每段提示词、尾帧和最终拼接结果。"],
    import: ["导入", "录入本地视频、产品图和 TikTok 带货指标。"],
  };
  $("viewTitle").textContent = titles[view][0];
  $("subTitle").textContent = titles[view][1];
}

async function refreshAll() {
  state.dashboard = await api("/api/dashboard");
  state.modules = await api("/api/modules");
  state.videos = (await api("/api/videos")).items;
  state.candidates = (await api("/api/free-sample-candidates")).items;
  state.jobs = (await api("/api/jobs")).items;
  renderDashboard();
  renderVideos();
  renderCandidates();
  renderJobs();
  renderModules();
}

function renderDashboard() {
  const counts = state.dashboard?.counts || {};
  const metrics = [
    ["账号", counts.accounts],
    ["达人", counts.creators],
    ["视频", counts.videos],
    ["爆款", counts.hot_videos],
    ["样品风险", counts.sample_candidates],
    ["复刻任务", counts.jobs],
  ];
  $("metrics").innerHTML = metrics.map(([label, value]) => `<div class="metric"><span class="value">${fmt(value)}</span><span class="label">${label}</span></div>`).join("");
  const config = state.dashboard?.config || {};
  $("systemStatus").innerHTML = [
    config.ffmpeg_available ? ["FFmpeg", "ok"] : ["FFmpeg 未配置", "danger"],
    config.ffprobe_available ? ["FFprobe", "ok"] : ["FFprobe 未配置", "danger"],
    config.yt_dlp_available ? ["yt-dlp", "ok"] : ["yt-dlp 未配置", "warn"],
    config.gemini_configured ? [`Gemini ${config.gemini_provider || ""}`, "ok"] : ["Gemini mock", "warn"],
    [`Seedance ${config.seedance_provider || "mock"}`, config.seedance_provider === "mock" ? "warn" : "ok"],
  ].map(([label, kind]) => `<span class="chip ${kind === "danger" ? "danger" : kind === "warn" ? "warn" : ""}">${label}</span>`).join("");
  $("hotList").innerHTML = (state.dashboard?.hot_videos || []).map(videoRow).join("") || empty("暂无爆款视频");
  $("candidateList").innerHTML = (state.dashboard?.sample_candidates || []).map(candidateRow).join("") || empty("暂无样品风险");
  $("recentJobs").innerHTML = (state.dashboard?.jobs || []).map(jobRow).join("") || empty("暂无复刻任务");
  bindJobButtons();
}

function renderModules() {
  const modules = state.modules || {};
  const collection = modules.collection || {};
  const screening = modules.screening || {};
  const replication = modules.replication || {};
  $("moduleStatus").innerHTML = [
    moduleRow("采集模块", collection.ready, `来源：${(collection.sources || []).join(" / ")}`),
    moduleRow("下载模块", collection.download_capabilities?.yt_dlp_available, `yt-dlp：${collection.download_capabilities?.yt_dlp_bin || "yt-dlp"}`),
    moduleRow("筛选模块", screening.ready, `爆款阈值 ${screening.hot_video_threshold || 60}，样品风险阈值 ${screening.sample_candidate_threshold || 50}`),
    moduleRow("复刻模块", replication.ready, `最长 ${replication.max_duration_seconds || 60}s，分段 ${replication.segment_seconds || 15}s`),
  ].join("");
}

function moduleRow(title, ok, detail) {
  return `<article class="row-card">
    <div class="row-title"><span>${escapeHtml(title)}</span><span>${ok ? "可用" : "需配置"}</span></div>
    <div class="status">${escapeHtml(detail || "")}</div>
  </article>`;
}

function videoRow(v) {
  return `<article class="row-card">
    <div class="row-title"><span>${escapeHtml(v.title || v.video_url || "未命名视频")}</span><span>${Number(v.hot_score || 0).toFixed(1)}</span></div>
    <div class="chips">
      <span class="chip">@${escapeHtml(v.username || "")}</span>
      <span class="chip">播放 ${fmt(v.views)}</span>
      <span class="chip warn">订单 ${fmt(v.orders)}</span>
    </div>
  </article>`;
}

function candidateRow(c) {
  const reasons = Array.isArray(c.reasons) ? c.reasons : [];
  return `<article class="row-card">
    <div class="row-title"><span>@${escapeHtml(c.username || "")}</span><span>${Number(c.score || 0).toFixed(1)}</span></div>
    <div class="chips">${reasons.map((r) => `<span class="chip danger">${escapeHtml(r)}</span>`).join("")}</div>
  </article>`;
}

function renderVideos() {
  const hotOnly = $("videoFilter").value === "hot";
  const videos = hotOnly ? state.videos.filter((v) => Number(v.hot_score || 0) >= 60) : state.videos;
  $("videoGrid").innerHTML = videos.map(videoCard).join("") || empty("暂无视频");
  document.querySelectorAll("[data-select-video]").forEach((btn) => {
    btn.addEventListener("click", () => selectVideo(Number(btn.dataset.selectVideo)));
  });
}

function videoCard(v) {
  const media = v.cover_path
    ? `<img src="${fileUrl(v.cover_path)}" alt="">`
    : v.original_video_path
      ? `<video src="${fileUrl(v.original_video_path)}" muted controls></video>`
      : `<div class="empty">无预览</div>`;
  return `<article class="video-card">
    <div class="thumb">${media}</div>
    <div class="video-body">
      <div class="video-title">${escapeHtml(v.title || v.video_url || "未命名视频")}</div>
      <div class="meta">
        <span><b>${fmt(v.views)}</b>播放</span>
        <span><b>${Number(v.hot_score || 0).toFixed(1)}</b>热度</span>
        <span><b>${fmt(v.orders)}</b>订单</span>
      </div>
      <div class="chips">
        <span class="chip">@${escapeHtml(v.username || "")}</span>
        <span class="chip">${escapeHtml(v.product_name || "未绑定产品")}</span>
      </div>
      <button class="primary" data-select-video="${v.id}">复刻</button>
    </div>
  </article>`;
}

function selectVideo(id) {
  state.selectedVideo = state.videos.find((v) => v.id === id);
  if (!state.selectedVideo) return;
  $("selectedVideo").innerHTML = `<b>${escapeHtml(state.selectedVideo.title || state.selectedVideo.video_url || "未命名视频")}</b><br>@${escapeHtml(state.selectedVideo.username || "")}`;
  $("productImagePath").value = state.selectedVideo.product_image_path || "";
}

function renderCandidates() {
  $("sampleTable").innerHTML = state.candidates.map(candidateRow).join("") || empty("暂无样品风险");
}

function renderJobs() {
  $("jobsList").innerHTML = state.jobs.map(jobRow).join("") || empty("暂无复刻任务");
  bindJobButtons();
}

function jobRow(j) {
  const output = j.output_video_path ? `<a href="${fileUrl(j.output_video_path)}" target="_blank">成片</a>` : "";
  return `<article class="job-card">
    <div class="row-title"><span>#${j.id} ${escapeHtml(j.title || "")}</span><span>${escapeHtml(j.status || "")}</span></div>
    <div class="chips">
      <span class="chip">@${escapeHtml(j.username || "")}</span>
      <span class="chip">${Number(j.progress || 0).toFixed(0)}%</span>
      ${output ? `<span class="chip">${output}</span>` : ""}
    </div>
    <div class="progress"><span style="width:${Math.max(0, Math.min(100, Number(j.progress || 0)))}%"></span></div>
    ${j.error ? `<div class="status">${escapeHtml(j.error)}</div>` : ""}
    <button class="secondary" data-job-id="${j.id}">分段详情</button>
  </article>`;
}

function bindJobButtons() {
  document.querySelectorAll("[data-job-id]").forEach((btn) => {
    btn.addEventListener("click", () => showJob(Number(btn.dataset.jobId)));
  });
}

async function showJob(id) {
  const detail = $("jobDetail");
  const job = await api(`/api/jobs/${id}`);
  detail.classList.add("active");
  detail.innerHTML = `<div class="panel-head">
    <h2>任务 #${job.id}</h2>
    ${job.output_video_path ? `<a href="${fileUrl(job.output_video_path)}" target="_blank">打开成片</a>` : ""}
  </div>
  ${(job.segments || []).map(segmentRow).join("") || empty("暂无分段")}`;
  setView("jobs");
}

function segmentRow(s) {
  return `<section class="segment">
    <div class="row-title"><span>第 ${s.segment_index} 段</span><span>${escapeHtml(s.status || "")}</span></div>
    <div class="chips">
      ${s.source_segment_path ? `<span class="chip"><a href="${fileUrl(s.source_segment_path)}" target="_blank">原片段</a></span>` : ""}
      ${s.generated_video_path ? `<span class="chip"><a href="${fileUrl(s.generated_video_path)}" target="_blank">生成片段</a></span>` : ""}
      ${s.tail_frame_path ? `<span class="chip"><a href="${fileUrl(s.tail_frame_path)}" target="_blank">尾帧</a></span>` : ""}
    </div>
    ${s.prompt ? `<div class="prompt">${escapeHtml(s.prompt)}</div>` : ""}
    ${s.error ? `<div class="status">${escapeHtml(s.error)}</div>` : ""}
  </section>`;
}

function empty(text) {
  return `<div class="row-card muted">${text}</div>`;
}

async function uploadFile(input, kind, targetInput, statusEl) {
  const file = input.files?.[0];
  if (!file) return "";
  statusEl.textContent = "上传中...";
  const content = await readAsDataUrl(file);
  const data = await api("/api/upload", {
    method: "POST",
    body: JSON.stringify({ filename: file.name, kind, content_base64: content }),
  });
  targetInput.value = data.path;
  statusEl.textContent = data.path;
  return data.path;
}

function readAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

async function addVideo() {
  const status = $("addVideoStatus");
  try {
    await uploadFile($("originalVideoInput"), "video", $("originalVideoPath"), status);
    await uploadFile($("importProductImageInput"), "product", $("importProductImagePath"), status);
    const payload = {
      account_name: $("accountName").value,
      username: $("creatorUsername").value,
      title: $("videoTitle").value,
      video_url: $("videoUrl").value,
      product_name: $("productName").value,
      duration_seconds: $("durationSeconds").value,
      views: $("views").value,
      likes: $("likes").value,
      comments: $("comments").value,
      shares: $("shares").value,
      orders: $("orders").value,
      gmv: $("gmv").value,
      sample_received_count: $("samplesReceived").value,
      posted_video_count: $("postedVideosCount").value,
      original_video_path: $("originalVideoPath").value,
      product_image_path: $("importProductImagePath").value,
    };
    await api("/api/videos", { method: "POST", body: JSON.stringify(payload) });
    status.textContent = "已保存";
    await refreshAll();
  } catch (err) {
    status.textContent = err.message;
  }
}

async function replicate() {
  const status = $("replicateStatus");
  try {
    if (!state.selectedVideo) throw new Error("请选择视频");
    await uploadFile($("productImageInput"), "product", $("productImagePath"), status);
    const data = await api("/api/replicate", {
      method: "POST",
      body: JSON.stringify({
        video_id: state.selectedVideo.id,
        product_image_path: $("productImagePath").value,
        max_duration_seconds: Number($("maxDuration").value || 60),
      }),
    });
    status.textContent = `任务 #${data.job_id} 已创建`;
    setView("jobs");
    await refreshAll();
  } catch (err) {
    status.textContent = err.message;
  }
}

async function importCsv() {
  const status = $("importStatus");
  try {
    const data = await api("/api/import/videos", { method: "POST", body: JSON.stringify({ csv: $("csvInput").value }) });
    status.textContent = `导入 ${data.imported || 0} 条`;
    await refreshAll();
  } catch (err) {
    status.textContent = err.message;
  }
}

async function collectVideos(csvOnly = false) {
  const status = $("collectStatus");
  try {
    status.textContent = "采集中...";
    const payload = {
      account_name: $("collectAccountName").value,
      url_text: csvOnly ? "" : $("collectUrlText").value,
      csv: $("collectCsvText").value,
      download: $("collectDownload").checked,
    };
    const data = await api("/api/closed-loop/collect-screen", { method: "POST", body: JSON.stringify(payload) });
    const imported = data.collection?.imported || 0;
    const hot = data.screening?.summary?.hot_video_count || 0;
    status.textContent = `已采集 ${imported} 条，筛出爆款 ${hot} 条`;
    await refreshAll();
    setView("videos");
  } catch (err) {
    status.textContent = err.message;
  }
}

async function analyze() {
  await api("/api/analyze", { method: "POST", body: "{}" });
  await refreshAll();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function bindEvents() {
  document.querySelectorAll(".nav").forEach((btn) => btn.addEventListener("click", () => setView(btn.dataset.view)));
  document.querySelectorAll("[data-goto]").forEach((btn) => btn.addEventListener("click", () => setView(btn.dataset.goto)));
  $("refreshBtn").addEventListener("click", refreshAll);
  $("analyzeBtn").addEventListener("click", analyze);
  $("reloadVideos").addEventListener("click", refreshAll);
  $("videoFilter").addEventListener("change", renderVideos);
  $("addVideoBtn").addEventListener("click", addVideo);
  $("importCsvBtn").addEventListener("click", importCsv);
  $("collectBtn").addEventListener("click", () => collectVideos(false));
  $("collectCsvBtn").addEventListener("click", () => collectVideos(true));
  $("replicateBtn").addEventListener("click", replicate);
  setInterval(refreshAll, 7000);
}

bindEvents();
refreshAll().catch((err) => {
  document.body.insertAdjacentHTML("beforeend", `<pre class="status">${escapeHtml(err.message)}</pre>`);
});

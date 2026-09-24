'use strict';
/* =====================================================================
   Camera Laptop — Web App: Live + Tua lại (timeline) + Sự kiện + Cài đặt
   ===================================================================== */

// ------------------------------------------------------------- helpers
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const pad = (n) => String(n).padStart(2, '0');
const BLANK = 'data:image/gif;base64,R0lGODlhAQABAAAAACw=';

function fmtTime(t, withSec = true) {
  const d = new Date(t * 1000);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}` + (withSec ? `:${pad(d.getSeconds())}` : '');
}
function fmtDate(t) {
  const d = new Date(t * 1000);
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()}`;
}
function fmtStamp(t) {
  const d = new Date(t * 1000);
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}
function dayStart(t) { const d = new Date(t * 1000); d.setHours(0, 0, 0, 0); return d.getTime() / 1000; }
function dayKey(t) { const d = new Date(t * 1000); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; }
function addDays(t, n) { const d = new Date(t * 1000); d.setDate(d.getDate() + n); return d.getTime() / 1000; }
function dayLabel(t) {
  const today = dayStart(now());
  const ds = dayStart(t);
  if (ds === today) return 'Hôm nay';
  if (ds === dayStart(addDays(today, -1))) return 'Hôm qua';
  return fmtDate(t);
}
function fmtDur(sec) {
  sec = Math.max(0, Math.round(sec));
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60), s = sec % 60;
  if (m < 60) return s ? `${m}p${pad(s)}` : `${m} phút`;
  return `${Math.floor(m / 60)}h${pad(m % 60)}`;
}
function fmtBytes(b) {
  if (!b) return '0 B';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.min(u.length - 1, Math.floor(Math.log(b) / Math.log(1024)));
  return `${(b / 1024 ** i).toFixed(i >= 3 ? 2 : 1)} ${u[i]}`;
}
function fmtUptime(s) {
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return (d ? `${d} ngày ` : '') + `${pad(h)}h ${pad(m)}m`;
}
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const store = {
  get(k, d) { try { const v = localStorage.getItem('cam.' + k); return v === null ? d : JSON.parse(v); } catch (_) { return d; } },
  set(k, v) { try { localStorage.setItem('cam.' + k, JSON.stringify(v)); } catch (_) { /* ignore */ } },
};

async function api(path, opts = {}) {
  const r = await fetch(path, { credentials: 'same-origin', ...opts, headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) } });
  if (r.status === 401) { location.reload(); throw new Error('Phiên đăng nhập hết hạn'); }
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || r.statusText);
  return d;
}
const post = (path, body = {}) => api(path, { method: 'POST', body: JSON.stringify(body) });

function toast(msg, { err = false, link = null, ms = 3500 } = {}) {
  const el = document.createElement('div');
  el.className = 'toast' + (err ? ' err' : '');
  el.textContent = msg;
  if (link) {
    const a = document.createElement('a');
    a.href = link.href; a.textContent = link.text;
    if (link.download) a.setAttribute('download', '');
    el.appendChild(a);
  }
  $('#toasts').appendChild(el);
  setTimeout(() => el.remove(), ms);
}

function downloadUrl(href, name) {
  const a = document.createElement('a');
  a.href = href; a.download = name || '';
  document.body.appendChild(a); a.click(); a.remove();
}

const TYPE_META = {
  person: { label: 'Người', icon: 'i-person' },
  manual: { label: 'Thủ công', icon: 'i-hand' },
  motion: { label: 'Chuyển động', icon: 'i-motion' },
};
function tagHtml(type) {
  const m = TYPE_META[type] || { label: type, icon: 'i-motion' };
  return `<span class="tag tag-${esc(type)}"><svg><use href="#${m.icon}"/></svg>${m.label}</span>`;
}
function evTitle(ev) {
  if (ev.type === 'manual') return ev.label === 'record' ? 'Ghi clip thủ công' : 'Ảnh chụp thủ công';
  if (ev.type === 'person') return `Phát hiện người${ev.confidence ? ` · ${Math.round(ev.confidence * 100)}%` : ''}`;
  return 'Chuyển động';
}

// --------------------------------------------------------------- state
const S = {
  clockOffset: 0,
  mode: 'live',          // 'live' | 'playback'
  paused: false,
  speed: 1,
  playT: Date.now() / 1000,
  curSeg: null,
  pendingOffset: 0,
  segments: [],
  events: [],
  fetched: { start: 0, end: 0, at: 0, motion: true },
  fetching: null,
  dayEvents: [],
  dayEventsDay: 0,
  dayEventsAt: 0,
  daySummary: {},
  overlay: store.get('overlay', false),
  pipOn: store.get('pip', window.innerWidth > 720),
  showMotion: store.get('motion', true),
  status: null,
  settings: null,
  view: 'watch',
};
const now = () => Date.now() / 1000 + S.clockOffset;

const els = {
  stage: $('#stage'), live: $('#liveImg'), video: $('#pbVideo'), pip: $('#pip'), pipImg: $('#pipImg'),
  modeBadge: $('#modeBadge'), osdTime: $('#osdTime'), recBadge: $('#recBadge'), msg: $('#stageMsg'),
  btnPlay: $('#btnPlay'), btnLive: $('#btnLive'), speed: $('#speedSel'),
};

function showMsg(text) {
  if (!text) { els.msg.classList.add('hidden'); return; }
  els.msg.textContent = text;
  els.msg.classList.remove('hidden');
}

// ============================================================ TIMELINE
const ZOOMS = [300, 900, 1800, 3600, 3 * 3600, 6 * 3600, 12 * 3600, 24 * 3600];
const ZOOM_LABEL = { 300: '5 phút', 900: '15 phút', 1800: '30 phút', 3600: '1 giờ', 10800: '3 giờ', 21600: '6 giờ', 43200: '12 giờ', 86400: '24 giờ' };
const TICK_STEPS = [5, 10, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600];

const TL = {
  wrap: $('#tlWrap'),
  canvas: $('#tlCanvas'),
  ctx: $('#tlCanvas').getContext('2d'),
  span: store.get('span', 3600),
  center: Date.now() / 1000,
  dragging: false,
  pointers: new Map(),
  W: 0, H: 0,

  init() {
    new ResizeObserver(() => this.resize()).observe(this.wrap);
    this.resize();
    const w = this.wrap;
    w.addEventListener('pointerdown', (e) => this.onDown(e));
    w.addEventListener('pointermove', (e) => this.onMove(e));
    w.addEventListener('pointerup', (e) => this.onUp(e));
    w.addEventListener('pointercancel', (e) => this.onUp(e, true));
    w.addEventListener('wheel', (e) => {
      e.preventDefault();
      this.setSpan(this.span * (e.deltaY > 0 ? 1.25 : 0.8));
    }, { passive: false });
    $('#zoomIn').onclick = () => this.stepZoom(-1);
    $('#zoomOut').onclick = () => this.stepZoom(1);
    this.updateZoomLabel();
  },

  resize() {
    const dpr = window.devicePixelRatio || 1;
    const r = this.wrap.getBoundingClientRect();
    this.W = r.width; this.H = r.height;
    this.canvas.width = Math.round(r.width * dpr);
    this.canvas.height = Math.round(r.height * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.draw();
  },

  setSpan(v) {
    this.span = Math.min(86400, Math.max(120, v));
    store.set('span', this.span);
    this.updateZoomLabel();
    this.draw();
  },
  stepZoom(dir) {
    let idx = ZOOMS.findIndex((z) => z >= this.span - 1);
    if (idx < 0) idx = ZOOMS.length - 1;
    if (dir < 0) idx = ZOOMS[idx] < this.span - 1 ? idx : idx - 1;
    else idx = ZOOMS[idx] > this.span + 1 ? idx : idx + 1;
    this.setSpan(ZOOMS[Math.max(0, Math.min(ZOOMS.length - 1, idx))]);
  },
  updateZoomLabel() {
    const z = ZOOMS.find((v) => Math.abs(v - this.span) < 1);
    $('#zoomLabel').textContent = z ? ZOOM_LABEL[z] : (this.span < 3600 ? `${Math.round(this.span / 60)} phút` : `${(this.span / 3600).toFixed(1)} giờ`);
  },

  get left() { return this.center - this.span / 2; },
  get spp() { return this.span / Math.max(1, this.W); },
  x(t) { return (t - this.left) / this.spp; },

  onDown(e) {
    this.wrap.setPointerCapture(e.pointerId);
    this.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (this.pointers.size === 1) {
      this.startX = e.clientX; this.startCenter = this.center; this.moved = false;
    } else if (this.pointers.size === 2) {
      const [a, b] = [...this.pointers.values()];
      this.pinchDist = Math.hypot(a.x - b.x, a.y - b.y); this.pinchSpan = this.span; this.moved = true;
    }
  },
  onMove(e) {
    if (!this.pointers.has(e.pointerId)) return;
    this.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (this.pointers.size === 2) {
      const [a, b] = [...this.pointers.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      if (this.pinchDist > 10) this.setSpan(this.pinchSpan * this.pinchDist / Math.max(10, d));
      return;
    }
    const dx = e.clientX - this.startX;
    if (!this.moved && Math.abs(dx) < 5) return;
    this.moved = true;
    this.dragging = true;
    this.wrap.classList.add('dragging');
    this.center = Math.min(now(), this.startCenter - dx * this.spp);
    updateCursorLabel(this.center);
    this.draw();
  },
  onUp(e, cancelled = false) {
    if (!this.pointers.has(e.pointerId)) return;
    const wasSingle = this.pointers.size === 1;
    this.pointers.delete(e.pointerId);
    if (this.pointers.size > 0) return;
    this.wrap.classList.remove('dragging');
    if (cancelled) { this.dragging = false; return; }
    if (this.dragging) {
      this.dragging = false;
      Player.seek(this.center);
    } else if (wasSingle && !this.moved) {
      const r = this.wrap.getBoundingClientRect();
      Player.seek(this.left + (e.clientX - r.left) * this.spp);
    }
  },

  draw() {
    const { ctx, W, H } = this;
    if (!W) return;
    const tNow = now();
    const left = this.left, right = left + this.span;
    ctx.clearRect(0, 0, W, H);

    const LANE_EV = [22, 16], LANE_REC = [42, 16], LANE_MO = [62, 8];
    // Nền các làn
    ctx.fillStyle = '#18202a';
    ctx.fillRect(0, LANE_REC[0], W, LANE_REC[1]);
    ctx.fillStyle = '#141b24';
    ctx.fillRect(0, LANE_EV[0], W, LANE_EV[1]);
    if (S.showMotion) ctx.fillRect(0, LANE_MO[0], W, LANE_MO[1]);

    // Đoạn đã ghi
    ctx.fillStyle = '#2f6fe0';
    const lastSeg = S.segments[S.segments.length - 1];
    for (const s of S.segments) {
      let end = s.end;
      if (s === lastSeg && !s.complete && S.status && S.status.continuous_recording) end = Math.max(end, tNow);
      if (end < left || s.start > right) continue;
      const x1 = Math.max(0, this.x(s.start)), x2 = Math.min(W, this.x(end));
      ctx.fillRect(x1, LANE_REC[0], Math.max(1, x2 - x1), LANE_REC[1]);
    }
    // Sự kiện
    for (const ev of S.events) {
      if (ev.end < left - 5 || ev.start > right) continue;
      if (ev.type === 'motion') {
        if (!S.showMotion) continue;
        ctx.fillStyle = '#14b8a6';
        const x1 = this.x(ev.start), x2 = this.x(ev.end);
        ctx.fillRect(x1, LANE_MO[0], Math.max(2, x2 - x1), LANE_MO[1]);
      } else {
        ctx.fillStyle = ev.type === 'manual' ? '#a78bfa' : '#f59e0b';
        const x1 = this.x(ev.start), x2 = this.x(Math.max(ev.end, ev.start + 1));
        ctx.fillRect(x1, LANE_EV[0], Math.max(3, x2 - x1), LANE_EV[1]);
      }
    }

    // Vùng tương lai
    if (tNow < right) {
      const xn = Math.max(0, this.x(tNow));
      ctx.fillStyle = 'rgba(11,15,20,0.72)';
      ctx.fillRect(xn, 18, W - xn, H - 18);
      ctx.strokeStyle = 'rgba(239,68,68,0.55)';
      ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(xn + 0.5, 18); ctx.lineTo(xn + 0.5, H); ctx.stroke();
      ctx.setLineDash([]);
    }

    // Vạch chia thời gian
    const spp = this.spp;
    const step = TICK_STEPS.find((s) => s / spp >= 72) || 21600;
    const minor = step >= 3600 ? step / 6 : step >= 600 ? step / 5 : step / 5;
    ctx.fillStyle = '#8b98a5';
    ctx.strokeStyle = '#2b3645';
    ctx.font = '11px ui-monospace, Consolas, monospace';
    ctx.textAlign = 'center';
    const tzOff = new Date(left * 1000).getTimezoneOffset() * 60;
    // Căn vạch theo giờ địa phương (vd. 00:00, 03:00… thay vì theo UTC)
    const align = (t, st) => Math.ceil((t - tzOff) / st) * st + tzOff;
    ctx.beginPath();
    for (let t = align(left, minor); t <= right; t += minor) {
      const x = Math.round(this.x(t)) + 0.5;
      ctx.moveTo(x, 16); ctx.lineTo(x, 20);
    }
    ctx.stroke();
    ctx.strokeStyle = '#3b4859';
    ctx.beginPath();
    for (let t = align(left, step); t <= right; t += step) {
      const x = Math.round(this.x(t)) + 0.5;
      ctx.moveTo(x, 14); ctx.lineTo(x, H);
      const d = new Date(t * 1000);
      const midnight = d.getHours() === 0 && d.getMinutes() === 0 && d.getSeconds() === 0;
      const label = midnight ? `${pad(d.getDate())}/${pad(d.getMonth() + 1)}` : fmtTime(t, step < 60);
      ctx.fillStyle = midnight ? '#e6edf3' : '#8b98a5';
      ctx.fillText(label, x, 11);
    }
    ctx.globalAlpha = 0.35;
    ctx.stroke();
    ctx.globalAlpha = 1;
  },
};

function updateCursorLabel(t) {
  $('#tlCursorLabel').textContent = fmtTime(t);
  const lbl = dayLabel(t);
  const el = $('#dateLabel');
  if (el.textContent !== lbl) {
    el.textContent = lbl;
    loadDayEvents();
  }
}

// ----------------------------------------------------- timeline data
async function fetchTimeline(force = false) {
  const span = Math.max(TL.span, 3600);
  const want0 = TL.center - span, want1 = TL.center + span;
  const f = S.fetched;
  const tNow = now();
  const stale = want1 >= tNow - 60 ? 8 : 120;
  if (!force && f.start <= want0 && f.end >= Math.min(want1, tNow) && Date.now() / 1000 - f.at < stale && f.motion === S.showMotion) return;
  if (S.fetching) return S.fetching;
  const start = TL.center - span * 2, end = TL.center + span * 2;
  const types = S.showMotion ? '' : '&types=person,manual';
  S.fetching = api(`/api/timeline?start=${start.toFixed(0)}&end=${end.toFixed(0)}${types}`)
    .then((d) => {
      S.segments = d.segments;
      S.events = d.events;
      S.fetched = { start, end, at: Date.now() / 1000, motion: S.showMotion };
      TL.draw();
    })
    .catch(() => {})
    .finally(() => { S.fetching = null; });
  return S.fetching;
}

async function findSegmentAfter(t) {
  const d = await api(`/api/timeline?start=${Math.floor(t)}&end=${Math.ceil(now())}&events=0`);
  return d.segments.find((s) => s.end > t) || null;
}

// ============================================================== PLAYER
const Player = {
  init() {
    const v = els.video;
    v.addEventListener('loadedmetadata', () => {
      let off = S.pendingOffset;
      if (isFinite(v.duration) && off > v.duration - 0.3) off = Math.max(0, v.duration - 0.3);
      try { v.currentTime = off; } catch (_) { /* ignore */ }
      v.playbackRate = S.speed;
      if (!S.paused) v.play().catch(() => {});
    });
    v.addEventListener('playing', () => showMsg(''));
    v.addEventListener('seeked', () => { if (S.paused) showMsg(''); });
    v.addEventListener('waiting', () => { if (S.mode === 'playback') showMsg('Đang tải…'); });
    v.addEventListener('ended', () => this.onEnded());
    v.addEventListener('error', () => {
      if (S.mode !== 'playback' || !v.getAttribute('src')) return;
      toast('Không phát được đoạn ghi này, chuyển sang đoạn kế tiếp', { err: true });
      this.onEnded();
    });
    els.live.addEventListener('load', () => { if (S.mode === 'live') showMsg(''); });
    els.live.addEventListener('error', () => {
      if (S.mode !== 'live' || S.paused || document.hidden) return;
      showMsg('Mất kết nối camera, đang thử lại…');
      clearTimeout(this._retry);
      this._retry = setTimeout(() => { if (S.mode === 'live' && !S.paused) this.startLive(); }, 2500);
    });
    els.pip.addEventListener('click', () => this.goLive());
  },

  startLive() {
    if (document.hidden) return;
    els.live.src = `/stream?overlay=${S.overlay ? 1 : 0}&_=${Date.now()}`;
  },
  stopLive() { els.live.src = BLANK; },
  updatePip() {
    const show = S.mode === 'playback' && S.pipOn && !document.hidden;
    els.pip.classList.toggle('hidden', !show);
    if (show && !els.pipImg.src.includes('/stream')) els.pipImg.src = `/stream?fps=6&q=50&_=${Date.now()}`;
    if (!show && els.pipImg.src.includes('/stream')) els.pipImg.src = BLANK;
  },

  goLive() {
    S.mode = 'live';
    S.paused = false;
    S.curSeg = null;
    const v = els.video;
    v.pause();
    v.removeAttribute('src');
    v.dataset.src = '';
    v.load();
    v.classList.add('hidden');
    els.live.classList.remove('hidden');
    showMsg('');
    this.startLive();
    this.updatePip();
    TL.center = now();
    updateModeUi();
  },

  enterPlayback() {
    if (S.mode === 'playback') return;
    S.mode = 'playback';
    this.stopLive();
    els.live.classList.add('hidden');
    els.video.classList.remove('hidden');
    this.updatePip();
    updateModeUi();
  },

  async seek(t) {
    const tNow = now();
    t = Math.min(t, tNow);
    if (tNow - t < 4) return this.goLive();
    TL.center = t;
    updateCursorLabel(t);
    await fetchTimeline();
    let seg = S.segments.find((s) => s.start <= t && t < s.end);
    if (!seg) {
      let next = S.segments.find((s) => s.start > t);
      if (!next) next = await findSegmentAfter(t).catch(() => null);
      if (next && next.start < tNow - 4) {
        toast(`Không có ghi hình lúc ${fmtTime(t)} → chuyển tới ${fmtTime(next.start)}${dayStart(next.start) !== dayStart(t) ? ' ' + fmtDate(next.start) : ''}`);
        t = next.start;
        seg = next;
        TL.center = t;
        fetchTimeline(true);
      } else {
        toast('Không có ghi hình sau thời điểm này — về xem trực tiếp');
        return this.goLive();
      }
    }
    this.enterPlayback();
    this.loadSeg(seg, t - seg.start);
  },

  loadSeg(seg, offset) {
    const v = els.video;
    S.curSeg = seg;
    S.playT = seg.start + offset;
    const src = `/api/segment/${seg.id}` + (seg.complete ? '' : `?v=${Math.floor(seg.end)}`);
    if (v.dataset.src === src && v.readyState >= 1) {
      try { v.currentTime = Math.max(0, offset); } catch (_) { /* ignore */ }
      if (!S.paused) v.play().catch(() => {});
      return;
    }
    showMsg('Đang tải…');
    S.pendingOffset = Math.max(0, offset);
    v.dataset.src = src;
    v.src = src;
  },

  async onEnded() {
    const cur = S.curSeg;
    if (!cur || S.mode !== 'playback') return;
    const t = cur.start + (els.video.currentTime || 0);
    await fetchTimeline(true);
    if (!cur.complete) {
      if (now() - t < 10) return this.goLive();
      const upd = S.segments.find((s) => s.id === cur.id);
      if (upd && upd.end > t + 2) return this.loadSeg(upd, t - upd.start);
    }
    const next = S.segments.find((s) => s.start > cur.start && s.id !== cur.id && s.end > t);
    if (next) return this.loadSeg(next, Math.max(0, t - next.start));
    const later = await findSegmentAfter(cur.end).catch(() => null);
    if (later && later.id !== cur.id) return this.loadSeg(later, 0);
    this.goLive();
  },

  togglePause() {
    if (S.mode === 'live') {
      S.paused = !S.paused;
      // Tạm dừng live = giữ khung hình hiện tại
      if (S.paused) els.live.src = `/snapshot.jpg?overlay=${S.overlay ? 1 : 0}&_=${Date.now()}`;
      else this.startLive();
    } else {
      S.paused = !S.paused;
      if (S.paused) els.video.pause(); else els.video.play().catch(() => {});
    }
    updateModeUi();
  },

  skip(sec) {
    const base = S.mode === 'live' ? now() : S.playT;
    this.seek(base + sec);
  },

  setSpeed(v) {
    S.speed = v;
    els.video.playbackRate = v;
  },

  jumpEvent(dir) {
    const all = [...S.events, ...S.dayEvents].filter((e) => e.type !== 'motion');
    const uniq = [...new Map(all.map((e) => [e.id, e])).values()].sort((a, b) => a.start - b.start);
    const t = S.mode === 'live' ? now() : S.playT;
    const ev = dir < 0 ? [...uniq].reverse().find((e) => e.start < t - 6) : uniq.find((e) => e.start > t + 1);
    if (!ev) return toast(dir < 0 ? 'Không còn sự kiện trước đó' : 'Không còn sự kiện sau đó');
    this.seek(ev.start - 3);
  },
};

function updateModeUi() {
  const live = S.mode === 'live';
  els.modeBadge.textContent = live ? (S.paused ? '❚❚ LIVE' : '● LIVE') : `▶ XEM LẠI${S.speed !== 1 ? ' ' + S.speed + '×' : ''}`;
  els.modeBadge.classList.toggle('pb', !live);
  els.btnLive.classList.toggle('active', live && !S.paused);
  els.btnPlay.querySelector('use').setAttribute('href', S.paused ? '#i-play' : '#i-pause');
  els.speed.disabled = live;
  $('#btnFwd').disabled = live;
  $('#btnAI').disabled = !live;
  $('#btnRec').disabled = !live;
}

// ------------------------------------------------------- render loop
let lastDraw = 0;
function tick() {
  const tNow = now();
  if (S.mode === 'live') {
    S.playT = tNow;
  } else if (S.curSeg) {
    S.playT = S.curSeg.start + (els.video.currentTime || 0);
  }
  if (!TL.dragging) {
    TL.center = S.playT;
    updateCursorLabel(S.playT);
  }
  els.osdTime.textContent = `${fmtDate(S.playT)} ${fmtTime(S.playT)}`;
  if (S.status && S.status.manual_recording) {
    const el = Math.max(0, tNow - S.status.manual_started);
    els.recBadge.textContent = `● REC ${pad(Math.floor(el / 60))}:${pad(Math.floor(el % 60))}`;
  }
  if (performance.now() - lastDraw > 200) {
    lastDraw = performance.now();
    TL.draw();
    fetchTimeline();
    highlightDayEvent();
  }
  requestAnimationFrame(tick);
}

// ======================================================== DAY EVENTS
async function loadDayEvents(force = false) {
  const ds = dayStart(TL.center);
  if (!force && ds === S.dayEventsDay && Date.now() - S.dayEventsAt < 15000) return;
  S.dayEventsDay = ds;
  S.dayEventsAt = Date.now();
  try {
    const d = await api(`/api/events?start=${ds}&end=${addDays(ds, 1)}&types=person,manual&limit=300`);
    if (S.dayEventsDay !== ds) return;
    S.dayEvents = d.events;
    renderDayEvents();
  } catch (_) { /* ignore */ }
}

function renderDayEvents() {
  const box = $('#dayEvents');
  $('#dayEvCount').textContent = S.dayEvents.length;
  if (!S.dayEvents.length) {
    box.innerHTML = '<div class="empty">Chưa có sự kiện nào trong ngày này</div>';
    return;
  }
  box.innerHTML = S.dayEvents.map((ev) => `
    <button class="dev" data-id="${ev.id}" data-start="${ev.start}" data-end="${ev.end}">
      <div class="thumb">${ev.snapshot_url ? `<img loading="lazy" src="${esc(ev.snapshot_url)}" alt="">` : `<svg><use href="#${TYPE_META[ev.type]?.icon || 'i-motion'}"/></svg>`}</div>
      <div class="dev-info">
        <span class="dev-time">${fmtTime(ev.start)}</span>
        <span class="dev-meta">${tagHtml(ev.type)}${ev.end - ev.start >= 1 ? fmtDur(ev.end - ev.start) : ''}</span>
      </div>
    </button>`).join('');
}

function highlightDayEvent() {
  const t = S.playT;
  $$('#dayEvents .dev').forEach((el) => {
    const on = S.mode === 'playback' && t >= +el.dataset.start - 4 && t <= +el.dataset.end + 4;
    el.classList.toggle('active', on);
  });
}

$('#dayEvents').addEventListener('click', (e) => {
  const el = e.target.closest('.dev');
  if (el) Player.seek(+el.dataset.start - 3);
});

// ============================================================ CALENDAR
const Cal = {
  month: null,
  async open() {
    const pop = $('#calPop');
    const r = $('#dateBtn').getBoundingClientRect();
    pop.style.left = `${Math.max(8, Math.min(window.innerWidth - 300, r.left))}px`;
    pop.style.top = `${r.bottom + 6}px`;
    const d = new Date(TL.center * 1000);
    this.month = new Date(d.getFullYear(), d.getMonth(), 1);
    pop.classList.remove('hidden');
    this.render();
    try { S.daySummary = await api('/api/days'); this.render(); } catch (_) { /* ignore */ }
  },
  close() { $('#calPop').classList.add('hidden'); },
  render() {
    const m = this.month;
    $('#calTitle').textContent = `Tháng ${m.getMonth() + 1}/${m.getFullYear()}`;
    const first = new Date(m);
    const startDow = (first.getDay() + 6) % 7; // Thứ 2 đầu tuần
    const cur = new Date(first); cur.setDate(1 - startDow);
    const todayKey = dayKey(now()), selKey = dayKey(TL.center);
    let html = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN'].map((w) => `<span class="wd">${w}</span>`).join('');
    for (let i = 0; i < 42; i++) {
      const t = cur.getTime() / 1000;
      const k = dayKey(t);
      const info = S.daySummary[k];
      const cls = [
        cur.getMonth() !== m.getMonth() ? 'other' : '',
        k === todayKey ? 'today' : '', k === selKey ? 'sel' : '',
        info && info.recorded ? 'has' : '', info && info.events ? 'has has-ev' : '',
      ].join(' ');
      html += `<button class="${cls}" data-t="${t}" ${t > now() ? 'disabled' : ''} title="${info ? `${fmtDur(info.recorded)} ghi hình · ${info.events} sự kiện` : ''}">${cur.getDate()}</button>`;
      cur.setDate(cur.getDate() + 1);
    }
    $('#calGrid').innerHTML = html;
  },
};
$('#dateBtn').onclick = (e) => { e.stopPropagation(); $('#calPop').classList.contains('hidden') ? Cal.open() : Cal.close(); };
$('#calPrev').onclick = (e) => { e.stopPropagation(); Cal.month.setMonth(Cal.month.getMonth() - 1); Cal.render(); };
$('#calNext').onclick = (e) => { e.stopPropagation(); Cal.month.setMonth(Cal.month.getMonth() + 1); Cal.render(); };
$('#calGrid').onclick = (e) => {
  const b = e.target.closest('button[data-t]');
  if (!b || b.disabled) return;
  Cal.close();
  jumpToDay(+b.dataset.t);
};
document.addEventListener('click', (e) => { if (!e.target.closest('#calPop')) Cal.close(); });

async function jumpToDay(ds) {
  ds = dayStart(ds);
  if (ds === dayStart(now())) {
    // Hôm nay: nếu đang live thì giữ live, nếu đang xem lại thì nhảy về đầu ngày có ghi hình
    if (S.mode === 'live') return;
  }
  if (ds > now()) return;
  try {
    const d = await api(`/api/timeline?start=${ds}&end=${addDays(ds, 1)}&events=0`);
    if (!d.segments.length) {
      TL.center = Math.min(now(), ds + 12 * 3600);
      updateCursorLabel(TL.center);
      if (S.mode === 'live') Player.enterPlayback();
      els.video.pause();
      S.paused = true;
      updateModeUi();
      return toast(`Không có ghi hình ngày ${fmtDate(ds)}`);
    }
    Player.seek(Math.max(ds, d.segments[0].start));
  } catch (err) { toast(err.message, { err: true }); }
}
$('#dayPrev').onclick = () => jumpToDay(addDays(dayStart(TL.center), -1));
$('#dayNext').onclick = () => {
  const next = addDays(dayStart(TL.center), 1);
  if (next > now()) return;
  if (next === dayStart(now())) return Player.goLive();
  jumpToDay(next);
};

// ============================================================ CONTROLS
els.btnPlay.onclick = () => Player.togglePause();
$('#btnBack').onclick = () => Player.skip(-10);
$('#btnFwd').onclick = () => Player.skip(10);
els.btnLive.onclick = () => Player.goLive();
els.speed.onchange = () => { Player.setSpeed(+els.speed.value); updateModeUi(); };
$('#btnPrevEv').onclick = () => Player.jumpEvent(-1);
$('#btnNextEv').onclick = () => Player.jumpEvent(1);

function syncToggles() {
  $('#btnAI').classList.toggle('on', S.overlay);
  $('#btnPip').classList.toggle('on', S.pipOn);
  $('#showMotion').checked = S.showMotion;
}
$('#btnAI').onclick = () => {
  S.overlay = !S.overlay; store.set('overlay', S.overlay); syncToggles();
  if (S.mode === 'live' && !S.paused) Player.startLive();
  toast(S.overlay ? 'Đang hiện khung nhận diện AI' : 'Đã ẩn khung nhận diện AI');
};
$('#btnPip').onclick = () => { S.pipOn = !S.pipOn; store.set('pip', S.pipOn); syncToggles(); Player.updatePip(); };
$('#showMotion').onchange = (e) => { S.showMotion = e.target.checked; store.set('motion', S.showMotion); fetchTimeline(true); };

$('#btnSnap').onclick = async () => {
  if (S.mode === 'live') {
    try {
      const d = await post('/api/snapshot');
      toast('Đã chụp & lưu ảnh', { link: { href: d.event.snapshot_url + '?download=1', text: 'Tải về', download: true } });
      loadDayEvents(true);
    } catch (err) { toast(err.message, { err: true }); }
    return;
  }
  // Đang xem lại: chụp khung hình của video
  const v = els.video;
  if (!v.videoWidth) return;
  const c = document.createElement('canvas');
  c.width = v.videoWidth; c.height = v.videoHeight;
  c.getContext('2d').drawImage(v, 0, 0);
  c.toBlob((b) => {
    const url = URL.createObjectURL(b);
    downloadUrl(url, `playback_${fmtStamp(S.playT)}.jpg`);
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }, 'image/jpeg', 0.92);
};

$('#btnRec').onclick = async () => {
  try {
    if (S.status && S.status.manual_recording) {
      const d = await post('/api/record/stop');
      toast('Đã lưu clip', d.event && d.event.clip_url ? { link: { href: d.event.clip_url + '?download=1', text: 'Tải về', download: true } } : {});
      loadDayEvents(true);
    } else {
      const d = await post('/api/record/start');
      if (!d.ok) throw new Error('Không thể bắt đầu ghi');
      toast('Bắt đầu ghi clip (tối đa 10 phút)');
    }
    await refreshStatus();
  } catch (err) { toast(err.message, { err: true }); }
};

function toggleFullscreen() {
  const st = els.stage;
  if (document.fullscreenElement || document.webkitFullscreenElement) {
    (document.exitFullscreen || document.webkitExitFullscreen).call(document);
  } else if (st.requestFullscreen) {
    st.requestFullscreen().catch(() => {});
  } else if (st.webkitRequestFullscreen) {
    st.webkitRequestFullscreen();
  } else if (S.mode === 'playback' && els.video.webkitEnterFullscreen) {
    els.video.webkitEnterFullscreen();
  }
}
$('#btnFull').onclick = toggleFullscreen;
els.stage.addEventListener('dblclick', toggleFullscreen);

// --------------------------------------------------------- export modal
function openModal(id) { $(id).classList.remove('hidden'); }
function closeModal(el) {
  el.classList.add('hidden');
  const v = el.querySelector('video');
  if (v) { v.pause(); v.removeAttribute('src'); v.load(); }
}
$$('.modal').forEach((m) => m.addEventListener('click', (e) => {
  if (e.target === m || e.target.closest('[data-close]')) closeModal(m);
}));

function toTimeInput(t) { const d = new Date(t * 1000); return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`; }
function fromInputs(dateStr, timeStr) {
  const [y, mo, d] = dateStr.split('-').map(Number);
  const [h, mi, s] = timeStr.split(':').map(Number);
  return new Date(y, mo - 1, d, h, mi, s || 0).getTime() / 1000;
}
$('#btnExport').onclick = () => {
  const base = S.mode === 'live' ? now() - 60 : S.playT - 30;
  $('#expDate').value = dayKey(base);
  $('#expFrom').value = toTimeInput(base);
  $('#expTo').value = toTimeInput(Math.min(now(), base + 60));
  openModal('#exportModal');
};
$('#expQuick').onclick = (e) => {
  const b = e.target.closest('[data-dur]');
  if (!b) return;
  const start = fromInputs($('#expDate').value, $('#expFrom').value);
  $('#expTo').value = toTimeInput(Math.min(now(), start + +b.dataset.dur));
};
$('#expGo').onclick = async () => {
  const start = fromInputs($('#expDate').value, $('#expFrom').value);
  let end = fromInputs($('#expDate').value, $('#expTo').value);
  if (end <= start) end += 86400; // qua nửa đêm
  if (end - start > 3600) return toast('Tối đa 60 phút mỗi lần xuất', { err: true });
  const btn = $('#expGo');
  btn.disabled = true;
  toast('Đang ghép video…', { ms: 2500 });
  try {
    const r = await fetch(`/api/export?start=${start}&end=${end}`, { credentials: 'same-origin' });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || 'Xuất clip thất bại');
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    downloadUrl(url, `cam_${fmtStamp(start)}.mp4`);
    setTimeout(() => URL.revokeObjectURL(url), 30000);
    closeModal($('#exportModal'));
    toast(`Đã xuất ${fmtDur(end - start)} video (${fmtBytes(blob.size)})`);
  } catch (err) { toast(err.message, { err: true }); }
  btn.disabled = false;
};

// ================================================================ EVENTS VIEW
const EV = { range: 'today', types: new Set(['person', 'manual']), cursor: null, items: [], loading: false };

function evRange() {
  const t = now(), ds = dayStart(t);
  switch (EV.range) {
    case 'yesterday': return [addDays(ds, -1), ds];
    case '7d': return [addDays(ds, -6), t + 60];
    case 'all': return [0, t + 60];
    default: return [ds, t + 60];
  }
}

async function loadEvents(reset = true) {
  if (EV.loading) return;
  EV.loading = true;
  const [start, end0] = evRange();
  const end = reset ? end0 : EV.cursor;
  const types = [...EV.types].join(',');
  if (reset) { EV.items = []; $('#evGrid').innerHTML = '<div class="empty">Đang tải…</div>'; }
  try {
    if (!types) { EV.items = []; renderEvents(false); return; }
    const d = await api(`/api/events?start=${start}&end=${end}&types=${types}&limit=60`);
    EV.items = reset ? d.events : EV.items.concat(d.events);
    EV.cursor = d.events.length ? d.events[d.events.length - 1].start - 0.001 : null;
    renderEvents(d.events.length === 60);
  } catch (err) {
    toast(err.message, { err: true });
  } finally { EV.loading = false; }
}

function renderEvents(hasMore) {
  const grid = $('#evGrid');
  $('#evMore').classList.toggle('hidden', !hasMore);
  if (!EV.items.length) { grid.innerHTML = '<div class="empty">Không có sự kiện nào</div>'; return; }
  let html = '', lastDay = '';
  for (const ev of EV.items) {
    const dk = dayKey(ev.start);
    if (dk !== lastDay) { lastDay = dk; html += `<div class="ev-day">${dayLabel(ev.start)} · ${fmtDate(ev.start)}</div>`; }
    const dur = ev.end - ev.start;
    html += `
      <div class="ev-card" data-id="${ev.id}">
        <div class="thumb" data-act="view">
          ${ev.snapshot_url ? `<img loading="lazy" src="${esc(ev.snapshot_url)}" alt="">` : `<svg><use href="#${TYPE_META[ev.type]?.icon || 'i-motion'}"/></svg>`}
          ${tagHtml(ev.type)}
          ${dur >= 1 ? `<span class="dur">${fmtDur(dur)}</span>` : ''}
        </div>
        <div class="ev-body">
          <div><b>${fmtTime(ev.start)}</b><small>${esc(evTitle(ev))}</small></div>
          <div class="ev-actions">
            <button class="icon-btn" data-act="play" title="Xem lại trên timeline"><svg><use href="#i-play"/></svg></button>
            ${ev.snapshot_url ? `<button class="icon-btn" data-act="dl-snap" title="Tải ảnh"><svg><use href="#i-camera"/></svg></button>` : ''}
            ${ev.clip_url ? `<button class="icon-btn" data-act="dl-clip" title="Tải clip"><svg><use href="#i-download"/></svg></button>` : ''}
            <button class="icon-btn" data-act="del" title="Xoá"><svg><use href="#i-trash"/></svg></button>
          </div>
        </div>
      </div>`;
  }
  grid.innerHTML = html;
}

$('#evGrid').addEventListener('click', async (e) => {
  const actEl = e.target.closest('[data-act]');
  const card = e.target.closest('.ev-card');
  if (!actEl || !card) return;
  const ev = EV.items.find((x) => x.id === +card.dataset.id);
  if (!ev) return;
  switch (actEl.dataset.act) {
    case 'play':
      switchView('watch');
      Player.seek(ev.start - 3);
      break;
    case 'view': openViewer(ev); break;
    case 'dl-snap': downloadUrl(ev.snapshot_url + '?download=1'); break;
    case 'dl-clip': downloadUrl(ev.clip_url + '?download=1'); break;
    case 'del':
      if (!confirm(`Xoá sự kiện lúc ${fmtTime(ev.start)} ${fmtDate(ev.start)} (kèm ảnh/clip)?`)) return;
      try {
        await post(`/api/events/${ev.id}/delete`);
        EV.items = EV.items.filter((x) => x.id !== ev.id);
        card.remove();
        loadDayEvents(true);
        toast('Đã xoá sự kiện');
      } catch (err) { toast(err.message, { err: true }); }
      break;
  }
});

function openViewer(ev) {
  $('#viewerTitle').textContent = `${evTitle(ev)} · ${fmtTime(ev.start)} ${fmtDate(ev.start)}`;
  const body = $('#viewerBody');
  if (ev.clip_url) {
    body.innerHTML = `<video controls autoplay playsinline muted src="${esc(ev.clip_url)}" ${ev.snapshot_url ? `poster="${esc(ev.snapshot_url)}"` : ''}></video>`;
    body.querySelector('video').addEventListener('error', () => {
      body.innerHTML = ev.snapshot_url ? `<img src="${esc(ev.snapshot_url)}" alt="">` : '';
      toast('Clip định dạng cũ không phát được trên trình duyệt — bấm "Tải clip" để xem', { err: true, ms: 5000 });
    });
  } else if (ev.snapshot_url) {
    body.innerHTML = `<img src="${esc(ev.snapshot_url)}" alt="">`;
  } else {
    body.innerHTML = '<div class="empty">Không có ảnh / clip — hãy xem lại trên timeline</div>';
  }
  const acts = $('#viewerActions');
  acts.innerHTML = `
    <button class="btn" data-v="play"><svg><use href="#i-play"/></svg>Xem trên timeline</button>
    ${ev.snapshot_url ? `<a class="btn" href="${esc(ev.snapshot_url)}?download=1" download><svg><use href="#i-camera"/></svg>Tải ảnh</a>` : ''}
    ${ev.clip_url ? `<a class="btn primary" href="${esc(ev.clip_url)}?download=1" download><svg><use href="#i-download"/></svg>Tải clip</a>` : ''}`;
  acts.querySelector('[data-v="play"]').onclick = () => {
    closeModal($('#viewer'));
    switchView('watch');
    Player.seek(ev.start - 3);
  };
  openModal('#viewer');
}

$('#rangeChips').onclick = (e) => {
  const b = e.target.closest('[data-range]');
  if (!b) return;
  EV.range = b.dataset.range;
  $$('#rangeChips .chip').forEach((c) => c.classList.toggle('active', c === b));
  loadEvents(true);
};
$('#typeChips').onclick = (e) => {
  const b = e.target.closest('[data-type]');
  if (!b) return;
  const t = b.dataset.type;
  EV.types.has(t) ? EV.types.delete(t) : EV.types.add(t);
  b.classList.toggle('active', EV.types.has(t));
  loadEvents(true);
};
$('#evMore').onclick = () => loadEvents(false);

// ============================================================ SETTINGS
const OUT_FMT = {
  confidence_threshold: (v) => `${Math.round(v * 100)}%`,
  motion_threshold: (v) => v,
  min_motion_area: (v) => `${v} px²`,
  cooldown_seconds: (v) => `${v}s`,
  record_on_detect_seconds: (v) => `${v}s`,
  retention_max_days: (v) => `${v} ngày`,
  retention_max_gb: (v) => `${v} GB`,
};

function renderSettings() {
  const st = S.settings;
  if (!st) return;
  $$('[data-key]').forEach((el) => {
    const k = el.dataset.key;
    if (!(k in st) || document.activeElement === el) return;
    if (el.type === 'checkbox') el.checked = !!st[k];
    else el.value = st[k];
    const out = $(`[data-out="${k}"]`);
    if (out) out.textContent = OUT_FMT[k] ? OUT_FMT[k](st[k]) : st[k];
  });
  $('#tgNote').textContent = st.telegram_configured ? '' : 'Telegram chưa được cấu hình — chạy "python setup_telegram.py" để nhận cảnh báo.';
  updateArmUi(st.armed);
}

let saveTimer = null;
const pending = {};
function queueSave(key, value) {
  pending[key] = value;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    const body = { ...pending };
    Object.keys(pending).forEach((k) => delete pending[k]);
    try {
      S.settings = await post('/api/settings', body);
      renderSettings();
      toast('Đã lưu thiết lập', { ms: 1500 });
    } catch (err) { toast(err.message, { err: true }); }
  }, 350);
}
$$('[data-key]').forEach((el) => {
  const k = el.dataset.key;
  el.addEventListener('input', () => {
    const out = $(`[data-out="${k}"]`);
    if (out && el.type === 'range') out.textContent = OUT_FMT[k] ? OUT_FMT[k](+el.value) : el.value;
  });
  el.addEventListener('change', () => queueSave(k, el.type === 'checkbox' ? el.checked : +el.value));
});

async function loadSettings() {
  try { S.settings = await api('/api/settings'); renderSettings(); } catch (_) { /* ignore */ }
}

function renderSystem() {
  const s = S.status;
  if (!s) return;
  const used = s.storage_used, lim = s.storage_limit;
  const pct = lim ? Math.min(100, (used / lim) * 100) : 0;
  const bar = $('#storageBar');
  bar.style.width = `${pct}%`;
  bar.classList.toggle('warn', pct > 85);
  $('#storageText').textContent = `${fmtBytes(used)} / ${lim ? fmtBytes(lim) : '∞'}`;
  $('#diskText').textContent = `Ổ đĩa trống ${fmtBytes(s.disk_free)}`;
  $('#sysInfo').innerHTML = `
    <dt>Camera</dt><dd>${s.camera_connected ? `🟢 ${s.resolution} · ${s.camera_fps} FPS` : '🔴 Mất kết nối'}</dd>
    <dt>Ghi 24/7</dt><dd>${s.continuous_recording ? 'Đang ghi' : 'Tắt'}</dd>
    <dt>Hoạt động</dt><dd>${fmtUptime(s.uptime)}</dd>
    <dt>CPU / RAM</dt><dd>${Math.round(s.cpu)}% / ${Math.round(s.ram)}%</dd>
    <dt>Phát hiện gần nhất</dt><dd>${s.last_detection ? `${fmtTime(s.last_detection)} ${fmtDate(s.last_detection)}` : '—'}</dd>`;
  const urls = s.urls || {};
  const rows = [];
  if (urls.local_url) rows.push(['Wi-Fi', urls.local_url]);
  if (urls.public_url && urls.public_url !== urls.local_url) rows.push(['Từ xa', urls.public_url]);
  $('#links').innerHTML = rows.map(([k, u]) => `
    <div class="link-row"><small>${k}</small><code>${esc(u)}</code><button class="btn sm" data-copy="${esc(u)}">Chép</button></div>`).join('');
}
$('#links').onclick = async (e) => {
  const b = e.target.closest('[data-copy]');
  if (!b) return;
  try { await navigator.clipboard.writeText(b.dataset.copy); toast('Đã chép link'); } catch (_) { toast('Không chép được', { err: true }); }
};
$('#logoutBtn').onclick = async () => {
  await post('/api/logout').catch(() => {});
  location.href = '/';
};

// ============================================================== STATUS
function updateArmUi(armed) {
  const b = $('#armBtn');
  b.classList.toggle('off', !armed);
  b.querySelector('use').setAttribute('href', armed ? '#i-shield' : '#i-shield-off');
  b.querySelector('span').textContent = armed ? 'Đang bảo vệ' : 'Tắt báo động';
}
$('#armBtn').onclick = async () => {
  const armed = !(S.status ? S.status.armed : true);
  try {
    S.settings = await post('/api/settings', { armed });
    renderSettings();
    if (S.status) S.status.armed = armed;
    toast(armed ? 'Đã bật chế độ bảo vệ' : 'Đã tắt cảnh báo Telegram');
  } catch (err) { toast(err.message, { err: true }); }
};

async function refreshStatus() {
  try {
    const s = await api('/api/status');
    S.clockOffset = s.now - Date.now() / 1000;
    S.status = s;
    const dot = $('#connDot');
    dot.classList.toggle('on', s.camera_connected);
    dot.classList.toggle('off', !s.camera_connected);
    dot.title = s.camera_connected ? `Camera đang hoạt động · ${s.camera_fps} FPS` : 'Mất kết nối camera';
    updateArmUi(s.armed);
    els.recBadge.classList.toggle('hidden', !s.manual_recording);
    $('#btnRec').classList.toggle('recording', s.manual_recording);
    if (S.view === 'settings') renderSystem();
  } catch (_) {
    const dot = $('#connDot');
    dot.classList.remove('on'); dot.classList.add('off');
  }
}

// =============================================================== VIEWS
function switchView(v) {
  S.view = v;
  $$('#tabs button').forEach((b) => b.classList.toggle('active', b.dataset.view === v));
  $$('.view').forEach((el) => el.classList.toggle('active', el.id === `view-${v}`));
  if (v === 'events') loadEvents(true);
  if (v === 'settings') { loadSettings(); renderSystem(); }
  if (v === 'watch') { TL.resize(); if (S.mode === 'live' && !S.paused) Player.startLive(); }
  else if (S.mode === 'live') Player.stopLive();
  if (v !== 'watch' && S.mode === 'playback') { els.video.pause(); S.paused = true; updateModeUi(); }
  Player.updatePip();
  history.replaceState(null, '', v === 'watch' ? location.pathname : `#${v}`);
}
$('#tabs').onclick = (e) => { const b = e.target.closest('[data-view]'); if (b) switchView(b.dataset.view); };

document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    Player.stopLive();
    Player.updatePip();
  } else {
    if (S.view === 'watch' && S.mode === 'live' && !S.paused) Player.startLive();
    Player.updatePip();
    refreshStatus();
  }
});

document.addEventListener('keydown', (e) => {
  if (e.target.closest('input, select, textarea') || e.ctrlKey || e.metaKey || e.altKey || S.view !== 'watch') return;
  switch (e.key) {
    case ' ': e.preventDefault(); Player.togglePause(); break;
    case 'ArrowLeft': Player.skip(e.shiftKey ? -60 : -10); break;
    case 'ArrowRight': if (S.mode === 'playback') Player.skip(e.shiftKey ? 60 : 10); break;
    case 'l': case 'L': Player.goLive(); break;
    case 'f': case 'F': toggleFullscreen(); break;
    case '+': case '=': TL.stepZoom(-1); break;
    case '-': TL.stepZoom(1); break;
    case ',': Player.jumpEvent(-1); break;
    case '.': Player.jumpEvent(1); break;
  }
});

// ================================================================ BOOT
(async function boot() {
  syncToggles();
  TL.init();
  Player.init();
  await refreshStatus();
  TL.center = now();
  Player.goLive();
  fetchTimeline(true);
  loadDayEvents(true);
  loadSettings();
  setInterval(refreshStatus, 4000);
  setInterval(() => { if (dayStart(TL.center) === dayStart(now())) loadDayEvents(); }, 15000);
  requestAnimationFrame(tick);
  const hash = location.hash.replace('#', '');
  if (['events', 'settings'].includes(hash)) switchView(hash);
})();

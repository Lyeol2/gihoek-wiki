/* 기획 위키 — 프론트엔드 (빌드 도구 없이 바로 실행) */
'use strict';

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const enc = encodeURIComponent;

const STATUS = { draft: '초안', review: '검토 중', final: '확정' };

const state = {
  templates: [],
  tpl: {},
  projects: [],
  project: null,      // 현재 프로젝트 id (폴더 이름)
  projectInfo: null,
  docs: [],
  byTitle: {},
  ai: null,
  editing: null,      // { doc, dirty }
  imageTarget: null,
  currentTitle: null,
};

/* ------------------------------------------------------------ links */

const projHref = (p = state.project) => `#/p/${enc(p)}`;
const docHref = id => `${projHref()}/doc/${enc(id)}`;
const editHref = id => `${docHref(id)}/edit`;
const newHref = (q = {}) => `${projHref()}/new` + (Object.keys(q).length ? '?' + new URLSearchParams(q) : '');

/* ------------------------------------------------------------ api */

async function api(path, opts = {}) {
  const res = await fetch('/api/' + path, {
    method: opts.method || 'GET',
    headers: opts.body ? { 'Content-Type': 'application/json' } : {},
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}
const papi = (path, opts) => api(`p/${enc(state.project)}/${path}`, opts);
const docApi = (id, opts) => papi(`docs/${enc(id)}`, opts);

async function uploadImage(file) {
  const res = await fetch(`/api/p/${enc(state.project)}/images`, {
    method: 'POST',
    headers: { 'X-Filename': enc(file.name || 'paste.png') },
    body: file,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || '업로드 실패');
  return data.url;
}

async function refreshProjects() {
  state.projects = await api('projects');
}

async function refreshDocs() {
  if (!state.project) { state.docs = []; state.byTitle = {}; return renderNav(); }
  state.docs = await papi('docs');
  state.byTitle = {};
  for (const d of state.docs) if (d.title) state.byTitle[d.title.trim()] = d;
  renderNav();
}

async function setProject(pid) {
  if (pid === state.project && state.projectInfo) return;
  state.project = pid;
  state.projectInfo = pid ? await api(`projects/${enc(pid)}`) : null;
  try { if (pid) localStorage.setItem('wiki.project', pid); } catch { /* 저장 못 해도 괜찮다 */ }
  await refreshDocs();
}

/* ------------------------------------------------------------ utils */

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function stripLinks(s) { return String(s ?? '').replace(/\[\[([^\[\]]+?)\]\]/g, '$1'); }

function wikiLink(title, label) {
  const t = title.trim();
  const d = state.byTitle[t];
  const text = esc(label ?? t);
  if (t === state.currentTitle) return `<strong>${text}</strong>`;
  if (d) return `<a class="wl" href="${docHref(d.id)}">${text}</a>`;
  return `<a class="wl missing" href="${newHref({ title: t })}" title="아직 없는 문서 · 눌러서 만들기">${text}</a>`;
}

function inline(s) {
  // [[링크]]를 먼저 토큰으로 바꾼 뒤 escape → 링크 제목이 escape 영향을 받지 않게
  const links = [];
  let out = String(s ?? '').replace(/\[\[([^\[\]]+?)\]\]/g, (_, t) => `\u0000${links.push(t) - 1}\u0000`);
  out = esc(out).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/`([^`]+)`/g, '<code>$1</code>');
  return out.replace(/\u0000(\d+)\u0000/g, (_, i) => wikiLink(links[+i]));
}

// 자유 문서 본문용: 문단, ### 소제목, 목록
function paras(s) {
  return String(s ?? '').split(/\n\s*\n/).map(p => p.trim()).filter(Boolean).map(p => {
    const h = p.match(/^#{3,6}\s+(.*)$/);
    if (h && !p.includes('\n')) return `<h3>${inline(h[1])}</h3>`;
    const lines = p.split('\n');
    if (lines.every(l => /^\s*([-*+]|\d+[.)])\s+/.test(l))) {
      const ordered = /^\s*\d/.test(lines[0]);
      const lis = lines.map(l => `<li>${inline(l.replace(/^\s*([-*+]|\d+[.)])\s+/, ''))}</li>`).join('');
      return ordered ? `<ol class="list">${lis}</ol>` : `<ul class="list">${lis}</ul>`;
    }
    return `<p>${inline(p).replace(/\n/g, '<br>')}</p>`;
  }).join('');
}

function fmtDate(ms) {
  if (!ms) return '';
  const d = new Date(ms);
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, '0')}.${String(d.getDate()).padStart(2, '0')}`;
}

function isEmpty(v) {
  if (v == null || v === '') return true;
  if (Array.isArray(v)) return v.length === 0;
  if (typeof v === 'object') return Object.values(v).every(x => x == null || x === '');
  return false;
}

function toast(msg, isError) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast' + (isError ? ' error' : '');
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), isError ? 6000 : 2500);
}

let overlayTimer;
function showOverlay(title) {
  const started = Date.now();
  const label = state.ai?.providers.find(p => p.id === state.ai.provider)?.label || 'AI';
  $('#overlayTitle').textContent = title || `${label}가 문서를 쓰는 중`;
  const tick = () => ($('#overlaySub').textContent = `${Math.round((Date.now() - started) / 1000)}초 · 보통 20~60초, 링크를 읽으면 몇 분 걸려요`);
  tick();
  overlayTimer = setInterval(tick, 1000);
  $('#overlay').hidden = false;
}
function hideOverlay() { clearInterval(overlayTimer); $('#overlay').hidden = true; }

/* ------------------------------------------------------------ sidebar */

// 핵심 문서(프로젝트에 하나씩 두는 문서): 확정된 것을 앞에, 그다음 최근에 고친 순
const coreDocs = t => state.docs.filter(d => d.template === t.id)
  .sort((a, b) => (b.status === 'final') - (a.status === 'final') || (b.updatedAt || 0) - (a.updatedAt || 0));

function renderNav() {
  const head = $('#projHead');
  if (!state.project) {
    head.innerHTML = '';
    $('#newBtn').hidden = true;
    $('#search').hidden = true;
    $('#nav').innerHTML = `<div class="nav-group"><div class="nav-head">프로젝트</div>
      ${state.projects.map(p => `<a class="nav-item" href="${projHref(p.id)}"><span class="pdot"></span>${esc(p.name)}</a>`).join('')
        || '<div class="nav-empty">아직 없음</div>'}</div>`;
    return;
  }
  $('#newBtn').hidden = false;
  $('#search').hidden = false;
  head.innerHTML = `<a class="proj-switch" href="#/" title="프로젝트 목록">
      <span class="proj-label">프로젝트</span><span class="proj-name">${esc(state.projectInfo?.name || state.project)}</span><span class="proj-caret">⇄</span></a>`;
  const q = $('#search').value.trim().toLowerCase();
  const current = decodeURIComponent(location.hash.match(/\/doc\/([^/?]+)/)?.[1] || '');
  let html = `<a class="nav-item home-link ${parseHash().parts.length === 2 ? 'active' : ''}" href="${projHref()}">⌂ 프로젝트 홈</a>`;
  const singles = state.templates.filter(t => t.single);
  if (singles.length && !q) {
    html += `<div class="nav-group"><div class="nav-head"><span class="ticon" style="--c:var(--accent)">★</span>핵심 문서</div>
      ${singles.map(t => {
        const ds = coreDocs(t);
        return ds.length ? ds.map(d => `<a class="nav-item ${d.id === current ? 'active' : ''}" href="${docHref(d.id)}">
            <span class="dot s-${d.status}"></span>${esc(ds.length > 1 ? d.title : t.name)}</a>`).join('')
          : `<a class="nav-item nav-todo" href="${newHref({ template: t.id })}">＋ ${esc(t.name)}</a>`;
      }).join('')}</div>`;
  }
  for (const t of state.templates) {
    if (t.single && !q) continue;
    const docs = state.docs.filter(d => d.template === t.id &&
      (!q || d.title.toLowerCase().includes(q) || (d.summary || '').toLowerCase().includes(q)));
    if (!docs.length && (q || t.id === 'note')) continue;
    html += `<div class="nav-group">
      <div class="nav-head"><span class="ticon" style="--c:${t.color}">${t.icon}</span>${esc(t.name)}
        <a class="nav-add" href="${newHref({ template: t.id })}" title="${esc(t.name)} 새로 만들기">+</a></div>
      ${docs.map(d => `<a class="nav-item ${d.id === current ? 'active' : ''}" href="${docHref(d.id)}">
        <span class="dot s-${d.status}"></span>${esc(d.title || '(제목 없음)')}</a>`).join('')
        || '<div class="nav-empty">없음</div>'}
    </div>`;
  }
  $('#nav').innerHTML = html;
}

async function loadAi() {
  state.ai = await api('config');
  $('#aiSelect').innerHTML = state.ai.providers.map(p =>
    `<option value="${p.id}" ${p.id === state.ai.provider ? 'selected' : ''} ${p.installed ? '' : 'disabled'}>${esc(p.label)}${p.installed ? '' : ' (미설치)'}</option>`).join('');
  $('#version').textContent = state.ai.version === 'dev' ? '개발 버전' : `v${state.ai.version}`;
}

/* ------------------------------------------------------------ 자동 업데이트 */

async function checkUpdate() {
  let u;
  try { u = await api('update'); } catch { return; }
  const btn = $('#updateBtn');
  btn.hidden = !u.available;
  if (!u.available) return;
  btn.textContent = `새 버전 v${u.latest} · 업데이트`;
  btn.onclick = () => installUpdate(u);
}

async function installUpdate(u) {
  if (!u.canInstall) {
    if (confirm(`${u.reason}\n\n릴리즈 페이지를 열까요?`)) window.open(u.url, '_blank');
    return;
  }
  if (state.editing?.dirty && !confirm('저장하지 않은 편집 내용이 있어요. 그래도 업데이트할까요?')) return;
  if (!confirm(`v${u.latest}로 업데이트할까요?\n내려받아 설치한 뒤 앱이 다시 열려요. 문서는 그대로 있어요.`)) return;
  const label = { downloading: '새 버전을 내려받는 중', installing: '설치하는 중', restarting: '다시 여는 중' };
  showOverlay('업데이트 준비 중');
  clearInterval(overlayTimer);
  $('#overlaySub').textContent = `v${u.current} → v${u.latest}`;
  await api('update', { method: 'POST' }).catch(() => {});
  let lost = 0;
  const timer = setInterval(async () => {
    try {
      const s = await api('update');
      if (s.current !== u.current) return location.reload();   // 새 버전 서버가 떴다
      if (s.state === 'error') {
        clearInterval(timer); hideOverlay();
        if (confirm(`업데이트하지 못했어요.\n${s.error}\n\n릴리즈 페이지를 열까요?`)) window.open(u.url, '_blank');
        return;
      }
      $('#overlayTitle').textContent = label[s.state] || '업데이트 중';
    } catch {
      // 서버가 꺼졌다 = 설치 중. 다시 뜰 때까지 기다린다 (맥은 앱 전체가 다시 열린다)
      $('#overlayTitle').textContent = label.restarting;
      if (++lost > 120) { clearInterval(timer); hideOverlay(); toast('앱을 다시 열어 주세요', true); }
    }
  }, 1000);
}

/* ------------------------------------------------------------ router */

function parseHash() {
  const h = location.hash.slice(1) || '/';
  const [path, qs] = h.split('?');
  return { parts: path.split('/').filter(Boolean).map(decodeURIComponent), query: new URLSearchParams(qs || '') };
}

async function route() {
  const { parts, query } = parseHash();
  if (state.skipRoute) { state.skipRoute = false; return; }
  if (state.editing?.dirty && !(parts[2] === 'doc' && parts[4] === 'edit' && parts[3] === state.editing.doc.id)) {
    if (!confirm('저장하지 않은 변경 사항이 있어요. 나갈까요?')) {
      state.skipRoute = true;
      history.back();
      return;
    }
  }
  state.editing = null;
  state.currentTitle = null;
  const main = $('#main');
  main.oninput = main.onclick = null;
  window.scrollTo(0, 0);
  try {
    if (parts[0] !== 'p' || !parts[1]) {
      await setProject(null);
      await refreshProjects();
      renderNav();
      return renderProjects();
    }
    await setProject(parts[1]);
    renderNav();
    const [, , view, id, sub] = parts;
    if (!view) return renderHome();
    if (view === 'new') return renderNew(query);
    if (view === 'doc' && sub === 'edit') return renderEdit(id);
    if (view === 'doc') return renderDoc(id);
    renderHome();
  } catch (e) {
    if (/찾을 수 없/.test(e.message) && parts[0] === 'p' && !parts[2]) { location.hash = '#/'; return; }
    main.innerHTML = `<div class="page"><p class="error-box">${esc(e.message)}</p>
      <p><a class="btn" href="${state.project ? projHref() : '#/'}">돌아가기</a></p></div>`;
  }
}

/* ------------------------------------------------------------ projects */

function renderProjects() {
  const cards = state.projects.map(p => `
    <a class="proj-card" href="${projHref(p.id)}">
      <div class="proj-card-name">${esc(p.name)}</div>
      <div class="proj-card-desc">${esc(p.description || '설명 없음')}</div>
      <div class="proj-card-meta">문서 ${p.docCount}개 · ${fmtDate(p.updatedAt)}</div>
    </a>`).join('');

  $('#main').innerHTML = `<div class="page">
    <header class="page-head">
      <h1>프로젝트</h1>
      <p class="muted">게임 하나에 프로젝트 하나. 문서는 프로젝트 폴더 안에 md 파일로 저장돼요.</p>
    </header>
    <section class="home-sec">
      <div class="proj-grid">
        <form class="proj-card proj-new" id="newProj">
          <div class="proj-card-name">＋ 새 프로젝트</div>
          <input class="input" id="pName" placeholder="프로젝트 이름 (예: 13번째 종)" required maxlength="80">
          <textarea class="input" id="pDesc" rows="3" placeholder="한두 줄 소개 (선택). 장르, 분위기, 핵심 콘셉트를 적어두면 AI가 문서를 쓸 때 참고해요."></textarea>
          <div id="pRepoBox" hidden>
            <label class="check"><input type="checkbox" id="pRepoOn" checked> GitHub 비공개 레포로 올려 팀과 같이 쓰기</label>
            <input class="input" id="pRepo" placeholder="레포 이름 (영문, 예: bell-13-wiki)" maxlength="60" pattern="[A-Za-z0-9][A-Za-z0-9._\-]*">
          </div>
          <button class="btn primary" type="submit" id="pSubmit">만들기</button>
        </form>
        ${cards}
      </div>
    </section>
    <section class="home-sec" id="joinSec" hidden>
      <h2>GitHub에서 가져오기 <span class="muted">초대받았거나 내 GitHub에 있는 프로젝트를 이 컴퓨터로 가져와요</span></h2>
      <div id="inviteList" class="invite-list"></div>
      <div id="repoList" class="invite-list"></div>
      <form class="row-form" id="joinForm">
        <input class="input" id="joinRepo" placeholder="레포 주소 (예: Lyeol2/bell-13-wiki)" required>
        <button class="btn" type="submit">가져오기</button>
      </form>
    </section>
    <p class="muted small">저장 위치: <code>${esc(state.ai?.projectsDir || '')}</code></p>
  </div>`;

  $('#newProj').onsubmit = async e => {
    e.preventDefault();
    const withRepo = !$('#pRepoBox').hidden && $('#pRepoOn').checked;
    const btn = $('#pSubmit');
    btn.disabled = true; btn.textContent = withRepo ? 'GitHub에 올리는 중…' : '만드는 중…';
    try {
      const p = await api('projects', { method: 'POST', body: {
        name: $('#pName').value, description: $('#pDesc').value, repo: withRepo ? $('#pRepo').value.trim() : '' } });
      if (p.gitError) alert(`프로젝트는 만들었지만 GitHub에 올리지 못했어요.\n${p.gitError}\n\n프로젝트 홈에서 다시 올릴 수 있어요.`);
      await refreshProjects();
      location.hash = projHref(p.id);
    } catch (err) { toast(err.message, true); btn.disabled = false; btn.textContent = '만들기'; }
  };
  if (!state.projects.length) $('#pName').focus();
  setupProjectGit();
}

const repoSlug = text => (text || '').normalize('NFKD').replace(/[^A-Za-z0-9._-]+/g, '-').replace(/^[-.]+|[-.]+$/g, '').toLowerCase().slice(0, 60);
const defaultRepo = text => repoSlug(text) || `wiki-${new Date().toISOString().slice(2, 10).replace(/-/g, '')}`;

// 받은 초대가 있으면 어디에 있든 알려준다 (수락은 첫 화면의 'GitHub에서 가져오기')
async function checkInvites() {
  try {
    const g = state.git || await loadGit();
    if (!g.ready) return;
    const list = await api('git/invitations');
    const link = $('#inviteLink');
    link.hidden = !list.length;
    if (list.length) link.textContent = `받은 초대 ${list.length}개 · 참여하기`;
  } catch { /* 못 읽어도 괜찮다 */ }
}

async function loadGit() {
  try { state.git = await api('git'); } catch { state.git = { ready: false, hint: '' }; }
  return state.git;
}

async function setupProjectGit() {
  const g = state.git || await loadGit();
  if (!g.ready || !$('#pRepoBox')) return;
  $('#pRepoBox').hidden = false;
  $('#joinSec').hidden = false;
  const sync = () => { $('#pRepo').hidden = !$('#pRepoOn').checked; $('#pRepo').required = $('#pRepoOn').checked; };
  $('#pRepoOn').onchange = sync; sync();
  let touched = false;
  $('#pRepo').oninput = () => { touched = true; };
  $('#pRepo').value = defaultRepo('');
  $('#pName').oninput = () => { if (!touched) $('#pRepo').value = defaultRepo($('#pName').value); };

  const join = async (repo, invitation, btn) => {
    const old = btn.textContent; btn.disabled = true; btn.textContent = '가져오는 중…';
    try {
      const p = await api('git/join', { method: 'POST', body: { repo, invitation } });
      await refreshProjects();
      location.hash = projHref(p.id);
    } catch (err) { toast(err.message, true); btn.disabled = false; btn.textContent = old; }
  };
  $('#joinForm').onsubmit = e => { e.preventDefault(); join($('#joinRepo').value, null, e.target.querySelector('button')); };
  try {
    const list = await api('git/invitations');
    if (!$('#inviteList')) return;
    $('#inviteList').innerHTML = list.map(i => `<div class="invite">
      <div class="grow"><b>${esc(i.repo)}</b><span class="muted"> · ${esc(i.from)} 님이 초대했어요</span></div>
      <button class="btn primary small" data-repo="${esc(i.repo)}" data-inv="${esc(i.id)}">참여하기</button></div>`).join('');
    $('#inviteList').querySelectorAll('button').forEach(b => { b.onclick = () => join(b.dataset.repo, b.dataset.inv, b); });
  } catch { /* 초대 목록은 못 읽어도 괜찮다 */ }
  try {
    const repos = (await api('git/repos')).filter(r => !r.local);
    if (!$('#repoList')) return;
    $('#repoList').innerHTML = repos.map(r => `<div class="invite">
      <div class="grow"><b>${esc(r.name)}</b><span class="muted"> · ${esc(r.repo)} · 내 GitHub에 있는 프로젝트</span></div>
      <button class="btn small" data-repo="${esc(r.repo)}">가져오기</button></div>`).join('');
    $('#repoList').querySelectorAll('button').forEach(b => { b.onclick = () => join(b.dataset.repo, null, b); });
  } catch { /* 목록은 못 읽어도 주소로 가져올 수 있다 */ }
}

/* ------------------------------------------------------------ 팀과 같이 쓰기 (Git) */

async function renderTeam(fetchRemote) {
  if (!$('#teamSec')) return;
  const pid = state.project;
  const g = state.git || await loadGit();
  let st;
  try { st = await papi(fetchRemote ? 'git/fetch' : 'git/status'); } catch { return; }
  const box = $('#teamSec');   // 기다리는 동안 화면이 다시 그려졌을 수 있으니 지금 있는 칸을 잡는다
  if (pid !== state.project || !box) return;

  if (!st.repo || !st.remote) {
    box.innerHTML = g.ready ? `<div class="team-bar">
        <div class="grow"><b>팀과 같이 쓰기</b><span class="muted"> · GitHub 비공개 레포로 올리면 팀원을 초대해서 같이 고칠 수 있어요</span></div>
        <form class="row-form" id="pubForm">
          <input class="input" id="pubRepo" value="${esc(defaultRepo(state.project))}" placeholder="레포 이름 (영문)" required maxlength="60">
          <button class="btn primary small" type="submit">GitHub에 올리기</button>
        </form></div>`
      : `<div class="team-bar"><div class="grow"><b>팀과 같이 쓰기</b><span class="muted"> · ${esc(g.hint || '')}</span></div></div>`;
    if (g.ready) $('#pubForm').onsubmit = async e => {
      e.preventDefault();
      const btn = e.target.querySelector('button'); btn.disabled = true; btn.textContent = '올리는 중…';
      try { await papi('git/publish', { method: 'POST', body: { repo: $('#pubRepo').value.trim() } }); toast('GitHub에 올렸어요'); renderTeam(); }
      catch (err) { toast(err.message, true); btn.disabled = false; btn.textContent = 'GitHub에 올리기'; }
    };
    return;
  }

  const parts = [];
  if (st.changes) parts.push(`내 변경 ${st.changes}개`);
  if (st.ahead) parts.push(`안 올린 저장 ${st.ahead}개`);
  if (st.behind) parts.push(`팀원 변경 ${st.behind}개`);
  const dirty = parts.length > 0;
  box.innerHTML = `<div class="team-bar">
      <div class="grow">
        <b><span class="dot ${dirty ? 'warn' : 'ok'}"></span>${dirty ? esc(parts.join(' · ')) : '팀과 같은 상태예요'}</b>
        <span class="muted"> · <a href="${esc(st.url)}" target="_blank" rel="noopener">${esc(st.slug)}</a>${st.last ? ` · 마지막 저장 ${esc(st.last.by)}, ${fmtDate(st.last.at)}` : ''}</span>
      </div>
      <button class="btn ${dirty ? 'primary' : ''} small" id="syncBtn">동기화</button>
      <button class="btn small" id="teamBtn">팀원</button>
    </div>
    <div class="team-panel" id="teamPanel" hidden></div>`;

  $('#syncBtn').onclick = async () => {
    if (!g.ready) return toast(g.hint, true);
    const btn = $('#syncBtn'); btn.disabled = true; btn.textContent = '동기화 중…';
    try {
      const r = await papi('git/sync', { method: 'POST', body: {} });
      await refreshDocs();
      const msg = [r.pulled && `받음 ${r.pulled}`, r.pushed && `올림 ${r.pushed}`].filter(Boolean).join(' · ') || '이미 최신이에요';
      if (r.conflicts.length) {
        alert(`팀원과 같은 문서를 고쳤어요. 팀원 버전을 받았고, 내 버전은 따로 저장해 뒀어요.\n\n${r.conflicts.map(c => `· ${c.copy}`).join('\n')}\n\n두 문서를 비교해서 합친 뒤 '내 버전' 문서를 지워 주세요.`);
      }
      toast(`동기화 완료 · ${msg}`);
      if (state.project === pid && $('#teamSec')) renderHome();
    } catch (err) { alert(`동기화하지 못했어요.\n${err.message}`); btn.disabled = false; btn.textContent = '동기화'; }
  };

  $('#teamBtn').onclick = async () => {
    const panel = $('#teamPanel');
    panel.hidden = !panel.hidden;
    if (panel.hidden) return;
    const draw = m => {
      panel.innerHTML = `<div class="chips">${m.members.map(u => `<span class="chip">@${esc(u)}</span>`).join('')}${
        m.pending.map(u => `<span class="chip muted">@${esc(u)} · 초대 중</span>`).join('')}</div>
        <form class="row-form" id="invForm">
          <input class="input" id="invUser" placeholder="초대할 팀원의 GitHub 아이디" required>
          <button class="btn primary small" type="submit">초대</button>
        </form>
        <p class="muted small">초대받은 팀원은 기획위키 첫 화면의 <b>GitHub에서 가져오기</b>에서 <b>참여하기</b>를 누르면 돼요. (GitHub CLI 로그인 필요)</p>`;
      $('#invForm').onsubmit = async e => {
        e.preventDefault();
        const btn = e.target.querySelector('button'); btn.disabled = true;
        try { const user = $('#invUser').value; draw(await papi('git/invite', { method: 'POST', body: { user } })); toast(`${user} 님을 초대했어요`); }
        catch (err) { toast(err.message, true); btn.disabled = false; }
      };
    };
    panel.innerHTML = '<p class="muted small">불러오는 중…</p>';
    try { draw(await papi('git/members')); } catch (err) { panel.innerHTML = `<p class="error-box">${esc(err.message)}</p>`; }
  };
}

/* ------------------------------------------------------------ project home */

function renderHome() {
  const info = state.projectInfo || {};
  const coreHtml = state.templates.filter(t => t.single).map(t => {
    const ds = coreDocs(t), d = ds[0];
    return d ? `<a class="core-card done" href="${docHref(d.id)}" style="--c:${t.color}">
        <span class="core-icon">${t.icon}</span>
        <span class="core-name">${esc(t.name)}<span class="status s-${d.status}">${STATUS[d.status] || ''}</span></span>
        <span class="core-desc">${esc(d.summary || d.title || '')}</span>
        <span class="core-meta">${fmtDate(d.updatedAt)}${ds.length > 1 ? ` · 같은 문서 ${ds.length}개` : ''}</span></a>`
      : `<a class="core-card" href="${newHref({ template: t.id })}" style="--c:${t.color}">
        <span class="core-icon">${t.icon}</span>
        <span class="core-name">${esc(t.name)}</span>
        <span class="core-desc">${esc(t.description)}</span>
        <span class="core-meta">＋ 만들기</span></a>`;
  }).join('');
  const coreCount = state.templates.filter(t => t.single && coreDocs(t).length).length;
  const coreTotal = state.templates.filter(t => t.single).length;

  const tplCards = state.templates.filter(t => !t.single).map(t => `
    <a class="tpl-card" href="${newHref({ template: t.id })}" style="--c:${t.color}">
      <span class="tpl-icon">${t.icon}</span>
      <span class="tpl-name">${esc(t.name)}</span>
      <span class="tpl-desc">${esc(t.description)}</span>
    </a>`).join('');

  const titles = new Set(Object.keys(state.byTitle));
  const wanted = {};
  for (const d of state.docs) for (const l of d.links || []) if (!titles.has(l)) (wanted[l] ||= []).push(d);
  const wantedHtml = Object.keys(wanted).length ? `
    <section class="home-sec">
      <h2>만들어야 할 문서 <span class="muted">다른 문서에서 언급됐지만 아직 없어요</span></h2>
      <div class="chips">${Object.entries(wanted).sort((a, b) => b[1].length - a[1].length).slice(0, 40)
        .map(([t, ds]) => `<span class="chip">${wikiLink(t)}<span class="chip-count">${ds.length}</span></span>`).join('')}</div>
    </section>` : '';

  const docCards = state.docs.map(d => {
    const t = state.tpl[d.template] || {};
    return `<a class="doc-card" href="${docHref(d.id)}" style="--c:${t.color || '#888'}">
      <div class="doc-cover">${d.cover ? `<img src="${esc(d.cover)}" alt="">` : `<span>${t.icon || '?'}</span>`}</div>
      <div class="doc-card-body">
        <div class="doc-card-meta"><span class="badge" style="--c:${t.color}">${esc(t.name || d.template)}</span>
          <span class="status s-${d.status}">${STATUS[d.status] || ''}</span></div>
        <div class="doc-card-title">${esc(d.title || '(제목 없음)')}</div>
        <div class="doc-card-sum">${esc(d.summary || '')}</div>
        <div class="doc-card-date">${fmtDate(d.updatedAt)}</div>
      </div>
    </a>`;
  }).join('');

  $('#main').innerHTML = `<div class="page">
    <header class="page-head proj-head">
      <div class="grow">
        <h1>${esc(info.name || state.project)}</h1>
        <div id="descView" class="proj-desc ${info.description ? '' : 'muted'}">${info.description ? paras(info.description) : '프로젝트 소개가 없어요. AI가 문서를 쓸 때 참고하니 한두 줄 적어두면 좋아요.'}</div>
        <div id="descEdit" hidden>
          <textarea class="input" id="descText" rows="4">${esc(info.description || '')}</textarea>
          <div class="actions"><button class="btn primary small" id="descSave">저장</button><button class="btn ghost small" id="descCancel">취소</button></div>
        </div>
      </div>
      <div class="proj-actions">
        <button class="btn small" id="descBtn">소개 고치기</button>
        <button class="btn small" id="revealBtn">폴더 열기</button>
        <button class="btn small ghost danger" id="projDelBtn">프로젝트 삭제</button>
      </div>
    </header>
    <section class="home-sec team-sec" id="teamSec"></section>
    <section class="home-sec"><h2>핵심 문서 <span class="muted">프로젝트에 하나씩 두는 기준 문서 · ${coreCount}/${coreTotal}</span></h2>
      <div class="core-grid">${coreHtml}</div></section>
    <section class="home-sec"><h2>새로 만들기 <span class="muted">필요한 만큼 여러 개</span></h2><div class="tpl-grid">${tplCards}</div></section>
    ${wantedHtml}
    <section class="home-sec"><h2>문서 <span class="muted">${state.docs.length}개</span></h2>
      ${docCards ? `<div class="doc-grid">${docCards}</div>` : '<p class="empty">아직 문서가 없어요. 위에서 양식을 골라 시작해보세요.</p>'}
    </section>
  </div>`;

  $('#revealBtn').onclick = () => papi('reveal', { method: 'POST', body: {} }).catch(e => toast(e.message, true));
  $('#projDelBtn').onclick = async () => {
    const name = info.name || state.project;
    if (!confirm(`"${name}" 프로젝트를 삭제할까요?\n\n문서 ${state.docs.length}개가 목록에서 사라져요. 이 컴퓨터에서는 완전히 지우지 않고 저장 폴더 안의 휴지통 폴더로 옮겨요.`)) return;
    try {
      // GitHub에 올린 프로젝트면 레포까지 지울지 따로 한 번 더 묻는다 (이건 되돌릴 수 없다)
      const st = await papi('git/status').catch(() => ({}));
      if (st.slug && confirm(`GitHub 레포 ${st.slug} 도 같이 지울까요?\n\n[확인] 레포까지 완전히 삭제 — 팀원도 더 이상 쓸 수 없고 되돌릴 수 없어요.\n[취소] 레포는 남겨 두고 이 컴퓨터의 프로젝트만 삭제`)) {
        if (!confirm(`정말 ${st.slug} 레포를 완전히 지울까요?\n이 작업은 되돌릴 수 없어요.`)) return;
        try { await api(`projects/${enc(state.project)}/repo`, { method: 'DELETE' }); }
        catch (e) { alert(`레포를 지우지 못해서 아무것도 삭제하지 않았어요.\n\n${e.message}`); return; }
      }
      await api(`projects/${enc(state.project)}`, { method: 'DELETE' });
      try { localStorage.setItem('wiki.project', ''); } catch { /* 없음 */ }
      state.project = null; state.projectInfo = null;
      await refreshProjects();
      toast(`"${name}" 프로젝트를 삭제했어요`);
      location.hash = '#/';
    } catch (e) { toast(e.message, true); }
  };
  renderTeam().then(() => renderTeam(true));   // 먼저 내 컴퓨터 상태를 보여주고, 이어서 GitHub의 새 변경을 확인한다
  const toggle = on => { $('#descView').hidden = on; $('#descEdit').hidden = !on; $('#descBtn').hidden = on; if (on) $('#descText').focus(); };
  $('#descBtn').onclick = () => toggle(true);
  $('#descCancel').onclick = () => toggle(false);
  $('#descSave').onclick = async () => {
    state.projectInfo = await api(`projects/${enc(state.project)}`, { method: 'PUT', body: { description: $('#descText').value } });
    renderHome();
  };
}

/* ------------------------------------------------------------ new */

function renderNew(query) {
  const sel = state.tpl[query.get('template')] ? query.get('template') : state.templates[0].id;
  const title = query.get('title') || '';
  $('#main').innerHTML = `<div class="page narrow">
    <header class="page-head"><h1>새 문서</h1></header>
    <div class="field-label">양식</div>
    <div class="tpl-pick">${state.templates.map(t => `
      <label class="tpl-opt" style="--c:${t.color}">
        <input type="radio" name="tpl" value="${t.id}" ${t.id === sel ? 'checked' : ''}>
        <span class="tpl-icon">${t.icon}</span><span class="tpl-name">${esc(t.name)}</span>
      </label>`).join('')}</div>
    <p class="muted small" id="tplDesc"></p>

    <label class="field-label" for="newTitle">제목 <span class="muted">(비우면 AI가 정해요)</span></label>
    <input class="input" id="newTitle" value="${esc(title)}" placeholder="예: 잿빛 항구 벨모어">

    <label class="field-label" for="memo">메모</label>
    <textarea class="input memo" id="memo" placeholder="아이디어, 회의 메모, AI와 나눈 대화를 그대로 붙여넣으세요.

예) 해적들이 모이는 안개 낀 항구도시. 밤마다 종이 13번 울림. 길드 3개가 항구 이권을 두고 싸움. 플레이어는 밀수꾼으로 시작."></textarea>

    <div class="actions">
      <button class="btn primary" id="genBtn">AI로 작성</button>
      <button class="btn" id="blankBtn">빈 양식으로 시작</button>
    </div>
  </div>`;

  const desc = () => { $('#tplDesc').textContent = state.tpl[$('input[name=tpl]:checked').value].description; };
  desc();
  $$('input[name=tpl]').forEach(r => r.addEventListener('change', desc));

  $('#genBtn').onclick = async () => {
    const template = $('input[name=tpl]:checked').value;
    const memo = $('#memo').value.trim();
    const title = $('#newTitle').value.trim();
    if (!memo && !title) return toast('메모나 제목을 적어주세요', true);
    showOverlay();
    try {
      const out = await api('generate', { method: 'POST', body: { project: state.project, template, memo, title } });
      const doc = await papi('docs', { method: 'POST', body: { template, title: title || out.title || '새 문서', fields: out.fields || {}, memo, status: 'draft' } });
      await refreshDocs();
      location.hash = docHref(doc.id);
    } catch (e) {
      toast(e.message, true);
    } finally { hideOverlay(); }
  };

  $('#blankBtn').onclick = async () => {
    const template = $('input[name=tpl]:checked').value;
    try {
      const doc = await papi('docs', { method: 'POST', body: { template, title: $('#newTitle').value.trim() || '새 문서', fields: {}, memo: $('#memo').value, status: 'draft' } });
      await refreshDocs();
      location.hash = editHref(doc.id);
    } catch (e) { toast(e.message, true); }
  };
}

/* ------------------------------------------------------------ view renderers */

function imgFigure(v, key, idx, cls = '') {
  v = v || {};
  const slot = `data-slot="${key}" data-idx="${idx}"`;
  if (v.src) {
    return `<figure class="fig ${cls}"><img src="${esc(v.src)}" alt="${esc(v.caption || '')}" ${slot} class="zoomable">
      ${v.caption ? `<figcaption>${inline(v.caption)}</figcaption>` : ''}</figure>`;
  }
  return `<figure class="fig placeholder ${cls}" ${slot} tabindex="0" title="클릭하거나 이미지를 끌어다 놓으세요">
    <div class="ph-inner"><span class="ph-plus">＋</span><span class="ph-text">이미지 넣기</span>
    ${v.idea ? `<span class="ph-idea">${esc(v.idea)}</span>` : ''}</div>
    ${v.caption ? `<figcaption>${inline(v.caption)}</figcaption>` : ''}</figure>`;
}

const VIEW = {
  text: v => `<div class="prose">${paras(v)}</div>`,
  longtext: v => `<div class="prose">${paras(v)}</div>`,
  list: v => `<ul class="list">${v.map(x => `<li>${inline(x)}</li>`).join('')}</ul>`,
  tags: v => `<div class="tags">${v.map(x => `<span class="tag">${inline(x)}</span>`).join('')}</div>`,
  flow: v => `<ol class="flow">${v.map((x, i) => `<li><span class="flow-n">${i + 1}</span><span>${inline(x)}</span></li>`).join('')}</ol>`,
  cards: v => `<div class="cards">${v.map((c, i) => `<div class="card"><div class="card-n">${String(i + 1).padStart(2, '0')}</div>
      <div class="card-title">${inline(c.title)}</div><div class="card-desc">${inline(c.desc)}</div></div>`).join('')}</div>`,
  keyvalue: (v, f) => {
    const keys = [...(f.keys || []), ...Object.keys(v).filter(k => !(f.keys || []).includes(k))];
    return `<dl class="kv">${keys.filter(k => v[k]).map(k => `<dt>${esc(k)}</dt><dd>${inline(v[k])}</dd>`).join('')}</dl>`;
  },
  table: (v, f) => `<div class="table-wrap"><table><thead><tr>${(f.columns || []).map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead>
      <tbody>${v.map(r => `<tr>${(f.columns || r).map((_, i) => `<td>${inline(r[i] ?? '')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`,
  timeline: v => `<ol class="timeline">${v.map(e => `<li><div class="tl-when">${inline(e.when)}</div><div class="tl-what">${inline(e.what)}</div></li>`).join('')}</ol>`,
  relations: v => `<div class="relations">${v.map(r => `<div class="rel">${wikiLink(stripLinks(r.target))}<span class="rel-what">${inline(r.relation)}</span></div>`).join('')}</div>`,
  image: (v, f) => imgFigure(v, f.key, -1, 'wide'),
  gallery: (v, f) => `<div class="gallery">${(v || []).map((g, i) => imgFigure(g, f.key, i)).join('')}
      ${(v || []).length < (f.max || 8) ? `<button class="gallery-add" data-slot="${f.key}" data-idx="new">＋ 이미지 추가</button>` : ''}</div>`,
};

function renderField(f, v) {
  if (f.type === 'gallery') return VIEW.gallery(v, f);
  if (f.type === 'image') return VIEW.image(v, f);
  if (isEmpty(v)) return '';
  return (VIEW[f.type] || VIEW.text)(v, f);
}

// md 파일에 직접 추가한 (양식에 없는) 섹션
function extraHtml(doc) {
  return (doc.extra || []).filter(x => x.heading && x.body).map(x =>
    `<section class="sec sec-extra"><h2>${esc(x.heading)}</h2><div class="prose">${paras(x.body)}</div></section>`).join('');
}

function sectionsHtml(t, doc, exclude) {
  return t.fields.filter(f => !exclude.includes(f.place)).map(f => {
    const v = doc.fields?.[f.key];
    if (f.type === 'gallery' && isEmpty(v)) {
      return `<section class="sec sec-empty-gallery no-print" id="s-${f.key}"><h2>${esc(f.label)}</h2>${renderField(f, v)}</section>`;
    }
    const body = renderField(f, v);
    if (!body) return '';
    return `<section class="sec sec-${f.type}" id="s-${f.key}"><h2>${esc(f.label)}</h2>${body}</section>`;
  }).join('') + extraHtml(doc);
}

function wikiLayout(t, doc) {
  const F = doc.fields || {};
  const lead = t.fields.find(f => f.place === 'lead');
  const infoFields = t.fields.filter(f => f.place === 'infobox');
  const main = t.fields.filter(f => !f.place);
  const toc = main.filter(f => !isEmpty(F[f.key]));
  const intro = (doc.extra || []).find(x => !x.heading && x.body);
  const hasInfo = infoFields.some(f => f.type === 'image' || !isEmpty(F[f.key]));
  return `<article class="doc wiki" style="--c:${t.color}">
    <header class="doc-head">
      <div class="doc-meta"><span class="badge" style="--c:${t.color}">${t.icon} ${esc(t.name)}</span>
        <span class="status s-${doc.status}">${STATUS[doc.status] || ''}</span><span class="muted">${fmtDate(doc.updatedAt)}</span></div>
      <h1>${esc(doc.title)}</h1>
      ${lead && F[lead.key] ? `<div class="lead">${paras(F[lead.key])}</div>` : ''}
      ${intro ? `<div class="lead">${paras(intro.body)}</div>` : ''}
    </header>
    <div class="wiki-body">
      ${hasInfo ? `<aside class="infobox">
        <div class="infobox-title" style="--c:${t.color}">${esc(doc.title)}</div>
        ${infoFields.map(f => f.type === 'image' ? imgFigure(F[f.key], f.key, -1) : renderField(f, F[f.key])).join('')}
      </aside>` : ''}
      ${toc.length > 3 ? `<nav class="toc no-print"><div class="toc-title">목차</div><ol>${toc.map(f => `<li><a href="#s-${f.key}" data-anchor>${esc(f.label)}</a></li>`).join('')}</ol></nav>` : ''}
      ${sectionsHtml(t, doc, ['lead', 'infobox'])}
    </div>
  </article>`;
}

function proposalLayout(t, doc) {
  const F = doc.fields || {};
  const hero = t.fields.filter(f => f.place === 'hero');
  const tag = hero.find(f => f.type === 'text');
  const art = hero.find(f => f.type === 'image');
  const meta = hero.find(f => f.type === 'keyvalue');
  const artV = art ? F[art.key] : null;
  const metaV = meta ? F[meta.key] || {} : {};
  return `<article class="doc proposal" style="--c:${t.color}">
    <section class="hero ${artV?.src ? 'has-art' : ''}" ${art ? `data-slot="${art.key}" data-idx="-1"` : ''}>
      ${artV?.src ? `<img class="hero-art" src="${esc(artV.src)}" alt="">` : ''}
      <div class="hero-inner">
        <div class="hero-kicker">${esc(state.projectInfo?.name || t.name)} · ${fmtDate(doc.updatedAt)}</div>
        <h1>${esc(doc.title)}</h1>
        ${tag && F[tag.key] ? `<p class="hero-tag">${inline(F[tag.key])}</p>` : ''}
        ${meta ? `<div class="hero-meta">${Object.entries(metaV).filter(([, v]) => v).map(([k, v]) => `<div><span>${esc(k)}</span><b>${inline(v)}</b></div>`).join('')}</div>` : ''}
      </div>
      ${art && !artV?.src ? `<button class="hero-img-btn no-print" data-slot="${art.key}" data-idx="-1">＋ 키 아트 넣기${artV?.idea ? ` <small>${esc(artV.idea)}</small>` : ''}</button>` : ''}
    </section>
    <div class="proposal-body">${sectionsHtml(t, doc, ['hero'])}</div>
  </article>`;
}

/* ------------------------------------------------------------ doc view */

async function renderDoc(id) {
  const doc = await docApi(id);
  const t = state.tpl[doc.template] || state.tpl.note;
  state.currentTitle = (doc.title || '').trim();
  const backlinks = state.docs.filter(d => d.id !== doc.id && (d.links || []).includes(doc.title));

  $('#main').innerHTML = `<div class="page doc-page">
    <div class="toolbar no-print">
      <select id="statusSel" class="status-sel s-${doc.status}">${Object.entries(STATUS).map(([k, v]) => `<option value="${k}" ${k === doc.status ? 'selected' : ''}>${v}</option>`).join('')}</select>
      <span class="muted small file-path" title="이 문서의 md 파일">${esc(doc.id)}.md</span>
      <span class="grow"></span>
      ${doc.previous ? '<button class="btn ghost" id="undoBtn" title="AI 수정 전으로 되돌리기">↶ 되돌리기</button>' : ''}
      <button class="btn" id="refineBtn">✦ AI로 다듬기</button>
      <a class="btn" href="${editHref(doc.id)}">편집</a>
      <button class="btn" id="printBtn">PDF</button>
      <button class="btn" id="histBtn" title="이 문서가 바뀌어 온 기록">기록</button>
      <button class="btn ghost" id="fileBtn" title="Finder에서 md 파일 보기">파일</button>
      <button class="btn ghost danger" id="delBtn" title="삭제">삭제</button>
    </div>
    <div id="refineBox" class="refine no-print" hidden>
      <textarea class="input" id="refineText" rows="3" placeholder="어떻게 고칠까요? 예) 세력을 4개로 늘리고, 연표에 대전쟁 추가. 문장은 더 짧게."></textarea>
      <div class="refine-row"><span class="muted small">이미지는 그대로 유지돼요. 마음에 안 들면 되돌릴 수 있어요.</span>
        <button class="btn primary" id="refineGo">다듬기</button></div>
    </div>
    <div id="histBox" class="hist no-print" hidden></div>
    ${t.layout === 'proposal' ? proposalLayout(t, doc) : wikiLayout(t, doc)}
    ${backlinks.length ? `<section class="backlinks no-print"><h3>이 문서를 언급한 문서</h3>
      <div class="chips">${backlinks.map(d => `<a class="chip" href="${docHref(d.id)}">${esc(d.title)}</a>`).join('')}</div></section>` : ''}
    ${doc.memo ? `<details class="memo-box no-print"><summary>원본 메모</summary><pre>${esc(doc.memo)}</pre></details>` : ''}
  </div>`;

  const save = async (patch, msg) => {
    Object.assign(doc, patch);
    const saved = await docApi(doc.id, { method: 'PUT', body: doc });
    await refreshDocs();
    if (msg) toast(msg);
    return saved;
  };
  const reopen = saved => (saved.id === id ? renderDoc(id) : (location.hash = docHref(saved.id)));

  $('#statusSel').onchange = async e => reopen(await save({ status: e.target.value }, '상태 변경됨'));
  $('#printBtn').onclick = () => window.print();
  $('#histBtn').onclick = async () => {
    const box = $('#histBox');
    box.hidden = !box.hidden;
    if (box.hidden) return;
    box.innerHTML = '<p class="muted small">기록을 불러오는 중…</p>';
    try {
      const list = await papi(`history/${enc(doc.id)}`);
      box.innerHTML = list.length ? `<div class="hist-head"><b>문서 기록</b><span class="muted small"> · 눌러서 그때의 문서를 볼 수 있어요</span></div>
        <div class="hist-list">${list.map((v, i) => `<button class="hist-item" data-i="${i}">
          <span class="hist-when">${fmtTime(v.at)}</span>
          <span class="hist-what">${v.source === 'git' ? `${esc(v.by)} · ${esc(v.message)}` : '내 컴퓨터에서 저장'}</span>
          <span class="badge-mini">${v.source === 'git' ? 'GitHub' : '저장'}</span></button>`).join('')}</div>`
        : '<p class="muted small">아직 기록이 없어요. 문서를 고쳐서 저장하면 이전 내용이 여기에 남아요.</p>';
      box.querySelectorAll('.hist-item').forEach(b => { b.onclick = () => renderVersion(doc, list[+b.dataset.i]); });
    } catch (e) { box.innerHTML = `<p class="error-box">${esc(e.message)}</p>`; }
  };
  $('#fileBtn').onclick = () => papi('reveal', { method: 'POST', body: { doc: doc.id } }).catch(e => toast(e.message, true));
  $('#delBtn').onclick = async () => {
    if (!confirm(`"${doc.title}" 문서를 삭제할까요?\n(프로젝트 폴더의 .wiki/trash로 옮겨져요)`)) return;
    await docApi(doc.id, { method: 'DELETE' });
    await refreshDocs();
    location.hash = projHref();
  };
  $('#refineBtn').onclick = () => { const b = $('#refineBox'); b.hidden = !b.hidden; if (!b.hidden) $('#refineText').focus(); };
  $('#refineGo').onclick = async () => {
    showOverlay('AI가 문서를 다듬는 중');
    try {
      const out = await api('generate', { method: 'POST', body: { project: state.project, template: doc.template, current: doc, instruction: $('#refineText').value } });
      const prev = { title: doc.title, fields: doc.fields };
      reopen(await save({ previous: prev, title: out.title || doc.title, fields: mergeImages(t, out.fields || {}, doc.fields || {}) }, '다듬기 완료'));
    } catch (e) { toast(e.message, true); } finally { hideOverlay(); }
  };
  if ($('#undoBtn')) $('#undoBtn').onclick = async () => {
    const cur = { title: doc.title, fields: doc.fields };
    reopen(await save({ title: doc.previous.title, fields: doc.previous.fields, previous: cur }, '되돌렸어요 (다시 누르면 원래대로)'));
  };

  // 보기 화면에서 바로 이미지 넣기
  const onSlot = async (slot, file) => {
    const key = slot.dataset.slot, idx = slot.dataset.idx;
    const url = await uploadImage(file);
    const F = doc.fields ||= {};
    if (idx === '-1') F[key] = { ...(F[key] || {}), src: url };
    else {
      const arr = F[key] = [...(F[key] || [])];
      if (idx === 'new') arr.push({ src: url, caption: '' });
      else arr[+idx] = { ...(arr[+idx] || {}), src: url };
    }
    reopen(await save({}, '이미지 추가됨'));
  };
  bindSlots($('#main'), onSlot, '.placeholder, .gallery-add, .hero-img-btn');
  bindDrops($('#main'), onSlot);
  $$('.zoomable').forEach(img => img.onclick = () => openLightbox(img.src));
  $$('[data-anchor]').forEach(a => a.onclick = e => { e.preventDefault(); $(a.getAttribute('href'))?.scrollIntoView({ behavior: 'smooth' }); });
}

const fmtTime = ms => new Date(ms).toLocaleString('ko-KR', { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });

/* 과거 버전 보기: 읽기 전용으로 그때의 문서를 보여주고, 원하면 그 버전으로 되돌린다 */
async function renderVersion(current, v) {
  let old;
  try { old = await papi(`history/${enc(current.id)}/${enc(v.id)}`); } catch (e) { return toast(e.message, true); }
  const t = state.tpl[old.template] || state.tpl.note;
  $('#main').innerHTML = `<div class="page doc-page">
    <div class="version-bar no-print">
      <div class="grow"><b>과거 버전을 보는 중</b><span class="muted"> · ${fmtTime(v.at)}${v.source === 'git' ? ` · ${esc(v.by)}` : ''}</span></div>
      <button class="btn primary small" id="restoreBtn">이 버전으로 되돌리기</button>
      <button class="btn small" id="backBtn">현재 문서로</button>
    </div>
    ${t.layout === 'proposal' ? proposalLayout(t, old) : wikiLayout(t, old)}
  </div>`;
  window.scrollTo(0, 0);
  $('#backBtn').onclick = () => renderDoc(current.id);
  $('#restoreBtn').onclick = async () => {
    if (!confirm('이 버전으로 되돌릴까요?\n지금 내용도 기록에 남아서 다시 돌아올 수 있어요.')) return;
    const body = { ...current, title: old.title, fields: old.fields, extra: old.extra, status: old.status, template: old.template };
    delete body.previous;
    try {
      const saved = await docApi(current.id, { method: 'PUT', body });
      await refreshDocs();
      toast('되돌렸어요');
      if (saved.id === current.id) renderDoc(saved.id); else location.hash = docHref(saved.id);
    } catch (e) { toast(e.message, true); }
  };
  $$('.zoomable').forEach(img => img.onclick = () => openLightbox(img.src));
}

function mergeImages(t, next, prev) {
  const out = { ...next };
  for (const f of t.fields) {
    if (f.type === 'image') {
      const p = prev[f.key] || {}, n = next[f.key] || {};
      out[f.key] = { ...n, src: p.src || n.src, caption: n.caption || p.caption, idea: n.idea || p.idea };
      if (!out[f.key].src) delete out[f.key].src;
    } else if (f.type === 'gallery') {
      const p = prev[f.key] || [], n = next[f.key] || [];
      const arr = [];
      for (let i = 0; i < Math.max(p.length, n.length); i++) {
        const pi = p[i] || {}, ni = n[i] || {};
        if (!pi.src && i >= n.length) continue;
        arr.push({ ...ni, src: pi.src, caption: ni.caption || pi.caption, idea: ni.idea || pi.idea });
      }
      out[f.key] = arr.map(x => { if (!x.src) delete x.src; return x; });
    }
  }
  return out;
}

function pickFile() {
  return new Promise(resolve => {
    const input = $('#filePick');
    input.value = '';
    input.onchange = () => resolve(input.files[0] || null);
    input.click();
  });
}

function bindSlots(root, onSlot, selector) {
  $$(selector, root).forEach(el => {
    el.addEventListener('click', async e => {
      e.preventDefault();
      e.stopPropagation();
      const file = await pickFile();
      if (file) onSlot(el, file).catch(err => toast(err.message, true));
    });
  });
}

function bindDrops(root, onSlot) {
  $$('[data-slot]', root).forEach(el => {
    el.addEventListener('dragover', e => { e.preventDefault(); el.classList.add('drop'); });
    el.addEventListener('dragleave', () => el.classList.remove('drop'));
    el.addEventListener('drop', e => {
      e.preventDefault();
      el.classList.remove('drop');
      const file = [...(e.dataTransfer.files || [])].find(f => f.type.startsWith('image/'));
      if (file) onSlot(el, file).catch(err => toast(err.message, true));
    });
  });
}

function openLightbox(src) {
  const box = document.createElement('div');
  box.className = 'lightbox';
  box.innerHTML = `<img src="${esc(src)}" alt="">`;
  box.onclick = () => box.remove();
  document.body.appendChild(box);
}

/* ------------------------------------------------------------ editor */

const LINE_TYPES = {
  list: { hint: '한 줄에 하나', parse: l => l, show: x => x },
  tags: { hint: '한 줄에 하나', parse: l => l, show: x => x },
  flow: { hint: '한 줄에 한 단계', parse: l => l, show: x => x },
  cards: { hint: '제목 | 설명  (한 줄에 하나)', parse: l => { const [a, ...b] = l.split('|'); return { title: a.trim(), desc: b.join('|').trim() }; }, show: x => `${x.title || ''} | ${x.desc || ''}` },
  timeline: { hint: '시기 | 사건  (한 줄에 하나)', parse: l => { const [a, ...b] = l.split('|'); return { when: a.trim(), what: b.join('|').trim() }; }, show: x => `${x.when || ''} | ${x.what || ''}` },
  relations: { hint: '대상 | 관계  (한 줄에 하나)', parse: l => { const [a, ...b] = l.split('|'); return { target: a.trim(), relation: b.join('|').trim() }; }, show: x => `${stripLinks(x.target)} | ${x.relation || ''}` },
};

function imageEditor(v, key, idx) {
  v = v || {};
  return `<div class="img-ed" data-key="${key}" data-idx="${idx}">
    <div class="img-ed-thumb" data-slot="${key}" data-idx="${idx}" title="클릭, 끌어다 놓기, 붙여넣기(⌘V)">
      ${v.src ? `<img src="${esc(v.src)}" alt="">` : '<span>＋ 이미지</span>'}</div>
    <div class="img-ed-fields">
      <input class="input" data-prop="caption" placeholder="캡션" value="${esc(v.caption || '')}">
      <input class="input small" data-prop="idea" placeholder="이미지 아이디어 (메모용)" value="${esc(v.idea || '')}">
      <div class="img-ed-btns">${v.src ? '<button class="btn ghost small" data-act="clear">이미지 빼기</button>' : ''}
        ${idx !== -1 ? '<button class="btn ghost small danger" data-act="remove">항목 삭제</button>' : ''}</div>
    </div>
  </div>`;
}

function editorField(f, v) {
  const key = f.key;
  let body = '';
  if (f.type === 'text' || f.type === 'longtext') {
    body = `<textarea class="input" data-key="${key}" rows="${f.type === 'longtext' ? 8 : 3}">${esc(v || '')}</textarea>`;
  } else if (LINE_TYPES[f.type]) {
    const L = LINE_TYPES[f.type];
    body = `<textarea class="input" data-key="${key}" rows="${Math.max(3, (v || []).length + 1)}" placeholder="${L.hint}">${esc((v || []).map(L.show).join('\n'))}</textarea>
      <div class="hint">${L.hint}${f.max ? ` · 권장 최대 ${f.max}개` : ''}</div>`;
  } else if (f.type === 'keyvalue') {
    const obj = v || {};
    const keys = [...(f.keys || []), ...Object.keys(obj).filter(k => !(f.keys || []).includes(k))];
    body = `<div class="kv-ed">${keys.map(k => `<label>${esc(k)}</label><input class="input" data-key="${key}" data-k="${esc(k)}" value="${esc(obj[k] || '')}">`).join('')}</div>`;
  } else if (f.type === 'table') {
    const rows = v && v.length ? v : [f.columns.map(() => '')];
    body = `<div class="table-ed" data-key="${key}"><table><thead><tr>${f.columns.map(c => `<th>${esc(c)}</th>`).join('')}<th></th></tr></thead>
      <tbody>${rows.map((r, ri) => `<tr>${f.columns.map((_, ci) => `<td><input class="cell" data-key="${key}" data-r="${ri}" data-c="${ci}" value="${esc(r[ci] || '')}"></td>`).join('')}
        <td><button class="row-del" data-key="${key}" data-r="${ri}" title="행 삭제">×</button></td></tr>`).join('')}</tbody></table>
      <button class="btn ghost small" data-addrow="${key}">+ 행 추가</button></div>`;
  } else if (f.type === 'image') {
    body = imageEditor(v, key, -1);
  } else if (f.type === 'gallery') {
    body = `<div class="gal-ed">${(v || []).map((g, i) => imageEditor(g, key, i)).join('')}
      <button class="btn ghost small" data-addimg="${key}">+ 이미지 추가</button></div>`;
  }
  return `<div class="ed-field" id="ed-${key}"><div class="ed-label">${esc(f.label)}${f.hint ? `<span class="hint"> · ${esc(f.hint)}</span>` : ''}</div>${body}</div>`;
}

async function renderEdit(id) {
  const doc = await docApi(id);
  const t = state.tpl[doc.template] || state.tpl.note;
  doc.fields ||= {};
  state.editing = { doc, dirty: false };
  const ed = state.editing;
  const extras = (doc.extra || []).filter(x => x.body);

  const draw = () => {
    $('#main').innerHTML = `<div class="page narrow editor">
      <div class="toolbar sticky">
        <span class="badge" style="--c:${t.color}">${t.icon} ${esc(t.name)}</span>
        <span class="grow"></span>
        <span class="muted small" id="dirtyMark"></span>
        <a class="btn ghost" href="${docHref(doc.id)}">취소</a>
        <button class="btn primary" id="saveBtn" title="Ctrl+S (맥은 ⌘S)를 누르면 저장하고 계속 편집해요">저장</button>
      </div>
      <input class="input title-input" id="titleIn" value="${esc(doc.title || '')}" placeholder="제목">
      <p class="muted small">본문에서 <code>[[문서 이름]]</code>은 위키 링크, <code>**강조**</code>는 굵게. 이미지는 칸을 클릭하거나 끌어다 놓거나 ⌘V로 붙여넣어요.</p>
      ${t.fields.map(f => editorField(f, doc.fields[f.key])).join('')}
      ${extras.length ? `<div class="ed-field"><div class="ed-label">md 파일에서 직접 추가한 섹션<span class="hint"> · ${extras.map(x => esc(x.heading || '머리말')).join(', ')} — 그대로 보존돼요. 고치려면 md 파일을 직접 여세요.</span></div></div>` : ''}
    </div>`;
    bindEditor();
  };

  const markDirty = () => { ed.dirty = true; const m = $('#dirtyMark'); if (m) m.textContent = '저장 안 됨'; };

  const setImg = (key, idx, patch) => {
    if (idx === -1) doc.fields[key] = { ...(doc.fields[key] || {}), ...patch };
    else {
      const arr = doc.fields[key] = [...(doc.fields[key] || [])];
      arr[idx] = { ...(arr[idx] || {}), ...patch };
    }
  };

  const onSlot = async (slot, file) => {
    const url = await uploadImage(file);
    setImg(slot.dataset.slot, +slot.dataset.idx, { src: url });
    markDirty(); draw(); markDirty();
  };

  function bindEditor() {
    const main = $('#main');
    $('#titleIn').oninput = e => { doc.title = e.target.value; markDirty(); };
    main.oninput = e => {
      const el = e.target;
      const key = el.dataset.key;
      const f = t.fields.find(x => x.key === (key || el.closest('[data-key]')?.dataset.key));
      if (!f) return;
      if (el.dataset.prop) {
        const box = el.closest('.img-ed');
        setImg(box.dataset.key, +box.dataset.idx, { [el.dataset.prop]: el.value });
      } else if (f.type === 'text' || f.type === 'longtext') doc.fields[key] = el.value;
      else if (LINE_TYPES[f.type]) doc.fields[key] = el.value.split('\n').map(s => s.trim()).filter(Boolean).map(LINE_TYPES[f.type].parse);
      else if (f.type === 'keyvalue') doc.fields[key] = { ...(doc.fields[key] || {}), [el.dataset.k]: el.value };
      else if (f.type === 'table') {
        const rows = doc.fields[key] = (doc.fields[key] || [f.columns.map(() => '')]).map(r => [...r]);
        rows[+el.dataset.r] ||= f.columns.map(() => '');
        rows[+el.dataset.r][+el.dataset.c] = el.value;
      }
      markDirty();
    };
    main.onclick = e => {
      const b = e.target.closest('button');
      if (!b) return;
      if (b.dataset.addrow) {
        const f = t.fields.find(x => x.key === b.dataset.addrow);
        doc.fields[f.key] = [...(doc.fields[f.key] || [f.columns.map(() => '')]), f.columns.map(() => '')];
        markDirty(); draw(); markDirty();
      } else if (b.classList.contains('row-del')) {
        const rows = [...(doc.fields[b.dataset.key] || [])];
        rows.splice(+b.dataset.r, 1);
        doc.fields[b.dataset.key] = rows;
        markDirty(); draw(); markDirty();
      } else if (b.dataset.addimg) {
        doc.fields[b.dataset.addimg] = [...(doc.fields[b.dataset.addimg] || []), { caption: '' }];
        markDirty(); draw(); markDirty();
      } else if (b.dataset.act) {
        const box = b.closest('.img-ed');
        const key = box.dataset.key, idx = +box.dataset.idx;
        if (b.dataset.act === 'clear') setImg(key, idx, { src: undefined });
        if (b.dataset.act === 'remove') { const arr = [...doc.fields[key]]; arr.splice(idx, 1); doc.fields[key] = arr; }
        markDirty(); draw(); markDirty();
      }
    };
    bindSlots(main, onSlot, '.img-ed-thumb');
    bindDrops(main, onSlot);
    $$('.img-ed-thumb', main).forEach(el => el.addEventListener('mouseenter', () => (state.imageTarget = el)));
    // 저장 버튼: 저장하고 문서 화면으로. Ctrl+S / ⌘S: 저장하고 계속 편집.
    const saveDoc = async stay => {
      const body = { ...doc, fields: { ...doc.fields } };
      for (const f of t.fields) if (f.type === 'table' && body.fields[f.key]) body.fields[f.key] = body.fields[f.key].filter(r => r.some(c => (c || '').trim()));
      if (!stay) doc.fields = body.fields;
      delete body.previous; // 편집 저장은 되돌리기 기록을 건드리지 않는다
      try {
        const saved = await docApi(doc.id, { method: 'PUT', body });
        ed.dirty = false;
        await refreshDocs();
        toast('저장됨');
        if (!stay) location.hash = docHref(saved.id);
        else if (saved.id !== doc.id) location.hash = editHref(saved.id);   // 제목을 바꿔서 파일 이름이 바뀐 경우
      } catch (e) { toast(e.message, true); }
    };
    $('#saveBtn').onclick = () => saveDoc(false);
    ed.save = () => saveDoc(true);
  }

  // ⌘V 이미지 붙여넣기 → 마지막으로 가리킨 이미지 칸, 없으면 첫 갤러리에 추가
  document.onpaste = async e => {
    if (state.editing !== ed) return;
    const file = [...(e.clipboardData?.files || [])].find(f => f.type.startsWith('image/'));
    if (!file) return;
    e.preventDefault();
    let target = state.imageTarget && document.contains(state.imageTarget) ? state.imageTarget : null;
    if (!target) {
      const g = t.fields.find(f => f.type === 'gallery');
      if (!g) return;
      doc.fields[g.key] = [...(doc.fields[g.key] || []), { caption: '' }];
      draw();
      target = $(`.img-ed[data-key="${g.key}"][data-idx="${doc.fields[g.key].length - 1}"] .img-ed-thumb`);
    }
    onSlot(target, file).catch(err => toast(err.message, true));
  };

  draw();
}

/* ------------------------------------------------------------ boot */

// 맥 앱 메뉴에서 부르는 함수
window.wiki = {
  newDoc: () => (location.hash = state.project ? newHref() : '#/'),
  home: () => (location.hash = state.project ? projHref() : '#/'),
  projects: () => (location.hash = '#/'),
};

async function boot() {
  state.templates = await (await fetch('/templates.json', { cache: 'no-store' })).json();
  for (const t of state.templates) state.tpl[t.id] = t;
  await Promise.all([refreshProjects(), loadAi()]);
  // 첫 화면: 마지막으로 열었던 프로젝트
  if (!location.hash || location.hash === '#') {
    let last = null;
    try { last = localStorage.getItem('wiki.project'); } catch { /* 없음 */ }
    if (last && state.projects.some(p => p.id === last)) location.replace(projHref(last));
  }
  $('#search').addEventListener('input', renderNav);
  $('#newBtn').onclick = () => window.wiki.newDoc();
  $('#aiSelect').onchange = async e => {
    state.ai = await api('config', { method: 'PUT', body: { provider: e.target.value } });
    toast(`AI: ${state.ai.providers.find(p => p.id === state.ai.provider).label}`);
  };
  window.addEventListener('hashchange', route);
  // Ctrl+S (맥은 ⌘S): 편집 중이면 저장하고 계속 편집, 프로젝트 소개를 고치는 중이면 그걸 저장
  window.addEventListener('keydown', e => {
    if (!(e.ctrlKey || e.metaKey) || e.altKey || e.key.toLowerCase() !== 's') return;
    e.preventDefault();
    if (state.editing?.save && $('#saveBtn')) return state.editing.save();
    const desc = $('#descSave');
    if (desc && !$('#descEdit').hidden) desc.click();
  });
  // 윈도우 앱은 화면이 열려 있는 동안 서버를 켜 둔다
  checkUpdate();
  setInterval(checkUpdate, 3 * 3600 * 1000);
  checkInvites();
  const ping = () => fetch('/api/ping').catch(() => {});
  setInterval(ping, 20000);
  document.addEventListener('visibilitychange', ping);
  window.addEventListener('beforeunload', e => { if (state.editing?.dirty) e.preventDefault(); });
  // 이미지 칸 밖에 파일을 떨어뜨려도 화면이 그 파일로 바뀌지 않게
  window.addEventListener('dragover', e => e.preventDefault());
  window.addEventListener('drop', e => e.preventDefault());
  route();
}

boot().catch(e => { $('#main').innerHTML = `<div class="page"><p class="error-box">${esc(e.message)}</p></div>`; });

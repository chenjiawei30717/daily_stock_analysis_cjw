const TABS = ['selection', 'market_review', 'dashboard'];
const LABELS = { selection: '选股报告', market_review: '大盘复盘', dashboard: '自选股仪表盘' };

const state = { date: '', activeTab: 'selection' };

async function fetchJson(url) {
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error('加载失败: ' + url);
  return res.json();
}

function showContent(html) {
  document.getElementById('content').innerHTML = html;
}

function renderDateOptions(index) {
  const sel = document.getElementById('dateSelect');
  sel.innerHTML = '';
  for (const d of index.dates) {
    const opt = document.createElement('option');
    opt.value = d.date;
    opt.textContent = d.date + (d.date === index.latest ? '（最新）' : '');
    sel.appendChild(opt);
  }
  sel.value = state.date;
}

async function loadReport() {
  showContent('<p class="placeholder">加载中…</p>');
  const url = 'archive/' + state.date + '/' + state.activeTab + '.md';
  try {
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) throw new Error('no report');
    const md = await res.text();
    const html = window.marked
      ? window.marked.parse(md)
      : '<pre>' + md.replace(/</g, '&lt;') + '</pre>';
    showContent(html);
  } catch (e) {
    showContent('<p class="placeholder">📭 ' + state.date + ' 无' + LABELS[state.activeTab] + '报告</p>');
  }
}

async function init() {
  let index;
  try {
    index = await fetchJson('index.json');
  } catch (e) {
    showContent('<p class="placeholder">站点数据未就绪,请等待首次 Actions 运行生成报告</p>');
    return;
  }
  if (!index.dates || index.dates.length === 0) {
    showContent('<p class="placeholder">暂无报告,请等待首次 Actions 运行</p>');
    return;
  }
  state.date = index.latest;
  renderDateOptions(index);

  document.getElementById('tabs').addEventListener('click', (e) => {
    const btn = e.target.closest('.tab');
    if (!btn) return;
    state.activeTab = btn.dataset.tab;
    document.querySelectorAll('.tab').forEach(b =>
      b.classList.toggle('active', b.dataset.tab === state.activeTab));
    loadReport();
  });

  document.getElementById('dateSelect').addEventListener('change', (e) => {
    state.date = e.target.value;
    loadReport();
  });

  loadReport();
}

init();
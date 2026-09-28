'use strict';

const $ = (selector) => document.querySelector(selector);
const samples = {
  support: '매일 들어오는 고객 문의를 읽고 담당 부서에 배정하는 업무를 개선하고 싶습니다. 문의를 유형별로 자동 분류하고 답변 초안을 제안하되, 담당자가 확인한 뒤 고객에게 보내는 방식입니다. 기존 문의 데이터의 품질, 운영 비용, 현업 사용성을 함께 검토해 주세요.',
  report: '여러 팀의 주간 업무 메모를 모아 보고서로 만드는 반복 업무를 자동화하고 싶습니다. 서로 다른 양식의 메모에서 진행 상황과 지연 항목을 추출하고, 공통 양식의 보고서를 생성한 뒤 팀장이 검토하는 흐름입니다. 작은 범위에서 검증하는 방법을 제안해 주세요.',
  quality: '공장별 PDF 불량 리포트를 모아 원인과 조치 현황을 비교하는 대시보드를 만들고 싶습니다. 문서에서 수치를 추출하고, 원문 근거를 보여주며, 담당자가 수정할 수 있어야 합니다. 데이터 정확성과 도입 비용, 현장 활용성을 함께 검토해 주세요.',
};
const labels = { orchestrator: 'Orchestrator', technical: '기술', business: '비용', user: '사용자' };
const phaseLabels = { draft: '초안 검토', feedback: '피드백', revise: '수정 요청' };
let current = null;
let activeTab = 'summary';
let polling = false;
let connected = false;
let traceRendered = 0;
let panelSignature = '';

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, signal: AbortSignal.timeout(12000) });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : '입력과 서버 상태를 확인해 주세요.');
  }
  return response.json();
}

function updateCount() { $('#char-count').textContent = `${$('#proposal').value.length.toLocaleString()} / 4,000`; }
$('#proposal').addEventListener('input', updateCount);
document.querySelectorAll('.sample').forEach((button) => button.addEventListener('click', () => {
  $('#proposal').value = samples[button.dataset.sample]; updateCount(); $('#proposal').focus();
}));
$('#mode').addEventListener('change', () => {
  $('#mode-note').textContent = $('#mode').value === 'demo'
    ? 'LLM 미사용. 규칙 기반 예시로 협업 구조를 보여줍니다. A2A 통신은 실제로 수행합니다.'
    : '서버에 설정한 Claude API로 분석합니다. 입력 자료가 Anthropic으로 전송되며 API 비용이 발생합니다.';
});

function setBusy(busy) {
  polling = busy;
  $('#start').disabled = busy || !connected;
  $('#start span').textContent = busy ? '전문가들이 검토 중입니다' : '검토 시작하기';
  $('#proposal').disabled = busy; $('#mode').disabled = busy;
  document.querySelectorAll('.sample').forEach((b) => { b.disabled = busy; });
}

function showError(message) { $('#form-error').textContent = message; $('#form-error').hidden = false; }

function renderTrace(events) {
  if (traceRendered === 0) $('#trace-list').replaceChildren();
  events.slice(traceRendered).forEach((event) => {
    const detail = node('details', undefined, `trace-row ${event.kind === 'error' ? 'error-row' : ''}`);
    const arrow = event.kind === 'response' ? '←' : '→';
    const state = { request: '요청', response: '응답', error: '실패' }[event.kind];
    detail.append(node('summary', `${String(event.seq).padStart(2, '0')}  ${labels[event.source]} ${arrow} ${labels[event.target]} · ${phaseLabels[event.phase]} · ${state}${event.elapsed_ms !== undefined ? ` / ${event.elapsed_ms}ms` : ''}`));
    detail.append(node('pre', JSON.stringify(event, null, 2)));
    $('#trace-list').append(detail);
  });
  traceRendered = events.length;
  $('#trace-count').textContent = `${events.length} EVENTS`;
}

function contentBlock(content) {
  const block = node('div');
  if (!content) { block.append(node('p', '아직 결과가 없습니다. 진행 상태와 누락·오류 안내를 확인해 주세요.', 'muted')); return block; }
  block.append(node('span', { pilot: '소규모 검증 제안', proceed: '진행 검토', rework: '보완 필요' }[content.position], 'verdict'));
  block.append(node('h3', content.headline, 'result-title'));
  const fields = { findings: '검토 내용', risks: '우려 · 남은 이견', actions: '실행 단계', metrics: '검증 지표', changes: '피드백 반영' };
  Object.entries(fields).forEach(([key, title]) => {
    if (!content[key]?.length) return;
    const section = node('section', undefined, 'result-section');
    section.append(node('h3', title));
    const list = node('ul'); content[key].forEach((text) => list.append(node('li', text)));
    section.append(list); block.append(section);
  });
  return block;
}

function renderPanel() {
  if (!current) return;
  const review = current.reviews[activeTab];
  const signature = JSON.stringify([activeTab, activeTab === 'summary' ? current.summary : review]);
  if (signature === panelSignature) return;
  panelSignature = signature;
  const panel = $('#result-panel'); panel.replaceChildren();
  panel.setAttribute('aria-labelledby', `tab-${activeTab}`);
  if (activeTab === 'summary') panel.append(contentBlock(current.summary));
  else {
    panel.append(contentBlock(review?.revised || review?.draft));
    if (review?.revised) {
      const detail = node('details', undefined, 'draft-detail');
      detail.append(node('summary', '피드백 이전 초안 비교하기')); detail.append(contentBlock(review.draft)); panel.append(detail);
    }
    if (review?.feedback && Object.keys(review.feedback).length) {
      const detail = node('details', undefined, 'draft-detail'); detail.append(node('summary', '다른 전문가에게 받은 피드백'));
      Object.entries(review.feedback).forEach(([name, feedback]) => {
        detail.append(node('h3', `${labels[name]} 전문가`)); detail.append(contentBlock(feedback));
      }); panel.append(detail);
    }
  }
}

const tabs = [...document.querySelectorAll('[role="tab"]')];
function selectTab(button) {
  activeTab = button.dataset.tab;
  tabs.forEach((t) => { t.setAttribute('aria-selected', String(t === button)); t.tabIndex = t === button ? 0 : -1; });
  renderPanel();
}
tabs.forEach((button, index) => {
  button.addEventListener('click', () => selectTab(button));
  button.addEventListener('keydown', (event) => {
    let target;
    if (event.key === 'ArrowRight') target = tabs[(index + 1) % tabs.length];
    if (event.key === 'ArrowLeft') target = tabs[(index + tabs.length - 1) % tabs.length];
    if (event.key === 'Home') target = tabs[0];
    if (event.key === 'End') target = tabs.at(-1);
    if (target) { event.preventDefault(); selectTab(target); target.focus(); }
  });
});

function render(run) {
  current = run;
  const running = run.status === 'running';
  const states = { running: '검토 진행 중', completed: '검토 완료', partial: '일부 검토 누락', failed: '검토 실패' };
  $('#run-status').textContent = states[run.status]; $('#run-status').className = `badge ${running ? 'active' : run.status}`;
  $('#orchestrator-state').textContent = running ? 'WORKING' : run.status === 'failed' ? 'FAILED' : 'DONE';
  const stages = ['draft', 'feedback', 'synthesize'];
  document.querySelectorAll('[data-stage]').forEach((element) => {
    element.classList.toggle('current', run.stage === element.dataset.stage);
    element.classList.toggle('done', run.status === 'completed' || stages.indexOf(element.dataset.stage) < stages.indexOf(run.stage));
  });
  document.querySelectorAll('[data-agent]').forEach((element) => {
    const name = element.dataset.agent;
    const pending = run.events.filter((e) => e.kind === 'request' && e.target === name && !run.events.some((r) => r.message_id === e.message_id && r.kind !== 'request'));
    const failed = run.events.some((e) => e.target === name && e.kind === 'error');
    const done = !!run.reviews[name]?.revised;
    const state = running && pending.length ? 'working' : failed ? 'failed' : done ? 'completed' : '';
    element.className = `expert ${state}`;
    element.querySelector('.agent-state').textContent = { working: '검토 중', failed: '누락 있음', completed: '완료' }[state] || (run.reviews[name] ? '초안 완료' : running ? '대기' : '미완료');
  });
  const requests = run.events.filter((e) => e.kind === 'request');
  const completedPeers = run.events.filter((e) => e.kind === 'response' && e.phase === 'feedback').length;
  $('#peer-count').textContent = `${completedPeers} / 6`;
  $('#request-count').textContent = `${requests.length} MESSAGES`;
  const descriptions = { draft: '각 전문가가 자신의 관점에서 제안을 검토합니다.', feedback: '전문가들이 A2A 메시지로 의견을 주고받고 초안을 수정합니다.', synthesize: '전문가 검토를 모아 실행 단계와 남은 이견을 정리합니다.' };
  $('#live-status').textContent = running ? descriptions[run.stage] : run.status === 'completed' ? '세 관점의 검토와 상호 피드백이 완료되었습니다.' : '누락·오류 안내를 확인해 주세요. 새 검토를 시작할 수 있습니다.';
  $('#result-empty').hidden = true; $('#result-content').hidden = false;
  $('#result-disclosure').textContent = run.mode === 'demo' ? 'DEMO · LLM 미사용 — 규칙 기반 예시입니다. 실제 입력을 AI로 분석한 결과가 아닙니다.' : 'CLAUDE API · AI 생성 결과입니다. 근거와 적용 가능성을 사람이 확인하세요.';
  $('#run-errors').hidden = !run.errors.length;
  $('#run-errors').replaceChildren(...run.errors.map((message) => node('p', message)));
  $('#download').hidden = running;
  if (!running) $('#download').href = `/api/runs/${run.id}/report`;
  renderPanel(); renderTrace(run.events);
}

async function poll(id) {
  let failures = 0;
  while (polling) {
    try {
      const run = await api(`/api/runs/${id}`); failures = 0; render(run);
      $('#form-error').hidden = true;
      if (run.status !== 'running') { setBusy(false); sessionStorage.removeItem('studio-run'); return; }
    } catch (error) {
      failures += 1; showError(`진행 상태를 확인하지 못했습니다. ${error.message}`);
      if (failures >= 3) { setBusy(false); showError('연결이 끊겼습니다. 서버를 확인하고 새로고침하면 저장된 실행의 상태를 다시 확인합니다.'); return; }
    }
    await new Promise((resolve) => setTimeout(resolve, 600));
  }
}

$('#review-form').addEventListener('submit', async (event) => {
  event.preventDefault(); if (polling) return;
  if ($('#proposal').value.trim().length < 20) { showError('공백을 제외한 내용을 포함해 20자 이상 입력해 주세요.'); return; }
  $('#form-error').hidden = true; setBusy(true);
  try {
    const run = await api('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ proposal: $('#proposal').value, mode: $('#mode').value }) });
    sessionStorage.setItem('studio-run', run.id); traceRendered = 0; panelSignature = ''; selectTab(tabs[0]);
    await poll(run.id);
  } catch (error) { showError(error.message); setBusy(false); }
});

async function init() {
  try {
    const config = await api('/api/config'); connected = true;
    $('#connection').textContent = 'LOCAL WORKSPACE';
    const option = $('#mode option[value="claude"]');
    option.disabled = !config.claude_available;
    option.textContent = config.claude_available ? `Claude API · ${config.claude_model}` : 'Claude API · 서버 설정 필요';
    setBusy(false);
    const saved = sessionStorage.getItem('studio-run');
    if (saved) {
      try {
        const run = await api(`/api/runs/${saved}`); $('#proposal').value = run.proposal; $('#mode').value = run.mode; updateCount(); $('#mode').dispatchEvent(new Event('change')); render(run);
        if (run.status === 'running') { setBusy(true); await poll(saved); } else sessionStorage.removeItem('studio-run');
      } catch { sessionStorage.removeItem('studio-run'); setBusy(false); }
    }
  } catch { $('#connection').textContent = '연결 실패'; showError('서버에 연결할 수 없습니다. 서버 실행 후 페이지를 새로고침하세요.'); }
}
init();

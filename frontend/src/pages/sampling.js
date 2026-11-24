import {GRADES} from '../labels.js';
import {auditList, channelInputs, empty, heading, lotPicker, number, safe, sectionTitle, status, time} from '../ui.js';

const pct = value => value == null ? '—' : `${(value * 100).toFixed(2)}%`;

function summaryStrip(plan, ev) {
  return `<div class="lot-strip"><div><small>方案状态</small>${status(plan.state)}</div>
    <div><small>加权估计 C 级占比</small><b class="mono">${pct(ev.estimate)}</b></div>
    <div><small>95% 加权区间</small><b class="mono">[${pct(ev.low)}, ${pct(ev.high)}]</b></div>
    <div><small>阈值 / 置信度</small><b class="mono">${pct(ev.threshold)} / ${pct(ev.confidence)}</b></div>
    <div><small>已判 / 总件数</small><b class="mono">${number(ev.total_judged)} / ${number(ev.total_units)}</b></div>
    <div><small>C 级检出</small><b class="mono">${number(ev.total_c)}</b></div>
    <div><small>待判件号</small><b class="mono">${number(ev.pending)}</b></div></div>`;
}

function palletCard(pallet, planState, account) {
  const progress = Math.min(100, pallet.judged / pallet.units * 100);
  const canRound = account.role === 'operator' && pallet.pending === 0 && pallet.issued < pallet.units
    && ['sampling', 'ready'].includes(planState);
  return `<article class="panel pallet"><div class="pallet-head"><h3>托盘 ${safe(pallet.label)}</h3><div>${status(pallet.state)}${pallet.conclusion ? status(pallet.conclusion) : ''}</div></div>
    <div class="pallet-stats">
      <div><small>托盘件数</small><b class="mono">${number(pallet.units)}</b></div>
      <div><small>已判 / 已发件号</small><b class="mono">${number(pallet.judged)} / ${number(pallet.issued)}</b></div>
      <div><small>C 级检出</small><b class="mono">${number(pallet.c)}</b></div>
      <div><small>观测占比</small><b class="mono">${pct(pallet.rate)}</b></div>
    </div>
    <p class="pallet-interval mono">95% 区间 [${pct(pallet.low)}, ${pct(pallet.high)}]</p>
    <div class="progress" aria-label="判级进度"><i style="--p:${progress}%"></i></div>
    <div class="pallet-foot"><small class="muted">${pallet.pending ? `${number(pallet.pending)} 件待判` : pallet.conclusion === 'pass' ? '区间上限低于 2%，结论合格' : pallet.conclusion === 'fail' ? '实测达到 2%，结论超阈' : pallet.issued >= pallet.units ? '件号已全部发放' : '等待补抽'}</small>
    ${canRound ? `<form data-action="sampling/rounds"><input type="hidden" name="pallet_id" value="${pallet.id}"><button>补抽</button></form>` : ''}</div></article>`;
}

function pendingTable(items, planState, account) {
  const canGrade = account.role === 'operator' && ['sampling', 'ready', 'full_inspection'].includes(planState);
  return `<section class="panel">${sectionTitle('待判件号', `${items.length} 件${items.length === 200 ? '（仅显示前 200）' : ''}`)}
    ${items.length ? `<div class="scroll-x"><table><thead><tr><th>托盘</th><th>件号</th><th>抽次</th><th></th></tr></thead><tbody>
      ${items.map(item => `<tr><td>${safe(item.pallet_label)}</td><td class="mono">#${item.item_no}</td><td class="mono">第 ${item.round_no} 抽次</td>
        <td>${canGrade ? `<button data-grade-item="${item.id}" data-item-no="${item.item_no}" data-pallet="${safe(item.pallet_label)}">判级</button>` : ''}</td></tr>`).join('')}
    </tbody></table></div>` : empty('没有待判件号', '所有已发件号均已判齐。')}</section>`;
}

function roundsTable(rounds) {
  return `<section class="panel">${sectionTitle('抽次记录', `${rounds.length} 次`)}
    ${rounds.length ? `<div class="scroll-x"><table><thead><tr><th>托盘</th><th>抽次</th><th>类型</th><th>发放件数</th><th>判级进度</th><th>定号种子</th><th>发放时间</th></tr></thead><tbody>
      ${rounds.map(round => `<tr><td>${safe(round.pallet_label)}</td><td class="mono">#${round.round_no}</td><td>${status(round.kind)}</td><td class="mono">${number(round.draw_size)}</td><td class="mono">${round.judged} / ${round.draw_size}</td><td class="mono">${safe(round.seed)}</td><td>${time(round.created_at)}</td></tr>`).join('')}
    </tbody></table></div>` : empty('尚无抽次', '登记方案后自动发放首轮件号。')}</section>`;
}

function recentTable(items) {
  if (!items.length) return '';
  return `<section class="panel">${sectionTitle('最近判级', `${items.length} 件`)}<div class="scroll-x"><table><thead><tr><th>托盘</th><th>件号</th><th>等级</th><th>判级人</th><th>时间</th></tr></thead><tbody>
    ${items.map(item => `<tr><td>${safe(item.pallet_label)}</td><td class="mono">#${item.item_no}</td><td><b class="grade-inline" title="${GRADES[item.grade] || ''}">${safe(item.grade)}</b></td><td>${safe(item.judged_by)}</td><td>${time(item.judged_at)}</td></tr>`).join('')}
  </tbody></table></div></section>`;
}

function signPanel(plan, ev, account) {
  if (plan.state === 'signed') {
    const basis = plan.basis;
    return `<section class="panel basis">${sectionTitle('签核依据', `${safe(plan.signed_by)} · ${time(plan.signed_at)}`)}
      <div class="pallet-stats">
        <div><small>加权估计</small><b class="mono">${pct(basis.estimate)}</b></div>
        <div><small>95% 加权区间</small><b class="mono">[${pct(basis.low)}, ${pct(basis.high)}]</b></div>
        <div><small>已判 / 总件数</small><b class="mono">${number(basis.total_judged)} / ${number(basis.total_units)}</b></div>
        <div><small>C 级检出</small><b class="mono">${number(basis.total_c)}</b></div>
      </div>
      <div class="scroll-x"><table><thead><tr><th>托盘</th><th>件数</th><th>已判</th><th>C 级</th><th>观测占比</th><th>95% 区间</th><th>结论</th></tr></thead><tbody>
        ${basis.pallets.map(pallet => `<tr><td>${safe(pallet.label)}</td><td class="mono">${number(pallet.units)}</td><td class="mono">${number(pallet.judged)}</td><td class="mono">${number(pallet.c)}</td><td class="mono">${pct(pallet.rate)}</td><td class="mono">[${pct(pallet.low)}, ${pct(pallet.high)}]</td><td>${status(pallet.conclusion)}</td></tr>`).join('')}
      </tbody></table></div>
      ${basis.note ? `<p class="notice">${safe(basis.note)}</p>` : ''}</section>`;
  }
  if (plan.state === 'rejected') {
    return `<section class="panel">${sectionTitle('签核', '按实数判')}<p class="notice warn">抽完全检后实测 C 级占比 ${pct(ev.estimate)}，达到 ${pct(ev.threshold)} 阈值，方案已判退，不得签核放行。</p></section>`;
  }
  const gates = [
    [ev.pending === 0, `已发件号判齐（待判 ${number(ev.pending)}）`],
    [ev.pallets.every(pallet => pallet.conclusion), '各托盘均有结论'],
    [ev.high < ev.threshold, `加权区间上限低于 ${pct(ev.threshold)}（当前 ${pct(ev.high)}）`],
  ];
  return `<section class="panel">${sectionTitle('签核', '质检主管')}
    <ul class="gate-list">${gates.map(([ok, label]) => `<li class="${ok ? 'ok' : ''}">${ok ? '✓' : '○'} ${label}</li>`).join('')}</ul>
    ${account.role === 'supervisor' && plan.state === 'ready'
      ? `<form class="fields" data-action="sampling/sign"><label class="full">签核说明<input name="note" required minlength="2" maxlength="300" placeholder="记录签核依据说明"></label><button class="primary full">签核放行</button></form>`
      : `<p class="muted">${account.role === 'supervisor' ? '签核条件未全部满足，继续抽检或等待判齐。' : '等待质检主管签核。'}</p>`}</section>`;
}

export function samplingPage(lots, data, account) {
  if (!data) return `${heading('包装线 / 托盘抽检', '托盘抽检', '从批次台账打开包装批次，登记或查看抽检方案。')}${empty('找不到所选批次', '请回到批次台账选择有效记录。')}<a data-nav href="/lots">返回包装批次 →</a>`;
  const {lot, plan} = data;
  const head = heading('包装线 / 托盘抽检', '托盘抽检', '按托盘件数加权估计整批 C 级占比，区间上限低于 2% 才可签核。', lotPicker(lots, lot.id, 'sampling'));
  const strip = `<div class="lot-strip"><div><small>包装批次</small><b>${safe(lot.code)}</b></div><div><small>产品</small><b>${safe(lot.product)}</b></div><div><small>批次件数</small><b class="mono">${number(lot.units)}</b></div>${status(lot.state)}</div>`;
  if (!plan) {
    return `${head}${strip}${empty('尚未登记抽检方案', '登记各托盘件数后，系统随机定号并发放首轮件号。')}
      ${account.role === 'operator' ? '<button class="primary" data-dialog="plan">＋ 登记抽检方案</button>' : '<p class="muted">等待线边操作员登记抽检方案。</p>'}
      ${planDialog(lot)}`;
  }
  const ev = data.evaluation;
  return `${head}${strip}${summaryStrip(plan, ev)}
    <div class="pallet-grid">${ev.pallets.map(pallet => palletCard(pallet, plan.state, account)).join('')}</div>
    <div class="sampling-grid">${pendingTable(data.pending_items, plan.state, account)}${signPanel(plan, ev, account)}</div>
    ${roundsTable(data.rounds)}${recentTable(data.recent_items)}
    <aside class="panel trace">${sectionTitle('抽检履历', '按时间倒序')}${auditList(data.events)}</aside>
    ${gradeDialog()}${planDialog(lot)}`;
}

function planDialog(lot) {
  return `<dialog id="plan"><div class="dialog-heading"><h2>登记抽检方案</h2><button data-dismiss="plan" aria-label="关闭">×</button></div>
    <p>批次共 <b class="mono">${number(lot.units)}</b> 件。逐托盘登记件数，合计须等于批次件数；登记后按 95% 置信度发放首轮随机件号。</p>
    <form id="plan-form" class="fields" data-action="sampling/plan"><div class="full" data-pallet-rows>
      <div class="pallet-row"><input name="plabel" required maxlength="120" placeholder="托盘号，如 P1"><input name="punits" type="number" min="1" max="2000000" required placeholder="件数"></div>
    </div><button type="button" data-add-pallet>＋ 添加托盘</button><button class="primary full">登记并发放首轮件号</button></form></dialog>`;
}

function gradeDialog() {
  return `<dialog id="grade-item"><div class="dialog-heading"><h2>件号判级</h2><button data-dismiss="grade-item" aria-label="关闭">×</button></div>
    <p class="item-ref mono"></p><form class="fields" data-action="">${channelInputs({})}<button class="primary full">提交判级</button></form></dialog>`;
}

// 口播IP智能体 · UI 原型手册 PDF 构建脚本
// 1) 用 Playwright 截取 docs/ui-mockup 下 15 个核心页面（隐藏临时 mock-nav）
// 2) 为 create.html 生成 7 步流水线各步骤状态变体截图
// 3) 拼装品牌化 report.html 并打印为 PDF
import { chromium } from '@playwright/test';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const MOCKUP = path.join(ROOT, 'docs', 'ui-mockup');
const OUT = path.join(MOCKUP, '.pdf-build');
const SHOTS = path.join(OUT, 'shots');
const PDF_PATH = path.join(ROOT, 'docs', '口播IP智能体-UI原型手册.pdf');
fs.mkdirSync(SHOTS, { recursive: true });

const STEP_NAMES = ['链接/选题', '文案', '声音', '数字人', '合成', '剪辑', '发布'];

// 页面清单（按用户指定顺序）：file / 模块名 / 分组 / 简介 / 所属核心流程
const PAGES = [
  { file: 'index.html', name: '工作台', group: '创作', flow: '① 链接/选题',
    desc: '产品首页与创作入口：Hero 区粘贴爆款链接或输入关键词选题，平台自动识别（抖音/快手/小红书），支持手动上传；展示 IP 概览、进行中任务与快捷入口。' },
  { file: 'create.html', name: '一键成片', group: '创作', flow: '① 链接/选题 → ⑦ 发布',
    desc: '核心流水线向导：一个输入框解决一切，提交后自动执行 7 步流水线（链接/选题 → 文案 → 声音 → 数字人 → 合成 → 剪辑 → 发布），全自动模式开启，每步仍可中途干预。' },
  { file: 'profile.html', name: 'IP 档案', group: '资产', flow: '全局动线 · 第 1 步',
    desc: 'IP 人设的单一事实来源：基础信息、人设标签、语气风格、内容禁区与绑定资产（声音/数字人/素材），支持多 IP 切换管理。' },
  { file: 'scripts.html', name: '文案工坊', group: '创作', flow: '② 文案',
    desc: '爆款文案解析与仿写：链接解析原文、结构拆解（黄金 3 秒/痛点/钩子）、人设化改写与敏感词检测，支持批量生成与版本对比。' },
  { file: 'editor.html', name: '视频剪辑', group: '创作', flow: '⑤ 合成 → ⑥ 发布',
    desc: '成片微调工作台：字幕校对、封面选择、片段裁剪与 BGM 替换，导出 MP4 或一键分发至多平台。' },
  { file: 'tasks.html', name: '任务中心', group: '创作', flow: '⑤ 合成（进度可视化）',
    desc: '批量队列与流水线进度中心：任务卡片内嵌迷你流水线（mini-pipe）实时展示 解析→文案→声音→数字人→合成→剪辑→发布 各步状态，支持暂停/重试/失败处理。' },
  { file: 'avatars.html', name: '数字人中心', group: '资产', flow: '④ 数字人',
    desc: '数字分身训练与管理：飞影 API 训练新分身、训练状态跟踪、合规授权存证，按 IP 筛选已就绪分身。' },
  { file: 'voices.html', name: '声音中心', group: '资产', flow: '③ 声音',
    desc: '声音克隆与音色库：上传样本克隆专属音色、试听对比、情绪/语速参数调节，绑定至 IP 人设。' },
  { file: 'assets.html', name: '素材库', group: '资产', flow: '⑤ 合成（素材供给）',
    desc: '封面、BGM、视频片段与水印的统一资产管理，按类型/平台筛选，供合成与剪辑环节调用。' },
  { file: 'templates.html', name: '模板中心', group: '资产', flow: '② 文案 / ⑤ 合成',
    desc: '口播模板与结构范式库：分行业分场景的爆款模板，一键套用到文案仿写与成片合成。' },
  { file: 'publish.html', name: '发布管理', group: '分发', flow: '⑥ 发布',
    desc: '多平台发布与排期：成片一键分发抖音/快手/小红书，定时发布、发布队列与失败重试，平台账号状态联动。' },
  { file: 'accounts.html', name: '账号管理', group: '分发', flow: '⑥ 发布（账号基建）',
    desc: '平台账号绑定与登录态巡检：已绑定账号状态总览、每日自动巡检、授权续期提醒与新账号绑定向导。' },
  { file: 'analytics.html', name: '数据看板', group: '分发', flow: '⑥ 发布（效果回流）',
    desc: '多平台数据回流与选题洞察：播放量趋势、平台分布、爆款归因分析，输出选题建议反哺创作。' },
  { file: 'settings.html', name: '算力设置', group: '系统', flow: '全局（算力/额度）',
    desc: '算力调度策略：云端优先、本地备用的算力切换，额度消耗明细、充值与预警阈值设置。' },
  { file: 'account.html', name: '我的账号', group: '系统', flow: '全局（账户体系）',
    desc: '个人账户中心：账号信息、安全设置、订阅套餐与登录设备管理。' },
];

const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');

async function shot(page, name, fullPage = true) {
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage });
  console.log('  ✓', name);
}

async function main() {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
  });
  const page = await ctx.newPage();
  const hideMockNav = '.mock-nav{display:none!important}';

  console.log('== 1/3 截取 15 个模块页面 ==');
  for (const p of PAGES) {
    await page.goto('file://' + path.join(MOCKUP, p.file), { waitUntil: 'networkidle' });
    await page.addStyleTag({ content: hideMockNav });
    await page.waitForTimeout(250);
    await shot(page, p.file.replace('.html', ''));
  }

  console.log('== 2/3 生成 create.html 7 步流水线状态变体 ==');
  await page.goto('file://' + path.join(MOCKUP, 'create.html'), { waitUntil: 'networkidle' });
  await page.addStyleTag({ content: hideMockNav });
  for (let k = 1; k <= 7; k++) {
    await page.evaluate((step) => {
      const steps = [...document.querySelectorAll('.stepper .step')];
      const lines = [...document.querySelectorAll('.stepper .step-line')];
      steps.forEach((el, i) => {
        el.classList.remove('done', 'current');
        if (i < step - 1) el.classList.add('done');
        if (i === step - 1) el.classList.add('current');
      });
      lines.forEach((el, i) => el.classList.toggle('done', i < step - 1));
      const title = document.querySelector('.card:has(.stepper) .card-title .more');
      if (title) title.textContent = `⚡ 全自动模式 · 当前执行：第 ${step} 步 / 共 7 步`;
    }, k);
    await page.waitForTimeout(120);
    const card = page.locator('.card:has(.stepper)');
    await card.screenshot({ path: path.join(SHOTS, `create-step-${k}.png`) });
    console.log('  ✓ create-step-' + k, `(${STEP_NAMES[k - 1]})`);
  }

  console.log('== 3/3 拼装报告并输出 PDF ==');
  const flowRows = [
    ['①', '链接/选题', '工作台 / 一键成片', 'index.html · create.html', '粘贴爆款链接或输入关键词，平台自动识别'],
    ['②', '文案', '文案工坊', 'scripts.html', '解析原文 → 结构拆解 → 人设化仿写 → 敏感词检测'],
    ['③', '声音', '声音中心', 'voices.html', '克隆音色绑定 IP，情绪/语速参数化'],
    ['④', '数字人', '数字人中心', 'avatars.html', '分身训练、合规授权、按 IP 调用'],
    ['⑤', '合成', '任务中心 / 视频剪辑', 'tasks.html · editor.html', '云端渲染合成，任务中心实时可视化进度，剪辑微调'],
    ['⑥', '发布', '发布管理 / 账号管理 / 数据看板', 'publish.html · accounts.html · analytics.html', '多平台分发排期，登录态巡检，数据回流反哺选题'],
  ];

  const stepVariantImgs = Array.from({ length: 7 }, (_, i) => `
    <figure class="variant">
      <img src="shots/create-step-${i + 1}.png" alt="第${i + 1}步">
      <figcaption>第 ${i + 1} 步 · ${STEP_NAMES[i]}（当前步高亮，前序步骤已完成）</figcaption>
    </figure>`).join('');

  const moduleSections = PAGES.map((p, i) => {
    const id = p.file.replace('.html', '');
    const extra = p.file === 'create.html'
      ? `
    <section class="module">
      <div class="mhead">
        <span class="mnum">02·附</span>
        <h2>一键成片 · 7 步流水线状态</h2>
        <span class="tag flow">全自动执行 · 每步可干预</span>
        <span class="file">create.html · stepper</span>
      </div>
      <p class="desc">步骤条（stepper）逐一高亮「链接/选题 → 文案 → 声音 → 数字人 → 合成 → 剪辑 → 发布」7 个步骤的进行状态：已完成步骤以品牌渐变填充，当前步骤青色描边高亮，连接线同步渐变推进。</p>
      <div class="vgrid">${stepVariantImgs}</div>
    </section>` : '';
    return `
    <section class="module">
      <div class="mhead">
        <span class="mnum">${String(i + 1).padStart(2, '0')}</span>
        <h2>${p.name}</h2>
        <span class="tag">${p.group}</span>
        <span class="tag flow">${p.flow}</span>
        <span class="file">${p.file}</span>
      </div>
      <p class="desc">${esc(p.desc)}</p>
      <img class="shot" src="shots/${id}.png" alt="${p.name}">
    </section>${extra}`;
  }).join('\n');

  const report = `<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  :root { --brand-from:#6366F1; --brand-to:#22D3EE; --text-2:#9CA3AF; --text-3:#6B7280; }
  body { font-family:"PingFang SC","Microsoft YaHei","Segoe UI",system-ui,sans-serif;
         background:#0B0E14; color:#E5E7EB; font-size:12px; }
  @page { size: A4 landscape; margin: 0; }
  .page { width: 297mm; height: 210mm; page-break-after: always; overflow: hidden;
          padding: 12mm 14mm; position: relative;
          background:
            radial-gradient(1200px 600px at 85% -10%, rgba(99,102,241,.16), transparent 60%),
            radial-gradient(900px 500px at -10% 110%, rgba(34,211,238,.12), transparent 55%),
            linear-gradient(160deg,#0B0E14,#111827); }
  /* 封面 */
  .cover { display:flex; flex-direction:column; justify-content:center; }
  .cover .kicker { color:var(--brand-to); letter-spacing:4px; font-size:13px; margin-bottom:14px; }
  .cover h1 { font-size:44px; line-height:1.25; margin-bottom:16px; }
  .grad { background:linear-gradient(90deg,var(--brand-from),var(--brand-to));
          -webkit-background-clip:text; background-clip:text; color:transparent; }
  .cover .sub { color:var(--text-2); font-size:15px; max-width:170mm; line-height:1.8; }
  .cover .meta { position:absolute; bottom:14mm; left:14mm; color:var(--text-3); font-size:12px; line-height:1.9; }
  .cover .badge { display:inline-block; padding:6px 14px; border-radius:999px; margin-top:22px;
                  border:1px solid rgba(99,102,241,.45); background:rgba(99,102,241,.12); color:#C7D2FE; font-size:12px; }
  /* 流程总览 */
  h2.pt { font-size:24px; margin-bottom:4px; }
  .psub { color:var(--text-3); margin-bottom:16px; font-size:12.5px; }
  table.flow { width:100%; border-collapse:collapse; font-size:12px; }
  table.flow th { text-align:left; color:var(--text-3); font-weight:500; padding:8px 10px;
                  border-bottom:1px solid rgba(255,255,255,.14); font-size:11.5px; letter-spacing:1px; }
  table.flow td { padding:10px; border-bottom:1px solid rgba(255,255,255,.06); vertical-align:top; line-height:1.6; }
  table.flow .no { font-size:18px; font-weight:700;
                   background:linear-gradient(135deg,var(--brand-from),var(--brand-to));
                   -webkit-background-clip:text; background-clip:text; color:transparent; }
  table.flow .st { font-weight:600; font-size:13.5px; }
  table.flow code { color:#67E8F9; font-size:11px; }
  .note { margin-top:14px; padding:12px 14px; border-radius:12px; font-size:12px; line-height:1.8;
          background:rgba(255,255,255,.04); border:1px solid rgba(255,255,255,.08); color:var(--text-2); }
  /* 模块页 */
  section.module { width:297mm; height:210mm; page-break-after:always; overflow:hidden;
                   padding:10mm 14mm; position:relative;
                   background:
                     radial-gradient(1200px 600px at 85% -10%, rgba(99,102,241,.10), transparent 60%),
                     linear-gradient(160deg,#0B0E14,#111827); }
  .mhead { display:flex; align-items:baseline; gap:12px; margin-bottom:6px; }
  .mnum { font-size:22px; font-weight:800;
          background:linear-gradient(135deg,var(--brand-from),var(--brand-to));
          -webkit-background-clip:text; background-clip:text; color:transparent; }
  .mhead h2 { font-size:20px; }
  .tag { padding:3px 10px; border-radius:999px; font-size:10.5px;
         background:rgba(99,102,241,.14); border:1px solid rgba(99,102,241,.4); color:#C7D2FE; }
  .tag.flow { background:rgba(34,211,238,.10); border-color:rgba(34,211,238,.4); color:#A5F3FC; }
  .file { margin-left:auto; color:var(--text-3); font-size:11px; }
  .desc { color:var(--text-2); font-size:12px; line-height:1.7; margin-bottom:8px; max-width:250mm; }
  img.shot { display:block; max-width:100%; max-height:138mm; object-fit:contain;
             border-radius:10px; border:1px solid rgba(255,255,255,.10);
             box-shadow:0 12px 40px rgba(0,0,0,.45); }
  .variants { display:grid; grid-template-columns:repeat(2,1fr); gap:6mm 8mm; margin-top:8mm; }
  .variant img { width:100%; border-radius:8px; border:1px solid rgba(255,255,255,.10); }
  .variant figcaption { color:var(--text-3); font-size:10.5px; margin-top:4px; }
  /* create 步骤变体页：两列网格，一页放 7 张 */
  .vgrid { display:grid; grid-template-columns:1fr 1fr; gap:4mm 6mm; margin-top:4mm; }
  .vgrid .variant img { width:100%; max-height:20mm; object-fit:contain; object-position:left top; background:#111827; }
</style></head><body>

<div class="page cover">
  <div class="kicker">ORAL IP AGENTS · UI PROTOTYPE BOOK</div>
  <h1>口播IP智能体<br><span class="grad">前端 UI 原型手册</span></h1>
  <div class="sub">覆盖 15 个核心模块页面与「链接 → 文案 → 声音 → 数字人 → 合成 → 发布」6 步核心流程，
    完整呈现一键成片 7 步流水线向导、全局动线导航（flow-bar）、算力与额度指示器及任务中心流水线进度设计。</div>
  <div class="badge">深色 SaaS 风 · 玻璃拟态 · 品牌渐变 #6366F1 → #22D3EE</div>
  <div class="meta">原型来源：docs/ui-mockup（HTML 静态原型）<br>设计依据：docs/05-前端页面布局与全栈技术脚手架方案.md · docs/06-最终开发文档.md<br>生成时间：2026-07-19</div>
</div>

<div class="page">
  <h2 class="pt">核心流程总览 <span class="grad">从链接到发布 · 6 步</span></h2>
  <div class="psub">全局动线导航（flow-bar）在所有页面顶部常驻，实时指示「我在流程哪一步」；侧栏底部常驻云端算力与额度指示器。</div>
  <table class="flow">
    <tr><th>步骤</th><th>环节</th><th>承载模块</th><th>原型文件</th><th>说明</th></tr>
    ${flowRows.map(r => `<tr><td class="no">${r[0]}</td><td class="st">${r[1]}</td><td>${r[2]}</td><td><code>${r[3]}</code></td><td>${r[4]}</td></tr>`).join('\n')}
  </table>
  <div class="note"><b style="color:#E5E7EB">一键成片 7 步流水线：</b>链接/选题 → 文案 → 声音 → 数字人 → 合成 → 剪辑 → 发布。
    提交链接后全自动执行（预计 ≤5 分钟出片，消耗约 120 点额度），步骤条用于预期管理，每步仍可中途干预；
    执行过程在任务中心以迷你流水线（mini-pipe）实时可视化。下文「02 一键成片」章节包含 7 个步骤的逐一状态截图。</div>
</div>

${moduleSections}

</body></html>`;

  fs.writeFileSync(path.join(OUT, 'report.html'), report, 'utf8');

  await page.goto('file://' + path.join(OUT, 'report.html'), { waitUntil: 'networkidle' });
  await page.waitForTimeout(400);
  await page.pdf({
    path: PDF_PATH,
    format: 'A4',
    landscape: true,
    printBackground: true,
    margin: { top: 0, right: 0, bottom: 0, left: 0 },
  });
  await browser.close();
  console.log('\nPDF 已生成:', PDF_PATH);
}

main().catch((e) => { console.error(e); process.exit(1); });

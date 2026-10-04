/**
 * SM 文件审查 —— Node 侧主入口（与 com.ppos.sm.Main 同一套规则与输出形状）。
 *
 * 用法:
 *   node js/review-all.mjs                    # 默认审查 fixture/
 *   node js/review-all.mjs <文件或目录路径>
 *   node js/review-all.mjs --json [--strict] [路径]
 *
 * 退出码（可接 CI）：ERROR>0 → 1；--strict 时 WARN>0 也 → 1；目标不存在 → 2。
 * 报告永远落 out/review-<时间戳>.{json,md}（out/ 不入库）。
 */
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { review } from './review-core.mjs';

const args = process.argv.slice(2);
const json = args.includes('--json');
const strict = args.includes('--strict');
const target = args.find((a) => !a.startsWith('--')) || 'fixture';

if (!existsSync(target)) {
  console.error(`目标不存在: ${target}`);
  process.exit(2);
}

const res = review(target);

mkdirSync('out', { recursive: true });
const jsonText = buildJson(target, res);
writeFileSync(`out/review-${stamp()}.json`, jsonText, 'utf8');
writeFileSync(`out/review-${stamp()}.md`, buildMarkdown(target, res), 'utf8');

if (json) {
  console.log(jsonText);
} else {
  printConsole(target, res, strict);
}

const err = res.findings.filter((f) => f.severity === 'ERROR').length;
const warn = res.findings.filter((f) => f.severity === 'WARN').length;
process.exit(err > 0 || (strict && warn > 0) ? 1 : 0);

// ── 输出（与 ReportWriter.java 同形）───────────────────────────────

function stamp() {
  const p = (x) => String(x).padStart(2, '0');
  const d = new Date();
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}

function generatedAt() {
  const p = (x) => String(x).padStart(2, '0');
  const d = new Date();
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function icon(sev) {
  return sev === 'ERROR' ? '❌' : sev === 'WARN' ? '⚠' : 'ℹ';
}

function printConsole(target2, res2, strict2) {
  const count = (sev) => res2.findings.filter((f) => f.severity === sev).length;
  const err = count('ERROR');
  const warn = count('WARN');
  const info = count('INFO');
  const SEP = '='.repeat(62);
  const SUB = '-'.repeat(62);
  console.log(SEP);
  console.log(` SM 文件审查 — ${target2}`);
  console.log(SEP);
  console.log(`  ❌ ERROR  ${err}`);
  console.log(`  ⚠  WARN  ${warn}`);
  console.log(`  ℹ  INFO  ${info}`);
  console.log(SUB);
  const cap = Math.min(res2.findings.length, 40);
  for (const f of res2.findings.slice(0, cap)) {
    console.log(`  ${icon(f.severity)} ${f.file}:${f.line}:${f.col}  ${f.rule}  ${f.message}`);
  }
  if (res2.findings.length > cap) {
    console.log(`  …其余 ${res2.findings.length - cap} 项见 out/ 报告文件`);
  }
  console.log(SUB);
  console.log(` 扫描: js ${res2.jsFiles} / java ${res2.javaFiles}（另检 XML ${res2.pomFiles} 个，非 UTF-8 跳过 ${res2.invalidUtf8}）`);
  const fail = err > 0 || (strict2 && warn > 0);
  let verdict;
  if (res2.findings.length === 0) verdict = '未发现问题 ✅';
  else if (fail) verdict = '存在失败级问题 ❌（退出码 1）';
  else if (warn > 0) verdict = '无 ERROR，仅警告/提示 ⚠（退出码 0）';
  else verdict = '仅 INFO 提示 ℹ（退出码 0）';
  console.log(` 结论: ${verdict}`);
  console.log(SEP);
}

function buildJson(target2, res2) {
  const count = (sev) => res2.findings.filter((f) => f.severity === sev).length;
  const findings = res2.findings.map((f) => ({
    file: f.file, line: f.line, col: f.col, rule: f.rule,
    severity: f.severity, message: f.message, excerpt: f.excerpt,
  }));
  return JSON.stringify({
    tool: 'sm-file-review',
    version: '1.0',
    target: target2,
    generatedAt: generatedAt(),
    files: {
      scanned: res2.jsFiles + res2.javaFiles,
      js: res2.jsFiles,
      java: res2.javaFiles,
      pom: res2.pomFiles,
      pomAtRoot: res2.pomAtRoot,
      invalidUtf8: res2.invalidUtf8,
    },
    summary: { ERROR: count('ERROR'), WARN: count('WARN'), INFO: count('INFO') },
    findings,
  }, null, 2);
}

function buildMarkdown(target2, res2) {
  const count = (sev) => res2.findings.filter((f) => f.severity === sev).length;
  const cell = (s) => s.replace(/\|/g, '\\|');
  const lines = [
    '# SM 文件审查报告',
    '',
    `- 目标: ${target2}`,
    `- 时间: ${generatedAt()}`,
    `- 扫描: js ${res2.jsFiles} / java ${res2.javaFiles}（另检 XML ${res2.pomFiles} 个，非 UTF-8 跳过 ${res2.invalidUtf8}）`,
    `- 结论: ERROR ${count('ERROR')} / WARN ${count('WARN')} / INFO ${count('INFO')}`,
    '',
    '| # | 级别 | 文件 | 行:列 | 规则 | 说明 | 摘录 |',
    '|---|---|---|---|---|---|---|',
  ];
  if (res2.findings.length === 0) {
    lines.push('| - | - | - | - | - | 未发现问题 | - |');
  }
  res2.findings.forEach((f, i) => {
    lines.push(`| ${i + 1} | ${f.severity} | \`${f.file}\` | ${f.line}:${f.col} | ${f.rule} | ${cell(f.message)} | \`${cell(f.excerpt)}\` |`);
  });
  return lines.join('\n') + '\n';
}

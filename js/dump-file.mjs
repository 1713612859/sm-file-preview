/**
 * 单文件速查：按行打印一个文件的全部命中（不写 out/ 报告）。
 *
 * 用法:
 *   node js/dump-file.mjs <文件路径>
 *
 * 仅 Node 侧便利脚本（类似 ej-render-test 的 dump-receipt），不参与 parity 对账。
 */
import { existsSync } from 'node:fs';
import { reviewFile } from './review-core.mjs';

const target = process.argv[2];
if (!target || !existsSync(target)) {
  console.error('用法: node js/dump-file.mjs <文件路径>');
  process.exit(2);
}

const res = reviewFile(target);
const icon = (sev) => (sev === 'ERROR' ? '❌' : sev === 'WARN' ? '⚠' : 'ℹ');

console.log(` SM 文件审查(单文件) — ${target}`);
if (res.findings.length === 0) {
  console.log(' ✅ 未发现问题');
} else {
  for (const f of res.findings) {
    console.log(`  ${icon(f.severity)} ${f.line}:${f.col}  ${f.rule}  ${f.message}`);
    if (f.excerpt) console.log(`      ${f.excerpt}`);
  }
  console.log(` 共 ${res.findings.length} 项`);
}

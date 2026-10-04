/**
 * 双实现交叉验证：Node 与 Java 对 fixture/ 各跑一遍 --json，逐项对账 + 基准 PIN 比对。
 *
 * 用法:
 *   node js/verify-parity.mjs
 *
 * 判定：
 *   1) 双侧 JSON（剔除 generatedAt 后的 files/summary/findings/target）必须完全一致；
 *   2) Node 侧命中数必须等于 PIN 基准（防「两侧同步地错」——夹具埋雷是固定已知的）。
 * 退出码 0 = 通过；1 = 口径漂移或基准未更新；2 = 环境问题（如 Java 侧没跑起来）。
 *
 * 注意：
 *   - mvn 退出码 1 属预期（fixture 故意埋了 ERROR 级问题），以 stdout JSON 为准；
 *   - JDK17 通过 SM_JAVA_HOME 或下方默认值指定（系统默认 Java 8 编译不了 17）。
 */
import { spawnSync } from 'node:child_process';

const JAVA17 = process.env.SM_JAVA_HOME || 'C:\\Users\\Administrator\\.jdks\\ms-17.0.20';

// PIN：fixture 基准命中数。规则或夹具变更后须实测回填（AGENTS 规则 3——基准更新是
// 显式动作，更新时同步改 fixture/README.md 的预期表）。
const PIN = { ERROR: 6, WARN: 11, INFO: 5, findings: 22 };

function extractJson(text) {
  const start = text.indexOf('{');
  const end = text.lastIndexOf('}');
  if (start < 0 || end <= start) return null;
  try {
    return JSON.parse(text.slice(start, end + 1));
  } catch (e) {
    return null;
  }
}

function runNode() {
  const r = spawnSync(process.execPath, ['js/review-all.mjs', 'fixture', '--json'], { encoding: 'utf8' });
  if (r.status !== 1) {
    // fixture 埋了 ERROR，退出码 1 是预期；0/2/null 都说明脚本本身出了问题
    if (r.status !== 0) { /* 0 也接受：万一未来夹具去雷 */ }
  }
  if (r.status === null || r.status === 2) {
    console.error('Node 侧异常退出:\n' + r.stdout + r.stderr);
    process.exit(2);
  }
  const j = extractJson(r.stdout);
  if (!j) {
    console.error('Node 侧未产出 JSON:\n' + r.stdout + r.stderr);
    process.exit(2);
  }
  return j;
}

function runJava() {
  // exec.args 按空白拆分，参数本身不能含空格（AGENTS「Windows 已知坑」）
  const r = spawnSync('mvn -q compile exec:java "-Dexec.args=fixture --json"', {
    shell: true,
    encoding: 'utf8',
    env: { ...process.env, JAVA_HOME: JAVA17 },
  });
  const j = extractJson(r.stdout);
  if (!j) {
    console.error('Java 侧未产出 JSON（检查 JAVA_HOME/Maven），原始输出:\n' + r.stdout + '\n' + r.stderr);
    process.exit(2);
  }
  return j;
}

function diffs(a, b, path, out) {
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) out.push(`${path}: 数组长度 ${a.length} ≠ ${b.length}`);
    for (let i = 0; i < Math.min(a.length, b.length); i++) diffs(a[i], b[i], `${path}[${i}]`, out);
    return;
  }
  if (a && b && typeof a === 'object' && typeof b === 'object') {
    for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) {
      if (!(k in a)) out.push(`${path}.${k}: 仅 Java 侧有 = ${JSON.stringify(b[k])}`);
      else if (!(k in b)) out.push(`${path}.${k}: 仅 Node 侧有 = ${JSON.stringify(a[k])}`);
      else diffs(a[k], b[k], `${path}.${k}`, out);
    }
    return;
  }
  if (a !== b) out.push(`${path}: Node=${JSON.stringify(a)} Java=${JSON.stringify(b)}`);
}

const nodeRes = runNode();
const javaRes = runJava();

delete nodeRes.generatedAt;
delete javaRes.generatedAt;

const out = [];
diffs(nodeRes, javaRes, '$', out);

const SEP = '='.repeat(62);
console.log(SEP);
console.log(' 双实现交叉验证 — fixture（Node vs Java）');
console.log(SEP);

let fail = false;
if (out.length === 0) {
  console.log(' ✅ 双实现输出一致（剔除 generatedAt 后逐项对账通过）');
} else {
  fail = true;
  console.log(` ❌ 双实现存在 ${out.length} 处差异（口径漂移，先改 JS/Java 任意一侧再同步另一侧）:`);
  for (const d of out.slice(0, 20)) console.log('   - ' + d);
  if (out.length > 20) console.log(`   …另有 ${out.length - 20} 处`);
}

const s = nodeRes.summary;
const n = nodeRes.findings.length;
const pinOk = s.ERROR === PIN.ERROR && s.WARN === PIN.WARN && s.INFO === PIN.INFO && n === PIN.findings;
if (pinOk) {
  console.log(` ✅ 基准 PIN 一致（${n} 项 = ERROR ${s.ERROR} / WARN ${s.WARN} / INFO ${s.INFO}）`);
} else {
  fail = true;
  console.log(` ❌ 基准 PIN 不符: 实测 ${n} 项 = ERROR ${s.ERROR} / WARN ${s.WARN} / INFO ${s.INFO}` +
    `，PIN 为 ${PIN.findings} = ERROR ${PIN.ERROR} / WARN ${PIN.WARN} / INFO ${PIN.INFO}`);
  console.log('    若属规则/夹具有意变更：核对 fixture/README.md 预期表后更新本文件 PIN（显式动作，勿顺手改）。');
}
console.log(SEP);
console.log(fail ? ' 结论: 未通过 ❌' : ' 结论: 全部通过 ✅');
process.exit(fail ? 1 : 0);

// 故意埋雷的 JS 样本（供 parity 回归），不会被业务执行。预期命中清单见 fixture/README.md。
const API_TOKEN = 'sk-live-9f3a2b7c8d1e';
const PASSWORD = 'admin12345678';

// TODO: 上线前清理调试逻辑
function debugDump(user) {
  debugger;
  console.log('user =', user);
  return eval('user.age + 1');
}

function looseEq(a, b) {
  return a == b;
}

function runLs(dir) {
  return execSync(`ls -la ${dir}`);
}

function fetchAvatar(id) {
  return httpGet('http://cdn.example.com/avatar/' + id);
}

const LONG_DESCRIPTION_LINE = '这一行故意写得非常长，用来验证 GEN-LONGLINE 行宽检查在双实现里的列号与截断口径完全一致，行宽按 UTF-16 单元计数、阈值 160，本行总长度已经远超阈值应当稳定命中 INFO 级提示，两侧实现的列号都必须是第 161 列，摘录裁剪首尾空白并截断到 120 个字符加省略号，这里继续补足无意义文字以确保超过阈值不会被边界情况干扰';

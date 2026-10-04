# AGENTS.md — 给 AI 助手的工作约定（sm-file-review）

> 项目是什么：面向 js 脚本与 Java 项目的静态文件审查工具，Node/Java 双实现交叉验证。
> 人类文档见 `README.md`；本文件是**行为约束**，做任何修改前先读完。

## 硬性规则

1. **规则/口径修改必须 JS/Java 双侧同步**：`js/rules.mjs`+`js/review-core.mjs` 与
   `Rules.java`+`ReviewEngine.java` 是同一套口径的两种实现，改一边必改另一边，
   否则交叉验证失去意义。改完必跑 `node js/verify-parity.mjs`，不绿不算完成。
2. **口径以真实代码拟合，禁止凭直觉改正则**。任何口径变更必须在代码注释里写明
   实测依据（日期 / 样本文件 / 行号），首版各规则的列号/豁免面都是实测冻结的。
3. **PIN 基准更新是显式动作**：夹具埋雷清单（`fixture/README.md` 预期表）与
   `verify-parity.mjs` 顶部 PIN 必须成对更新；禁止为了让 parity 变绿而单改 PIN。
4. **`out/` 不入库**：审查报告可能含真实项目内容。样本用 `fixture/`（脱敏）。
5. **样本文件头部禁止写「预期命中」注释**——注释里出现 GEN-**TODO**/FIXME 字样会被
   GEN-TODO 自己命中（连字符算词边界），预期只记 `fixture/README.md` 表格。
6. 提交信息用中文，一行主题 + 空行 + 正文。

## 环境

- **JDK 17**：`JAVA_HOME=C:\Users\Administrator\.jdks\ms-17.0.20`（系统默认 8，
  编译不了 17）。`verify-parity.mjs` 已内置该默认值，可用 `SM_JAVA_HOME` 覆盖。
- Maven 默认入口 `com.ppos.sm.Main`（pom 属性形态，`-Dexec.args` 传参）。
- Node 18+（lookbehind 正则 / TextDecoder）；shell 是 Git Bash（Windows）。

## Windows / Git Bash 已知坑

- `-Dexec.args="路径 含空格"` 会被截断 → 先拷到无空格路径再传。
- Java 侧 stdout 已强制 UTF-8；GBK 控制台直接看中文花屏属显示问题，管道采集正常。
- 内联 `node -e "..."` 里的正则反斜杠会被 shell 吃掉 → 写临时 `.mjs` 文件跑。
- JS 正则 `g` 标志复用陷阱：规则表不挂 `g`；多模式分支必须用不带 `g` 的源正则
  `.match()`（带 `g` 返回字符串数组无 `.index`，首版 JS-EXEC-DYN 列号 NaN 真实翻过车）。
- 夹具 `fixture/java/com/example/BadEncoding.java` 是 latin-1 字节文件，
  **不要用会重写编码的编辑器/命令碰它**，否则 PROJ-ENCODING 基准失效。

## 遇到 parity 红项的处置顺序

1. 先看差异是什么（verify-parity 会列出最多 20 处 field 级差异）——
   绝大多数是「一边改了口径另一边没跟」。
2. 判定哪边是对的（对照 fixture/README.md 预期表），同步另一边。
3. 若两侧一致但 PIN 不符：确认是有意变更 → 更新预期表 + PIN（规则 3）；
   不是有意变更 = 夹具被人改了，先查 git diff 再动。
4. 结论同步到用户时给出：根因 / 修复 / parity 回归结果 三段。

## 输出习惯

- 检查项标签中英混合（规则 ID 英文 + 中文说明），汇总用 ✅/❌/⚠/ℹ 标记。
- 新增规则同时补：双侧规则表、fixture 埋雷样本、预期表行、PIN 数值
  （四处一组，漏一处 parity 必红）。

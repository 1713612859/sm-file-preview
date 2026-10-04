# fixture/ — 脱敏基准样本

双实现交叉验证（`node js/verify-parity.mjs`）的对账底账。**埋雷清单是固定已知的**：
一方面约束 Node/Java 两侧逐项一致（防实现漂移），另一方面约束命中数与
`js/verify-parity.mjs` 顶部 PIN 一致（防「两侧同步地错」）。

> 样本文件头部不要写「预期命中」注释——注释里出现 GEN-**TODO**/FIXME 字样会被
> GEN-TODO 规则自己命中（连字符算词边界），预期只记在本表。

## 预期命中表（2026-10-04 实测冻结，共 22 项 = ERROR 6 / WARN 11 / INFO 5）

| 文件 | 预期命中（行号） |
|---|---|
| `js/sample-bad.js` | 10 项：GEN-SECRET×2（2,3）、GEN-TODO（5）、JS-DEBUGGER（7）、JS-CONSOLE（8）、JS-EVAL（9）、JS-LOOSEEQ（13）、JS-EXEC-DYN（17）、GEN-HTTP（21）、GEN-LONGLINE（24，列 161） |
| `js/sample-good.mjs` | 0 项（干净样本：`===`/`!==`、https、无 console/debugger/eval） |
| `js/edge-comments.js` | 2 项：GEN-TODO（7，FIXME）、GEN-HTTP（9，字符串里的 http://x.example.com）。**不命中**：块注释里的 console/eval（被抹掉）、localhost 与 w3.org URL（豁免） |
| `java/com/example/SampleBad.java` | 8 项：GEN-SECRET（8）、GEN-TODO（10）、JAVA-SYSOUT×2（12,23）、JAVA-EMPTY-CATCH（15）、JAVA-STACKTRACE（19）、JAVA-SQL-CONCAT（21）、GEN-HTTP（22） |
| `java/com/example/SampleGood.java` | 0 项（干净样本：logger + 参数化 SQL） |
| `java/com/example/BadEncoding.java` | 1 项：PROJ-ENCODING（文件含 latin-1 字节 0xE9，非 UTF-8 → 仅报编码，**跳过行级规则**——其 System.out.println 不应报） |
| `pom.xml` | 0 项（合法根 pom，兼作 pomAtRoot=true 标记） |
| `bad-pom/pom.xml` | 1 项：PROJ-XML（4:3 注释未闭合） |

## 增改样本的流程

1. 改样本或规则后跑 `node js/review-all.mjs fixture` 看实测；
2. 两侧实现都要跑（或直接 `node js/verify-parity.mjs`）；
3. 有意变更 → 更新本表 + `js/verify-parity.mjs` 顶部 PIN（显式动作，勿顺手改）。

# sm-file-review — SM 文件审查工具

> **本仓库当前有两条工具线：**
> 1. **SM SIA 认证验收线(2026-10 起主用)**:`sia_validator.py`(44 条规则验收闸门)、
>    `sia_generator.py`(EJ 版式参考生成器)、`sia_recompute.py`(逐笔重算对拍)、
>    `sia_common.py`(公共库)。先读 `00_包内导览_先看这里.md`。
> 2. js/Java 源码静态审查线(下文所述,Node/Java 双实现交叉验证)。

面向 **js 脚本**（.js/.mjs/.cjs/.ts/.jsx/.tsx）与 **Java 项目**（.java + pom.xml）的
静态文件审查工具链。规则表 **Node / Java 双实现交叉验证**（沿袭 ej-render-test 的
「同一套口径、两种实现、结论必须一致」范式）。

```
目标文件/目录 ──遍历分类──> js 行 / java 行 / pom.xml
        │                     │
        │          抹注释状态机 + 规则表（13 条行级 + 2 项项目级）
        │                     │
        │        review-all(Node) ═══对账═══ Main(Java)   ← verify-parity
        └───────────────────────> out/review-*.json / *.md + 控制台摘要（退出码可接 CI）
```

## 环境要求

| 组件 | 要求 | 说明 |
|---|---|---|
| JDK | 17+（本机在 `C:\Users\Administrator\.jdks\ms-17.0.20`） | 系统 JAVA_HOME 可能是 8，跑 Java 侧时需指定 |
| Maven | 任意较新版本 | `pom.xml` 零第三方依赖，默认入口 `com.ppos.sm.Main` |
| Node.js | 18+（用到 lookbehind 正则与 TextDecoder） | 跑 `js/` 下的审查与对账脚本 |

## 快速开始

```bash
# Node 侧（默认审查 fixture/）
node js/review-all.mjs [路径] [--strict] [--json]

# Java 侧（JDK17；系统默认 Java 8 会编译失败）
JAVA_HOME='C:\Users\Administrator\.jdks\ms-17.0.20' \
  mvn -q exec:java "-Dexec.args=fixture"          # 或 "<路径> --strict"

# 双实现交叉验证（改任何规则后必跑）
node js/verify-parity.mjs

# 单文件速查（只 Node，不落报告）
node js/dump-file.mjs <文件路径>
```

产物：`out/review-<yyyyMMdd-HHmmss>.json`（结构化，供对账/CI 消费）+ 同名 `.md`
（人读表格）。`out/` 不入库。

**退出码**：`ERROR>0 → 1`；`--strict` 时 `WARN>0` 也 → 1；目标不存在 → 2。

## 规则总览（口径与真实代码拟合，勿凭直觉改）

### 通用（js + java 行）

| 规则 | 级别 | 口径 |
|---|---|---|
| GEN-SECRET | ERROR | 凭据关键词（含 `_` 前缀形态，如 `DB_PASSWORD`）+ 引号字面量 ≥8 字符 |
| GEN-TODO | WARN | `TODO/FIXME/XXX/HACK` 词边界；**按原文行匹配**（标记本来就在注释里，字符串里的也会报，属已知误报面） |
| GEN-HTTP | WARN | 非 HTTPS 外链（`http://`，豁免 localhost/127.0.0.1/www.w3.org） |
| GEN-LONGLINE | INFO | 行宽 >160（UTF-16 单元），列号恒 161 |

### js 专属

| 规则 | 级别 | 口径 |
|---|---|---|
| JS-EVAL | ERROR | `eval(` / `new Function(` |
| JS-DEBUGGER | ERROR | `debugger` 语句 |
| JS-EXEC-DYN | WARN | `exec/execSync` 以字面量起头且含 `${}` 或 `"+` 拼接（命令注入启发式） |
| JS-CONSOLE | INFO | `console.log/debug/...` 调试输出 |
| JS-LOOSEEQ | INFO | 宽松相等 `==`/`!=`（lookbehind 排除 `===`/`!==`/`<=`） |

### java 专属

| 规则 | 级别 | 口径 |
|---|---|---|
| JAVA-SQL-CONCAT | WARN | SQL 关键词字面量后接 `+` 拼接（建议 PreparedStatement） |
| JAVA-STACKTRACE | WARN | `printStackTrace()` |
| JAVA-EMPTY-CATCH | WARN | 单行空 catch 块 |
| JAVA-SYSOUT | INFO | `System.out/err.print*` |

### 项目级（目录扫描时）

| 规则 | 级别 | 口径 |
|---|---|---|
| PROJ-XML | ERROR | 任意层级 `pom.xml` 的良构性（栈式标签配平；错误文案 JS/Java 逐字一致） |
| PROJ-ENCODING | WARN | 非 UTF-8 文件仅报此项并**跳过行级规则**（两侧跳过口径一致） |

### 匹配语义（JS/Java 双侧必须一致）

- **stripped 匹配**：先跑「抹注释状态机」抹掉注释内容（保持行长不变，列号不失真），
  字符串字面量内容保留（凭据/URL 要查的就是字符串）；块注释与 js 模板串跨行，
  单/双引号串不跨行。已知近似：Java text block 按 `"""` 三次引号翻转近似、CDATA 不识别。
- **raw 匹配**：仅 GEN-TODO——计划标记本来就在注释里。
- 目录遍历忽略 `node_modules/target/out/dist/build/.git/.idea/.zcode/.vscode/coverage/.settings`；
  单文件 >2MB 跳过；BOM(U+FEFF) 剥离后按 UTF-8 严格解码。
- 发现排序：file → line → col → rule；摘录裁首尾空白、截断 120 UTF-16 单元。

## 双实现与对账

`js/rules.mjs` ↔ `Rules.java`、`js/review-core.mjs` ↔ `ReviewEngine.java` 是同一套
口径的两种实现。`node js/verify-parity.mjs` 做两件事：

1. 双方对 `fixture/` 各跑 `--json`，剔除 `generatedAt` 后逐项 diff（files/summary/每条 finding）；
2. 命中数对 `verify-parity.mjs` 顶部 **PIN** 基准（22 项 = 6 错误 / 11 警告 / 5 提示），
   防「两侧同步地错」——埋雷清单见 `fixture/README.md`。

任何规则/口径变更：**JS/Java 双侧同步 → 跑 parity → 有意变更则显式更新 PIN 与预期表**。

## 目录结构

```
sm-file-review/
├── pom.xml                 # Maven(JDK17)，零依赖，默认入口 com.ppos.sm.Main
├── src/main/java/com/ppos/sm/
│   ├── Main.java           # CLI 入口（stdout 已强制 UTF-8）
│   ├── Rules.java          # 规则表（镜像 js/rules.mjs）
│   ├── ReviewEngine.java   # 遍历/分类/抹注释/匹配/XML/编码
│   ├── Finding.java        # 发现记录 + 排序
│   └── ReportWriter.java   # 控制台/JSON/Markdown 输出
├── js/
│   ├── rules.mjs           # 规则表（镜像 Rules.java）
│   ├── review-core.mjs     # 引擎（镜像 ReviewEngine.java）
│   ├── review-all.mjs      # Node 主入口
│   ├── dump-file.mjs       # 单文件速查（Node 便利脚本）
│   └── verify-parity.mjs   # 双实现对账 + PIN 基准
├── fixture/                # 脱敏基准样本（埋雷清单见其 README）
└── out/                    # 报告产物（不入库）
```

## 已知边界（用前必读）

- 正则行级启发式，**不是语法级分析**——跨行语句、上下文语义不在能力面内；
- 规则定义文件被自审时，正则字面量会命中自身规则（`node js/review-all.mjs .` 的
  自食狗粮现象，属预期噪声）；
- JS-EXEC-DYN/JAVA-SQL-CONCAT 是注入**启发式**（宁可轻报不拦真），报了不等于可利用；
- GEN-TODO 会命中字符串/文档里的 TODO 字样；GEN-SECRET 关键词列表有限
  （password/passwd/secret/api[_-]?key/access[_-]?key/token），`userPassword` 这类
  驼峰前缀形态**不报**（词边界所限，防误报优先）。

## 约定

- `out/` 不入库（审查对象可能是真实业务项目）；基准样本用 `fixture/`（脱敏）。
- 校验口径修改必须 **JS/Java 双侧同步**，并在注释里写明依据（实测日期/样本/行号）。
- 提交信息用中文，一行主题 + 空行 + 正文。

## Windows / Git Bash 已知坑

- `-Dexec.args="路径 含空格"` 会被截断 → 先拷到无空格路径；`verify-parity.mjs` 的
  exec.args 参数本身不含空格分词歧义。
- Java stdout 已强制 UTF-8：管道/文件采集正常；GBK 控制台直接看中文可能花屏，
  需要 `| iconv -f UTF-8 -t GBK` 转一下再看。
- 带正则的内联 `node -e "..."` 会被 shell 吃反斜杠 → 写临时 `.mjs` 文件跑。
- JS 正则对象带 `g` 标志被 `test/exec` 复用会残留 `lastIndex` 导致漏报——本仓规则表
  一律不挂 `g`，引擎用 `matchAll`（不改源 lastIndex）；多模式分支用不带 `g` 的
  源正则 `.match()`（带 `g` 时 match 返回字符串数组，没有 `.index`——首版真实翻过车）。

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SM SIA POS 认证提交物验证器(标准库实现,无第三方依赖)。

依据:00 需求文档 / 01 V1.5 规格 / 02 已认证样例(标准答案,金额恒等式在其上校准 0 ERROR);
MOV 口径定案(2026-10-04 EJ 复核)= 金样例口径。规则 44 条(F8/V12/A11/D8/E5),
共享常量与函数见 sia_common.py(改动需三条工具全量回归)。

用法:
  python sia_validator.py <目录> [--baseline sample|spec] [--mov-caliber app|golden]
                          [--tol 0.02] [--no-evidence] [--out-dir out] [--max-examples 5] [--rules]
输出:控制台摘要 + out/sia_review_<时间戳>.md/.json(每条问题含 文件/行/订单/列/期望/实际/出处)。
退出码:0=无 ERROR;1=存在 ERROR;2=用法错。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from sia_common import (
    ALNUM, DATE_RX, DT_RX, NUM2_RX, AMOUNT_KEYS, TX_HEADER, TX_NULLABLE,
    TX_NUMERIC_COLS, TX_TEXT_COLS, TX_STRICT_ALNUM,
    DET_HEADER_SAMPLE, DET_HEADER_SPEC, detect_det_slots,
    TENDER_COL, classify_tender, money, parse_csv_strict,
)

# --------------------------------------------------------------------------
# 规则元数据:ID -> (严重级别, 需求出处)
# --------------------------------------------------------------------------
META = {
    "F01": ("ERROR", "§4.2 文件命名 mm_yyyy_transactions.csv / mm_yyyy_transactiondetails.csv"),
    "F02": ("WARN",  "§4.3 UTF-8 编码(建议无 BOM,与已认证样例一致)"),
    "F03": ("ERROR", "§6/§7/§13 表头单行、列名与顺序固定(主表 63 列;明细按基线)"),
    "F04": ("ERROR", "§4.3 所有数据值用英文双引号包裹"),
    "F05": ("ERROR", "§4.3 一行=一条记录,列数与表头一致,无空行"),
    "F06": ("ERROR", "§4.3 日期 YYYY-MM-DD / 日期时间 YYYY-MM-DD HH:mm:ss(24h)"),
    "F07": ("WARN",  "§4.3 换行风格应统一(CRLF 或 LF,不混用)"),
    "F08": ("WARN",  "§4.3 文件期号与营业日一致;数据窗口 30 天滚动(超出仅 INFO 提示)"),
    "V01": ("ERROR", "§6 Order Num / Terminal Number / Serial Number 仅字母数字"),
    "V02": ("WARN",  "§6 ALPHANUMERIC=仅字母数字,禁止特殊符号;已认证样例支付代码为 CSH/CCMASTERCRD 等"),
    "V03": ("ERROR", "§6/§7 非可空字段不得为空(可空清单见需求文档)"),
    "V04": ("ERROR", "§6 NUMERIC=两位小数"),
    "V05": ("ERROR", "§6/§10 Guest Count 不能为 0"),
    "V06": ("ERROR", "§6 BOOLEAN 仅 0/1"),
    "V07": ("ERROR", "§8.9 Sales Type 取值 SM01–SM10"),
    "V08": ("WARN",  "§4.4 营业日归属:默认=Check Close 当天;仅次日凌晨(<06:00)结单才归前一日"),
    "V09": ("ERROR", "§3/§4.4 Check Open 不得晚于 Check Close"),
    "V10": ("ERROR", "§6 ALPHANUMERIC 字段长度上限 250"),
    "V11": ("ERROR", "§8.7 Payment Type 为空 ⇔ Payment Amount 为 0"),
    "V12": ("WARN",  "§6 Guest Count=总客数(含 Senior/PWD),应 ≥ Senior+PWD"),
    "A01": ("ERROR", "§8 金额恒等式:Gross = Net + TotalTax + ServiceCharge + TotalDiscount + LessTax(金样例 313 笔全平)"),
    "A02": ("ERROR", "§8.7 支付金额之和 = 应付 = Gross − TotalDiscount − LessTax"),
    "A03": ("ERROR", "§8.1 VAT=价内税:TotalTax ≈ (Net − TaxExempt)×12% + LocalTax(样例口径:地方税并入 TotalTax;MOV 场景豁免)"),
    "A04": ("ERROR", "§8.2 Senior/PWD 法定折扣必须先扣 VAT:LessTax>0,且对应客数列 ≥1"),
    "A05": ("WARN",  "§8.2/金样例S7(=app 实测口径,EJ 复核 2026-10-04) MOV:折扣=去税净额×20%,VAT=折前净额×12%照收,应付=Gross−折扣"),
    "A05E": ("ERROR", "[已废弃口径,仅 --mov-caliber app 时启用] 早期从引擎代码推断的 MOV 口径;真实 app(EJ实测)与金样例同口径,勿用"),
    "A06": ("ERROR", "§6 第20列 Total Discount = 各折扣分列之和(Regular/Other 多促销按 :: 求和)"),
    "A07": ("ERROR", "§6 第51–61列 支付汇总与 Payment Type 归类一致(借记≠信用卡,卡组织拆分)"),
    "A07N": ("WARN", "§6 第51–61列 负冲抵单(作废/退款)的汇总列:已认证样例允许不严格(现金归0、Other放整单额),建议严格按归类填负数"),
    "A08": ("ERROR", "§8.5/§8.6 作废/退款符号约定:整单作废金额负号冲抵;新单号退款 Refund Amount 为负"),
    "A09": ("WARN",  "§8.6/§10 退款应能对应此前某笔同额正销售(三方对账)"),
    "D01": ("ERROR", "§5/§10 主表每个 Order Num 在明细表都有商品行,反之亦然"),
    "D02": ("ERROR", "§5/§7.1/§10 明细成交价合计 Σ(qty×TransactionItemPrice) = |Gross| − LocalTax − LessTax − TotalDiscount"),
    "D03": ("ERROR", "§7 成交价 ≤ 原价(Menu Item Price)"),
    "D04": ("ERROR", "§7.1 明细 Discount Amount = 原价 − 成交价(口径B,含免税部分;00文档§12已确认)"),
    "D05": ("WARN",  "§8.5/§8.6/场景对照 作废/退款明细:数量=-1、标记=1、金额>0;金额口径=整单(样例基线)"),
    "D06": ("ERROR", "§8.5/§8.6 明细标记作废/退款的行,主表对应交易必须 Void/Refund=1"),
    "D07": ("ERROR", "§7 Item Quantity 为数值(作废/退款行=-1)"),
    "D08": ("WARN",  "§5 SKU 披露档位:Item ID/Item Name 为空时确认属 b/c 档(字段留空是有意行为)"),
    "E01": ("WARN",  "§3 交付物:每笔交易应有对应 OR 收据(ORs/ 目录,命名含订单号)"),
    "E02": ("WARN",  "§3 交付物:每个营业日应有 Z-Read 日结(ZReads/ 目录,命名含日期)"),
    "E03": ("INFO",  "证据件 txt/xps 应成对(便于机器与人双读)"),
    "E04": ("ERROR", "§10 三方对账:OR 内容 Amount Due/Gross/VAT/VATable 应与 CSV 一致"),
    "E05": ("ERROR", "§10 三方对账:Z-Read GROSS/VAT/NET AMOUNT 应与该营业日 CSV 合计一致"),
}


class Findings:
    def __init__(self):
        self.items = []

    def add(self, rule, file, line=0, order="", column="", expected="", actual="", detail=""):
        sev, ref = META[rule]
        self.items.append({
            "rule": rule, "severity": sev, "ref": ref, "file": str(file), "line": line,
            "order": str(order), "column": column,
            "expected": str(expected), "actual": str(actual), "detail": detail,
        })


# --------------------------------------------------------------------------
# 日期语义校验:格式正则 + 日历存在性双验
# --------------------------------------------------------------------------
def valid_date(s: str) -> bool:
    """格式与日历均合法才返回 True。实测依据(2026-10-11 评审复现,Python 3.13):
    2026-02-30 / 2026-13-01 能过 DATE_RX,但 date.fromisoformat 抛 ValueError——
    只查格式会让 F06 漏报、V08 的 fromisoformat 未捕获直接崩溃。"""
    if not DATE_RX.match(s):
        return False
    try:
        date.fromisoformat(s)
        return True
    except ValueError:
        return False


def valid_dt(s: str) -> bool:
    """同 valid_date,面向日期时间列(Check Open/Close):
    2026-01-01 25:00:00 之类格式合法但日历/时钟非法的值同样要拦。"""
    if not DT_RX.match(s):
        return False
    try:
        datetime.fromisoformat(s)
        return True
    except ValueError:
        return False


# --------------------------------------------------------------------------
# 证据件校验(ORs/ 与 ZReads/)
# --------------------------------------------------------------------------
def check_evidence(root: Path, tx_by_order: dict, ix: dict, findings: Findings, tol: float):
    or_dir, zr_dir = root / "ORs", root / "ZReads"

    if or_dir.is_dir():
        files = sorted(or_dir.iterdir())
        # 命名口径(2026-10-22 复核定版):主路径 {orderId}_{T终端标}_OR_{smSeq}
        # ——三态(Sale/Voided/Refund)统一 OR 段,#0=smSeq 裸值直显(形如
        # 56251_T1_OR_2),OR 段数字与 CSV #0 同源,本正则直接命中;
        # 存量回退 {orderId}_{T}_{Si|Voided|Refund}_{裸16位}(smSeq 缺失老行,
        # VOID/REFUND 回退标签也认,防 E01 误报缺失);金样例仍为 *_OR_单号。
        # (2026-10-11 定案 OR/Si 双标识口径保留,Voided/Refund 为 2026-10-22 增补)
        covered = {str(int(m.group(1))) for m in
                   (re.search(r"(?:\b|[_-])(?:OR|SI|VOIDED|REFUND)[_-]?(\d+)", f.name, re.I)
                    for f in files) if m}
        for o in tx_by_order:
            if o not in covered and o.lstrip("0") not in covered:
                # 命名口径同上方 covered 正则:OR/Si 双标识 + 回退三态标签
                findings.add("E01", "ORs/", order=o,
                             expected=f"存在 *_OR_{o}.*(主路径 {{orderId}}_T{{n}}_OR_{{smSeq}})或回退 *_Si_{o}.* 收据",
                             actual="未找到(命名不规则或缺失)")
        _check_or_content(files, tx_by_order, findings, tol)
        txt_stems = {f.stem for f in files if f.suffix.lower() == ".txt"}
        xps_stems = {f.stem for f in files if f.suffix.lower() == ".xps"}
        if txt_stems and xps_stems and (txt_stems - xps_stems):
            findings.add("E03", "ORs/", detail=f"txt 无对应 xps: {sorted(txt_stems - xps_stems)[:5]}")
    else:
        findings.add("E01", str(root), detail="无 ORs/ 目录")

    if zr_dir.is_dir():
        days = {}
        for f in sorted(zr_dir.iterdir()):
            m = re.search(r"(\d{4}-\d{2}-\d{2})", f.name)
            if m:
                days.setdefault(m.group(1), []).append(f)
        # 表头缺列时跳过按日聚合(缺列已由 F03 报 ERROR,此处不应崩溃)
        if "Business Day" in ix:
            for o, (_ln, r, _ix, _v, _p) in tx_by_order.items():
                bd = r[ix["Business Day"]]
                if bd not in days:
                    findings.add("E02", "ZReads/", order=o, expected=f"存在 {bd} 的 Z-Reading", actual="缺失")
        if all(c in ix for c in ("Business Day", "Void", "Refund")):
            _check_zread_content(days, tx_by_order, ix, findings, tol)
    else:
        findings.add("E02", str(root), detail="无 ZReads/ 目录")


def _check_or_content(files, tx_by_order, findings, tol):
    # 订单号可能带前导零(APOS-SM 为 16 位),按去零归一键匹配,否则内容校验静默跳过;
    # 金样例短单号("1"/"2"...)不受影响。命名同 E01:OR/Si 双标识 + 回退三态标签
    # (2026-10-22:主路径 {orderId}_T{n}_OR_{smSeq} 三态统一,OR 段与 #0 同源裸值)。
    tx_by_int = {k.lstrip("0"): v for k, v in tx_by_order.items()}
    for f in files:
        if f.suffix.lower() != ".txt":
            continue
        m = re.search(r"(?:\b|[_-])(?:OR|SI|VOIDED|REFUND)[_-]?(\d+)", f.name, re.I)
        key = str(int(m.group(1))) if m else None
        t = tx_by_int.get(key) if key else None
        if not t:
            continue
        _ln, _r, _ix, vals, psum = t
        txt = f.read_text(encoding="utf-8", errors="replace")

        def num(pat):
            mm = re.search(pat, txt)
            return float(mm.group(1).replace(",", "")) if mm else None

        v = num(r"Amount Due\s+([\d,]+\.\d{2})")
        if v is not None and abs(v - abs(psum)) > tol:
            findings.add("E04", f"ORs/{f.name}", order=m.group(1), column="Amount Due",
                         expected=f"={abs(psum):.2f}(CSV 支付合计)", actual=f"{v:.2f}")
        v = num(r"VAT Amount \(12%\)\s+([\d,]+\.\d{2})")
        if v is not None and abs(v - abs(vals["Total Tax"])) > tol:
            findings.add("E04", f"ORs/{f.name}", order=m.group(1), column="VAT Amount",
                         expected=f"={abs(vals['Total Tax']):.2f}(CSV Total Tax)", actual=f"{v:.2f}")
        v = num(r"VATable Sales\s+([\d,]+\.\d{2})")
        if v is not None and vals["Tax Exempt Sales"] == 0:
            # 2026-10-22 MOV 形态补充(APOS 同源票面实证 12 单,smSeq 直显命名
            # 使 E04 首次真正匹配到 CSV 单——旧组合号命名一直静默跳过;对照
            # 产物票面同值,非票面变更):MOV 单票面 VATable=折扣前净额
            # =Net+MOV折扣额(纯 MOV 单=Gross−TotalTax;混合 LESS 单如 257:
            # 651.78=530.35+121.43≠Gross−Tax 682.21,故以 Net+MOV 为准)。
            # 非 MOV 单维持官方样例口径 VATable=Net。
            mov_col = _ix.get("National Coach / Athlete /  Medal of Valor Discount amount")
            mov_amt = money(_r[mov_col]) if mov_col is not None else None
            want = abs(vals["Net Sales Amount"]) + abs(mov_amt) if (mov_amt or 0) > 0 \
                else abs(vals["Net Sales Amount"])
            if abs(v - want) > tol:
                findings.add("E04", f"ORs/{f.name}", order=m.group(1), column="VATable Sales",
                             expected=f"={want:.2f}({'MOV VAT基数' if (mov_amt or 0) > 0 else 'CSV Net Sales'})",
                             actual=f"{v:.2f}",
                             detail="OR 打印的 VATable 与期望不一致(MOV 单按 VAT 基数=Gross−Tax,其余=Net;疑似模板把 Net−VAT 当 VATable)")


def _check_zread_content(days, tx_by_order, ix, findings, tol):
    # 四种对账口径:支付合计(含冲抵负单)、全单 Gross 合计(含负)、
    # 正常单 Gross 合计(EJ ZRead 语义:冲抵走 LESS 行,不进 GROSS/BREAKDOWN)、正常单 Tax
    # 2026-10-22 终端维度:Z-Reading 是每台终端一张(文件名 _T<终端号>_),对账须
    # 只取该终端的 T 行——同日双终端首次出现(T2+T555 同在 10-22,T555 票 16,089.47
    # 与自身分组全等却被拿去对全日 22,289.47 误报 E05×2 实证)。
    # 终端来源优先 Terminal Number 列(2026-10-22 复核定版:#0=smSeq 裸值直显,
    # 单号不含终端段,终端只能取 #61 列——实测 T2/T555 双终端);组合号形态
    # SALE/VOID/REFUND+终端号+16 位单号(存量回退)走单号正则;均无法解析的行
    # (金样例裸序号)回落全日。
    ORDER_TERM_RX = re.compile(r"^(?:SALE|VOID|REFUND)(\d+?)\d{16}$")
    day_paysum, day_tax, day_gross = defaultdict(float), defaultdict(float), defaultdict(float)
    day_normal_gross, day_normal_tax = defaultdict(float), defaultdict(float)
    _t61 = ix.get("Terminal Number")
    for _o, (_ln, r, _ix, vals, psum) in tx_by_order.items():
        bd = r[ix["Business Day"]]
        term61 = None
        if _t61 is not None:
            try:
                term61 = str(int(r[_t61]))
            except (TypeError, ValueError):
                term61 = None
        m = ORDER_TERM_RX.match(_o or "")
        term_m = (m.group(1).lstrip("0") or "0") if m else None
        term = term61 or term_m
        key = (bd, term) if term else (bd, "*")
        day_paysum[key] += psum
        day_tax[key] += vals["Total Tax"]
        day_gross[key] += vals["Gross Sales Amount"]
        if r[_ix["Void"]] != "1" and r[_ix["Refund"]] != "1":
            day_normal_gross[key] += vals["Gross Sales Amount"]
            day_normal_tax[key] += vals["Total Tax"]

    def aggr(bd, term):
        """终端命中则取该终端分组,否则(裸序号/无该终端行)回落全日合计"""
        keys = [(bd, term)] if day_paysum.get((bd, term)) is not None or term == "*" else []
        keys.append((bd, "*"))
        return keys[0]

    for bd, fs in days.items():
        txts = [f for f in fs if f.suffix.lower() == ".txt"]
        if not txts:
            continue
        fm = re.search(r"_Z-Reading_T(\d+)_", txts[0].name)
        # 终端号 int 归一(与 #61 列/组合号剥出的键同口径,防 "02"/"2" 形态分歧)
        key = aggr(bd, str(int(fm.group(1)))) if fm else (bd, "*")
        txt = txts[0].read_text(encoding="utf-8", errors="replace")

        def znum(pat):
            mm = re.search(pat, txt)
            return float(mm.group(1).replace(",", "")) if mm else None

        gv = znum(r"GROSS AMOUNT:\s+([\d,]+\.\d{2})")
        vv = znum(r"VAT AMOUNT:\s+([\d,]+\.\d{2})")
        g_ok = [round(x, 2) for x in (day_paysum.get(key, 0), day_gross.get(key, 0),
                                      day_normal_gross.get(key, 0))]
        if gv is not None and not any(abs(gv - x) <= tol for x in g_ok):
            findings.add("E05", f"ZReads/{txts[0].name}", column="GROSS AMOUNT",
                         expected=f"∈ {g_ok[0]:.2f}(支付合计)/{g_ok[1]:.2f}(Gross)/{g_ok[2]:.2f}(正常单Gross)",
                         actual=f"{gv:.2f}", detail=f"按终端分组 key={key}(文件名 T{fm.group(1) if fm else '?'})"
                         if fm else "")
        v_ok = [round(x, 2) for x in (day_tax.get(key, 0), day_normal_tax.get(key, 0))]
        if vv is not None and not any(abs(vv - x) <= tol for x in v_ok):
            findings.add("E05", f"ZReads/{txts[0].name}", column="VAT AMOUNT",
                         expected=f"∈ {v_ok[0]:.2f}(全单Tax)/{v_ok[1]:.2f}(正常单Tax)",
                         actual=f"{vv:.2f}", detail=f"按终端分组 key={key}(文件名 T{fm.group(1) if fm else '?'})"
                         if fm else "")


# --------------------------------------------------------------------------
# 报告输出
# --------------------------------------------------------------------------
def write_reports(root, args, findings: Findings, n_err, n_warn, n_info) -> Path:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / f"sia_review_{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    base.with_suffix(".json").write_text(json.dumps({
        "target": str(root), "baseline": args.baseline, "movCaliber": args.mov_caliber,
        "tol": args.tol, "summary": {"error": n_err, "warn": n_warn, "info": n_info},
        "findings": findings.items}, ensure_ascii=False, indent=1), encoding="utf-8")

    md = ["# SM SIA 提交物验证报告", "",
          f"- 目标: `{root}`",
          f"- 明细基线: {args.baseline}(sample=已认证样例 18 列 / spec=V1.5 规格 19 列);MOV 口径: {args.mov_caliber}",
          f"- 金额容差: {args.tol}",
          f"- 结论: **{'不通过' if n_err else '通过'}**(ERROR={n_err}, WARN={n_warn}, INFO={n_info})", ""]
    by_rule = defaultdict(list)
    for f in findings.items:
        by_rule[f["rule"]].append(f)
    for sev in ("ERROR", "WARN", "INFO"):
        if not any(i["severity"] == sev for i in findings.items):
            continue
        md.append(f"## {sev}")
        md.append("")
        for rule, items in sorted(by_rule.items()):
            if items[0]["severity"] != sev:
                continue
            md.append(f"### {rule} × {len(items)} — {META[rule][1]}")
            for it in items[:30]:
                loc = [f"`{it['file']}`"]
                if it["line"]:
                    loc.append(f"L{it['line']}")
                if it["order"]:
                    loc.append(f"订单 {it['order']}")
                if it["column"]:
                    loc.append(f"列[{it['column']}]")
                md.append(f"- **{' · '.join(loc)}**")
                if it["expected"] or it["actual"]:
                    md.append(f"  - 期望: {it['expected']}  | 实际: {it['actual']}")
                if it["detail"]:
                    md.append(f"  - {it['detail']}")
            if len(items) > 30:
                md.append(f"- ...(其余 {len(items) - 30} 条同规则,见 JSON)")
            md.append("")
    base.with_suffix(".md").write_text("\n".join(md), encoding="utf-8")
    return base


def severity_counts(findings: Findings) -> dict:
    """一次遍历统计各级别数量(避免对 findings 反复全扫)。"""
    counts = {"ERROR": 0, "WARN": 0, "INFO": 0}
    for i in findings.items:
        counts[i["severity"]] += 1
    return counts


def print_console(root, args, findings: Findings):
    by_rule = defaultdict(list)
    for f in findings.items:
        by_rule[f["rule"]].append(f)
    print(f"目标: {root}  基线: {args.baseline}  MOV口径: {args.mov_caliber}")
    n = severity_counts(findings)
    print(f"结论: {'❌ 不通过' if n['ERROR'] else '✅ 无 ERROR'}  "
          f"ERROR={n['ERROR']}  WARN={n['WARN']}  INFO={n['INFO']}")
    for rule in sorted(by_rule):
        items = by_rule[rule]
        ex = items[0]
        loc = f"{ex['file']}" + (f" L{ex['line']}" if ex['line'] else "") + \
              (f" 订单{ex['order']}" if ex['order'] else "")
        print(f"  [{items[0]['severity']}] {rule} ×{len(items)}  {META[rule][1][:46]}"
              f"  例: {loc} 期望[{ex['expected'][:28]}] 实际[{ex['actual'][:28]}]")
        for it in items[1:min(args.max_examples, len(items))]:
            print(f"        - {it['file']} L{it['line']} 订单{it['order']} {it['column']}"
                  f" 期望[{it['expected'][:40]}] 实际[{it['actual'][:40]}]")


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="SM SIA 提交物验证器")
    ap.add_argument("target", nargs="?", help="待验证目录(--rules 模式可省略)")
    ap.add_argument("--baseline", choices=["sample", "spec"], default="sample",
                    help="明细表布局期望基线(默认 sample=已认证样例 18 列布局);实际槽位按表头自动探测")
    ap.add_argument("--mov-caliber", choices=["app", "golden"], default="golden",
                    help="MOV 税额口径,默认 golden(=app 实测口径,经 PPOS.db 真实订单 EJ 复核 2026-10-04);"
                         "app=早期从 calculateOrder 代码推断的口径(VAT 按折后净额),真实链路未采用,仅留作排查")
    ap.add_argument("--tol", type=float, default=0.02, help="金额容差(默认 0.02)")
    ap.add_argument("--no-evidence", action="store_true", help="跳过 ORs/ZReads 证据校验")
    ap.add_argument("--out-dir", default="out", help="报告输出目录")
    ap.add_argument("--max-examples", type=int, default=5, help="控制台示例条数")
    ap.add_argument("--rules", action="store_true", help="打印规则清单后退出")
    args = ap.parse_args()

    if args.rules:
        for rid in sorted(META, key=lambda k: (META[k][0], k)):
            print(f"[{META[rid][0]:5}] {rid:5} {META[rid][1]}")
        print(f"共 {len(META)} 条")
        sys.exit(0)
    if not args.target:
        ap.error("缺少待验证目录(或使用 --rules 查看规则清单)")

    root = Path(args.target)
    if not root.is_dir():
        print(f"目标不存在或不是目录: {root}", file=sys.stderr)
        sys.exit(2)

    tx_files = sorted(root.glob("*_transactions.csv"))
    dt_files = sorted(root.glob("*_transactiondetails.csv"))
    findings = Findings()

    if not tx_files or not dt_files:
        findings.add("F01", str(root),
                     detail=f"目录内未同时找到 *_transactions.csv({len(tx_files)})"
                            f" 与 *_transactiondetails.csv({len(dt_files)})")
    for f in tx_files + dt_files:
        if not re.match(r"^(0[1-9]|1[0-2])_\d{4}_(transactions|transactiondetails)\.csv$", f.name):
            findings.add("F01", f.name, detail="文件名不符合 mm_yyyy_transactions.csv 规范")
    if tx_files and dt_files and tx_files[0].name[:7] != dt_files[0].name[:7]:
        findings.add("F01", f"{tx_files[0].name} / {dt_files[0].name}", detail="两个文件的 mm_yyyy 期号不一致")

    tx_name = tx_files[0].name if tx_files else "(缺 transactions.csv)"
    dt_name = dt_files[0].name if dt_files else "(缺 transactiondetails.csv)"

    header, tx_rows = [], []
    if tx_files:
        header, tx_rows = parse_csv_strict(tx_files[0], findings, header_quoted=True)
        if header != TX_HEADER:
            missing = [c for c in TX_HEADER if c not in header]
            extra = [c for c in header if c not in TX_HEADER]
            findings.add("F03", tx_name, expected="63 列固定表头(需求文档 §13.2)",
                         actual=f"实际 {len(header)} 列;缺:{missing[:4]};多:{extra[:4]}")

    det_header, dt_rows = [], []
    if dt_files:
        want = DET_HEADER_SAMPLE if args.baseline == "sample" else DET_HEADER_SPEC
        det_header, dt_rows = parse_csv_strict(dt_files[0], findings,
                                               header_quoted=(args.baseline == "spec"))
        if det_header != want:
            findings.add("F03", dt_name, expected=f"基线[{args.baseline}]表头 {want}",
                         actual=f"实际 {det_header}",
                         detail="若为有意选择另一布局,请加 --baseline spec|sample 并与 SM/Mosaic 确认")
    slots, _layout = detect_det_slots(det_header)
    if det_header and slots is None:
        findings.add("F03", dt_name, detail="明细表头无法识别为 sample/spec 任一布局,明细字段级检查跳过")

    # 明细行预索引(2026-10-22 A05/A09 豁免判据用;D 族逐行检查仍在后文不变):
    # A05=单个 MOV/NAAC 人只折自己商品(非整单)时,TD=Σ明细(NAAC/MOV 码)折扣×qty
    #   即判"明细可解释"跳过整单 20% 判据(订单208: 26.79+35.71+53.57×2+60.00
    #   =229.64=TD;209/555-13 同构实证);
    # A09=部分退款 |Gross| 不等于任何整单额,改按明细(商品,单价)子集回链原单
    #   (REFUND06=SALE239(950) 退 A150+C300=450 实证)
    det_idx = defaultdict(list)  # order -> [(label, qty, price, code, damt)]
    if slots is not None:
        for _ln, _r in dt_rows:
            if len(_r) != len(det_header):
                continue
            _q = money(_r[slots["Item Quantity"]])
            _p = money(_r[slots["Transaction Item Price"]])
            _da = money(_r[slots["Discount Amount"]])
            if _q is None or _p is None or _da is None:
                continue
            det_idx[_r[slots["Order Num / Bill Num"]]].append(
                (f"{_r[slots['Item ID']]},{_r[slots['Item Name']]}", _q, _p,
                 str(_r[slots["Discount Code"]] or "").strip().upper(), _da))

    # ---------------- 主表逐行 ----------------
    ix = {n: i for i, n in enumerate(header)}
    tx_by_order, pos_gross_amounts = {}, []

    for ln, r in tx_rows:
        if len(r) != len(header):
            findings.add("F05", tx_name, line=ln, expected=f"{len(header)} 列", actual=f"{len(r)} 列")
            continue

        def get(c, _r=r, _ix=ix):
            return _r[_ix[c]] if c in _ix else ""

        o = get("Order Num / Bill Num")
        g = lambda c: money(get(c))

        # ---- 字段格式(F/V 族) ----
        for c in TX_STRICT_ALNUM:
            if not ALNUM.match(get(c)):
                findings.add("V01", tx_name, line=ln, order=o, column=c, expected="仅字母数字", actual=get(c))
        for c in TX_TEXT_COLS:
            if len(get(c)) > 250:
                findings.add("V10", tx_name, line=ln, order=o, column=c, expected="≤250 字符", actual=f"{len(get(c))} 字符")
        for k in (1, 2, 3):
            pt = get(f"Payment Type_{k}")
            if pt and not ALNUM.match(pt):
                findings.add("V02", tx_name, line=ln, order=o, column=f"Payment Type_{k}",
                             expected="仅字母数字(样例代码:CSH/CCMASTERCRD/DCVISA/GIFTCHEQUE/GCASH/MALLPAYxx)", actual=pt)
        if not valid_date(get("Business Day")):
            findings.add("F06", tx_name, line=ln, order=o, column="Business Day", actual=get("Business Day"))
        for c in ("Check Open", "Check Close"):
            if not valid_dt(get(c)):
                findings.add("F06", tx_name, line=ln, order=o, column=c, actual=get(c))
        if all(valid_dt(get(c)) for c in ("Check Open", "Check Close")):
            t_open = datetime.fromisoformat(get("Check Open"))
            t_close = datetime.fromisoformat(get("Check Close"))
            if t_open > t_close:
                findings.add("V09", tx_name, line=ln, order=o, expected="Check Open ≤ Check Close",
                             actual=f"{get('Check Open')} > {get('Check Close')}")
            bd_s = get("Business Day")
            if valid_date(bd_s):  # 坏/缺/日历不存在的营业日已由 F06 报告,此处只对合法日期做归属判定
                bd = date.fromisoformat(bd_s)
                close_d = t_close.date()
                if bd == close_d - timedelta(days=1) and t_close.hour >= 6:
                    findings.add("V08", tx_name, line=ln, order=o, column="Business Day",
                                 expected="非凌晨结单应归 Check Close 当天", actual=f"BD={bd} close={t_close}")
                elif bd not in (close_d, close_d - timedelta(days=1)):
                    findings.add("V08", tx_name, line=ln, order=o, column="Business Day",
                                 expected=f"= {close_d}(或凌晨结单前一天)", actual=str(bd))
        for c in TX_HEADER:
            if c not in TX_NULLABLE and get(c) == "":
                findings.add("V03", tx_name, line=ln, order=o, column=c, expected="非空(该列不可空)", actual='""')
        for c in TX_NUMERIC_COLS:
            v = get(c)
            if v and not NUM2_RX.match(v):
                findings.add("V04", tx_name, line=ln, order=o, column=c, expected="两位小数数值", actual=v)
        gc_, gsen, gpwd = g("Guest Count"), g("Guest Count (Senior)"), g("Guest Count (PWD)")
        if gc_ == 0:
            findings.add("V05", tx_name, line=ln, order=o, column="Guest Count", expected="≥1", actual="0")
        if None not in (gc_, gsen, gpwd) and gc_ < gsen + gpwd:
            findings.add("V12", tx_name, line=ln, order=o, column="Guest Count",
                         expected=f"≥ Senior+PWD={gsen + gpwd:.0f}", actual=f"{gc_:.0f}")
        for c in ("Void", "Refund"):
            if get(c) not in ("0", "1"):
                findings.add("V06", tx_name, line=ln, order=o, column=c, actual=get(c))
        if not re.match(r"^SM(0[1-9]|10)$", get("Sales Type")):
            findings.add("V07", tx_name, line=ln, order=o, column="Sales Type", actual=get("Sales Type"))
        for k in (1, 2, 3):
            if (not get(f"Payment Type_{k}")) and (g(f"Payment Amount_{k}") or 0) != 0:
                findings.add("V11", tx_name, line=ln, order=o, column=f"Payment Amount_{k}",
                             expected="类型为空时金额=0", actual=get(f"Payment Amount_{k}"))

        # ---- 金额(A 族) ----
        vals = {c: (g(c) or 0.0) for c in AMOUNT_KEYS}
        psum = round(sum(g(f"Payment Amount_{k}") or 0.0 for k in (1, 2, 3)), 2)

        mov_disc = vals["National Coach / Athlete /  Medal of Valor Discount amount"]
        disc_vat = round(mov_disc * 0.12, 2) if (mov_disc > 0 and args.mov_caliber == "app") else 0.0

        lhs = round(vals["Net Sales Amount"] + vals["Total Tax"] + vals["Total Service Charge"]
                    + vals["Total Discount"] + vals["Less Tax Amount"] + disc_vat, 2)
        if abs(lhs - vals["Gross Sales Amount"]) > args.tol:
            findings.add("A01", tx_name, line=ln, order=o,
                         expected=f"Gross={vals['Gross Sales Amount']:.2f}",
                         actual=f"Net+Tax+SVC+Disc+LessTax{'+折扣VAT' if disc_vat else ''}={lhs:.2f}",
                         detail="金额恒等式不平(净/税/服务费/折扣/免税任一项算错)")

        payable = round(vals["Gross Sales Amount"] - vals["Total Discount"]
                        - vals["Less Tax Amount"] - disc_vat, 2)
        if abs(psum - payable) > args.tol:
            findings.add("A02", tx_name, line=ln, order=o,
                         expected=f"支付合计={payable:.2f}(=Gross−Discount−LessTax)", actual=f"{psum:.2f}",
                         detail="支付金额与应付不一致;常见原因:服务费未计入 Gross、或支付额含未被主表承认的费用")

        if (mov_disc == 0 or args.mov_caliber == "app") and vals["Total Tax"] != 0:
            vat_expect = round((vals["Net Sales Amount"] - vals["Tax Exempt Sales"]) * 0.12, 2) \
                         + vals["Other/Local Tax"]
            # 2026-10-20 修复:先 round 再比较会把真差 0.016(如订单155 净1951.80/TE300
            # →198.216 vs Tax198.20)抬成 0.02 的浮点边界假红;改比原始差值+epsilon,
            # 口径不变(容差仍 0.011~0.02,含边界),金样例回归不变
            vat_raw = (vals["Net Sales Amount"] - vals["Tax Exempt Sales"]) * 0.12 \
                      + vals["Other/Local Tax"]
            if abs(vat_raw - vals["Total Tax"]) > max(args.tol, 0.011) + 1e-9:
                findings.add("A03", tx_name, line=ln, order=o, column="Total Tax",
                             expected=f"≈{vat_expect:.2f}((Net−TaxExempt)×12%+LocalTax)",
                             actual=f"{vals['Total Tax']:.2f}",
                             detail="VAT 口径:价内税(Net=含税/1.12);地方税按样例并入 TotalTax。"
                                    "若把 Tax 算成 Gross×12%(价外税)即触发本条")

        if vals["Senior Citizen Discount Amount"] > 0:
            if vals["Less Tax Amount"] <= 0:
                findings.add("A04", tx_name, line=ln, order=o, column="Less Tax Amount",
                             expected=">0(Senior 折扣必须先扣 VAT 32.14/300 口径)",
                             actual=f"{vals['Less Tax Amount']:.2f}",
                             detail="算法应为:净=Gross/1.12 → 折扣=净×20% → LessTax=Gross−净")
            if (gsen or 0) < 1:
                findings.add("A04", tx_name, line=ln, order=o, column="Guest Count (Senior)",
                             expected="≥1", actual=get("Guest Count (Senior)"))
        if vals["PWD Discount Amount"] > 0:
            if vals["Less Tax Amount"] <= 0:
                findings.add("A04", tx_name, line=ln, order=o, column="Less Tax Amount",
                             expected=">0(PWD 折扣必须先扣 VAT)", actual=f"{vals['Less Tax Amount']:.2f}")
            if (gpwd or 0) < 1:
                findings.add("A04", tx_name, line=ln, order=o, column="Guest Count (PWD)",
                             expected="≥1", actual=get("Guest Count (PWD)"))
        if mov_disc > 0:
            # 2026-10-20 多人政府折扣豁免:A05 按单人 MOV 建模(折扣=整单净额×20%),
            # 多人混合单(SC+NAAC+MOV 各按各自份额折扣)不适用——Sen/PWD 折扣>0
            # 即判多人单跳过 A05(订单145 三人/146 五人实证);continue 会跳过
            # 后续 D01 等检查,改为嵌套 if 只跳过 A05 本身
            multi_gov = vals["Senior Citizen Discount Amount"] > 0 or vals["PWD Discount Amount"] > 0
            # 2026-10-22 明细可解释性豁免(第二轮盲区):单个 MOV/NAAC 人只折自己的
            # 部分商品时,折扣=被折行去税净额×20%(逐行精确),整单判据必然偏差——
            # TD 与明细 MOV/NAAC 码行折扣合计(|qty| 加权)一致即判通过
            # (订单208=229.64/209=185.00/555-13=14.28 三单实证)
            gov_detail_sum = sum(abs(d[4]) * abs(d[1]) for d in det_idx.get(o, ())
                                 if d[3] in ("NAAC", "MOV"))
            detail_ok = abs(round(gov_detail_sum, 2) - mov_disc) <= args.tol
            if not multi_gov and not detail_ok:
                expect = round(vals["Gross Sales Amount"] / 1.12 * 0.20, 2)
                if abs(expect - mov_disc) > args.tol:
                    findings.add("A05" if args.mov_caliber == "golden" else "A05E", tx_name, line=ln, order=o,
                                 column="NationalCoach / Athlete / Medal of Valor Discount amount",
                                 expected=f"≈{expect:.2f}(去税净额×20%)", actual=f"{mov_disc:.2f}",
                                 detail=("金样例S7(=app 实测,EJ 复核):折扣=净额×20%,VAT=折前净额×12%照收,应付=Gross−折扣"
                                         if args.mov_caliber == "golden" else
                                         "app 口径(废弃分支):折扣=净额×20%,VAT=折后净额×12%,应付=原价×80%"))

        disc_parts = []
        roa = get("Regular / Other Discount Amount")
        if roa:
            try:
                disc_parts += [float(x) for x in roa.split("::")]
            except ValueError:
                pass
        disc_parts += [vals["Employee Discount Amount"], vals["Senior Citizen Discount Amount"],
                       vals["VIP Discount Amount"], vals["PWD Discount Amount"], mov_disc,
                       vals["SMAC Discount Amount"], vals["Online Deals Discount Amount"]]
        disc_parts += [g(f"Discount Field {k} Amount") or 0.0 for k in range(1, 7)]
        if abs(round(sum(disc_parts), 2) - vals["Total Discount"]) > args.tol:
            findings.add("A06", tx_name, line=ln, order=o, column="Total Discount",
                         expected=f"={round(sum(disc_parts), 2):.2f}(分列之和)",
                         actual=f"{vals['Total Discount']:.2f}")

        agg = defaultdict(float)
        for k in (1, 2, 3):
            pt, pa = get(f"Payment Type_{k}"), g(f"Payment Amount_{k}") or 0.0
            if pt:
                cat = classify_tender(pt)
                if cat is None:
                    findings.add("A07", tx_name, line=ln, order=o, detail=f"无法归类的支付方式: {pt}")
                else:
                    agg[cat] += pa
        cc_total = round(sum(v for k, v in agg.items()
                             if k in ("mc", "visa", "amex", "diners", "jcb", "othercc")), 2)
        for cat, col in TENDER_COL.items():
            colv = g(col) or 0.0
            want = round(agg.get(cat, 0.0), 2)
            ok7 = abs(colv - want) <= args.tol
            if cat == "other" and not ok7:
                # 已认证样例口径:Total Other Tender = 其他支付 + 全部信用卡金额重复计入
                ok7 = abs(colv - round(want + cc_total, 2)) <= args.tol
            if not ok7:
                rule7 = "A07N" if vals["Gross Sales Amount"] < 0 else "A07"
                findings.add(rule7, tx_name, line=ln, order=o, column=col,
                             expected=f"={want:.2f}(按 Payment Type 归类;Other 列样例口径另接受 +信用卡{cc_total:.2f})",
                             actual=f"{colv:.2f}")

        if get("Void") == "1" and (vals["Gross Sales Amount"] >= 0 or vals["Void Amount"] <= 0):
            findings.add("A08", tx_name, line=ln, order=o,
                         expected="整单作废:Gross/Net/Tax/支付为负且 Void Amount>0",
                         actual=f"Gross={vals['Gross Sales Amount']:.2f} VoidAmount={vals['Void Amount']:.2f}")
        if get("Refund") == "1":
            if vals["Gross Sales Amount"] < 0 and vals["Refund Amount"] >= 0:
                findings.add("A08", tx_name, line=ln, order=o, column="Refund Amount",
                             expected="<0(新单号退款为负数)", actual=f"{vals['Refund Amount']:.2f}")
            if vals["Gross Sales Amount"] >= 0 and vals["Refund Amount"] <= 0:
                findings.add("A08", tx_name, line=ln, order=o, column="Refund Amount",
                             expected=">0(同单号原行更新为正数)", actual=f"{vals['Refund Amount']:.2f}")

        if vals["Gross Sales Amount"] > 0:
            pos_gross_amounts.append(vals["Gross Sales Amount"])
        tx_by_order[o] = (ln, r, ix, vals, psum)

    # A09:退款可对应历史正单
    # 2026-10-22 部分退感知:部分退款的 |Gross| 是退货商品组合额,不等于任何整单额,
    # 同额匹配必然落空(REFUND06=SALE239(950) 退 A150+C300=450 首次实证;此前
    # 300/350/800/650 恰有同额他单碰巧通过)。全额退维持同额匹配;部分退改按
    # 明细(商品,单价)子集回链——退货行(label,price)能在某正单中找到且数量足够,
    # 且该正单 Gross ≥ 退款额,即判原单可追溯。
    pos_gross = {round(v, 2) for v in pos_gross_amounts}
    pos_orders = {}  # order -> (gross, {(label, price): qty})
    for po, (_pl, _pr, _pix, pvals, _pp) in tx_by_order.items():
        if pvals["Gross Sales Amount"] > 0 and \
                _pr[_pix["Void"]] != "1" and _pr[_pix["Refund"]] != "1":
            bag = defaultdict(float)
            for d in det_idx.get(po, ()):
                bag[(d[0], d[2])] += abs(d[1])
            pos_orders[po] = (pvals["Gross Sales Amount"], bag)
    for o, (ln, r, ix_, vals, psum) in tx_by_order.items():
        refund_flag = r[ix_["Refund"]] if "Refund" in ix_ else "0"
        if refund_flag == "1" or (vals["Refund Amount"] != 0 and vals["Gross Sales Amount"] < 0):
            amt = abs(vals["Gross Sales Amount"])
            same_amt = any(abs(amt - p) <= args.tol for p in pos_gross)
            subset_ok = False
            if not same_amt:
                need = defaultdict(float)
                for d in det_idx.get(o, ()):
                    need[(d[0], d[2])] += abs(d[1])
                if need:
                    subset_ok = any(
                        amt <= pg + args.tol and all(
                            bag.get(k, 0) >= q - 1e-9 for k, q in need.items())
                        for pg, bag in pos_orders.values())
            if not same_amt and not subset_ok:
                findings.add("A09", tx_name, line=ln, order=o,
                             expected=f"|Gross|={amt:.2f} 能对应同额正销售或明细可回链原单(部分退)",
                             actual="历史交易中无同额正单,明细亦无可回链原单")

    # F08:文件期号与营业日一致性 + 30 天滚动窗口
    if tx_files and tx_by_order and "Business Day" in ix:
        m = re.match(r"^(\d{2})_(\d{4})_", tx_files[0].name)
        if m:
            period = f"{m.group(2)}-{m.group(1)}"
            days = sorted({r[ix["Business Day"]] for _, r, _, _, _ in tx_by_order.values()})
            bad = [d for d in days if not d.startswith(period)]
            if bad:
                findings.add("F08", tx_name, expected=f"营业日均属文件期号 {period}",
                             actual=f"{len(bad)} 天越期: {bad[:5]}")
            if days:
                try:
                    span = (date.fromisoformat(days[-1]) - date.fromisoformat(days[0])).days + 1
                except ValueError:
                    span = 0  # 营业日值格式坏已由 F06 报告
                if span > 30:
                    findings.add("F08", tx_name, expected="30 天滚动窗口(今天−29 ~ 今天)",
                                 actual=f"数据跨度 {span} 天({days[0]}~{days[-1]})",
                                 detail="认证测试数据可豁免;生产文件须滚动裁剪")

    # ---------------- 明细逐行(D 族) ----------------
    det_by_order = defaultdict(list)
    if slots is not None:
        for ln, r in dt_rows:
            if len(r) != len(det_header):
                findings.add("F05", dt_name, line=ln, expected=f"{len(det_header)} 列", actual=f"{len(r)} 列")
                continue
            o = r[slots["Order Num / Bill Num"]]
            det_by_order[o].append((ln, r))
            dg = lambda c: money(r[slots[c]])
            qty, tx, menu, disc = dg("Item Quantity"), dg("Transaction Item Price"), \
                dg("Menu Item Price"), dg("Discount Amount")
            if qty is None:
                findings.add("D07", dt_name, line=ln, order=o, column="Item Quantity",
                             actual=r[slots["Item Quantity"]])
            if dg("Item ID") == "":
                findings.add("D08", dt_name, line=ln, order=o, column="Item ID",
                             detail="Item ID 为空:确认属 SKU 不披露档位(b/c 档有意留空)")
            if tx is not None and menu is not None and tx > menu + args.tol:
                findings.add("D03", dt_name, line=ln, order=o, column="Transaction Item Price",
                             expected=f"≤ 原价 {menu:.2f}", actual=f"{tx:.2f}")
            if None not in (menu, tx, disc) and abs((menu - tx) - disc) > args.tol:
                findings.add("D04", dt_name, line=ln, order=o, column="Discount Amount",
                             expected=f"={menu - tx:.2f}(原价−成交价,口径B)", actual=f"{disc:.2f}")
            vflag, rflag = r[slots["Void"]], r[slots["Refund"]]
            for c, f in (("Void", vflag), ("Refund", rflag)):
                if f not in ("0", "1"):
                    findings.add("V06", dt_name, line=ln, order=o, column=c, actual=f)
            if vflag == "1" or rflag == "1":
                if qty is not None and qty > 0:
                    findings.add("D05", dt_name, line=ln, order=o, column="Item Quantity",
                                 expected="=-1(作废/退款行数量为负)", actual=f"{qty:.2f}")
                amt_col = "Void Amount" if vflag == "1" else "Refund Amount"
                if (dg(amt_col) or 0) <= 0:
                    findings.add("D05", dt_name, line=ln, order=o, column=amt_col,
                                 expected=">0(明细作废/退款金额填正数)", actual=r[slots[amt_col]])
                t = tx_by_order.get(o)
                mcol = "Void" if vflag == "1" else "Refund"
                # 主表缺 Void/Refund 列已由 F03 报 ERROR,次级检查不追加(与 A09 缺列默认
                # "0"、E02 缺列跳过同口径,2026-10-11 评审);孤儿明细(t=None)由 D01 报
                if t and mcol in t[2] and t[1][t[2][mcol]] != "1":
                    findings.add("D06", dt_name, line=ln, order=o, column="Void/Refund",
                                 expected="主表对应交易 tag=1", actual=f"主表={t[1][t[2][mcol]]}")

        # 主↔明细覆盖 + 金额合计(D01/D02/D05)
        for o, (ln, r, ix_, vals, psum) in tx_by_order.items():
            rows = det_by_order.get(o)
            if not rows:
                findings.add("D01", tx_name, line=ln, order=o, expected="明细表存在该订单的商品行", actual="缺失")
                continue
            total, ok = 0.0, True
            for _dln, dr in rows:
                qq, pp = money(dr[slots["Item Quantity"]]), money(dr[slots["Transaction Item Price"]])
                if qq is None or pp is None:
                    ok = False
                    continue
                total += qq * pp
            # 2026-10-20 修复:负折扣单 LT/TD 为负值,不取绝对值会把期望抬高
            # (设备2 VOID 单 TD=-73 实证 expect 198 假红);金样例负单 TD/LT=0 不受影响
            expect = round(abs(vals["Gross Sales Amount"]) - vals["Other/Local Tax"]
                           - abs(vals["Less Tax Amount"]) - abs(vals["Total Discount"]), 2)
            if ok and abs(round(abs(total), 2) - expect) > args.tol:
                findings.add("D02", tx_name, line=ln, order=o,
                             expected=f"明细 Σ(qty×成交价)={expect:.2f}(|Gross|−LocalTax−LessTax−Discount)",
                             actual=f"{total:.2f}",
                             detail="常见原因:折扣/免税/服务费未摊入商品成交价,或明细价格与主表脱节")
            void_flag = r[ix_["Void"]] if "Void" in ix_ else "0"
            refund_flag = r[ix_["Refund"]] if "Refund" in ix_ else "0"
            if void_flag == "1" or refund_flag == "1":
                amt_col = "Void Amount" if void_flag == "1" else "Refund Amount"
                per_row = {money(dr[slots[amt_col]]) for _, dr in rows}
                max_menu = max((money(dr[slots["Menu Item Price"]]) or 0) for _, dr in rows)
                if per_row and abs(list(per_row)[0] - abs(vals["Gross Sales Amount"])) > args.tol \
                        and abs(list(per_row)[0] - max_menu) <= args.tol:
                    findings.add("D05", dt_name, line=ln, order=o, column=amt_col,
                                 expected="整单金额(已认证样例口径,每行=整单额)", actual="逐商品金额",
                                 detail="03 提交包曾选择逐商品口径;两种口径需与 SM 确认后统一")
        for o, rows in det_by_order.items():
            if o not in tx_by_order:
                findings.add("D01", dt_name, line=rows[0][0], order=o, expected="主表存在该订单", actual="孤儿明细行")

    # ---------------- 证据件 + 输出 ----------------
    if not args.no_evidence:
        check_evidence(root, tx_by_order, ix, findings, args.tol)

    n = severity_counts(findings)
    base = write_reports(root, args, findings, n["ERROR"], n["WARN"], n["INFO"])
    print_console(root, args, findings)
    print(f"报告: {base}.md / {base}.json")
    sys.exit(1 if n["ERROR"] else 0)


if __name__ == "__main__":
    main()

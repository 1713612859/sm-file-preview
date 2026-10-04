#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SM SIA 标准参考生成器 —— 以已认证样例为数据源,重建完整提交物并自校验。

做什么:
  1. 读取 02 已认证样例(标准答案)的两个 CSV,按目标期号平移日期后原值重写;
  2. 从 CSV 字段按校准口径生成每笔交易的 OR 票据(txt,POS 小票版式)
     —— VATable = Net − TaxExempt(修复模拟器"Net−VAT"缺陷);
  3. 按营业日聚合生成 Z-Reading(txt),作废/退款负单计入日合计
     —— 标签用 GROSS AMOUNT:/VAT AMOUNT:(带冒号,保证验证器 E05 真正对账);
  4. 自动调用 sia_validator.py 全量校验,并产出《生成报告》。
定位:研发 SMFileGenerator 实现前的**目标形态对拍基准**;金额取自已认证样例,不重算
(重算引擎见 sia_recompute.py;共享常量见 sia_common.py)。

用法:
  python sia_generator.py [--source <样例目录>] [--to 2026-09] [--out-dir out] [--skip-validate]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from sia_common import AMOUNT_KEYS, load_csv, money, q, R

GOLDEN_DEFAULT = r"C:\Users\Administrator\Desktop\SM mall 认证\02_认证样例数据(SM提供)\SM SIA TestScenarios 2024-07-31"

DISCOUNT_LABELS = [
    ("Senior Citizen Discount Amount", "Discount (SC 20%)"),
    ("PWD Discount Amount", "Discount (PWD 20%)"),
    ("National Coach / Athlete /  Medal of Valor Discount amount", "Discount (MOV 20%)"),
    ("VIP Discount Amount", "Discount (VIP)"),
    ("Employee Discount Amount", "Discount (Employee)"),
    ("SMAC Discount Amount", "Discount (SMAC)"),
    ("Online Deals Discount Amount", "Discount (Online Deals)"),
]
TENDER_LABEL = {
    "CSH": "CASH", "CASH": "CASH", "GIFTCHEQUE": "GIFT CHEQUE", "GIFT_CHECK": "GIFT CHEQUE",
    "DCMASTERCRD": "DEBIT CARD - MASTERCARD", "DCVISA": "DEBIT CARD - VISA",
    "CCMASTERCRD": "CREDIT CARD - MASTERCARD", "CCVISA": "CREDIT CARD - VISA",
    "CCDINERS": "CREDIT CARD - DINERS", "CCAMEX": "CREDIT CARD - AMEX",
    "GCASH": "GCASH", "PAYMAYA": "PAYMAYA", "MALLPAY01": "MALLPAY 1", "MALLPAY03": "MALLPAY 3",
    "MALLPAY04": "MALLPAY 4",
}
# 明细槽位(样例 18 列布局)
DSLOT_NAME, DSLOT_QTY, DSLOT_TX = 2, 5, 6


def fmt(v):
    return f"{v:,.2f}"


def lr(k: str, v, w: int = 48) -> str:
    """左标签右值,数值右贴行宽(EJ leftRightText 风格);标签超长时截断保数值。"""
    v = str(v)
    if len(k) > w - len(v) - 1:
        k = k[: w - len(v) - 1]
    return f"{k}{v:>{w - len(k)}}"


def center(s: str, w: int = 48) -> str:
    pad = max(0, (w - len(s)) // 2)
    return " " * pad + s


def negfmt(v: float) -> str:
    """EJ 税区负值口径:非 0 显示 -abs,0.00 显示正 0.00。"""
    a = fmt(abs(v))
    return "0.00" if a == "0.00" else "-" + a


def shift(datestr: str, to_y: str, to_m: str) -> str:
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(.*)$", datestr)
    return datestr if not m else f"{to_y}-{to_m}-{m.group(3)}{m.group(4)}"


class Generator:
    def __init__(self, source: Path, to: str, out_root: Path):
        tx = sorted(source.glob("*_transactions.csv"))
        dt = sorted(source.glob("*_transactiondetails.csv"))
        if not tx or not dt:
            sys.exit(f"源目录缺少样例 CSV: {source}")
        self.tx_rows = load_csv(tx[0])
        self.dt_rows = load_csv(dt[0])
        self.dt_header = self.dt_rows[0]
        self.ix = {n: i for i, n in enumerate(self.tx_rows[0])}
        self.items = defaultdict(list)          # 订单号 -> 明细行(一次建索引,消 O(n²) 扫描)
        for r in self.dt_rows[1:]:
            self.items[r[0]].append(r)
        self.source = source
        self.to_y, self.to_m = to.split("-")
        self.out_dir = out_root / f"sia_generated_{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    # ---------- CSV ----------
    def write_csvs(self):
        (self.out_dir / "ORs").mkdir(parents=True, exist_ok=True)
        (self.out_dir / "ZReads").mkdir(exist_ok=True)
        date_cols = {self.ix["Business Day"], self.ix["Check Open"], self.ix["Check Close"]}
        shift_row = lambda r: [shift(c, self.to_y, self.to_m) if i in date_cols else c
                               for i, c in enumerate(r)]
        lines = [",".join(q(c) for c in self.tx_rows[0])]
        lines += [",".join(q(c) for c in shift_row(r)) for r in self.tx_rows[1:]]
        (self.out_dir / f"{self.to_m}_{self.to_y}_transactions.csv").write_text(
            "\r\n".join(lines) + "\r\n", encoding="utf-8", newline="")

        lines = [",".join(self.dt_header)]      # 样例基线:明细表头不带引号
        lines += [",".join(q(c) for c in r) for r in self.dt_rows[1:]]
        (self.out_dir / f"{self.to_m}_{self.to_y}_transactiondetails.csv").write_text(
            "\r\n".join(lines) + "\r\n", encoding="utf-8", newline="")

    # ---------- 数据视图(字段全部即时快照,规避闭包晚绑定) ----------
    def orders(self):
        for r in self.tx_rows[1:]:
            cell = lambda c: r[self.ix[c]]
            vals = {c: money(cell(c)) or 0.0 for c in AMOUNT_KEYS}
            yield {
                "order": cell("Order Num / Bill Num"),
                "day": shift(cell("Business Day"), self.to_y, self.to_m),
                "close": shift(cell("Check Close"), self.to_y, self.to_m),
                "trx_type": cell("Transaction Type"), "void": cell("Void"), "refund": cell("Refund"),
                "terminal": cell("Terminal Number"), "serial": cell("Serial Number"),
                "guest": cell("Guest Count"),
                "pays": [(cell(f"Payment Type_{k}"), money(cell(f"Payment Amount_{k}")) or 0.0)
                         for k in (1, 2, 3)],
                "paysum": R(sum(money(cell(f"Payment Amount_{k}")) or 0.0 for k in (1, 2, 3))),
                "vals": vals,
            }

    # ---------- OR 票据(销售票,EJ salesInvoice 版式) ----------
    def render_or(self, o) -> str:
        v = o["vals"]
        gross = abs(v["Gross Sales Amount"])
        payable = R(gross - v["Total Discount"] - v["Less Tax Amount"])
        exempt = abs(v["Tax Exempt Sales"])
        vatable = max(R(abs(v["Net Sales Amount"]) - exempt), 0.0)
        mov = v["National Coach / Athlete /  Medal of Valor Discount amount"]
        vat_off = R(gross - gross / 1.12)
        gov = "SC" if v["Senior Citizen Discount Amount"] > 0 else \
              ("PWD" if v["PWD Discount Amount"] > 0 else None)

        L, ap = [], lambda s="": L.append(s)
        ap(f"                SN:{o['serial']}")
        ap(f"               {o['close']}")
        ap("-" * 48)
        ap(f"Billing#: {int(o['order']):016d}")
        ap(f"Trx Type: {o['trx_type']}")
        ap(f"Pax: {o['guest']}")
        ap("Cashier: Masteradmin")
        ap(f"TERMINAL#: {o['terminal']}")
        ap(f"Exact Date: {o['close']}")
        ap("-" * 48)
        ap("           SALES INVOICE")
        ap(f"               SI {int(o['order']):016d}")
        ap(center("Cashier Copy"))
        ap("-" * 48)
        ap(f"{'Description':<20}{'Qty':>6}{'U.Price':>12}{'Amount':>14}")
        ap("-" * 48)
        n_items, n_qty = 0, 0.0
        marker = "E" if exempt > 0 and exempt >= abs(v["Net Sales Amount"]) - 0.005 else "V"
        for it in self.items[o["order"]]:
            qty, price = money(it[DSLOT_QTY]) or 0.0, money(it[DSLOT_TX]) or 0.0
            n_items += 1
            n_qty += qty
            ap(it[DSLOT_NAME])
            ap(f"{qty:>26,.2f}{price:>12,.2f}{qty * price:>14,.2f} {marker}")
        ap("-" * 48)
        ap(lr("Gross Sales", fmt(gross)))
        # 免税/折扣区(与 CSV 口径一一对应)
        if v["Senior Citizen Discount Amount"] > 0 or v["PWD Discount Amount"] > 0:
            ap(lr("LESS 12% VAT", fmt(v["Less Tax Amount"])))
        if mov > 0:
            ap(lr("LESS 12% VAT", fmt(vat_off)))
        for col, label in DISCOUNT_LABELS:
            if v[col] > 0:
                ap(lr(label, fmt(v[col])))
        if mov > 0:  # MOV:折扣后按折前净额加回 VAT(应付=Gross−折扣)
            ap(lr("Add 12% VAT", fmt(vat_off)))
        if v["Total Service Charge"] > 0:
            ap(lr("Service Charge", fmt(v["Total Service Charge"])))
        if v["Other/Local Tax"] > 0:
            ap(lr("Local Tax", fmt(v["Other/Local Tax"])))
        ap(f"Amount Due{fmt(payable):>14}")
        ap("-" * 48)
        for pt, pa in o["pays"]:
            if pt:
                ap(lr(TENDER_LABEL.get(pt.upper(), pt), fmt(abs(pa))))
        ap(lr("CHANGE", "0.00"))
        ap("-" * 48)
        ap(lr("Number of Items", str(n_items)))
        ap(lr("Total Qty", f"{n_qty:,.2f}"))
        ap("-" * 48)
        ap(lr("VATable Sales", fmt(vatable)))
        ap(lr("VAT Amount (12%)", fmt(abs(v["Total Tax"]))))
        ap(lr("VAT Exempt Sales", fmt(exempt)))
        ap(lr("Zero Rated Sales", "0.00"))
        if gov:  # EJ 政府折扣顾客信息区(样例数据无顾客信息,字段留空)
            ap("-" * 48)
            ap(lr(f"{gov} NAME:", ""))
            ap(lr(f"{gov} ADDRESS:", ""))
            ap(lr(f"{gov} TIN:", ""))
            ap(lr(f"{gov} ID#:", ""))
            ap(f"{gov} Signature：__________________________________")
        ap("-" * 48)
        ap(f"                   {o['day']}")
        ap("-" * 48)
        ap("        THIS SERVES AS YOUR SALES INVOICE")
        return "\n".join(L) + "\n"

    # ---------- 作废/退货票(EJ voidReceipt/returnReceipt 版式) ----------
    def render_reversal(self, o, kind: str) -> str:
        """kind='VOID'|'RETURN';金额/税区按 EJ 口径全负号,数量取负。"""
        v = o["vals"]
        gross = abs(v["Gross Sales Amount"])
        payable = R(gross - v["Total Discount"] - v["Less Tax Amount"])
        exempt = abs(v["Tax Exempt Sales"])
        vatable = max(R(abs(v["Net Sales Amount"]) - exempt), 0.0)
        tag = "VOID" if kind == "VOID" else "RETURN"

        L, ap = [], lambda s="": L.append(s)
        ap(f"                SN:{o['serial']}")
        ap("-" * 48)
        ap(center(f"{kind} TRANSACTION"))
        ap(center("Cashier Copy"))
        ap("-" * 48)
        ap(lr(f"{tag}#", o["order"]))
        ap(lr("Date&Time", o["close"]))
        ap(lr("Sales SI#", o["order"]))
        ap("-" * 48)
        ap(f"Billing#: {int(o['order']):016d}")
        ap(f"Trx Type: {o['trx_type']}")
        ap(f"Pax: {o['guest']}")
        ap("Cashier: Masteradmin")
        ap(f"TERMINAL#: {o['terminal']}")
        ap("-" * 48)
        ap(f"{'Description':<20}{'Qty':>6}{'U.Price':>12}{'Amount':>14}")
        ap("-" * 48)
        for it in self.items[o["order"]]:
            qty, price = money(it[DSLOT_QTY]) or 0.0, money(it[DSLOT_TX]) or 0.0
            qty = -abs(qty)
            ap(it[DSLOT_NAME])
            ap(f"{qty:>26g}{price:>12,.2f}{qty * price:>14,.2f}")
        ap("-" * 48)
        if v["Total Service Charge"] > 0:
            ap(lr("Service Charge", "-" + fmt(v["Total Service Charge"])))
        ap(lr("Gross Sales", "-" + fmt(gross)))
        if v["Senior Citizen Discount Amount"] > 0 or v["PWD Discount Amount"] > 0:
            ap(lr("LESS 12% VAT", fmt(v["Less Tax Amount"])))
            ap(lr("Discount 20%", fmt(v["Total Discount"])))
            ap(lr("Add 12% VAT", fmt(v["Less Tax Amount"])))
        ap(f"Amount{'-' + fmt(payable):>14}")
        ap("-" * 48)
        for pt, pa in o["pays"]:
            if pt:
                ap(lr(TENDER_LABEL.get(pt.upper(), pt), "-" + fmt(abs(pa))))
        ap("-" * 48)
        ap(lr("VATable Sales", negfmt(vatable)))
        ap(lr("VAT Amount (12%)", negfmt(v["Total Tax"])))
        ap(lr("VAT Exempt Sales", negfmt(exempt)))
        ap(lr("Zero Rated Sales", "0.00"))
        ap("-" * 48)
        ap(lr("Customer Name:", ""))
        ap(lr("Address:", ""))
        ap(lr("TIN:", ""))
        ap("-" * 48)
        ap(f"                   {o['day']}")
        return "\n".join(L) + "\n"

    def write_ors(self):
        for o in self.orders():
            kind = "VOID" if o["void"] == "1" else ("RETURN" if o["refund"] == "1" else None)
            content = self.render_reversal(o, kind) if kind else self.render_or(o)
            (self.out_dir / "ORs" / f"{56245 + int(o['order'])}_T1_OR_{o['order']}.txt").write_text(
                content, encoding="utf-8", newline="")
        return len(self.tx_rows) - 1

    # ---------- Z-Read(EJ zReading 版式:四段结构,标签带冒号供 E05 对账) ----------
    def write_zreads(self):
        days = defaultdict(list)
        for o in self.orders():
            days[o["day"]].append(o)
        accumulated = 0.0
        for n, (day, os_) in enumerate(sorted(days.items()), start=1):
            voids = [o for o in os_ if o["void"] == "1"]
            rets = [o for o in os_ if o["refund"] == "1"]
            normal = [o for o in os_ if o["void"] != "1" and o["refund"] != "1"]
            S = lambda key, xs=normal: R(sum(o["vals"][key] for o in xs))   # EJ 口径:BREAKDOWN/GROSS 只计正常单
            si_all = [int(o["order"]) for o in os_]
            gross = S("Gross Sales Amount")
            vatable = R(sum(max(o["vals"]["Net Sales Amount"] - o["vals"]["Tax Exempt Sales"], 0.0)
                            for o in normal))
            less_tax = S("Less Tax Amount")
            void_amt = R(sum(abs(o["vals"]["Gross Sales Amount"]) for o in voids))
            ret_amt = R(sum(abs(o["vals"]["Gross Sales Amount"]) for o in rets))
            net = R(gross - S("Total Discount") - ret_amt - void_amt - less_tax)
            other_disc = R(S("Total Discount")
                           - S("Senior Citizen Discount Amount") - S("PWD Discount Amount")
                           - S("National Coach / Athlete /  Medal of Valor Discount amount"))
            report_time = max(o["close"] for o in os_)[-8:]

            L, ap = [], lambda s="": L.append(s)
            ap(f"                SN:{os_[0]['serial']}")
            ap("-" * 48)
            ap("        Z-READING REPORT")
            ap("-" * 48)
            ap(lr("Report Date & Time:", f"{day} {report_time}"))
            ap(lr("Start Date & Time:", f"{day} 00:00:00"))
            ap(lr("End Date & Time:", f"{day} 23:59:59"))
            ap(lr("Beg. SI #:", f"{min(si_all):016d}"))
            ap(lr("End. SI #:", f"{max(si_all):016d}"))
            ap(lr("Beg. VOID #:", f"{min(int(o['order']) for o in voids):016d}" if voids else "0" * 16))
            ap(lr("End. VOID #:", f"{max(int(o['order']) for o in voids):016d}" if voids else "0" * 16))
            ap(lr("Beg. RETURN #:", f"{min(int(o['order']) for o in rets):016d}" if rets else "0" * 16))
            ap(lr("End. RETURN #:", f"{max(int(o['order']) for o in rets):016d}" if rets else "0" * 16))
            ap(lr("Reset Invoice No.", "0"))
            ap(lr("Reset Accumulated Sales", "0"))
            ap(lr("Z Counter.", str(n))
               )
            ap("-" * 48)
            ap(lr("Present Accumulated Sales", fmt(R(accumulated + gross))))
            ap(lr("Previous Accumulated Sales:", fmt(R(accumulated))))
            ap(lr("Sales for the Day:", fmt(gross)))
            ap("-" * 48)
            ap("               BREAKDOWN OF SALES")
            ap(lr("VATABLE SALES:", fmt(vatable)))
            ap(lr("VAT AMOUNT:", fmt(S("Total Tax"))))
            ap(lr("VAT EXEMPT SALES:", fmt(S("Tax Exempt Sales"))))
            ap(lr("ZERO RATED SALES:", "0.00"))
            ap("-" * 48)
            ap(lr("GROSS AMOUNT:", fmt(gross)))
            ap(lr("LESS DISCOUNT:", fmt(S("Total Discount"))))
            ap(lr("LESS RETURN:", fmt(ret_amt)))
            ap(lr("LESS VOID:", fmt(void_amt)))
            ap(lr("LESS VAT ADJUSTMENT:", fmt(less_tax)))
            ap(lr("NET AMOUNT:", fmt(net)))
            ap("-" * 48)
            ap("                DISCOUNT SUMMARY")
            ap(lr("SC DISC:", fmt(S("Senior Citizen Discount Amount"))))
            ap(lr("PWD DISC:", fmt(S("PWD Discount Amount"))))
            ap(lr("NAAC DISC:", "0.00"))
            ap(lr("SP DISC:", "0.00"))
            ap(lr("MOV DISC:", fmt(S("National Coach / Athlete /  Medal of Valor Discount amount"))))
            ap(lr("OTHER DISC:", fmt(other_disc)))
            ap("-" * 48)
            ap("                SALES ADJUSTMENT")
            ap(lr("VOID:", fmt(void_amt)))
            ap(lr("RETURN:", fmt(ret_amt)))
            ap("-" * 48)
            ap("                 VAT ADJUSTMENT")
            ap(lr("SC TRANS:", fmt(S("Less Tax Amount") if S("Senior Citizen Discount Amount") > 0 else 0.0)))
            ap(lr("PWD TRANS:", fmt(S("Less Tax Amount") if S("PWD Discount Amount") > 0 else 0.0)))
            ap(lr("NAAC TRANS:", "0.00"))
            ap(lr("SP TRANS:", "0.00"))
            ap(lr("MOV TRANS:", "0.00"))
            ap(lr("DIPLOMATIC TRANS:", "0.00"))
            ap(lr("REG DISC TRANS:", "0.00"))
            ap(lr("ZERO-RATED TRANS:", "0.00"))
            ap(lr("VAT ON RETURN:", fmt(R(sum(abs(o["vals"]["Total Tax"]) for o in rets)))))
            ap(lr("VAT ON VOID:", fmt(R(sum(abs(o["vals"]["Total Tax"]) for o in voids)))))
            ap(lr("OTHER VAT Adjustment:", "0.00"))
            (self.out_dir / "ZReads" / f"Z-Reading_T1_{day}.txt").write_text(
                "\n".join(L) + "\n", encoding="utf-8", newline="")
            accumulated += gross
        return len(days)

    # ---------- 生成报告 ----------
    def write_report(self, or_n, zr_n, validator_out: str):
        days = defaultdict(list)
        for o in self.orders():
            days[o["day"]].append(o)
        rows = ["# SM SIA 标准参考生成报告", "",
                f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"- 数据源(已认证样例,值原样采用): `{self.source}`",
                f"- 目标期号: {self.to_y}-{self.to_m}(日期平移,金额不变)",
                f"- 口径: 金样例恒等式;MOV=折前净额税基(应付=Gross−折扣);票据 VATable=Net−TaxExempt;"
                f"ZRead 按净收款计(作废/退款已扣,标签带冒号供 E05 对账)", "",
                "## 生成物清单", "",
                "| 文件 | 数量 | 说明 |", "|---|---|---|",
                f"| `{self.to_m}_{self.to_y}_transactions.csv` | {len(self.tx_rows) - 1} 行 | 主表 63 列(样例布局) |",
                f"| `{self.to_m}_{self.to_y}_transactiondetails.csv` | {len(self.dt_rows) - 1} 行 | 明细 18 列(样例布局,表头不带引号) |",
                f"| `ORs/*.txt` | {or_n} 张 | 每笔交易一张;作废/退款票据内容有横幅标记 |",
                f"| `ZReads/*.txt` | {zr_n} 张 | 每营业日一张 |", "",
                "## 逐日汇总", "",
                "| 营业日 | 笔数 | 净收款合计 | VAT 合计 | 折扣合计 | 作废 | 退款 |",
                "|---|---|---|---|---|---|---|"]
        for day, os_ in sorted(days.items()):
            rows.append(
                f"| {day} | {len(os_)} | {fmt(R(sum(o['paysum'] for o in os_)))} | "
                f"{fmt(R(sum(o['vals']['Total Tax'] for o in os_)))} | "
                f"{fmt(R(sum(o['vals']['Total Discount'] for o in os_)))} | "
                f"{sum(1 for o in os_ if o['void'] == '1')} | {sum(1 for o in os_ if o['refund'] == '1')} |")
        rows += ["", "## 验证器结果(sia_validator.py,含证据件对账)", "", "```",
                 validator_out.strip(), "```", "",
                 "> 目标态:0 ERROR(WARN 仅样例固有负单口径 A07N)。",
                 "> 研发对拍:SMFileGenerator 产出的同口径数据,经验证器应达到与本报告一致的结果。"]
        (self.out_dir / "生成报告.md").write_text("\n".join(rows), encoding="utf-8", newline="")


def main():
    ap = argparse.ArgumentParser(description="SM SIA 标准参考生成器(样例数据 → CSV+OR票据+ZRead+自校验报告)")
    ap.add_argument("--source", default=GOLDEN_DEFAULT, help="已认证样例目录(默认桌面 02 金样例)")
    ap.add_argument("--to", default="2026-09", help="目标期号 YYYY-MM(默认 2026-09)")
    ap.add_argument("--out-dir", default="out", help="输出根目录")
    ap.add_argument("--skip-validate", action="store_true", help="只生成,不跑验证器")
    args = ap.parse_args()

    gen = Generator(Path(args.source), args.to, Path(args.out_dir))
    gen.write_csvs()
    or_n = gen.write_ors()
    zr_n = gen.write_zreads()

    vout = "(已跳过)"
    if not args.skip_validate:
        r = subprocess.run([sys.executable, str(Path(__file__).parent / "sia_validator.py"),
                            str(gen.out_dir)], capture_output=True, text=True, encoding="utf-8")
        vout = r.stdout or r.stderr
        print(vout)
    gen.write_report(or_n, zr_n, vout)
    print(f"\n生成目录: {gen.out_dir}")
    print(f"票据: OR {or_n} 张 / ZRead {zr_n} 张 | CSV {len(gen.tx_rows) - 1} + {len(gen.dt_rows) - 1} 行")
    print(f"生成报告: {gen.out_dir / '生成报告.md'}")


if __name__ == "__main__":
    main()

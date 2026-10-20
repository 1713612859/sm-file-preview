# -*- coding: utf-8 -*-
"""
sia_json_map.py —— sys_mall_sm_line 的 orderJson(orderTables 真值) → SM SIA CSV 重新映射生成器。

背景:云端 derived[] 是 APOS 旧启发式算的成品行,口径已证实有错(D04/A02/订单145 收据↔CSV 矛盾)。
本工具**不读 derived**,直接从 orderTables(ppos_sales_order/item/payment/gov_person)按冻结口径重映射。

口径(全部有定版依据):
- 恒等式:A01 Gross=Net+Tax+SVC+Disc+LessTax;A02 支付=Gross−Disc−LessTax;D02/D04 明细口径B
- Gross 列 = grossSales + serviceCharge(金样例:SVC 单 Menu 价含 svc,Gross 同口径;SVC 单商品价同步上浮)
- LessTax = lessVatAmount − addVatAmount;TotalDiscount = Gross列 − grandTotal − LessTax(残差,天然满足 A02)
- 折扣分列:Senior/PWD 各列;**NAAC+MOV 累加落第29列 National Coach/Athlete/Medal of Valor(2026-10-20 定版,
  列名语义即覆盖两类)**;manual 族按 manualDiscountCategory 落列:VIP/SMAC/EMP/ONLDEAL/REGULAR
- 负单(VOID/REFUND):原 SALE T 行金额镜像取负 + 独立新单号({KIND}{终端}{序号});明细 qty=−1、价正、
  整单金额列(金样例口径);VoidAmount=+应付、RefundAmount=−应付
- 支付码:CASH→CSH/GIFT_CHECK→GIFTCHEQUE/MASTERCARD→CCMASTERCRD/VISA→CCVISA/GCASH/MALLPAY* 原码;
  51-61 汇总列用 sia_common.classify_tender 单一事实源,55列=other+Σ信用卡(金样例怪癖)
- 明细成交价=rowNet/qty + 最大余额尾差调配(保 D02);Discount Amount=原价−成交价(口径B 含免税部分)

用法: python sia_json_map.py <rows.json> <输出目录>
"""
import json
import os
import sys
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from sia_common import classify_tender, TENDER_COL

Q = Decimal("0.01")
Z = Decimal("0.00")


def R(x) -> Decimal:
    return Decimal(str(x if x is not None else 0)).quantize(Q, rounding=ROUND_HALF_UP)


def F(d: Decimal) -> str:
    if d == 0:
        d = abs(d)  # 规避负单镜像产生的 -0.00
    return f"{d:.2f}"


# ---- 官方冻结表头(63 列带引号 / 明细 18 列不带引号,SM 2026-10-12 定稿布局) ----
TX_HEADER = [
    "Order Num / Bill Num", "Business Day", "Check Open", "Check Close", "Sales Type",
    "Transaction Type", "Void", "Void Amount", "Refund", "Refund Amount", "Guest Count",
    "Guest Count (Senior)", "Guest Count (PWD)", "Gross Sales Amount", "Net Sales Amount",
    "Total Tax", "Other/Local Tax", "Total Service Charge", "Total Tip", "Total Discount",
    "Less Tax Amount", "Tax Exempt Sales", "Regular / Other Discount Name",
    "Regular / Other Discount Amount", "Employee Discount Amount", "Senior Citizen Discount Amount",
    "VIP Discount Amount", "PWD Discount Amount",
    "National Coach / Athlete /  Medal of Valor Discount amount", "SMAC Discount Amount",
    "Online Deals Discount Name", "Online Deals Discount Amount",
    "Discount Field 1 Name", "Discount Field 2 Name", "Discount Field 3 Name",
    "Discount Field 4 Name", "Discount Field 5 Name", "Discount Field 6 Name",
    "Discount Field 1 Amount", "Discount Field 2 Amount", "Discount Field 3 Amount",
    "Discount Field 4 Amount", "Discount Field 5 Amount", "Discount Field 6 Amount",
    "Payment Type_1", "Payment Amount_1", "Payment Type_2", "Payment Amount_2",
    "Payment Type_3", "Payment Amount_3", "Total Cash Sales Amount",
    "Total Gift Cheque / Gift Card Sales Amount", "Total Debit Card Sales Amount",
    "Total E-wallet / Online Sales Amount", "Total Other Tender Sales Amount",
    "Total Mastercard Sales Amount", "Total Visa Sales Amount", "Total American Express Sales Amount",
    "Total Diners Sales Amount", "Total JCB Sales Amount", "Total Other Credit Card Sales Amount",
    "Terminal Number", "Serial Number",
]
DET_HEADER = [
    "Order Num / Bill Num", "Item ID Item Name", "Item Parent Category", "Item Category",
    "Item Sub-Category", "Item Quantity", "Transaction Item Price", "Menu Item Price",
    "Discount Code", "Discount Amount", "Modifier (1) Name", "Modifier (1) Quantity",
    "Modifier (2) Name", "Modifier (2) Quantity", "Void", "Void Amount", "Refund", "Refund Amount",
]

# 支付码/订单类型权威映射 —— 与 APOS 收银端单一事实源同步(ppos-app-v2
# smPaymentChannels.ts + constants/enums/orderType.ts,2026-10-20 核对;
# 与 sm-user/src/core/smJsonMap.ts 三方一致,上游改表须三处同步)
def _normalize_sm_code(v):
    import re
    return re.sub(r"[^A-Z0-9]", "", str(v or "").upper())[:250]

CARD_BRANDS = {"MASTERCARD": "MASTERCRD", "AMERICANEXPRESS": "AMEX", "AMEX": "AMEX",
               "VISA": "VISA", "DINERS": "DINERS", "JCB": "JCB"}
METHOD_CHANNELS = {"CASH": "CSH", "GIFTCHECK": "GIFTCHEQUE", "GIFTCHEQUE": "GIFTCHEQUE",
                   "GCASH": "GCASH", "STOREDVALUECARD": "STOREDVALUE", "MAYA": "PAYMAYA",
                   "GRABPAY": "GRABPAY", "WECHAT": "WECHATPAY", "ALIPAY": "ALIPAY",
                   "FOODPANDAPAY": "FOODPANDAPAY", "QRPH": "QRPH", "MEMBERBALANCE": "MEMBERBALANCE",
                   "ONLINE": "ONLINE", "SMAC": "SMAC", "MALLPAY01": "MALLPAY01",
                   "MALLPAY03": "MALLPAY03", "MALLPAY04": "MALLPAY04", "POINTS": "POINTS"}


def resolve_sm_code(payment_method, card_type=None, ewallet_type=None):
    method = _normalize_sm_code(payment_method)
    if not method:
        return ""
    brand = CARD_BRANDS.get(_normalize_sm_code(card_type)) or CARD_BRANDS.get(method)
    if method == "CREDITCARD" or method in CARD_BRANDS:
        return f"CC{brand}" if brand else "CCOTHER"
    if method == "DEBITCARD":
        return f"DC{brand}" if brand else "DCOTHER"
    # 独立借记品牌码(DCMASTERCARD→DCMASTERCRD,差一个 R 不能恒等;2026-10-20 定版)
    if method.startswith("DC") and method[2:] in CARD_BRANDS:
        return f"DC{CARD_BRANDS[method[2:]]}"
    if method in METHOD_CHANNELS:
        return METHOD_CHANNELS[method]
    if ewallet_type:
        w = METHOD_CHANNELS.get(_normalize_sm_code(ewallet_type))
        if w:
            return w
    return method  # 未知:归一原码恒等,桶归 other


TRX_TYPE = {1: "DINE_IN", 2: "TAKE_AWAY", 3: "FOODPANDA", 4: "GRAB", 5: "PICK_UP",
            6: "DELIVERY", 7: "IN_STORE"}  # APOS OrderTypeEnum 原形,保留下划线(2026-10-20 二次定版,避免 SM 报错)
CAT_COL = {  # manualDiscountCategory → (折扣列键, 是否带名称列)
    "VIP": ("vip", False), "SMAC": ("smac", False), "EMP": ("emp", False),
    "ONLDEAL": ("onl", True), "REGULAR": ("ro", True),
}
CC_CATS = ("mc", "visa", "amex", "diners", "jcb", "othercc")


def dts(iso: str) -> str:
    return (iso or "").replace("T", " ")[:19]


def one(x):
    """orderTables 里的表可能是 [{...}] 或 {...}。"""
    if isinstance(x, list):
        return x[0] if x else {}
    return x or {}


class Event:
    def __init__(self, row):
        self.row = row
        doc = json.loads(row["order_json"])
        ot = doc.get("orderTables") or {}
        self.ok = "ppos_sales_order" in ot
        if not self.ok:
            self.so, self.items, self.pays = {}, [], []
            return
        self.so = one(ot["ppos_sales_order"])
        self.items = ot.get("ppos_sales_order_item") or []
        self.pays = ot.get("ppos_sales_order_payment") or []
        rf = ot.get("ppos_sales_order_refund") or []
        rf0 = rf[0] if isinstance(rf, list) and rf else (rf if isinstance(rf, dict) else None)
        self.refund_head = rf0 or None
        self.refund_items = ot.get("ppos_sales_order_refund_item") or []
        self.refund_amount_c = int(R((rf0 or {}).get("refundAmount") or 0) * 100)
        self.kind = row["event_kind"]
        self.month = row["month_key"]
        self.bday = row["business_date"]
        self.etime = row["event_time"]
        self.oid = int(row["order_id"])
        self.order_no = self.so.get("orderNo") or ""
        self.terminal = str(self.so.get("terminalNo") or "").strip()
        self.serial = str(self.so.get("serialNumber") or "").replace(" ", "")

    @property
    def order_num(self) -> str:
        if self.kind == "VOID":
            return "VOID" + self.terminal + str(self.so.get("voidOrderNo") or "").zfill(16)
        if self.kind == "REFUND":
            return "REFUND" + self.terminal + str(self.so.get("returnOrderNo") or "").zfill(16)
        return "SALE" + self.terminal + self.order_no


def sale_amounts(ev: Event):
    """从 orderTables 头部推 T 行金额真值(全部恒等式闭合)。"""
    so = ev.so
    gross = R(so.get("grossSales"))                     # 商品含税额(不含 SVC)
    svc = R(so.get("serviceCharge"))
    lt = R(R(so.get("lessVatAmount")) - R(so.get("addVatAmount")))
    pay = R(so.get("grandTotal"))
    gross_col = R(gross + svc)                          # Gross 列 = 含 SVC(金样例口径)
    td = R(gross_col - pay - lt)                        # 残差(满足 A02)
    tax = R(so.get("vatAmount"))
    net = R(gross_col - tax - svc - td - lt)            # A01 残差
    # TE 口径(2026-10-18 定版:第22列折后):SC/PWD/DIPLOMAT 等政府免税族 Tax=0 时
    # TE=Net(金样例#64=214.29);其余场景(mov>0 或 Tax≠0)用 JSON 头部 vatExemptSales
    # (145/146 与收据票面同值;平单 TE=0 不受影响)
    # TE 口径(2026-10-18 折后定版,2026-10-20 扩到混合单):纯 SC/PWD 免税单
    # (Tax=0)TE=Net;混合单(Tax>0 且 LT>0 且无 MOV)TE=Net−variableSales(免税
    # 部分折后,A03 平衡,订单172 实证 550≠头部折前 612.50);MOV 单 A03 豁免,
    # TE 保持头部原值(与票面一致)
    mov_c0 = R(so.get("naacDiscountAmount")) + R(so.get("movDiscountAmount"))
    if lt > 0 and mov_c0 == 0:
        te = net if tax == 0 else R(net - R(so.get("variableSales")))
    else:
        te = R(so.get("vatExemptSales"))
    sen = R(so.get("scDiscountAmount"))
    pwd = R(so.get("pwdDiscountAmount"))
    movcol = R(R(so.get("naacDiscountAmount")) + R(so.get("movDiscountAmount")))
    disc_cols = {"sen": sen, "pwd": pwd, "mov": movcol, "vip": Z, "smac": Z, "emp": Z,
                 "onl": Z, "ro": Z, "sp": Z, "diplo": Z}
    names = {}
    rest = R(td - sen - pwd - movcol)
    manual = R(so.get("manualDiscount"))
    if rest > 0:
        key, has_name = CAT_COL.get(so.get("manualDiscountCategory") or "REGULAR", ("ro", True))
        disc_cols[key] = rest
        if has_name:
            mtype = so.get("manualDiscountType")
            if key == "onl":
                names[key] = "Online Deals"  # 金样例 #31 字面量口径,不按率生成
            elif mtype == "percent" and so.get("grossSales"):
                rate = R(Decimal(str(rest)) / Decimal(str(gross_col)) * 100)
                names[key] = f"{float(rate):g}% Discount"  # %g 防科学计数+去尾零(20 → '20')
            else:
                names[key] = "Amount Discount" if mtype == "amount" else "Discount"
        if abs(rest - manual) > Decimal("0.02"):
            print(f"  [warn] {ev.order_num}: 常规族残差 {rest} ≠ manualDiscount {manual}——以残差为准")
    elif rest < Decimal("-0.005"):
        print(f"  [warn] {ev.order_num}: 政府折扣分列和 {R(sen + pwd + movcol)} > TotalDiscount {td}")
    return {"gross": gross_col, "net": net, "tax": tax, "svc": svc, "td": td, "lt": lt, "te": te,
            "pay": pay, "disc_cols": disc_cols, "disc_names": names}


def tender_columns(pays_money):
    """pays_money: [(SM支付码, Decimal 金额)] → 51-61 列(55列=other+ΣCC 金样例怪癖)。"""
    agg = defaultdict(lambda: Z)
    for code, amt in pays_money:
        cat = classify_tender(code)
        if cat is None:
            print(f"  [warn] 无法归类的支付方式: {code}")
            cat = "other"
        agg[cat] = R(agg[cat] + amt)
    cc = R(sum((agg[c] for c in CC_CATS), Z))
    out = {}
    for cat, col in TENDER_COL.items():
        v = agg.get(cat, Z)
        out[col] = R(v + cc) if cat == "other" else v
    return out


def build_t(ev: Event, amounts, pays_money, flags):
    so = ev.so
    v = amounts
    dc, dn = v["disc_cols"], v["disc_names"]
    legs = pays_money[:3] + [("", Z)] * (3 - min(len(pays_money), 3))
    tender = tender_columns(pays_money)
    sign = -1 if flags["negative"] else 1
    neg = (lambda d: R(d * sign))
    when = dts(ev.etime) if flags["negative"] else dts(so.get("orderTime") or ev.etime)
    vals = [
        ev.order_num, ev.bday, when, when,
        "SM01", TRX_TYPE.get(so.get("orderType"), "DINE IN"),
        "1" if ev.kind == "VOID" else "0", F(R(v["pay"])) if ev.kind == "VOID" else "0.00",
        "1" if ev.kind == "REFUND" else "0", F(R(-v["pay"])) if ev.kind == "REFUND" else "0.00",
        str(so.get("totalPersons") or 1), str(so.get("scCount") or 0), str(so.get("pwdCount") or 0),
        F(neg(v["gross"])), F(neg(v["net"])), F(neg(v["tax"])), "0.00",
        F(neg(v["svc"])), "0.00", F(neg(v["td"])), F(neg(v["lt"])), F(neg(v["te"])),
        dn.get("ro", ""), F(neg(dc["ro"])), F(neg(dc["emp"])), F(neg(dc["sen"])),
        F(neg(dc["vip"])), F(neg(dc["pwd"])), F(neg(dc["mov"])), F(neg(dc["smac"])),
        dn.get("onl", ""), F(neg(dc["onl"])),
        dn.get("sp", "SP" if dc["sp"] > 0 else ""), "", "", "", "", "",
        F(neg(dc["sp"])), "0.00", "0.00", "0.00", "0.00", "0.00",
    ]
    # 注意:上面 Discount Field 1 Name 用 SP 专用;DIPLOMATIC 若出现落 Discount Field 2
    if dc["diplo"] > 0:
        vals[33] = "DIPLOMATIC"
        vals[40] = F(neg(dc["diplo"]))
    for i, (code, amt) in enumerate(legs):
        vals.append(code)
        vals.append(F(R(amt)))
    vals.extend(F(tender[c]) for c in (
        "Total Cash Sales Amount", "Total Gift Cheque / Gift Card Sales Amount",
        "Total Debit Card Sales Amount", "Total E-wallet / Online Sales Amount",
        "Total Other Tender Sales Amount", "Total Mastercard Sales Amount",
        "Total Visa Sales Amount", "Total American Express Sales Amount",
        "Total Diners Sales Amount", "Total JCB Sales Amount",
        "Total Other Credit Card Sales Amount"))
    vals.append(ev.terminal or "2")
    vals.append(ev.serial)
    assert len(vals) == 63, f"{ev.order_num}: T 值 {len(vals)} ≠ 63"
    return vals


def build_d(ev: Event, amounts):
    """SALE 明细:成交价=rowNet/qty(最大余额调配),口径B 折扣;SVC 单价格上浮。"""
    so = ev.so
    svc_rate = Decimal(0)
    if R(so.get("serviceCharge")) > 0 and R(so.get("grossSales")) > 0:
        svc_rate = R(so.get("serviceCharge")) / R(so.get("grossSales"))
    rows = []
    for it in ev.items:
        menu = R(it.get("originalPrice") or it.get("unitPrice"))
        rownet = R(it.get("rowNet"))
        if svc_rate > 0:
            menu = R(menu * (1 + svc_rate))
            rownet = R(rownet * (1 + svc_rate))
        qty = int(it.get("quantity") or 1)
        rows.append({"it": it, "menu": menu, "rownet": rownet, "qty": qty,
                     "price": R(rownet / qty) if qty else menu})
    # 确定性尾差调配(与 sm-user/smJsonMap.ts allocateUnitPrices 同源):
    # 行按 qty 降序,每行 step=trunc(diff/qty) 分,单调收敛无振荡,|残差|<min(qty)
    diff_c = int((sum((r["rownet"] for r in rows), Z) - sum((r["qty"] * r["price"] for r in rows), Z)) * 100)
    if diff_c != 0:
        for r in sorted(rows, key=lambda x: -x["qty"]):
            if diff_c == 0:
                break
            step = int(diff_c / r["qty"])  # 单位:分
            if step == 0:
                continue
            r["price"] = R(r["price"] + Decimal(step) / 100)
            diff_c -= step * r["qty"]
    out = []
    for r in rows:
        disc = R(r["menu"] - r["price"])
        if disc < 0:
            print(f"  [warn] {ev.order_num}: {r['it'].get('skuCode')} 成交价 {r['price']} > 原价 {r['menu']}(D03)")
        out.append([
            ev.order_num, f"{r['it'].get('skuCode')},{r['it'].get('productName')}",
            "SM", "SM", "SM", f"{r['qty']}.00", F(r["price"]), F(r["menu"]),
            r["it"].get("govDiscountType") or "", F(disc),
            "", "", "", "", "0", "0.00", "0", "0.00",
        ])
    return out


def build_d_negative(ev: Event, amounts):
    """VOID/REFUND 明细:qty=−1、价格取正(原单价)、整单金额列(D05 样例口径)。"""
    grand = R(amounts["pay"])
    out = []
    for it in ev.items:
        price = R(it.get("originalPrice") or it.get("unitPrice"))
        row = [
            ev.order_num, f"{it.get('skuCode')},{it.get('productName')}",
            "SM", "SM", "SM", "-1.00", F(price), F(price), "", "0.00",
            "", "", "", "",
            "1" if ev.kind == "VOID" else "0", F(grand) if ev.kind == "VOID" else "0.00",
            "1" if ev.kind == "REFUND" else "0", F(grand) if ev.kind == "REFUND" else "0.00",
        ]
        out.append(row)
    return out


def self_check(order_num, t, drows, negative=False):
    """逐单恒等式自检:A01/A02/A06/D02/D03/D04(列名查下标,防错位)。"""
    ix = {h: i for i, h in enumerate(TX_HEADER)}
    g = lambda name: Decimal(t[ix[name]])
    errs = []
    a01 = R(g("Net Sales Amount") + g("Total Tax") + g("Total Service Charge")
            + g("Total Discount") + g("Less Tax Amount"))
    if abs(a01 - g("Gross Sales Amount")) > Decimal("0.005"):
        errs.append(f"A01 {a01}≠Gross {g('Gross Sales Amount')}")
    psum = R(g("Payment Amount_1") + g("Payment Amount_2") + g("Payment Amount_3"))
    payable = R(g("Gross Sales Amount") - g("Total Discount") - g("Less Tax Amount"))
    if abs(psum - payable) > Decimal("0.02"):
        errs.append(f"A02 支付{psum}≠应付{payable}")
    parts = [g(c) for c in (
        "Regular / Other Discount Amount", "Employee Discount Amount", "Senior Citizen Discount Amount",
        "VIP Discount Amount", "PWD Discount Amount",
        "National Coach / Athlete /  Medal of Valor Discount amount", "SMAC Discount Amount",
        "Online Deals Discount Amount",
        "Discount Field 1 Amount", "Discount Field 2 Amount", "Discount Field 3 Amount",
        "Discount Field 4 Amount", "Discount Field 5 Amount", "Discount Field 6 Amount")]
    if abs(R(sum(parts)) - g("Total Discount")) > Decimal("0.02"):
        errs.append(f"A06 分列和{R(sum(parts))}≠TD {g('Total Discount')}")
    total = R(sum((Decimal(dr[5]) * Decimal(dr[6]) for dr in drows), Z))
    expect = R(abs(g("Gross Sales Amount")) - g("Other/Local Tax")
               - g("Less Tax Amount") - g("Total Discount"))
    if abs(abs(total) - expect) > Decimal("0.02"):
        errs.append(f"D02 Σ{abs(total)}≠{expect}")
    for dr in drows:
        if Decimal(dr[7]) < Decimal(dr[6]):
            errs.append(f"D03 {dr[1]} 原价<成交")
        if abs(Decimal(dr[7]) - Decimal(dr[6]) - Decimal(dr[9])) > Decimal("0.005"):
            errs.append(f"D04 {dr[1]} 折扣{dr[9]}≠原价−成交{R(Decimal(dr[7]) - Decimal(dr[6]))}")
    return errs


def main():
    rows_path, out_dir = sys.argv[1], sys.argv[2]
    rows = json.load(open(rows_path, encoding="utf-8"))
    events = []
    skipped = []
    for r in rows:
        ev = Event(r)
        if ev.ok:
            events.append(ev)
        else:
            skipped.append((r.get("order_id"), r.get("event_kind")))
    print(f"事件 {len(rows)} → 有效 {len(events)},跳过 {len(skipped)}: {skipped}")

    sales_by_no = {e.order_no: e for e in events if e.kind == "SALE"}
    events.sort(key=lambda e: (e.bday, e.etime, e.row["id"]))

    t_rows, d_rows = [], []
    all_errs = []
    for ev in events:
        if ev.kind == "SALE":
            am = sale_amounts(ev)
            pays = [(resolve_sm_code(p.get("paymentMethod"), p.get("cardType"), p.get("ewalletType")), R(p.get("amount")))
                    for p in ev.pays]
            if not pays:
                print(f"  [warn] {ev.order_num}: 无支付腿(grandTotal={am['pay']})")
                pays = [("CSH", am["pay"])]
            t = build_t(ev, am, pays, {"negative": False})
            d = build_d(ev, am)
        else:
            orig = sales_by_no.get(ev.order_no)
            if orig is None:
                print(f"  [warn] {ev.order_num}: 找不到原单 {ev.order_no},跳过")
                continue
            am = sale_amounts(orig)
            # 部分退货门禁(2026-10-20):refund 表金额或自身腿合计 ≠ 原单应付 →
            # 部分退真值映射(与 TS partialRefundTruth 同口径)
            own_sum = sum(R(p.get("amount")) for p in ev.pays)
            full_by_refund = ev.refund_amount_c == 0 or abs(ev.refund_amount_c - int(am["pay"] * 100)) <= 1
            full_by_legs = not own_sum or abs(own_sum - am["pay"]) <= 0.01
            partial = not (full_by_refund and full_by_legs) or (
                ev.refund_head and str(ev.refund_head.get("refundType") or "").upper() == "PARTIAL")
            if partial and ev.refund_head:
                rh = ev.refund_head
                svc = R(rh.get("serviceCharge"))
                gross2 = R(R(rh.get("grossSales")) + svc)
                td2 = R(rh.get("govDiscountAmountNoTax"))
                lt2 = R(R(rh.get("lessVatAmount")) - R(rh.get("addVatAmount")))
                tax2 = sum((R(x.get("vatAmount")) for x in ev.refund_items), Z)
                pay2 = R(rh.get("refundAmount"))
                net2 = R(gross2 - tax2 - svc - td2 - lt2)
                te2 = net2 if (tax2 == 0 and lt2 > 0) else R(rh.get("vatExemptSales"))
                dc = dict.fromkeys(("ro", "emp", "sen", "vip", "pwd", "mov", "smac", "onl", "sp", "diplo"), Z)
                for x in ev.refund_items:
                    t_ = str(x.get("govDiscountType") or "").upper()
                    a_ = R(x.get("govDiscountAmountNoTax"))
                    if a_ <= 0: continue
                    if t_ == "SC": dc["sen"] += a_
                    elif t_ == "PWD": dc["pwd"] += a_
                    elif t_ in ("NAAC", "MOV"): dc["mov"] += a_
                    elif t_ == "SP": dc["sp"] += a_
                    elif t_ == "DIPLOMATIC": dc["diplo"] += a_
                    else: dc["ro"] += a_
                names = {"ro": "Discount"} if dc["ro"] > 0 else {}
                # ORIGINAL:按原单腿比例分摊(最大腿收尾差)
                legs2 = []
                orig_pays = [(resolve_sm_code(p.get("paymentMethod"), p.get("cardType"), p.get("ewalletType")), R(p.get("amount"))) for p in orig.pays]
                orig_total = sum((a for _, a in orig_pays), Z)
                if orig_total > 0:
                    ranked = sorted(orig_pays, key=lambda x: -x[1])[:3]
                    alloc = Z
                    for c_, a_ in ranked:
                        sh = R(pay2 * a_ / orig_total)
                        legs2.append((c_, sh)); alloc += sh
                    if legs2: legs2[0] = (legs2[0][0], R(legs2[0][1] + pay2 - alloc))
                if not legs2: legs2 = [("CSH", pay2)]
                legs2 = [(c_, -a_) for c_, a_ in legs2]  # PY build_t 负单腿需预取负(TS 由 sgn 翻转)
                t = build_t(ev, {"gross": gross2, "net": net2, "tax": tax2, "svc": svc, "td": td2, "lt": lt2,
                                   "te": te2, "pay": pay2, "disc_cols": dc, "disc_names": names}, legs2, {"negative": True})
                t_rows.append(t)
                # D 行:refund_item 子集,价含行级 svc
                grand = pay2
                for x in ev.refund_items:
                    svc_i = R(x.get("serviceCharge"))
                    price = R(R(x.get("unitPrice")) + svc_i)
                    menu = R(R(x.get("originalPrice")) + svc_i)
                    lid = x.get("salesOrderItemId")
                    link = next((o for o in orig.items if o.get("id") == lid), None) or                            next((o for o in orig.items if o.get("productName") == x.get("productName")), None)
                    sku = x.get("skuCode") or (link or {}).get("skuCode") or ""
                    d_rows.append([ev.order_num, f"{sku},{x.get('productName') or ''}", "SM", "SM", "SM",
                                   f"-{max(1, int(x.get('quantity') or 1))}.00", F(price), F(menu),
                                   x.get("govDiscountType") or "", F(R(menu - price)),
                                   "", "", "", "", "0", "0.00", "1", F(grand)])
                print(f"  [warn] {ev.order_num}: 部分退货真值映射(refund={pay2:.2f},原单应付 {am['pay']:.2f})")
                continue
            sign = -1
            # 负单自身支付表非空则优先(支持退款渠道≠原单),空则镜像原单
            own = [(resolve_sm_code(p.get("paymentMethod"), p.get("cardType"), p.get("ewalletType")), R(R(p.get("amount")) * -1))
                   for p in ev.pays]
            own = [(c, a) for c, a in own if c]
            if own:
                pays = own
            else:
                pays = [(resolve_sm_code(p.get("paymentMethod"), p.get("cardType"), p.get("ewalletType")), R(R(p.get("amount")) * -1))
                        for p in orig.pays]
            if not pays:
                pays = [("CSH", R(-am["pay"]))]
            t = build_t(ev, am, pays, {"negative": True})
            d = build_d_negative(ev, am)
        t_rows.append(t)
        d_rows.extend(d)
        errs = self_check(ev.order_num, t, d)
        if errs:
            all_errs.append((ev.order_num, errs))

    os.makedirs(out_dir, exist_ok=True)
    tx_path = os.path.join(out_dir, "10_2026_transactions.csv")
    det_path = os.path.join(out_dir, "10_2026_transactiondetails.csv")
    q = lambda s: '"' + s + '"'
    with open(tx_path, "w", encoding="utf-8", newline="") as f:
        f.write(",".join(q(h) for h in TX_HEADER) + "\r\n")
        for t in t_rows:
            f.write(",".join(q(v) for v in t) + "\r\n")
    with open(det_path, "w", encoding="utf-8", newline="") as f:
        f.write(",".join(DET_HEADER) + "\r\n")
        for d in d_rows:
            f.write(",".join(q(v) for v in d) + "\r\n")

    print(f"\n生成: T {len(t_rows)} 行 / D {len(d_rows)} 行 → {tx_path}")
    if all_errs:
        print(f"自检失败 {len(all_errs)} 单:")
        for no, errs in all_errs[:20]:
            print(f"  {no}: {'; '.join(errs[:4])}")
        sys.exit(1)
    print("自检:A01/A02/A06/D02/D03/D04 全部通过 ✅")


if __name__ == "__main__":
    main()

# SM SIA — orderTables → CSV 字段映射总表

> 版本:2026-10-20(与 `sm-user/src/core/smJsonMap.ts`、`sm-file-review/sia_json_map.py` 双实现同源,含金样例 313 单反构对拍验证)
> 数据流:`sys_mall_sm_line.order_json.orderTables`(APOS 收银端上传真值)→ 本映射 → `transactions.csv`(63 列)/`transactiondetails.csv`(18 列)
> 权威支付/订单类型来源:`ppos-app-v2/src/services/mall/sm/smPaymentChannels.ts`、`ppos-app-v2/src/constants/enums/orderType.ts`

## 一、主表 63 列映射(transactions.csv)

| # | CSV 列名 | 来源(orderTables) | 公式 / 规则 |
|---|---|---|---|
| 1 | Order Num / Bill Num | so.orderNo / voidOrderNo / returnOrderNo + terminalNo | SALE 单:`SALE{终端}{16位序号}`;VOID:`VOID{终端}{voidOrderNo 16位}`;REFUND:`REFUND{终端}{returnOrderNo 16位}` |
| 2 | Business Day | 行 business_date | 原样 |
| 3 | Check Open | so.orderTime(缺省行 eventTime) | `T`→空格,YYYY-MM-DD HH:mm:ss |
| 4 | Check Close | 同 #3 | 同 #3(负单用负事件自身的 eventTime) |
| 5 | Sales Type | — | **SM01**(固定;金样例 313 单全 SM01,SM02/03 属 S17/S18 补测) |
| 6 | Transaction Type | so.orderType(枚举见 §四) | 1=DINE IN … 7=IN STORE,未知档 DINE IN |
| 7 | Void | — | VOID 事件=1,其余=0 |
| 8 | Void Amount | — | VOID 时 = **+grandTotal**(正数),其余 0.00 |
| 9 | Refund | — | REFUND 事件=1,其余=0 |
| 10 | Refund Amount | — | REFUND 时 = **−grandTotal**(负数) |
| 11 | Guest Count | so.totalPersons | 缺省/0 时兜底 1 |
| 12 | Guest Count (Senior) | so.scCount | 原样 |
| 13 | Guest Count (PWD) | so.pwdCount | 原样 |
| 14 | Gross Sales Amount | so.grossSales + so.serviceCharge | **Gross 列 = 商品含税额 + 服务费**(金样例口径;负单整体取负) |
| 15 | Net Sales Amount | 恒等式残差 | = Gross(#14) − TotalTax − SVC − TD − LT(A01 闭合) |
| 16 | Total Tax | so.vatAmount | 原样(服务费不另计税,税额为商品税) |
| 17 | Other/Local Tax | — | **0.00**(固定;app 不产地方税) |
| 18 | Total Service Charge | so.serviceCharge | 原样 |
| 19 | Total Tip | — | 0.00 |
| 20 | Total Discount | 残差 | = Gross(#14) − grandTotal − LessTax(#21)(A02 闭合) |
| 21 | Less Tax Amount | so.lessVatAmount − so.addVatAmount | VAT 对冲净额(SC 免税型=全额减税;MOV 型对冲后=0) |
| 22 | Tax Exempt Sales | so.vatExemptSales | **免税族(Tax=0 且 LT>0)取 #15 Net 折后**(2026-10-18 定版,金样例#64=214.29);其余用头部原值 |
| 23 | Regular / Other Discount Name | manual 族 | REGULAR 类:percent→"N% Discount"(如 20% Discount)、amount→"Amount Discount" |
| 24 | Regular / Other Discount Amount | manual 残差(REGULAR) | 见 §五分列规则 |
| 25 | Employee Discount Amount | manual 残差(EMP) | 同上 |
| 26 | Senior Citizen Discount Amount | so.scDiscountAmount | 原样 |
| 27 | VIP Discount Amount | manual 残差(VIP) | 同上 |
| 28 | PWD Discount Amount | so.pwdDiscountAmount | 原样 |
| 29 | National Coach / Athlete / Medal of Valor Discount amount | so.naacDiscountAmount + so.movDiscountAmount | **NAAC+MOV 累加**(2026-10-20 定版:列名语义即覆盖 NAAC 教练/运动员 与 MOV 英勇勋章两类) |
| 30 | SMAC Discount Amount | manual 残差(SMAC) | 同上 |
| 31 | Online Deals Discount Name | — | 残差(ONLDEAL)>0 时写字面量 **"Online Deals"**(2026-10-20 用户定版;金样例 #31×3 同口径,不按率生成) |
| 32 | Online Deals Discount Amount | manual 残差(ONLDEAL) | 同上 |
| 33 | Discount Field 1 Name | so.spDiscountAmount>0 | "SP" |
| 34 | Discount Field 2 Name | so.diplomatDiscountAmount>0 | "DIPLOMATIC" |
| 35–38 | Discount Field 3–6 Name | — | 空 |
| 39 | Discount Field 1 Amount | so.spDiscountAmount | 原样 |
| 40 | Discount Field 2 Amount | so.diplomatDiscountAmount | 原样 |
| 41–44 | Discount Field 3–6 Amount | — | 0.00 |
| 45–50 | Payment Type/Amount 1–3 | ppos_sales_order_payment | resolveSmCode(§三)后取**前 3 腿**;超过 3 腿截断并告警(format-cap);无腿兜底 CSH=grandTotal+告警 |
| 51 | Total Cash Sales Amount | 全部腿归类 | classifyTender→cash;负单镜像取负(严格口径) |
| 52 | Total Gift Cheque / Gift Card | 同上 | →gc |
| 53 | Total Debit Card | 同上 | →debit(DC 前缀;**不进品牌列、不双计**) |
| 54 | Total E-wallet / Online | 同上 | →ewallet(GCASH/PAYMAYA/MAYA/WECHATPAY/ALIPAY/QRPH/GRABPAY/FOODPANDAPAY/STOREDVALUE/MEMBERBALANCE/ONLINE) |
| 55 | Total Other Tender | 同上 | **other + Σ信用卡(#56–61)**(金样例怪癖:信用卡双计) |
| 56–60 | Mastercard / Visa / Amex / Diners / JCB | 同上 | CC 品牌各自桶 |
| 61 | Total Other Credit Card | 同上 | othercc |
| 62 | Terminal Number | so.terminalNo | 原样 |
| 63 | Serial Number | so.serialNumber | 去空格 |

## 二、明细 18 列映射(transactiondetails.csv)

| # | CSV 列名 | 来源 | 公式 / 规则 |
|---|---|---|---|
| 1 | Order Num / Bill Num | — | 同主表 #1 |
| 2 | Item ID Item Name | it.skuCode + it.productName | `"SKU,品名"` 合并单值(SM 2026-10-12 定稿布局) |
| 3 | Item Parent Category | — | SM |
| 4 | Item Category | — | SM |
| 5 | Item Sub-Category | — | SM |
| 6 | Item Quantity | it.quantity | 原样;负单行固定 **−1.00**(符号由数量承载,金样例形态) |
| 7 | Transaction Item Price(成交价) | it.rowNet | = scaleUp(rowNet)÷qty + 确定性尾差调配(§六);负单行 = 原单价(正数) |
| 8 | Menu Item Price(原价) | it.originalPrice(缺省 unitPrice) | scaleUp 后;负单行 = 原单价 |
| 9 | Discount Code | it.govDiscountType | SC / PWD / MOV / DIPLOMATIC… 原样 |
| 10 | Discount Amount | — | = 原价 − 成交价(**口径B,含免税部分**,00文档§12;×qty 合计 = TD+LT) |
| 11–14 | Modifier (1)(2) Name/Quantity | — | 全空 |
| 15 | Void | — | VOID 行=1 |
| 16 | Void Amount | — | VOID 行 = +grandTotal(**整单口径**,每行同值,金样例 D05) |
| 17 | Refund | — | REFUND 行=1 |
| 18 | Refund Amount | — | REFUND 行 = +grandTotal(整单口径;主表 #10 为负,两列符号口径不同均为金样例形态) |

## 三、支付码映射(POS → SM 标准码)

| POS 支付码 | SM 上报码 | 汇总桶(#51–61) |
|---|---|---|
| CASH | CSH | 51 cash |
| WECHAT | WECHATPAY | 54 ewallet |
| ALIPAY | ALIPAY | 54 |
| GCASH | GCASH | 54 |
| MAYA | PAYMAYA | 54 |
| QRPH | QRPH | 54 |
| GRAB_PAY | GRABPAY | 54 |
| FOODPANDA_PAY | FOODPANDAPAY | 54 |
| STORED_VALUE_CARD | STOREDVALUE | 54 |
| MEMBER_BALANCE | MEMBERBALANCE | 54 |
| GIFT_CHECK | GIFTCHEQUE | 52 gc |
| POINTS | POINTS | 55 other |
| SMAC | SMAC | 55 other |
| MALLPAY01–04 | 恒等 | 55 other |
| MASTERCARD | **CCMASTERCRD** | 56 mc(+55 双计) |
| VISA | CCVISA | 57 visa(+55 双计) |
| AMEX | CCAMEX | 58(+55 双计) |
| DINERS | CCDINERS | 59(+55 双计) |
| JCB | CCJCB | 60(+55 双计) |
| CREDIT_CARD(无品牌) | CCOTHER | 61(+55 双计) |
| CREDIT_CARD + cardType | CC{品牌段} | 对应品牌桶(+55 双计) |
| DEBIT_CARD(无品牌) | DCOTHER | 53 debit(不双计) |
| DEBIT_CARD + cardType | DC{品牌段} | 53 debit |
| **DCMASTERCARD** | **DCMASTERCRD**(2026-10-20 定版,差一个 R 不得恒等) | 53 debit |
| E_WALLET + ewalletType | 按 ewalletType 细分(如 GCash→GCASH) | 54 |
| 未知码 | 归一原码恒等(大写+剔非字母数字) | 55 other |

> 品牌段拼写依已认证金样例:CCMASTERCRD×78 / DCMASTERCRD×107。
> 51–61 汇总按**全部支付腿**归类(含超出 #45–50 三腿上限的腿)。

## 四、订单类型(so.orderType → #6)

> **定版(2026-10-20 用户二次确认):#6 保留 app 枚举下划线原形(DINE_IN/TAKE_AWAY 等),避免 SM 报错**——曾实施"去下划线"后撤销;管线原「#6 去下划线」步已移除。负单事件同样按 orderType 输出(不写 VOID/REFUND 字样,金样例该形态仅 ETECH 呈现)。

| orderType | 枚举 | CSV #6 输出(=枚举原形,含下划线) |
|---|---|---|
| 1 | DINE_IN | DINE_IN |
| 2 | TAKE_AWAY | TAKE_AWAY |
| 3 | FOODPANDA | FOODPANDA |
| 4 | GRAB | GRAB |
| 5 | PICK_UP | PICK_UP |
| 6 | DELIVERY | DELIVERY |
| 7 | IN_STORE | IN_STORE |

## 五、折扣分列规则(manual 残差)

```
残差 rest = TotalDiscount(#20) − SC列(#26) − PWD列(#28) − 第29列(#29,NAAC+MOV) − SP(#39) − DIPLOMAT(#40)
rest > 0 → 按 manualDiscountCategory 落列:
  VIP → #27 | SMAC → #30 | EMP → #25 | ONLDEAL → #31/32(名"Online Deals") | REGULAR → #23/24
rest < 0 → 记 adjusted 告警(分列合计超 TD,头部金额矛盾信号)
```

## 六、服务费与尾差

- **服务费基数双口径自适应**(SM 反馈 2026-10-20 允许商品含税×率,app 引擎现行;金样例为净额×率):映射按头部真值残差,两种基数均恒等式闭合。
- SVC 单商品价统一上浮:×(商品额+服务费)/商品额,使 D02(Σ成交价 = Gross−LT−TD)闭合。
- 明细单价尾差:rowNet÷qty(HALF_UP)后按 qty 降序逐行 `trunc(diff/qty)` 分调整——确定性收敛,无振荡,含 qty=1 行必归零。

## 七、负单(VOID / REFUND)

- 独立新单号(#1),金额 = 原 SALE 各列**镜像取负**(#14/15/16/18/20/21/22 及折扣列、支付腿、51–61);
- #8=+应付 / #10=−应付;明细 qty=−1、价格取正、#16/#18 整单金额(金样例 D05 口径);
- 原单索引 =(terminalNo, orderNo);同键多候选取同业务日最早并告警;缺原单→整事件回退 derived 并告警。

## 八、校验、回退与告警

- **恒等式自检**(每单内置):A01 Gross=Net+Tax+SVC+TD+LT;A02 支付=Gross−TD−LT;A06 TD=分列和;D02 Σ(qty×成交价)=|Gross|−LT−TD;D03 成交≤原价;D04 折扣=原价−成交。
- **结构性不可用回退**(整事件回退 derived 旧行 + 告警):orderTables 缺失/损坏、orderNo 缺失、头部金额非法(gross/grandTotal 负、TD 残差为负、支付超毛额)、未知事件类型、负单缺同批原单。
- **行级告警**:坏明细行剔除(row-skipped)、无支付腿兜底 CSH(adjusted)、支付腿>3 截断(format-cap)。
- 验收基线:161 真实事件 ERROR=0;金样例 313 单反构对拍 0 差异 ERROR=0;TS/Python 双实现逐字节一致。

## 附:金样例呈现形态差异(验证器双绿,demo 产 app 形态)

| 项 | 金样例(ETECH) | 本映射(app 形态) |
|---|---|---|
| #1 单号 | 裸序号(1…313) | 组合号 SALE+终端+16位序号 |
| #6 交易类型 | Dine-in / VOID / REFUND | DINE_IN 等(枚举原形,**保留下划线**,2026-10-20 二次定版) |
| 负单 51–61 | 宽松(现金 0、Other 整额) | 严格负数(更规范,消 A07N) |
| 服务费呈现 | 214 型藏 Other/Local Tax | SVC 独立列(#18) |

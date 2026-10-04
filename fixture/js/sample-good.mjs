// 干净样本：不应产生任何发现。
export function calcTotal(items) {
  let total = 0;
  for (const it of items) {
    if (it.active === true) {
      total += it.price * it.qty;
    }
  }
  return Math.round(total * 100) / 100;
}

export async function fetchPrice(sku) {
  const res = await fetch(`https://api.example.com/price/${sku}`);
  if (res.status !== 200) {
    throw new Error(`price lookup failed for ${sku}`);
  }
  return res.json();
}

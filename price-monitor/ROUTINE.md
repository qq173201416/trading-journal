# PC parts price monitor (daily routine)

Run by a scheduled task once a day at 00:20 America/Los_Angeles, right after the
midnight-PT turnover when Newegg/Amazon daily deals and most US retailers'
overnight repricing go live.

## Steps

1. Read `watchlist.json` (items, trusted sellers, alert rules) and `history.jsonl`.
2. For each item, use WebSearch (and WebFetch where it works) to find today's
   **new-condition** price at the trusted sellers only. Direct curl to retailers
   is blocked by the container proxy, so rely on WebSearch/WebFetch.
   Also check deal aggregators (slickdeals.net, r/buildapcsales, 9to5toys,
   Tom's Hardware deals) for *leads*, but only count a price once it points to a
   trusted seller. Use camelcamelcamel / PCPartPicker price-history pages when
   reachable to update the all-time low.
3. Reject: used, refurbished, renewed, open-box, Amazon/Newegg/Walmart
   3rd-party marketplace sellers, eBay, AliExpress, Temu, unknown shops,
   wrong model variants (see each item's `match`), prices that need a
   membership you can't verify, and anything that looks like a listing error.
4. Append one line per item to `history.jsonl`:
   `{"date":"YYYY-MM-DD","id":"ssd","price":149.99,"seller":"Amazon","url":"...","in_stock":true}`
   (use `"price":null` if no trustworthy price was found). If a new all-time low
   is confirmed, update `known_low` / `known_low_note` in `watchlist.json`.
5. Alert if any item meets `alert_rules` (new low, within 3% of the known low,
   or >= 15% below MSRP / 30-day median). Then send ONE Telegram message with
   `python3 price-monitor/notify.py "<text>"`, in Chinese, e.g.:

   ```
   🔥 装机价格提醒 2026-10-23
   Samsung 990 PRO 2TB  $129.99 @ Amazon（历史新低，原低 $134）
   https://...
   ```

   If nothing qualifies, do NOT send anything.
6. Commit `price-monitor/` changes and push.

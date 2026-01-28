# taiwan_stock_rss_to_manus_json.py
# 完全自動 / 無料 / API不要

import feedparser
import json
from datetime import datetime, timedelta

# =========================
# 設定
# =========================

STOCKS = {
    "2330": ["台積電", "TSMC"],
    "2451": ["創見"],
    "8271": ["宇瞻"],
    "2382": ["廣達", "Quanta"]
}

RSS_FEEDS = [
    "https://tw.stock.yahoo.com/rss",
    "https://www.cna.com.tw/rss.aspx",
    "https://ctee.com.tw/feed",
    "https://udn.com/rssfeed/news/2/6645"
]

# 検索期間（最大30日）
DAYS_RANGE = 30

OUTPUT_FILE = "manus_input.json"

# =========================
# RSS取得
# =========================

def fetch_all_entries():
    entries = []
    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        entries.extend(feed.entries)
    return entries


def within_days(entry, days):
    if not hasattr(entry, "published_parsed"):
        return False
    published = datetime(*entry.published_parsed[:6])
    return published >= datetime.now() - timedelta(days=days)


# =========================
# 銘柄別ニュース抽出
# =========================

def extract_stock_news(entries):
    result = []

    for stock_code, keywords in STOCKS.items():
        stock_news = []

        for e in entries:
            if not within_days(e, DAYS_RANGE):
                continue

            title = e.get("title", "")
            link = e.get("link", "")

            if any(k in title for k in keywords):
                stock_news.append({
                    "title_zh": title,
                    "url": link,
                    "published": e.get("published", "")
                })

        # 必ず1本は保証（最悪でも空配列は渡さない）
        if not stock_news:
            stock_news.append({
                "title_zh": "該当期間内の重要ニュースは確認されませんでした",
                "url": "",
                "published": ""
            })

        result.append({
            "stock_code": stock_code,
            "news": stock_news
        })

    return result


# =========================
# メイン処理
# =========================

def main():
    entries = fetch_all_entries()
    data = extract_stock_news(entries)

    manus_payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "RSS auto collection",
        "stocks": data
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(manus_payload, f, ensure_ascii=False, indent=2)

    print(f"✅ manus入力用JSONを生成しました: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

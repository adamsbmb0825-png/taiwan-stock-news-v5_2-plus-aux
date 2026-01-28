import os
import feedparser
import requests
from datetime import datetime, timedelta
import pytz
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# =========================
# 設定
# =========================

TZ = pytz.timezone("Asia/Taipei")

STOCKS = {
    "2330": "台積電",
    "2451": "創見",
    "8271": "宇瞻",
    "2382": "廣達"
}

RSS_TEMPLATES = [
    "https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
]

HEADERS = {"User-Agent": "Mozilla/5.0"}

# =========================
# ユーティリティ
# =========================

def translate_title_zh_to_ja(title_zh: str) -> str:
    """
    AIを使わない簡易翻訳（投資向け用語辞書）
    """
    table = {
        "台積電": "TSMC",
        "美國": "米国",
        "中國": "中国",
        "半導體": "半導体",
        "需求": "需要",
        "營收": "売上",
        "下滑": "減少",
        "成長": "成長",
        "市場": "市場",
        "投資": "投資",
        "財報": "決算"
    }
    ja = title_zh
    for k, v in table.items():
        ja = ja.replace(k, v)
    return ja

def fetch_news(stock_code, stock_name):
    now = datetime.now(TZ)
    periods = [
        ("today", now - timedelta(days=1)),
        ("weekly", now - timedelta(days=7)),
        ("monthly", now - timedelta(days=30)),
    ]

    for label, since in periods:
        query = f"{stock_name} {stock_code} 股票"
        rss_url = RSS_TEMPLATES[0].format(query=query)
        feed = feedparser.parse(rss_url)

        results = []
        for entry in feed.entries:
            if not hasattr(entry, "published"):
                continue
            published = datetime(*entry.published_parsed[:6], tzinfo=pytz.UTC).astimezone(TZ)
            if published >= since:
                results.append({
                    "title_zh": entry.title,
                    "title_ja": translate_title_zh_to_ja(entry.title),
                    "url": entry.link,
                    "published": published.strftime("%Y-%m-%d %H:%M")
                })

        if results:
            return label, results

    # それでも無ければ「月内ダミー」
    return "monthly", [{
        "title_zh": "該当期間内に確認可能な主要ニュースはありませんでした",
        "title_ja": "直近1か月間に特筆すべきニュースは確認されませんでした",
        "url": "https://news.google.com/",
        "published": now.strftime("%Y-%m-%d %H:%M")
    }]

# =========================
# メール生成
# =========================

def build_html(news_map):
    html = f"""
    <h1>📈 台湾株ニュース配信</h1>
    <p>配信日時：{datetime.now(TZ).strftime('%Y-%m-%d %H:%M')}</p>
    <hr>
    """

    for code, data in news_map.items():
        html += f"<h2>{data['name']}（{code}）</h2>"
        html += f"<p><b>分類：</b>{data['category']}</p>"

        for n in data["news"]:
            html += f"""
            <p>
            <b>{n['title_ja']}</b><br>
            <a href="{n['url']}">{n['title_zh']}</a><br>
            <small>{n['published']}</small>
            </p>
            """

        html += """
        <p>📊 投資判断補助（株価フェーズ整理）</p>
        <ul>
            <li>短期材料として注目</li>
            <li>市場反応を確認</li>
            <li>初動は慎重に</li>
        </ul>
        <hr>
        """

    return html

# =========================
# メール送信
# =========================

def send_email(html):
    api_key = os.environ.get("SENDGRID_API_KEY")
    mail_from = os.environ.get("SENDGRID_FROM")
    mail_to = os.environ.get("SENDGRID_TO")

    if not api_key or not mail_from or not mail_to:
        print("❌ SendGrid 環境変数が不足しています")
        return

    message = Mail(
        from_email=mail_from,
        to_emails=mail_to,
        subject="📈 台湾株ニュース配信",
        html_content=html
    )

    sg = SendGridAPIClient(api_key)
    response = sg.send(message)
    print("✅ メール送信完了", response.status_code)

# =========================
# メイン
# =========================

def main():
    news_map = {}

    for code, name in STOCKS.items():
        category, news = fetch_news(code, name)
        news_map[code] = {
            "name": name,
            "category": category,
            "news": news
        }

    html = build_html(news_map)
    send_email(html)

if __name__ == "__main__":
    main()

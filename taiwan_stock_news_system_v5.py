# =====================================================
# Taiwan Stock News System v5 FINAL+
# AI不使用 / 段階探索 / 1銘柄1ニュース保証
# =====================================================

import os
import feedparser
import pytz
from datetime import datetime, timedelta
from urllib.parse import unquote
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# ---------------------
# 基本設定
# ---------------------

TZ = pytz.timezone("Asia/Taipei")
NOW = datetime.now(TZ)

RSS_FEEDS = [
    "https://tw.stock.yahoo.com/rss",
    "https://www.moneydj.com/kmdj/rss",
    "https://www.cna.com.tw/rss/aeco.xml",
]

STOCKS = {
    "2330": {"name": "台積電", "keywords": ["台積電", "TSMC", "2330"]},
    "2451": {"name": "創見", "keywords": ["創見", "Transcend", "2451"]},
    "8271": {"name": "宇瞻", "keywords": ["宇瞻", "Apacer", "8271"]},
    "2382": {"name": "廣達", "keywords": ["廣達", "Quanta", "2382"]},
}

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
SENDGRID_FROM = os.getenv("SENDGRID_FROM")
SENDGRID_TO = os.getenv("SENDGRID_TO")

# ---------------------
# ニュース取得
# ---------------------

def fetch_news():
    articles = []
    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        for e in feed.entries:
            try:
                published = datetime(*e.published_parsed[:6], tzinfo=TZ)
            except:
                continue

            articles.append({
                "title": e.title,
                "link": e.link,
                "published": published
            })
    return articles


def in_range(article, days):
    return article["published"] >= NOW - timedelta(days=days)


def match(article, keywords):
    text = article["title"]
    return any(k in text for k in keywords)


def clean_title(title):
    return unquote(title).strip()

# ---------------------
# 投資判断補助（固定ロジック）
# ---------------------

def investment_phase(range_label):
    if range_label == "today":
        return [
            "短期材料として注目",
            "市場反応を確認",
            "初動は慎重に"
        ]
    if range_label == "weekly":
        return [
            "中立〜ややポジティブ",
            "短期ボラティリティ低下",
            "押し目候補"
        ]
    if range_label == "monthly":
        return [
            "中長期視点で整理",
            "材料は織り込み済み",
            "レンジ意識"
        ]
    return [
        "材料不足",
        "様子見フェーズ",
        "無理なエントリー不要"
    ]

# ---------------------
# HTML生成
# ---------------------

def build_html(result):
    html = f"""
    <h1>📈 台湾株ニュース配信</h1>
    <p>配信日時：{NOW.strftime('%Y-%m-%d %H:%M')}</p>
    <hr>
    """

    for code, d in result.items():
        html += f"<h2>{d['name']}（{code}）</h2>"

        if d["news"]:
            n = d["news"]
            html += f"""
            <p>
            <strong>
            <a href="{n['link']}">{n['title']}</a>
            </strong><br>
            <small>分類：{d['range']}</small>
            </p>
            """
        else:
            html += "<p>該当ニュースは見つかりませんでした。</p>"

        html += "<h3>📊 投資判断補助（株価フェーズ整理）</h3><ul>"
        for line in d["phase"]:
            html += f"<li>{line}</li>"
        html += "</ul><hr>"

    return html

# ---------------------
# メール送信
# ---------------------

def send_mail(html):
    if not SENDGRID_API_KEY:
        print("SendGrid API Key 未設定")
        return

    msg = Mail(
        from_email=SENDGRID_FROM,
        to_emails=SENDGRID_TO,
        subject="📈 台湾株ニュース配信",
        html_content=html
    )

    sg = SendGridAPIClient(SENDGRID_API_KEY)
    sg.send(msg)

# ---------------------
# メイン
# ---------------------

def main():
    print("台湾株ニュース配信 v5 FINAL+")

    articles = fetch_news()
    result = {}

    for code, s in STOCKS.items():
        selected = None
        selected_range = None

        for label, days in [("today", 1), ("weekly", 7), ("monthly", 30)]:
            for a in articles:
                if in_range(a, days) and match(a, s["keywords"]):
                    selected = {
                        "title": clean_title(a["title"]),
                        "link": a["link"]
                    }
                    selected_range = label
                    break
            if selected:
                break

        result[code] = {
            "name": s["name"],
            "news": selected,
            "range": selected_range,
            "phase": investment_phase(selected_range)
        }

    html = build_html(result)
    send_mail(html)

if __name__ == "__main__":
    main()

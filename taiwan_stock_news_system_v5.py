# ============================================
# Taiwan Stock News System v5 (FINAL)
# AI不使用 / ルールベース / 定期配信用
# ============================================

import os
import feedparser
import requests
import re
import json
from datetime import datetime, timedelta
import pytz
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# =========================
# 設定
# =========================

TIMEZONE = pytz.timezone("Asia/Taipei")
TODAY = datetime.now(TIMEZONE)

RSS_FEEDS = [
    "https://tw.stock.yahoo.com/rss",
    "https://www.moneydj.com/kmdj/rss",
    "https://www.cna.com.tw/rss/aeco.xml",
    "https://www.cna.com.tw/rss/afe.xml",
]

STOCKS = {
    "2330": {
        "name": "台積電",
        "keywords": ["台積電", "TSMC", "2330", "晶圓", "先進製程", "CoWoS"]
    },
    "2451": {
        "name": "創見",
        "keywords": ["創見", "Transcend", "2451", "記憶體", "Flash"]
    },
    "8271": {
        "name": "宇瞻",
        "keywords": ["宇瞻", "Apacer", "8271", "DRAM", "Flash"]
    },
    "2382": {
        "name": "廣達",
        "keywords": ["廣達", "Quanta", "2382", "伺服器", "AI伺服器"]
    },
}

# =========================
# SendGrid
# =========================

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY")
SENDGRID_FROM = os.environ.get("SENDGRID_FROM")
SENDGRID_TO = os.environ.get("SENDGRID_TO")

# =========================
# ユーティリティ
# =========================

def fetch_all_news():
    articles = []
    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        for e in feed.entries:
            published = None
            if hasattr(e, "published"):
                try:
                    published = datetime(*e.published_parsed[:6], tzinfo=TIMEZONE)
                except:
                    pass
            articles.append({
                "title": e.title,
                "summary": getattr(e, "summary", ""),
                "link": e.link,
                "published": published
            })
    return articles


def is_recent(article, days=3):
    if not article["published"]:
        return False
    return article["published"] >= TODAY - timedelta(days=days)


def match_stock(article, keywords):
    text = article["title"] + article["summary"]
    for kw in keywords:
        if kw in text:
            return True
    return False


def classify_news(text):
    text = text.lower()
    if any(k in text for k in ["下修", "衰退", "減產", "裁員"]):
        return "negative"
    if any(k in text for k in ["投資", "擴產", "資本支出", "建廠"]):
        return "capex"
    if any(k in text for k in ["營收", "財報", "獲利", "展望"]):
        return "earnings"
    return "neutral"


def build_investment_phase(news_list):
    if not news_list:
        return [
            "市場は様子見フェーズ",
            "短期ボラティリティ低下",
            "中長期では押し目監視"
        ]

    types = [n["type"] for n in news_list]

    if "negative" in types:
        return [
            "短期的な調整リスク",
            "不透明感が残る状況",
            "反発には材料待ち"
        ]

    if "capex" in types or "earnings" in types:
        return [
            "中長期ではポジティブ",
            "事業成長への期待",
            "押し目は検討余地あり"
        ]

    return [
        "材料は限定的",
        "方向感に欠ける展開",
        "様子見継続"
    ]


def render_html(result):
    html = f"""
    <h1>📈 台湾株ニュース配信</h1>
    <p>配信日時：{TODAY.strftime('%Y-%m-%d %H:%M')}</p>
    <hr>
    """

    for code, data in result.items():
        html += f"<h2>{data['name']}（{code}）</h2>"

        if not data["news"]:
            html += "<p>本日は配信対象となる新規ニュースはありませんでした。</p>"
        else:
            for n in data["news"]:
                html += f"""
                <p>
                <strong>{n['title']}</strong><br>
                <a href="{n['link']}">{n['link']}</a>
                </p>
                """

        html += "<h3>📊 投資判断補助（株価フェーズ整理）</h3><ul>"
        for line in data["phase"]:
            html += f"<li>{line}</li>"
        html += "</ul><hr>"

    return html


def send_email(html):
    if not SENDGRID_API_KEY or not SENDGRID_FROM or not SENDGRID_TO:
        print("❌ SendGrid 環境変数不足")
        return

    message = Mail(
        from_email=SENDGRID_FROM,
        to_emails=SENDGRID_TO,
        subject="📈 台湾株ニュース配信",
        html_content=html
    )

    sg = SendGridAPIClient(SENDGRID_API_KEY)
    response = sg.send(message)
    print("✅ メール送信完了", response.status_code)


# =========================
# メイン処理
# =========================

def main():
    print("台湾株ニュース配信システム v5（AI不使用・最終版）")

    articles = fetch_all_news()
    articles = [a for a in articles if is_recent(a)]

    result = {}

    for code, stock in STOCKS.items():
        matched = []
        for a in articles:
            if match_stock(a, stock["keywords"]):
                matched.append({
                    "title": a["title"],
                    "link": a["link"],
                    "type": classify_news(a["title"] + a["summary"])
                })

        phase = build_investment_phase(matched)

        result[code] = {
            "name": stock["name"],
            "news": matched,
            "phase": phase
        }

    html = render_html(result)
    send_email(html)


if __name__ == "__main__":
    main()

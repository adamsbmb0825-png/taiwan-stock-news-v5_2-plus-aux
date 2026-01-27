import os
import feedparser
from datetime import datetime
import pytz
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# =============================
# 設定（コード内にキーは書かない）
# =============================

TIMEZONE = pytz.timezone("Asia/Taipei")

STOCKS = [
    {"code": "2330", "name": "台積電"},
    {"code": "2451", "name": "創見"},
    {"code": "8271", "name": "宇瞻"},
    {"code": "2382", "name": "廣達"},
]

RSS_FEEDS = [
    "https://www.cnyes.com/rss/news",
    "https://tw.stock.yahoo.com/rss",
]

# =============================
# Gemini（APIキーは環境変数）
# =============================

def gemini_judge_relevance(stock_name, title, summary):
    """
    Geminiに「このニュースは株価判断に重要か？」をYes/Noで聞く
    """
    import google.generativeai as genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return False

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-pro")

    prompt = f"""
以下のニュースが「{stock_name}」の株価判断に重要か？
Yes か No のみで答えよ。

ニュースタイトル:
{title}

本文要約:
{summary}
"""

    try:
        response = model.generate_content(prompt)
        return "yes" in response.text.lower()
    except Exception:
        return False


# =============================
# メール送信（SendGrid）
# =============================

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
        subject="🇹🇼 台湾株ニュース配信",
        html_content=html
    )

    sg = SendGridAPIClient(api_key)
    sg.send(message)
    print("✅ メール送信成功")


# =============================
# メイン処理
# =============================

def main():
    print("台湾株ニュース配信システム v5.2 (Gemini版)")

    delivery = []

    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:20]:
            title = entry.get("title", "")
            summary = entry.get("summary", "")

            for stock in STOCKS:
                if stock["name"] in title:
                    important = gemini_judge_relevance(
                        stock["name"], title, summary
                    )
                    if important:
                        delivery.append(f"<li><b>{stock['name']}</b>: {title}</li>")

    if not delivery:
        print("⚠️ 配信ニュースなし")
        return

    now = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M")
    html = f"""
    <h2>🇹🇼 台湾株ニュース ({now})</h2>
    <ul>
    {''.join(delivery)}
    </ul>
    """

    send_email(html)


if __name__ == "__main__":
    main()

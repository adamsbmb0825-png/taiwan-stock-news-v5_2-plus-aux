#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
台湾株ニュース配信システム v5.3-stable
- AI API 完全不使用
- ルールベース判定
- 投資判断補助ニュース必ず1本生成
- 無料・定期実行可能
"""

VERSION = "v5.3-stable-no-ai-202601"

import os
import feedparser
import requests
import json
import hashlib
import re
from datetime import datetime, timedelta
import pytz
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# =========================
# 基本設定
# =========================

TW_TZ = pytz.timezone("Asia/Taipei")

RSS_FEEDS = [
    "https://news.google.com/rss/search?q=台積電&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=創見&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=宇瞻&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=廣達&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
]

KEYWORDS_SCORE = {
    "營收": 5,
    "法說": 5,
    "EPS": 5,
    "接單": 4,
    "出貨": 4,
    "AI": 3,
    "半導體": 3,
    "伺服器": 3,
    "擴產": 4,
    "下修": -3,
    "衰退": -4,
}

# =========================
# 銘柄情報
# =========================

def load_stocks():
    with open("stocks.json", encoding="utf-8") as f:
        return json.load(f)["stocks"]

STOCKS = load_stocks()

# =========================
# ニュース収集
# =========================

def normalize(text):
    return re.sub(r"\s+", " ", text.lower())

def score_news(news, stock_name):
    score = 0
    text = normalize(news["title"] + " " + news.get("summary", ""))
    if stock_name.lower() in text:
        score += 3
    for k, v in KEYWORDS_SCORE.items():
        if k.lower() in text:
            score += v
    return score

def collect_news():
    all_news = []
    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        for e in feed.entries[:20]:
            all_news.append({
                "title": e.title,
                "link": e.link,
                "summary": getattr(e, "summary", ""),
                "published": getattr(e, "published", "")
            })
    return all_news

# =========================
# 投資判断補助（必ず1本）
# =========================

def generate_investment_aux(stock_name, news_count):
    if news_count >= 5:
        phase = "上昇トレンド継続"
    elif news_count >= 2:
        phase = "材料待ち・持ち合い"
    else:
        phase = "調整局面・様子見"

    return {
        "title": "📉 投資判断補助（株価フェーズ整理）",
        "summary": f"{stock_name}に関する直近ニュース量から判断すると、現在は「{phase}」の可能性が高い局面です。",
        "analysis": "本項目は売買を推奨するものではなく、ニュース量と方向性を整理する補助情報です。",
        "is_aux": True,
    }

# =========================
# メイン処理
# =========================

def main():
    print("="*60)
    print(f"台湾株ニュース配信システム {VERSION}")
    print("="*60)

    all_news = collect_news()
    results = {}

    for stock_id, stock in STOCKS.items():
        name = stock["name"]
        print(f"\n📊 {name}（{stock_id}）")

        scored = []
        for n in all_news:
            s = score_news(n, name)
            if s > 0:
                n["score"] = s
                scored.append(n)

        scored.sort(key=lambda x: x["score"], reverse=True)
        delivery_news = scored[:3]

        # 投資判断補助を必ず追加
        delivery_news.append(generate_investment_aux(name, len(scored)))

        results[stock_id] = {
            "stock_info": stock,
            "news": delivery_news
        }

        print(f"配信: {len(delivery_news)} 本")

    if results:
        send_email(results)
    else:
        print("⚠️ 配信するニュースがありません")

def send_email(results):
    html = "<h1>台湾株ニュース</h1>"
    for r in results.values():
        html += f"<h2>{r['stock_info']['name']}</h2><ul>"
        for n in r["news"]:
            html += f"<li>{n['title']}<br>{n.get('summary','')}</li>"
        html += "</ul>"

    msg = Mail(
        from_email=os.environ["SENDGRID_FROM"],
        to_emails=os.environ["SENDGRID_TO"],
        subject="台湾株ニュース配信",
        html_content=html
    )

    sg = SendGridAPIClient(os.environ["SENDGRID_API_KEY"])
    sg.send(msg)
    print("✅ メール送信成功")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
台湾株ニュース配信システム（Gemini版 / 無料枠前提 / 安定80点）
要件:
- 各銘柄 最低1本ニュース保証（見つからない場合でも候補から強制採用）
- today / weekly / monthly の分類（検索範囲を広げる）
- 中国語タイトル + 日本語タイトル（上に日本語）
- URLは本文に生URLを出さず、タイトルにハイパーリンク
- 重複は「同一URL」「似たタイトル」を抑制
- Geminiは「1銘柄1回」だけ使用（翻訳+要点+最重要1本選択）
- Google Cloud Console（課金）不要：GEMINI_API_KEY のみ使用
"""

VERSION = "v5.2-gemini-free-stable-20260128"

import os
import re
import json
import time
import hashlib
import requests
import feedparser
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytz
from dateutil import parser as date_parser

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# Gemini SDK (Google GenAI SDK)
# pip install google-genai
from google import genai  # type: ignore


TW_TZ = pytz.timezone("Asia/Taipei")

# ==========================
# 環境変数（必須）
# ==========================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "").strip()

EMAIL_FROM = os.getenv("EMAIL_FROM", "").strip()  # 送信元（SendGridで認証済みが推奨）
EMAIL_TO = os.getenv("EMAIL_TO", "").strip()      # 送信先（自分のGmailなど）

# 任意: 追加の送信先（カンマ区切り）
EMAIL_TO_CC = os.getenv("EMAIL_TO_CC", "").strip()

# Geminiモデル（無料枠で使いやすい軽量系）
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash").strip()

# ==========================
# 銘柄データ読み込み
# ==========================
def load_stocks():
    """
    同一ディレクトリの stocks.json を読む。
    形式:
    { "stocks": { "2330": {"name":"台積電","business_type":"..."}, ... } }
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base_dir, "stocks.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("stocks", {})
    except Exception as e:
        print(f"❌ stocks.json 読み込み失敗: {e}", flush=True)
        return {}

STOCKS = load_stocks()


# ==========================
# RSSフィード（必要ならここで増やせる）
# ==========================
RSS_FEEDS = [
    # --- stock direct ---
    "https://news.google.com/rss/search?q=台積電+OR+TSMC&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=TSMC&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=TSMC&hl=ja&gl=JP&ceid=JP:ja",

    "https://news.google.com/rss/search?q=創見+OR+Transcend&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=創見+OR+Transcend&hl=ja&gl=JP&ceid=JP:ja",

    "https://news.google.com/rss/search?q=宇瞻+OR+Apacer&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=Apacer&hl=en-US&gl=US&ceid=US:en",

    "https://news.google.com/rss/search?q=廣達+OR+Quanta&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=Quanta+Computer&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=廣達+OR+Quanta&hl=ja&gl=JP&ceid=JP:ja",

    # --- driver queries ---
    "https://news.google.com/rss/search?q=AI伺服器&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=NVIDIA&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=GB200&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=HBM&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=DRAM價格&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=半導體&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=ODM&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",

    # --- earnings/event ---
    "https://news.google.com/rss/search?q=台積電+營收&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=創見+營收&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=宇瞻+營收&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=廣達+營收&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
]

SNS_DOMAINS = [
    "threads.net", "instagram.com", "line.me", "linkedin.com",
    "tiktok.com", "youtube.com", "youtu.be", "facebook.com", "x.com", "twitter.com"
]


# ==========================
# ユーティリティ
# ==========================
def is_sns_domain(url: str) -> bool:
    u = (url or "").lower()
    return any(d in u for d in SNS_DOMAINS)

def clean_url(url: str) -> str:
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    exclude_params = [
        "utm_source","utm_medium","utm_campaign","utm_term","utm_content",
        "fbclid","gclid","msclkid","oc","_ga","_gl"
    ]
    clean_params = {k: v for k, v in query_params.items() if k not in exclude_params}
    clean_query = urlencode(clean_params, doseq=True)
    return urlunparse(parsed._replace(query=clean_query))

def resolve_final_url(url: str, timeout: int = 3) -> str | None:
    try:
        r = requests.head(url, allow_redirects=True, timeout=timeout)
        return clean_url(r.url)
    except Exception:
        return None

def normalize_text(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s

def signature_for_item(title: str, final_url: str) -> str:
    base = f"{normalize_text(title)}|{final_url}"
    return hashlib.md5(base.encode("utf-8")).hexdigest()

def parse_pub_date(entry) -> datetime | None:
    pub_date = None
    if hasattr(entry, "published"):
        try:
            pub_date = date_parser.parse(entry.published).astimezone(TW_TZ)
        except Exception:
            pub_date = None
    return pub_date

def safe_get_publisher(entry, final_url: str) -> str:
    # RSS source title
    try:
        if hasattr(entry, "source") and hasattr(entry.source, "title") and entry.source.title:
            return str(entry.source.title)
    except Exception:
        pass
    # domain fallback
    try:
        d = urlparse(final_url).netloc.replace("www.", "")
        return d
    except Exception:
        return "unknown"


# ==========================
# RSS収集
# ==========================
def process_rss_entry(entry) -> dict | None:
    rss_url = entry.get("link", "")
    title = entry.get("title", "")
    snippet = (entry.get("summary", "") or "")[:240]

    final_url = resolve_final_url(rss_url, timeout=3)
    if not final_url:
        return None
    if is_sns_domain(final_url):
        return None

    pub_date = parse_pub_date(entry)
    publisher = safe_get_publisher(entry, final_url)

    sig = signature_for_item(title, final_url)

    return {
        "title_zh": title,
        "snippet": snippet,
        "publisher": publisher,
        "published": pub_date.isoformat() if pub_date else None,
        "link": final_url,
        "signature": sig,
    }

def collect_news_parallel(max_entries_per_feed: int = 20) -> list[dict]:
    print("📰 RSSフィードからニュース収集中...", flush=True)
    all_entries = []

    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            all_entries.extend(feed.entries[:max_entries_per_feed])
        except Exception as e:
            print(f"⚠️ RSS収集エラー: {feed_url} - {e}", flush=True)

    print(f"  RSS収集完了: {len(all_entries)}件", flush=True)

    items: list[dict] = []
    seen = set()

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(process_rss_entry, ent) for ent in all_entries]
        for i, fut in enumerate(as_completed(futures), 1):
            if i % 100 == 0:
                print(f"  処理中: {i}/{len(all_entries)}件", flush=True)
            try:
                it = fut.result()
                if not it:
                    continue
                if it["signature"] in seen:
                    continue
                seen.add(it["signature"])
                items.append(it)
            except Exception:
                continue

    print(f"✅ 重複除外後: {len(items)}件", flush=True)
    return items


# ==========================
# 検索範囲の段階拡張
# today / weekly / monthly
# ==========================
def within_days(pub_iso: str | None, days: int) -> bool:
    if not pub_iso:
        return False
    try:
        d = datetime.fromisoformat(pub_iso)
        if d.tzinfo is None:
            d = TW_TZ.localize(d)
        return d >= (datetime.now(TW_TZ) - timedelta(days=days))
    except Exception:
        return False

def stock_keywords(stock_id: str, stock_info: dict) -> list[str]:
    kws = [stock_info.get("name",""), stock_id]
    # よくある英名
    name = stock_info.get("name","")
    if stock_id == "2330":
        kws += ["TSMC", "台積電", "tsmc"]
    if stock_id == "2451":
        kws += ["Transcend", "創見", "transcend"]
    if stock_id == "8271":
        kws += ["Apacer", "宇瞻", "apacer"]
    if stock_id == "2382":
        kws += ["Quanta", "廣達", "quanta", "Quanta Computer"]
    # 空要素除去
    return [k for k in kws if k]

def pick_candidates_for_stock(all_news: list[dict], stock_id: str, stock_info: dict) -> list[dict]:
    kws = stock_keywords(stock_id, stock_info)

    # まずキーワードヒット
    candidates = []
    for n in all_news:
        text = f"{n.get('title_zh','')} {n.get('snippet','')}"
        if any(kw in text for kw in kws):
            candidates.append(n)

    # もし少なすぎるなら業界ワードも許可（補助）
    if len(candidates) < 5:
        bt = (stock_info.get("business_type") or "").strip()
        if bt:
            for n in all_news:
                if n in candidates:
                    continue
                text = f"{n.get('title_zh','')} {n.get('snippet','')}"
                if bt[:6] and bt[:6] in text:
                    candidates.append(n)

    # 日付が新しい順
    def sort_key(n):
        p = n.get("published")
        try:
            return datetime.fromisoformat(p) if p else datetime(1970,1,1, tzinfo=TW_TZ)
        except Exception:
            return datetime(1970,1,1, tzinfo=TW_TZ)

    candidates.sort(key=sort_key, reverse=True)

    # 同じドメイン・似たタイトルが連続するのを軽く抑制
    dedup = []
    seen_title = set()
    for n in candidates:
        t = normalize_text(n.get("title_zh",""))
        # ざっくり近似（先頭40文字）
        key = t[:40]
        if key in seen_title:
            continue
        seen_title.add(key)
        dedup.append(n)
        if len(dedup) >= 20:
            break

    return dedup

def split_by_recency(cands: list[dict]) -> dict:
    today = [c for c in cands if within_days(c.get("published"), 1)]
    weekly = [c for c in cands if within_days(c.get("published"), 7)]
    monthly = [c for c in cands if within_days(c.get("published"), 30)]
    return {"today": today, "weekly": weekly, "monthly": monthly}


# ==========================
# Gemini（1銘柄1回）で「最重要1本」+「日本語」+「要点」
# ==========================
def gemini_client():
    # GEMINI_API_KEY は環境変数から自動取得されるが、明示指定も可能
    if not GEMINI_API_KEY:
        return None
    try:
        return genai.Client(api_key=GEMINI_API_KEY)
    except Exception:
        return None

def build_gemini_prompt(stock_id: str, stock_name: str, bucket: str, items: list[dict]) -> str:
    lines = []
    for i, n in enumerate(items, 1):
        pub = n.get("published") or ""
        lines.append(
            f"[{i}] {n.get('title_zh','')}\n"
            f"出典: {n.get('publisher','')}\n"
            f"日時: {pub}\n"
            f"概要: {n.get('snippet','')}\n"
            f"URL: {n.get('link','')}\n"
        )

    body = "\n\n".join(lines)

    return f"""以下は台湾株ニュース候補です。

【銘柄】{stock_name}（{stock_id}）
【カテゴリ】{bucket}（today/weekly/monthly）

【目的】
- 日本人投資家向けに「投資判断に有用な最重要1本」を1つだけ選ぶ
- 自然で読みやすい日本語タイトルを付ける（中国語原文の上に表示する想定）
- 要点を3つに絞る（推測しない、原文の範囲で）

【出力形式】※JSONのみ、前後に文章を付けない
{{
  "picked_index": 1,
  "title_ja": "日本語タイトル（自然）",
  "title_zh": "原文タイトル（そのまま）",
  "bullets": ["要点1","要点2","要点3"],
  "why_this": "なぜ重要か（1文、事実ベース）"
}}

【注意】
- 数値や事実は原文に基づく
- 断定しすぎない（可能性/見通し等は原文がそう述べる場合のみ）
- 3〜4行に収まる粒度

【ニュース候補】
{body}
"""

def gemini_pick_one(stock_id: str, stock_name: str, bucket: str, items: list[dict]) -> dict | None:
    client = gemini_client()
    if not client:
        return None

    prompt = build_gemini_prompt(stock_id, stock_name, bucket, items)

    try:
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        text = (resp.text or "").strip()
        # JSONだけ取り出す
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group())
        return data
    except Exception as e:
        print(f"⚠️ Gemini失敗: {stock_name} - {e}", flush=True)
        return None


# ==========================
# 投資判断補助（AIなし・固定）
# ==========================
def investment_aux_text(stock_name: str) -> dict:
    return {
        "title_ja": "📉 投資判断補助（株価フェーズ整理）",
        "title_zh": "",
        "bullets": [
            "ニュース（材料）の有無と、値動きの大きさは一致しないことがあります。",
            "短期の上下は“需給/地合い/利益確定”でも起きるため、材料の質を優先して整理します。",
            "本メールは売買推奨ではなく、確認すべき論点の棚卸しです。"
        ],
        "why_this": f"{stock_name}の当日情報を“確認用のメモ”として付与しています。",
        "link": None,
        "publisher": "System",
        "published": datetime.now(TW_TZ).isoformat(),
        "bucket": "aux",
        "is_aux": True,
    }


# ==========================
# 1銘柄ぶん組み立て（最低1本保証）
# ==========================
def build_one_stock_result(stock_id: str, stock_info: dict, all_news: list[dict]) -> dict:
    name = stock_info.get("name", stock_id)
    print("="*60, flush=True)
    print(f"📊 {name}（{stock_id}）", flush=True)
    print("="*60, flush=True)

    cands = pick_candidates_for_stock(all_news, stock_id, stock_info)
    print(f"候補ニュース: {len(cands)}件", flush=True)

    buckets = split_by_recency(cands)

    # 探す順：today → weekly → monthly → それでもダメなら cands先頭（強制）
    chosen_bucket = None
    chosen_list = None
    for b in ["today", "weekly", "monthly"]:
        if buckets[b]:
            chosen_bucket = b
            chosen_list = buckets[b]
            break

    if not chosen_list and cands:
        chosen_bucket = "monthly"
        chosen_list = cands  # 強制候補（>30日が混ざる可能性はあるが「空よりマシ」）
    if not chosen_list:
        # ここまで来るのは異常（RSS取れてない等）
        # 空でも最低1本要求なのでダミーを出す
        chosen_bucket = "monthly"
        chosen_list = [{
            "title_zh": f"{name} 関連ニュースが取得できませんでした（RSS/ネットワーク要確認）",
            "snippet": "RSS取得やネットワーク制限により候補が0件でした。",
            "publisher": "System",
            "published": datetime.now(TW_TZ).isoformat(),
            "link": None,
            "signature": hashlib.md5(f"{stock_id}-{time.time()}".encode()).hexdigest()
        }]

    # Geminiに投げる候補は上位10件
    shortlist = chosen_list[:10]

    gem = gemini_pick_one(stock_id, name, chosen_bucket, shortlist)
    if gem:
        idx = int(gem.get("picked_index", 1)) - 1
        idx = max(0, min(idx, len(shortlist)-1))
        picked = shortlist[idx]
        news_item = {
            "title_ja": gem.get("title_ja", picked.get("title_zh", "")),
            "title_zh": gem.get("title_zh", picked.get("title_zh", "")),
            "bullets": gem.get("bullets", [])[:3],
            "why_this": gem.get("why_this", ""),
            "link": picked.get("link"),
            "publisher": picked.get("publisher"),
            "published": picked.get("published"),
            "bucket": chosen_bucket,
            "is_aux": False,
        }
        print(f"✅ 採用: {chosen_bucket} / Gemini選定", flush=True)
    else:
        # Gemini失敗時のフォールバック（最低品質保証）
        picked = shortlist[0]
        news_item = {
            "title_ja": picked.get("title_zh", ""),  # 翻訳できないので同文
            "title_zh": picked.get("title_zh", ""),
            "bullets": [picked.get("snippet", "")[:60] + "…"],
            "why_this": "Geminiが利用できないため、候補の先頭を採用しました。",
            "link": picked.get("link"),
            "publisher": picked.get("publisher"),
            "published": picked.get("published"),
            "bucket": chosen_bucket,
            "is_aux": False,
        }
        print(f"⚠️ 採用: {chosen_bucket} / Gemini未使用（フォールバック）", flush=True)

    # 1銘柄 = [ニュース1本] + [投資判断補助1本]
    # ※「必ずニュース1本」の要件を満たしつつ、補助は常に追加
    out = {
        "stock_id": stock_id,
        "stock_name": name,
        "business_type": stock_info.get("business_type", ""),
        "items": [news_item, investment_aux_text(name)],
    }
    return out


# ==========================
# メール送信
# ==========================
def send_email(render_data: list[dict], now_taipei: datetime):
    if not SENDGRID_API_KEY:
        print("❌ SENDGRID_API_KEY が未設定です", flush=True)
        return
    if not EMAIL_FROM or not EMAIL_TO:
        print("❌ EMAIL_FROM / EMAIL_TO が未設定です", flush=True)
        return

    from email_template_v5 import generate_html_email  # ローカルファイル

    html_content = generate_html_email(render_data, now_taipei, VERSION)

    to_list = [EMAIL_TO]
    cc_list = []
    if EMAIL_TO_CC:
        cc_list = [x.strip() for x in EMAIL_TO_CC.split(",") if x.strip()]

    message = Mail(
        from_email=EMAIL_FROM,
        to_emails=to_list,
        subject=f"🇹🇼 台湾株ニュース配信 {VERSION} - {now_taipei.strftime('%Y-%m-%d %H:%M')}",
        html_content=html_content
    )
    if cc_list:
        message.add_cc(cc_list)

    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        resp = sg.send(message)
        print(f"✅ メール送信成功（ステータス: {resp.status_code}）", flush=True)
    except Exception as e:
        print(f"❌ メール送信エラー: {e}", flush=True)


def main():
    print("="*60, flush=True)
    print(f"台湾株ニュース配信システム {VERSION}", flush=True)
    print("="*60, flush=True)

    if not STOCKS:
        print("❌ stocks.json の銘柄が空です。stocks.json を確認してください。", flush=True)
        return

    # RSS収集（広めに取って、銘柄側で today/weekly/monthly に分類）
    all_news = collect_news_parallel(max_entries_per_feed=30)

    results: list[dict] = []
    for sid, sinfo in STOCKS.items():
        results.append(build_one_stock_result(sid, sinfo, all_news))

    now_taipei = datetime.now(TW_TZ)
    print("\n📧 メール送信中...", flush=True)
    send_email(results, now_taipei)


if __name__ == "__main__":
    main()

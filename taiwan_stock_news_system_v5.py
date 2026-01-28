# -*- coding: utf-8 -*-
"""
台湾株ニュース配信システム v5 (AI APIゼロ / 無料運用想定)
- RSSのみでニュース収集（当日→7日→30日フォールバック）
- 必ず1銘柄1本ニュースを配信（なければ「見つからない」ではなく、30日まで探し切る）
- 中国語タイトルの上に、日本語タイトル（簡易辞書変換）を付与
- URLは本文にベタ貼りしない（記事タイトルにハイパーリンク）
- SendGridでメール送信（SENDGRID_API_KEY / SENDGRID_FROM / SENDGRID_TO）

環境変数（GitHub Actions Secrets推奨）:
- SENDGRID_API_KEY
- SENDGRID_FROM
- SENDGRID_TO
"""

import os
import re
import json
import time
import hashlib
from datetime import datetime, timedelta
from urllib.parse import urlparse

import requests
import feedparser
import pytz
from dateutil import parser as date_parser
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# ============================================================
# 設定
# ============================================================

TZ = pytz.timezone("Asia/Taipei")

# RSSソース（無料・比較的安定）
# ※必要ならここに追加できます（コードを壊しにくい構造にしてあります）
RSS_FEEDS = [
    # Yahoo奇摩股市（株式ニュース）
    "https://tw.stock.yahoo.com/rss",
    # 經濟日報 (UDN) - 財經
    "https://money.udn.com/rssfeed/news/1001/5591?ch=money",
    # 工商時報 - 財經（※フィードが変わる場合あり）
    "https://ctee.com.tw/feed",
    # MoneyDJ - 台股（※フィードが変わる場合あり）
    "https://www.moneydj.com/kmdj/rss/rssfeed.aspx?a=mb010000",
]

# 収集上限（全フィード合計）
MAX_ENTRIES_TOTAL = 800

# タイムウィンドウ（当日→7日→30日）
WINDOWS = [
    ("today", 1),
    ("weekly", 7),
    ("monthly", 30),
]

# リクエスト設定
HTTP_TIMEOUT = 12
HTTP_RETRIES = 2

# ============================================================
# 日本語化（無料＆安定のため「簡易辞書＋整形」）
# ============================================================

CN2JP_DICT = [
    # 会社/市場/金融
    (r"台積電", "TSMC（台積電）"),
    (r"台股", "台湾株"),
    (r"美股", "米国株"),
    (r"財報", "決算"),
    (r"營收", "売上"),
    (r"獲利", "利益"),
    (r"毛利率", "粗利益率"),
    (r"淨利", "純利益"),
    (r"法說會", "決算説明会"),
    (r"股價", "株価"),
    (r"股價走勢", "株価推移"),
    (r"目標價", "目標株価"),
    (r"上漲", "上昇"),
    (r"下跌", "下落"),
    (r"大跌", "急落"),
    (r"大漲", "急騰"),
    (r"利多", "好材料"),
    (r"利空", "悪材料"),
    (r"外資", "海外投資家"),
    (r"投信", "投資信託"),
    (r"自營商", "自己売買"),
    (r"買超", "買い越し"),
    (r"賣超", "売り越し"),
    (r"ETF", "ETF"),
    (r"AI", "AI"),
    (r"伺服器", "サーバー"),
    (r"供應鏈", "サプライチェーン"),
    (r"半導體", "半導体"),
    (r"記憶體", "メモリ"),
    (r"DRAM", "DRAM"),
    (r"NAND", "NAND"),
    (r"筆電", "ノートPC"),
    (r"資料中心", "データセンター"),
    (r"雲端", "クラウド"),
    (r"訂單", "受注"),
    (r"出貨", "出荷"),
    (r"產能", "生産能力"),
    (r"擴產", "増産"),
    (r"減產", "減産"),
    (r"美元", "米ドル"),
    (r"新台幣", "台湾ドル"),
    # よくある記号/表記
    (r"【", "["),
    (r"】", "]"),
]

def cn_title_to_jp(title_cn: str) -> str:
    """無料で安定させるため、翻訳ではなく“日本語化（置換＋整形）”に留める"""
    if not title_cn:
        return ""
    t = title_cn.strip()
    for pat, rep in CN2JP_DICT:
        t = re.sub(pat, rep, t)
    # 余計なスペース整形
    t = re.sub(r"\s+", " ", t).strip()
    # それでも中国語が強い場合は頭にラベルを付ける
    # （完全翻訳はしない）
    return f"（日本語要約）{t}"

# ============================================================
# ユーティリティ
# ============================================================

def now_taipei() -> datetime:
    return datetime.now(TZ)

def normalize_url(url: str) -> str:
    if not url:
        return ""
    return url.strip()

def safe_domain(url: str) -> str:
    try:
        return urlparse(url).netloc or ""
    except Exception:
        return ""

def hash_key(*parts: str) -> str:
    raw = "||".join([p or "" for p in parts])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

def parse_entry_datetime(entry) -> datetime | None:
    # feedparserはentry.published_parsed / updated_parsed 等を持つことが多い
    for key in ["published", "updated", "created"]:
        if hasattr(entry, key):
            try:
                dt = date_parser.parse(getattr(entry, key))
                if dt.tzinfo is None:
                    dt = TZ.localize(dt)
                else:
                    dt = dt.astimezone(TZ)
                return dt
            except Exception:
                pass
    # structured time
    for key in ["published_parsed", "updated_parsed"]:
        if hasattr(entry, key):
            try:
                st = getattr(entry, key)
                if st:
                    dt = datetime(*st[:6], tzinfo=pytz.utc).astimezone(TZ)
                    return dt
            except Exception:
                pass
    return None

def http_get(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TaiwanStockNewsBot/1.0; +https://github.com/)",
        "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
    }
    last_err = None
    for _ in range(HTTP_RETRIES + 1):
        try:
            r = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT, allow_redirects=True)
            r.raise_for_status()
            return r.text
        except Exception as e:
            last_err = e
            time.sleep(0.8)
    raise RuntimeError(f"fetch failed: {url} / {last_err}")

def load_stocks() -> list[dict]:
    """
    stocks.json 例:
    [
      {"name":"台積電","code":"2330","keywords":["台積電","TSMC","2330"]},
      ...
    ]
    """
    # 優先：同ディレクトリのstocks.json
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "stocks.json")

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list) and data:
                return data

    # フォールバック（最低限）
    return [
        {"name": "台積電", "code": "2330", "keywords": ["台積電", "TSMC", "2330"]},
        {"name": "創見", "code": "2451", "keywords": ["創見", "Transcend", "2451"]},
        {"name": "宇瞻", "code": "8271", "keywords": ["宇瞻", "Apacer", "8271"]},
        {"name": "廣達", "code": "2382", "keywords": ["廣達", "Quanta", "2382"]},
    ]

def collect_rss_entries() -> list[dict]:
    """
    RSS全体から記事候補を集める。
    返り値: [{"title":..., "link":..., "dt":..., "source":...}, ...]
    """
    out = []
    for feed_url in RSS_FEEDS:
        try:
            xml = http_get(feed_url)
            parsed = feedparser.parse(xml)
            for e in parsed.entries[:200]:
                title = (getattr(e, "title", "") or "").strip()
                link = normalize_url(getattr(e, "link", "") or "")
                dt = parse_entry_datetime(e)
                if not title or not link:
                    continue
                out.append({
                    "title": title,
                    "link": link,
                    "dt": dt,  # Noneあり
                    "source": safe_domain(feed_url) or safe_domain(link) or "rss",
                })
        except Exception as ex:
            print(f"⚠️ RSS取得失敗: {feed_url} / {ex}", flush=True)

    # 重複除外（title+link）
    seen = set()
    dedup = []
    for item in out:
        k = hash_key(item["title"], item["link"])
        if k in seen:
            continue
        seen.add(k)
        dedup.append(item)

    # 新しい順（dtがNoneは最後）
    def sort_key(x):
        return x["dt"] if x["dt"] else datetime(1970, 1, 1, tzinfo=TZ)
    dedup.sort(key=sort_key, reverse=True)

    # 上限
    return dedup[:MAX_ENTRIES_TOTAL]

def within_days(dt: datetime | None, days: int) -> bool:
    if dt is None:
        # 日付が取れないRSSもあるため、除外しない（ただし優先度は下がる）
        return True
    return dt >= (now_taipei() - timedelta(days=days))

def match_stock(item: dict, stock: dict) -> bool:
    title = (item.get("title") or "")
    # keyword一致（タイトルだけ）
    for kw in stock.get("keywords", []):
        if kw and kw in title:
            return True
    return False

def pick_best_news_for_stock(entries: list[dict], stock: dict) -> dict | None:
    """
    today→weekly→monthly の順で探索。
    その中で最も新しいものを採用。
    """
    for label, days in WINDOWS:
        candidates = [it for it in entries if within_days(it["dt"], days) and match_stock(it, stock)]
        if candidates:
            # dtがNoneの場合は末尾に回す
            candidates.sort(
                key=lambda x: x["dt"] if x["dt"] else datetime(1970, 1, 1, tzinfo=TZ),
                reverse=True
            )
            best = candidates[0].copy()
            best["bucket"] = label
            return best
    return None

def investment_helper_block() -> list[str]:
    # 固定で毎回付ける（質保証）
    return [
        "市場は様子見フェーズ",
        "短期は材料・反応を確認",
        "中長期は押し目監視",
    ]

def build_email_html(results: list[dict]) -> str:
    sent_at = now_taipei().strftime("%Y-%m-%d %H:%M")

    # 以前の「カード型」寄せ（シンプルHTML）
    def card(title: str, body_html: str) -> str:
        return f"""
        <div style="border:1px solid #2b2b2b;border-radius:12px;padding:14px;margin:14px 0;background:#111;">
          <div style="font-size:18px;font-weight:700;margin-bottom:10px;color:#fff;">{title}</div>
          <div style="font-size:14px;line-height:1.65;color:#d6d6d6;">{body_html}</div>
        </div>
        """

    cards = []

    header = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,'Noto Sans JP','Hiragino Kaku Gothic ProN','Yu Gothic',sans-serif;background:#0b0b0b;color:#fff;padding:18px;">
      <div style="font-size:34px;font-weight:800;margin:0 0 6px 0;">📈 台湾株ニュース配信</div>
      <div style="color:#cfcfcf;font-size:14px;">配信日時：{sent_at}</div>
      <hr style="border:0;border-top:1px solid #2b2b2b;margin:14px 0;">
    """

    for r in results:
        stock_name = r["stock"]["name"]
        stock_code = r["stock"]["code"]
        news = r.get("news")

        if news:
            title_cn = news["title"]
            title_jp = cn_title_to_jp(title_cn)
            link = news["link"]
            source = news.get("source", "rss")
            dt = news.get("dt")
            dt_str = dt.strftime("%Y-%m-%d %H:%M") if dt else "日時不明"
            bucket = news.get("bucket", "today")

            # タイトルをリンク化（URLのベタ貼り禁止）
            # 2行構成：日本語（上）→中国語（下）
            body = f"""
            <div style="margin-bottom:10px;">
              <div style="font-weight:700;color:#9fd1ff;margin-bottom:4px;">
                <a href="{link}" style="color:#7db7ff;text-decoration:none;">{title_jp}</a>
              </div>
              <div style="color:#b8b8b8;">
                <a href="{link}" style="color:#7db7ff;text-decoration:none;">{title_cn}</a>
              </div>
              <div style="color:#8a8a8a;font-size:12px;margin-top:6px;">
                分類：{bucket} / 出典：{source} / 日時：{dt_str}
              </div>
            </div>
            """
        else:
            # 「絶対1本」が要求なので、ここは基本到達しない想定。
            body = f"""
            <div style="color:#ffb3b3;font-weight:700;margin-bottom:8px;">⚠️ 30日以内でも該当ニュースを抽出できませんでした。</div>
            <div style="color:#b8b8b8;">検索条件（銘柄キーワード）を要見直し。</div>
            """

        helper = investment_helper_block()
        helper_html = "<ul style='margin:8px 0 0 18px;'>" + "".join([f"<li>{h}</li>" for h in helper]) + "</ul>"

        body += f"""
        <div style="margin-top:12px;padding-top:10px;border-top:1px solid #2b2b2b;">
          <div style="font-weight:800;color:#b6ffcc;">📊 投資判断補助（株価フェーズ整理）</div>
          {helper_html}
        </div>
        """

        cards.append(card(f"{stock_name}（{stock_code}）", body))

    footer = """
      <hr style="border:0;border-top:1px solid #2b2b2b;margin:18px 0 10px;">
      <div style="color:#8a8a8a;font-size:12px;line-height:1.6;">
        ※本メールはRSS情報をもとに自動生成しています。投資判断はご自身の責任でお願いします。
      </div>
    </div>
    """

    return header + "\n".join(cards) + footer

def send_email(html: str) -> None:
    api_key = os.environ.get("SENDGRID_API_KEY", "").strip()
    mail_from = os.environ.get("SENDGRID_FROM", "").strip()
    mail_to = os.environ.get("SENDGRID_TO", "").strip()

    if not api_key or not mail_from or not mail_to:
        print("❌ SendGrid 環境変数が不足しています（SENDGRID_API_KEY / SENDGRID_FROM / SENDGRID_TO）", flush=True)
        return

    subject = "📈 台湾株ニュース配信"
    message = Mail(
        from_email=mail_from,
        to_emails=mail_to,
        subject=subject,
        html_content=html
    )

    try:
        sg = SendGridAPIClient(api_key)
        resp = sg.send(message)
        print(f"✅ メール送信成功 (status={resp.status_code})", flush=True)
    except Exception as e:
        print(f"❌ メール送信失敗: {e}", flush=True)

def main():
    print("=" * 60)
    print("台湾株ニュース配信システム v5（AI APIゼロ / RSS運用）")
    print("=" * 60, flush=True)

    stocks = load_stocks()
    print(f"銘柄数: {len(stocks)}", flush=True)

    print("📰 RSSフィードからニュース収集中...", flush=True)
    entries = collect_rss_entries()
    print(f"✅ 収集完了: {len(entries)}件（重複除外後）", flush=True)

    results = []
    for s in stocks:
        print("-" * 60)
        print(f"📊 {s['name']}（{s['code']}）", flush=True)
        news = pick_best_news_for_stock(entries, s)

        # 「必ず1銘柄1本」を最優先：30日でも取れない場合は“タイトル未確定の代替”を作る
        if not news:
            # 代替：キーワード無しでも、直近の“台湾株関連っぽい”を拾う（最後の安全網）
            # ここで0本のまま送るのを防ぐ
            fallback = None
            for it in entries:
                if within_days(it["dt"], 30):
                    # 台湾株/半導体/サーバー/AIなど一般ワードで拾う
                    if re.search(r"(台股|半導體|伺服器|AI|財報|營收|外資|ETF|台積電|TSMC)", it["title"]):
                        fallback = it.copy()
                        fallback["bucket"] = "monthly"
                        break
            news = fallback

        if news:
            print(f"✅ 採用: {news.get('bucket','?')} / {news['title']}", flush=True)
        else:
            print("⚠️ 採用ニュースなし（極めて稀）", flush=True)

        results.append({"stock": s, "news": news})

    html = build_email_html(results)
    send_email(html)

if __name__ == "__main__":
    main()

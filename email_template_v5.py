# email_template_v5.py
# 台湾株ニュース配信 v5.x
# 以前うまくいっていたダークデザインを踏襲
# ・銘柄ごと1カード
# ・論点1行
# ・ニュース最大3本
# ・日本語タイトルを主、原文は補足
# ・URL直貼り禁止（タイトルにリンク）

from datetime import datetime
import html


def generate_html_email(results: dict, taipei_time: datetime) -> str:
    def esc(s):
        return html.escape(s or "")

    html_parts = []

    # ===== HTML HEADER =====
    html_parts.append(f"""
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>台湾株ニュース配信</title>
</head>
<body style="
    margin:0;
    padding:0;
    background-color:#0f172a;
    color:#e5e7eb;
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Hiragino Kaku Gothic ProN','Noto Sans JP',Meiryo,sans-serif;
">
<div style="max-width:900px;margin:0 auto;padding:24px;">
<h1 style="color:#f8fafc;">🇹🇼 台湾株ニュース配信</h1>
<p style="color:#94a3b8;font-size:13px;">
配信時刻：{taipei_time.strftime('%Y-%m-%d %H:%M')}（台北時間）
</p>
<hr style="border:0;border-top:1px solid #334155;margin:24px 0;">
""")

    # ===== STOCK BLOCKS =====
    for stock_id, result in results.items():
        stock = result["stock_info"]
        topic = result.get("topic", "")
        news_list = result.get("news", [])

        html_parts.append(f"""
<div style="
    background-color:#020617;
    border:1px solid #334155;
    border-radius:10px;
    padding:20px;
    margin-bottom:28px;
">
<h2 style="margin:0 0 6px 0;color:#facc15;">
{esc(stock["name"])}（{stock_id}）
</h2>
<p style="margin:0 0 14px 0;color:#cbd5f5;font-size:14px;">
<strong>論点：</strong>{esc(topic)}
</p>
""")

        if not news_list:
            html_parts.append("""
<p style="color:#94a3b8;font-size:14px;">
該当期間内に有意なニュースは確認されませんでした。
</p>
""")
        else:
            for news in news_list[:3]:
                title_ja = news.get("title_ja") or news.get("title") or ""
                title_orig = news.get("title") or ""
                link = news.get("link") or ""
                snippet = news.get("snippet") or ""

                html_parts.append(f"""
<div style="margin-bottom:18px;">
<p style="margin:0 0 6px 0;font-size:15px;">
<a href="{esc(link)}" style="color:#38bdf8;text-decoration:none;">
{esc(title_ja)}
</a>
</p>
<p style="margin:0 0 6px 0;color:#9ca3af;font-size:12px;">
原文：{esc(title_orig)}
</p>
<p style="margin:0;color:#e5e7eb;font-size:14px;line-height:1.6;">
{esc(snippet)}
</p>
</div>
""")

        html_parts.append("</div>")

    # ===== FOOTER =====
    html_parts.append("""
<hr style="border:0;border-top:1px solid #334155;margin:32px 0;">
<p style="color:#64748b;font-size:12px;">
本メールは投資判断を補助する情報提供を目的としています。売買を推奨するものではありません。
</p>
</div>
</body>
</html>
""")

    return "".join(html_parts)

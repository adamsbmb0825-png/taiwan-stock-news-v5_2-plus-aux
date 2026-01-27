import os
import feedparser
import pytz
from datetime import datetime
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# =========================
# SendGrid Mail
# =========================
def send_email(html):
    api_key = os.environ.get("SENDGRID_API_KEY")
    mail_from = os.environ.get("SENDGRID_FROM")
    mail_to = os.environ.get("SENDGRID_TO")

    print("🚀 send_email() CALLED")

    if not api_key or not mail_from or not mail_to:
        print("❌ SendGrid 環境変数が不足しています")
        return

    message = Mail(
        from_email=mail_from,
        to_emails=mail_to,
        subject="📈 台湾株ニュース配信",
        html_content=html
    )

    try:
        sg = SendGridAPIClient(api_key)
        response = sg.send(message)
        print(f"✅ SendGrid送信成功 status={response.status_code}")
    except Exception as e:
        print("❌ SendGrid送信失敗:", e)


# =========================
# Main
# =========================
def main():
    print("台湾株ニュース配信システム v5.2-lite")

    # ---- ここは将来拡張用（今はダミー） ----
    delivery_news = []  # ← ニュースが0件でもOK

    # =========================
    # HTML生成（必ず作る）
    # =========================
    tz = pytz.timezone("Asia/Taipei")
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M")

    if delivery_news:
        body = "<br>".join(delivery_news)
    else:
        body = """
        <p>本日は配信対象となる新規ニュースはありませんでした。</p>
        <p>📉 投資判断補助（株価フェーズ整理）</p>
        <ul>
          <li>市場は様子見フェーズ</li>
          <li>短期ボラティリティ低下</li>
          <li>中長期では押し目監視</li>
        </ul>
        """

    html = f"""
    <html>
      <body>
        <h2>台湾株ニュース配信</h2>
        <p>配信日時：{now}</p>
        <hr>
        {body}
      </body>
    </html>
    """

    # =========================
    # ★ 必ず送信される ★
    # =========================
    send_email(html)


if __name__ == "__main__":
    main()

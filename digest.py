"""Send the day's top stories to Slack and/or email. Both channels are optional.

Usage:
    python digest.py --dry-run          print what would be sent
    python digest.py --force            send now
    python digest.py --only-hour 6      send only when the current UTC hour is 6 (used by the workflow)

Environment (set only what you want to use):
    SLACK_WEBHOOK_URL                                  Slack incoming webhook
    SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASS   SMTP server for email
    DIGEST_TO (comma separated), DIGEST_FROM (defaults to SMTP_USER)
    SITE_URL                                           link back to the dashboard (optional)
"""
import html
import json
import os
import smtplib
import sys
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

import insights as ins

DATA_FILE = Path(__file__).resolve().parent / "data.json"


def _stale_note(data, now):
    hours = ins.stale_hours(data.get("generated_at"), now)
    return f"Note: this data is about {round(hours)} hours old; the update job may be failing." if hours > 12 else ""


def _slack_escape(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_slack_text(data, site_url="", now=None):
    now = now or datetime.now(timezone.utc)
    lines = [f"*Tech Insights, {data.get('last_updated', '')}*"]
    for n, item in enumerate(data.get("top_stories", []), 1):
        link = ins.safe_link(item.get("link", ""))
        title = _slack_escape(item.get("title", "")).replace("|", "-")
        head = f"{n}. <{link}|{title}>" if link else f"{n}. {title}"
        lines.append(f"{head}  _({_slack_escape(item.get('sector', ''))})_")
        if item.get("why_it_matters"):
            lines.append(f"    {_slack_escape(item['why_it_matters'])}")
    terms = [e["term"] for e in data.get("emerging", [])]
    if terms:
        lines.append("*Emerging:* " + ", ".join(_slack_escape(t) for t in terms))
    recap = data.get("weekly_recap") or {}
    if recap.get("text") and recap.get("week_ending") == now.date().isoformat():
        lines.append("*Weekly recap:* " + _slack_escape(recap["text"]))
    if site_url and ins.safe_link(site_url):
        lines.append(f"<{ins.safe_link(site_url)}|Open the dashboard>")
    note = _stale_note(data, now)
    if note:
        lines.append(f"_{note}_")
    return "\n".join(lines)


def build_email(data, site_url="", now=None):
    """Return (subject, plain_text, html_body)."""
    now = now or datetime.now(timezone.utc)
    top = data.get("top_stories", [])
    subject = "Tech Insights: " + (top[0]["title"] if top else "daily digest")
    subject = ins.truncate(subject.replace("\n", " "), 120)
    plain, rich = [f"Tech Insights, {data.get('last_updated', '')}", ""], ["<h2>Tech Insights</h2>"]
    for n, item in enumerate(top, 1):
        link = ins.safe_link(item.get("link", "")) or ""
        plain.append(f"{n}. {item.get('title', '')} ({item.get('sector', '')})")
        if item.get("summary"):
            plain.append(f"   {item['summary']}")
        if item.get("why_it_matters"):
            plain.append(f"   Why it matters: {item['why_it_matters']}")
        if link:
            plain.append(f"   {link}")
        plain.append("")
        title = html.escape(item.get("title", ""))
        rich.append(f"<p><b>{n}. " + (f'<a href="{html.escape(link)}">{title}</a>' if link else title) +
                    f"</b> <small>({html.escape(item.get('sector', ''))})</small><br>" +
                    html.escape(item.get("summary", "")) +
                    (f"<br><i>Why it matters:</i> {html.escape(item['why_it_matters'])}" if item.get("why_it_matters") else "") + "</p>")
    terms = [e["term"] for e in data.get("emerging", [])]
    if terms:
        plain += ["Emerging: " + ", ".join(terms), ""]
        rich.append("<p><b>Emerging:</b> " + html.escape(", ".join(terms)) + "</p>")
    recap = data.get("weekly_recap") or {}
    if recap.get("text") and recap.get("week_ending") == now.date().isoformat():
        plain += ["Weekly recap: " + recap["text"], ""]
        rich.append("<p><b>Weekly recap:</b> " + html.escape(recap["text"]) + "</p>")
    if site_url and ins.safe_link(site_url):
        safe = ins.safe_link(site_url)
        plain.append(f"Dashboard: {safe}")
        rich.append(f'<p><a href="{html.escape(safe)}">Open the dashboard</a></p>')
    note = _stale_note(data, now)
    if note:
        plain.append(note)
        rich.append(f"<p><i>{html.escape(note)}</i></p>")
    return subject, "\n".join(plain), "\n".join(rich)


def send_slack(webhook, text):
    if not ins.safe_link(webhook) or not webhook.startswith("https://"):
        raise ValueError("SLACK_WEBHOOK_URL must be an https URL")
    request = urllib.request.Request(webhook, data=json.dumps({"text": text}).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 (https enforced above)
        response.read()


def send_email(subject, plain, rich, env):
    recipients = [r.strip() for r in env["DIGEST_TO"].split(",") if r.strip()]
    msg = EmailMessage()
    msg["Subject"], msg["To"] = subject, ", ".join(recipients)
    msg["From"] = env.get("DIGEST_FROM") or env["SMTP_USER"]
    msg.set_content(plain)
    msg.add_alternative(rich, subtype="html")
    with smtplib.SMTP(env["SMTP_HOST"], int(env.get("SMTP_PORT") or 587), timeout=30) as server:
        server.starttls()
        server.login(env["SMTP_USER"], env["SMTP_PASS"])
        server.send_message(msg)


def main(argv):
    now = datetime.now(timezone.utc)
    if "--only-hour" in argv:
        wanted = int(argv[argv.index("--only-hour") + 1])
        if now.hour != wanted and "--force" not in argv:
            print(f"Digest skipped (UTC hour is {now.hour}, sends at {wanted}).")
            return 0
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Digest skipped: cannot read data.json ({exc}).", file=sys.stderr)
        return 1
    if not data.get("top_stories"):
        print("Digest skipped: no top stories yet.")
        return 0

    env = os.environ
    site_url = env.get("SITE_URL", "")
    slack_text = build_slack_text(data, site_url, now)
    subject, plain, rich = build_email(data, site_url, now)
    if "--dry-run" in argv:
        print(slack_text, "\n--- email ---\nSubject:", subject, "\n" + plain)
        return 0

    sent, failed = 0, 0
    if env.get("SLACK_WEBHOOK_URL"):
        try:
            send_slack(env["SLACK_WEBHOOK_URL"], slack_text)
            sent += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"Slack digest failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    if all(env.get(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "DIGEST_TO")):
        try:
            send_email(subject, plain, rich, env)
            sent += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"Email digest failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    if not sent and not failed:
        print("No digest channel configured (set SLACK_WEBHOOK_URL and/or the SMTP_* secrets).")
    else:
        print(f"Digest sent to {sent} channel(s), {failed} failed.")
    return 0  # a failed digest must never block the data update from being committed


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

import httpx


def notify_discord(webhook_url: str | None, title: str, description: str, color: int) -> None:
    if not webhook_url:
        return
    try:
        with httpx.Client(timeout=10) as client:
            client.post(webhook_url, json={"embeds": [{"title": title, "description": description, "color": color}]})
    except Exception:
        pass

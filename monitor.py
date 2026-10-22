
import os
import re
import json
import hashlib
import requests
from bs4 import BeautifulSoup
from pathlib import Path

URL = "https://www.zatocsi.cz/free-spiny-bonusy-hned/"
STATE_FILE = Path("state.json")
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


def clean(text):
    return re.sub(r"\s+", " ", text).strip()


def get_offers():
    response = requests.get(
        URL,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    for tag in soup.select(
        "script, style, nav, footer, header, noscript"
    ):
        tag.decompose()

    main = soup.find("main") or soup.find("article") or soup.body
    if main is None:
        raise RuntimeError("Na stránce se nepodařilo najít obsah.")

    offers = {}
    headings = main.find_all(["h2", "h3", "h4"])

    for heading in headings:
        title = clean(heading.get_text(" ", strip=True))
        if len(title) < 4:
            continue

        # Najdi nejmenší rozumný blok obsahující nabídku.
        node = heading
        chosen = heading.parent

        for _ in range(5):
            if node.parent is None or node.parent == main:
                break
            node = node.parent
            text = clean(node.get_text(" ", strip=True))
            if 40 <= len(text) <= 1200:
                chosen = node
                break

        details = clean(chosen.get_text(" ", strip=True))
        if len(details) < len(title):
            details = title

        key = clean(title).casefold()
        fingerprint = hashlib.sha256(
            details.encode("utf-8")
        ).hexdigest()

        offers[key] = {
            "title": title,
            "details": details[:900],
            "fingerprint": fingerprint,
        }

    if not offers:
        raise RuntimeError(
            "Nenašly se žádné nabídky. "
            "Kontrola se zastavila, aby nesmazala uložená data."
        )

    return offers


def send_telegram(message):
    response = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": message[:4000],
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    response.raise_for_status()


def main():
    current = get_offers()

    if STATE_FILE.exists():
        previous = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    else:
        previous = None

    if previous is None:
        # První spuštění: uloží aktuální stav bez záplavy zpráv.
        STATE_FILE.write_text(
            json.dumps(current, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        send_telegram(
            "✅ Zatočsi monitor je aktivní!\n"
            f"Uloženo {len(current)} aktuálních položek jako výchozí stav.\n"
            "Nové nabídky budu posílat při dalších kontrolách.\n"
            + URL
        )
        return

    new_keys = current.keys() - previous.keys()
    removed_keys = previous.keys() - current.keys()
    changed_keys = [
        key for key in current.keys() & previous.keys()
        if current[key]["fingerprint"]
        != previous[key]["fingerprint"]
    ]

    messages = []

    for key in sorted(new_keys):
        offer = current[key]
        messages.append(
            "🆕 NOVÁ NABÍDKA\n"
            f"{offer['title']}\n{offer['details']}"
        )

    for key in sorted(changed_keys):
        offer = current[key]
        messages.append(
            "✏️ ZMĚNA NABÍDKY\n"
            f"{offer['title']}\n{offer['details']}"
        )

    for key in sorted(removed_keys):
        messages.append(
            "⚠️ NABÍDKA ZMIZELA ZE STRÁNKY\n"
            f"{previous[key]['title']}"
        )

    if messages:
        # Posílej pouze změny, ne celý seznam každý den.
        for start in range(0, len(messages), 4):
            batch = messages[start:start + 4]
            send_telegram(
                "🎰 Zatočsi.cz – aktualizace\n\n"
                + "\n\n".join(batch)
                + f"\n\n🔗 {URL}"
            )

    STATE_FILE.write_text(
        json.dumps(current, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"Kontrola hotová. Nové: {len(new_keys)}, "
        f"změněné: {len(changed_keys)}, "
        f"zmizelé: {len(removed_keys)}"
    )


if __name__ == "__main__":
    main()

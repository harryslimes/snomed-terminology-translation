from __future__ import annotations

import argparse
import csv
import logging
import time
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
from urllib.parse import urljoin


logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("snomed.sonaveeb")

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"


DICTIONARIES = [
    "https://sonaveeb.ee/ds/bks",
    "https://sonaveeb.ee/ds/gen",
    "https://sonaveeb.ee/ds/GER",
    "https://sonaveeb.ee/ds/den",
    "https://sonaveeb.ee/ds/imm",
    "https://sonaveeb.ee/ds/lon",
    "https://sonaveeb.ee/ds/mef",
    "https://sonaveeb.ee/ds/nfs",
    "https://sonaveeb.ee/ds/pot",
    "https://sonaveeb.ee/ds/rkb",
    "https://sonaveeb.ee/ds/TAI",
    "https://sonaveeb.ee/ds/glu",
    "https://sonaveeb.ee/ds/%C3%95TERM",
]


def fetch_sonaveeb_dictionary_subpages(session: requests.Session, url: str) -> list[str]:
    response = session.get(url, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.content, "html.parser")
    base_url = response.url
    letter_urls: list[str] = []
    for a in soup.find_all("a"):
        text = a.get_text(strip=True)
        if len(text) == 1 and text.isalpha():
            href = a.get("href")
            if not href:
                continue
            full_url = urljoin(base_url, href)
            letter_urls.append(full_url)

    if url == "https://sonaveeb.ee/ds/mef":
        for idx, link in enumerate(letter_urls):
            if link == "https://sonaveeb.ee/ds/mef/r":
                letter_urls = letter_urls[idx:]
                break

    logger.info("Dictionary %s has %d letter pages.", url, len(letter_urls))
    return letter_urls


def fetch_sonaveeb_dictionary_entries(session: requests.Session, url: str) -> list[str]:
    response = session.get(url, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.content, "html.parser")
    all_links = soup.find_all("a")
    last_letter_index = None
    for i, link in enumerate(all_links):
        text = link.get_text(strip=True)
        if len(text) == 1 and text.isalpha():
            last_letter_index = i

    medical_term_urls: list[str] = []
    if last_letter_index is not None:
        for link in all_links[last_letter_index + 1 :]:
            text = link.get_text(strip=True)
            if not text or len(text) <= 1:
                continue
            href = link.get("href")
            if not href:
                continue
            full_url = urljoin(response.url, href)
            if full_url.startswith("https://sonaveeb.ee/search"):
                medical_term_urls.append(full_url)

    logger.info("Letter page %s has %d terms.", url, len(medical_term_urls))
    return medical_term_urls


def fetch_sonaveeb_dictionary_definitions(session: requests.Session, url: str):
    response = session.get(url, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    entries: list[tuple[str, str, str]] = []
    for item in soup.select("ul.homonym-list li.homonym-list-item"):
        term_el = item.select_one(".text-body-two span span") or item.select_one(".text-body-two span")
        desc_el = item.select_one(".homonym__text p") or item.select_one(".homonym__text")
        lang_el = item.select_one(".lang-code")

        if not term_el or not desc_el:
            continue

        term = term_el.get_text(strip=True)
        desc = desc_el.get_text(" ", strip=True)
        lang = lang_el.get_text(strip=True) if lang_el else ""

        if term and desc:
            entries.append((term, lang, desc))

    return entries or None


def load_visited(urls_path: Path) -> set[str]:
    if not urls_path.exists():
        return set()
    return set(urls_path.read_text(encoding="utf-8").splitlines())


def append_visited(urls_path: Path, url: str) -> None:
    with urls_path.open("a", encoding="utf-8") as handle:
        handle.write(url + "\n")


def ensure_csv_header(path: Path) -> None:
    if path.exists():
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["term", "lang", "desc"])


def append_row(path: Path, row: tuple[str, str, str]) -> None:
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(row)


def iter_all_term_urls(session: requests.Session, delay: float) -> Iterable[str]:
    for dictionary_url in DICTIONARIES:
        letter_pages = fetch_sonaveeb_dictionary_subpages(session, dictionary_url)
        for letter_page in letter_pages:
            term_urls = fetch_sonaveeb_dictionary_entries(session, letter_page)
            for term_url in term_urls:
                yield term_url
            if delay:
                time.sleep(delay)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Sonaveeb dictionary entries into data/sonaveeb.csv")
    parser.add_argument("--output", default=str(DATA_DIR / "sonaveeb.csv"))
    parser.add_argument("--visited", default=str(DATA_DIR / "sonaveeb_urls.txt"))
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset output and visited tracking before scraping.",
    )
    parser.add_argument("--max-terms", type=int, default=None)
    parser.add_argument("--user-agent", default="snomed-translation-bot/1.0")
    args = parser.parse_args()

    output_path = Path(args.output)
    visited_path = Path(args.visited)

    if args.reset:
        output_path.write_text("", encoding="utf-8")
        visited_path.write_text("", encoding="utf-8")

    ensure_csv_header(output_path)
    visited = load_visited(visited_path) if args.resume and not args.reset else set()

    session = requests.Session()
    session.headers.update({"User-Agent": args.user_agent})

    processed = 0
    logger.info("Starting Sonaveeb scrape (resume=%s).", args.resume)
    term_urls = iter_all_term_urls(session, args.delay)

    for term_url in tqdm(term_urls, desc="terms", unit="term"):
        if args.max_terms is not None and processed >= args.max_terms:
            break
        if term_url in visited:
            continue

        retries = 0
        while retries <= 3:
            try:
                results = fetch_sonaveeb_dictionary_definitions(session, term_url)
                if results:
                    for row in results:
                        append_row(output_path, row)
                append_visited(visited_path, term_url)
                visited.add(term_url)
                processed += 1
                break
            except Exception as exc:
                retries += 1
                logger.warning("Failed fetching %s (retry %d): %s", term_url, retries, exc)
                time.sleep(1.0)
        if args.delay:
            time.sleep(args.delay)

    logger.info("Finished. Wrote %d entries to %s", processed, output_path)


if __name__ == "__main__":
    main()

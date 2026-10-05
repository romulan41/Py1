import csv
import re
import sys

import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "https://www.4garden.ro"
ROOT_URL = f"{BASE_URL}/butasi-vita-de-vie/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def clean_text(text):
    return " ".join(text.split())


def normalize_url(url):
    url = " ".join(url.split())
    if not url:
        return url
    if "://" in url:
        scheme, rest = url.split("://", 1)
        rest = re.sub(r"/{2,}", "/", rest)
        url = f"{scheme}://{rest}"
    else:
        url = re.sub(r"/{2,}", "/", url)
    return url if url.endswith("/") else url + "/"


def is_category_url(url):
    return (
        url.startswith(ROOT_URL)
        and url != ROOT_URL
        and "/filtru/" not in url
        and not re.search(r"-p\d+/?$", url.rstrip("/"))
    )


def is_product_url(url):
    return bool(re.search(r"-p\d+/?$", url.rstrip("/"))) and url.startswith(ROOT_URL)


def get_categories():
    response = requests.get(ROOT_URL, headers=HEADERS, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    categories = []
    seen = set()

    for link in soup.select("a[href]"):
        href = normalize_url(link.get("href", "").strip())
        text = clean_text(link.get_text(" ", strip=True))
        if not href or not text:
            continue
        if is_category_url(href):
            if href not in seen:
                seen.add(href)
                categories.append((text, href))

    return categories


def get_varieties_for_category(category_url):
    response = requests.get(category_url, headers=HEADERS, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    names = []
    seen = set()

    for link in soup.select("a[href]"):
        href = normalize_url(link.get("href", "").strip())
        text = clean_text(link.get_text(" ", strip=True))
        if not href or not text:
            continue
        if href.startswith(category_url) and is_product_url(href):
            if text not in seen:
                seen.add(text)
                names.append(text)

    return names


def main():
    categories = get_categories()
    varieties_by_category = [
        (category_name, get_varieties_for_category(category_url))
        for category_name, category_url in categories
    ]

    with open("soiuri_vita_de_vie.tsv", "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile, delimiter="\t")
        writer.writerow(["Categorie", "Denumire soi"])

        for category_name, varieties in varieties_by_category:
            for variety_name in varieties:
                writer.writerow([category_name, variety_name])

    with open("4garden.txt", "w", encoding="utf-8") as textfile:
        for category_name, varieties in varieties_by_category:
            textfile.write(f"{category_name}\n")
            for variety_name in varieties:
                textfile.write(f"{variety_name}\n")
            textfile.write("\n")

    print("Soiurile au fost salvate in '4garden.txt' si 'soiuri_vita_de_vie.tsv'.")
    for category_name, varieties in varieties_by_category:
        print(f"\n{category_name}:")
        for variety_name in varieties:
            print(f"- {variety_name}")


if __name__ == "__main__":
    main()

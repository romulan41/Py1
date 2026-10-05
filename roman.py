import requests
from bs4 import BeautifulSoup
import csv

base_url = "https://pepinierele-roman.ro"
main_url = f"{base_url}/par/"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# 1️⃣ Extragem lista de soiuri și linkurile lor
response = requests.get(main_url, headers=headers)
soup = BeautifulSoup(response.text, "html.parser")

products = soup.find_all("h2", class_="woocommerce-loop-product__title")
names = [p.get_text(strip=True) for p in products]
links = [p.find_parent("a")["href"] for p in products]

# 2️⃣ Deschidem fișier CSV (tab-separated)
with open("soiuri_par.tsv", "w", newline="", encoding="utf-8") as csvfile:
    writer = csv.writer(csvfile, delimiter="\t")
    # Scriem header-ul
    writer.writerow(["Soi", "Perioada coacere", "Descriere", "Link"])

    # 3️⃣ Pentru fiecare soi, accesăm pagina și extragem datele
    for name, link in zip(names, links):
        res = requests.get(link, headers=headers)
        prod_soup = BeautifulSoup(res.text, "html.parser")

        # ---- Perioada de coacere ----
        span = prod_soup.find("span", class_="ct-span")
        perioada = span.get_text(strip=True) if span else "N/A"

        # ---- Descriere ----
        descr_div = prod_soup.find("div", class_="oxy-product-description")
        if descr_div:
            descriere = descr_div.get_text(separator=" ", strip=True)
            descriere = descriere.replace("Descriere:", "").strip()
        else:
            descriere = "N/A"

        # ---- Scriem în fișier ----
        writer.writerow([name, perioada, descriere, link])

print("Datele au fost salvate în 'soiuri_par.tsv'.")

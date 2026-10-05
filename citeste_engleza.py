import re
import time
import tkinter as tk
import tkinter.font as tkfont
from collections import deque
from collections.abc import Iterator
from pathlib import Path

from deep_translator import GoogleTranslator, MyMemoryTranslator


FISIER_Sursa = Path(__file__).with_name("carte_eng.txt")
FISIER_ENGLEZA = Path(__file__).with_name("engleza.txt")
FISIER_ROMANA = Path(__file__).with_name("romana.txt")
ABREVIERI = ("Mr", "Mrs", "Ms", "Dr", "Prof", "Rev", "St", "Jr", "Sr", "etc")
INTERVAL_AFISARE_MS = 10000


def imparte_propozitii(text: str) -> Iterator[str]:
	"""Împarte textul în propoziții, fără a separa abrevierile uzuale."""
	text = re.sub(r"\s+", " ", text).strip()
	inceput = 0

	for potrivire in re.finditer(r"""[.!?]+(?:["'”’)\]]*)?(?=\s|$)""", text):
		sfarsit = potrivire.end()
		propozitie = text[inceput:sfarsit].strip()
		abreviere = rf"\b(?:{'|'.join(ABREVIERI)})\.$"
		if re.search(abreviere, propozitie, re.IGNORECASE):
			continue
		if propozitie:
			yield propozitie
			inceput = sfarsit

	ultima_propozitie = text[inceput:].strip()
	if ultima_propozitie:
		yield ultima_propozitie


def tradu_in_romana(text_engleza: str) -> str:
	"""Traduce textul cu Google și folosește MyMemory ca rezervă."""
	try:
		return GoogleTranslator(source="english", target="romanian").translate(
			text_engleza
		)
	except Exception:
		return MyMemoryTranslator(source="english", target="romanian").translate(
			text_engleza
		)


def proceseaza_carte() -> None:
	timp_start = time.perf_counter()
	text = FISIER_Sursa.read_text(encoding="utf-8-sig")
	numar_propozitii = 0

	with FISIER_ENGLEZA.open(
		"w", encoding="utf-8", newline="\n"
	) as fisier_engleza:
		with FISIER_ROMANA.open(
			"w", encoding="utf-8", newline="\n"
		) as fisier_romana:
			for propozitie in imparte_propozitii(text):
				traducere = tradu_in_romana(propozitie)
				fisier_engleza.write(propozitie + "\n")
				fisier_romana.write(re.sub(r"\s+", " ", traducere).strip() + "\n")
				numar_propozitii += 1

	print(f"Am procesat {numar_propozitii} propozitii.")
	print(f"Timp de executie: {time.perf_counter() - timp_start:.2f} secunde.")


def citeste_perechi() -> list[tuple[str, str]]:
	linii_engleza = FISIER_ENGLEZA.read_text(encoding="utf-8-sig").splitlines()
	linii_romana = FISIER_ROMANA.read_text(encoding="utf-8-sig").splitlines()

	if not linii_engleza and linii_romana:
		propozitii = list(
			imparte_propozitii(FISIER_Sursa.read_text(encoding="utf-8-sig"))
		)
		if len(propozitii) == len(linii_romana):
			FISIER_ENGLEZA.write_text(
				"\n".join(propozitii) + "\n", encoding="utf-8"
			)
			linii_engleza = propozitii
			print("engleza.txt era gol; l-am refacut din carte_eng.txt.")

	if len(linii_engleza) != len(linii_romana):
		raise ValueError(
			"engleza.txt si romana.txt trebuie sa contina acelasi numar de "
			f"randuri (engleza: {len(linii_engleza)}, "
			f"romana: {len(linii_romana)})."
		)
	if not linii_engleza:
		raise ValueError("Nu exista propozitii de afisat in fisierele de text.")
	return [
		(" ".join(romana.split()), " ".join(engleza.split()))
		for engleza, romana in zip(linii_engleza, linii_romana)
	]


class FereastraGhid:
	"""Overlay de conversație cu stilul din j_w.py."""

	CULOARE_FUNDAL = "#202020"
	NUMAR_RANDURI = 4

	def __init__(self, perechi: list[tuple[str, str]]) -> None:
		self._perechi = perechi
		self._urmatoarea_propozitie = 0
		self._istoric: deque[tuple[str, str]] = deque(
			maxlen=self.NUMAR_RANDURI
		)
		self._x_apasare = 0
		self._y_apasare = 0
		self.root = tk.Tk()
		self.root.title("Ghid de conversatie")
		self.root.overrideredirect(True)
		self.root.configure(bg=self.CULOARE_FUNDAL)
		self.root.wm_attributes("-alpha", 0.82)
		self.root.wm_attributes("-topmost", True)
		self.root.bind_all("<Escape>", self._inchide)
		self.root.protocol("WM_DELETE_WINDOW", self._inchide)

		latime_ecran = self.root.winfo_screenwidth()
		self._inaltime_ecran = self.root.winfo_screenheight()
		self._latime = int(latime_ecran * 0.92)
		self._inaltime_linie = tkfont.Font(
			root=self.root,
			family="Segoe UI",
			size=32,
			weight="bold",
		).metrics("linespace")
		self._margine_verticala = 40
		self._spatiu_randuri = 8
		inaltime = (
			self._inaltime_linie * self.NUMAR_RANDURI
			+ self._margine_verticala * 2
		)
		x = (latime_ecran - self._latime) // 2
		self.root.geometry(f"{self._latime}x{inaltime}+{x}+20")

		self._etichete = []
		for index in range(self.NUMAR_RANDURI):
			eticheta = tk.Text(
				self.root,
				height=1,
				width=1,
				font=("Segoe UI", 32, "bold"),
				bg=self.CULOARE_FUNDAL,
				wrap="word",
				borderwidth=0,
				highlightthickness=0,
				padx=0,
				pady=0,
				takefocus=False,
			)
			eticheta.tag_configure(
				"romana", foreground="#1E90FF" if index == 3 else "#FFD700"
			)
			eticheta.tag_configure("engleza", foreground="#FF3333")
			eticheta.place(
				x=40,
				y=self._margine_verticala + index * self._inaltime_linie,
				width=self._latime - 80,
				height=self._inaltime_linie,
			)
			eticheta.bind("<ButtonPress-1>", self._incepe_mutarea)
			eticheta.bind("<B1-Motion>", self._muta_fereastra)
			self._etichete.append(eticheta)

		self.root.after(0, self._actualizeaza)

	def _incepe_mutarea(self, eveniment: tk.Event) -> None:
		self._x_apasare = eveniment.x_root - self.root.winfo_x()
		self._y_apasare = eveniment.y_root - self.root.winfo_y()

	def _muta_fereastra(self, eveniment: tk.Event) -> None:
		x = eveniment.x_root - self._x_apasare
		y = eveniment.y_root - self._y_apasare
		self.root.geometry(f"+{x}+{y}")

	def _actualizeaza(self) -> None:
		if self._urmatoarea_propozitie >= len(self._perechi):
			self.root.destroy()
			return

		self._istoric.append(self._perechi[self._urmatoarea_propozitie])
		self._urmatoarea_propozitie += 1
		mesaje = list(self._istoric)
		while len(mesaje) < self.NUMAR_RANDURI:
			mesaje.insert(0, ("", ""))

		for eticheta, (text_romana, text_engleza) in zip(
			self._etichete, mesaje
		):
			eticheta.configure(state="normal")
			eticheta.delete("1.0", "end")
			eticheta.insert("end", text_romana, "romana")
			if text_engleza:
				eticheta.insert("end", f" ({text_engleza})", "engleza")
			eticheta.configure(state="disabled")

		self.root.update_idletasks()
		inaltimi_randuri = []
		for eticheta in self._etichete:
			rezultat = eticheta.count("1.0", "end", "displaylines")
			numar_linii = rezultat[0] if rezultat else 0
			inaltimi_randuri.append(
				max(1, numar_linii) * self._inaltime_linie
			)

		y_rand = self._margine_verticala
		for eticheta, inaltime_rand in zip(
			self._etichete, inaltimi_randuri
		):
			eticheta.place_configure(y=y_rand, height=inaltime_rand)
			y_rand += inaltime_rand + self._spatiu_randuri

		inaltime = (
			y_rand - self._spatiu_randuri + self._margine_verticala
		)
		y_fereastra = min(
			self.root.winfo_y(),
			max(0, self._inaltime_ecran - inaltime - 20),
		)
		self.root.geometry(
			f"{self._latime}x{inaltime}"
			f"+{self.root.winfo_x()}+{y_fereastra}"
		)
		self.root.after(INTERVAL_AFISARE_MS, self._actualizeaza)

	def _inchide(self, _eveniment: tk.Event | None = None) -> None:
		self.root.destroy()

	def ruleaza(self) -> None:
		self.root.mainloop()


def afiseaza_ghid() -> None:
	FereastraGhid(citeste_perechi()).ruleaza()


def main() -> None:
	for fisier in (FISIER_ENGLEZA, FISIER_ROMANA):
		fisier.write_text("", encoding="utf-8")
	proceseaza_carte()
	afiseaza_ghid()


if __name__ == "__main__":
	main()

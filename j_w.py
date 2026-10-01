import asyncio
import msvcrt
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from queue import Empty, Queue
from threading import Event, Thread
import tkinter as tk
import tkinter.font as tkfont
import time

import edge_tts
import miniaudio
import numpy as np
import sounddevice as sd
import speech_recognition as sr
from argostranslate import translate as argos_translate
from faster_whisper import WhisperModel

REDA_VOCEA_ROMANA = False
MODEL_WHISPER = "small"
TipMesaj = tuple[str | None, str | None, str | None]
_model_whisper: WhisperModel | None = None


def gaseste_intrarea_vbcable() -> tuple[int, dict]:
	"""Găsește dispozitivul de captură VB-CABLE instalat în Windows."""
	dispozitive = sd.query_devices()
	candidate = [
		(index, dispozitiv)
		for index, dispozitiv in enumerate(dispozitive)
		if dispozitiv["max_input_channels"] > 0
		and "CABLE Output" in dispozitiv["name"]
	]
	if not candidate:
		raise RuntimeError(
			"Nu am găsit intrarea VB-CABLE. Verifică instalarea și redă sunetul "
			"prin dispozitivul «CABLE Input»."
		)
	return max(
		candidate,
		key=lambda item: (
			sd.query_hostapis(item[1]["hostapi"])["name"] == "Windows WASAPI",
			item[1]["max_input_channels"] == 2,
			item[1]["default_samplerate"],
		),
	)


def gaseste_iesiri_vocale() -> list[tuple[int, dict]]:
	"""Listează ieșirile hardware fără VB-CABLE sau driverul WDM-KS."""
	dispozitive = sd.query_devices()
	candidate = [
		(index, dispozitiv)
		for index, dispozitiv in enumerate(dispozitive)
		if dispozitiv["max_output_channels"] > 0
		and sd.query_hostapis(dispozitiv["hostapi"])["name"]
		in ("Windows WASAPI", "Windows DirectSound", "MME")
		and not any(
			termen in dispozitiv["name"].casefold()
			for termen in (
				"cable",
				"vb-audio",
				"microsoft sound mapper",
				"primary sound driver",
			)
		)
	]
	if not candidate:
		raise RuntimeError(
			"Nu am găsit o ieșire audio hardware separată de VB-CABLE."
		)
	prioritate_host = {"Windows WASAPI": 3, "Windows DirectSound": 2, "MME": 1}
	return sorted(
		candidate,
		key=lambda item: (
			prioritate_host[sd.query_hostapis(item[1]["hostapi"])["name"]],
			item[1]["max_output_channels"] == 2,
			item[1]["default_samplerate"],
		),
		reverse=True,
	)


def gaseste_iesirea_vocala() -> tuple[int, dict]:
	"""Alege prima ieșire hardware stabilă, evitând VB-CABLE."""
	return gaseste_iesiri_vocale()[0]


class _CititorAudio:
	def __init__(self, flux: sd.RawInputStream, canale: int) -> None:
		self._flux = flux
		self._canale = canale

	def read(self, cadre: int) -> bytes:
		date, _depasesc = self._flux.read(cadre)
		if self._canale == 1:
			return date
		stereo = np.frombuffer(date, dtype=np.int16).reshape(-1, self._canale)
		mono = stereo.astype(np.int32).mean(axis=1).astype(np.int16)
		return mono.tobytes()


class SursaVBCAble(sr.AudioSource):
	"""Adaptează intrarea sounddevice pentru detectarea pauzelor vocale."""

	def __init__(self, dispozitiv_index: int, frecventa: int) -> None:
		self.CHUNK = 1024
		self.SAMPLE_RATE = frecventa
		self.SAMPLE_WIDTH = 2
		self.stream = None
		self._dispozitiv_index = dispozitiv_index
		self._canale = min(2, int(sd.query_devices(dispozitiv_index)["max_input_channels"]))
		self._flux: sd.RawInputStream | None = None

	def __enter__(self):
		self._flux = sd.RawInputStream(
			samplerate=self.SAMPLE_RATE,
			device=self._dispozitiv_index,
			channels=self._canale,
			dtype="int16",
			blocksize=self.CHUNK,
		)
		self._flux.start()
		self.stream = _CititorAudio(self._flux, self._canale)
		return self

	def __exit__(self, exc_type, exc_value, traceback) -> None:
		if self._flux is not None:
			self._flux.stop()
			self._flux.close()
			self._flux = None
		self.stream = None


def recunoaste_si_tradu(
	audio: sr.AudioData,
	mesaje: Queue[TipMesaj],
) -> str:
	"""Transcrie japoneza, apoi o traduce în engleză și română."""
	text_japoneza = transcrie_cu_whisper(audio)
	text_engleza = pastreaza_intrebarea(
		tradu_in_engleza(text_japoneza), text_japoneza
	)
	text_romana = pastreaza_intrebarea(
		tradu_in_romana(text_engleza), text_engleza
	)
	mesaje.put((text_engleza, text_romana, None))
	return text_romana


def pastreaza_intrebarea(text: str, *surse: str) -> str:
	"""Păstrează semnul întrebării final din sursă în traducere."""
	if not any(este_intrebare(sursa) for sursa in surse):
		return text
	traducere = text.rstrip()
	while traducere.endswith((".", "!", "?", "。", "！", "？")):
		traducere = traducere[:-1].rstrip()
	return f"{traducere}?"


def este_intrebare(text: str) -> bool:
	"""Detectează întrebări punctuate și forme japoneze cu particula か."""
	terminare = text.rstrip().rstrip("\"'”’」』")
	if terminare.endswith(("?", "？")):
		return True
	terminare = terminare.rstrip("。.!！")
	return terminare.endswith(("か", "かな", "かなあ", "の"))


def tradu_in_romana(text_engleza: str) -> str:
	"""Traduce local engleza în română folosind Argos Translate."""
	text_curat = text_engleza.strip()
	text_normalizat = " ".join(
		text_curat.casefold().replace("’", "'").split()
	).rstrip(".,!?;:")
	if text_normalizat in ("i'll take it", "i will take it"):
		semn_punctuatie = (
			text_curat[-1]
			if text_curat.endswith((".", ",", "!", "?", ";", ":"))
			else ""
		)
		return f"Îl iau{semn_punctuatie}"
	return argos_translate.translate(text_engleza, "en", "ro")


def tradu_in_engleza(text_japoneza: str) -> str:
	"""Traduce local japoneza în engleză folosind Argos Translate."""
	return argos_translate.translate(text_japoneza, "ja", "en")


def transcrie_cu_whisper(audio: sr.AudioData) -> str:
	"""Transcrie audio japonez local cu faster-whisper."""
	global _model_whisper
	if _model_whisper is None:
		_model_whisper = WhisperModel(
			MODEL_WHISPER,
			device="cpu",
			compute_type="int8",
		)
	date_audio = audio.get_raw_data(convert_rate=16000, convert_width=2)
	semnal = np.frombuffer(date_audio, dtype=np.int16).astype(np.float32) / 32768.0
	segmente, _informatii = _model_whisper.transcribe(
		semnal,
		language="ja",
		beam_size=5,
		vad_filter=True,
	)
	text = " ".join(segment.text.strip() for segment in segmente).strip()
	if not text:
		raise sr.UnknownValueError()
	return text


async def genereaza_voce(text: str) -> bytes:
	"""Generează voce românească în memorie, fără fișier audio temporar."""
	fragmente = []
	comunicator = edge_tts.Communicate(text, "ro-RO-AlinaNeural")
	async for fragment in comunicator.stream():
		if fragment["type"] == "audio":
			fragmente.append(fragment["data"])
	return b"".join(fragmente)


def reda_subtitrarea(text: str, dispozitiv_index: int) -> None:
	"""Redă vocea și încearcă alt driver dacă ieșirea principală eșuează."""
	try:
		date_audio = asyncio.run(genereaza_voce(text))
		iesiri = gaseste_iesiri_vocale()
		iesiri.sort(key=lambda item: item[0] != dispozitiv_index)
		erori = []
		for index, dispozitiv in iesiri:
			frecventa = int(dispozitiv["default_samplerate"])
			try:
				pcm = miniaudio.decode(
					date_audio,
					output_format=miniaudio.SampleFormat.SIGNED16,
					nchannels=1,
					sample_rate=frecventa,
				)
				semnal = np.frombuffer(pcm.samples, dtype=np.int16)
				sd.play(semnal, samplerate=frecventa, device=index, blocking=True)
				if index != dispozitiv_index:
					api = sd.query_hostapis(dispozitiv["hostapi"])["name"]
					print(f"Vocea română redată prin alternativa {api}.", flush=True)
				return
			except Exception as eroare:
				erori.append(f"{dispozitiv['name']}: {eroare}")
				try:
					sd.stop()
				except Exception:
					pass
		print("Eroare la toate ieșirile audio: " + " | ".join(erori), flush=True)
	except Exception as eroare:
		print(f"Eroare la redarea vocii românești: {eroare}", flush=True)


class FereastraSubtitrari:
	"""Overlay transparent, mereu deasupra, pentru traducerea românească."""

	CULOARE_FUNDAL = "#202020"

	def __init__(
		self,
		mesaje: Queue[TipMesaj],
		oprire: Event,
	) -> None:
		self._mesaje = mesaje
		self._oprire = oprire
		self._x_apasare = 0
		self._y_apasare = 0
		self.root = tk.Tk()
		self.root.title("Subtitrare în română")
		self.root.overrideredirect(True)
		self.root.configure(bg=self.CULOARE_FUNDAL)
		self.root.wm_attributes("-alpha", 0.82)
		self.root.wm_attributes("-topmost", True)

		latime_ecran = self.root.winfo_screenwidth()
		inaltime_ecran = self.root.winfo_screenheight()
		latime = int(latime_ecran * 0.92)
		self._inaltime_linie = tkfont.Font(
			root=self.root,
			family="Segoe UI",
			size=32,
			weight="bold",
		).metrics("linespace")
		self._margine_verticala = 40
		self._spatiu_randuri = 8
		inaltime_rand = self._inaltime_linie
		inaltime = inaltime_rand * 4 + self._margine_verticala * 2
		x = (latime_ecran - latime) // 2
		y = 20
		self.root.geometry(f"{latime}x{inaltime}+{x}+{y}")
		self._latime = latime
		self._inaltime_ecran = inaltime_ecran

		self._istoric: deque[tuple[str, str]] = deque(maxlen=4)
		self._etichete_istoric = []
		for index in range(4):
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
				y=self._margine_verticala + index * inaltime_rand,
				width=latime - 80,
				height=inaltime_rand,
			)
			self._leaga_mutarea(eticheta)
			self._etichete_istoric.append(eticheta)
		self.root.bind_all("<Escape>", self._inchide)
		self.root.after(100, self._actualizeaza)



	def _leaga_mutarea(self, widget: tk.Misc) -> None:
		widget.bind("<ButtonPress-1>", self._incepe_mutarea)
		widget.bind("<B1-Motion>", self._muta_fereastra)

	def _incepe_mutarea(self, eveniment: tk.Event) -> None:
		self._x_apasare = eveniment.x_root - self.root.winfo_x()
		self._y_apasare = eveniment.y_root - self.root.winfo_y()

	def _muta_fereastra(self, eveniment: tk.Event) -> None:
		x = eveniment.x_root - self._x_apasare
		y = eveniment.y_root - self._y_apasare
		self.root.geometry(f"+{x}+{y}")

	def _actualizeaza(self) -> None:
		if self._oprire.is_set():
			self.root.destroy()
			return
		while True:
			try:
				text_engleza, text_romana, _text_romana_directa = (
					self._mesaje.get_nowait()
				)
			except Empty:
				break
			if text_romana is not None and text_romana != "Se traduce...":
				linie = (text_romana, text_engleza or "")
				if not self._istoric or self._istoric[-1] != linie:
					self._istoric.append(linie)

		mesaje = list(self._istoric)
		while len(mesaje) < 4:
			mesaje.insert(0, ("", ""))
		for eticheta, (text_romana, text_engleza) in zip(
			self._etichete_istoric, mesaje[-4:]
		):
			eticheta.configure(state="normal")
			eticheta.delete("1.0", "end")
			eticheta.insert("end", text_romana, "romana")
			if text_engleza:
				eticheta.insert("end", f" ({text_engleza})", "engleza")
			eticheta.configure(state="disabled")

		self.root.update_idletasks()
		inaltimi_randuri = []
		for eticheta in self._etichete_istoric:
			rezultat_numar_linii = eticheta.count(
				"1.0", "end", "displaylines"
			)
			numar_linii = (
				rezultat_numar_linii[0] if rezultat_numar_linii else 0
			)
			inaltimi_randuri.append(
				max(1, numar_linii) * self._inaltime_linie
			)

		y_rand = self._margine_verticala
		for eticheta, inaltime_rand in zip(
			self._etichete_istoric, inaltimi_randuri
		):
			eticheta.place_configure(y=y_rand, height=inaltime_rand)
			y_rand += inaltime_rand + self._spatiu_randuri
		inaltime = (
			y_rand
			- self._spatiu_randuri
			+ self._margine_verticala
		)
		y_fereastra = min(
			self.root.winfo_y(),
			max(0, self._inaltime_ecran - inaltime - 20),
		)
		self.root.geometry(
			f"{self._latime}x{inaltime}"
			f"+{self.root.winfo_x()}+{y_fereastra}"
		)
		self.root.after(100, self._actualizeaza)

	def _inchide(self, _eveniment: tk.Event | None = None) -> None:
		self._oprire.set()
		self.root.destroy()

	def ruleaza(self) -> None:
		self.root.mainloop()


def asculta_si_tradu(
	mesaje: Queue[TipMesaj], oprire: Event
) -> None:
	"""Ascultă VB-CABLE și afișează doar traducerea românească."""
	dispozitiv_index, dispozitiv = gaseste_intrarea_vbcable()
	if REDA_VOCEA_ROMANA:
		iesire_index, iesire = gaseste_iesirea_vocala()
	frecventa = int(dispozitiv["default_samplerate"])
	fragmente_in_curs: list[Future[str]] = []
	audio_in_asteptare: list[sr.AudioData] = []
	recunoastere = sr.Recognizer()
	recunoastere.pause_threshold = 1.0
	recunoastere.non_speaking_duration = 0.5
	recunoastere.phrase_threshold = 0.25

	print(f"Ascult din: {dispozitiv['name']}")
	if REDA_VOCEA_ROMANA:
		api_iesire = sd.query_hostapis(iesire["hostapi"])["name"]
		print(f"Vocea română se redă prin: {iesire['name']} ({api_iesire})")
	else:
		print("Redarea vocii românești este dezactivată.")
	print("Subtitrările apar aici. Apasă q în această fereastră pentru a închide.")
	try:
		with ThreadPoolExecutor(max_workers=2) as executor:
			with ThreadPoolExecutor(max_workers=1) as executor_voce:
				with SursaVBCAble(dispozitiv_index, frecventa) as sursa_audio:
					ascultare = executor.submit(
						recunoastere.listen, sursa_audio, 1.0, 30.0
					)
					while not oprire.is_set():
						if ascultare.done():
							try:
								audio = ascultare.result()
								audio_in_asteptare.append(audio)
							except sr.WaitTimeoutError:
								pass
							ascultare = executor.submit(
								recunoastere.listen, sursa_audio, 1.0, 30.0
							)

						while audio_in_asteptare and len(fragmente_in_curs) < 1:
							fragmente_in_curs.append(
								executor.submit(
									recunoaste_si_tradu,
									audio_in_asteptare.pop(0),
									mesaje,
								)
							)

						while fragmente_in_curs and fragmente_in_curs[0].done():
							fragment_incheiat = fragmente_in_curs.pop(0)
							try:
								text_romana = fragment_incheiat.result()
								print(f"\n{text_romana}\n", flush=True)
								if REDA_VOCEA_ROMANA:
									executor_voce.submit(
										reda_subtitrarea,
										text_romana,
										iesire_index,
									)
							except sr.UnknownValueError:
								pass
							except sr.RequestError as eroare:
								print(f"Eroare la recunoașterea vocală: {eroare}")
							except Exception as eroare:
								print(f"Eroare la traducere: {eroare}")
						time.sleep(0.01)
	except KeyboardInterrupt:
		print("\nAscultarea a fost oprită.")


def asteapta_tasta_q(oprire: Event) -> None:
	while not oprire.is_set():
		if msvcrt.kbhit() and msvcrt.getwch().casefold() == "q":
			print("\nSe închide aplicația de subtitrare.", flush=True)
			oprire.set()
			return
		time.sleep(0.05)


def main() -> None:
	mesaje: Queue[TipMesaj] = Queue()
	oprire = Event()
	fereastra = FereastraSubtitrari(mesaje, oprire)
	thread_audio = Thread(
		target=asculta_si_tradu, args=(mesaje, oprire), daemon=True
	)
	thread_audio.start()
	Thread(target=asteapta_tasta_q, args=(oprire,), daemon=True).start()
	fereastra.ruleaza()


if __name__ == "__main__":
	main()

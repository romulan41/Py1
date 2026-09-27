import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
import time

import edge_tts
import miniaudio
import numpy as np
import sounddevice as sd
import speech_recognition as sr
from deep_translator import GoogleTranslator, MyMemoryTranslator


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


def recunoaste_si_tradu(audio: sr.AudioData) -> tuple[str, str]:
	"""Recunoaște vorbirea în engleză cu Google și o traduce în română."""
	text_engleza = sr.Recognizer().recognize_google(audio, language="en-US")
	text_romana = tradu_in_romana(text_engleza)
	return text_engleza, text_romana


def tradu_in_romana(text_engleza: str) -> str:
	"""Traduce textul cu Google și folosește MyMemory doar ca rezervă."""
	try:
		return GoogleTranslator(source="english", target="romanian").translate(
			text_engleza
		)
	except Exception:
		return MyMemoryTranslator(source="english", target="romanian").translate(
			text_engleza
		)


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


def asculta_si_tradu() -> None:
	"""Ascultă continuu VB-CABLE și afișează subtitrări traduse."""
	dispozitiv_index, dispozitiv = gaseste_intrarea_vbcable()
	iesire_index, iesire = gaseste_iesirea_vocala()
	frecventa = int(dispozitiv["default_samplerate"])
	fragmente_in_curs: list[Future[tuple[str, str]]] = []
	audio_in_asteptare: list[sr.AudioData] = []
	recunoastere = sr.Recognizer()
	recunoastere.pause_threshold = 2.0
	recunoastere.non_speaking_duration = 0.5
	recunoastere.phrase_threshold = 0.25

	print(f"Ascult din: {dispozitiv['name']}")
	api_iesire = sd.query_hostapis(iesire["hostapi"])["name"]
	print(f"Vocea română se redă prin: {iesire['name']} ({api_iesire})")
	print("Subtitrările apar aici. Oprește ascultarea cu Ctrl+C.")
	try:
		with ThreadPoolExecutor(max_workers=2) as executor:
			with ThreadPoolExecutor(max_workers=1) as executor_voce:
				with SursaVBCAble(dispozitiv_index, frecventa) as sursa_audio:
					ascultare = executor.submit(
						recunoastere.listen, sursa_audio, 1.0, 30.0
					)
					while True:
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
								)
							)

						while fragmente_in_curs and fragmente_in_curs[0].done():
							fragment_incheiat = fragmente_in_curs.pop(0)
							try:
								text_engleza, subtitrare = fragment_incheiat.result()
								print(f"\nEN: {text_engleza}\nRO: {subtitrare}\n", flush=True)
								executor_voce.submit(
									reda_subtitrarea,
									subtitrare,
									iesire_index,
								)
							except sr.UnknownValueError:
								pass
							except sr.RequestError as eroare:
								print(f"Eroare la recunoașterea vocală: {eroare}")
							except Exception as eroare:
								print(f"Eroare la traducere: {eroare}")
						time.sleep(0.05)
	except KeyboardInterrupt:
		print("\nAscultarea a fost oprită.")


if __name__ == "__main__":
	try:
		asculta_si_tradu()
	except RuntimeError as eroare:
		raise SystemExit(str(eroare)) from eroare

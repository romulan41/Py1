import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
from queue import Empty, Queue
from threading import Event, Thread
import tkinter as tk
import time

import edge_tts
import miniaudio
import numpy as np
import sounddevice as sd
import speech_recognition as sr
from faster_whisper import WhisperModel
import argostranslate.translate

REDA_VOCEA_ROMANA = False

# (text_romana, este_final) - None pentru "se traduce"
TipMesaj = tuple[str | None, bool]

# Cate randuri de subtitrare se pastreaza simultan pe ecran
RANDURI_VIZIBILE = 3
# Cate secunde se ruleaza o traducere partiala inainte de alta (evita spam-ul)
INTERVAL_PARTIAL = 0.45

# Initializare model Whisper offline (foloseste "base" sau "small")
print("Se încarcă modelul Whisper local (offline)...")
model_whisper = WhisperModel("base", device="cpu", compute_type="int8")
print("Modelul Whisper este gata!")


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


def recunoaste_japoneza_segment(
    audio: sr.AudioData,
    mesaje: Queue[TipMesaj],
) -> str:
    """Transcrie în japoneză segment cu segment, trimițând fiecare bucată nouă."""
    raw_bytes = audio.get_raw_data(convert_rate=16000, convert_width=2)
    audio_np = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    segmente, _info = model_whisper.transcribe(
        audio_np, language="ja", beam_size=5, word_timestamps=True
    )

    bucati: list[str] = []
    ultima_traducere = 0.0
    for segment in segmente:
        text_segment = segment.text.strip()
        if not text_segment:
            continue
        bucati.append(text_segment)

        # Traducere parțială imediată: primul segment se afișează fără întârziere.
        acum = time.monotonic()
        if not ultima_traducere or (acum - ultima_traducere) >= INTERVAL_PARTIAL:
            ultima_traducere = acum
            mesaje.put((tradu_in_romana("".join(bucati)), False))

    text_japoneza = " ".join(bucati).strip()
    if text_japoneza:
        mesaje.put((tradu_in_romana(text_japoneza), True))
    return text_japoneza


def este_intrebare(text: str) -> bool:
    """Detectează întrebări punctuate și forme japoneze cu particula か."""
    terminare = text.rstrip().rstrip("\"'”’」』")
    if terminare.endswith(("?", "？")):
        return True
    terminare = terminare.rstrip("。.!！")
    return terminare.endswith(("か", "かな", "かなあ", "の"))


def pastreaza_intrebarea(text: str, *surse: str) -> str:
    """Păstrează semnul întrebării final din sursă în traducere."""
    if not any(este_intrebare(sursa) for sursa in surse):
        return text
    traducere = text.rstrip()
    while traducere.endswith((".", "!", "?", "。", "！", "？")):
        traducere = traducere[:-1].rstrip()
    return f"{traducere}?"


def tradu_in_romana(text_japoneza: str) -> str:
    """Traduce offline direct din japoneză în română (fără pas intermediar)."""
    text_japoneza = text_japoneza.strip()
    if not text_japoneza:
        return ""
    try:
        return pastreaza_intrebarea(
            argostranslate.translate.translate(text_japoneza, "ja", "ro"),
            text_japoneza,
        )
    except Exception:
        # Pachetul ja->ro poate lipsi: arată textul original, nu o eroare.
        return text_japoneza


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
    """Overlay transparent cu subtitrare doar în română, una sub alta."""

    CULOARE_TRANSPARENTA = "#010203"
    CULOARE_RAND_NOU = "#FFFF00"
    CULOARE_RAND_VECHI = "#8A7F00"
    DIMENSIUNE_FONT = 30
    PAS_INTRE_RANDURI = 46

    def __init__(
        self,
        mesaje: Queue[TipMesaj],
        oprire: Event,
    ) -> None:
        self._mesaje = mesaje
        self._oprire = oprire
        self._x_apasare = 0
        self._y_apasare = 0
        # Lista de randuri: cel mai recent este primul element.
        self._randuri: list[str] = []
        # Perechi (eticheta, variabila text) pentru randurile deja finalizate.
        self._etichete: list[tuple[tk.Label, tk.StringVar]] = []

        self.root = tk.Tk()
        self.root.title("Subtitrare RO (Offline)")
        self.root.overrideredirect(True)
        self.root.configure(bg=self.CULOARE_TRANSPARENTA)
        self.root.wm_attributes("-transparentcolor", self.CULOARE_TRANSPARENTA)
        self.root.wm_attributes("-alpha", 1.0)
        self.root.wm_attributes("-topmost", True)

        latime_ecran = self.root.winfo_screenwidth()
        inaltime_ecran = self.root.winfo_screenheight()
        latime = int(latime_ecran * 0.9)
        # Un rand pentru fiecare subtitrare finalizata + randul activ.
        inaltime = (RANDURI_VIZIBILE + 1) * self.PAS_INTRE_RANDURI + 60
        x = (latime_ecran - latime) // 2
        y = max(0, inaltime_ecran - inaltime - 120)
        self.root.geometry(f"{latime}x{inaltime}+{x}+{y}")

        for rand in range(RANDURI_VIZIBILE):
            variabila = tk.StringVar(master=self.root, value="")
            eticheta = self._creeaza_rand(
                variabila,
                latime - 60,
                40 + rand * self.PAS_INTRE_RANDURI,
                culoare_text=self.CULOARE_RAND_VECHI,
            )
            self._etichete.append((eticheta, variabila))

        # Randul activ: textul care "crește" in timp real.
        self._text_in_curs = tk.StringVar(
            master=self.root, value="Se așteaptă sunetul japonez..."
        )
        self._creeaza_rand(
            self._text_in_curs,
            latime - 60,
            40 + RANDURI_VIZIBILE * self.PAS_INTRE_RANDURI,
            culoare_text=self.CULOARE_RAND_NOU,
        )

        self.root.bind_all("<Escape>", self._inchide)
        self.root.after(100, self._actualizeaza)

    def _creeaza_rand(
        self,
        text: tk.StringVar,
        latime_maxima: int,
        pozitie_y: int,
        culoare_text: str,
    ) -> tk.Label:
        """Creează un rând cu contur de umbră în 8 direcții, ca în j_off.py."""
        font = ("Segoe UI", self.DIMENSIUNE_FONT, "bold")
        for deplasare_x, deplasare_y in (
            (-1, 0),
            (1, 0),
            (0, -1),
            (0, 1),
            (-1, -1),
            (-1, 1),
            (1, -1),
            (1, 1),
        ):
            umbra = tk.Label(
                self.root,
                textvariable=text,
                font=font,
                fg="#000000",
                bg=self.CULOARE_TRANSPARENTA,
                wraplength=latime_maxima,
                justify="center",
                borderwidth=0,
            )
            umbra.place(relx=0.5, y=pozitie_y + deplasare_y, x=deplasare_x, anchor="center")
            self._leaga_mutarea(umbra)

        eticheta = tk.Label(
            self.root,
            textvariable=text,
            font=font,
            fg=culoare_text,
            bg=self.CULOARE_TRANSPARENTA,
            wraplength=latime_maxima,
            justify="center",
            borderwidth=0,
        )
        eticheta.place(relx=0.5, y=pozitie_y, anchor="center")
        self._leaga_mutarea(eticheta)
        return eticheta

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

    def _actualizeaza_randuri(self) -> None:
        """Randează lista de texte: cel mai nou sus, cele vechi se estompează."""
        for pozitie, (eticheta, variabila) in enumerate(self._etichete):
            if pozitie < len(self._randuri):
                variabila.set(self._randuri[pozitie])
                eticheta.configure(
                    fg=self.CULOARE_RAND_NOU if pozitie == 0 else self.CULOARE_RAND_VECHI
                )
            else:
                variabila.set("")

    def _adauga_rand_final(self, text: str) -> None:
        if not text:
            return
        self._randuri.insert(0, text)
        del self._randuri[RANDURI_VIZIBILE:]
        self._actualizeaza_randuri()
        self._text_in_curs.set("")

    def _actualizeaza(self) -> None:
        while True:
            try:
                text, este_final = self._mesaje.get_nowait()
            except Empty:
                break
            if text is None:
                continue
            if este_final:
                self._adauga_rand_final(text)
            else:
                # Textul "crește" în timp real, ca în Google Translate.
                self._text_in_curs.set(text)
        self.root.after(100, self._actualizeaza)

    def _inchide(self, _eveniment: tk.Event | None = None) -> None:
        self._oprire.set()
        self.root.destroy()

    def ruleaza(self) -> None:
        self.root.mainloop()


def asculta_si_tradu(
    mesaje: Queue[TipMesaj], oprire: Event
) -> None:
    """Ascultă VB-CABLE, transcrie local cu Whisper și traduce doar în română."""
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
    print("Subtitrarea apare aici, doar în română. Oprește cu Esc.")
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
                                    recunoaste_japoneza_segment,
                                    audio_in_asteptare.pop(0),
                                    mesaje,
                                )
                            )

                        while fragmente_in_curs and fragmente_in_curs[0].done():
                            fragment_incheiat = fragmente_in_curs.pop(0)
                            try:
                                text_japoneza = fragment_incheiat.result()
                                if text_japoneza:
                                    print(f"\nJA: {text_japoneza}", flush=True)
                                    if REDA_VOCEA_ROMANA:
                                        executor_voce.submit(
                                            reda_subtitrarea,
                                            tradu_in_romana(text_japoneza),
                                            iesire_index,
                                        )
                            except Exception as eroare:
                                print(f"Eroare la procesare: {eroare}")
                        time.sleep(0.01)
    except KeyboardInterrupt:
        print("\nAscultarea a fost oprită.")


def main() -> None:
    # Instalează o singură dată pachetul direct japoneză -> română.
    try:
        argostranslate.package.update_package_index()
        for p in argostranslate.package.get_available_packages():
            if p.from_code == "ja" and p.to_code == "ro":
                argostranslate.package.install_from_path(p.download())
    except Exception:
        pass

    mesaje: Queue[TipMesaj] = Queue()
    oprire = Event()
    fereastra = FereastraSubtitrari(mesaje, oprire)
    thread_audio = Thread(
        target=asculta_si_tradu, args=(mesaje, oprire), daemon=True
    )
    thread_audio.start()
    fereastra.ruleaza()


if __name__ == "__main__":
    main()

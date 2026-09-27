# Importă modulul pentru rularea funcțiilor asincrone.
import asyncio
# Importă clasa Path pentru lucrul cu căi de fișiere.
from pathlib import Path

# Importă biblioteca Edge TTS pentru generarea vocii neurale.
import edge_tts
# Importă traducătorul MyMemory pentru traducerea online din română în engleză.
from deep_translator import MyMemoryTranslator


# Obține folderul în care se află acest script.
base_dir = Path(__file__).resolve().parent
# Stabilește calea fișierului românesc care va fi citit.
source_path = base_dir / "romana.txt"
# Stabilește calea fișierului cu traducerea în engleză.
translation_path = base_dir / "engleza.txt"
# Stabilește calea fișierului MP3 care va fi generat.
audio_path = base_dir / "engleza.mp3"

# Citește textul românesc folosind codarea UTF-8.
source_text = source_path.read_text(encoding="utf-8")
# Creează traducătorul pentru limba română către limba engleză.
translator = MyMemoryTranslator(source="romanian", target="english")
# Definește traduceri corecte pentru expresiile prezente în fișierul sursă.
known_translations = {
	"bună dimineața.": "Good morning.",
	"bună ziua.": "Good afternoon.",
	"bună seara.": "Good evening.",
	"la revedere.": "Goodbye.",
	"pe curând.": "See you soon.",
	"pe mai târziu.": "See you later.",
	"domnișoară.": "Miss.",
	"doamnă.": "Mrs.",
	"domn.": "Mr.",
}
# Separă liniile pentru a păstra și poziția liniilor goale.
source_lines = source_text.splitlines()
# Selectează liniile necunoscute pentru traducerea online batch.
unknown_lines = [line for line in source_lines if line.strip() and line.strip().casefold() not in known_translations]
# Traduce liniile necunoscute într-o singură cerere către serviciul online.
translated_unknown = translator.translate_batch(unknown_lines) if unknown_lines else []
# Creează un iterator pentru rezultatele traducerilor necunoscute.
unknown_iterator = iter(translated_unknown)
# Reface textul, păstrând liniile goale și traducerile cunoscute.
translated_lines = []
# Parcurge liniile originale în aceeași ordine.
for line in source_lines:
	# Păstrează liniile goale fără traducere.
	if not line.strip():
		translated_lines.append("")
	# Folosește traducerea verificată pentru expresiile cunoscute.
	elif line.strip().casefold() in known_translations:
		translated_lines.append(known_translations[line.strip().casefold()])
	# Folosește rezultatul online pentru orice linie nouă.
	else:
		translated_lines.append(next(unknown_iterator))
# Unește liniile traduse într-un singur text.
translated_text = "\n".join(translated_lines)
# Păstrează linia finală dacă fișierul original o avea.
if source_text.endswith("\n"):
	translated_text += "\n"
# Scrie traducerea în fișierul englezesc.
translation_path.write_text(translated_text, encoding="utf-8")

# Alege vocea neurală în limba engleză.
voice = "en-US-AriaNeural"


# Definește o funcție asincronă pentru generarea fișierului audio.
async def generate_audio() -> None:
	# Creează obiectul care transformă textul tradus în voce.
	communicator = edge_tts.Communicate(translated_text, voice)
	# Salvează vocea generată în fișierul MP3.
	await communicator.save(str(audio_path))


# Pornește și execută funcția asincronă.
asyncio.run(generate_audio())

# Afișează locațiile fișierelor create.
print(f"Translation generated: {translation_path}")
print(f"Audio generated: {audio_path}")

import asyncio
from pathlib import Path

import edge_tts
from deep_translator import MyMemoryTranslator


FOLDER = Path(__file__).resolve().parent
ROMANIAN_FILE = FOLDER / "romana.txt"
ENGLISH_FILE = FOLDER / "engleza.txt"
AUDIO_FILE = FOLDER / "romana-engleza.mp3"

def tradu_in_engleza(linii_romana: list[str]) -> list[str]:
	"""Traduce textul românesc și scrie traducerea în engleza.txt."""
	traducator = MyMemoryTranslator(source="romanian", target="english")
	text_romana = "\n".join(linii_romana)
	text_englez = traducator.translate(text_romana)
	linii_engleza = text_englez.splitlines()
	if len(linii_engleza) != len(linii_romana):
		raise ValueError("Serviciul de traducere a schimbat numărul liniilor.")

	if ROMANIAN_FILE.read_text(encoding="utf-8").endswith("\n"):
		text_englez += "\n"
	ENGLISH_FILE.write_text(text_englez, encoding="utf-8")
	return linii_engleza


async def genereaza_mp3_bilingv(
	linii_romana: list[str], linii_engleza: list[str]
) -> None:
	"""Creează un MP3 în care fiecare linie se aude în română și engleză."""
	voce_romana = "ro-RO-AlinaNeural"
	voce_engleza = "en-US-AriaNeural"
	fragmente_audio = []

	for linie_romana, linie_engleza in zip(linii_romana, linii_engleza):
		for text, voce in (
			(linie_romana.strip(), voce_romana),
			(linie_engleza.strip(), voce_engleza),
		):
			if not text:
				continue
			comunicator = edge_tts.Communicate(text, voce)
			async for fragment in comunicator.stream():
				if fragment["type"] == "audio":
					fragmente_audio.append(fragment["data"])

	if not fragmente_audio:
		raise ValueError("romana.txt nu conține text de transformat în audio.")
	AUDIO_FILE.write_bytes(b"".join(fragmente_audio))


def main() -> None:
	if not ROMANIAN_FILE.exists():
		raise SystemExit(f"Nu am găsit fișierul sursă: {ROMANIAN_FILE}")

	text_romana = ROMANIAN_FILE.read_text(encoding="utf-8")
	linii_romana = text_romana.splitlines()
	if not any(linie.strip() for linie in linii_romana):
		raise SystemExit("romana.txt este gol.")

	linii_engleza = tradu_in_engleza(linii_romana)
	asyncio.run(genereaza_mp3_bilingv(linii_romana, linii_engleza))
	print(f"English text created: {ENGLISH_FILE}")
	print(f"Bilingual audio created: {AUDIO_FILE}")


if __name__ == "__main__":
	main()

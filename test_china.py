import argparse
import asyncio
import os
from pathlib import Path

import edge_tts
from deep_translator import MyMemoryTranslator


BASE_DIR = Path(__file__).resolve().parent
ROMANIAN_FILE = BASE_DIR / "romana.txt"
ENGLISH_FILE = BASE_DIR / "engleza.txt"
AUDIO_FILE = BASE_DIR / "romana.engleza.mp3"

KNOWN_TRANSLATIONS = {
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


def create_english_translation(romanian_lines: list[str]) -> list[str]:
	"""Traduce liniile românești și salvează rezultatul în engleza.txt."""
	unknown_lines = [
		line
		for line in romanian_lines
		if line.strip() and line.strip().casefold() not in KNOWN_TRANSLATIONS
	]

	if unknown_lines:
		translator = MyMemoryTranslator(source="romanian", target="english")
		unknown_translations = iter(translator.translate_batch(unknown_lines))
	else:
		unknown_translations = iter(())

	english_lines = []
	for line in romanian_lines:
		normalized_line = line.strip().casefold()
		if not normalized_line:
			english_lines.append("")
		elif normalized_line in KNOWN_TRANSLATIONS:
			english_lines.append(KNOWN_TRANSLATIONS[normalized_line])
		else:
			english_lines.append(next(unknown_translations))

	english_text = "\n".join(english_lines)
	if ROMANIAN_FILE.read_text(encoding="utf-8").endswith("\n"):
		english_text += "\n"
	ENGLISH_FILE.write_text(english_text, encoding="utf-8")
	return english_lines


async def create_bilingual_audio(
	romanian_lines: list[str], english_lines: list[str]
) -> None:
	"""Creează un MP3 cu fiecare replică întâi în română, apoi în engleză."""
	romanian_voice = "ro-RO-AlinaNeural"
	english_voice = "en-US-AriaNeural"
	audio_chunks = []

	for romanian_line, english_line in zip(romanian_lines, english_lines):
		for text, voice in (
			(romanian_line.strip(), romanian_voice),
			(english_line.strip(), english_voice),
		):
			if not text:
				continue
			communicator = edge_tts.Communicate(text, voice)
			async for chunk in communicator.stream():
				if chunk["type"] == "audio":
					audio_chunks.append(chunk["data"])

	AUDIO_FILE.write_bytes(b"".join(audio_chunks))


def run_gemini_chat() -> None:
	"""Pornește chatul Gemini, dacă utilizatorul cere explicit această opțiune."""
	from google import genai

	api_key = os.getenv("GEMINI_API_KEY")
	if not api_key:
		raise SystemExit("Setează variabila de mediu GEMINI_API_KEY pentru chatul Gemini.")

	chat = genai.Client(api_key=api_key).chats.create(model="gemini-3.8-flash")
	print("Chat Gemini pornit. Scrie 'iesire' pentru a opri.")
	while True:
		question = input("\nTu: ")
		if question.strip().casefold() == "iesire":
			print("La revedere!")
			break
		if not question.strip():
			continue
		try:
			response = chat.send_message(question)
			print(f"\nGemini: {response.text}")
		except Exception as error:
			print(f"Eroare la conectarea cu Gemini: {error}")


def main() -> None:
	parser = argparse.ArgumentParser(
		description="Traduce romana.txt și generează un MP3 bilingv."
	)
	parser.add_argument(
		"--chat",
		action="store_true",
		help="pornește chatul Gemini în loc să genereze fișierele audio",
	)
	args = parser.parse_args()

	if args.chat:
		run_gemini_chat()
		return

	romanian_lines = ROMANIAN_FILE.read_text(encoding="utf-8").splitlines()
	english_lines = create_english_translation(romanian_lines)
	asyncio.run(create_bilingual_audio(romanian_lines, english_lines))
	print(f"Traducere creată: {ENGLISH_FILE}")
	print(f"Audio creat: {AUDIO_FILE}")


if __name__ == "__main__":
	main()

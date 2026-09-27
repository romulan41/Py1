import os
from google import genai

# Folosim cheia ta API validă
client = genai.Client(api_key="AQ.dddd")

# Am actualizat modelul la gemini-3.8-flash conform cerințelor Google
chat = client.chats.create(model="gemini-3.8-flash")

print("--- Chatul Corectat Gemini 3.8 a pornit! Scrie 'iesire' pentru a opri. ---")

while True:
    intrebare = input("\nTu: ")
    
    if intrebare.lower() == 'iesire':
        print("La revedere!")
        break
        
    if not intrebare.strip():
        continue
        
    print("Gemini răspunde...")
    
    try:
        response = chat.send_message(intrebare)
        print(f"\nGemini: {response.text}")
    except Exception as e:
        print(f"\nA apărut o eroare la conexiune: {e}")

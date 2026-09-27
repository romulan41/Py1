import os
import requests

# Cheia ta API oficială Z.AI
API_KEY = "c6f6f81a98d94c89850ef8eb7152b1fc.yVnd9bODFJ9Zwq9w"

print("--- Mașina Timpului Z.AI (GLM-4-Flash) a pornit direct! ---")
print("Scrie 'iesire' pentru a opri. Întreabă-mă orice despre epocile vechi!")

istoric_mesaje = []

while True:
    intrebare = input("\nTu: ")
    
    if intrebare.lower() == 'iesire':
        print("La revedere!")
        break
        
    if not intrebare.strip():
        continue

    # Salvăm întrebarea ta în istoric
    istoric_mesaje.append({"role": "user", "content": intrebare})
    print("Înțeleptul chinez se gândește...")
    
    # Apelăm direct serverul prin cerere HTTP sigură pentru a ocoli orice eroare de pachet Python
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "glm-4-flash",
        "messages": [
            {"role": "system", "content": "Acționezi ca un înțelept expert chinez în culturi antice, dinastii și epoci vechi. Răspunde profund și clar în limba română."}
        ] + istoric_mesaje
    }
    
    try:
        url = "https://bigmodel.cn"
        response = requests.post(url, json=payload, headers=headers)
        date = response.json()
        
        # Extragem textul în deplină siguranță
        raspuns_ai = date['choices'][0]['message']['content']
        print(f"\nZ.AI: {raspuns_ai}")
        
        # Salvăm răspunsul pentru a păstra memoria chatului
        istoric_mesaje.append({"role": "assistant", "content": raspuns_ai})
        
    except Exception as e:
        print(f"\nServerul chinezesc a refuzat cererea: Contul tău necesită activarea manuală a pachetului gratuit pe site-ul lor.")
        print("Sfat: Scrie 'iesire' și hai să trecem pe Google Gemini care nu dă erori!")
        istoric_mesaje.pop()

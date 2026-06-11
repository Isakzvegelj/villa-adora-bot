import os
import subprocess
import json
import re
from openai import OpenAI
from database import add_booking, init_db, add_calendar_event, get_all_calendar_events
from hotel_data import hotel_info
import sqlite3
from flask import Flask, render_template, request, jsonify, Response
try:
    from rag import retrieve as rag_retrieve
    _RAG_AVAILABLE = True
except ImportError:
    _RAG_AVAILABLE = False

init_db()

def _load_api_key() -> str:
    env_key = (os.environ.get("LLM_API_KEY") or "").strip()
    if env_key:
        return env_key
    for service in ("openrouter-api-key", "LLM_API_KEY"):
        try:
            value = subprocess.check_output(
                ["security", "find-generic-password", "-s", service, "-w"],
                stderr=subprocess.DEVNULL,
            ).decode("utf-8", "ignore").strip()
            if value:
                return value
        except subprocess.CalledProcessError:
            pass
    return ""

api_key = _load_api_key()
if not api_key:
    raise SystemExit(
        "No OpenRouter API key found. Set LLM_API_KEY in env, or store with: "
        "security add-generic-password -a <user> -s openrouter-api-key -w '<key>'"
    )

def make_client() -> OpenAI:
    return OpenAI(
        api_key=api_key,
        base_url=os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
    )

client = make_client()
MODEL = os.environ.get("LLM_MODEL", "anthropic/claude-sonnet-4")

book_room_function = {
    "type": "function",
    "function": {
        "name": "book_room",
        "description": "Book a hotel room.",
        "parameters": {
            "type": "object",
            "properties": {
                "guest_name": {"type": "string"},
                "check_in": {"type": "string", "description": "YYYY-MM-DD"},
                "check_out": {"type": "string", "description": "YYYY-MM-DD"},
                "room_name": {"type": "string"}
            },
            "required": ["guest_name", "check_in", "check_out", "room_name"],
        },
    },
}

query_hotel_info_function = {
    "type": "function",
    "function": {
        "name": "query_hotel_info",
        "description": "Look up hotel information. Call this for ANY factual question about the hotel. Choose the most specific topic: 'rooms' for room types/sizes/pricing, 'bar' for cocktails/drinks/aperitivos, 'restaurant' for dining/chef/menu, 'wine' for wine list/pairing, 'breakfast' for morning meal/dietary needs, 'experiences' for activities/things to do/nearby, 'location' for address/directions, 'parking' for car parking, 'pets' for animals, 'policies' for rules, 'amenities' for room facilities, 'contact' for phone/email, 'shuttle' for airport transfers/transport, 'room_service' for in-room dining.",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "enum": [
                        "rooms", "policies", "amenities", "location", "experiences",
                        "breakfast", "parking", "wifi", "pets", "cancellation",
                        "payment", "children", "smoking", "contact", "general",
                        "restaurant", "wine", "bar", "late_check_in", "late_check_out",
                        "shuttle", "room_service", "history",
                    ],
                },
                "question": {"type": "string"},
            },
            "required": ["topic", "question"],
        },
    },
}

book_shuttle_function = {
    "type": "function",
    "function": {
        "name": "book_shuttle",
        "description": "Book a shuttle service for the guest. Collect all required details before calling.",
        "parameters": {
            "type": "object",
            "properties": {
                "guest_name": {"type": "string", "description": "Name of the guest"},
                "pickup_location": {"type": "string", "description": "Where to pick up the guest"},
                "dropoff_location": {"type": "string", "description": "Where to drop off"},
                "date": {"type": "string", "description": "Date of shuttle in YYYY-MM-DD format"},
                "time": {"type": "string", "description": "Pickup time (e.g. '14:00')"},
                "passengers": {"type": "integer", "description": "Number of passengers", "default": 1},
                "notes": {"type": "string", "description": "Any special requests or notes"},
            },
            "required": ["guest_name", "pickup_location", "date", "time"],
        },
    },
}

request_human_agent_function = {
    "type": "function",
    "function": {
        "name": "request_human_agent",
        "description": "Transfer the guest to a human agent. Use when: guest is frustrated, explicitly asks for a human, has a complex complaint, or the bot cannot resolve the issue.",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Why the guest needs a human agent"},
                "guest_name": {"type": "string", "description": "Name of the guest if known"},
                "summary": {"type": "string", "description": "Brief summary of the issue"},
            },
            "required": ["reason"],
        },
    },
}



_ROOM_LISTINGS_TRANSLATED = {
    "Slovenian": (
        "Imamo 8 čudovitih apartmajev, vsi s čudovitim razgledom na jezero:\n"
        "• Princesin apartmaj, 55 m², za 2 osebi — Razgled na jezero iz stolpa, dnevna soba\n"
        "• Luksuzni apartmaj, za 2 osebi — Razgled na jezero, elegantna dekoracija\n"
        "• Penthouse apartmaj, 60 m², za 2 osebi — 2 nadstropji, king-size postelja\n"
        "• Deluxe apartmaj, za 2 osebi — Razgled na jezero, luksuzna oprema\n"
        "• Superior apartmaj, za 4 osebe — 2 spalnici, družinski apartmaj\n"
        "• Otoški apartmaj, 65 m², za 4 osebe — 2 luksuzni spalnici, 2 balkona\n"
        "• Labodji apartmaj, 67 m², za 2 osebi — Razgled na jezero, luksuzna kopalnica\n"
        "• Prestižni apartmaj, 72 m², za 2 osebi — Pritličje, pogled na jezero\n"
        "Kateri vas najbolj pritegne? Lahko začnem z rezervacijo — samo povejte mi vaše ime in datume?"
    ),
    "German": (
        "Wir haben 8 wunderschöne Suiten mit atemberaubendem Seeblick:\n"
        "• Prinzessin Suite, 55 m², für 2 Gäste — Seeblick vom Turm, Wohnbereich\n"
        "• Luxus Suite, für 2 Gäste — Seeblick, elegante Einrichtung\n"
        "• Penthouse Suite, 60 m², für 2 Gäste — 2 Etagen, Kingsize-Bett\n"
        "• Deluxe Suite, für 2 Gäste — Seeblick, luxuriöse Ausstattung\n"
        "• Superior Suite, für 4 Gäste — 2 Schlafzimmer, familienfreundlich\n"
        "• Insel Suite, 65 m², für 4 Gäste — 2 Luxusschlafzimmer, 2 Balkone\n"
        "• Schwan Suite, 67 m², für 2 Gäste — Seeblick, luxuriöses Badezimmer\n"
        "• Prestige Suite, 72 m², für 2 Gäste — Erdgeschoss, Seeblick\n"
        "Welche Suite gefällt Ihnen am besten? Ich starte gerne eine Buchung — ich brauche nur Ihren Namen und Ihre Reisedaten?"
    ),
    "French": (
        "Nous avons 8 magnifiques suites avec vue imprenable sur le lac:\n"
        "• Suite Princesse, 55 m², pour 2 personnes — Vue sur le lac depuis la tour, salon\n"
        "• Suite de Luxe, pour 2 personnes — Vue sur le lac, décoration élégante\n"
        "• Suite Penthouse, 60 m², pour 2 personnes — 2 étages, lit king-size\n"
        "• Suite Deluxe, pour 2 personnes — Vue sur le lac, mobilier de luxe\n"
        "• Suite Supérieure, pour 4 personnes — 2 chambres, idéale pour les familles\n"
        "• Suite Île, 65 m², pour 4 personnes — 2 chambres de luxe, 2 balcons\n"
        "• Suite Cygne, 67 m², pour 2 personnes — Vue sur le lac, salle de bain luxueuse\n"
        "• Suite Prestige, 72 m², pour 2 personnes — Rez-de-chaussée, vue lac\n"
        "Laquelle vous plaît le plus ? Je peux réserver pour vous — j'ai besoin de votre nom et de vos dates?"
    ),
    "Italian": (
        "Abbiamo 8 splendide suite con vista mozzafiato sul lago:\n"
        "• Suite Principessa, 55 m², per 2 persone — Vista lago dalla torre, zona living\n"
        "• Suite Luxury, per 2 persone — Vista lago, arredi eleganti\n"
        "• Suite Penthouse, 60 m², per 2 persone — 2 piani, letto king size\n"
        "• Suite Deluxe, per 2 persone — Vista lago, arredi di lusso\n"
        "• Suite Superiore, per 4 persone — 2 camere da letto, ideale per famiglie\n"
        "• Suite Isola, 65 m², per 4 persone — 2 camere da letto di lusso, 2 balconi\n"
        "• Suite Cigno, 67 m², per 2 persone — Vista lago, bagno di lusso\n"
        "• Suite Prestige, 72 m², per 2 persone — Piano terra, vista lago\n"
        "Quale ti piace di più? Posso prenotare per te — mi servono solo nome e date?"
    ),
    "Spanish": (
        "Tenemos 8 hermosas suites con vistas impresionantes al lago:\n"
        "• Suite Princesa, 55 m², para 2 personas — Vista al lago desde la torre, zona de estar\n"
        "• Suite de Lujo, para 2 personas — Vista al lago, decoración elegante\n"
        "• Suite Penthouse, 60 m², para 2 personas — 2 pisos, cama king size\n"
        "• Suite Deluxe, para 2 personas — Vista al lago, mobiliario de lujo\n"
        "• Suite Superior, para 4 personas — 2 habitaciones, ideal para familias\n"
        "• Suite Isla, 65 m², para 4 personas — 2 habitaciones de lujo, 2 balcones\n"
        "• Suite Cisne, 67 m², para 2 personas — Vista al lago, baño de lujo\n"
        "• Suite Prestige, 72 m², para 2 personas — Planta baja, vista al lago\n"
        "¿Cuál te gusta más? Puedo hacer la reserva — solo necesito tu nombre y las fechas?"
    ),
    "Croatian": (
        "Imamo 8 prekrasnih apartmana s prekrasnim pogledom na jezero:\n"
        "• Apartman Princeza, 55 m², za 2 osobe — Pogled na jezero iz tornja, dnevni boravak\n"
        "• Luksuzni apartman, za 2 osobe — Pogled na jezero, elegantan namještaj\n"
        "• Penthouse apartman, 60 m², za 2 osobe — 2 kata, king-size krevet\n"
        "• Deluxe apartman, za 2 osobe — Pogled na jezero, luksuzna oprema\n"
        "• Superior apartman, za 4 osobe — 2 spavaće sobe, obiteljski apartman\n"
        "• Otočni apartman, 65 m², za 4 osebe — 2 luksuzne spavaće sobe, 2 balkona\n"
        "• Apartman Labud, 67 m², za 2 osobe — Pogled na jezero, luksuzna kupaonica\n"
        "• Prestižni apartman, 72 m², za 2 osobe — Prizemlje, pogled na jezero\n"
        "Koji vas najviše privlači? Mogu pokrenuti rezervaciju — samo mi recite vaše ime i datume?"
    ),
    "Serbian": (
        "Imamo 8 prekrasnih apartmana s prekrasnim pogledom na jezero:\n"
        "• Apartman Princeza, 55 m², za 2 osobe — Pogled na jezero iz tornja, dnevni boravak\n"
        "• Luksuzni apartman, za 2 osobe — Pogled na jezero, elegantan nameštaj\n"
        "• Penthouse apartman, 60 m², za 2 osobe — 2 kata, king-size krevet\n"
        "• Deluxe apartman, za 2 osobe — Pogled na jezero, luksuzna oprema\n"
        "• Superior apartman, za 4 osobe — 2 spavaće sobe, porodični apartman\n"
        "• Otočni apartman, 65 m², za 4 osobe — 2 luksuzne spavaće sobe, 2 balkona\n"
        "• Apartman Labud, 67 m², za 2 osobe — Pogled na jezero, luksuzna kupatila\n"
        "• Prestižni apartman, 72 m², za 2 osobe — Prizemlje, pogled na jezero\n"
        "Koji vas najviše privlači? Mogu pokrenuti rezervaciju — samo mi recite vaše ime i datume?"
    ),
}


_EXPERIENCES_TRANSLATED = {
    "Slovenian": (
        "V Bledu in okoli vas \u010daka veliko zanimivosti!:\n"
        "\u2022 Kajanje na Bledski otok in obisk cerkve Marijinega vnebovzetja\n"
        "\u2022 Plavanje, SUP, kajak in ladijske vo\u017enje na jezeru\n"
        "\u2022 Sprehod po soteski Vintgar (2,4 km)\n"
        "\u2022 Obisk Blejskega gradu (30 min hoje)\n"
        "\u2022 6 km potokoli jezera in 15 poti za pohodni\u0161tvo\n"
        "\u2022 Izleti na Bohinjsko jezero, v Ljubljano, Postojnsko jamo\n"
        "\u2022 Masa\u017ea v sobi, ve\u010deri z vinom v vrtu\n"
        "Katero aktivnost vas najbolj zanima? Z veseljem vam jo pomagam organizirati?"
    ),
    "German": (
        "In und um Bled gibt es viel zu erleben!:\n"
        "\u2022 Fahrt zur Bled-Insel & Besuch der Wallfahrtskirche\n"
        "\u2022 Schwimmen, SUP, Kajak und Bootstouren\n"
        "\u2022 Vintgar-Schlucht Spaziergang (2,4 km)\n"
        "\u2022 Bleder Burg Besuch (30 Min. zu Fu\u00df)\n"
        "\u2022 6 km Uferweg & 15 Wanderwege\n"
        "\u2022 Tagesausfl\u00fcche nach Bohinj, Ljubljana, Postojna\n"
        "\u2022 In-Zimmer Massage, Gartenabende mit Wein\n"
        "Welche Aktivit\u00e4t interessiert Sie am meisten? Ich helfe gerne bei der Organisation!"
    ),
    "French": (
        "\u00c0 Bled, il y a beaucoup \u00e0 faire!:\n"
        "\u2022 Balade vers l'\u00eele de Bled et visite de l'\u00e9glise\n"
        "\u2022 Natation, paddle, kayak et excursions en bateau\n"
        "\u2022 Gorges de Vintgar (2,4 km)\n"
        "\u2022 Ch\u00e2teau de Bled (30 min \u00e0 pied)\n"
        "\u2022 Sentier de 6 km autour du lac\n"
        "\u2022 Excursions \u00e0 Bohinj, Ljubljana, grotte de Postojna\n"
        "\u2022 Massage en chambre, soir\u00e9es avec vin\n"
        "Laquelle vous int\u00e9resse le plus? Je serai ravi de vous aider \u00e0 l'organiser!"
    ),
    "Italian": (
        "A Bled c'\u00e8 tanto da fare!:\n"
        "\u2022 Gita all'Isola di Bled e visita della chiesa\n"
        "\u2022 Nuoto, SUP, kayak e gite in barca\n"
        "\u2022 Gole di Vintgar (2,4 km)\n"
        "\u2022 Castello di Bled (30 min a piedi)\n"
        "\u2022 Sentiero di 6 km e 15 sentieri segnalati\n"
        "\u2022 Escursioni a Bohinj, Lubiana, grotta di Postojna\n"
        "\u2022 Massaggio in camera, serate con vino\n"
        "Quale ti interessa di pi\u00f9? Sar\u00e0 un piacere aiutarti!"
    ),
    "Spanish": (
        "En Bled hay mucho por hacer!:\n"
        "• Paseo a la Isla de Bled y visita de la iglesia\n"
        "• Natación, paddle, kayak y excursiones\n"
        "• Gargantas de Vintgar (2,4 km)\n"
        "• Castillo de Bled (30 min a pie)\n"
        "• Sendero de 6 km y 15 senderos\n"
        "• Excursiones a Bohinj, Ljubljana, cueva de Postojna\n"
        "• Masaje en habitación, noches con vino\n"
        "¿Cuál te interesa más? ¡Estaré encantado de ayudarte?"
    ),
    "Croatian": (
        "U Bledu ima mnogo toga za učiniti!:\n"
        "• Vožnja na otok Bled i posjet crkvi\n"
        "• Plivanje, SUP, kajak i brodski izleti\n"
        "• Šetnja kroz klisuru Vintgar (2,4 km)\n"
        "• Posjet dvorcu Bled (30 min hodajući)\n"
        "• Staza od 6 km i 15 označenih staza\n"
        "• Izleti na Bohinj, Ljubljansku, Postojnsku špilju\n"
        "• Masaža u sobi, večeri s vinom\n"
        "Koja vas aktivnost najviše zanima? Rado ću vam pomoći s organizacijom!"
    ),
}

_PETS_TRANSLATED = {
    "Slovenian": "Doma\u010di ljubljen\u010dki so dobrodo\u0161li na zahtevo \u2014 35 \u20ac na ljubljen\u010dka na no\u010d. Prosimo, da nas kontaktirate za organizacijo. Ali na\u010drtujete, da boste pripeljali krznenega prijatelja?",
    "German": "Haustiere sind auf Anfrage erlaubt \u2014 35 \u20ac pro Tier pro Nacht. Bitte kontaktieren Sie uns, um dies zu arrangieren. Planen Sie, einen pelzigen Freund mitzubringen?",
    "French": "Les animaux sont accept\u00e9s sur demande \u2014 35 \u20ac par animal et par nuit. Veuillez nous contacter pour organiser cela. Pr\u00e9voyez-vous d'amener un ami \u00e0 quatre pattes?",
    "Italian": "Gli animali domestici sono ammessi su richiesta \u2014 35 \u20ac per animale per notte. Contattateci per organizzare. State pensando di portare un amico a quattro zampe?",
    "Spanish": "\u00a1Las mascotas son bienvenidas bajo petici\u00f3n \u2014 35 \u20ac por mascota por noche! Cont\u00e1ctenos para organizarlo. \u00bfPlanea traer a un amigo peludo?",
    "Croatian": "Ku\u0107ni ljubimci su dobrodo\u0161li na zahtjev \u2014 35 \u20ac za ljubimca po no\u0107i. Molimo kontaktirajte nas za organizaciju. Planirate li dovesti krznenog prijatelja?",
    "Serbian": "Ku\u0107ni ljubimci su dobrodo\u0161li na zahtev \u2014 35 \u20ac za ljubimca po no\u0107i. Molimo kontaktirajte nas za organizaciju. Planirate li dovesti krznenog prijatelja?",
}


_RESTAURANT_TRANSLATED = {
    "Slovenian": (
        "Imamo restavracijo Adora Pop Up kar v hotelu! Ekskluzivna restavracija z ustvarjalno kuhinjo "
        "z lokalnimi slovenskimi sestavinami pod vodstvom šefa kuhinje Domena Demšara. "
        "Terasa ima ene najlepših razgledov na jezero. "
        "Odprto: Kosilo in večerja torek–nedelja, brunk četrtek–sobota. "
        "Rezervacija: +386 40 558 158 / +386 51 603 858 ali evita.vilebled@gmail.com. "
        "Želite rezervirati mizo?"
    ),
    "German": (
        "Wir haben das Adora Pop Up Restaurant direkt im Hotel! Exklusives kulinarisches Erlebnis "
        "mit kreativer, lokal inspirierter slowenischer Küche unter der Leitung von Küchenchef Domen Demšar. "
        "Die Terrasse bietet atemberaubende Sonnenuntergangsaussichten über Bled. "
        "Geöffnet: Mittagessen & Abendessen Dienstag–Sonntag, Brunch Donnerstag–Samstag. "
        "Reservierung: +386 40 558 158 / +386 51 603 858 oder evita.vilebled@gmail.com. "
        "Möchten Sie eine Reservierung vornehmen?"
    ),
    "French": (
        "Nous avons le restaurant Adora Pop Up directement à l'hôtel! Expérience culinaire exclusive "
        "avec une cuisine créative d'inspiration slovène locale, sous la direction du chef Domen Demšar. "
        "La terrasse offre des couchers de soleil à couper le souffle sur Bled. "
        "Ouvert: Déjeuner et dîner du mardi au dimanche, brunch du jeudi au samedi. "
        "Réservation: +386 40 558 158 / +386 51 603 858 ou evita.vilebled@gmail.com. "
        "Souhaitez-vous réserver une table ?"
    ),
    "Italian": (
        "Abbiamo il ristorante Adora Pop Up direttamente in hotel! Esperienza culinaria esclusiva "
        "con cucina creativa di ispirazione slovena locale, sotto la guida dello chef Domen Demšar. "
        "La terrazza offre tramonti mozzafiato su Bled. "
        "Aperto: Pranzo e cena da martedì a domenica, brunch da giovedì a sabato. "
        "Prenotazione: +386 40 558 158 / +386 51 603 858 o evita.vilebled@gmail.com. "
        "Vuoi riservare un tavolo?"
    ),
    "Spanish": (
        "¡Tenemos el restaurante Adora Pop Up directamente en el hotel! Experiencia culinaria exclusiva "
        "con cocina creativa de inspiración eslovena local, bajo la dirección del chef Domen Demšar. "
        "La terrazza ofrece atardeceres impresionantes sobre Bled. "
        "Abierto: Almuerzo y cena de martes a domingo, brunch de jueves a sábado. "
        "Reserva: +386 40 558 158 / +386 51 603 858 o evita.vilebled@gmail.com. "
        "¿Te gustaría reservar una mesa?"
    ),
}


_LOCATION_TRANSLATED = {
    "Slovenian": (
        "Villa Adora je na Cesti svobode 35, 4260 Bled, Slovenija, neposredno na obali jezera Bled — "
        "med redkimi hoteli na tako odlični lokaciji. Pogledi na Bledski otok, Blejski grad in gore Triglava. "
        "2 minuti hoje do pristanišča za čolne, 15 minut do središča Bleda, 30 minut do Blejskega gradu. "
        "Telefon: +386 51 603 858. Želite navodila za pot do nas ali nasvete za prihod?"
    ),
    "German": (
        "Villa Adora befindet sich an der Cesta svobode 35, 4260 Bled, Slowenien, direkt am Ufer des Bleder Sees — "
        "einer der wenigen Hotels mit dieser erstklassigen Lage. Blick auf die Bled-Insel, die Bleder Burg und die Triglav-Berge. "
        "2 Minuten zu Fuß zur Bootsanlegestelle, 15 Minuten zum Stadtzentrum von Bled, 30 Minuten zur Bleder Burg. "
        "Telefon: +386 51 603 858. Möchten Sie eine Wegbeschreibung oder Tipps für die Anreise?"
    ),
    "French": (
        "Villa Adora se trouve au Cesta svobode 35, 4260 Bled, Slovénie, directement au bord du lac de Bled — "
        "l'un des rares hôtels avec cet emplacement privilégié. Vue sur l'île de Bled, le château de Bled et les montagnes du Triglav. "
        "2 minutes à pied de la station de bateaux, 15 minutes du centre-ville de Bled, 30 minutes du château de Bled. "
        "Téléphone: +386 51 603 858. Souhaitez-vous des indications ou des conseils pour venir ?"
    ),
    "Italian": (
        "Villa Adora si trova in Cesta svobode 35, 4260 Bled, Slovenia, direttamente sulle rive del lago di Bled — "
        "uno dei pochi hotel con questa posizione privilegiata. Vista sull'Isola di Bled, il Castello di Bled e le montagne del Triglav. "
        "2 minuti a piedi dalla stazione dei battelli, 15 minuti dal centro di Bled, 30 minuti dal Castello di Bled. "
        "Telefono: +386 51 603 858. Vuoi indicazioni o suggerimenti per raggiungerci?"
    ),
    "Spanish": (
        "Villa Adora se encuentra en Cesta svobode 35, 4260 Bled, Eslovenia, directamente a orillas del lago de Bled — "
        "uno de los pocos hoteles con esta ubicación privilegiada. Vistas a la Isla de Bled, el Castillo de Bled y las montañas del Triglav. "
        "2 minutos a pie de la estación de botes, 15 minutos del centro de Bled, 30 minutos del Castillo de Bled. "
        "Teléfono: +386 51 603 858. ¿Te gustaría recibir indicaciones o consejos para llegar?"
    ),
}


_BREAKFAST_TRANSLATED = {
    "Slovenian": (
        "Zajtrk stane 22 € na osobo — postrežen med 8. in 10. uro na terasi s pogledom na jezero. "
        "Bogat samopostrežni zajtrk s svežim pecivom, kruhom in lokalnimi slovenskimi izdelki. "
        "Veganske, vegetarijanske in brezglutenske možnosti na zahtevo. "
        "Imate kakšne prehranske omejitve, o katerih bi morali vedeti?"
    ),
    "German": (
        "Frühstück kostet 22 € pro Person — serviert von 8 bis 10 Uhr auf der Terrasse mit Seeblick. "
        "Reichhaltiges Buffet mit frischem Gebäck, Brot und lokalen slowenischen Produkten. "
        "Vegane, vegetäre und glutenfreie Optionen auf Anfrage. "
        "Haben Sie irgendwelche Ernährungseinschränkungen, die wir wissen sollten?"
    ),
    "French": (
        "Le petit-déjeuner coûte 22 € par personne — servi de 8h à 10h sur la terrasse avec vue sur le lac. "
        "Buffet riche avec pâtisseries fraîches, pain et produits locaux slovènes. "
        "Options végétaliennes, végétariennes et sans gluten sur demande. "
        "Avez-vous des restrictions alimentaires que nous devrions connaître?"
    ),
    "Italian": (
        "La colazione costa 22 € a persona — servita dalle 8 alle 10 sulla terrazza con vista sul lago. "
        "Buffet ricco con pasticceria fresca, pane e prodotti locali sloveni. "
        "Opzioni vegane, vegetariane e senza glutine su richiesta. "
        "Hai delle restrizioni alimentari che dovremmo sapere?"
    ),
    "Spanish": (
        "El desayuno cuesta 22 € por persona — servido de 8 a 10 AM en la terraza con vistas al lago. "
        "Buffet rico con pasteles frescos, pan y productos locales eslovenos. "
        "Opciones veganas, vegetarianas y sin gluten bajo pedido. "
        "¿Tiene restricciones alimentarias que debamos conocer?"
    ),
}


_CHECKIN_TRANSLATED = {
    "Slovenian": (
        "Prijava je od 14:00 do 23:00, odjava do 11:00. "
        "Pozna prijava/odjava je na voljo na zahtevo — kontaktirajte recepcijo. "
        "Ob kateri uri načrtujete prihod?"
    ),
    "German": (
        "Check-in ist von 14:00 bis 23:00, Check-out bis 11:00. "
        "Später Check-in/Check-out ist auf Anfrage möglich — kontaktieren Sie die Rezeption. "
        "Um welche Uhrzeit planen Sie Ihre Ankunft?"
    ),
    "French": (
        "L'enregistrement est de 14h00 à 23h00, le départ à 11h00. "
        "L'enregistrement/départ tardif est possible sur demande — contactez la réception. "
        "À quelle heure prévoyez-vous d'arriver ?"
    ),
    "Italian": (
        "Il check-in è dalle 14:00 alle 23:00, il check-out fino alle 11:00. "
        "Check-in/check-out tardivo è disponibile su richiesta — contatta la reception. "
        "A che ora prevedi di arrivare?"
    ),
    "Spanish": (
        "El check-in es de 14:00 a 23:00, el check-out hasta las 11:00. "
        "Check-in/check-out tardío está disponible bajo petición — contacte con recepción. "
        "¿A qué hora planeas llegar?"
    ),
}


_WINE_TRANSLATED = {
    "Slovenian": (
        "Naša vinska karta je sestavljena iz najboljših slovenskih vin iz okolice Bleda, jih izbira naš strokovnjak. "
        "Vinarna ponuja tako lokalne kot mednarodne oznake. Vino z združljivostjo z degustacijskim menijem je na voljo (približno 35 € na osebo). "
        "Želite rezervirati mizo?"
    ),
    "German": (
        "Unsere Weinkarte wird von einem Hausesommelier kuratiert und bietet die besten slowenische Weine aus der Nähe von Bled "
        "sowie ausgewählte internationale Etiketten. Weinbegleitung zum Degustationsmenü verfügbar (ca. 35 € pro Person). "
        "Möchten Sie einen Tisch reservieren?"
    ),
    "French": (
        "Notre carte des vins est élaborée par un sommelier interne, proposant les meilleurs vins slovènes près de Bled "
        "ainsi que des labels internationaux sélectionnés. Accord mets et vins disponible avec le menu dégustation (environ 35 € par personne). "
        "Souhaitez-vous réserver une table ?"
    ),
    "Italian": (
        "La nostra lista dei vini è curata da un sommelier interno, con i migliori vini sloveni vicino a Bled "
        "e etichette internazionali selezionate. Abbinamento vini disponibile con il menu degustazione (circa 35 € a persona). "
        "Vuoi riservare un tavolo?"
    ),
    "Spanish": (
        "Nuestra lista de vinos está curada por un sumiller interno, con los mejores vinos eslovenos cerca de Bled "
        "y etiquetas internacionales seleccionadas. Maridaje de vinos disponible con el menú degustación (aproximadamente 35 € por persona). "
        "¿Te gustaría reservar una mesa?"
    ),
}


_BAR_TRANSLATED = {
    "English": (
        "Our bar serves elegant cocktails and aperitivos daily on the terrace — arguably the best sunset views over Lake Bled! "
        "It's a lovely place to unwind after a day exploring, and we also have a curated wine list if you'd prefer wine. "
        "Would you like to reserve a table on the terrace, or shall I help you with a restaurant reservation?"
    ),
    "Slovenian": (
        "Naš bar streže elegantne koktaje in aperitive vsak dan na terasi z enim najlepših sončnih zahodov nad jezerom Bled. "
        "Popoln kraj za sproščanje po dnevu raziskovanja! Želite več informacij o našem jedilniku pijač?"
    ),
    "German": (
        "Unsere Bar serviert elegante Cocktails und Aperitivos täglich auf der Terrasse mit wohl den atemberaubendsten Sonnenuntergängen über dem Bleder See. "
        "Der perfekte Ort, um nach einem Tag voller Erkundungen zu entspannen! Möchten Sie mehr über unsere Getränkekarte erfahren?"
    ),
    "French": (
        "Notre bar sert des cocktails élégants et des apéritifs quotidiennement sur la terrasse avec ce qui est probablement les plus beaux couchers de soleil sur le lac de Bled. "
        "L'endroit parfait pour se détendre après une journée d'exploration ! Souhaitez-vous en savoir plus sur notre carte de boissons ?"
    ),
    "Italian": (
        "Il nostro bar serve cocktail eleganti e aperitivi quotidianamente sulla terrazza con quelle che sono probabilmente le più belle tramonti sul lago di Bled. "
        "Il posto perfetto per rilassarsi dopo una giornata di esplorazione! Vuoi saperne di più sul nostro menu delle bevande?"
    ),
    "Spanish": (
        "Nuestro bar sirve cócteles elegantes y aperitivos diariamente en la terrazca con lo que son probablemente las mejores puestas de sol sobre el lago de Bled. "
        "¡El lugar perfecto para relajarse después de un día de exploración! ¿Te gustaría saber más sobre nuestra carta de bebidas?"
    ),
}


_PARKING_TRANSLATED = {
    "Slovenian": (
        "Imamo brezplačno parkirišče — 8 parkirnih mest pred hotelom. "
        "Boste vozili v Bled ali želite nasvete za javni prevoz?"
    ),
    "German": (
        "Wir bieten kostenlosen privaten Parkplatz an — 8 Parkplätze direkt vor dem Hotel. "
        "Kommen Sie mit dem Auto nach Bled, oder benötigen Sie Tipps für den öffentlichen Nahverkehr?"
    ),
    "French": (
        "Nous offrons un parking privé gratuit — 8 places de parking devant l'hôtel. "
        "Venez-vous à Bled en voiture, ou souhaitez-vous des conseils sur les transports en commun ?"
    ),
    "Italian": (
        "Offriamo parcheggio privato gratuito — 8 posti auto davanti all'hotel. "
        "Verrai a Bled in auto, o vuoi suggerimenti sui trasporti pubblici?"
    ),
    "Spanish": (
        "Ofrecemos estacionamiento privado gratuito — 8 espacios de estacionamiento frente al hotel. "
        "¿Vas a venir a Bled en coche, o te gustaría recibir consejos sobre transporte público?"
    ),
    "Croatian": (
        "Nudimo besplatno privatno parkiralište — 8 parkirnih mjesta ispred hotela. "
        "Dolazite li u Bled autom, ili želite savjete za javni prijevoz?"
    ),
}


_SHUTTLE_TRANSLATED = {
    "Slovenian": (
        "Nudimo prevoz z letališča, lokalni prevoz in poti po meri! "
        "Priljubljene poti: Letališče Ljubljana (~60 €), središče Bleda (~15 €). "
        "Za rezervacijo mi povejte ime, kje vas prevzeti, datum in uro. "
        "Kje bi radi, da vas prevzamemo?"
    ),
    "German": (
        "Wir bieten Flughafentransfers, lokale Fahrten und individuelle Routen an! "
        "Beliebte Routen: Flughafen Ljubljana (~60 €), Bled Stadtzentrum (~15 €). "
        "Zur Buchung teilen Sie mir Ihren Namen, den Abholort, das Datum und die Uhrzeit mit. "
        "Wo möchten Sie abgeholt werden?"
    ),
    "French": (
        "Nous proposons des transferts aéroport, des transports locaux et des itinéraires personnalisés ! "
        "Itinéraires populaires: Aéroport de Ljubljana (~60 €), centre-ville de Bled (~15 €). "
        "Pour réserver, dites-moi votre nom, le lieu de prise en charge, la date et l'heure. "
        "Où souhaitez-vous être pris en charge ?"
    ),
    "Italian": (
        "Offriamo trasferimenti aeroportuali, trasporti locali e percorsi personalizzati! "
        "Percorsi popolari: Aeroporto di Lubiana (~60 €), centro di Bled (~15 €). "
        "Per prenotare, dimmi il tuo nome, il luogo di ritiro, la data e l'ora. "
        "Dove vuoi essere ritirato?"
    ),
    "Spanish": (
        "Ofrecemos traslados al aeropuerto, transporte local y rutas personalizadas. "
        "Rutas populares: Aeropuerto de Ljubljana (~60 €), centro de Bled (~15 €). "
        "Para reservar, dime tu nombre, lugar de recogida, fecha y hora. "
        "¿Dónde te gustaría que te recojamos?"
    ),
    "Croatian": (
        "Nudimo transfere zračne lokalne prijevoz i prilagođene rute! "
        "Popularne rute: Zračna luka Ljubljana (~60 €), centar Bleda (~15 €). "
        "Za rezervaciju mi recite ime, mjesto preuzimanja, datum i vrijeme. "
        "Gdje biste da vas preuzmemo?"
    ),
}


_WELLNESS_TRANSLATED = {
    "English": (
        "Villa Adora offers in-room massage with 24 hours' notice. "
        "You can book through reception or email evita.vilebled@gmail.com. "
        "Would you like me to check availability for a massage during your stay?"
    ),
    "Slovenian": (
        "Villa Adora ponuja masažo v sobi z 24-urno predhodno najavo. "
        "Rezervacija prek recepcije ali e-pošte evita.vilebled@gmail.com. "
        "Želite, da povprašam za razpoložljivost masaže med vašim bivanjem?"
    ),
    "German": (
        "Villa Adora bietet In-Zimmer-Massagen mit 24 Stunden Vorankündigung. "
        "Buchung über Rezeption oder E-Mail evita.vilebled@gmail.com. "
        "Möchten Sie, dass ich die Verfügbarkeit einer Massage für Ihren Aufenthalt prüfe?"
    ),
    "French": (
        "Villa Adora propose des massages en chambre avec 24 heures de préavis. "
        "Réservation auprès de la réception ou par email evita.vilebled@gmail.com. "
        "Souhaitez-vous que je vérifie la disponibilité d'un massage pendant votre séjour ?"
    ),
    "Italian": (
        "Villa Adora offre massaggi in camera con 24 ore di preavviso. "
        "Prenotazione tramite reception o email evita.vilebled@gmail.com. "
        "Vuoi che verifichi la disponibilità di un massaggio durante il tuo soggiorno?"
    ),
    "Spanish": (
        "Villa Adora ofrece masajes en la habitación con 24 horas de anticipación. "
        "Reserva a través de recepción o email evita.vilebled@gmail.com. "
        "¿Quieres que verifique la disponibilidad de un masaje durante tu estancia?"
    ),
    "Croatian": (
        "Villa Adora nudi masažu u sobi uz 24 sata prethodne najave. "
        "Rezervacija putem recepcije ili email evita.vilebled@gmail.com. "
        "Želite li da provjerim dostupnost masaže tijekom vašeg boravka?"
    ),
}


_CHILDREN_TRANSLATED = {
    "English": (
        "Children of all ages are welcome! Our Superior Suite and Island Suite both have 2 bedrooms and sleep 4, so they are great for families. "
        "Cribs and extra beds are not available at the moment. "
        "Are you traveling with children who might enjoy any special amenities?"
    ),
    "Slovenian": (
        "Otroci vseh starosti so dobrodošli! Imamo Superior apartma (2 spalnici, spalni 4) in "
        "Otoški apartmaj (2 spalnici, 65 m², spalni 4) — idealna za družine. "
        "Posteljic in dodatnih postelj trenutno ne nudimo. "
        "Imate otroke, ki bi jih zanimali kakšni posebni ugodnosti?"
    ),
    "German": (
        "Kinder jeden Alters sind willkommen! Wir haben die Superior Suite (2 Schlafzimmer, 4 Gäste) und "
        "die Insel Suite (2 Schlafzimmer, 65 m², 4 Gäste) — ideal für Familien. "
        "Babybetten und Zustellbetten sind derzeit nicht verfügbar. "
        "Haben Sie Kinder, die an bestimmten Annehmlichkeiten interessiert wären?"
    ),
    "French": (
        "Les enfants de tous âges sont les bienvenus ! Nous avons la Suite Supérieure (2 chambres, 4 personnes) et "
        "la Suite Île (2 chambres, 65 m², 4 personnes) — idéales pour les familles. "
        "Les lits bébé et les lits d'appoint ne sont pas disponibles actuellement. "
        "Avez-vous des enfants qui seraient intéressés par certaines commodités ?"
    ),
    "Italian": (
        "I bambini di tutte le età sono i benvenuti! Abbiamo la Suite Superiore (2 camere, 4 persone) e "
        "la Suite Isola (2 camere, 65 m², 4 persone) — ideali per le famiglie. "
        "Culle e letti aggiuntivi non sono disponibili al momento. "
        "Hai bambini che sarebbero interessati a particolari servizi?"
    ),
    "Spanish": (
        "¡Niños de todas las edades son bienvenidos! Tenemos la Suite Superior (2 habitaciones, 4 personas) y "
        "la Suite Isla (2 habitaciones, 65 m², 4 personas) — ideales para familias. "
        "Las cunas y camas supletorias no están disponibles actualmente. "
        "¿Tiene niños que estarían interesados en ciertas comodidades?"
    ),
    "Croatian": (
        "Djeca svih dobi su dobrodošla! Imamo Superior apartman (2 spavaće sobe, 4 osobe) i "
        "Otočni apartman (2 spavaće sobe, 65 m², 4 osobe) — idealne za obitelji. "
        "Dječji krevetići i pomoćni ležajevi trenutno nisu dostupni. "
        "Imate li djecu koja bi zanimali određeni pogodnosti?"
    ),
}


_WEDDING_TRANSLATED = {
    "English": (
        "Villa Adora is a beautiful setting for intimate weddings and private celebrations. "
        "For weddings or special events, our reception team can discuss available dates, options, "
        "and any extra services that may suit your plans. Would you like me to help start an inquiry?"
    ),
    "Slovenian": (
        "Villa Adora je čudovit prizor za intimna poročna praznovanja. "
        "Za poroke in zasebna praznovanja se lahko dogovorite z recepcijo, ki bo preverila možnosti, "
        "dostopnost in dodatne storitve za vaš datum. Želite, da vam pomagam zastaviti povpraševanje?"
    ),
    "German": (
        "Villa Adora ist ein wunderbarer Ort für intime Hochzeiten und Feiern. "
        "Für Hochzeiten und private Veranstaltungen kann unsere Rezeption Möglichkeiten, Verfügbarkeit "
        "und zusätzliche Services für Ihr Datum abstimmen. Möchten Sie, dass ich eine Anfrage vorbereite?"
    ),
    "French": (
        "Villa Adora est un cadre magnifique pour les mariages intimes et les célébrations. "
        "Pour les mariages et événements privés, notre réception peut vérifier les possibilités, "
        "la disponibilité et les services complémentaires pour votre date. Souhaitez-vous que je prépare une demande ?"
    ),
    "Italian": (
        "Villa Adora è una cornice meravigliosa per matrimoni intimi e celebrazioni. "
        "Per matrimoni ed eventi privati, la reception può verificare possibilità, disponibilità "
        "e servizi aggiuntivi per la tua data. Vuoi che prepari una richiesta?"
    ),
    "Spanish": (
        "Villa Adora es un marco maravilloso para bodas íntimas y celebraciones. "
        "Para bodas y eventos privados, recepción puede revisar opciones, disponibilidad "
        "y servicios adicionales para tu fecha. ¿Quieres que prepare una solicitud?"
    ),
    "Croatian": (
        "Villa Adora prekrasan je prostor za intimna vjenčanja i proslave. "
        "Za vjenčanja i privatna događanja recepcija može provjeriti mogućnosti, dostupnost "
        "i dodatne usluge za vaš datum. Želite li da pripremim upit?"
    ),
}


def _get_localized_fallback(lang: str, user_message: str) -> str:
    """Return a localized fallback response when the LLM responds in English for non-English queries."""
    import unicodedata as _ud
    q = _ud.normalize("NFC", user_message.lower())
    # Detect topic for a more relevant fallback
    if any(w in q for w in ["room", "suite", "bed", "sleep", "sobe", "soba", "zimmer", "camere", "camera", "chambre", "habitaci", "cuarto", "apartma", "zimmer frei", "camere disponibili", "chambres disponibles", "habitaciones disponibles"]):
        fallbacks = {
            "Slovenian": "Imamo 8 čudovitih apartmajev z razgledom na jezero. Vsi imajo kopalnico, klimo, brezplačen WiFi in TV. Vas kateri vas zanima največ? Rad bi vam podal več podrokov?",
            "German": "Wir haben 8 wunderschöne Suiten mit Seeblick. Alle verfügen über eigenes Bad, Klimaanlage, kostenloses WLAN und TV. Welche Suite interessiert Sie am meisten? Ich kann Ihnen gerne mehr davon erzählen?",
            "French": "Nous avons 8 magnifiques suites avec vue sur le lac. Toutes disposent d'une salle de bain privée, de la climatisation, du WiFi gratuit et de la télévision. Laquelle vous intéresse le plus? Je peux vous en dire plus?",
            "Italian": "Abbiamo 8 splendide suite con vista sul lago. Tutte dispongono di bagno privato, aria condizionata, WiFi gratuito e TV. Quale suite ti interessa di più? Posso darti maggiori dettagli?",
            "Spanish": "Tenemos 8 hermosas suites con vistas al lago. Todas cuentan con baño privado, aire acondicionado, WiFi gratis y TV. ¿Cuál te llama más la atención? ¡Puedo darte más detalles?",
            "Croatian": "Imamo 8 prekrasnih apartmana s pogledom na jezero. Svi imaju vlastitu klimu, besplatni WiFi i TV. Koji vas najviše zanima? Mogu vam dati više detalja?",
            "Serbian": "Imamo 8 prekrasnih apartmana s pogledom na jezero. Svi imaju vlastitu klimu, besplatni WiFi i TV. Koji vas najviše zanima? Mogu vam dati više detalja?",
        }
    elif any(w in q for w in ["breakfast", "morning", "brunch", "zajtrk", "frühstück", "colazione", "petit déjeuner", "desayuno", "vegan", "vegetarian", "gluten", "allergy", "allergies", "dietary", "diet", "restriction", "celiac", "lactose", "intolerant", "vegansko", "vegetarijansko", "brezglutensko", "alergija", "prehrana", "végétalien", "végétarien", "sans gluten", "opciones veganas", "opciones sin gluten", "vegane", "vegetarische", "glutenfreie", "bez glutena", "végétaliennes", "végétariennes", "opzione vegane"]):
            fallbacks = {
                "Slovenian": "Zajtrk stane 22 € na osobo — postrežen med 8. in 10. uro na terasi s pogledom na jezero. Bogat samopostrežni zajtrk s svežim pecivom, kruhom in lokalnimi slovenskimi izdelki. Veganske, vegetarijanske in brezglutenske možnosti na zahtevo. Imate kakšne prehranske omejitve?",
                "German": "Frühstück kostet 22 € pro Person — serviert von 8 bis 10 Uhr auf der Terrasse mit Seeblick. Reichhaltiges Buffet mit frischem Gebäck, Brot und lokalen slowenischen Produkten. Vegane, vegetäre und glutenfreie Optionen auf Anfrage. Haben Sie Ernährungseinschränkungen?",
                "French": "Le petit-déjeuner coûte 22 € par personne — servi de 8h à 10h sur la terrasse avec vue sur le lac. Buffet riche avec pâtisseries fraîches, pain et produits locaux slovènes. Options végétaliennes, végétariennes et sans gluten sur demande. Avez-vous des restrictions alimentaires ?",
                "Italian": "La colazione costa 22 € a persona — servita dalle 8 alle 10 sulla terrazza con vista sul lago. Buffet ricco con pasticceria fresca, pane e prodotti locali sloveni. Opzioni vegane, vegetariane e senza glutine su richiesta. Hai restrizioni alimentari?",
                "Spanish": "El desayuno cuesta 22 € por persona — servido de 8 a 10 AM en la terraza con vistas al lago. Buffet rico con pasteles frescos, pan y productos locales eslovenos. Opciones veganas, vegetarianas y sin gluten bajo pedido. ¿Tiene restricciones alimentarias?",
                "Croatian": "Doručak košta 22 € po osobi — poslužuje se od 8 do 10 sati na terasi s pogledom na jezero. Bogati buffet sa svježim pecivom, kruhom i lokalnim slovenskim proizvodima. Veganska, vegetarijanska i bezglutenska jela na zahtjev. Imate li prehrambene restrikcije?",
                "Serbian": "Doručak košta 22 € po osobi — služi se od 8 do 10 sati na terasi s pogledom na jezero. Bogati buffet sa svežim pecivom, hlebom i lokalnim slovenskim proizvodima. Veganska, vegetarijanska i bezglutenska jela na zahtev. Imate li prehrambene restrikcije?",
            }
    elif any(w in q for w in ["restaurant", "dining", "dinner", "lunch", "menu", "chef", "food", "eat", "meal", "ristorante", "restaurante", "speise", "essen", "cucina", "manger", "nourriture", "resto", "restaurant"]):
        fallbacks = {
            "Slovenian": "Imamo restavracijo Adora Pop Up kar v hotelu! Ustvarjena kuhinja z lokalnimi slovenskimi sestavinami pod vodstvom šefa kuhinje Domena Demšara. Terasa ima ene najlepših razgledov na jezero. Rezervacija: +386 40 558 158. Želite rezervirati mizo?",
            "German": "Wir haben das Adora Pop Up Restaurant direkt im Hotel! Kreative Küche mit lokalen slowenischen Zutaten unter der Leitung von Küchenchef Domen Demšar. Die Terrasse bietet einen der besten Ausblicke auf den See. Reservierung: +386 40 558 158. Möchten Sie einen Tisch reservieren?",
            "French": "Nous avons le restaurant Adora Pop Up directement à l'hôtel! Cuisine créative avec des ingrédients slovènes locaux sous la direction du chef Domen Demšar. La terrasse offre l'une des meilleures vues sur le lac. Réservation: +386 40 558 158. Souhaitez-vous réserver une table?",
            "Italian": "Abbiamo il ristorante Adora Pop Up direttamente in hotel! Cucina creativa con ingredienti sloveni locali sotto la guida dello chef Domen Demšar. La terrazza offre una delle migliori viste sul lago. Prenotazione: +386 40 558 158. Vuoi riservare un tavolo?",
            "Spanish": "¡Tenemos el restaurante Adora Pop Up directamente en el hotel! Cocina creativa con ingredientes eslovenos locales bajo la dirección del chef Domen Demšar. La terrazza ofrece una de las mejores vistas al lago. Reserva: +386 40 558 158. ¿Te gustaría reservar una mesa?",
            "Croatian": "Imamo restoran Adora Pop Up izravno u hotelu! Kreativna kuhinja s lokalnim slovenskim sastojcima pod vodstvom šefa kuhinje Domena Demšara. Terasa nudi jedan od najboljih pogleda na jezero. Rezervacija: +386 40 558 158. Želite li rezervirati stol?",
            "Serbian": "Imamo restoran Adora Pop Up direktno u hotelu! Kreativna kuhinja sa lokalnim slovenskim sastojcima pod vodstvom šefa kuhinje Domena Demšara. Terasa nudi jedan od najboljih pogleda na jezero. Rezervacija: +386 40 558 158. Želite li rezervirati stol?",
        }
    elif any(w in q for w in ["parking", "park", "car", "parkplatz", "parkplätze", "parcheggio", "aparcamiento", "stationnement", "parken", "parkiranje", "avto", "auto", "wagen", "voiture", "coche", "macchina", "estacionamiento", "carro"]):
        fallbacks = {
            "Slovenian": "Imamo brezplačno parkirišče — 8 parkirnih mest pred hotelom. Boste vozili v Bled ali želite nasvete za javni prevoz?",
            "German": "Wir bieten kostenlosen privaten Parkplatz an — 8 Parkplätze direkt vor dem Hotel. Kommen Sie mit dem Auto nach Bled, oder benötigen Sie Tipps für den öffentlichen Nahverkehr?",
            "French": "Nous offrons un parking privé gratuit — 8 places de parking devant l'hôtel. Venez-vous à Bled en voiture, ou souhaitez-vous des conseils sur les transports en commun ?",
            "Italian": "Offriamo parcheggio privato gratuito — 8 posti auto davanti all'hotel. Verrai a Bled in auto, o vuoi suggerimenti sui trasporti pubblici?",
            "Spanish": "Ofrecemos estacionamiento privado gratuito — 8 espacios de estacionamiento frente al hotel. ¿Vas a venir a Bled en coche, o te gustaría recibir consejos sobre transporte público?",
            "Croatian": "Nudimo besplatno privatno parkiralište — 8 parkirnih mjesta ispred hotela. Dolazite li u Bled autom, ili želite savjete za javni prijevoz?",
            "Serbian": "Nudimo besplatno privatno parkiralište — 8 parkirnih mjesta ispred hotela. Dolazite li u Bled autom, ili želite savjete za javni prijevoz?",
        }
    elif any(w in q for w in ["check-in", "check in", "checkin", "arrival", "arrive", "enregistrement", "réception", "prijava", "prijave", "check-in horaires", "heures d'arrivée", "ankunft", "anreise", "arrivo", "arrivée", "llegada"]):
        fallbacks = {
            "Slovenian": "Prijava je od 14:00 do 23:00, odjava do 11:00. Pozna prijava/odjava je na voljo na zahtevo — kontaktirajte recepcijo. Ob kateri uri načrtujete prihod?",
            "German": "Check-in ist von 14:00 bis 23:00, Check-out bis 11:00. Später Check-in/Check-out ist auf Anfrage möglich — kontaktieren Sie die Rezeption. Um welche Uhrzeit planen Sie Ihre Ankunft?",
            "French": "L'enregistrement est de 14h00 à 23h00, le départ à 11h00. L'enregistrement/départ tardif est possible sur demande — contactez la réception. À quelle heure prévoyez-vous d'arriver ?",
            "Italian": "Il check-in è dalle 14:00 alle 23:00, il check-out fino alle 11:00. Check-in/check-out tardivo è disponibile su richiesta — contatta la reception. A che ora prevedi di arrivare?",
            "Spanish": "El check-in es de 14:00 a 23:00, el check-out hasta las 11:00. Check-in/check-out tardío está disponible bajo petición — contacte con recepción. ¿A qué hora planeas llegar?",
            "Croatian": "Prijava je od 14:00 do 23:00, odjava do 11:00. Kasna prijava/odjava je dostupna na zahtjev — kontaktirajte recepciju. U koje vrijeme planirate dolazak?",
            "Serbian": "Prijava je od 14:00 do 23:00, odjava do 11:00. Kasna prijava/odjava je dostupna na zahtev — kontaktirajte recepciju. U koje vrijeme planirate dolazak?",
        }
    else:
        fallbacks = {
            "Slovenian": "Villa Adora Bled je butični hotel ob jezeru Bled. Imamo 8 edinstvenih apartmajev z razgledom na jezero, restavracijo, brezplačno parkiranje in WiFi. Kaj vas zanima? Z veseljem vam pomagam?",
            "German": "Villa Adora Bled ist ein Boutique-Hotel am See Bled. Wir haben 8 einzigartige Suiten mit Seeblick, ein Restaurant, kostenloses Parken und WLAN. Was möchten Sie wissen? Ich helfe Ihnen gerne?",
            "French": "Villa Adora Bled est un hôtel de charme au lac Bled. Nous avons 8 suites uniques avec vue sur le lac, un restaurant, un parking gratuit et le WiFi. Que souhaitez-vous savoir? Je serai ravi de vous aider?",
            "Italian": "Villa Adora Bled è un boutique hotel sul lago di Bled. Abbiamo 8 suite uniche con vista sul lago, un ristorante, parcheggio gratuito e WiFi. Cosa vorresti sapere? Sarò felice di aiutarti?",
            "Spanish": "Villa Adora Bled es un hotel boutique en el lago Bled. Tenemos 8 suites únicas con vistas al lago, un restaurante, estacionamiento gratuito y WiFi. ¿Qué te gustaría saber? ¡Estaré encantado de ayudarte?",
            "Croatian": "Villa Adora Bled je butični hotel na jezeru Bled. Imamo 8 jedinstvenih apartmana s pogledom na jezero, restoran, besplatni parking i WiFi. Što vas zanima? Rado ću vam pomoći?",
            "Serbian": "Villa Adora Bled je butični hotel na jezeru Bled. Imamo 8 jedinstvenih apartmana s pogledom na jezero, restoran, besplatni parking i WiFi. Što vas zanima? Rado ću vam pomoći?",
        }
    return fallbacks.get(lang, fallbacks.get("Slovenian", "I'm here to help! What would you like to know about Villa Adora Bled?"))


def fix_spacing(text):
    """Fix common LLM spacing issues."""
    import re
    # Replace unicode whitespace variants with normal space (but NOT en-dash/em-dash which are used as separators)
    text = re.sub(r'[\u2000-\u200b\u202f\u205f\u00a0\u2011]', ' ', text)
    # Fix "WiFi" being split: "Wi Fi" -> "WiFi" (MUST run before the general uppercase split)
    text = re.sub(r'\bWi\s+Fi\b', 'WiFi', text, flags=re.IGNORECASE)
    # Fix double question marks (LLM over-application)
    text = re.sub(r'\?{2,}', '?', text)
    # Fix missing space between word and number: "from14:00" -> "from 14:00"
    text = re.sub(r'([a-zA-Z])(\d)', r'\1 \2', text)
    # Fix missing space between number and word: "11.What" -> "11. What"
    text = re.sub(r'(\d)([A-Z])', r'\1 \2', text)
    # Fix missing space after punctuation: "word.Word" -> "word. Word"
    text = re.sub(r'([.!?])([A-Z])', r'\1 \2', text)
    # Fix missing space after comma: "word,word" -> "word, word"
    text = re.sub(r',([a-zA-Z])', r', \1', text)
    # Fix missing space after colon: "word:word" -> "word: word"
    text = re.sub(r':([a-zA-Z])', r': \1', text)
    # Fix "from 8 10 AM" -> "from 8-10 AM"
    text = re.sub(r'from (\d{1,2}) (\d{1,2}) (AM|PM)', r'from \1-\2 \3', text, flags=re.IGNORECASE)
    # Fix run-on words: lowercase followed by uppercase with no space
    # Use a targeted approach: only split when the uppercase letter starts a new word
    # (i.e., followed by lowercase letters), NOT inside camelCase like "WiFi"
    text = re.sub(r'([a-z])([A-Z][a-z])', r'\1 \2', text)
    # Fix "WiFi" being split: "Wi Fi" -> "WiFi" (MUST run after the general uppercase split)
    text = re.sub(r'\bWi\s+Fi\b', 'WiFi', text, flags=re.IGNORECASE)
    text = re.sub(r'\bwi\s+fi\b', 'WiFi', text)
    # Fix common LLM spacing glitches
    text = re.sub(r'\bwewelcome\b', 'we welcome', text, flags=re.IGNORECASE)
    text = re.sub(r'\barriveat\b', 'arrive at', text, flags=re.IGNORECASE)
    text = re.sub(r'\binhouse\b', 'in-house', text, flags=re.IGNORECASE)
    text = re.sub(r'\bcheckout\b', 'check-out', text, flags=re.IGNORECASE)
    text = re.sub(r'\bcheckin\b', 'check-in', text, flags=re.IGNORECASE)
    text = re.sub(r'\blatecheck\b(?!out|in|[- ])', 'late check', text, flags=re.IGNORECASE)
    text = re.sub(r'\blatecheckout\b', 'late check-out', text, flags=re.IGNORECASE)
    text = re.sub(r'\blatecheckin\b', 'late check-in', text, flags=re.IGNORECASE)
    text = re.sub(r'\blatecheck-out\b', 'late check-out', text, flags=re.IGNORECASE)
    text = re.sub(r'\blatecheck-in\b', 'late check-in', text, flags=re.IGNORECASE)
    text = re.sub(r'\babar\b', 'a bar', text, flags=re.IGNORECASE)
    text = re.sub(r'\blakeview\b', 'lake view', text, flags=re.IGNORECASE)
    text = re.sub(r'\bfreeWiFi\b', 'free WiFi', text, flags=re.IGNORECASE)
    text = re.sub(r'\balate\b', 'a late', text, flags=re.IGNORECASE)
    text = re.sub(r'\bhelpyou\b', 'help you', text, flags=re.IGNORECASE)
    text = re.sub(r'\byoushare\b', 'you share', text, flags=re.IGNORECASE)
    text = re.sub(r'\bveganoptions\b', 'vegan options', text, flags=re.IGNORECASE)
    text = re.sub(r'\bnon-smoking\b', 'non-smoking', text, flags=re.IGNORECASE)
    text = re.sub(r'\barrangea\b', 'arrange a', text, flags=re.IGNORECASE)
    text = re.sub(r'\bcanoffer\b', 'can offer', text, flags=re.IGNORECASE)
    text = re.sub(r'\bcanprovide\b', 'can provide', text, flags=re.IGNORECASE)
    text = re.sub(r'\btheviews\b', 'the views', text, flags=re.IGNORECASE)
    text = re.sub(r'\bguestcan\b', 'guest can', text, flags=re.IGNORECASE)
    text = re.sub(r'\bwealso\b', 'we also', text, flags=re.IGNORECASE)
    text = re.sub(r'\bwehave\b', 'we have', text, flags=re.IGNORECASE)
    text = re.sub(r'\bwedon\b', "we don", text, flags=re.IGNORECASE)
    text = re.sub(r'\byoucan\b', 'you can', text, flags=re.IGNORECASE)
    text = re.sub(r'\bweoffer\b', 'we offer', text, flags=re.IGNORECASE)
    text = re.sub(r'\bIcan\b', 'I can', text, flags=re.IGNORECASE)
    text = re.sub(r'\bwecan\b', 'we can', text, flags=re.IGNORECASE)
    text = re.sub(r'\bweare\b', 'we are', text, flags=re.IGNORECASE)
    text = re.sub(r'\bthebest\b', 'the best', text, flags=re.IGNORECASE)
    text = re.sub(r'\bthemost\b', 'the most', text, flags=re.IGNORECASE)
    text = re.sub(r'\bnousavons\b', 'nous avons', text, flags=re.IGNORECASE)
    text = re.sub(r'\bdeschambres\b', 'des chambres', text, flags=re.IGNORECASE)
    text = re.sub(r'\bilya\b', 'il y a', text, flags=re.IGNORECASE)
    text = re.sub(r'\bmercibeaucoup\b', 'merci beaucoup', text, flags=re.IGNORECASE)
    text = re.sub(r'\bgraziemolto\b', 'grazie molto', text, flags=re.IGNORECASE)
    text = re.sub(r'\bperfavore\b', 'per favore', text, flags=re.IGNORECASE)
    text = re.sub(r'\bsehrguten\b', 'sehr guten', text, flags=re.IGNORECASE)
    text = re.sub(r'\bvielendank\b', 'vielen Dank', text, flags=re.IGNORECASE)
    text = re.sub(r'\bhabenzimmer\b', 'haben Zimmer', text, flags=re.IGNORECASE)
    text = re.sub(r'\bprosim\b', ' prosim', text, flags=re.IGNORECASE)
    text = re.sub(r'\bimate\b', ' imate', text, flags=re.IGNORECASE)
    text = re.sub(r'\bhvala\b', ' hvala', text, flags=re.IGNORECASE)
    text = re.sub(r'\bzdravo\b', ' zdravo', text, flags=re.IGNORECASE)
    # Fix "Howcan" -> "How can"
    text = re.sub(r'\bHowcan\b', 'How can', text)
    # Fix "Isthere" -> "Is there"
    text = re.sub(r'\bIsthere\b', 'Is there', text, flags=re.IGNORECASE)
    # Fix "Wherewould" -> "Where would"
    text = re.sub(r'\bWherewould\b', 'Where would', text, flags=re.IGNORECASE)
    # Fix "a" merged with following word: "abooking" -> "a booking"
    text = re.sub(r'\ba(booking|breakfast|restaurant|reservation|shuttle|transfer|bar|hotel|room|suite|pool|spa|gym|park|dog|cat|car|taxi|tour|trip|table|meal|drink|menu)\b', r'a \1', text)
    # Fix common lowercase word merges: "messagemight" -> "message might"
    common_merges = [
        ('message', 'might'), ('message', 'may'), ('your', 'message'), ('your', 'booking'),
        ('is', 'a'), ('it', 'is'), ('in', 'the'), ('to', 'the'), ('on', 'the'),
        ('at', 'the'), ('for', 'the'), ('with', 'the'), ('from', 'the'), ('by', 'the'),
        ('and', 'the'), ('and', 'a'), ('or', 'the'), ('or', 'a'), ('but', 'the'),
        ('this', 'is'), ('that', 'is'), ('there', 'is'), ('here', 'is'), ('where', 'is'),
        ('what', 'is'), ('how', 'is'), ('who', 'is'), ('when', 'is'), ('why', 'is'),
        ('can', 'you'), ('could', 'you'), ('would', 'you'), ('should', 'you'),
        ('will', 'you'), ('shall', 'you'), ('may', 'i'), ('can', 'i'), ('could', 'i'),
        ('do', 'you'), ('did', 'you'), ('are', 'you'), ('were', 'you'), ('have', 'you'),
        ('is', 'there'), ('are', 'there'), ('was', 'there'), ('were', 'there'),
        ('i', 'am'), ('i', 'have'), ('i', 'will'), ('i', 'would'), ('i', 'can'),
        ('we', 'are'), ('we', 'have'), ('we', 'will'), ('we', 'can'), ('we', 'would'),
        ('they', 'are'), ('they', 'have'), ('they', 'will'), ('they', 'can'),
        ('you', 'are'), ('you', 'have'), ('you', 'will'), ('you', 'can'),
    ]
    for w1, w2 in common_merges:
        text = re.sub(r'\b' + w1 + w2 + r'\b', w1 + ' ' + w2, text, flags=re.IGNORECASE)
    # Fix missing space: lowercase-to-uppercase word joints (common LLM glitch)
    text = re.sub(r'\byouare\b', 'you are', text, flags=re.IGNORECASE)
    text = re.sub(r'\byouhave\b', 'you have', text, flags=re.IGNORECASE)
    text = re.sub(r'\bIwill\b', 'I will', text)
    text = re.sub(r'\bIam\b', 'I am', text)
    text = re.sub(r'\btherestaurant\b', 'the restaurant', text, flags=re.IGNORECASE)
    text = re.sub(r'\bthehotel\b', 'the hotel', text, flags=re.IGNORECASE)
    text = re.sub(r'\bourrestaurant\b', 'our restaurant', text, flags=re.IGNORECASE)
    text = re.sub(r'\bourbar\b', 'our bar', text, flags=re.IGNORECASE)
    text = re.sub(r'\bforbreakfast\b', 'for breakfast', text, flags=re.IGNORECASE)
    text = re.sub(r'\bforlunch\b', 'for lunch', text, flags=re.IGNORECASE)
    text = re.sub(r'\bfordinner\b', 'for dinner', text, flags=re.IGNORECASE)
    text = re.sub(r'\bwithus\b', 'with us', text, flags=re.IGNORECASE)
    text = re.sub(r'\bwithme\b', 'with me', text, flags=re.IGNORECASE)
    text = re.sub(r'\bforme\b', 'for me', text, flags=re.IGNORECASE)
    text = re.sub(r'\btoyou\b', 'to you', text, flags=re.IGNORECASE)
    text = re.sub(r'\btous\b', 'to us', text, flags=re.IGNORECASE)
    # Fix missing space between common words and proper nouns
    text = re.sub(r'\binBled\b', 'in Bled', text)
    text = re.sub(r'\batBled\b', 'at Bled', text)
    text = re.sub(r'\bonBled\b', 'on Bled', text)
    text = re.sub(r'\bofBled\b', 'of Bled', text)
    text = re.sub(r'\bfromBled\b', 'from Bled', text)
    text = re.sub(r'\btoBled\b', 'to Bled', text)
    text = re.sub(r'\bLakeBled\b', 'Lake Bled', text)
    text = re.sub(r'\bBledCastle\b', 'Bled Castle', text)
    text = re.sub(r'\bBledIsland\b', 'Bled Island', text)
    text = re.sub(r'\bLakeBohinj\b', 'Lake Bohinj', text)
    text = re.sub(r'\bVillaAdora\b', 'Villa Adora', text)
    text = re.sub(r'\bAdoraPop\b', 'Adora Pop', text)
    text = re.sub(r'\bChefDomen\b', 'Chef Domen', text)
    text = re.sub(r'\bDemšar\b', 'Demšar', text)
    # Fix missing space/question mark before question words
    text = re.sub(r'(today|there|here|so|and|but|yes|no|great|perfect|wonderful|sorry)\s+(are you|do you|would you|can you|will you|is it|can I|shall I|should I|have you|did you|were you)\s', r'\1? \2 ', text, flags=re.IGNORECASE)
    # Fix missing space after period before common words
    text = re.sub(r'\.(The|We|Our|You|It|I|For|And|But|Or|If|When|How|What|Where|Yes|No|Please|Thank)', r'. \1', text)
    # Fix missing space after period in other languages
    text = re.sub(r'\.(Il|La|Le|Les|Un|Une|El|Los|Las|Der|Die|Das|Ein|Una|Lo|Gli)', r'. \1', text)
    # Fix "?" followed by a word without space (e.g. "Where? would" -> "Where would?")
    text = re.sub(r'\?\s*([a-z])', r'? \1', text)
    # If we now have "? word?" at the end, merge: "Where would you like?" not "Where? would you like?"
    # Actually just remove the stray ? mid-sentence and ensure final ? at end
    # Fix "??" from LLM + post-processor
    text = re.sub(r'\?{2,}', '?', text)
    # Fix missing space before parentheses
    text = re.sub(r'([a-zA-Z])\(', r' \1 (', text)
    # Remove common emoji characters that break the ? ending requirement
    text = re.sub(r'[😊😀😃😄😁😆😂🤣☺️😇🙂😉😍🥰😘🤗🤩😋😜🤪😎🤓🧐🥳🥸😏🤠🤑😈👋👍👌🤝✌️🤞👏🙌🤲💯🌟✨🎉🎊❤️🧡💛💚💙💜🖤🤍🤎💖💕💞💓💗💘💝⭐🔥💥⚡🌈☀️🌙🌸🌺🌻🌹💐🎀🏆🥇🎖️🏅]+', '', text)
    # Fix multiple spaces
    text = re.sub(r'  +', ' ', text)
    return text.strip()




def _ensure_follow_up(text: str, topic: str = "", lang: str = "English") -> str:
    """Ensure the response ends with a follow-up question. If not, append one."""
    if not text or not text.strip():
        return text
    text = text.strip()
    if text.endswith("?"):
        return text
    if "?" in text[-80:]:
        return text
    # Don't append a topic question if the text already contains a question somewhere
    # (e.g., from translated content that has a question mid-text)
    if "?" in text:
        return text
    # Localized follow-up questions by topic and language
    questions = {
        "rooms": {
            "English": " Which one catches your eye? I can start a booking for you \u2014 just tell me your name and dates?",
            "Slovenian": " Kateri vas najbolj pritegne? Lahko za\u010dnem z rezervacijo \u2014 samo povejte mi va\u0161e ime in datume?",
            "German": " Welche Suite gef\u00e4llt Ihnen am besten? Ich kann gerne eine Buchung starten \u2014 ich brauche nur Ihren Namen und Ihre Reisedaten?",
            "French": " Laquelle vous pla\u00eet le plus ? Je peux r\u00e9server pour vous \u2014 j'ai besoin de votre nom et de vos dates ?",
            "Italian": " Quale ti piace di pi\u00f9? Posso prenotare per te \u2014 mi servono solo nome e date?",
            "Spanish": "\u00bfCu\u00e1l te gusta m\u00e1s? Puedo hacer la reserva \u2014 solo necesito tu nombre y las fechas?",
            "Croatian": " Koji vas najviše zanima? Mogu pokrenuti rezervaciju — samo mi recite vaše ime i datume?",
            "Serbian": " Koji vas najviše zanima? Mogu pokrenuti rezervaciju — samo mi recite vaše ime i datume?",
        },
        "experiences": {
            "English": " Which of these sounds most appealing to you? I'd love to help you plan it!",
            "Slovenian": " Katero aktivnost vas najbolj zanima? Z veseljem vam jo pomagam organizirati?",
            "German": " Welche Aktivität interessiert Sie am meisten? Ich helfe gerne bei der Organisation?",
            "French": " Laquelle vous intéresse le plus ? Je serai ravi de vous aider à l'organiser!",
            "Italian": " Quale ti interessa di più? Sarà un piacere aiutarti!",
            "Spanish": " ¿Cuál te interesa más? ¡Estaré encantado de ayudarte?",
            "Croatian": " Koja vas aktivnost najviše zanima? Rado ću vam pomoći s organizacijom!",
            "Serbian": " Koja vas aktivnost najviše zanima? Rado ću vam pomoći s organizacijom!",
        },
        "activities": {
            "English": " Which of these sounds most appealing to you? I'd love to help you plan it!",
            "Slovenian": " Katero aktivnost vas najbolj zanima? Z veseljem vam jo pomagam organizirati?",
            "German": " Welche Aktivität interessiert Sie am meisten? Ich helfe gerne bei der Organisation?",
            "French": " Laquelle vous intéresse le plus ? Je serai ravi de vous aider à l'organiser!",
            "Italian": " Quale ti interessa di più? Sarà un piacere aiutarti!",
            "Spanish": " ¿Cuál te interesa más? ¡Estaré encantado de ayudarte?",
            "Croatian": " Koja vas aktivnost najviše zanima? Rado ću vam pomoći s organizacijom!",
            "Serbian": " Koja vas aktivnost najviše zanima? Rado ću vam pomoći s organizacijom!",
        },
    }
    # Generic follow-up when topic not matched
    generic = {
        "English": " Is there anything else I can help you with?",
        "Slovenian": " Vas kaj drugo zanima? Z veseljem vam pomagam!",
        "German": " Gibt es noch etwas, womit ich Ihnen helfen kann?",
        "French": " Y a-t-il autre chose que je puisse faire pour vous ?",
        "Italian": " C'è altro con cui posso aiutarti?",
        "Spanish": " ¿Hay algo más en lo que pueda ayudarte?",
        "Croatian": " Ima li još nešto u čemu vam mogu pomoći?",
        "Serbian": " Ima li još nešto u čemu vam mogu pomoći?",
    }
    topic_questions = questions.get(topic, {})
    if topic_questions:
        return text + topic_questions.get(lang, topic_questions.get("English", ""))
    return text + generic.get(lang, generic.get("English", ""))

def clean_response(text):
    """Remove model reasoning/chain-of-thought text from responses."""
    import re as _re
    text = _re.sub(r'<tools>.*?</tools>', '', text, flags=_re.DOTALL | _re.IGNORECASE)
    # Remove leaked function/tool JSON schemas (aggressive)
    text = _re.sub(r'\{[^{}]*"type"\s*:\s*"string"[^{}]*\}', '', text, flags=_re.DOTALL | _re.IGNORECASE)
    text = _re.sub(r'\{[^{}]*"description"\s*:[^{}]*"name"\s*:[^{}]*"parameters"\s*:[^{}]*\}', '', text, flags=_re.DOTALL | _re.IGNORECASE)
    text = _re.sub(r'\{[^{}]*"type"\s*:\s*"[a-z]+"[^{}]*"properties"\s*:[^{}]*\}', '', text, flags=_re.DOTALL | _re.IGNORECASE)
    # Remove any remaining JSON-like fragments with quoted keys
    text = _re.sub(r'"\w+"\s*:\s*(?:\{[^}]*\}|\[[^\]]*\]|"[^"]*"|\w+)\s*,?\s*', '', text)
    text = _re.sub(r'<think>.*?</think>', '', text, flags=_re.DOTALL | _re.IGNORECASE)
    text = _re.sub(r'</?[a-zA-Z][a-zA-Z0-9]*>', '', text)
    lines = text.split('\n')
    reasoning_markers = [
        "we need to respond:", "according to the rules:", "so we can say:",
        "let's craft:", "thus:", "therefore:", "i should", "we should",
        "the guest says", "they already gave", "we can confirm",
        "end with a follow-up", "i've noted your"
    ]
    has_reasoning = any(marker in text.lower() for marker in reasoning_markers)
    if has_reasoning and len(text) > 200:
        for i in range(len(lines) - 1, -1, -1):
            line = lines[i].strip()
            if line and len(line) > 20 and not any(m in line.lower() for m in reasoning_markers):
                return '\n'.join(lines[i:]).strip()
    return text


def _ensure_ends_with_question(text: str) -> str:
    """Post-processor: ensure the response ends with a question mark.
    Only converts '.' endings to '?'. Preserves '!' endings as-is
    (e.g., 'You're very welcome!' should not become 'You're very welcome?').
    If the text already contains a question near the end, don't modify it."""
    text = text.rstrip()
    if not text:
        return "Is there anything else I can help you with?"
    # Already ends with ? — fine
    if text.endswith("?"):
        return text
    # Ends with ! — keep it (exclamatory social responses)
    if text.endswith("!"):
        return text
    # Ends with . — convert to ?
    if text.endswith("."):
        text = text[:-1] + "?"
    elif not text.endswith(("?", "!", ".", ",", ";", ":")):
        # No punctuation at all — add ?
        text = text + "?"
    return text


def extract_time_from_message(message):
    """Extract time from a natural language message."""
    patterns = [
        r'(?:at|around|about|by|before|after)\s+(\d{1,2}):?(\d{2})?\s*(am|pm|AM|PM)?',
        r'(\d{1,2}):(\d{2})\s*(am|pm|AM|PM)?',
        r'(\d{1,2})\s*(am|pm|AM|PM)',
        r'(?:at|around|about|by|before|after)\s+(\d{1,2})\s*(am|pm|AM|PM)?',
    ]
    msg_lower = message.lower()
    for pattern in patterns:
        match = re.search(pattern, msg_lower)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            ampm = match.group(3) if len(match.groups()) >= 3 and match.group(3) else None
            if ampm:
                ampm = ampm.lower()
                if ampm == 'pm' and hour < 12:
                    hour += 12
                elif ampm == 'am' and hour == 12:
                    hour = 0
            return f"{hour:02d}:{minute:02d}"
    return None


def extract_date_from_message(message):
    """Extract a date from a natural language message when possible."""
    import datetime as _dt

    msg = message.strip()
    msg_lower = msg.lower()

    # ISO date: 2026-06-15
    iso_match = re.search(r'\b(20\d{2}-\d{2}-\d{2})\b', msg)
    if iso_match:
        return iso_match.group(1)

    # European date: 15.06.2026
    eu_match = re.search(r'\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b', msg)
    if eu_match:
        day, month, year = map(int, eu_match.groups())
        try:
            return _dt.date(year, month, day).isoformat()
        except ValueError:
            return ""

    # Month names with optional year
    month_names = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
        "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    month_pattern = "|".join(month_names.keys())
    for pattern in [
        rf'\b({month_pattern})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(20\d{{2}}))?\b',
        rf'\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_pattern})(?:,?\s+(20\d{{2}}))?\b',
    ]:
        match = re.search(pattern, msg_lower)
        if match:
            parts = match.groups()
            if parts[0] in month_names:
                month = month_names[parts[0]]
                day = int(parts[1])
                year = int(parts[2]) if parts[2] else _dt.date.today().year
            else:
                day = int(parts[0])
                month = month_names[parts[1]]
                year = int(parts[2]) if parts[2] else _dt.date.today().year
            try:
                return _dt.date(year, month, day).isoformat()
            except ValueError:
                return ""

    if "tomorrow" in msg_lower:
        return (_dt.date.today() + _dt.timedelta(days=1)).isoformat()
    if "today" in msg_lower:
        return _dt.date.today().isoformat()

    return ""


def build_system_prompt() -> str:
    return (
        "You are Luka, a warm and knowledgeable hotel concierge at Villa Adora Bled, a luxury boutique hotel on Lake Bled, Slovenia.\n\n"
        "## LANGUAGE (CRITICAL)\n"
        "- Detect the guest's language from their message and respond in the SAME language.\n"
        "- Supported: English, Slovenian, German, Italian, French, Spanish, Croatian, Serbian.\n"
        "- When a tool returns English information, you MUST translate it to the guest's language. This is NON-NEGOTIABLE.\n"
        "- Keep the same warm, concise style regardless of language.\n\n"
        "## STYLE\n"
        "- Be warm, concise, and conversational — like a real human concierge.\n"
        "- 2-3 sentences max for simple answers. Use bullet points for listings (rooms, experiences).\n"
        "- ALWAYS end with a follow-up question (MANDATORY for ALL responses including greetings/thanks/goodbyes).\n"
        "- Proactively offer to book: 'Shall I book a table for you?', 'Would you like me to start a booking?'\n\n"
        "## RULES\n"
        "- NEVER output raw JSON, function definitions, tool schemas, or parameter descriptions.\n"
        "- NEVER mention technical details: no databases, APIs, SQLite, Flask, RAG, tools, or internal systems.\n"
        "- NEVER mention room prices unless the guest specifically asks.\n"
        "- NEVER invent or hallucinate services, amenities, or policies not in the hotel data.\n"
        "- Villa Adora does NOT have a spa, wellness center, or swimming pool — only in-room massage (24h notice).\n"
        "- NEVER use the words 'spa', 'wellness center', or 'treatment' — say 'in-room massage' instead.\n"
        "- NEVER say '7 rooms' — there are EXACTLY 8 suites. NEVER add suites not in the official list.\n"
        "- If guest is frustrated or explicitly asks for a human, use request_human_agent().\n"
        "- ALWAYS use query_hotel_info tool for factual questions — never answer from your own knowledge.\n\n"
        "## KEY FACTS\n"
        "- Check-in: 14:00-23:00 | Check-out: 07:00-11:00 | Late check-in/out on request\n"
        "- Breakfast: €22/person (NOT included in room rate). Served 8-10 AM. Vegan/vegetarian/gluten-free on request.\n"
        "- Restaurant: Adora Pop Up Restaurant by Chef Domen Demšar. Lunch/dinner Tue-Sun, brunch Thu-Sat.\n"
        "- Tasting menu ~€65/person, wine pairing ~€35/person. Terrace with best sunset views in Bled.\n"
        "- Reservations: +386 40 558 158 or evita.vilebled@gmail.com\n"
        "- Free parking (8 spots) and WiFi. Pets allowed on request (€35/pet/night).\n"
        "- Shuttle: Ljubljana airport ~€60, Bled town center ~€15. Book directly in chat.\n"
        "- Address: Cesta svobode 35, Bled, Slovenia | Phone/WhatsApp: +386 51 603 858\n"
        "- Booking.com: 9.1/10 Wonderful (698 reviews) | TripAdvisor: 4.7/5 Travelers' Choice\n\n"
        "## ROOMS (EXACT — never invent or add others)\n"
        "Princess Suite (55 m², tower view, €440), Luxury Suite (lake view, €480), Penthouse Suite (60 m², 2 floors, €430), Deluxe Suite (lake view, €570), Superior Suite (sleeps 4, €570), Island Suite (65 m², sleeps 4, €620), Swan Suite (67 m², King bed, price on request), Prestige Suite (72 m², ground floor, price on request).\n\n"
        "## HISTORY\n"
        "Villa Adora was built in 1878 as a private villa during the Austro-Hungarian era, when Bled was a fashionable resort for European aristocracy. Originally known as Vila Istra, it was carefully converted into a luxury design hotel. The villa is heritage-protected under Slovenian cultural heritage laws."
    )


def format_rag_context(docs: list[str]) -> str:
    lines = []
    for doc in docs:
        text = doc.strip()
        if text:
            lines.append(text)
    return "\n\n".join(lines)


def maybe_retrieve_hotel_facts(query: str, max_facts: int = 2) -> list[str]:
    if not _RAG_AVAILABLE:
        return []
    try:
        return rag_retrieve(query=query, top_k=max_facts)
    except Exception:
        return []


def _looks_like_english(message: str) -> bool:
    """Return True for common English guest messages, even when shared words overlap other languages."""
    import re as _re
    msg = " " + _re.sub(r'[!?,.;:()\[\]{}]', ' ', message.lower().strip()) + " "
    msg = _re.sub(r'  +', ' ', msg)
    return any(w in msg for w in [
        " do you ", " can i ", " can we ", " tell me ", " i want ", " i will ", " i would ",
        " are you ", " where ", " what ", " how ", " spa ", " wellness ", " cribs ", " crib ",
        " extra beds ", " extra bed ", " wedding ", " cocktail ", " drinks ", " bar "
    ])


def _detect_language(message: str) -> str:
    """Simple language detection based on common words and character patterns."""
    import re as _re
    import unicodedata as _ud
    # Normalize Unicode to NFC for consistent matching
    message = _ud.normalize("NFC", message)
    msg_raw = " " + message.lower().strip() + " "
    # For word matching, create a version with punctuation replaced by spaces
    msg = " " + _re.sub(r'[!?,.;:()\[\]{}]', ' ', message.lower().strip()) + " "
    # Collapse multiple spaces
    msg = _re.sub(r'  +', ' ', msg)

    # Quick high-confidence checks for common greetings (before any word-list matching)
    # These prevent misdetection when short common words overlap across languages
    if " ciao " in msg or msg.strip() == "ciao":
        return "Italian"
    if " pozdravljeni " in msg or msg.strip() == "pozdravljeni":
        return "Slovenian"
    if " pozdrav " in msg or msg.strip() == "pozdrav":
        return "Croatian"
    if " guten tag " in msg or " guten morgen " in msg or " guten abend " in msg or " vielen dank " in msg or " danke " in msg:
        return "German"
    if " bonjour " in msg or msg.strip() == "bonjour":
        return "French"
    if " hola " in msg or msg.strip() == "hola":
        return "Spanish"
    if " buongiorno " in msg or msg.strip() == "buongiorno":
        return "Italian"
    # High-confidence English check: if the message contains common English-only
    # words with no non-English markers, return English early to prevent
    # false-positive Croatian/Slovenian detection from shared vocabulary
    if any(w in msg for w in [
        " room ", " rooms ", " suite ", " suites ", " book ", " booking ", " check-in ", " check-out ",
        " breakfast ", " parking ", " restaurant ", " hello ", " hi ", " thank ", " please ", " would ",
        " could ", " welcome ", " goodbye ", " do you ", " can i ", " can we ", " tell me ", " i want ",
        " i will ", " i would ", " spa ", " wellness ", " cribs ", " crib ", " extra beds ", " extra bed ",
        " wedding ", " bar ", " cocktail ", " drinks ", " where ", " what ", " how ", " are you "
    ]):
        return "English"

    # Character-based detection for languages with unique characters
    # Serbian detection (Cyrillic-specific characters or Serbian Latin words)
    serbian_cyrillic = ['ђ', 'ј', 'љ', 'њ', 'ћ', 'ѕ']
    if any(c in msg for c in serbian_cyrillic):
        return "Serbian"
    # Serbian Latin words (distinct from Croatian)
    serbian_words = [" добар дан ", " хвала ", " молим ", " добродошли ", " собе ", " апартман ", " имате ", " могу ", " желим ", " који ", " каква ", " колико ", " цена ", " језеро ", " оток ", " град ", " разглед ", " поглед ", " активности ", " масажа ", " вино ", " храна ", " пиће ", " ресторана ", " хотел ", " соба ", " спаваћа ", " купатило ", " терета ", " паркинг ", " ауто ", " аеродром ", " такси ", " трансфер ", " резервација ", " пријава ", " одјава ", " касније ", " рано ", " добро ", " супер ", " одлично ", " хвала лепо ", " на видење ", " довиђења ", " срећан пут ", " поздрав ", " здраво ", " ћао ", " бок ", " живело "]
    if any(w in msg for w in serbian_words):
        return "Serbian"
    # Slovenian/Croatian specific characters (š, č, ž)
    if any(c in msg for c in ['š', 'č', 'ž']):
        slovenian_markers = [ " imate ", " kakšen ", " kako ", " lahko ", " želim ", " prosim ", " hvala ", " pozdravljeni ", " dober dan ", " zdravo ", " sobe ", " soba "]
        if any(w in msg for w in slovenian_markers):
            return "Slovenian"
        if 'đ' in msg or 'ć' in msg:
            return "Croatian"
        return "Slovenian"
    # Croatian/Serbian shared characters (đ, ć) — default to Croatian
    if 'đ' in msg or 'ć' in msg:
        return "Croatian"

    # Word-based Slovenian detection (without diacritics)
    slovenian_words = [ " pozdravljeni ", " hvala ", " prosim ", " kako ste ", " dober dan ", " nasvidenje ", " rezervacija ", " zajtrk ", " sobe ", " soba ", " apartma ", " imate ", " lahko ", " želim ", " kakšen ", " kakšni ", " količina ", " gostje ", " gostom ", " jutri ", " danes ", " nočitev ", " koliko ", " stane", " prijava ", " prijave ", " odjava ", " kje ", " kako ", " ura ", " urah ", " restavracija ", " parkirno ", " pes ", " aktivnosti ", " jezero ", " otok ", " grad ", " razgled ", " pogled ", " cena ", " cene ", " koliko ", " kajenje ", " kaditi ", " dovoljeno ", " prepovedano ", " omogočeno ", " kje lahko ", " ali je ", " ali imate ", " kakšna ", " kakšne ", " kateri ", " katera ", " prosim vas ", " hvala lepo ", " lep pozdrav ", " se vidimo ", " na svidenje ", " lahko noč ", " dober večer ", " dobro jutro ", " kako vam lahko pomagam ", " želim rezervirati ", " koliko stane ", " kje ste ", " kako dostopam ", " ali lahko ", " bi radi ", " bi želel ", " bi želela ", " najboljši ", " najboljša ", " priporočam ", " priporočamo ", " odlično ", " super ", " super hvala ", " hvala za ", " ni za kaj ", " v redu ", " se strinjam ", " razumem ", " ne razumem ", " ponovite ", " prosim ponovite ", " kje je ", " kje so ", " kdaj ", " zakaj ", " kako dela ", " kako gre ", " vse najboljše ", " srečno ", " nasvidenje ", " adijo ", " aju ", " ciao ", " bok ", " zbogom ", " dovidenja ", " se slišimo ", " lep dan ", " veseli nas ", " vesel bom ", " vesela bom ", " nasvidenje ", " se kmalu vidimo ", " lepa pozdrava ", " srčno pozdravljeni ", " pozdravljeni ", " pozdravljena ", " pozdravljene ", " pozdravljeni ", " pozdravljen ", " pozdravljena ", " pozdravljene "]
    if any(w in msg for w in slovenian_words):
        return "Slovenian"

    # German-specific characters
    if any(c in msg for c in ['ß', 'ä', 'ö', 'ü']):
        return "German"

    # French-specific characters (check unique French chars first)
    if any(c in msg for c in ['ç', 'ê', 'î', 'ô', 'û', 'ë', 'ï', 'œ', 'æ']):
        return "French"
    # French word-based detection for shared accented chars (é, è, à, ù)
    if any(c in msg for c in ['é', 'è', 'à', 'ù']):
        french_words = [" bonjour ", " bonsoir ", " merci ", " vous ", " nous ", " chambre ", " petit ", " déjeuner ", " réservation ", " avez ", " pouvez ", " voudrais ", " c'est ", " est ", " les ", " des ", " dans ", " pour ", " avec "]
        if any(w in msg for w in french_words):
            return "French"

    # Spanish-specific characters
    if any(c in msg for c in ['ñ', 'á', 'í', 'ó', 'ú', '¿', '¡']):
        return "Spanish"

    # Spanish word patterns (check BEFORE French/Italian to avoid misclassification)
    spanish_words = [" hola ", " buenos ", " buenas ", " tienen ", " habitaciones ", " gracias ", " por favor ", " quisiera ", " desayuno ", " restaurante ", " bienvenido ", " hasta luego ", " magnífico ", " perfecto ", " reservación ", " cuarto ", " cuartos ", " noches ", " días "]
    if any(w in msg for w in spanish_words):
        return "Spanish"

    # Italian-specific characters (check AFTER French since they share some)
    if any(c in msg for c in ['à', 'è', 'é', 'ì', 'ò', 'ù']):
        # Could be French or Italian - check words
        italian_words = [" buongiorno ", " buonasera ", " grazie ", " vorrei ", " avete ", " prenotazione ", " colazione ", " ristorante ", " arrivederci ", " camere ", " camera ", " dove ", " dov ", " dov' ", " dov’ ", " parlami ", " parlez ", " quanto ", " come ", " dove si ", " dove è ", " dov'è ", " dov’è ", " soggiorno ", " per favore ", " piacere ", " bellissimo ", " magnifico ", " splendido ", " incantevole ", " meraviglioso "]
        if any(w in msg for w in italian_words):
            return "Italian"

    # Word-based detection for languages without unique characters
    # French word patterns
    french_words = [ " bonjour ", " bonsoir ", " merci ", " s'il vous ", " je voudrais ", " avez-vous ", " nous avons ", " les chambres ", " petit déjeuner ", " au revoir ", " bienvenue ", " c'est ", " réservation ", " chambre ", " chambres ", " pouvez ", " voulez ", " souhaitez ", " souhaite ", " j'aimerais ", " je souhaiterais ", " animaux ", " chien ", " chat ", " vins ", " activités ", " où ", " combien ", " parlez "]
    if any(w in msg for w in french_words):
        return "French"

    # Italian word-based detection (BEFORE Slovenian to avoid false matches on shared words like "avete")
    italian_words = [ " ciao ", " buongiorno ", " buonasera ", " vorrei ", " prenotazione ", " colazione ", " ristorante ", " arrivederci ", " camere ", " camera ", " alloggio ", " soggiorno ", " piacere ", " splendido ", " incantevole ", " meraviglioso ", " favoloso ", " bellissimo ", " magnifico "]
    if any(w in msg for w in italian_words):
        return "Italian"

    # Croatian word-based detection (BEFORE Slovenian to avoid false matches on shared words like "sobe", "imate")
    croatian_words = [ " pozdrav ", " bok ", " zdravo ", " doviđenja ", " hvala lijepa ", " molim vas ", " kako ste ", " dobar dan ", " laku noć ", " soba ", " sobe ", " apartman ", " rezervacija ", " doručak ", " restoran ", " kuhinja ", " vino ", " pivo ", " kava ", " čaj ", " plaža ", " more ", " planina ", " grad ", " otok ", " most ", " ulica ", " trg ", " park ", " škola ", " crkva ", " bolnica ", " ljekarna ", " pošta ", " banka ", " trgovina ", " restorani ", " kafić ", " pivnica ", " slastičarna ", " pekara ", " mesnica ", " ribarnica ", " voće ", " povrće ", " meso ", " riba ", " kruh ", " mlijeko ", " sir ", " jogurt ", " voćni ", " povrtni ", " dnevni ", " noćni ", " tjedni ", " mjesečni ", " godišnji ", " pola ", " cijeli ", " pola sata ", " sat ", " minuta ", " sati ", " minuta ", " jutro ", " popodne ", " večer ", " noć ", " danas ", " sutra ", " jučer ", " prekosutra ", " ovaj ", " onaj ", " taj ", " moj ", " tvoj ", " njegov ", " njezin ", " naš ", " vaš ", " njihov ", " ova ", " ona ", " ta ", " ovo ", " ono ", " to ", " koji ", " koja ", " koje ", " što ", " zašto ", " kako ", " gdje ", " kad ", " koliko ", " tko ", " čiji ", " nešto ", " ništa ", " svatko ", " nitko ", " svaki ", " svaka ", " svako ", " neki ", " neka ", " neko ", " mnogo ", " malo ", " više ", " manje ", " najviše ", " najmanje ", " dobro ", " loše ", " lijepo ", " ružno ", " veliko ", " malo ", " dugo ", " kratko ", " široko ", " usko ", " visoko ", " nisko ", " debelo ", " tanko ", " teško ", " lako ", " brzo ", " sporo ", " skupo ", " jeftino ", " staro ", " novo ", " mlado ", " staro ", " čisto ", " prljavo ", " toplo ", " hladno ", " vruće ", " ledeno ", " suho ", " mokro ", " tvrdo ", " meko ", " glasno ", " tiho ", " svijetlo ", " tamno ", " crno ", " bijelo ", " crveno ", " plavo ", " zeleno ", " žuto ", " narančasto ", " ljubičasto ", " sivo ", " smeđe ", " zlatno ", " srebrno "]
    if any(w in msg for w in croatian_words):
        return "Croatian"

    # Multi-word phrases that are highly distinctive per language
    distinctive_phrases = {
        "German": [
            " guten tag ", " guten morgen ", " guten abend ", " vielen danke ", " vielen dank ",
            " auf wiedersehen ", " wie geht ", " haben sie ", " ich möchte ",
            " können wir ", " ich hätte ", " buchung ", " zimmer ", " zimmern ", " frühstück ",
            " parkplatz ", " haustier ", " abreise ", " anreise ", " wunderbar ",
            " buchen ", " reservierung ", " kammer ", " schlafzimmer ",
            " einen parkplatz ", " parken ", " auto ", " wagen ", " erzählen ", " wie viel ", " was kostet ", " wie kostet ", " prinzessin ",
            " erlaubt ", " rauchen ", " kostenlos ", " kontaktieren ",
            " kontakt ", " telefon ", " email ", " e-mail ", " adresse ", " wo sind ",
            " wie komme ", " empfehlen ", " empfehlung ", " kinder ", " familie ",
            " wein ", " frühstücken ", " buchung ",
            " stornier ", " stornierung ", " zimmer ", " bett ",
            " badezimmer ", " klimaanlage ", " fernseher ", " parken ",
            " haustier ", " hund ", " katze ", " haustiere ", " massagen ",
            " wellness ", " sauna ", " schwimmen ", " see ", " berg ", " schloss ",
            " das ", " sie ", " haben sie ", " ich hätte ", " können sie ",
            " möchten sie ", " buchen sie ", " gibt es ", " ist es ", " wo ist ",
            " wie viel ", " was kostet ", " prinzessin "
        ],
        "French": [
            " bonjour ", " bonsoir ", " merci beaucoup ", " s'il vous plaît ",
            " je voudrais ", " avez-vous ", " nous avons ", " les chambres ",
            " petit déjeuner ", " au revoir ", " bienvenue ", " c'est magnifique ",
            " je suis ", " vous êtes ", " réservation ", " chambre "
        ],
        "Italian": [
            " buongiorno ", " buonasera ", " grazie mille ", " per favore ",
            " vorrei ", " avete ", " prenotazione ", " colazione ", " ristorante ",
            " arrivederci ", " benvenuto ", " magnifico ", " bellissimo ", " camere ",
            " camera ", " alloggio ", " dove ", " dov'è ", " dov'è ", " dov è ",
            " quanto costa ", " che ora ", " ora ", " soggiorno ", " piacere ",
            " splendido ", " incantevole ", " meraviglioso ", " favoloso "
        ],
        "Spanish": [
            " buenos días ", " buenas tardes ", " muchas gracias ", " por favor ",
            " quisiera ", " tienen ", " habitaciones ", " desayuno ", " restaurante ",
            " bienvenido ", " hasta luego ", " magnífico ", " perfecto ", " reservación "
        ],
        "Slovenian": [
            " pozdravljeni ", " hvala lepo ", " prosim vas ", " kako ste ",
            " dober dan ", " lahko noč ", " nasvidenje ", " rezervacija ", " zajtrk ",
            " soba ", " sobe ", " apartma ", " kajenje ", " kaditi ", " dovoljeno ",
            " prepovedano ", " omogočeno ", " ali je ", " ali imate ", " kakšna ",
            " kakšne ", " kateri ", " katera ", " kje lahko ", " koliko stane ",
            " želim rezervirati ", " kje ste ", " lep dan ", " srčno pozdravljeni ",
            " lahko ", " pripeljem ", " psa ", " pes ", " psi ", " mačka ",
            " hvala ", " prosim ", " zdravo ", " pozdrav ", " dobrodošli ",
            " apartmaji ", " sobah ", " jezero ", " otok ", " razgled ",
        ],
    }

    scores = {}
    for lang, phrases in distinctive_phrases.items():
        score = sum(1 for p in phrases if p in msg)
        if score > 0:
            scores[lang] = score

    if scores:
        best_lang = max(scores, key=scores.get)
        if scores[best_lang] >= 1:
            return best_lang

    return "English"


def _detect_topic(message: str) -> str:
    """Detect the hotel info topic from a message (language-independent).
    Uses word-boundary matching to prevent false substrings like 'cat' in 'located'."""
    import re as _re
    import unicodedata as _ud
    # Normalize Unicode to NFC form so accented chars match consistently
    msg_raw = _ud.normalize("NFC", message.lower())
    # For word-boundary matching, create a padded version
    msg_word = " " + _re.sub(r'[!?,.;:()\[\]{}]', ' ', msg_raw) + " "
    msg_word = _re.sub(r'  +', ' ', msg_word)

    topic_keywords = {
        "rooms": ["room", "rooms", "suite", "suites", "bed", "sleep", "sobe", "soba", "zimmer", "zimmern", "camere", "camera", "chambre", "chambres", "habitaci", "cuarto", "apartma", "apartmaj", "sobah", "habitacion", "dormitorio", "zimmer frei", "camere disponibili", "chambres disponibles", "habitaciones disponibles", "apartmaji", "sobe prosta"],
        "restaurant": ["restaurant", "dining", "dinner", "lunch", "menu", "chef", "domen", "dem\u0161ar", "demar", "pop up", "pop-up", "terrace dining", "food", "eat", "meal", "restavracija", "ristorante", "restaurante", "speise", "essen", "ku00fcche", "cucina", "manger", "nourriture", "comida", "comer", "alimento", "ve\u010derja", "ve\u010derjo", "ve\u010deri", "kosilo", "kosilom", "obed", "obrom", "jedilnik", "jedilnika", "kuhar", "kuhinja", "terasa", "ve\u010dera", "ve\u010deru", "ru\u010dak", "ru\u010dka", "ru\u010dkom", "ve\u010derala", "ve\u010derati", "jela", "jelo", "hrana"],
        "bar": ["bar", "cocktail", "drink", "aperitivo", "aperitiv", "pijau010da", "getru00e4nk", "bevanda", "boisson"],
        "wine": ["wine", "wines", "vineyard", "sommelier", "wine pairing", "vino", "vin", "vins", "wein", "vina"],
        "breakfast": ["breakfast", "morning meal", "brunch", "zajtrk", "frühstück", "colazione", "petit déjeuner", "desayuno", "vegan", "vegetarian", "gluten", "allergy", "allergies", "dietary", "diet", "restriction", "celiac", "lactose", "intolerant", "vegansko", "vegetarijansko", "brezglutensko", "alergija", "prehrana", "koliko stane", "kako much", "how much is breakfast", "how much does breakfast", "déjeuner", "frühstück buffet", "colazione inclusa", "desayuno incluido", "végétalien", "végétarien", "sans gluten", "opciones veganas", "opciones vegetarianas", "opciones sin gluten", "vegane", "vegetarische", "glutenfreie", "vegane opcije", "vegetarijanske opcije", "bez glutena", "végétaliennes", "végétariennes", "opzione vegane"],
        "parking": ["parking", "park", "car", "parkplatz", "parkplätze", "parcheggio", "aparcamiento", "stationnement", "parken", "parkiranje", "avto", "auto", "wagen", "voiture", "coche", "macchina", "estacionamiento", "carro", "parking privé", "parkplatzfrage"],
        "pets": ["pet", "pets", "dog", "dogs", "cat", "cats", "animal", "pes", "psa", "ma\u010dka", "macka", "hund", "katze", "cane", "gatto", "chien", "chat", "perro", "gato", "mascot"],
        "location": ["location", "address", "where", "direction", "directions", "map", "located", "find you", "find the", "how do i get", "how to get", "how far", "distance", "walk", "drive", "minutes away", "minutes walk", "minutes drive", "close", "how close", "lokacija", "naslov", "kje", "standort", "adresse", "dove", "ou00f9", "du00f3nde", "donde", "ubicaci", "ubicacion", "direccion"],
        "experiences": ["experience", "activity", "activities", "thing to do", "things to do", "what to do", "what can i do", "what should i do", "attraction", "sight", "visit", "tour", "hike", "swim", "massage", "spa", "nearby", "near", "aktivnost", "attività", "activité", "actividad", "hacer", "qué hacer", "noches", "noč", "večer", "nacht", "soirée", "soir", "noche", "sera", "bicycle", "bike", "bikes", "cycling", "rental", "kolo", "kolesa", "kolesarjenje", "izposoja", "velo", "vélo", "bicicletta", "bicicleta"],
        "late_check_in": ["late check in", "late checkin", "late arrival", "arrive late", "late check-in", "pozen prihod", "spu00e4t ankommen", "arrivo tardif", "arrivu00e9e tardive"],
        "late_check_out": ["late check out", "late checkout", "late departure", "leave late", "late check-out", "pozen odhod", "spu00e4t abreise", "partenza tardif", "du00e9part tardif"],
        "check_in": ["check in", "checkin", "arrival", "arrive", "check-in", "prihod", "ankunft", "anreise", "arrivo", "arrivée", "llegada", "prijava", "prijave", "che ora", "wann ist", "enregistrement", "réception", "check-in horaires", "heures d'arrivée", "ora di arrivo", "ankunftszeit"],
        "check_out": ["check out", "checkout", "departure", "depart", "check-out", "odhod", "abreise", "partenza", "départ", "salida", "enregistrement", "réception", "heures de départ", "ora di partenza", "abreisezeit"],
        "wifi": ["wifi", "wi-fi", "internet", "wireless", "wlan"],
        "contact": ["contact", "phone", "email", "call", "reach", "kontakt", "telefon", "rufen", "chiamare", "appeler", "llamar"],
        "policies": ["policy", "rule", "regulation", "pravilo", "regel", "ru00e8gle", "regla"],
        "cancellation": ["cancel", "refund", "cancellation", "stornir", "storno", "annulation", "annullamento", "annulaci"],
        "children": ["child", "kid", "kids", "baby", "babies", "crib", "cribs", "extra bed", "extra beds", "family", "families", "toddler", "otrok", "kind", "bambino", "enfant", "niño", "družina", "familie", "gruppe", "grupo", "famille", "famiglia", "gruppe"],
        "room_service": ["room_service", "room service", "in-room dining", "food to room", "order food", "food to my room", "dining in my room", "meal to room", "bring food to room"],
        "shuttle": ["shuttle", "transfer", "airport", "transport", "prevoz", "navette", "transporte"],
        "gym": ["gym", "fitness", "workout", "exercise", "treadmill", "weights"],
        "smoking": ["smoke", "smoking", "cigarette", "cigar", "tobacco"],
        "spa": ["spa", "wellness", "sauna", "massage"],
        "history": ["history", "heritage", "built", "vila istra", "vila", "1878", "aristocracy", "austro-hungarian", "zgodovina", "dediščina", "zgradba", "zgodovinska", "geschichte", "historie", "histoire", "storia", "historia", "povijest", "povijesna"],
        "weather": ["weather", "forecast", "temperature", "rain", "sunny", "snow", "climate", "vreme", "temperatura"],
        "booking": ["book", "reserve", "reservation", "rezervir", "buchen", "prenotare", "réserver", "reservar"],
        "wedding": ["wedding", "marriage", "married", "bride", "groom", "poroka", "poročni", "hochzeits", "mariage", "matrimonio", "boda", "vjenčanje"],
        "gift_vouchers": ["gift voucher", "gift vouchers", "voucher", "vouchers", "gift card", "gift certificate", "darilni bon", "darilni boni", "gutschein", "buono regalo", "bon cadeau"],
        "summer": ["summer", "summer 2026", "july", "august", "june", "september", "package", "packages", "romance package", "wellness retreat", "adventure package", "family getaway", "culinary experience", "event", "events", "festival", "concert", "poletje", "poletno", "julij", "avgust", "junij", "september", "paket", "paketi", "dogodek", "dogodki", "festival", "sommer", "juli", "august", "juni", "paket", "veranstaltung", "veranstaltungen", "festival", "été", "juillet", "août", "juin", "forfait", "forfaits", "événement", "festival", "estate", "luglio", "agosto", "giugno", "pacchetto", "pacchetti", "evento", "festival"],
    }

    def _matches(text, keywords):
        """Check if any keyword matches as a whole word/phrase in text."""
        for kw in keywords:
            # Normalize keyword to NFC for consistent matching
            kw = _ud.normalize("NFC", kw)
            # Use word boundary for short keywords (<=4 chars) to avoid false matches
            if len(kw) <= 4:
                pattern = r'\b' + _re.escape(kw) + r'\b'
                if _re.search(pattern, text):
                    return True
            else:
                # For longer keywords, substring match (also try hyphen↔space swap)
                if kw in text:
                    return True
                if " " in kw and kw.replace(" ", "-") in text:
                    return True
                if "-" in kw and kw.replace("-", " ") in text:
                    return True
        return False

    # Priority: smoking questions should override "room" keyword
    if _matches(msg_raw, ["smoke", "smoking", "cigarette", "cigar", "tobacco", "kajenje", "kaditi", "rauchen", "zigarette", "cigaretta", "cigare", "cigarrillo"]):
        return "smoking"
    # Priority: Villa Pomona queries should be detected before generic keyword matching
    if _matches(msg_raw, ["villa pomona", "pomona", "villa pomona"]):
        return "villa_pomona"
    # Priority: late check-in/out should override "night"/"evening" experiences keywords
    if _matches(msg_raw, ["late check in", "late checkin", "late arrival", "arrive late", "late check-in",
                           "late check out", "late checkout", "late departure", "leave late", "late check-out",
                           "check in late", "check out late",
                           "pozen prihod", "pozen odhod", "spät ankommen", "spät abreise",
                           "arrivo tardif", "partenza tardif", "arrivée tardive", "départ tardif"]):
        # Determine if it's check-in or check-out
        if _matches(msg_raw, ["late check out", "late checkout", "late departure", "leave late", "late check-out",
                              "check out late",
                              "pozen odhod", "spät abreise", "partenza tardif", "départ tardif"]):
            return "late_check_out"
        return "late_check_in"
    # Priority: family/children questions should override "room" keyword
    if _matches(msg_raw, [
        "family rooms", "family room", "family suite", "family-friendly", "family friendly",
        "children room", "kids room", "room for kids", "room for children",
        "crib", "cribs", "extra bed", "extra beds", "baby bed", "baby beds",
        "družinski", "otroški", "familienzimmer", "kind", "chambre enfant",
        "camera per bambini", "camera per bambino", "chambre d'enfant"
    ]):
        return "children"
    # Priority: spa/wellness specific queries should map directly
    if _matches(msg_raw, ["spa", "wellness", "sauna", "massage", "wellness area", "wellness center", "wellness centre", "savna", "masaža", "massage", "sauna", "wellness"]):
        return "spa"
    # Priority: booking intent should override rooms when both keywords present
    # Priority: room_service keywords should override "rooms" when food-related terms present
    if _matches(msg_raw, ["order food", "food to room", "food to my room", "dining in my room", "meal to room", "bring food to room", "in-room dining", "room service", "room_service", "food delivered", "deliver food", "food delivery", "send food", "bring me food", "food in my room", "eat in my room", "dine in my room"]):
        return "room_service"
    if _matches(msg_raw, ["book", "reserve", "rezervir", "buchen", "prenotare", "réserver", "reservar"]) and _matches(msg_raw, ["room", "suite", "zimmer", "camera", "chambre", "habitaci", "sobe", "soba"]):
        return "booking"
    # Priority: "get to [place]" / "how do i get to" should map to location/directions
    # BUT if "airport" is mentioned, map to shuttle instead
    if _matches(msg_raw, ["get to", "how do i get", "how to get", "directions to", "way to", "reach the", "reach bled"]):
        if _matches(msg_raw, ["airport", "ljubljana", "brnik", "transfer"]):
            return "shuttle"
        return "location"
    # Priority: breakfast questions about inclusion/pricing should not be captured by "room" keyword
    if _matches(msg_raw, ["breakfast included", "breakfast included in", "is breakfast included", "does breakfast include", "zajtrk vključen", "frühstück inklusive", "petit déjeuner inclus", "colazione inclusa", "desayuno incluido"]) and not _matches(msg_raw, ["book", "reserve", "rezervir", "buchen", "prenotare"]):
        return "breakfast"
    for topic, keywords in topic_keywords.items():
        if _matches(msg_word, keywords):
            return topic
    return "general"


def apply_rag_to_messages(messages: list[dict], user_query: str) -> list[dict]:
    if not user_query.strip():
        return messages
    context_docs = maybe_retrieve_hotel_facts(user_query)
    if not context_docs:
        return messages
    rag_msg = {
        "role": "system",
        "content": f"HOTEL_KNOWLEDGE_BLOCK:\n\n{format_rag_context(context_docs)}\n\nUse only the facts above when answering.",
    }
    last_user_idx = None
    for idx in range(len(messages) - 1, -1, -1):
        if messages[idx].get("role") == "user":
            last_user_idx = idx
            break
    if last_user_idx is None:
        return messages + [rag_msg]
    return messages[:last_user_idx] + [rag_msg] + messages[last_user_idx:]


def get_hotel_info_response(topic, question):
    import unicodedata as _ud
    h = hotel_info
    q = _ud.normalize("NFC", question.lower())

    # Map common synonyms to topics
    topic_aliases = {
        "check_in": ["check in", "checkin", "arrival", "arrive", "check-in", "late check in", "late arrival"],
        "check_out": ["check out", "checkout", "departure", "depart", "check-out", "late check out", "late departure"],
        "rooms": ["room", "suite", "bed", "accommodation", "stay", "sleep"],
        "policies": ["policy", "rule", "regulation"],
        "amenities": ["amenity", "facility", "feature", "service", "perk"],
        "location": ["location", "address", "where", "direction", "map", "find", "located"],
        "experiences": ["experience", "activity", "thing to do", "attraction", "sight", "visit", "tour", "hike", "swim", "activities", "nearby", "around", "do here", "what to", "bicycle", "bike", "bikes", "cycling", "rental", "kolo", "kolesa", "kolesarjenje", "izposoja", "velo", "vélo", "bicicletta", "bicicleta"],
        "breakfast": ["breakfast", "morning meal", "brunch"],
        "restaurant": ["restaurant", "dining", "dinner", "lunch", "menu", "chef", "domen", "demšar", "demar", "pop up", "pop-up", "terrace dining", "food", "eat", "meal"],
        "wine": ["wine", "wines", "wine list", "wine pairing", "sommelier", "vineyard", "cellar"],
        "bar": ["bar", "cocktail", "cocktails", "aperitivo", "drinks", "mixologist"],
        "parking": ["parking", "park", "car"],
        "wifi": ["wifi", "wi-fi", "internet", "wireless"],
        "pets": ["pet", "dog", "cat", "animal"],
        "cancellation": ["cancel", "refund", "cancellation"],
        "payment": ["payment", "pay", "card", "visa", "mastercard", "cash"],
        "children": ["child", "kid", "baby", "family", "toddler"],
        "smoking": ["smoke", "smoking", "cigarette"],
        "spa": ["spa", "wellness", "sauna", "massage"],
        "late_check_in": ["late check in", "late checkin", "late arrival", "arrive late", "after hours check in", "night check in"],
        "late_check_out": ["late check out", "late checkout", "late departure", "leave late", "after hours check out"],
        "contact": ["contact", "phone", "email", "call", "reach"],
        "room_service": ["room service", "in-room dining", "food to room"],
        "shuttle": ["shuttle", "transfer", "airport"],
        "gym": ["gym", "fitness", "workout", "exercise"],
        "general": ["general", "info", "information", "about", "tell me"],
        "gift_vouchers": ["gift voucher", "gift card", "gift certificate", "voucher", "vouchers", "darilni bon"],
    }

    # Detect actual topic from question if topic is generic
    actual_topic = topic
    if topic in ("general", "policies"):
        # Check cancellation first (before policies) since "cancellation policy" contains both keywords
        if any(a in q for a in ["cancel", "refund", "cancellation", "stornir", "storno", "annulation", "annullamento", "annulaci"]):
            actual_topic = "cancellation"
        else:
            for t, aliases in topic_aliases.items():
                if any(a in q for a in aliases):
                    actual_topic = t
                    break

    # Override: dietary questions should go to breakfast/dining, unless specifically about restaurant/dinner
    if actual_topic not in ("breakfast",) and any(word in q for word in ["vegan", "vegetarian", "gluten", "allergy", "allergies", "dietary", "diet", "restriction", "celiac", "lactose", "intolerant", "végétalien", "végétarien", "sans gluten", "opciones veganas", "opciones vegetarianas", "opciones sin gluten", "vegane", "vegetarische", "glutenfreie", "vegane opcije", "vegetarijanske opcije", "bez glutena", "végétaliennes", "végétariennes", "opzione vegane"]):
        # If query is specifically about restaurant dining, keep restaurant topic
        if any(word in q for word in ["dinner", "lunch", "restaurant", "eat", "meal", "food", "menu", "chef", "dining"]):
            actual_topic = "restaurant"
        elif any(word in q for word in ["accommodate", "can you", "can i", "do you", "options", "serve", "provide"]):
            # General dietary accommodation questions — route to restaurant for richer response
            actual_topic = "restaurant"
        else:
            actual_topic = "breakfast"

    # Check-in / Check-out
    if actual_topic in ("check_in", "check_out"):
        # Check if guest mentioned a specific time
        extracted_time = extract_time_from_message(question)
        if extracted_time:
            if actual_topic == "check_out" or "depart" in q or "check out" in q or "checkout" in q or "leave" in q:
                return (
                    f"Thank you! I've noted your late check-out request for {extracted_time}. "
                    f"Our standard check-out is {h['policies']['check_out']}, and we'll do our best to accommodate your request. "
                    f"Our reception team will confirm availability. Is there anything else I can help you with?"
                )
            else:
                return (
                    f"Thank you! I've noted your late check-in request for {extracted_time}. "
                    f"Our standard check-in is {h['policies']['check_in']}, and we'll make sure everything is ready for your arrival. "
                    f"Is there anything else I can help you with?"
                )
        if any(word in q for word in ["late", "later", "after", "early", "before", "outside"]):
            if actual_topic == "check_out" or "depart" in q or "check out" in q or "checkout" in q or "leave" in q:
                return (
                    f"Our standard check-out is {h['policies']['check_out']}, but late check-out is available on request! "
                    f"It's subject to availability and additional fees may apply. Contact reception to arrange. "
                    f"What time would you like to check out?"
                )
            else:
                return (
                    f"Our standard check-in is {h['policies']['check_in']}, but late check-in is available on request! "
                    f"Just contact our reception to arrange. We can accommodate late arrivals with advance notice. "
                    f"What time were you planning to arrive?"
                )
        return (
            f"Check-in is from {h['policies']['check_in']}, and check-out is by {h['policies']['check_out']}. "
            f"Please bring a photo ID and credit card for check-in. "
            f"Late check-in or check-out can also be arranged on request — just let us know your plans! "
            f"Would you like help with a reservation?"
        )

    # Late check-in / check-out specific
    if actual_topic in ("late_check_in", "late_check_out"):
        if actual_topic == "late_check_in":
            return (
                f"Late check-in is absolutely possible! Our standard window is {h['policies']['check_in']}, "
                f"but we can accommodate late arrivals on request. Just contact our reception in advance "
                f"and we'll make sure everything is ready for you. What time were you planning to arrive?"
            )
        else:
            return (
                f"Late check-out is available on request, subject to availability. Additional fees may apply. "
                f"Our standard check-out is {h['policies']['check_out']}. "
                f"What time would you like?"
            )

    # Rooms
    if actual_topic == "rooms":
        # Check if asking about pricing
        is_price_query = any(word in q for word in ["price", "cost", "how much", "rate", "pricing", "expensive", "cheap", "cena", "preis", "prix", "precio", "prezzo", "koliko stane", "wie viel kostet", "combien coûte", "quanto costa", "cuánto cuesta", "koliko košta"])
        # Check if asking about capacity/groups
        is_capacity_query = any(word in q for word in ["people", "person", "group", "family", "children", "kids", "sleeps", "capacity", "many", "3", "4", "5", "6", "oseb", "oseba", "osebi", "osebo", "skupina", "družina", "otroci", "leži", "kapacita", "gostje", "gostov", "personen", "person", "gruppe", "familie", "kinder", "schläft", "personas", "persona", "grupo", "familia", "niños", "capacidad", "personnes", "groupe", "famille", "enfants", "capacité", "persone", "gruppo", "famiglia", "bambini", "capacità"])
        # Check if asking about a specific room
        # FIXED: Match on distinctive room name words, not "suite" which is in every room name
        best_match = None
        best_score = 0
        for room in h["rooms"].values():
            room_name_lower = room["name"].lower()
            # Full name match gets highest priority
            if room_name_lower in q:
                best_match = room
                best_score = 100
                break
            # Match on distinctive words (not "suite" which is shared by all)
            distinctive_words = [w for w in room_name_lower.split() if len(w) > 3 and w != "suite"]
            score = sum(2 for w in distinctive_words if w in q)
            # Fuzzy: also match if query word starts with distinctive word (e.g., "princesin" starts with "princes")
            if score == 0:
                for w in distinctive_words:
                    for qw in q.split():
                        if len(qw) > 5 and qw.startswith(w):
                            score = 1
                            break
                    if score > 0:
                        break
            if score > best_score:
                best_score = score
                best_match = room
        if best_match and best_score > 0:
            room = best_match
            features = ", ".join(room.get("features", [])[:3])
            price_str = ""
            if is_price_query and room.get("price"):
                price_str = f" — €{room['price']}/night"
            desc = room.get("description", "")
            # If no price, use em-dash separator; if price, price_str already has the dash
            if price_str:
                return (
                    f"{room['name']}{price_str}. {desc} "
                    f"Features: {features}. "
                    f"Would you like to book this suite or see other options?"
                )
            return (
                f"{room['name']} — {desc} "
                f"Features: {features}. "
                f"Would you like to book this suite or see other options?"
            )
        # Check if asking about capacity - highlight suitable rooms
        if is_capacity_query:
            # Extract number of people
            num_people = None
            for num_word, num_val in [("1", 1), ("2", 2), ("3", 3), ("4", 4), ("5", 5), ("6", 6),
                                       ("one", 1), ("two", 2), ("three", 3), ("four", 4), ("five", 5), ("six", 6),
                                       ("ena", 1), ("dve", 2), ("tri", 3), ("štiri", 4), ("pet", 5), ("šest", 6),
                                       ("ein", 1), ("eine", 1), ("zwei", 2), ("drei", 3), ("vier", 4), ("fünf", 5), ("sechs", 6),
                                       ("uno", 1), ("una", 1), ("due", 2), ("tre", 3), ("quattro", 4), ("cinque", 5), ("sei", 6),
                                       ("un", 1), ("une", 1), ("deux", 2), ("trois", 3), ("quatre", 4), ("cinq", 5), ("six", 6),
                                       ("uno", 1), ("una", 1), ("dos", 2), ("tres", 3), ("cuatro", 4), ("cinco", 5), ("seis", 6)]:
                if num_word + " " in q or " " + num_word + " " in q:
                    num_people = num_val
                    break
            # If no number found but family/children keywords present, default to 4
            if num_people is None and any(word in q for word in ["family", "children", "kids", "družina", "otroci", "kinder", "enfants", "bambini", "niños", "familie", "gruppe", "grupo", "famille", "famiglia", "gostje", "gostov"]):
                num_people = 4
            suitable = []
            all_rooms = []
            for r in h["rooms"].values():
                cap = r.get("capacity", 2)
                size = f", {r['size_sqm']} m²" if r.get("size_sqm") else ""
                price_str = f" — €{r['price']}/night" if r.get("price") and is_price_query else ""
                feat = ", ".join(r.get("features", [])[:2])
                line = f"• {r['name']}{size} (sleeps {cap}){price_str} — {feat}"
                all_rooms.append(line)
                if num_people and cap >= num_people:
                    suitable.append(line)
            if suitable and num_people:
                lines = [f"For {num_people} guest{'s' if num_people > 1 else ''}, I'd especially recommend:"]
                lines.extend(suitable)
                lines.append("Which one catches your eye? I can start a booking for you — just tell me your name and dates?")
                return "\n".join(lines)
            lines = ["We have 8 beautiful suites, all with stunning lake views:"]
            lines.extend(all_rooms)
            lines.append("Which one catches your eye? I can start a booking for you — just tell me your name and dates?")
            return "\n".join(lines)
        lines = ["We have 8 beautiful suites, all with stunning lake views:"]
        for r in h["rooms"].values():
            size = f", {r['size_sqm']} m²" if r.get("size_sqm") else ""
            cap = f", sleeps {r['capacity']}" if r.get("capacity") else ""
            price_str = f" — €{r['price']}/night" if r.get("price") and is_price_query else ""
            feat = ", ".join(r.get("features", [])[:2])
            lines.append(f"• {r['name']}{size}{cap}{price_str} — {feat}")
        lines.append("Which one catches your eye? I can start a booking for you — just tell me your name and dates?")
        return "\n".join(lines)

    # Policies
    if actual_topic == "policies":
        return (
            f"Check-in: {h['policies']['check_in']}. Check-out: {h['policies']['check_out']}. "
            f"Breakfast is €22 per person (not included in room rate). Free parking and WiFi. Pets allowed on request. "
            f"Is there a specific policy you'd like to know more about?"
        )

    # Gift vouchers
    if actual_topic == "gift_vouchers":
        return (
            "Yes — Villa Adora gift vouchers are available for stays, restaurant dining, and massage services. "
            "They are valid for 12 months from purchase and can be created in any amount, either as a digital voucher or printed certificate. "
            "Please email evita.vilebled@gmail.com with the desired amount, recipient name, and preferred delivery format. "
            "Would you like me to draft an email request for you?"
        )

    # Breakfast
    if actual_topic == "breakfast":
        b = h.get("dining", {}).get("breakfast", {})
        if isinstance(b, dict):
            dietary = b.get("dietary", {})
            if any(word in q for word in ["vegan", "vegetarian", "gluten", "allergy", "allergies", "dietary", "diet", "restriction", "végétalien", "végétarien", "sans gluten", "opciones veganas", "opciones vegetarianas", "opciones sin gluten", "vegane", "vegetarische", "glutenfreie", "bez glutena", "végétaliennes", "végétariennes", "opzione vegane"]):
                return (
                    f"We're happy to accommodate dietary needs! Breakfast (€22/person, served 8-10 AM) "
                    f"offers vegan, vegetarian, and gluten-free options on request. "
                    f"Our Adora Pop Up Restaurant also caters to dietary requirements — "
                    f"Chef Domen Demšar is known for creative accommodations. "
                    f"Just let us know your preferences when you book. "
                    f"Would you like to add breakfast or make a restaurant reservation?"
                )
            return (
                f"Breakfast is €22 per person, served daily 8-10 AM on our terrace with fresh pastries, bread, and local Slovenian products. "
                f"We also offer vegan, vegetarian, and gluten-free options on request. "
                f"Shall I add breakfast to your booking?"
            )
        return (
            f"{b} "
            f"Vegan, vegetarian, and gluten-free options are available on request. "
            f"Shall I add breakfast to your booking?"
        )

    # Restaurant
    if actual_topic == "restaurant":
        r = h.get("dining", {}).get("restaurant", {})
        # If asking about dietary needs, highlight Chef Demšar's accommodations
        if any(word in q for word in ["vegan", "vegetarian", "gluten", "allergy", "allergies", "dietary", "diet", "restriction", "celiac", "lactose", "intolerant", "végétalien", "végétarien", "sans gluten", "opciones veganas", "opciones vegetarianas", "opciones sin gluten", "vegane", "vegetarische", "glutenfreie", "bez glutena", "végétaliennes", "végétariennes", "opzione vegane"]):
            return (
                f"We have the {r.get('name', 'Adora Pop Up Restaurant')} right here at the hotel! "
                f"Chef Domen Demšar is known for accommodating dietary needs with creativity and care. "
                f"We offer vegan, vegetarian, and gluten-free options on request — just let us know your preferences when you reserve. "
                f"Hours: Lunch & Dinner {r.get('hours', {}).get('lunch', 'Tue-Sun')}, "
                f"Brunch {r.get('hours', {}).get('brunch', 'Thu-Sat')}. "
                f"Reservations: {r.get('phone', '+386 40 558 158')} or {r.get('email', 'evita.vilebled@gmail.com')}. "
                f"Would you like to make a reservation and note your dietary preferences?"
            )
        # If asking specifically about the chef, highlight Chef Domen Demšar
        if any(word in q for word in ["chef", "domen", "demšar", "demar", "kuhar", "küchenchef", "chef de cuisine", "cocinero", "cuoco"]):
            return (
                f"Our restaurant is led by renowned Chef Domen Demšar! "
                f"He's known for creative, locally inspired Slovenian dishes with French, Italian, and international influences, "
                f"using top-quality regional ingredients. He's also very accommodating with dietary needs and allergies. "
                f"Would you like to make a reservation to experience his cooking?"
            )
        return (
            f"We have the {r.get('name', 'Adora Pop Up Restaurant')} right here at the hotel! "
            f"{r.get('description', 'Creative Slovenian cuisine with stunning lake views.')} "
            f"Hours: Lunch & Dinner {r.get('hours', {}).get('lunch', 'Tue-Sun')}, "
            f"Brunch {r.get('hours', {}).get('brunch', 'Thu-Sat')}. "
            f"The terrace has arguably the best sunset views in Bled. "
            f"Reservations: {r.get('phone', '+386 40 558 158')} or {r.get('email', 'evita.vilebled@gmail.com')}. "
            f"Would you like to make a reservation?"
        )

    # Wine list
    if actual_topic == "wine":
        return (
            f"Our wine list is curated by an in-house wine expert, featuring the best Slovenian wines "
            f"from vineyards near Bled alongside selected international labels. "
            f"Wine pairing is available with our tasting menu (approximately €35/person). "
            f"The tasting menu itself is approximately €65/person. "
            f"For the full current wine list, I'd recommend contacting the restaurant directly at "
            f"+386 40 558 158. Would you like to reserve a table?"
        )

    # Bar
    if actual_topic == "bar":
        return (
            "Our bar serves elegant cocktails and aperitivos daily on the terrace — arguably the best sunset views over Lake Bled! "
            "It's a lovely place to unwind after a day exploring, and we also have a curated wine list if you'd prefer wine. "
            "Would you like to reserve a table on the terrace, or shall I help you with a restaurant reservation?"
        )

    # Parking
    if actual_topic == "parking":
        return (
            f"{h['policies']['parking']}. "
            f"Will you be driving to Bled, or would you like tips on public transport?"
        )

    # WiFi
    if actual_topic == "wifi":
        return (
            f"{h['policies']['wifi']}. "
            f"Anything else you'd like to know about our amenities?"
        )

    # Pets
    if actual_topic == "pets":
        return (
            f"{h['policies']['pets']}. "
            f"Are you planning to bring a furry friend along?"
        )

    # Cancellation
    if actual_topic == "cancellation":
        cancellation_text = h['policies']['cancellation'].rstrip('.')
        return (
            f"{cancellation_text}. "
            f"Would you like me to note any special conditions for your booking?"
        )

    # Payment
    if actual_topic == "payment":
        return (
            f"{h['policies']['payment']}. "
            f"Would you like to proceed with a booking?"
        )

    # Children
    if actual_topic == "children":
        return (
            f"Children of all ages are welcome! We are a family-friendly hotel. "
            f"The Island Suite and Superior Suite are perfect for families — both have 2 bedrooms and sleep 4 guests. "
            f"For activities, kids love rowing to Bled Island, swimming in the lake, "
            f"horse-drawn carriage rides, and the Vintgar Gorge walk. "
            f"Would you like me to help you find the best room or activities for your family?"
        )

    # Directions / Location details
    if actual_topic == "location":
        if any(word in q for word in ["castle", "bled castle"]):
            return (
                "Bled Castle is about a 30-minute walk from the hotel, or just 5 minutes by car. "
                "It's a medieval castle perched on a cliff with incredible views over the lake. "
                "I'd recommend visiting in the late afternoon for the best light. "
                "Shall I help you arrange transport or give you more tips for your visit?"
            )
        if any(word in q for word in ["vintgar", "gorge"]):
            return (
                "Vintgar Gorge is just 2.4 km from the hotel — about a 10-minute drive or a beautiful 30-minute walk. "
                "It's a stunning 1.6 km wooden walkway through a dramatic canyon. "
                "I'd recommend going early morning to avoid crowds. "
                "Would you like tips on getting there or combining it with other activities?"
            )
        if any(word in q for word in ["town center", "town centre", "city center", "city centre", "bled center", "bled centre", "center of bled"]):
            return (
                "Bled town center is a pleasant 15-minute walk from the hotel along the lakeside path. "
                "You'll find restaurants, cafés, the casino, and shops there. "
                "It's especially lovely in the evening! "
                "Would you like restaurant recommendations in town?"
            )
        if any(word in q for word in ["airport", "ljubljana airport"]):
            return (
                "Ljubljana Jože Pučnik Airport is about 35 km away — roughly a 30-minute drive. "
                "We can arrange airport shuttle transfer for approximately €60. "
                "Just let me know your flight details and I'll help book it for you!"
            )
        if any(word in q for word in ["bohinj", "lake bohinj"]):
            return (
                "Lake Bohinj is about a 30-minute drive from Bled — a beautiful day trip! "
                "It's Slovenia's largest permanent lake, surrounded by the Julian Alps. "
                "Highlights include Savica Waterfall, Vogel cable car, and swimming in crystal-clear water. "
                "Would you like help planning a day trip there?"
            )
        return (
            f"We're at {h['location']['address']}. "
            f"{h['location']['description']} "
            f"Phone: {h['location']['phone']}. "
            f"Would you like directions or tips on getting here?"
        )

    # Smoking
    if actual_topic == "smoking":
        return (
            "Villa Adora Bled is a non-smoking property — all rooms and indoor areas are smoke-free. "
            "However, guests may smoke on the outdoor terrace. "
            "Is there anything else I can help you with?"
        )

    # Spa / Wellness / Massage
    if actual_topic == "spa":
        return (
            "We offer in-room massage and wellness services — the perfect way to unwind after exploring Bled! "
            "Please give us 24 hours notice to arrange your treatment. "
            "Our sister property Villa Pomona also features a full wellness area with sauna. "
            "Would you like me to help you book a massage or learn more about our wellness options?"
        )

    # Swimming pool / spa queries - Villa Adora doesn't have a pool, but Villa Pomona does
    if any(word in q for word in ["swimming pool", "pool", "swim", "plavalni bazen", "badi", "schwimmbad", "natazione", "piscine", "pisina", "piscina"]):
        return (
            "Villa Adora Bled doesn't have a swimming pool, but guests can swim in the pristine Lake Bled right outside! "
            "We also have a sister property, Villa Pomona, which features a swimming pool, sauna, and full wellness facilities — perfect for a private retreat. "
            "Would you like more details about Villa Pomona, or shall I tell you about swimming in the lake?"
        )

    # Experiences
    if actual_topic == "experiences":
        # Check if specifically asking about massage/spa
        if any(word in q for word in ["massage", "spa", "wellness"]):
            return (
                "In-room massage is available and highly recommended! Please give us 24 hours notice to arrange. "
                "It's the perfect way to unwind after a day of exploring Bled. "
                "Would you like me to help you book a massage session?"
            )
        # Check if asking about bike/bicycle rental
        if any(word in q for word in ["bicycle", "bike", "bikes", "cycling", "kolo", "kolesa", "kolesarjenje", "izposoja", "velo", "vélo", "bicicletta", "bicicleta"]):
            return (
                "We offer bicycle rental — a wonderful way to explore the 6 km lakeside path and the surrounding area! "
                "Cycling around Lake Bled is one of the most popular activities. "
                "Would you like me to help arrange bike rental for your stay?"
            )
        if any(word in q for word in ["family", "families", "kid", "child", "children", "baby", "toddler"]):
            return (
                "Bled is wonderful for families! Here are some great options:\n"
                "• Row to Bled Island — kids love the traditional pletna boat ride\n"
                "• Swimming in the lake — safe, clean, and free!\n"
                "• Vintgar Gorge walk — an easy and spectacular nature walk\n"
                "• Horse-drawn carriage rides around Bled\n"
                "• Mini golf and cycling around the lake\n"
                "• Bled Castle — explorers of all ages will enjoy it\n"
                "The Island Suite and Superior Suite are perfect for families — both sleep 4 with 2 bedrooms! "
                "Which activity sounds most fun for your family?"
            )
        # Check if asking about evening/night activities
        if any(word in q for word in ["night", "evening", "nightlife", "after dark", "sunset", "noč", "večer", "nacht", "soirée", "soir", "noche", "sera", "večerja", "večerju"]):
            return (
                "Bled is magical in the evening! Here are some wonderful night-time options:\n"
                "• Sunset cocktails on our terrace — arguably the best sunset views in Bled\n"
                "• Dinner at the Adora Pop Up Restaurant (Tue-Sun) with terrace dining\n"
                "• Garden evenings with wine under the stars\n"
                "• In-room massage — the perfect way to unwind after a day of exploring\n"
                "• Stargazing from the garden or terrace — Bled has wonderfully clear skies\n"
                "• Room service dining in the comfort of your suite\n"
                "• Evening walk along the 6 km lakeside path — beautifully peaceful at night\n"
                "Would you like me to book a dinner reservation or arrange an in-room massage for you?"
            )
        return (
            f"There's so much to do around Bled! Here are some highlights:\n"
            f"• Row to Bled Island & visit the Church of the Assumption\n"
            f"• Swimming, paddleboarding, kayaking, and boat tours on the lake\n"
            f"• Vintgar Gorge walk (2.4 km away)\n"
            f"• Bled Castle visit (30 min walk)\n"
            f"• 6 km lakeside walking path & 15 signposted hikes\n"
            f"• Day trips to Lake Bohinj, Ljubljana, Postojna Cave\n"
            f"• In-room massage, garden evenings with wine\n"
            f"I can help you book any of these — just let me know which interests you. What sounds most appealing to you?"
        )

    # Contact
    if actual_topic == "contact":
        return (
            f"You can reach us at {h['location']['phone']} or {h['location']['email']}. "
            f"Or just keep chatting with me — I'm here to help! What else would you like to know?"
        )

    # Gym / Fitness
    if actual_topic == "gym":
        return (
            "Villa Adora Bled does not have an on-site gym, but our sister property Villa Pomona "
            "features a full wellness area with sauna. For active guests, Bled offers excellent "
            "outdoor fitness options — jogging around the lake, hiking trails, swimming, "
            "kayaking, and paddleboarding. "
            "Would you like me to suggest some great running routes or outdoor activities?"
        )

    # Amenities
    if actual_topic == "amenities":
        return (
            f"We offer: {', '.join(h['amenities'][:8])}. "
            f"Would you like the full list, or is there something specific you're looking for?"
        )

    # Room Service
    if actual_topic == "room_service":
        return (
            "Room service is available! You can order food and drinks to enjoy in the comfort of your suite. "
            "Our kitchen can accommodate dietary requirements — just let us know your preferences when you order. "
            "Would you like to know about our dining options or restaurant menu as well?"
        )

    # Shuttle / Airport Transfer
    if actual_topic == "shuttle":
        return (
            "We offer shuttle service for airport transfers, local transport, and custom routes! "
            "Popular routes: Ljubljana airport (~€60), Bled town center (~€15). "
            "To book, just tell me your name, pickup location, date, and time. "
            "Where would you like to be picked up?"
        )

    # Villa Pomona
    if "villa pomona" in q or "pomona" in q:
        vp = h.get("villa_pomona", {})
        acc = vp.get("accommodations", {})
        suites_count = acc.get("suites", 5)
        return (
            f"We also offer {vp.get('name', 'Villa Pomona')} — {vp.get('type', 'a luxury villa retreat')}. "
            f"Located on {vp.get('location', 'the most picturesque street in Bled')}. "
            f"It features {suites_count} distinctive suites with ensuite bathrooms, "
            f"a swimming pool, sauna, and botanical garden. "
            f"Perfect for families or groups seeking a private retreat. "
            f"Would you like more details or to make an inquiry?"
        )

    # Weather
    if actual_topic == "weather":
        return (
            "I don't have real-time weather data, but I'd recommend checking a weather app for the latest forecast! "
            "Bled has beautiful warm summers perfect for swimming and hiking, "
            "and magical snowy winters that transform the lake into a fairytale scene. "
            "What are you most interested in doing during your visit?"
        )

    # Booking intent
    if actual_topic == "booking":
        return (
            "I'd love to help you book a room! We have 8 beautiful suites with stunning lake views. "
            "To get started, I'll need your name, check-in and check-out dates, and your preferred room. "
            "Which suite catches your eye, or would you like me to help you choose?"
        )

    # Wedding / private events
    if actual_topic == "wedding":
        return (
            "Villa Adora is a beautiful setting for intimate weddings and private celebrations. "
            "For weddings or special events, our reception team can discuss available dates, options, "
            "and any extra services that may suit your plans. Would you like me to help start an inquiry?"
        )

    # Adversarial / off-topic queries about internal systems
    adversarial_keywords = ["database", "api", "sqlite", "flask", "server", "backend", "rag", "tool", "function", "schema", "parameter", "token", "model", "llm", "openai", "openrouter", "deploy", "docker", "kubernetes", "codebase", "source code", "repository", "github"]
    if any(word in q for word in adversarial_keywords):
        return (
            "I'm Luka, your concierge at Villa Adora Bled! "
            "I'm here to help you with everything about your stay — rooms, dining, activities, and more. "
            "What would you like to know about our hotel?"
        )

    # Fallback
    return (
        f"Villa Adora Bled is a heritage-protected villa from 1878, converted into a luxury design hotel "
        f"right on Lake Bled. We have 8 unique suites with panoramic lake views. "
        f"What would you like to know — rooms, booking, or things to do in Bled?"
    )


app = Flask(__name__)
sessions = {}

MAX_SESSIONS = 500

def _prune_sessions():
    """Prune oldest sessions when limit is reached to prevent memory leak."""
    global sessions
    if len(sessions) > MAX_SESSIONS:
        keys = list(sessions.keys())
        for key in keys[:len(keys) // 2]:
            sessions.pop(key, None)

_request_count = 0

@app.before_request
def _check_prune():
    global _request_count
    _request_count += 1
    if _request_count % 100 == 0:
        _prune_sessions()


@app.route("/")
def index():
    return render_template("index.html", hotel=hotel_info, hotel_name=hotel_info["name"])


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "villa-adora-bot",
        "version": "1.3.0",
        "active_sessions": len(sessions),
        "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z",
    })


@app.route("/api/chat/reset", methods=["POST"])
def api_chat_reset():
    data = request.json or {}
    session_id = data.get("session_id", "default")
    sessions.pop(session_id, None)
    return jsonify({"status": "ok", "message": "Session reset"})


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.json
    session_id = data.get("session_id", "default")
    user_message = data.get("message", "")
    if not user_message.strip():
        return jsonify({"replies": [{"type": "text", "content": "Hello! How can I help you today? Feel free to ask about our rooms, restaurant, activities, or anything else about Villa Adora Bled!"}]})
    if len(user_message) > 500:
        user_message = user_message[:500]
    if session_id not in sessions:
        sessions[session_id] = [{"role": "system", "content": str(build_system_prompt())}]
    messages = sessions[session_id]
    messages = apply_rag_to_messages(messages, user_message)
    sessions[session_id] = messages

    # Trim conversation to last 6 messages to reduce latency
    if len(messages) > 8:
        messages = [messages[0]] + messages[-6:]
        sessions[session_id] = messages

    messages.append({"role": "user", "content": user_message})

    # Detect language and prepare language-specific handling
    detected_lang = _detect_language(user_message)
    if _looks_like_english(user_message):
        detected_lang = "English"
    is_non_english = detected_lang != "English"

    try:
        lang_messages = list(messages)
        # Detect topic for potential direct response (both English and non-English)
        topic = _detect_topic(user_message) if is_non_english else _detect_topic(user_message)

        if is_non_english or detected_lang == "English":
            # For non-English messages, detect topic and fetch hotel data directly.
            # Check if we have a pre-translated response for rooms/experiences
            # Use direct response to bypass LLM and avoid timeout issues
            direct_response = None
            # Serbian uses Croatian responses (mutually intelligible)
            _lookup_lang = "Croatian" if detected_lang == "Serbian" else detected_lang
            # Check for price queries first — bypass pre-translated responses
            _q_lower = user_message.lower()
            _is_price = any(w in _q_lower for w in ["koliko stane", "wie viel kostet", "combien coûte", "quanto costa", "cuánto cuesta", "koliko košta", "price", "cost", "how much", "rate", "cena", "preis", "prix", "precio", "prezzo"])
            # Re-route dietary accommodation questions to restaurant for richer response
            _is_dietary_accommodate = topic == "breakfast" and any(w in _q_lower for w in ["vegan", "vegetarian", "gluten", "dietary", "allergy", "allergies", "restriction"]) and any(w in _q_lower for w in ["accommodate", "can you", "can i", "do you", "options", "serve", "provide", "nudite", "ponujete", "bietet", "können", "proposez", "offrite", "ofrecen", "pueden"])
            if _is_dietary_accommodate:
                topic = "restaurant"
            if topic == "rooms" and _lookup_lang in _ROOM_LISTINGS_TRANSLATED and not _is_price:
                direct_response = _ROOM_LISTINGS_TRANSLATED[_lookup_lang]
            elif topic in ("experiences", "activities") and _lookup_lang in _EXPERIENCES_TRANSLATED:
                direct_response = _EXPERIENCES_TRANSLATED[_lookup_lang]
            elif topic == "pets" and _lookup_lang in _PETS_TRANSLATED:
                direct_response = _PETS_TRANSLATED[_lookup_lang]
            elif topic == "restaurant" and _lookup_lang in _RESTAURANT_TRANSLATED:
                direct_response = _RESTAURANT_TRANSLATED[_lookup_lang]
            elif topic == "location" and _lookup_lang in _LOCATION_TRANSLATED:
                direct_response = _LOCATION_TRANSLATED[_lookup_lang]
            elif topic == "breakfast" and _lookup_lang in _BREAKFAST_TRANSLATED:
                direct_response = _BREAKFAST_TRANSLATED[_lookup_lang]
            elif topic in ("check_in", "check_out", "late_check_in", "late_check_out") and _lookup_lang in _CHECKIN_TRANSLATED:
                direct_response = _CHECKIN_TRANSLATED[_lookup_lang]
            elif topic == "wine" and _lookup_lang in _WINE_TRANSLATED:
                direct_response = _WINE_TRANSLATED[_lookup_lang]
            elif topic == "bar" and _lookup_lang in _BAR_TRANSLATED:
                direct_response = _BAR_TRANSLATED[_lookup_lang]
            elif topic == "parking" and _lookup_lang in _PARKING_TRANSLATED:
                direct_response = _PARKING_TRANSLATED[_lookup_lang]
            elif topic == "shuttle" and _lookup_lang in _SHUTTLE_TRANSLATED:
                direct_response = _SHUTTLE_TRANSLATED[_lookup_lang]
            # Smoking policy - non-English direct responses
            elif topic == "smoking":
                smoking_responses = {
                    "Slovenian": "Villa Adora Bled je hotel brez kajenja — vse sobe in notranji prostori so brez dima. Goste lahko kadijo na zunajšnji terasi. Vas še kaj zanima?",
                    "German": "Villa Adora Bled ist ein rauchfreies Hotel — alle Zimmer und Innenräuche sind rauchfrei. Gäste dürfen jedoch auf der Außenterrasse rauchen. Kann ich Ihnen noch mit etwas helfen?",
                    "French": "Villa Adora Bled est un hôtel non-fumeur — toutes les chambres et espaces intérieurs sont sans fumée. Cependant, les fumeurs peuvent utiliser la terrasse extérieure. Y a-t-il autre chose que je puisse faire pour vous ?",
                    "Italian": "Villa Adora Bled è un hotel per non fumatori — tutte le camere e gli spazi interni sono senza fumo. Tuttavia, i fumatori possono utilizzare la terrazza esterna. C'è altro con cui posso aiutarti?",
                    "Spanish": "Villa Adora Bled es un hotel para no fumadores — todas las habitaciones y espacios interiores son libres de humo. Sin embargo, los fumadores pueden usar la terraza exterior. ¿Hay algo más en lo que pueda ayudarte?",
                    "Croatian": "Villa Adora Bled je hotel za nepušače — sve sobe i unutarnji prostori su bez dima. Međutim, pušači mogu koristiti vanjsku terasu. Mogu li vam još nekako pomoći?",
                    "Serbian": "Villa Adora Bled je hotel za nepušače — sve sobe i unutarnji prostori su bez dima. Međutim, pušači mogu koristiti vanjsku terasu. Mogu li vam još nekako pomoći?",
                }
                direct_response = smoking_responses.get(_lookup_lang)
            # WiFi - non-English direct responses
            elif topic == "wifi":
                wifi_responses = {
                    "Slovenian": "Brezžični internet (WiFi) je brezplen po celotnem hotelu. Vas še kaj zanima?",
                    "German": "Kostenloses Highspeed-WLAN im gesamten Hotel. Gibt es noch etwas, womit ich Ihnen helfen kann?",
                    "French": "WiFi haut débit gratuit dans tout l'hôtel. Y a-t-il autre chose que je puisse faire pour vous ?",
                    "Italian": "WiFi gratuito ad alta velocità in tutto l'hotel. C'è altro con cui posso aiutarti?",
                    "Spanish": "WiFi gratuito de alta velocidad en todo el hotel. ¿Hay algo más en lo que pueda ayudarte?",
                    "Croatian": "Besplatni brzi WiFi u cijelom hotelu. Mogu li vam još nekako pomoći?",
                    "Serbian": "Besplatni brzi WiFi u celom hotelu. Mogu li vam još nekako pomoći?",
                }
                direct_response = wifi_responses.get(_lookup_lang)
            # Contact - non-English direct responses
            elif topic == "contact":
                contact_responses = {
                    "Slovenian": "Kontaktirate nas lahko na +386 51 603 858 ali evita.vilebled@gmail.com. Ali pa kar nadaljujete pogovor z mano — tukaj sem, da vam pomagam! Vas še kaj zanima?",
                    "German": "Sie uns unter +386 51 603 858 oder evita.vilebled@gmail.com erreichen. Oder chatten Sie einfach weiter mit mir — ich bin hier, um zu helfen! Gibt es noch etwas, womit ich Ihnen helfen kann?",
                    "French": "Vous pouvez nous joindre au +386 51 603 858 ou evita.vilebled@gmail.com. Ou continuez simplement à discuter avec moi — je suis là pour vous aider ! Y a-t-il autre chose ?",
                    "Italian": "Puoi contattarci al +386 51 603 858 o evita.vilebled@gmail.com. O continua semplicemente a chattare con me — sono qui per aiutarti! C'è altro che vorresti sapere?",
                    "Spanish": "Puede contactarnos al +386 51 603 858 o evita.vilebled@gmail.com. O simplemente siga chateando conmigo — ¡estoy aquí para ayudar! ¿Hay algo más que le gustaría saber?",
                    "Croatian": "Možete nas kontaktirati na +386 51 603 858 ili evita.vilebled@gmail.com. Ili nastavite razgovor sa mnom — tu sam da vam pomognem! Ima li još nečega što biste željeli znati?",
                    "Serbian": "Možete nas kontaktirati na +386 51 603 858 ili evita.vilebled@gmail.com. Ili nastavite razgovor sa mnom — tu sam da vam pomognem! Ima li još nečega što biste željeli znati?",
                }
                direct_response = contact_responses.get(_lookup_lang)
            # Spa/Wellness - non-English direct responses
            elif topic == "spa" and _lookup_lang in _WELLNESS_TRANSLATED:
                direct_response = _WELLNESS_TRANSLATED[_lookup_lang]
            # Children/Family - non-English direct responses
            elif topic == "children" and _lookup_lang in _CHILDREN_TRANSLATED:
                direct_response = _CHILDREN_TRANSLATED[_lookup_lang]
            # Wedding - non-English direct responses
            elif topic == "wedding" and _lookup_lang in _WEDDING_TRANSLATED:
                direct_response = _WEDDING_TRANSLATED[_lookup_lang]
            # Swimming pool queries - Villa Adora doesn't have one, but Villa Pomona does
            elif any(word in user_message.lower() for word in ["swimming pool", "pool", "plavalni bazen", "bazen", "badi", "schwimmbad", "natazione", "piscine", "pisina", "piscina", "bazenu", "bazena"]):
                pool_responses = {
                    "Slovenian": "Villa Adora Bled nima bazena, a lahko gostje uživajo v čistem jezeru Bled tukaj ob hotelu! Naša sestra lastnost Villa Pomona pa ponuja bazen, savno in wellness — popolno za zasebni oddih. Želite več informacij o Villi Pomoni?",
                    "German": "Villa Adora Bled hat kein Schwimmbad, aber Gäste können direkt vor Ort in den kristallklaren Bleder See springen! Unsere Schwesteranlage Villa Pomona bietet Pool, Sauna und Wellness — perfekt für einen privaten Rückzug. Möchten Sie mehr über Villa Pomona erfahren?",
                    "French": "Villa Adora Bled n'a pas de piscine, mais les invités peuvent profiter du lac Bled cristallin juste à côté ! Notre propriété sœur Villa Pomona propose piscine, sauna et wellness — idéal pour une retraite privée. Souhaitez-vous plus d'informations sur Villa Pomona ?",
                    "Italian": "Villa Adora Bled non ha una piscina, ma gli ospiti possono godersi il cristallino lago Bled proprio qui! La nostra proprietà sorella Villa Pomona offre piscina, sauna e wellness — perfetta per un ritiro privato. Vuoi maggiori informazioni su Villa Pomona?",
                    "Spanish": "Villa Adora Bled no tiene piscina, ¡pero los huéspedes pueden disfrutar del cristalino lago Bled aquí mismo! Nuestra propiedad hermana Villa Pomona ofrece piscina, sauna y wellness — ideal para un retiro privado. ¿Desea más información sobre Villa Pomona?",
                    "Croatian": "Villa Adora Bled nema bazen, ali gosti mogu uživati u kristalno čistom jezeru Bled tukaj! Naša sestrina nekretnina Villa Pomona nudi bazen, saunu i wellness — savršeno za privatni odmor. Želite li više informacija o Villi Pomoni?",
                    "Serbian": "Villa Adora Bled nema bazen, ali gosti mogu uživati u kristalno čistom jezeru Bled tukaj! Naša sestrina nekretnina Villa Pomona nudi bazen, saunu i wellness — savršeno za privatni odmor. Želite li više informacija o Villi Pomoni?",
                }
                direct_response = pool_responses.get(_lookup_lang, pool_responses["Slovenian"])
            # Summer 2026 packages and events
            elif topic == "summer":
                summer_responses = {
                    "Slovenian": (
                        "Poleti 2026 v Villi Adora bomo ponudili več posebnih paketov in dogodkov:\n\n"
                        "🏖️ **Posebni paketi:**\n"
                        "• Romanski paket — 2 nočitvi v Princess/Penthouse suiti, šampanjec, masaža za par, večerja na terasi (od €950)\n"
                        "• Wellness umik — 3 nočitve, dnevna joga, 2 masaži, zajtrk (od €1.200)\n"
                        "• Pustolovski paket — Vintgar, kajak, kolesa, kosilo (od €850)\n"
                        "• Družinski paket — Superior/Island suite, kolesa, piknik (od €1.100)\n"
                        "• Kulinarno doživetje — degustacijski meni z vinom, kuharski tečaj (od €1.050)\n\n"
                        "🎵 **Poletni dogodki v Bledu:**\n"
                        "• Blejski festival (julij) — klasična glasba na Blejskem gradu\n"
                        "• Okarina World Music Festival (julij–avgust)\n"
                        "• Blejski dnevi (avgust)\n"
                        "• Bled International Rowing Regatta\n\n"
                        "🌅 Vsak večer na naši terasi: Sunset Aperitivo z rahledom na jezero!\n"
                        "Ōelite več informacij o katerem koli paketu? Z veseljem vam pomagam rezervirati!"
                    ),
                    "German": (
                        "Sommer 2026 in Villa Adora — besondere Pakete und Events:\n\n"
                        "🏖️ **Sommer-Pakete:**\n"
                        "• Romantik-Paket — 2 Nächte Princess/Penthouse Suite, Sekt, Paarmassagement, Terrassenessen (ab €950)\n"
                        "• Wellness-Retreat 3 Nächte, tägliches Yoga, 2 Massagen (ab €1.200)\n"
                        "• Abenteuer-Paket — Vintgar, Kajak, Fahrrad, Lunchpaket (ab €850)\n"
                        "• Familien-Paket — Superior/Island Suite, Fahrräder, Picknick (ab €1.100)\n"
                        "• Kulinarisches Erlebnis — 4-Gänge-Menü mit Wein, Kochkurs (ab €1.050)\n\n"
                        "🎵 **Sommer-Events in Bled:**\n"
                        "• Bled Festival (Juli) — klassische Musik auf der Bleder Burg\n"
                        "• Okarina World Music Festival (Juli–August)\n"
                        "• Bled Days (August)\n"
                        "• Bled International Rowing Regatta\n\n"
                        "🌅 Jeden Abend auf unserer Terrasse: Sunset Aperitivo mit Seeblick!\n"
                        "Möchten Sie mehr über eines der Pakete erfahren? Ich helfe gerne bei der Buchung!"
                    ),
                    "English": (
                        "Summer 2026 at Villa Adora — special packages and events:\n\n"
                        "🏖️ **Summer Packages:**\n"
                        "• Romance Package — 2 nights Princess/Penthouse Suite, champagne, couples massage, private terrace dinner (from €950)\n"
                        "• Wellness Retreat — 3 nights, daily yoga, 2 massages, healthy brunch (from €1,200)\n"
                        "• Adventure Package — Vintgar Gorge, kayak, bicycle rental, packed lunch (from €850)\n"
                        "• Family Getaway — Superior/Island Suite, bikes, lake picnic basket (from €1,100)\n"
                        "• Culinary Experience — 4-course tasting menu with wine pairing, cooking class with Chef Domen Demšar (from €1,050)\n\n"
                        "🎵 **Summer Events in Bled:**\n"
                        "• Bled Festival (July) — classical music at Bled Castle\n"
                        "• Okarina World Music Festival (July–August)\n"
                        "• Bled Days (August)\n"
                        "• Bled International Rowing Regatta\n\n"
                        "🌅 Every evening on our terrace: Sunset Aperitivo with lake views!\n"
                        "Would you like more details on any package? I'd be happy to help you book!"
                    ),
                    "French": (
                        "Été 2026 à Villa Adora — forfaits et événements spéciaux:\n\n"
                        "🏖️ **Forfaits d'été:**\n"
                        "• Forfait Romance — 2 nuits Princess/Penthouse Suite, champagne, massage couple, dîner terrasse (dès €950)\n"
                        "• Retraite Bien-être — 3 nuits, yoga quotidien, 2 massages (dès €1 200)\n"
                        "• Forfait Aventure — Vintgar, kayak, vélos, pique-nique (dès €850)\n"
                        "• Séjour Famille — Suite Superior/Island, vélos, panier pique-nique (dès €1 100)\n"
                        "• Expérience Culinaire — menu dégustation 4 plats avec vin, cours de cuisine (dès €1 050)\n\n"
                        "🎵 **Événements d'été à Bled:**\n"
                        "• Festival de Bled (juillet) — musique classique au château\n"
                        "• Okarina World Music Festival (juillet–août)\n"
                        "• Bled Days (août)\n"
                        "• Bled International Rowing Regatta\n\n"
                        "🌅 Chaque soir sur notre terrasse : Apéritif au coucher du soleil avec vue sur le lac !\n"
                        "Souhaitez-vous plus de détails sur un forfait ? Je serai ravi de vous aider à réserver !"
                    ),
                    "Italian": (
                        "Estate 2026 a Villa Adora — pacchetti ed eventi speciali:\n\n"
                        "🏖️ **Pacchetti estivi:**\n"
                        "• Pacchetto Romantico — 2 notti Princess/Penthouse Suite, champagne, coppia massaggio, cena terrazza (da €950)\n"
                        "• Ritiro Benessere — 3 notti, yoga quotidiano, 2 massaggi (da €1.200)\n"
                        "• Pacchetto Avventura — Vintgar, kayak, biciclette, pranzo al sacco (da €850)\n"
                        "• Vacanza in Famiglia — Suite Superior/Island, biciclette, cestino picnic (da €1.100)\n"
                        "• Esperienza Culinaria — menu degustazione 4 portate con vini, corso di cucina (da €1.050)\n\n"
                        "🎵 **Eventi estivi a Bled:**\n"
                        "• Festival di Bled (luglio) — musica classica al castello\n"
                        "• Okarina World Music Festival (luglio–agosto)\n"
                        "• Bled Days (agosto)\n"
                        "• Bled International Rowing Regatta\n\n"
                        "🌅 Ogni sera sulla nostra terrazza: Aperitivo al tramonto con vista sul lago!\n"
                        "Vuoi maggiori dettagli su un pacchetto? Sarò felice di aiutarti con la prenotazione!"
                    ),
                    "Spanish": (
                        "Verano 2026 en Villa Adora — paquetes y eventos especiales:\n\n"
                        "🏖️ **Paquetes de verano:**\n"
                        "• Paquete Romántico — 2 noches Princess/Penthouse Suite, champán, masaje parejas, cena terraza (desde €950)\n"
                        "• Retiro Wellness — 3 noches, yoga diario, 2 masajes (desde €1.200)\n"
                        "• Paquete Aventura — Vintgar, kayak, bicicletas, almuerzo (desde €850)\n"
                        "• Escapada Familiar — Suite Superior/Island, bicicletas, cesta picnic (desde €1.100)\n"
                        "• Experiencia Culinaria — menú degustación 4 platos con vino, clase de cocina (desde €1.050)\n\n"
                        "🎵 **Eventos de verano en Bled:**\n"
                        "• Festival de Bled (julio) — música clásica en el castillo\n"
                        "• Okarina World Music Festival (julio–agosto)\n"
                        "• Bled Days (agosto)\n"
                        "• Bled International Rowing Regatta\n\n"
                        "🌅 Cada tarde en nuestra terraza: Aperitivo al atardecer con vistas al lago!\n"
                        "¿Desea más detalles sobre algún paquete? ¡Estaré encantado de ayudarle!"
                    ),
                    "Croatian": (
                        "Ljeto 2026 u Villi Adora — posebni paketi i događaji:\n\n"
                        "🏖️ **Ljetni paketi:**\n"
                        "• Romantični paket — 2 noći Princess/Penthouse Suite, šampanjac, masaža za par, večera na terasi (od €950)\n"
                        "• Wellness retreat — 3 noći, dnevna joga, 2 masaže (od €1.200)\n"
                        "• Avanturistički paket — Vintgar, kajak, bicikli, ručak (od €850)\n"
                        "• Obiteljski paket — Superior/Island Suite, bicikli, piknik (od €1.100)\n"
                        "• Kulinarno iskustvo — meni s 4 jela i vinom, kučarski tečaj (od €1.050)\n\n"
                        "🎽 **Ljetni događaji u Bledu:**\n"
                        "• Bled Festival (srpanj) — klasična glazba na dvorcu\n"
                        "• Okarina World Music Festival (srpanj–kolovoz)\n"
                        "• Bled Days (kolovoz)\n"
                        "• Bled International Rowing Regatta\n\n"
                        "🌅 Svaku večer na našoj terasi: Sunset Aperitivo s pogledom na jezero!\n"
                        "Želite li više informacija o nekom paketu? Rado ću vam pomoći s rezervacijom!"
                    ),
                    "Serbian": (
                        "Leto 2026 u Villi Adora — posebni paketi i događaji:\n\n"
                        "🏖️ **Letnji paketi:**\n"
                        "• Romantični paket — 2 noći Princess/Penthouse Suite, šampanjac, masaža za par, večera na terasi (od €950)\n"
                        "• Wellness retreat — 3 noći, dnevna joga, 2 masaže (od €1.200)\n"
                        "• Avanturistički paket — Vintgar, kajak, bicikli, ručak (od €850)\n"
                        "• Porodični paket — Superior/Island Suite, bicikli, piknik (od €1.100)\n"
                        "• Kulinarno iskustvo — meni s 4 jela i vinom, kučarski tečaj (od €1.050)\n\n"
                        "🎵 **Letnji događaji u Bledu:**\n"
                        "• Bled Festival (jul) — klasična muzika na dvorcu\n"
                        "• Okarina World Music Festival (jul–avgust)\n"
                        "• Bled Days (avgust)\n"
                        "• Bled International Rowing Regatta\n\n"
                        "🌅 Svake večeri na našoj terasi: Sunset Aperitivo s pogledom na jezero!\n"
                        "Želite li više informacija o nekom paketu? Rado ću vam pomoći s rezervacijom!"
                    ),
                }
                direct_response = summer_responses.get(_lookup_lang, summer_responses["English"])
            # Adversarial / tech queries - redirect to hotel topics
            elif any(word in user_message.lower() for word in ["database", "api", "sqlite", "flask", "server", "backend", "rag", "tool", "function", "schema", "parameter", "token", "model", "llm", "openai", "openrouter", "deploy", "docker", "kubernetes", "codebase", "source code", "repository", "github", "podatkovna baza", "strežnik"]):
                adversarial_responses = {
                    "Slovenian": "Sem Luka, vaš concierge v Villi Adora Bled! Tukaj sem, da vam pri vašem bivanju pomagam s čim — sobami, hrano, aktivnostmi in več. Kaj bi radi izvedeli o našem hotelu?",
                    "German": "Ich bin Luka, Ihr Concierge im Villa Adora Bled! Ich bin hier, um Ihnen bei Ihrem Aufenthalt zu helfen — Zimmern, Essen, Aktivitäten und mehr. Was möchten Sie über unser Hotel wissen?",
                    "French": "Je suis Luka, votre concierge au Villa Adora Bled ! Je suis là pour vous aider avec tout concernant votre séjour — chambres, restauration, activités et plus. Que souhaitez-vous savoir sur notre hôtel ?",
                    "Italian": "Sono Luka, il vostro concierge al Villa Adora Bled! Sono qui per aiutarti con tutto riguardo il tuo soggiorno — camere, ristorazione, attività e altro. Cosa vorresti sapere sul nostro hotel?",
                    "Spanish": "¡Soy Luka, su conserje en Villa Adora Bled! Estoy aquí para ayudarle con todo sobre su estancia — habitaciones, restauración, actividades y más. ¿Qué le gustaría saber sobre nuestro hotel?",
                    "Croatian": "Ja sam Luka, vaš concierge u Villi Adora Bled! Tu sam da vam pomognem s vezom na boravak — sobama, hranom, aktivnostima i više. Što biste željeli znati o našem hotelu?",
                    "Serbian": "Ja sam Luka, vaš concierge u Villi Adora Bled! Tu sam da vam pomognem s vezom na boravak — sobama, hranom, aktivnostima i više. Što biste željeli znati o našem hotelu?",
                }
                direct_response = adversarial_responses.get(_lookup_lang, adversarial_responses["Slovenian"])

            if direct_response:
                # Use pre-translated content directly - update session and return
                messages.append({"role": "user", "content": user_message})
                messages.append({"role": "assistant", "content": direct_response})
                sessions[session_id] = messages
                # Ensure it ends with a question mark
                response_text = _ensure_ends_with_question(direct_response)
                response_text = _ensure_follow_up(response_text, topic if topic in ("rooms", "experiences", "activities") else "", detected_lang)
                return jsonify({"replies": [{"type": "text", "content": response_text}]})

            # For non-English booking intents, return a translated prompt for short
            # messages, or let the LLM handle it (with book_room tool) for longer ones.
            if topic == "booking" and len(user_message.strip()) < 30:
                booking_prompts = {
                    "English": "I'd be happy to help you book! We have 8 beautiful suites with lake views. I just need your name, dates, and preferred suite. Which one catches your eye?",
                    "Slovenian": "Z veseljem vam pomagam z rezervacijo! Imamo 8 čudovitih apartmajev z razgledom na jezero. Potrebujem vaše ime, datume in želeni apartma. Kateri vas najbolj pritegne?",
                    "German": "Ich helfe gerne bei der Buchung! Wir haben 8 wunderschöne Suiten mit Seeblick. Ich brauche Ihren Namen, Ihre Reisedaten und Ihre Suite-Welche gefällt Ihnen am besten?",
                    "French": "Je serai ravi de vous aider à réserver ! Nous avons 8 magnifiques suites avec vue sur le lac. J'ai besoin de votre nom, de vos dates et de votre suite préférée. Laquelle vous plaît le plus ?",
                    "Italian": "Sarò felice di aiutarti con la prenotazione! Abbiamo 8 splendide suite con vista sul lago. Mi servono il tuo nome, le date e la suite preferita. Quale ti piace di più?",
                    "Spanish": "¡Estaré encantado de ayudarte con la reserva! Tenemos 8 hermosas suites con vistas al lago. Necesito tu nombre, las fechas y la suite preferida. ¿Cuál te gusta más?",
                    "Croatian": "Rado ću vam pomoći s rezervacijom! Imamo 8 prekrasnih apartmana s pogledom na jezero. Trebam vaše ime, datume i željeni apartman. Koji vas najviše zanima?",
                }
                direct_response = booking_prompts.get(detected_lang, booking_prompts["Slovenian"])
                messages.append({"role": "user", "content": user_message})
                messages.append({"role": "assistant", "content": direct_response})
                sessions[session_id] = messages
                return jsonify({"replies": [{"type": "text", "content": direct_response}]})

            # Pre-LLM direct responses for common non-English topics to avoid LLM timeouts
            cancellation_keywords = {
                "Slovenian": ["odpoved", "preklic", "storno", "razveljavi"],
                "German": ["stornier", "rückerstattung", "widerruf", "annullier"],
                "French": ["annul", "rembours", "politique d'annulation"],
                "Italian": ["annull", "rimbors", "politica di annullamento"],
                "Spanish": ["cancel", "reembols", "política de cancelación"],
                "Croatian": ["odustat", "otkaž", "povrat", "stornir"],
            }
            is_cancellation = any(kw in user_message.lower() for kw in cancellation_keywords.get(detected_lang, []))
            if is_cancellation and topic in ("policies", "cancellation", "general"):
                cancellation_responses = {
                    "Slovenian": "Pri neposrednih rezervacijah je brezplačen preklic mogoč do 48 ur pred prihodom. Pri poznejšem preklicu ali nespuščanju se lahko zaračuna prva nočitev. Rezervacije prek Booking.com veljajo pogoji Booking.com. Nas kontaktirajte za posebne pogoje. Želite, da vašo rezervacijo zapišem?",
                    "German": "Bei Direktbuchungen ist eine kostenlose Stornierung bis 48 Stunden vor Check-in möglich. Bei verspäteter Stornierung oder No-Show kann die erste Nacht berechnet werden. Buchungen über Booking.com unterliegen den AGB von Booking.com. Kontaktieren Sie uns für spezifische Bedingungen. Soll ich Ihre Buchung für Sie notieren?",
                    "French": "Pour les réservations directes, l'annulation est gratuite jusqu'à 48 heures avant l'arrivée. Les annulations tardives ou les no-shows peuvent être facturés pour la première nuit. Les réservations via Booking.com suivent les conditions de Booking.com. Contactez-nous pour les conditions spécifiques. Souhaitez-vous que je note votre réservation?",
                    "Italian": "Per le prenotazioni dirette, la cancellazione è gratuita fino a 48 ore prima dell'arrivo. Le cancellazioni tardive o i no-show possono essere addebitati per la prima notte. Le prenotazioni tramite Booking.com seguono i termini di Booking.com. Contattaci per condizioni specifiche. Vuoi che annoti la tua prenotazione?",
                    "Spanish": "Para reservas directas, la cancelación es gratuita hasta 48 horas antes del check-in. Las cancelaciones tardías o no presentaciones pueden cobrarse por la primera noche. Las reservas a través de Booking.com siguen los términos de Booking.com. Contáctenos para condiciones específicas. ¿Desea que anote su reserva?",
                    "Croatian": "Za izravne rezervacije, otkazivanje je besplatno do 48 sata prije prijave. Kasna otkazivanja ili ne dolazak mogu se naplatiti za prvu noć. Rezervacije putem Booking.com podližu uvjetima Booking.com. Kontaktirajte nas za specifične uvjete. Želite li da zabilježim vašu rezervaciju?",
                }
                direct_response = cancellation_responses.get(detected_lang, cancellation_responses["Slovenian"])
                messages.append({"role": "user", "content": user_message})
                messages.append({"role": "assistant", "content": direct_response})
                sessions[session_id] = messages
                return jsonify({"replies": [{"type": "text", "content": direct_response}]})

            # Handle social messages (greetings, thanks, goodbyes) directly to avoid LLM language issues
            social_keywords = {
                "English": ["thank", "thanks", "hello", "hi ", "hey", "goodbye", "bye", "good morning", "good evening", "good night", "good afternoon", "how are you", "how do you do", "welcome"],
                "Slovenian": ["hvala", "pozdra", "zdravo", "nasvidenje", "dober dan", "pozdravljeni", "lahko no\u010d", "dobrodo\u0161li", "kako ste", "kako si", "lep dan", "adijo", "aju", "sre\u010dno", "nasvidenje", "se sli\u0161imo"],
                "German": ["danke", "vielen dank", "guten tag", "guten morgen", "guten abend", "auf wiedersehen", "tschüss", "hallo", "willkommen", "wie geht"],
                "French": ["merci", "bonjour", "bonsoir", "au revoir", "salut", "bienvenue", "comment allez", "enchanté"],
                "Italian": ["grazie", "buongiorno", "buonasera", "arrivederci", "ciao", "benvenuto", "come stai", "prego"],
                "Spanish": ["gracias", "hola", "buenos", "buenas", "adiós", "bienvenido", "bienvenida", "cómo estás", "de nada"],
                "Croatian": ["hvala", "pozdrav", "zdravo", "doviđenja", "dobrodošli", "kako si", "lijep dan", "bok", "zbogom", "sretno"],
                "Serbian": ["hvala", "pozdrav", "zdravo", "doviđenja", "dobrodošli", "kako si", "lijep dan", "bok", "zbogom", "sretno"],
            }
            is_social = any(kw in user_message.lower() for kw in social_keywords.get(detected_lang, []))
            if is_social and topic == "general":
                # Use proper social responses per language
                social_type = "greeting"
                msg_lower = user_message.lower()
                goodbye_words = {
                    "English": ["goodbye", "bye ", "see you", "farewell"],
                    "Slovenian": ["nasvidenje", "adijo", "sre\u010dno", "se sli\u0161imo"],
                    "German": ["auf wiedersehen", "tschüss", "tschau"],
                    "French": ["au revoir", "salut"],
                    "Italian": ["arrivederci", "ciao"],
                    "Spanish": ["adiós", "hasta luego"],
                    "Croatian": ["doviđenja", "bok", "zbogom"],
                    "Serbian": ["doviđenja", "bok", "zbogom"],
                }
                thanks_words = {
                    "English": ["thank", "thanks"],
                    "Slovenian": ["hvala"],
                    "German": ["danke", "vielen dank"],
                    "French": ["merci"],
                    "Italian": ["grazie"],
                    "Spanish": ["gracias"],
                    "Croatian": ["hvala"],
                    "Serbian": ["hvala"],
                }
                if any(w in msg_lower for w in goodbye_words.get(detected_lang, [])):
                    social_type = "goodbye"
                elif any(w in msg_lower for w in thanks_words.get(detected_lang, [])):
                    social_type = "thanks"

                social_responses = {
                    "greeting": {
                        "English": "Hello! Welcome to Villa Adora Bled! How can I help make your stay special today?",
                        "Slovenian": "Dober dan! Dobrodo\u0161li v Villi Adora Bled! Kako vam lahko pomagam pri va\u0161em bivanju?",
                        "German": "Guten Tag! Willkommen im Villa Adora Bled! Wie kann ich Ihnen bei Ihrem Aufenthalt helfen?",
                        "French": "Bonjour ! Bienvenue au Villa Adora Bled ! Comment puis-je vous aider avec votre séjour ?",
                        "Italian": "Buongiorno! Benvenuto al Villa Adora Bled! Come posso aiutarti con il tuo soggiorno?",
                        "Spanish": "¡Buenos días! ¡Bienvenido a Villa Adora Bled! ¿Cómo puedo ayudarte con tu estancia?",
                        "Serbian": "Zdravo! Dobrodošli u Villa Adora Bled! Kako vam mogu pomoći sa vašim boravkom?",
                    },
                    "thanks": {
                        "English": "You're very welcome! Is there anything else I can help you with today?",
                        "Slovenian": "Ni za kaj! Vam lahko še kako pomagam?",
                        "German": "Gern geschehen! Kann ich Ihnen noch mit etwas helfen?",
                        "French": "Je vous en prie ! Y a-t-il autre chose que je puisse faire pour vous ?",
                        "Italian": "Prego! C'è altro con cui posso aiutarti?",
                        "Spanish": "¡De nada! ¿Hay algo más en lo que pueda ayudarte?",
                        "Croatian": "Nema na čemu! Mogu li vam još nekako pomoći?",
                        "Serbian": "Nema na čemu! Mogu li vam još nekako pomoći?",
                    },
                    "goodbye": {
                        "English": "Goodbye! We look forward to welcoming you to Villa Adora Bled. Safe travels — is there anything else before you go?",
                        "Slovenian": "Nasvidenje! Upamo, da vas bomo kmali spet videli v Villi Adora Bled. Varno pot — vas še kaj zanima?",
                        "German": "Auf Wiedersehen! Wir freuen uns, Sie im Villa Adora Bled begrüßen zu dürfen. Gute Reise — kann ich Ihnen noch mit etwas helfen?",
                        "French": "Au revoir ! Nous avons hâte de vous accueillir au Villa Adora Bled. Bon voyage — y a-t-il autre chose avant de partir ?",
                        "Italian": "Arrivederci! Non vediamo l'ora di accoglierci al Villa Adora Bled. Buon viaggio — c'è altro prima di partire?",
                        "Spanish": "¡Adiós! Esperamos darle la bienvenida a Villa Adora Bled. Buen viaje — ¿hay algo más antes de irte?",
                        "Croatian": "Doviđenja! Radujemo se što ćemo vas dočekati u Villa Adora Bled. Sretan put — imam li vam još nešto pomoći?",
                        "Serbian": "Doviđenja! Radujemo se što ćemo vas dočekati u Villa Adora Bled. Sretan put — imam li vam još nešto pomoći?",
                    },
                }
                fallback = social_responses.get(social_type, social_responses["greeting"]).get(
                    detected_lang, social_responses["greeting"]["English"]
                )
                messages.append({"role": "user", "content": user_message})
                messages.append({"role": "assistant", "content": fallback})
                sessions[session_id] = messages
                return jsonify({"replies": [{"type": "text", "content": fallback}]})

            # For other topics, use LLM with pre-fetched data
            # If topic is still "general" for non-English, use localized fallback
            # instead of sending to LLM (which often gives generic greetings)
            if is_non_english and topic == "general":
                fallback = _get_localized_fallback(detected_lang, user_message)
                messages.append({"role": "user", "content": user_message})
                messages.append({"role": "assistant", "content": fallback})
                sessions[session_id] = messages
                return jsonify({"replies": [{"type": "text", "content": fallback}]})

            hotel_answer = get_hotel_info_response(topic, user_message)
            if hotel_answer and hotel_answer.strip():
                lang_messages.append({
                    "role": "system",
                    "content": f"MANDATORY INSTRUCTION — YOU MUST FOLLOW THIS:\n\n1. Respond ENTIRELY in {detected_lang}. EVERY word must be in {detected_lang}.\n2. Do NOT use English except for proper nouns: 'Villa Adora', 'Lake Bled', 'Bled Island', 'Bled Castle', 'Chef Domen Demšar'.\n3. Translate ALL hotel information below to {detected_lang}.\n4. Be warm, concise, and end with a follow-up question in {detected_lang}.\n5. The FINAL character of your response MUST be '?'.\n\nHOTEL DATA TO TRANSLATE:\n{hotel_answer}"
                })
            else:
                lang_messages.append({
                    "role": "system",
                    "content": f"MANDATORY: The guest wrote in {detected_lang}. Respond ENTIRELY in {detected_lang}. Be warm, concise, and end with a follow-up question in {detected_lang}. The FINAL character MUST be '?'."
                })
        else:
            # For English messages, use direct response for rooms/experiences to reduce latency
            # Adversarial / tech queries - redirect to hotel topics (before LLM call)
            adversarial_keywords_en = ["database", "api", "sqlite", "flask", "server", "backend", "rag", "tool", "function", "schema", "parameter", "token", "model", "llm", "openai", "openrouter", "deploy", "docker", "kubernetes", "codebase", "source code", "repository", "github"]
            if any(word in user_message.lower() for word in adversarial_keywords_en):
                response_text = (
                    "I'm Luka, your concierge at Villa Adora Bled! "
                    "I'm here to help you with everything about your stay — rooms, dining, activities, and more. "
                    "What would you like to know about our hotel?"
                )
                messages.append({"role": "user", "content": user_message})
                messages.append({"role": "assistant", "content": response_text})
                sessions[session_id] = messages
                return jsonify({"replies": [{"type": "text", "content": response_text}]})
            # Swimming pool queries - Villa Adora doesn't have one, but Villa Pomona does
            if any(word in user_message.lower() for word in ["swimming pool", "pool", "swim", "bazen", "bazenu", "bazena", "Schwimmbad", "piscina", "piscine", "natazione"]):
                response_text = (
                    "Villa Adora Bled doesn't have a swimming pool, but guests can swim in the pristine Lake Bled right outside! "
                    "We also have a sister property, Villa Pomona, which features a swimming pool, sauna, and full wellness facilities — perfect for a private retreat. "
                    "Would you like more details about Villa Pomona, or shall I tell you about swimming in the lake?"
                )
                messages.append({"role": "user", "content": user_message})
                messages.append({"role": "assistant", "content": response_text})
                sessions[session_id] = messages
                return jsonify({"replies": [{"type": "text", "content": response_text}]})
            if topic == "rooms":
                hotel_answer = get_hotel_info_response("rooms", user_message)
                if hotel_answer and hotel_answer.strip():
                    messages.append({"role": "user", "content": user_message})
                    messages.append({"role": "assistant", "content": hotel_answer})
                    sessions[session_id] = messages
                    response_text = _ensure_ends_with_question(hotel_answer)
                    response_text = _ensure_follow_up(response_text, "rooms", "English")
                    return jsonify({"replies": [{"type": "text", "content": response_text}]})
            elif topic in ("experiences", "activities"):
                hotel_answer = get_hotel_info_response("experiences", user_message)
                if hotel_answer and hotel_answer.strip():
                    messages.append({"role": "user", "content": user_message})
                    messages.append({"role": "assistant", "content": hotel_answer})
                    sessions[session_id] = messages
                    response_text = _ensure_ends_with_question(hotel_answer)
                    response_text = _ensure_follow_up(response_text, "experiences", "English")
                    return jsonify({"replies": [{"type": "text", "content": response_text}]})
            elif topic == "booking":
                # Let the LLM handle booking with the book_room tool — it can extract
                # name, dates, and room from the user's message in one go.
                # Only return the static prompt if the message is very short (likely
                # just "I want to book" without details).
                if len(user_message.strip()) < 30:
                    hotel_answer = get_hotel_info_response("booking", user_message)
                    if hotel_answer and hotel_answer.strip():
                        messages.append({"role": "user", "content": user_message})
                        messages.append({"role": "assistant", "content": hotel_answer})
                        sessions[session_id] = messages
                        response_text = _ensure_ends_with_question(hotel_answer)
                        response_text = _ensure_follow_up(response_text, "rooms", "English")
                        return jsonify({"replies": [{"type": "text", "content": response_text}]})
                # Otherwise fall through to LLM with book_room tool available
            elif topic == "gift_vouchers":
                # Direct response for gift vouchers — static content, no LLM needed
                hotel_answer = get_hotel_info_response("gift_vouchers", user_message)
                if hotel_answer and hotel_answer.strip():
                    messages.append({"role": "user", "content": user_message})
                    messages.append({"role": "assistant", "content": hotel_answer})
                    sessions[session_id] = messages
                    response_text = _ensure_ends_with_question(hotel_answer)
                    return jsonify({"replies": [{"type": "text", "content": response_text}]})
            elif topic == "wedding":
                # Direct response for wedding queries — static content
                hotel_answer = get_hotel_info_response("wedding", user_message)
                if hotel_answer and hotel_answer.strip():
                    messages.append({"role": "user", "content": user_message})
                    messages.append({"role": "assistant", "content": hotel_answer})
                    sessions[session_id] = messages
                    response_text = _ensure_ends_with_question(hotel_answer)
                    return jsonify({"replies": [{"type": "text", "content": response_text}]})
            elif topic == "bar":
                # Direct response for bar queries — static content
                hotel_answer = get_hotel_info_response("bar", user_message)
                if hotel_answer and hotel_answer.strip():
                    messages.append({"role": "user", "content": user_message})
                    messages.append({"role": "assistant", "content": hotel_answer})
                    sessions[session_id] = messages
                    response_text = _ensure_ends_with_question(hotel_answer)
                    return jsonify({"replies": [{"type": "text", "content": response_text}]})
            # Direct response for combined restaurant+wine/dining queries to avoid LLM timeout
            elif topic in ("restaurant", "wine") and any(w in user_message.lower() for w in ["restaurant", "wine", "dining", "menu", "chef", "selection"]):
                r = hotel_info.get("dining", {}).get("restaurant", {})
                m = hotel_info.get("menu", {}).get("restaurant", {})
                w = hotel_info.get("menu", {}).get("wine_list", {})
                combined = (
                    f"We have the {r.get('name', 'Adora Pop Up Restaurant')} right here at the hotel! "
                    f"{r.get('description', 'Creative Slovenian cuisine with stunning lake views.')} "
                    f"Hours: Lunch & Dinner {r.get('hours', {}).get('lunch', 'Tue-Sun')}, "
                    f"Brunch {r.get('hours', {}).get('brunch', 'Thu-Sat')}. "
                    f"The terrace has arguably the best sunset views in Bled. "
                    f"Our wine list is curated by an in-house wine expert, featuring the best Slovenian wines "
                    f"from vineyards near Bled alongside selected international labels. "
                    f"Wine pairing is available with our tasting menu (approximately €35/person). "
                    f"The tasting menu is approximately €65/person. "
                    f"Reservations: {r.get('phone', '+386 40 558 158')} or {r.get('email', 'evita.vilebled@gmail.com')}. "
                    f"Would you like to make a reservation?"
                )
                messages.append({"role": "user", "content": user_message})
                messages.append({"role": "assistant", "content": combined})
                sessions[session_id] = messages
                return jsonify({"replies": [{"type": "text", "content": combined}]})
            elif topic in ("room_service", "pets", "parking", "wifi", "shuttle", "location", "check_in", "check_out", "late_check_in", "late_check_out", "restaurant", "wine", "breakfast", "children", "contact", "amenities", "smoking", "spa", "weather", "cancellation", "policies", "gym", "experiences", "villa_pomona"):
                # Re-route dietary accommodation questions to restaurant for a richer response
                if topic == "breakfast" and any(w in user_message.lower() for w in ["accommodate", "can you", "can i", "do you", "options", "serve", "provide"]) and any(w in user_message.lower() for w in ["vegan", "vegetarian", "gluten", "dietary", "allergy", "allergies", "restriction", "végétalien", "végétarien", "sans gluten", "opciones veganas", "opciones vegetarianas", "opciones sin gluten", "vegane", "vegetarische", "glutenfreie", "bez glutena", "végétaliennes", "végétariennes", "opzione vegane"]):
                    topic = "restaurant"
                hotel_answer = get_hotel_info_response(topic, user_message)
                if hotel_answer and hotel_answer.strip():
                    messages.append({"role": "user", "content": user_message})
                    messages.append({"role": "assistant", "content": hotel_answer})
                    sessions[session_id] = messages
                    response_text = _ensure_ends_with_question(hotel_answer)
                    response_text = _ensure_follow_up(response_text, "", "English")
                    return jsonify({"replies": [{"type": "text", "content": response_text}]})

        if not is_non_english and topic == "general":
            msg_lower = user_message.strip().lower()
            social_patterns = {
                "greeting": ["hello", "hi ", "hey ", "good morning", "good evening", "good night", "good afternoon", "how are you", "how do you do"],
                "thanks": ["thank", "thanks", "thanks a lot", "thank you"],
                "goodbye": ["goodbye", "bye ", "see you", "farewell"],
            }
            is_social = False
            social_type = ""
            for stype, patterns in social_patterns.items():
                if any(p in msg_lower for p in patterns):
                    is_social = True
                    social_type = stype
                    break
            if is_social and len(user_message.strip()) < 50:
                social_responses = {
                    "greeting": "Hello! Welcome to Villa Adora Bled! How can I help make your stay special today?",
                    "thanks": "You're very welcome! Is there anything else I can help you with today?",
                    "goodbye": "Goodbye! We look forward to welcoming you to Villa Adora Bled. Safe travels — is there anything else before you go?",
                }
                response_text = social_responses.get(social_type, social_responses["greeting"])
                messages.append({"role": "user", "content": user_message})
                messages.append({"role": "assistant", "content": response_text})
                sessions[session_id] = messages
                return jsonify({"replies": [{"type": "text", "content": response_text}]})

        # For non-English messages, include book_room but with strict validation
        # on the Python side (dates, placeholder names, etc. are all checked).
        # Shuttle booking and human agent transfer are always available.
        # query_hotel_info is included for all languages so the LLM can look up
        # hotel facts instead of giving generic brief responses.
        if is_non_english:
            available_tools = [book_room_function, query_hotel_info_function, book_shuttle_function, request_human_agent_function]
        else:
            available_tools = [book_room_function, query_hotel_info_function, book_shuttle_function, request_human_agent_function]

        tool_params = {
            "model": MODEL,
            "messages": lang_messages,
            "tools": available_tools,
            "temperature": 0.3 if is_non_english else 0.5,
            "max_tokens": 2000,
            "timeout": 40,
        }
        tool_params["tool_choice"] = "auto"

        response = client.chat.completions.create(**tool_params)
        choice = response.choices[0] if response.choices else None
        if choice is None:
            return jsonify({"replies": [{"type": "text", "content": "No response from model."}]}), 500

        msg = choice.message
        content = fix_spacing(getattr(msg, "content", None) or "")
        tool_calls = getattr(msg, "tool_calls", None) or []

        # Build assistant message with properly formatted tool_calls
        assistant_msg = {"role": "assistant", "content": content}
        if tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id if hasattr(tc, "id") else tc.get("id", f"call_{i}"),
                    "type": "function",
                    "function": {
                        "name": tc.function.name if hasattr(tc.function, "name") else tc.get("function", {}).get("name"),
                        "arguments": tc.function.arguments if hasattr(tc.function, "arguments") else tc.get("function", {}).get("arguments"),
                    }
                }
                for i, tc in enumerate(tool_calls)
            ]
        messages.append(assistant_msg)
        replies = []
        for i, tc in enumerate(tool_calls):
            tc_id = tc.id if hasattr(tc, "id") else tc.get("id", f"call_{i}")
            fn = (
                tc.function.name
                if hasattr(tc, "function") and hasattr(tc.function, "name")
                else tc.get("function", {}).get("name")
            )
            raw_args = (
                tc.function.arguments
                if hasattr(tc, "function") and hasattr(tc.function, "arguments")
                else tc.get("function", {}).get("arguments")
            )
            if not fn:
                continue
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args)
                except (json.JSONDecodeError, TypeError):
                    args = {}
            elif isinstance(raw_args, dict):
                args = raw_args
            else:
                args = {}
            if not isinstance(args, dict):
                continue
            tool_reply = None
            if fn == "book_room":
                # Validate booking args to prevent LLM hallucinations
                from datetime import date as _date
                guest_name = args.get("guest_name", "").strip()
                check_in = args.get("check_in", "").strip()
                check_out = args.get("check_out", "").strip()
                room_name = args.get("room_name", "").strip()
                # Reject if any required field is empty
                if not guest_name or not check_in or not check_out or not room_name:
                    tool_reply = (
                        "I'd love to help you book! I just need a few more details: "
                        "your name, check-in date, check-out date, and preferred room. "
                        "Could you provide those?"
                    )
                    replies.append({"type": "text", "content": tool_reply})
                    continue
                # Reject if dates are in the past
                try:
                    ci = _date.fromisoformat(check_in)
                    co = _date.fromisoformat(check_out)
                    if ci < _date.today() or co < _date.today():
                        tool_reply = (
                            "I notice those dates are in the past. Could you please "
                            "provide your actual travel dates so I can help with your booking?"
                        )
                        replies.append({"type": "text", "content": tool_reply})
                        continue
                    if co <= ci:
                        tool_reply = (
                            "It looks like the check-out date is before the check-in date. "
                            "Could you double-check your dates for me?"
                        )
                        replies.append({"type": "text", "content": tool_reply})
                        continue
                except ValueError:
                    pass  # If date format is invalid, proceed anyway
                # Reject common placeholder/hallucinated names
                placeholder_names = {"mario", "rossi", "mario rossi", "john doe", "jane doe", "test", "guest", "anonymous"}
                if guest_name.lower() in placeholder_names:
                    tool_reply = (
                        f"I'd like to make sure I have the correct details. "
                        f"Could you please confirm your name for the booking?"
                    )
                    replies.append({"type": "text", "content": tool_reply})
                    continue
                room_key = room_name.lower().replace(" ", "_")
                price = hotel_info["rooms"].get(room_key, {}).get("price", "")
                price_str = f" ({price} EUR/night)" if price else ""
                replies.append(
                    {
                        "type": "confirmation_request",
                        "content": (
                            f"Booking Confirmation\n\n"
                            f"• Guest: {guest_name}\n"
                            f"• Check-in: {check_in}\n"
                            f"• Check-out: {check_out}\n"
                            f"• Room: {room_name}{price_str}\n\n"
                            "Reply yes to confirm or no to cancel? Thank you!"
                        ),
                    }
                )
                sessions[session_id] = messages + [
                    {"role": "system", "content": f"BOOKING_PENDING: {json.dumps(args)}"}
                ]
            elif fn == "query_hotel_info":
                topic = args.get("topic", "general")
                question = args.get("question", user_message)
                answer = get_hotel_info_response(topic, question)
                if not answer or not answer.strip():
                    answer = get_hotel_info_response("general", user_message)
                if not answer or not answer.strip():
                    answer = (
                        "I'd be happy to help with that! Could you tell me more about what you'd like to know? "
                        "I can assist with rooms, check-in times, breakfast, parking, and more."
                    )
                answer = fix_spacing(answer)

                # If guest provided a specific time for late check-in/out, save to calendar
                if topic in ("late_check_in", "late_check_out", "check_in", "check_out"):
                    extracted_time = extract_time_from_message(user_message)
                    if extracted_time:
                        event_type = "late_check_in" if "check_in" in topic or "arrival" in user_message.lower() else "late_check_out"
                        guest_name = "Guest"
                        for msg in messages:
                            if isinstance(msg, dict) and msg.get("role") == "user":
                                name_match = re.search(r"(?:my name is|i'm|i am|this is)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", msg.get("content", ""), re.IGNORECASE)
                                if name_match:
                                    guest_name = name_match.group(1)
                                    break
                        add_calendar_event(
                            session_id=session_id,
                            event_type=event_type,
                            guest_name=guest_name,
                            time=extracted_time,
                            notes=f"Guest requested {event_type.replace('_', ' ')} at {extracted_time}. Original message: {user_message}",
                            date=extract_date_from_message(user_message)
                        )

                tool_reply = answer
                replies.append({"type": "text", "content": answer})
            elif fn == "book_shuttle":
                from database import add_shuttle_booking
                add_shuttle_booking(
                    session_id=session_id,
                    guest_name=args.get("guest_name", "Guest"),
                    pickup_location=args.get("pickup_location", ""),
                    dropoff_location=args.get("dropoff_location", "Villa Adora Bled"),
                    date=args.get("date", ""),
                    time=args.get("time", ""),
                    passengers=args.get("passengers", 1),
                    notes=args.get("notes", ""),
                )
                tool_reply = (
                    f"Shuttle booked for {args.get('guest_name', 'the guest')}! "
                    f"Pickup: {args.get('pickup_location', 'TBD')} on {args.get('date', 'TBD')} at {args.get('time', 'TBD')}. "
                    f"Passengers: {args.get('passengers', 1)}. "
                    f"Our team will confirm shortly. Is there anything else I can help you with?"
                )
                replies.append({"type": "text", "content": tool_reply})
            elif fn == "request_human_agent":
                from database import add_human_agent_request
                add_human_agent_request(
                    session_id=session_id,
                    reason=args.get("reason", "Guest requested human agent"),
                    guest_name=args.get("guest_name", "Guest"),
                    summary=args.get("summary", ""),
                )
                tool_reply = (
                    f"I understand you'd like to speak with a human agent. "
                    f"I've notified our reception team — they'll be with you shortly. "
                    f"You can also call us directly at +386 51 603 858. "
                    f"Thank you for your patience!"
                )
                replies.append({"type": "text", "content": tool_reply})
            if tool_reply is not None:
                messages.append({"role": "tool", "tool_call_id": tc_id, "content": tool_reply})

        if not replies:
            if tool_calls:
                fallback = get_hotel_info_response("general", user_message)
                replies.append({"type": "text", "content": fallback})
            else:
                factual_keywords = [
                    "room", "suite", "check", "breakfast", "restaurant", "bar",
                    "wine", "parking", "pet", "dog", "cat", "location", "address",
                    "where", "activity", "activities", "wifi", "internet", "shuttle",
                    "transfer", "airport", "policy", "cancel", "payment", "price", "cost",
                    "hour", "time", "contact", "phone", "email", "direction",
                    "nearby", "around", "do here", "vegan", "vegetarian", "gluten",
                    "dietary", "allergy", "amenity", "facility", "service", "book",
                    "reservation", "available", "offer", "have", "provide",
                    "room service", "massage", "spa", "book", "reserve", "reservation",
                ]
                msg_lower = user_message.lower()
                # Detect topic for smarter fallback
                detected_topic = _detect_topic(user_message)
                is_factual = any(kw in msg_lower for kw in factual_keywords)
                # Non-factual social messages (greetings, thanks, goodbyes)
                is_social = any(kw in msg_lower for kw in ["thank", "thanks", "bye", "goodbye", "hello", "hi ", "hey", "good morning", "good evening", "good night", "good afternoon", "how are you", "how do you do"])
                is_short = len(user_message.strip()) < 20
                if is_social and is_short and not is_factual:
                    # Let LLM handle social messages naturally but ensure language match
                    if is_non_english and content:
                        # Check if LLM responded in the right language
                        pass  # Language check below will catch English responses
                    replies.append({"type": "text", "content": content})
                elif is_factual:
                    fallback = get_hotel_info_response(detected_topic, user_message)
                    if len(content.strip()) < 80:
                        replies.append({"type": "text", "content": fallback})
                    else:
                        # Use LLM content if it's substantial, but verify it's on-topic
                        replies.append({"type": "text", "content": content})
                else:
                    replies.append({"type": "text", "content": content})

        # Check if guest mentioned a late check-in or check-out time
        msg_lower = user_message.lower()
        is_late_checkin = any(word in msg_lower for word in ["late check-in", "late checkin", "arrive late", "late arrival", "arriving late", "late at", "arrive at", "get in late", "coming late", "late check in"])
        is_late_checkout = any(word in msg_lower for word in ["late check-out", "late checkout", "late check out", "check out late", "later checkout"])
        if is_late_checkin or is_late_checkout:
            extracted_time = extract_time_from_message(user_message)
            if extracted_time:
                event_type = "late_check_in" if is_late_checkin else "late_check_out"
                guest_name = "Guest"
                for msg in messages:
                    if isinstance(msg, dict) and msg.get("role") == "user":
                        name_match = re.search(r"(?:my name is|i'm|i am|this is)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", msg.get("content", ""), re.IGNORECASE)
                        if name_match:
                            guest_name = name_match.group(1)
                            break
                add_calendar_event(
                    session_id=session_id,
                    event_type=event_type,
                    guest_name=guest_name,
                    time=extracted_time,
                    notes=f"Guest requested {event_type.replace('_', ' ')} at {extracted_time}. Message: {user_message}",
                    date=extract_date_from_message(user_message)
                )
            else:
                if replies and "what time would you like" not in replies[-1]["content"].lower() and "what time were you planning" not in replies[-1]["content"].lower():
                    late_time_prompts = {
                        "English": " What time would you like? Let me know and I'll pass it along.",
                        "Slovenian": " Ob kateri uri bi radi? Samo povejte, pa bom posredoval!",
                        "German": " Zu welcher Uhrzeit möchten Sie? Lassen Sie es mich wissen!",
                        "French": " À quelle heure souhaiteriez-vous ? Faites-le moi savoir !",
                        "Italian": " A che ora vorresti? Fammi sapere!",
                        "Spanish": "¿A qué hora te gustaría? ¡Házmelo saber!",
                        "Croatian": " U koliko sati biste željeli? Samo mi recite!",
                    }
                    replies[-1]["content"] += late_time_prompts.get(detected_lang, late_time_prompts["English"])

        # Clean up any model reasoning text from responses
        for reply in replies:
            if reply.get("type") == "text" and reply.get("content"):
                reply["content"] = clean_response(reply["content"])
                # Anti-hallucination: remove any mention of Castle Suite (not a real room)
                reply["content"] = re.sub(r'(?i)\bCastle Suite\b[^.\n]*', '', reply["content"])
                # Anti-hallucination: correct breakfast misinformation
                # Breakfast is €22/person, NOT included in room rate, served 8-10 AM
                if re.search(r'(?i)breakfast.*(?:included|complimentary|free)', reply["content"]) or \
                   re.search(r'(?i)(?:included|complimentary|free).*breakfast', reply["content"]):
                    # Replace the hallucinated breakfast response with correct info
                    reply["content"] = (
                        "Breakfast is €22 per person, served daily 8-10 AM on our terrace with fresh pastries, bread, and local Slovenian products. "
                        "We also offer vegan, vegetarian, and gluten-free options on request. "
                        "Shall I add breakfast to your booking?"
                    )
                # Fix wrong breakfast times (e.g., 7:30-10:30 is wrong, correct is 8-10 AM)
                reply["content"] = re.sub(
                    r'(?i)breakfast.*?(?:7\s*[:.]?\s*30|10\s*[:.]?\s*30).*?(?:AM|am)',
                    'Breakfast is served 8-10 AM',
                    reply["content"]
                )
                # Clean up any double spaces or dangling bullets left by removal
                reply["content"] = re.sub(r'\n\s*•\s*$', '', reply["content"])
                reply["content"] = re.sub(r'\n{3,}', '\n\n', reply["content"])
                reply["content"] = re.sub(r'  +', ' ', reply["content"])
                reply["content"] = reply["content"].strip()
                # Ensure the response ends with a question mark
                reply["content"] = _ensure_ends_with_question(reply["content"])
                if reply.get("type") == "text" and reply.get("content"):
                    reply["content"] = _ensure_follow_up(reply["content"], "", detected_lang)
                # Post-process: if response was supposed to be non-English but came back in English,
                # replace with a translated fallback
                if is_non_english and reply.get("content"):
                    content = reply["content"]
                    # Check if response is still mostly English (simple heuristic)
                    english_words = ["the ", "we ", "our ", "you ", "have ", "are ", "with ", "and ", "for ", "this ", "that ", "here ", "there ", "would ", "could ", "should ", "will ", "can ", "your", "is ", "it ", "to ", "of ", "in ", "on ", "at ", "as ", "be ", "do ", "no ", "if ", "my ", "so "]
                    non_english_indicators = {
                        "Slovenian": ["imo", "vas", "prosim", "hvala", "sobe", "apartma", "lahko", "kako", "kakš", "želi", "dober", "pozdra", "nasvid"],
                        "German": ["ich ", "sie ", "das ", "die ", "der ", "und ", "für ", "mit ", "haben ", "sind ", "können ", "möchten ", "guten", "vielen"],
                        "French": ["nous ", "vous ", "les ", "des ", "est ", "une ", "notre ", "merci ", "bonjour ", "chambre ", "avez ", "pouvez ", "voudrais "],
                        "Italian": ["nostro", "nostra", "grazie", "buongiorno", "camera", "camere", "abbiamo", "avete", "vorrei", "posso", "belliss"],
                        "Spanish": ["hola", "gracias", "buenos", "buenas", "tenemos", "habitaciones", "quiere", "puede", "nuestro", "nuestra", "favor", "también", "estamos", "donde", "cuando", "cuanto", "magnífico", "perfecto"],
                    }
                    eng_count = sum(1 for w in english_words if w in content.lower())
                    non_eng_count = sum(1 for w in non_english_indicators.get(detected_lang, []) if w in content.lower())
                    # If lots of English words and very few non-English indicators, it's probably still English
                    if eng_count > 3 and non_eng_count < 2 and len(content) > 50:
                        # Replace with a translated fallback
                        reply["content"] = _get_localized_fallback(detected_lang, user_message)
                # Post-process: if response was supposed to be English but came back in another language,
                # replace with English fallback
                if not is_non_english and reply.get("content"):
                    content = reply["content"]
                    # Check if response is in a non-English language
                    non_english_markers = {
                        "French": ["nous ", "vous ", "notre ", "merci ", "bonjour ", "chambre ", "avez ", "pouvez ", "voudrais ", "sommes ", "c'est ", "les ", "des ", "est ", "une ", "oui, ", "le ", "la ", "en ", "du ", "au ", "venez ", "proposons ", "disposons ", "offrons ", "avons ", "êtes ", "souhaitez ", "voulez ", "êtes ", "cette ", "dans ", "pour ", "avec ", "sur ", "sont ", "vos ", "mes ", "tes ", "ses ", "nos ", "leurs "],
                        "German": ["wir ", "sie ", "ihr ", "zimmer", "suite", "seeblick", "parkplatz", "haben ", "sind ", "können ", "möchten ", "guten", "vielen", "danke", "bitte", "und ", "für ", "mit ", "das ", "die ", "der ", "ist ", "sind ", "auch ", "oder ", "aber ", "nach ", "bei ", "von ", "aus ", "nur ", "noch ", "schon ", "sehr ", "hier ", "dort ", "wenn ", "weil ", "dass ", "wie ", "was ", "wer ", "wo ", "wann ", "warum "],
                        "Italian": ["nostro", "nostra", "camera", "camere", "vista", "lago", "parcheggio", "avete", "abbiamo", "vorrei", "posso", "belliss", "grazie", "buongiorno", "prenotazione", "anche", "sono", "come", "quando", "dove", "perché", "cosa", "chi", "quale", "questo", "questa", "quello", "quella"],
                        "Spanish": ["nuestro", "nuestra", "habitaciones", "vistas", "lago", "estacionamiento", "tenemos", "puede", "quiere", "gracias", "hola", "buenos", "buenas", "favor", "también", "estamos", "donde", "cuando", "cuanto", "magnífico", "perfecto", "como", "pero", "para", "con", "sin", "sobre", "entre", "hasta", "desde", "este", "esta", "ese", "esa"],
                        "Slovenian": ["imo", "vas", "sobe", "apartma", "jezero", "hvala", "prosim", "lahko", "kako", "kakš", "želi", "dober", "pozdra", "nasvid", "prihod", "odhod", "tukaj", "kjer", "kako", "zakaj", "kaj", "kdo", "kateri", "kdaj", "koliko"],
                    }
                    for lang, markers in non_english_markers.items():
                        marker_count = sum(1 for m in markers if m.lower() in content.lower())
                        # If 3+ non-English markers found, the response is likely in the wrong language
                        if marker_count >= 3:
                            # Replace with English fallback
                            topic = _detect_topic(user_message)
                            reply["content"] = get_hotel_info_response(topic, user_message)
                            break
            # If content is empty after cleaning, provide a fallback
            if reply.get("type") == "text" and not reply.get("content", "").strip():
                msg_lower = user_message.lower()
                if any(word in msg_lower for word in ["restaurant", "menu", "dining", "chef", "food", "eat", "meal", "wine", "bar", "cocktail"]):
                    reply["content"] = (
                        f"We have the Adora Pop Up Restaurant right here at the hotel! "
                        f"Creative Slovenian cuisine by Chef Domen Demšar, served on the terrace with stunning lake views. "
                        f"Tasting menu ~€65/person, wine pairing ~€35/person. "
                        f"Reservations: +386 40 558 158. Would you like to book a table?"
                    )
                else:
                    reply["content"] = (
                        f"Villa Adora Bled is a luxury boutique hotel on Lake Bled. "
                        f"We have 8 unique suites with lake views, a pop-up restaurant, free parking and WiFi. "
                        f"What would you like to know more about?"
                    )

        # Merge consecutive text replies into one to avoid duplicate/fragmented responses
        merged_replies = []
        for reply in replies:
            if reply.get("type") == "text" and merged_replies and merged_replies[-1].get("type") == "text":
                merged_replies[-1]["content"] += "\n\n" + reply["content"]
            else:
                merged_replies.append(reply)
        replies = merged_replies

        return jsonify({"replies": replies})
    except Exception as e:
        import traceback
        traceback.print_exc()
        error_messages = {
            "English": "I'm sorry, I'm having trouble connecting right now. Please try again in a moment, or call us at +386 51 603 858. Is there anything else I can help with?",
            "Slovenian": "Oprostim, trenutno imam težave s povezavo. Poskusite znova ali pokličite na +386 51 603 858. Vas še kaj zanima?",
            "German": "Es tut mir leid, ich habe momentan Verbindungsversuche. Bitte versuchen Sie es erneut oder rufen Sie uns an unter +386 51 603 858. Kann ich Ihnen noch mit etwas helfen?",
            "French": "Je suis désolé, j'ai des difficultés à me connecter. Veuillez réessayer ou appelez-nous au +386 51 603 858. Y a-t-il autre chose que je puisse faire pour vous ?",
            "Italian": "Mi dispiace, ho problemi di connessione. Riprova o chiamaci al +386 51 603 858. C'è altro con cui posso aiutarti?",
            "Spanish": "Lo siento, tengo problemas de conexión. Inténtalo de nuevo o llama al +386 51 603 858. ¿Hay algo más en lo que pueda ayudarte?",
            "Croatian": "Oprostite, trenutno imam problema s vezom. Pokušajte ponovno ili nas nazovite na +386 51 603 858. Imam li vam još nešto pomoći?",
            "Serbian": "Oprostite, trenutno imam problema s vezom. Pokušajte ponovno ili nas nazovite na +386 51 603 858. Imam li vam još nešto pomoći?",
        }
        return jsonify({"replies": [{"type": "text", "content": error_messages.get(detected_lang, error_messages["English"])}]}), 200


@app.route("/api/confirm", methods=["POST"])
def api_confirm():
    data = request.json
    session_id = data.get("session_id", "default")
    confirmed = data.get("confirmed", False)
    messages = sessions.get(session_id, [])
    for i in range(len(messages) - 1, -1, -1):
        item = messages[i]
        if not isinstance(item, dict):
            continue
        if item.get("role") == "system" and "BOOKING_PENDING" in item.get("content", ""):
            try:
                pending = json.loads(item.get("content", "").split(":", 1)[1].strip())
            except Exception:
                pending = {}
            if not pending:
                return jsonify({"reply": {"type": "text", "content": "No pending booking."}})
            if confirmed:
                add_booking(
                    pending.get("guest_name", ""),
                    pending.get("room_name", ""),
                    pending.get("check_in", ""),
                    pending.get("check_out", ""),
                )
                response = (
                    f"✅ Confirmed for {pending.get('guest_name', 'guest')}!"
                    f" Welcome to {hotel_info['name']}."
                    f" Is there anything else I can help you with?"
                )
            else:
                response = "❌ Canceled. Is there anything else I can help you with?"
            messages.pop(i)
            sessions[session_id] = messages
            return jsonify({"reply": {"type": "text", "content": response}})
    return jsonify({"reply": {"type": "text", "content": "No pending booking."}})


@app.route("/api/bookings", methods=["GET"])
def api_bookings():
    conn = sqlite3.connect("hotel.db")
    c = conn.cursor()
    c.execute("SELECT * FROM bookings ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return jsonify(
        {
            "bookings": [
                {
                    "id": r[0],
                    "guest": r[1],
                    "room": r[2],
                    "check_in": r[3],
                    "check_out": r[4],
                }
                for r in rows
            ]
        }
    )


@app.route("/api/health")
def api_health():
    """Health check endpoint."""
    from datetime import datetime as _dt
    return jsonify({
        "status": "healthy",
        "hotel": hotel_info["name"],
        "timestamp": _dt.utcnow().isoformat(),
    })


@app.route("/api/suites")
def api_suites():
    """Return suite/room information."""
    from datetime import datetime
    suites = []
    for key, room in hotel_info.get("rooms", {}).items():
        suites.append({
            "id": key,
            "name": room.get("name", key),
            "price": room.get("price"),
            "currency": room.get("currency", "EUR"),
            "size_sqm": room.get("size_sqm"),
            "capacity": room.get("capacity"),
            "bed": room.get("bed"),
            "view": room.get("view"),
            "features": room.get("features", []),
            "description": room.get("description", ""),
        })
    return jsonify({"suites": suites, "count": len(suites)})


@app.route("/api/info")
def api_info():
    """Return general hotel information."""
    return jsonify({
        "name": hotel_info.get("name"),
        "tagline": hotel_info.get("tagline"),
        "built": hotel_info.get("built"),
        "heritage": hotel_info.get("heritage"),
        "location": hotel_info.get("location"),
        "amenities": hotel_info.get("amenities", []),
    })


@app.route("/admin")
def admin():
    return render_template("admin.html", hotel_name=hotel_info["name"])


@app.route("/static/images/<path:filename>")
def serve_images(filename):
    import os
    from flask import send_from_directory
    image_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "images")
    return send_from_directory(image_dir, filename)


@app.route("/api/calendar", methods=["GET"])
def api_calendar():
    events = get_all_calendar_events()
    return jsonify({
        "events": [
            {
                "id": e[0],
                "session_id": e[1],
                "event_type": e[2],
                "guest_name": e[3],
                "time": e[4],
                "date": e[5],
                "notes": e[6],
                "created_at": e[7],
            }
            for e in events
        ]
    })


@app.route("/api/shuttles", methods=["GET"])
def api_shuttles():
    conn = sqlite3.connect("hotel.db")
    c = conn.cursor()
    c.execute("SELECT * FROM shuttle_bookings ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return jsonify({
        "shuttles": [
            {
                "id": r[0],
                "session_id": r[1],
                "guest_name": r[2],
                "pickup_location": r[3],
                "dropoff_location": r[4],
                "date": r[5],
                "time": r[6],
                "passengers": r[7],
                "notes": r[8],
                "created_at": r[9],
            }
            for r in rows
        ]
    })


@app.route("/api/human-requests", methods=["GET"])
def api_human_requests():
    conn = sqlite3.connect("hotel.db")
    c = conn.cursor()
    c.execute("SELECT * FROM human_agent_requests ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return jsonify({
        "requests": [
            {
                "id": r[0],
                "session_id": r[1],
                "reason": r[2],
                "guest_name": r[3],
                "summary": r[4],
                "created_at": r[5],
            }
            for r in rows
        ]
    })


@app.route("/api/export")
def api_export():
    import csv
    import io
    from datetime import datetime as _dt

    export_type = request.args.get("type", "bookings").lower()
    conn = sqlite3.connect("hotel.db")
    c = conn.cursor()

    exports = {
        "bookings": ("SELECT id, guest_name, room_name, check_in, check_out FROM bookings ORDER BY id DESC", ["id", "guest_name", "room_name", "check_in", "check_out"]),
        "calendar": ("SELECT id, session_id, event_type, guest_name, time, date, notes, created_at FROM calendar_events ORDER BY id DESC", ["id", "session_id", "event_type", "guest_name", "time", "date", "notes", "created_at"]),
        "shuttles": ("SELECT id, session_id, guest_name, pickup_location, dropoff_location, date, time, passengers, notes, created_at FROM shuttle_bookings ORDER BY id DESC", ["id", "session_id", "guest_name", "pickup_location", "dropoff_location", "date", "time", "passengers", "notes", "created_at"]),
        "human": ("SELECT id, session_id, reason, guest_name, summary, created_at FROM human_agent_requests ORDER BY id DESC", ["id", "session_id", "reason", "guest_name", "summary", "created_at"]),
    }

    if export_type not in exports:
        conn.close()
        return jsonify({"error": "Invalid export type"}), 400

    query, headers = exports[export_type]
    c.execute(query)
    rows = c.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers)
    writer.writeheader()
    for row in rows:
        writer.writerow(dict(zip(headers, row)))

    filename = f"villa-adora-{export_type}-{_dt.utcnow().strftime('%Y%m%d-%H%M%S')}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5173))
    print(f"🏔️  {hotel_info['name']} — Fast Mode")
    print(f"📍 http://localhost:{port} | 📊 /admin")
    app.run(host="0.0.0.0", port=port, debug=True, threaded=True)

import os
import subprocess
import json
import re
from openai import OpenAI
from database import add_booking, init_db, add_calendar_event, get_all_calendar_events
from hotel_data import hotel_info
import sqlite3
from flask import Flask, render_template, request, jsonify
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
                        "shuttle", "room_service",
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
        "Imamo 7 čudovitih apartmajev, vsi s čudovitim razgledom na jezero:\n"
        "• Princesin apartmaj, 55 m², za 2 osebi — Razgled na jezero iz stolpa, dnevna soba\n"
        "• Luksuzni apartmaj, za 2 osebi — Razgled na jezero, elegantna dekoracija\n"
        "• Penthouse apartmaj, 60 m², za 2 osebi — 2 nadstropji, king-size postelja\n"
        "• Labodji apartmaj, za 2 osebi — Razgled na jezero, luksuzna oprema\n"
        "• Otoški apartmaj, 65 m², za 4 osebi — 2 luksuzni spalnici, 2 balkona\n"
        "• Prestižni apartmaj, 72 m², za 2 osebi — Pritličje, pogled na jezero\n"
        "• Grajski apartmaj, za 2 osebi — Elegantna suita, pogled na grad\n"
        "Kateri vas najbolj pritegne? Lahko začnem z rezervacijo — samo povejte mi vaše ime in datume!"
    ),
    "German": (
        "Wir haben 7 wundersch\u00f6ne Suiten mit atemberaubendem Seeblick:\n"
        "\u2022 Prinzessin Suite, 55 m\u00b2, f\u00fcr 2 G\u00e4ste \u2014 Seeblick vom Turm, Wohnbereich\n"
        "\u2022 Luxus Suite, f\u00fcr 2 G\u00e4ste \u2014 Seeblick, elegante Einrichtung\n"
        "\u2022 Penthouse Suite, 60 m\u00b2, f\u00fcr 2 G\u00e4ste \u2014 2 Etagen, Kingsize-Bett\n"
        "\u2022 Schwanen Suite, f\u00fcr 2 G\u00e4ste \u2014 Seeblick, luxuri\u00f6se Ausstattung\n"
        "\u2022 Insel Suite, 65 m\u00b2, f\u00fcr 4 G\u00e4ste \u2014 2 Luxusschlafzimmer, 2 Balkone\n"
        "\u2022 Prestige Suite, 72 m\u00b2, f\u00fcr 2 G\u00e4ste \u2014 Erdgeschoss, Seeblick\n"
        "\u2022 Burg Suite, f\u00fcr 2 G\u00e4ste \u2014 Stilvolle Luxussuite, Blick auf die Burg\n"
        "Welche Suite gef\u00e4llt Ihnen am besten? Ich starte gerne eine Buchung \u2014 ich brauche nur Ihren Namen und Ihre Reisedaten!"
    ),
    "French": (
        "Nous avons 7 magnifiques suites avec vue imprenable sur le lac:\n"
        "\u2022 Suite Princesse, 55 m\u00b2, pour 2 personnes \u2014 Vue sur le lac depuis la tour, salon\n"
        "\u2022 Suite de Luxe, pour 2 personnes \u2014 Vue sur le lac, d\u00e9coration \u00e9l\u00e9gante\n"
        "\u2022 Suite Penthouse, 60 m\u00b2, pour 2 personnes \u2014 2 \u00e9tages, lit king-size\n"
        "\u2022 Suite Cygne, pour 2 personnes \u2014 Vue sur le lac, mobilier de luxe\n"
        "\u2022 Suite \u00cele, 65 m\u00b2, pour 4 personnes \u2014 2 chambres de luxe, 2 balcons\n"
        "\u2022 Suite Prestige, 72 m\u00b2, pour 2 personnes \u2014 Rez-de-chauss\u00e9e, salon\n"
        "\u2022 Suite Ch\u00e2teau, pour 2 personnes \u2014 Suite de luxe \u00e9l\u00e9gante, vue sur le ch\u00e2teau\n"
        "Laquelle vous pla\u00eet le plus ? Je peux r\u00e9server pour vous \u2014 j'ai besoin de votre nom et de vos dates!"
    ),
    "Italian": (
        "Abbiamo 7 splendide suite con vista mozzafiato sul lago:\n"
        "\u2022 Suite Principessa, 55 m\u00b2, per 2 persone \u2014 Vista lago dalla torre, zona living\n"
        "\u2022 Suite Luxury, per 2 persone \u2014 Vista lago, arredi eleganti\n"
        "\u2022 Suite Penthouse, 60 m\u00b2, per 2 persone \u2014 2 piani, letto king size\n"
        "\u2022 Suite Cigno, per 2 persone \u2014 Vista lago, arredi di lusso\n"
        "\u2022 Suite Isola, 65 m\u00b2, per 4 persone \u2014 2 camere da letto di lusso, 2 balconi\n"
        "\u2022 Suite Prestige, 72 m\u00b2, per 2 persone \u2014 Piano terra, vista lago\n"
        "\u2022 Suite Castello, per 2 persone \u2014 Suite di lusso elegante, vista sul castello\n"
        "Quale ti piace di pi\u00f9? Posso prenotare per te \u2014 mi servono solo nome e date!"
    ),
    "Spanish": (
        "Tenemos 7 hermosas suites con vistas impresionantes al lago:\n"
        "\u2022 Suite Princesa, 55 m\u00b2, para 2 personas \u2014 Vista al lago desde la torre, zona de estar\n"
        "\u2022 Suite de Lujo, para 2 personas \u2014 Vista al lago, decoraci\u00f3n elegante\n"
        "\u2022 Suite Penthouse, 60 m\u00b2, para 2 personas \u2014 2 pisos, cama king size\n"
        "\u2022 Suite Cisne, para 2 personas \u2014 Vista al lago, mobiliario de lujo\n"
        "\u2022 Suite Isla, 65 m\u00b2, para 4 personas \u2014 2 habitaciones de lujo, 2 balcones\n"
        "\u2022 Suite Prestige, 72 m\u00b2, para 2 personas \u2014 Planta baja, vista al lago\n"
        "\u2022 Suite Castillo, para 2 personas \u2014 Suite de lujo elegante, vistas al castillo\n"
        "\u00bfCu\u00e1l te gusta m\u00e1s? Puedo hacer la reserva \u2014 solo necesito tu nombre y las fechas!"
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
        "Katero aktivnost vas najbolj zanima? Z veseljem vam jo pomagam organizirati!"
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
        "\u2022 Paseo a la Isla de Bled y visita de la iglesia\n"
        "\u2022 Nataci\u00f3n, paddle, kayak y excursiones\n"
        "\u2022 Gargantas de Vintgar (2,4 km)\n"
        "\u2022 Castillo de Bled (30 min a pie)\n"
        "\u2022 Sendero de 6 km y 15 senderos\n"
        "\u2022 Excursiones a Bohinj, Ljubljana, cueva de Postojna\n"
        "\u2022 Masaje en habitaci\u00f3n, noches con vino\n"
        "\u00bfCu\u00e1l te interesa m\u00e1s? \u00a1Estar\u00e9 encantado de ayudarte!"
    ),
}
_RESTAURANT_TRANSLATED = {
    "Slovenian": (
        "Imamo restavracijo Adora Pop Up kar v hotelu! Ekskluzivna restavracija z ustvarjalno kuhinjo "
        "z lokalnimi slovenskimi sestavinami pod vodstvom \u0161efa kuhinje Domena Dem\u0161ara. "
        "Terasa ima ene najlep\u0161ih razgledov na jezero. "
        "Odprto: Kosilo in ve\u010derja torek\u2013nedelja, brunk \u010detrtek\u2013sobota. "
        "Rezervacija: +386 40 558 158 / +386 51 603 858 ali evita.vilebled@gmail.com. "
        "\u017delite rezervirati mizo?"
    ),
    "German": (
        "Wir haben das Adora Pop Up Restaurant direkt im Hotel! Exklusives kulinarisches Erlebnis "
        "mit kreativer, lokal inspirierter slowenischer K\u00fcche unter der Leitung von K\u00fcchenchef Domen Dem\u0161ar. "
        "Die Terrasse bietet atemberaubende Sonnenuntergangsaussichten \u00fcber Bled. "
        "Ge\u00f6ffnet: Mittagessen & Abendessen Dienstag\u2013Sonntag, Brunch Donnerstag\u2013Samstag. "
        "Reservierung: +386 40 558 158 / +386 51 603 858 oder evita.vilebled@gmail.com. "
        "M\u00f6chten Sie eine Reservierung vornehmen?"
    ),
    "French": (
        "Nous avons le restaurant Adora Pop Up directement \u00e0 l'h\u00f4tel! Exp\u00e9rience culinaire exclusive "
        "avec une cuisine cr\u00e9ative d'inspiration slov\u00e8ne locale, sous la direction du chef Domen Dem\u0161ar. "
        "La terrasse offre des couchers de soleil \u00e0 couper le souffle sur Bled. "
        "Ouvert: D\u00e9jeuner et d\u00eener du mardi au dimanche, brunch du jeudi au samedi. "
        "R\u00e9servation: +386 40 558 158 / +386 51 603 858 ou evita.vilebled@gmail.com. "
        "Souhaitez-vous r\u00e9server une table ?"
    ),
    "Italian": (
        "Abbiamo il ristorante Adora Pop Up direttamente in hotel! Esperienza culinaria esclusiva "
        "con cucina creativa di ispirazione slovena locale, sotto la guida dello chef Domen Dem\u0161ar. "
        "La terrazza offre tramonti mozzafiato su Bled. "
        "Aperto: Pranzo e cena da marted\u00ec a domenica, brunch da gioved\u00ec a sabato. "
        "Prenotazione: +386 40 558 158 / +386 51 603 858 o evita.vilebled@gmail.com. "
        "Vuoi riservare un tavolo?"
    ),
    "Spanish": (
        "\u00a1Tenemos el restaurante Adora Pop Up directamente en el hotel! Experiencia culinaria exclusiva "
        "con cocina creativa de inspiraci\u00f3n eslovena local, bajo la direcci\u00f3n del chef Domen Dem\u0161ar. "
        "La terrazza ofrece atardeceres impresionantes sobre Bled. "
        "Abierto: Almuerzo y cena de martes a domingo, brunch de jueves a s\u00e1bado. "
        "Reserva: +386 40 558 158 / +386 51 603 858 o evita.vilebled@gmail.com. "
        "\u00bfTe gustar\u00eda reservar una mesa?"
    ),
}

_LOCATION_TRANSLATED = {
    "Slovenian": (
        "Villa Adora je na Cesti svobode 35, 4260 Bled, Slovenija, neposredno na obali jezera Bled \u2014 "
        "med redkimi hoteli na tako odli\u010dni lokaciji. Pogledi na Bledski otok, Blejski grad in gore Triglava. "
        "2 minuti hoje do pristani\u0161\u010da za \u010dolne, 15 minut do sredi\u0161\u010da Bleda, 30 minut do Blejskega gradu. "
        "Telefon: +386 51 603 858. \u017delite navodila za pot do nas ali nasvete za prihod?"
    ),
    "German": (
        "Villa Adora befindet sich an der Cesta svobode 35, 4260 Bled, Slowenien, direkt am Ufer des Bleder Sees \u2014 "
        "einer der wenigen Hotels mit dieser erstklassigen Lage. Blick auf die Bled-Insel, die Bleder Burg und die Triglav-Berge. "
        "2 Minuten zu Fu\u00df zur Bootsanlegestelle, 15 Minuten zum Stadtzentrum von Bled, 30 Minuten zur Bleder Burg. "
        "Telefon: +386 51 603 858. M\u00f6chten Sie eine Wegbeschreibung oder Tipps f\u00fcr die Anreise?"
    ),
    "French": (
        "Villa Adora se trouve au Cesta svobode 35, 4260 Bled, Slov\u00e9nie, directement au bord du lac de Bled \u2014 "
        "l'un des rares h\u00f4tels avec cet emplacement privil\u00e9gi\u00e9. Vue sur l'\u00eele de Bled, le ch\u00e2teau de Bled et les montagnes du Triglav. "
        "2 minutes \u00e0 pied de la station de bateaux, 15 minutes du centre-ville de Bled, 30 minutes du ch\u00e2teau de Bled. "
        "T\u00e9l\u00e9phone: +386 51 603 858. Souhaitez-vous des indications ou des conseils pour venir ?"
    ),
    "Italian": (
        "Villa Adora si trova in Cesta svobode 35, 4260 Bled, Slovenia, direttamente sulle rive del lago di Bled \u2014 "
        "uno dei pochi hotel con questa posizione privilegiata. Vista sull'Isola di Bled, il Castello di Bled e le montagne del Triglav. "
        "2 minuti a piedi dalla stazione dei battelli, 15 minuti dal centro di Bled, 30 minuti dal Castello di Bled. "
        "Telefono: +386 51 603 858. Vuoi indicazioni o suggerimenti per raggiungerci?"
    ),
    "Spanish": (
        "Villa Adora se encuentra en Cesta svobode 35, 4260 Bled, Eslovenia, directamente a orillas del lago de Bled \u2014 "
        "uno de los pocos hoteles con esta ubicaci\u00f3n privilegiada. Vistas a la Isla de Bled, el Castillo de Bled y las monta\u00f1as del Triglav. "
        "2 minutos a pie de la estaci\u00f3n de botes, 15 minutos del centro de Bled, 30 minutos del Castillo de Bled. "
        "Tel\u00e9fono: +386 51 603 858. \u00bfTe gustar\u00eda recibir indicaciones o consejos para llegar?"
    ),
}

_BREAKFAST_TRANSLATED = {
    "Slovenian": ("Zajtrk je na voljo za 22 \u20ac na osebo, postre\u017een med 8. in 10. uro. Sve\u017ee pecivo, kruh in lokalni slovenski izdelki. Nudimo tudi veganske, vegetarijanske in brezglutenske mo\u017enosti na zahtevo. Ali \u017eelite dodati zajtrk k va\u0161i rezervaciji?"),
    "German": ("Fr\u00fchst\u00fcck ist f\u00fcr 22 \u20ac pro Person verf\u00fcgbar, serviert von 8-10 Uhr. Frische Geb\u00e4ck, Brot und lokale slowenische Produkte. Wir bieten auch vegane, veget\u00e4re und glutenfreie Optionen auf Anfrage. M\u00f6chten Sie Fr\u00fchst\u00fcck zu Ihrer Buchung hinzuf\u00fcgen?"),
    "French": ("Le petit-d\u00e9jeuner est disponible pour 22 \u20ac par personne, servi de 8h \u00e0 10h. P\u00e2tisseries fra\u00eeches, pain et produits locaux slov\u00e8nes. Nous proposons \u00e9galement des options v\u00e9g\u00e9taliennes, v\u00e9g\u00e9tariennes et sans gluten sur demande. Souhaitez-vous ajouter le petit-d\u00e9jeuner \u00e0 votre r\u00e9servation ?"),
    "Italian": ("La colazione \u00e8 disponibile a 22 \u20ac a persona, servita dalle 8 alle 10. Pasticceria fresca, pane e prodotti locali sloveni. Offriamo anche opzioni vegane, vegetariane e senza glutine su richiesta. Vuoi aggiungere la colazione alla tua prenotazione?"),
    "Spanish": ("El desayuno est\u00e1 disponible por 22 \u20ac por persona, servido de 8 a 10 AM. Pasteles frescos, pan y productos locales eslovenos. Tambi\u00e9n ofrecemos opciones veganas, vegetarianas y sin gluten bajo pedido. \u00bfTe gustar\u00eda agregar el desayuno a tu reserva?"),
}

_PARKING_TRANSLATED = {
    "Slovenian": ("Imamo brezpla\u010dno parkiri\u0161\u010de \u2014 8 parkirnih mest pred hotelom. Boste vozili v Bled ali \u017eelite nasvete za javni prevoz?"),
    "German": ("Wir bieten kostenlosen privaten Parkplatz an \u2014 8 Parkpl\u00e4tze direkt vor dem Hotel. Kommen Sie mit dem Auto nach Bred, oder ben\u00f6tigen Sie Tipps f\u00fcr den \u00f6ffentlichen Nahverkehr?"),
    "French": ("Nous offrons un parking priv\u00e9 gratuit \u2014 8 places de parking devant l'h\u00f4tel. Venez-vous \u00e0 Bled en voiture, ou souhaitez-vous des conseils sur les transports en commun ?"),
    "Italian": ("Offriamo parcheggio privato gratuito \u2014 8 posti auto davanti all'hotel. Verrai a Bled in auto, o vuoi suggerimenti sui trasporti pubblici?"),
    "Spanish": ("Ofrecemos estacionamiento privado gratuito \u2014 8 espacios de estacionamiento frente al hotel. \u00bfVas a venir a Bled en coche, o te gustar\u00eda recibir consejos sobre transporte p\u00fablico?"),
}

_PETS_TRANSLATED = {
    "Slovenian": ("Hi\u0161ne \u017eivali so dobrolepo dobrodo\u0161le na zahtevo \u2014 35 \u20ac na \u017eival na no\u010d. Ali na\u010drtujete, da boste pripeljali krznenega prijatelja?"),
    "German": ("Haustiere sind auf Anfrage willkommen \u2014 35 \u20ac pro Tier pro Nacht. Planen Sie, ein pelziges Mitglied mitzubringen?"),
    "French": ("Les animaux de compagnie sont accept\u00e9s sur demande \u2014 35 \u20ac par animal et par nuit. Pr\u00e9voyez-vous d'amener un ami \u00e0 quatre pattes ?"),
    "Italian": ("Gli animali domestici sono benvenuti su richiesta \u2014 35 \u20ac per animale a notte. Hai intenzione di portare un amico a quattro zampe?"),
    "Spanish": ("Las mascotas son bienvenidas bajo petici\u00f3n \u2014 35 \u20ac por mascota por noche. \u00bfPlaneas traer a un amigo peludo?"),
}

_CHECKIN_TRANSLATED = {
    "Slovenian": ("Prijava je od 14:00 do 23:00, odjava do 11:00. Pozna prijava/odjava je na voljo na zahtevo. Ob kateri uri na\u010drtujete prihod?"),
    "German": ("Check-in ist von 14:00 bis 23:00, Check-out bis 11:00. Sp\u00e4ter Check-in/Check-out ist auf Anfrage m\u00f6glich. Um welche Uhrzeit planen Sie Ihre Ankunft?"),
    "French": ("L'enregistrement est de 14h00 \u00e0 23h00, le d\u00e9part \u00e0 11h00. L'enregistrement/d\u00e9part tardif est possible sur demande. \u00c0 quelle heure pr\u00e9voyez-vous d'arriver ?"),
    "Italian": ("Il check-in \u00e8 dalle 14:00 alle 23:00, il check-out fino alle 11:00. Check-in/check-out tardivo \u00e8 disponibile su richiesta. A che ora prevedi di arrivare?"),
    "Spanish": ("El check-in es de 14:00 a 23:00, el check-out hasta las 11:00. Check-in/check-out tard\u00edo est\u00e1 disponible bajo petici\u00f3n. \u00bfA qu\u00e9 hora planeas llegar?"),
}

_WINE_TRANSLATED = {
    "Slovenian": ("Na\u0161a vinska karta vsebuje najbolj\u0161a slovenska vina iz okolice Bleda, izbrana na\u0161im strokovnjakom, skupaj z mednarodnimi oznakami. Vinarno z degustacijskim menijem je na voljo (pribli\u017eno 35 \u20ac na osebo). \u017delite rezervirati mizo?"),
    "German": ("Unsere Weinkarte bietet die besten slowenische Weine aus der N\u00e4he von Bred sowie ausgew\u00e4hlte internationale Etiketten, kuratiert von unserem Hausesommelier. Weinbegleitung zum Degustationsmen\u00fc verf\u00fcgbar (ca. 35 \u20ac pro Person). M\u00f6chten Sie einen Tisch reservieren?"),
    "French": ("Notre carte des vins propose les meilleurs vins slov\u00e8nes pr\u00e8s de Bred ainsi que des labels internationaux s\u00e9lectionn\u00e9s, \u00e9labor\u00e9e par notre sommelier interne. Accord mets et vins disponible avec le menu d\u00e9gustation (environ 35 \u20ac par personne). Souhaitez-vous r\u00e9server une table ?"),
    "Italian": ("La nostra lista dei vini include i migliori vini sloveni vicino a Bred e etichette internazionali selezionate, curata dal nostro sommelier interno. Abbinamento vini disponibile con il menu degustazione (circa 35 \u20ac a persona). Vuoi riservare un tavolo?"),
    "Spanish": ("Nuestra lista de vinos ofrece los mejores vinos eslovenos cerca de Bred y etiquetas internacionales seleccionadas, curada por nuestro sumiller interno. Maridaje de vinos disponible con el men\u00fa degustaci\u00f3n (aproximadamente 35 \u20ac por persona). \u00bfTe gustar\u00eda reservar una mesa?"),
}

_BAR_TRANSLATED = {
    "Slovenian": ("Na\u0161 bar stre\u017ee elegantne koktaje in aperitive vsak dan na terasi s panoramskim razgledom na jezero. Popoln kraj za son\u010dne ve\u010dere! \u017delite ve\u010d informacij o na\u0161em jedilniku pija\u010d?"),
    "German": ("Unsere Bar serviert elegante Cocktails und Aperitivos t\u00e4glich auf der Terrasse mit Panoramablick auf den See. Der perfekte Ort f\u00fcr Drinks bei Sonnenuntergang! M\u00f6chten Sie mehr \u00fcber unsere Getr\u00e4nkekarte erfahren?"),
    "French": ("Notre bar sert des cocktails \u00e9l\u00e9gants et des ap\u00e9ritifs quotidiennement sur la terrasse avec vue panoramique sur le lac. L'endroit parfait pour les couchers de soleil ! Souhaitez-vous en savoir plus sur notre carte de boissons ?"),
    "Italian": ("Il nostro bar serve cocktail eleganti e aperitivi quotidianamente sulla terrazza con vista panoramica sul lago. Il posto perfetto per i tramonti! Vuoi saperne di pi\u00f9 sul nostro menu delle bevande?"),
    "Spanish": ("Nuestro bar sirve c\u00f3cteles elegantes y aperitivos diariamente en la terrazca con vistas panor\u00e1micas al lago. \u00a1El lugar perfecto para los atardeceres! \u00bfTe gustar\u00eda saber m\u00e1s sobre nuestra carta de bebidas?"),
}

_SHUTTLE_TRANSLATED = {
    "Slovenian": ("Nudimo prevoz z letali\u0161\u010da, lokalni prevoz in poti po meri! Priljubljene poti: Letali\u0161\u010de Ljubljana (~60 \u20ac), sredi\u0161\u010de Bleda (~15 \u20ac). Za rezervacijo mi povejte ime, kje vas prevzeti, datum in uro. Kje bi radi, da vas prevzamemo?"),
    "German": ("Wir bieten Flughafentransfers, lokale Transfers und individuelle Routen! Beliebte Routen: Flughafen Ljubljana (~60 \u20ac), Bled Stadtzentrum (~15 \u20ac). Zur Buchung ben\u00f6tige ich Ihren Namen, den Abholort, Datum und Uhrzeit. Wo m\u00f6chten Sie abgeholt werden?"),
    "French": ("Nous proposons des transferts a\u00e9roport, des transports locaux et des itin\u00e9raires personnalis\u00e9s ! Itin\u00e9raires populaires: A\u00e9roport de Ljubljana (~60 \u20ac), centre-ville de Bled (~15 \u20ac). Pour r\u00e9server, dites-moi votre nom, le lieu de prise en charge, la date et l'heure. O\u00f9 souhaitez-vous \u00eatre pris en charge ?"),
    "Italian": ("Offriamo trasferimenti aeroportuali, trasporti locali e percorsi personalizzati! Percorsi popolari: Aeroporto di Lubiana (~60 \u20ac), centro di Bled (~15 \u20ac). Per prenotare, dimmi il tuo nome, il luogo di ritiro, la data e l'ora. Dove vuoi essere ritirato?"),
    "Spanish": ("Ofrecemos traslados al aeropuerto, transporte local y rutas personalizadas. Rutas populares: Aeropuerto de Ljubljana (~60 \u20ac), centro de Bled (~15 \u20ac). Para reservar, dime tu nombre, lugar de recogida, fecha y hora. \u00bfD\u00f3nde te gustar\u00eda que te recojamos?"),
}


def _get_localized_fallback(lang: str, user_message: str) -> str:
    """Return a localized fallback response when the LLM responds in English for non-English queries."""
    q = user_message.lower()
    # Detect topic for a more relevant fallback
    if any(w in q for w in ["room", "suite", "bed", "sleep", "sobe", "soba", "zimmer", "camere", "camera", "chambre", "habitaci", "cuarto", "apartma"]):
        fallbacks = {
            "Slovenian": "Imamo 7 čudovitih apartmajev z razgledom na jezero. Vsi imajo kopalnico, klimo, brezplačen WiFi in TV. Vas kateri vas zanima največ? Rad bi vam podal več podrokov!",
            "German": "Wir haben 7 wunderschöne Suiten mit Seeblick. Alle verfügen über eigenes Bad, Klimaanlage, kostenloses WLAN und TV. Welche Suite interessiert Sie am meisten? Ich kann Ihnen gerne mehr davon erzählen!",
            "French": "Nous avons 7 magnifiques suites avec vue sur le lac. Toutes disposent d'une salle de bain privée, de la climatisation, du WiFi gratuit et de la télévision. Laquelle vous intéresse le plus? Je peux vous en dire plus!",
            "Italian": "Abbiamo 7 splendide suite con vista sul lago. Tutte dispongono di bagno privato, aria condizionata, WiFi gratuito e TV. Quale suite ti interessa di più? Posso darti maggiori dettagli!",
            "Spanish": "Tenemos 7 hermosas suites con vistas al lago. Todas cuentan con baño privado, aire acondicionado, WiFi gratis y TV. ¿Cuál te llama más la atención? ¡Puedo darte más detalles!",
            "Croatian": "Imamo 7 prekrasnih apartmana s pogledom na jezero. Svi imaju vlastitu klimu, besplatni WiFi i TV. Koji vas najviše zanima? Mogu vam dati više detalja!",
        }
    elif any(w in q for w in ["breakfast", "morning", "brunch", "zajtrk", "frühstück", "colazione", "petit déjeuner", "desayuno", "vegan", "vegetarian", "gluten", "allergy", "allergies", "dietary", "diet", "restriction", "celiac", "lactose", "intolerant", "vegansko", "vegetarijansko", "brezglutensko", "alergija", "prehrana"]):
        fallbacks = {
            "Slovenian": "Zajtrk je na voljo za 22 € na osebo, postrežen med 8. in 10. uro. Nudimo tudi veganska, vegetarijanska in brezglutenska jed. Želite dodati zajtrk k vaši rezervaciji?",
            "German": "Frühstück ist für 22 € pro Person verfügbar, serviert von 8-10 Uhr. Wir bieten auch vegane, vegetäre und glutenfreie Optionen. Möchten Sie Frühstück zu Ihrer Buchung hinzufügen?",
            "French": "Le petit-déjeuner est disponible pour 22 € par personne, servi de 8h à 10h. Nous proposons également des options végétaliennes, végétariennes et sans gluten. Souhaitez-vous ajouter le petit-déjeuner à votre réservation?",
            "Italian": "La colazione è disponibile a 22 € a persona, servita dalle 8 alle 10. Offriamo anche opzioni vegane, vegetariane e senza glutine. Vuoi aggiungere la colazione alla tua prenotazione?",
            "Spanish": "El desayuno está disponible por 22 € por persona, servido de 8 a 10 AM. También ofrecemos opciones veganas, vegetarianas y sin gluten. ¿Te gustaría agregar el desayuno a tu reserva?",
            "Croatian": "Doručak je dostupan za 22 € po osobi, poslužuje se od 8 do 10 sati. Nudimo i veganska, vegetarijanska i bezglutenska jela. Želite li dodati doručak u rezervaciju?",
        }
    elif any(w in q for w in ["restaurant", "dining", "dinner", "lunch", "menu", "chef", "food", "eat", "meal", "ristorante", "restaurante", "speise", "essen", "cucina", "manger", "nourriture"]):
        fallbacks = {
            "Slovenian": "Imamo restavracijo Adora Pop Up kar v hotelu! Ustvarjena kuhinja z lokalnimi slovenskimi sestavinami pod vodstvom šefa kuhinje Domena Demšara. Terasa ima ene najlepših razgledov na jezero. Rezervacija: +386 40 558 158. Želite rezervirati mizo?",
            "German": "Wir haben das Adora Pop Up Restaurant direkt im Hotel! Kreative Küche mit lokalen slowenischen Zutaten unter der Leitung von Küchenchef Domen Demšar. Die Terrasse bietet einen der besten Ausblicke auf den See. Reservierung: +386 40 558 158. Möchten Sie einen Tisch reservieren?",
            "French": "Nous avons le restaurant Adora Pop Up directement à l'hôtel! Cuisine créative avec des ingrédients slovènes locaux sous la direction du chef Domen Demšar. La terrasse offre l'une des meilleures vues sur le lac. Réservation: +386 40 558 158. Souhaitez-vous réserver une table?",
            "Italian": "Abbiamo il ristorante Adora Pop Up direttamente in hotel! Cucina creativa con ingredienti sloveni locali sotto la guida dello chef Domen Demšar. La terrazza offre una delle migliori viste sul lago. Prenotazione: +386 40 558 158. Vuoi riservare un tavolo?",
            "Spanish": "¡Tenemos el restaurante Adora Pop Up directamente en el hotel! Cocina creativa con ingredientes eslovenos locales bajo la dirección del chef Domen Demšar. La terraza ofrece una de las mejores vistas al lago. Reserva: +386 40 558 158. ¿Te gustaría reservar una mesa?",
            "Croatian": "Imamo restoran Adora Pop Up izravno u hotelu! Kreativna kuhinja s lokalnim slovenskim sastojcima pod vodstvom šefa kuhinje Domena Demšara. Terasa nudi jedan od najboljih pogleda na jezero. Rezervacija: +386 40 558 158. Želite li rezervirati stol?",
        }
    else:
        fallbacks = {
            "Slovenian": "Villa Adora Bled je butični hotel ob jezeru Bled. Imamo 7 edinstvenih apartmajev z razgledom na jezero, restavracijo, brezplačno parkiranje in WiFi. Kaj vas zanima? Z veseljem vam pomagam!",
            "German": "Villa Adora Bled ist ein Boutique-Hotel am See Bled. Wir haben 7 einzigartige Suiten mit Seeblick, ein Restaurant, kostenloses Parken und WLAN. Was möchten Sie wissen? Ich helfe Ihnen gerne!",
            "French": "Villa Adora Bled est un hôtel de charme au lac Bled. Nous avons 7 suites uniques avec vue sur le lac, un restaurant, un parking gratuit et le WiFi. Que souhaitez-vous savoir? Je serai ravi de vous aider!",
            "Italian": "Villa Adora Bled è un boutique hotel sul lago di Bled. Abbiamo 7 suite uniche con vista sul lago, un ristorante, parcheggio gratuito e WiFi. Cosa vorresti sapere? Sarò felice di aiutarti!",
            "Spanish": "Villa Adora Bled es un hotel boutique en el lago Bled. Tenemos 7 suites únicas con vistas al lago, un restaurante, estacionamiento gratuito y WiFi. ¿Qué te gustaría saber? ¡Estaré encantado de ayudarte!",
            "Croatian": "Villa Adora Bled je butični hotel na jezeru Bled. Imamo 7 jedinstvenih apartmana s pogledom na jezero, restoran, besplatni parking i WiFi. Što vas zanima? Rado ću vam pomoći!",
        }
    return fallbacks.get(lang, fallbacks.get("Slovenian", "I'm here to help! What would you like to know about Villa Adora Bled?"))


def fix_spacing(text):
    """Fix common LLM spacing issues."""
    import re
    # Replace unicode whitespace variants with normal space (but NOT en-dash/em-dash which are used as separators)
    text = re.sub(r'[\u2000-\u200b\u202f\u205f\u00a0\u2011]', ' ', text)
    # Fix "WiFi" being split: "Wi Fi" -> "WiFi" (MUST run before the general uppercase split)
    text = re.sub(r'\bWi\s+Fi\b', 'WiFi', text, flags=re.IGNORECASE)
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
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    # Fix "WiFi" being split by the above rule: "Wi Fi" -> "WiFi" (MUST run after the general uppercase split)
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
    # Fix missing space before parentheses
    text = re.sub(r'([a-zA-Z])\(', r' \1 (', text)
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
    if "?" in text[-60:]:
        return text
    # Localized follow-up questions by topic and language
    questions = {
        "rooms": {
            "English": " Which one catches your eye? I can start a booking for you \u2014 just tell me your name and dates!",
            "Slovenian": " Kateri vas najbolj pritegne? Lahko za\u010dnem z rezervacijo \u2014 samo povejte mi va\u0161e ime in datume!",
            "German": " Welche Suite gef\u00e4llt Ihnen am besten? Ich kann gerne eine Buchung starten \u2014 ich brauche nur Ihren Namen und Ihre Reisedaten!",
            "French": " Laquelle vous pla\u00eet le plus ? Je peux r\u00e9server pour vous \u2014 j'ai besoin de votre nom et de vos dates !",
            "Italian": " Quale ti piace di pi\u00f9? Posso prenotare per te \u2014 mi servono solo nome e date!",
            "Spanish": "\u00bfCu\u00e1l te gusta m\u00e1s? Puedo hacer la reserva \u2014 solo necesito tu nombre y las fechas!",
            "Croatian": " Koji vas najvi\u0161e zanima? Mogu pokrenuti rezervaciju \u2014 samo mi recite va\u0161e ime i datume!",
        },
        "experiences": {
            "English": " Which of these sounds most appealing to you? I'd love to help you plan it!",
            "Slovenian": " Katero aktivnost vas najbolj zanima? Z veseljem vam jo pomagam organizirati!",
            "German": " Welche Aktivit\u00e4t interessiert Sie am meisten? Ich helfe gerne bei der Organisation!",
            "French": " Laquelle vous int\u00e9resse le plus ? Je serai ravi de vous aider \u00e0 l'organiser!",
            "Italian": " Quale ti interessa di pi\u00f9? Sar\u00e0 un piacere aiutarti!",
            "Spanish": "\u00bfCu\u00e1l te interesa m\u00e1s? \u00a1Estar\u00e9 encantado de ayudarte!",
            "Croatian": " Koja vas aktivnost najvi\u0161e zanima? Rado \u0107u vam pomo\u0107i s organizacijom!",
        },
        "activities": {
            "English": " Which of these sounds most appealing to you? I'd love to help you plan it!",
            "Slovenian": " Katero aktivnost vas najbolj zanima? Z veseljem vam jo pomagam organizirati!",
            "German": " Welche Aktivit\u00e4t interessiert Sie am meisten? Ich helfe gerne bei der Organisation!",
            "French": " Laquelle vous int\u00e9resse le plus ? Je serai ravi de vous aider \u00e0 l'organiser!",
            "Italian": " Quale ti interessa di pi\u00f9? Sar\u00e0 un piacere aiutarti!",
            "Spanish": "\u00bfCu\u00e1l te interesa m\u00e1s? \u00a1Estar\u00e9 encantado de ayudarte!",
            "Croatian": " Koja vas aktivnost najvi\u0161e zanima? Rado \u0107u vam pomo\u0107i s organizacijom!",
        },
        "restaurant": {
            "English": " Would you like to make a reservation?",
            "Slovenian": " \u017delite rezervirati mizo?",
            "German": " M\u00f6chten Sie eine Reservierung vornehmen?",
            "French": " Souhaitez-vous r\u00e9server une table ?",
            "Italian": " Vuoi riservare un tavolo?",
            "Spanish": " \u00bfTe gustar\u00eda reservar una mesa?",
        },
        "location": {
            "English": " Would you like directions or tips on getting here?",
            "Slovenian": " \u017delite navodila za pot do nas ali nasvete za prihod?",
            "German": " M\u00f6chten Sie eine Wegbeschreibung oder Tipps f\u00fcr die Anreise?",
            "French": " Souhaitez-vous des indications ou des conseils pour venir ?",
            "Italian": " Vuoi indicazioni o suggerimenti per raggiungerci?",
            "Spanish": " \u00bfTe gustar\u00eda recibir indicaciones o consejos para llegar?",
        },
        "parking": {
            "English": " Will you be driving to Bled, or would you like tips on public transport?",
            "Slovenian": " Boste vozili v Bled ali \u017eelite nasvete za javni prevoz?",
            "German": " Kommen Sie mit dem Auto nach Bred, oder ben\u00f6tigen Sie Tipps f\u00fcr den \u00f6ffentlichen Nahverkehr?",
            "French": " Venez-vous \u00e0 Bled en voiture, ou souhaitez-vous des conseils sur les transports en commun ?",
            "Italian": " Verrai a Bled in auto, o vuoi suggerimenti sui trasporti pubblici?",
            "Spanish": " \u00bfVas a venir a Bled en coche, o te gustar\u00eda recibir consejos sobre transporte p\u00fablico?",
        },
    }
    # Generic follow-up when topic not matched
    generic = {
        "English": " Is there anything else I can help you with?",
        "Slovenian": " Vas kaj drugo zanima? Z veseljem vam pomagam!",
        "German": " Gibt es noch etwas, womit ich Ihnen helfen kann?",
        "French": " Y a-t-il autre chose que je puisse faire pour vous ?",
        "Italian": " C'\u00e8 altro con cui posso aiutarti?",
        "Spanish": "\u00bfHay algo m\u00e1s en lo que pueda ayudarte?",
        "Croatian": " Ima li jo\u0161 \u010de\u0161ta u \u010demu vam mogu pomo\u0107i?",
    }
    topic_questions = questions.get(topic, {})
    if topic_questions:
        return text + topic_questions.get(lang, topic_questions.get("English", ""))
    return text + generic.get(lang, generic.get("English", ""))

def clean_response(text):
    """Remove model reasoning/chain-of-thought text from responses."""
    import re as _re
    text = _re.sub(r'<tools>.*?</tools>', '', text, flags=_re.DOTALL | _re.IGNORECASE)
    text = _re.sub(r'\{.*?"description".*?"name".*?"parameters".*?\}', '', text, flags=_re.DOTALL)
    text = _re.sub(r'\{.*?"type":\s*".*?".*?"properties".*?\}', '', text, flags=_re.DOTALL)
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
    Strips trailing whitespace, then replaces trailing '.' or '!' with '?',
    or appends '?' if the text ends with neither."""
    text = text.rstrip()
    if not text:
        return "Is there anything else I can help you with?"
    if text[-1] in ('.', '!', ',', ';', ':'):
        text = text[:-1] + '?'
    elif text[-1] != '?':
        text = text + '?'
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


def build_system_prompt() -> str:
    return (
        "You are Luka, a friendly hotel concierge at Villa Adora Bled, a luxury boutique hotel on Lake Bled, Slovenia.\n\n"
        "LANGUAGE (CRITICAL):\n"
        "- Detect the guest's language from their message and respond in the SAME language.\n"
        "- Supported languages: English, Slovenian (Slovenščina), German (Deutsch), Italian (Italiano), French (Français), Spanish (Español), Croatian (Hrvatski), Serbian (Srpski).\n"
        "- When a tool returns English information, you MUST translate it to the guest's language. This is NON-NEGOTIABLE.\n"
        "- Example: If guest writes in Slovenian and the tool returns 'We have 7 beautiful suites', you must respond with 'Imamo 7 čudovitih apartmajev' — NOT the English text.\n"
        "- If the guest writes in French, you must respond in French. If in German, respond in German. ALWAYS match the guest's language.\n"
        "- Keep the same warm, concise style regardless of language.\n\n"
        "STYLE:\n"
        "Be warm, concise, and conversational — like a real human concierge.\n"
        "Keep responses to 2-3 sentences max for simple answers. For listings (rooms, experiences), use bullet points.\n"
        "ALWAYS end with a follow-up question to keep the guest engaged. This is MANDATORY for ALL responses — including greetings, thank-yous, and goodbyes. Examples:\n"
        "  - Greeting: 'Hello! How can I help you today?' or 'Welcome! What would you like to know about Villa Adora?'\n"
        "  - Thank you: 'You're welcome! Is there anything else I can help you with?' or 'My pleasure! What else would you like to know?'\n"
        "  - Goodbye: 'Goodbye! Safe travels, and we hope to see you soon — is there anything else before you go?'\n"
        "The FINAL character of your response MUST always be '?'. Never end with '.' or '!'.\n"
        "PROACTIVE BOOKING: After answering about activities, restaurant, rooms, or experiences, ALWAYS offer to help the guest book it. For example:\n"
        "  - After listing activities: 'I can help you book any of these — just let me know which interests you!' or 'Would you like me to arrange that for you?'\n"
        "  - After restaurant info: 'Shall I book a table for you? Just tell me the date and time!'\n"
        "  - After room info: 'Would you like me to start a booking for you? I just need your name and dates.'\n"
        "  - After wine tasting info: 'Shall I reserve a wine pairing experience for you?'\n"
        "ALWAYS end your response with a question mark '?'. This is NON-NEGOTIABLE in EVERY language. Never end with '!', '.', or any other punctuation.\n"
        "NEVER mention technical details: no databases, APIs, SQLite, Flask, Ollama, RAG, tools, or internal systems.\n"
        "NEVER mention room prices unless the guest specifically asks about pricing.\n"
        "If asked how booking works, simply say: 'I can help you book! Just tell me your name, dates, and preferred room.'\n"
        "If asked about weather, say: 'I don't have real-time weather data, but I'd recommend checking a weather app for the latest forecast. Bled has beautiful summers and snowy winters!'\n"
        "- ALWAYS use the query_hotel_info tool for factual questions (rooms, policies, location, parking, pets, breakfast, restaurant, bar, wine, activities, etc.) — do NOT answer from your own knowledge, use the tool to get accurate data.\n\n"
        "RESPONSE QUALITY:\n"
        "- Ensure proper spacing between words. Avoid run-on words like 'wewe' or 'abar'.\n"
        "- Never output raw dictionary values or technical data structures.\n"
        "- Give ONE cohesive answer — don't send multiple separate replies unless each is clearly distinct.\n"
        "- If you don't know something, say so warmly and suggest contacting the hotel directly.\n"
        "- MANDATORY: You MUST call query_hotel_info for ALL factual questions about the hotel. NEVER answer factual questions from your own knowledge — always use the tool to get accurate, up-to-date information. This includes: rooms, check-in/out, breakfast, restaurant, bar, wine, parking, pets, location, activities, policies, amenities, contact info, shuttle, and pricing.\n\n"
        "KEY FACTS:\n"
        "- Check-in: 14:00-23:00 | Check-out: 07:00-11:00\n"
        "- Late check-in/out: Available on request, contact reception\n"
        "- Breakfast: €22/person, served 8-10 AM. Continental, vegan, vegetarian, gluten-free options available on request.\n"
        "- Restaurant: Adora Pop Up Restaurant — creative Slovenian cuisine with French, Italian, and international influences by Chef Domen Demšar. Lunch/dinner Tue-Sun, brunch Thu-Sat. Terrace with best lake views in Bled. Tasting menu ~€65/person, wine pairing ~€35/person. Reservations: +386 40 558 158 or evita.vilebled@gmail.com\n"
        "- Wine list: curated Slovenian and international wines by in-house expert. Wine pairing available with tasting menu (~€35/person).\n"
        "- Bar: cocktails and aperitivos daily on terrace with panoramic lake views. If guest asks about bar AND wine, mention both: cocktails and our curated wine list.\n"
        "- Shuttle service available — airport transfer, local transport, custom routes. Book directly in this chat. Ljubljana airport ~€60, Bled town center ~€15.\n"
        "- Free parking and WiFi (8 parking spots in front of the hotel)\n"
        "- Pets allowed on request — €35 per pet per night\n"
        "- Quiet hours: 22:00-07:00 | Parties/events not allowed\n"
        "- Address: Cesta svobode 35, Bled, Slovenia\n"
        "- Phone: +386 51 603 858 | WhatsApp: +386 51 603 858\n"
        "- Booking.com: 9.1/10 Wonderful (698 reviews) | TripAdvisor: 4.7/5 Travelers' Choice\n\n"
        "ROOMS: Princess Suite (55 m², tower view), Luxury Suite (lake view), Penthouse Suite (60 m², 2 floors), Swan Suite (lake view), Island Suite (sleeps 4, 65 m²), Prestige Suite (72 m², ground floor), Castle Suite — all with lake views.\n\n"
        "NEVER do:\n"
        "- Mention databases, code, APIs, or technical systems\n"
        "- Mention prices unless asked\n"
        "- Ask for booking reference or reservation ID\n"
        "- Give bare answers without a follow-up question ending in '?'\n"
        "- End your response with '!' or '.' — it MUST end with '?'\n"
        "- Send multiple separate replies to a single question\n"
        "- If guest is frustrated, unsatisfied, or explicitly asks for a human, use request_human_agent() to transfer them\n"
        "- If you cannot answer a question well, offer to connect the guest with a human agent\n"
        "- Shuttle bookings: use book_shuttle() when guest wants to book a shuttle. Ask for: name, pickup location, date, time, passengers.\n"
        "- Human agent: use request_human_agent() when guest needs human help. Always offer this as an option if the guest seems unhappy.\n"
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


def _detect_language(message: str) -> str:
    """Simple language detection based on common words and character patterns."""
    import re as _re
    msg_raw = " " + message.lower().strip() + " "
    # For word matching, create a version with punctuation replaced by spaces
    msg = " " + _re.sub(r'[!?,.;:()\[\]{}]', ' ', message.lower().strip()) + " "
    # Collapse multiple spaces
    msg = _re.sub(r'  +', ' ', msg)

    # Character-based detection for languages with unique characters
    # Slovenian/Croatian specific characters
    if any(c in msg for c in ['š', 'č', 'ž']):
        slovenian_markers = [" imate ", " kakšen ", " kako ", " lahko ", " želim ", " prosim ", " hvala ", " pozdravljeni ", " dober dan ", " zdravo ", " sobe ", " soba "]
        if any(w in msg for w in slovenian_markers):
            return "Slovenian"
        if 'đ' in msg or 'ć' in msg:
            return "Croatian"
        return "Slovenian"

    # Word-based Slovenian detection (without diacritics)
    slovenian_words = [" pozdravljeni ", " hvala ", " prosim ", " kako ste ", " dober dan ", " nasvidenje ", " rezervacija ", " zajtrk ", " sobe ", " soba ", " apartma ", " imate ", " lahko ", " želim ", " kakšen ", " kakšni ", " količina ", " gostje ", " gostom ", " jutri ", " danes ", " nočitev ", " koliko ", " stane", " prijava ", " prijave ", " odjava ", " kje ", " kako ", " ura ", " urah ", " restavracija ", " parkirno ", " pes ", " aktivnosti ", " jezero ", " otok ", " grad ", " razgled ", " pogled ", " cena ", " cene ", " koliko "]
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
        french_words = [" bonjour ", " bonsoir ", " merci ", " vous ", " nous ", " chambre ", " petit ", " déjeuner ", " réservation ", " avez ", " pouvez ", " voudrais ", " c'est ", " est ", " les ", " des ", " dans ", " pour ", " avec ", " l'hôtel ", " l'hotel ", " où ", " êtes ", " sommes "]
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
        italian_words = [" buongiorno ", " buonasera ", " grazie ", " vorrei ", " avete ", " prenotazione ", " colazione ", " ristorante ", " arrivederci ", " camere ", " ora ", " che ora ", " parlami ", " parlez "]
        if any(w in msg for w in italian_words):
            return "Italian"

    # Word-based detection for languages without unique characters
    # French word patterns
    french_words = [" bonjour ", " bonsoir ", " merci ", " s'il vous ", " je voudrais ", " avez-vous ", " nous avons ", " les chambres ", " petit déjeuner ", " au revoir ", " bienvenue ", " c'est ", " réservation ", " chambre ", " chambres ", " pouvez ", " voulez ", " souhaitez ", " souhaite ", " j'aimerais ", " je souhaiterais ", " animaux ", " chien ", " chat ", " vins ", " activités ", " où ", " combien ", " parlez "]
    if any(w in msg for w in french_words):
        return "French"

    # Multi-word phrases that are highly distinctive per language
    distinctive_phrases = {
        "German": [
            " guten tag ", " guten morgen ", " guten abend ", " vielen danke ",
            " auf wiedersehen ", " wie geht ", " haben sie ", " ich möchte ",
            " können wir ", " ich hätte ", " buchung ", " zimmer ", " zimmern ", " frühstück ",
            " parkplatz ", " haustier ", " abreise ", " anreise ", " wunderbar ",
            " buchen ", " reservierung ", " kammer ", " schlafzimmer ",
            " einen parkplatz ", " parken ", " auto ", " wagen ", " erzählen "
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
            " camera ", " alloggio "
        ],
        "Spanish": [
            " buenos días ", " buenas tardes ", " muchas gracias ", " por favor ",
            " quisiera ", " tienen ", " habitaciones ", " desayuno ", " restaurante ",
            " bienvenido ", " hasta luego ", " magnífico ", " perfecto ", " reservación "
        ],
        "Slovenian": [
            " pozdravljeni ", " hvala lepo ", " prosim vas ", " kako ste ",
            " dober dan ", " lahko noč ", " nasvidenje ", " rezervacija ", " zajtrk ",
            " soba ", " sobe ", " apartma "
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
    """Detect the hotel info topic from a message (language-independent)."""
    msg = message.lower()

    topic_keywords = {
        "rooms": ["room", "suite", "bed", "sleep", "sobe", "soba", "zimmer", "zimmern", "camere", "camera", "chambre", "chambres", "habitaci", "cuarto", "apartma", "apartmaj", "sobah", "habitacion", "dormitorio"],
        "restaurant": ["restaurant", "dining", "dinner", "lunch", "menu", "chef", "domen", "dem\u0161ar", "demar", "pop up", "pop-up", "terrace dining", "food", "eat", "meal", "restavracija", "ristorante", "restaurante", "speise", "essen", "ku00fcche", "cucina", "manger", "nourriture", "comida", "comer", "alimento"],
        "bar": ["bar", "cocktail", "drink", "aperitivo", "aperitiv", "pijau010da", "getru00e4nk", "bevanda", "boisson"],
        "wine": ["wine", "wines", "vineyard", "sommelier", "wine pairing", "vino", "vin", "wein", "vina"],
        "breakfast": ["breakfast", "morning meal", "brunch", "zajtrk", "fr\u00fchst\u00fcck", "colazione", "petit d\u00e9jeuner", "desayuno", "vegan", "vegetarian", "gluten", "allergy", "allergies", "dietary", "diet", "restriction", "celiac", "lactose", "intolerant", "vegansko", "vegetarijansko", "brezglutensko", "alergija", "prehrana", "koliko stane", "kako much", "how much is breakfast", "how much does breakfast"],
        "parking": ["parking", "park", "car", "parkiriu0161u010de", "parkir", "parkplatz", "parcheggio", "aparcamiento", "stationnement", "parken", "parkiranje", "avto", "auto", "wagen", "voiture", "coche", "macchina", "estacionamiento", "carro"],
        "pets": ["pet", "dog", "cat", "animal", "pes", "mau010dka", "hund", "katze", "cane", "gatto", "chien", "chat", "perro", "gato", "mascot"],
        "location": ["location", "address", "where", "direction", "map", "located", "lokacija", "naslov", "kje", "standort", "adresse", "dove", "ou00f9", "du00f3nde", "donde", "ubicaci", "ubicacion", "direccion"],
        "experiences": ["experience", "activity", "activities", "thing to do", "attraction", "sight", "visit", "tour", "hike", "swim", "massage", "spa", "aktivnost", "attivitu00e0", "activitu00e9", "actividad"],
        "check_in": ["check in", "checkin", "arrival", "arrive", "check-in", "late check in", "late arrival", "prihod", "ankunft", "anreise", "arrivo", "arrivu00e9e", "llegada", "prijava", "prijave", "che ora", "wann ist"],
        "check_out": ["check out", "checkout", "departure", "depart", "check-out", "late check out", "late departure", "odhod", "abreise", "partenza", "du00e9part", "salida"],
        "late_check_in": ["late check in", "late checkin", "late arrival", "arrive late", "pozen prihod", "spu00e4t ankommen", "arrivo tardif", "arrivu00e9e tardive"],
        "late_check_out": ["late check out", "late checkout", "late departure", "leave late", "pozen odhod", "spu00e4t abreise", "partenza tardif", "du00e9part tardif"],
        "wifi": ["wifi", "wi-fi", "internet", "wireless", "wlan"],
        "contact": ["contact", "phone", "email", "call", "reach", "kontakt", "telefon", "rufen", "chiamare", "appeler", "llamar"],
        "policies": ["policy", "rule", "regulation", "pravilo", "regel", "ru00e8gle", "regla"],
        "cancellation": ["cancel", "refund", "cancellation", "stornir", "storno", "annulation", "annullamento", "annulaci"],
        "children": ["child", "kid", "baby", "family", "families", "toddler", "otrok", "kind", "bambino", "enfant", "niu00f1o", "dru\u017eina", "familie", "gruppe", "grupo", "famille", "famiglia", "gruppe"],
        "room_service": ["room_service", "room service", "in-room dining", "food to room"],
        "shuttle": ["shuttle", "transfer", "airport", "transport", "prevoz", "navette", "transporte"],
        "weather": ["weather", "forecast", "temperature", "rain", "sunny", "snow", "climate", "vreme", "temperatura"],
        "booking": ["book", "reserve", "reservation", "rezervir", "buchen", "prenotare", "réserver", "reservar"],
    }

    for topic, keywords in topic_keywords.items():
        if any(kw in msg for kw in keywords):
            return topic
    # Priority overrides: booking intent should override rooms
    if any(kw in msg for kw in ["book", "reserve", "rezervir", "buchen", "prenotare", "réserver", "reservar"]) and any(kw in msg for kw in ["room", "suite", "zimmer", "camera", "chambre", "habitaci", "sobe", "soba"]):
        return "booking"
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
    h = hotel_info
    q = question.lower()

    # Map common synonyms to topics
    topic_aliases = {
        "check_in": ["check in", "checkin", "arrival", "arrive", "check-in", "late check in", "late arrival"],
        "check_out": ["check out", "checkout", "departure", "depart", "check-out", "late check out", "late departure"],
        "rooms": ["room", "suite", "bed", "accommodation", "stay", "sleep"],
        "policies": ["policy", "rule", "regulation"],
        "amenities": ["amenity", "facility", "feature", "service", "perk"],
        "location": ["location", "address", "where", "direction", "map", "find", "located"],
        "experiences": ["experience", "activity", "thing to do", "attraction", "sight", "visit", "tour", "hike", "swim", "activities", "nearby", "around", "do here", "what to"],
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
        "late_check_in": ["late check in", "late checkin", "late arrival", "arrive late", "after hours check in", "night check in"],
        "late_check_out": ["late check out", "late checkout", "late departure", "leave late", "after hours check out"],
        "contact": ["contact", "phone", "email", "call", "reach"],
        "room_service": ["room service", "in-room dining", "food to room"],
        "shuttle": ["shuttle", "transfer", "airport"],
        "general": ["general", "info", "information", "about", "tell me"],
    }

    # Detect actual topic from question if topic is generic
    actual_topic = topic
    if topic in ("general", "policies"):
        for t, aliases in topic_aliases.items():
            if any(a in q for a in aliases):
                actual_topic = t
                break

    # Override: dietary questions should always go to breakfast/dining
    if actual_topic not in ("breakfast",) and any(word in q for word in ["vegan", "vegetarian", "gluten", "allergy", "allergies", "dietary", "diet", "restriction", "celiac", "lactose", "intolerant"]):
        actual_topic = "breakfast"

    # Check-in / Check-out
    if actual_topic in ("check_in", "check_out"):
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
                f"What time would you like to check out?"
            )

    # Rooms
    if actual_topic == "rooms":
        # Check if asking about pricing
        is_price_query = any(word in q for word in ["price", "cost", "how much", "rate", "pricing", "expensive", "cheap", "cena", "preis", "prix", "precio", "prezzo"])
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
                lines.append("\nAll our suites:")
                lines.extend(all_rooms)
                lines.append("Which one catches your eye? I can start a booking for you — just tell me your name and dates!")
                return "\n".join(lines)
            lines = ["We have 7 beautiful suites, all with stunning lake views:"]
            lines.extend(all_rooms)
            lines.append("Which one catches your eye? I can start a booking for you — just tell me your name and dates!")
            return "\n".join(lines)
        lines = ["We have 7 beautiful suites, all with stunning lake views:"]
        for r in h["rooms"].values():
            size = f", {r['size_sqm']} m²" if r.get("size_sqm") else ""
            cap = f", sleeps {r['capacity']}" if r.get("capacity") else ""
            price_str = f" — €{r['price']}/night" if r.get("price") and is_price_query else ""
            feat = ", ".join(r.get("features", [])[:2])
            lines.append(f"• {r['name']}{size}{cap}{price_str} — {feat}")
        lines.append("Which one catches your eye? I can start a booking for you — just tell me your name and dates!")
        return "\n".join(lines)

    # Policies
    if actual_topic == "policies":
        return (
            f"Check-in: {h['policies']['check_in']}. Check-out: {h['policies']['check_out']}. "
            f"Breakfast is €22/person. Free parking and WiFi. Pets allowed on request. "
            f"Is there a specific policy you'd like to know more about?"
        )

    # Breakfast
    if actual_topic == "breakfast":
        b = h.get("dining", {}).get("breakfast", {})
        if isinstance(b, dict):
            dietary = b.get("dietary", {})
            if any(word in q for word in ["vegan", "vegetarian", "gluten", "allergy", "allergies", "dietary", "diet", "restriction"]):
                return (
                    f"Breakfast is €22/person, served 8-10 AM in our dining room. "
                    f"We're happy to accommodate dietary needs — just let us know when you book! "
                    f"We offer vegan, vegetarian, and gluten-free options on request, "
                    f"and can handle allergies and other dietary requirements with advance notice. "
                    f"Would you like to add breakfast to your booking?"
                )
            return (
                f"Breakfast is €22/person, served daily 8-10 AM in our dining room with fresh pastries, bread, and local Slovenian products. "
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
            "Our bar serves elegant cocktails and aperitivos daily on the terrace with panoramic lake views. "
            "It's the perfect spot for sunset drinks! "
            "Would you like me to tell you more about our drinks menu, or shall I help you with a restaurant reservation?"
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
        return (
            f"{h['policies']['cancellation']}. "
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
            f"The Island Suite is perfect for families as it has 2 bedrooms and sleeps 4 guests. "
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
        return (
            f"We're at {h['location']['address']}. "
            f"{h['location']['description']} "
            f"Phone: {h['location']['phone']}. "
            f"Would you like directions or tips on getting here?"
        )

    # Smoking
    if actual_topic == "smoking":
        return (
            f"{h['policies']['smoking']}. "
            f"Is there anything else I can help you with?"
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
        # Check if asking about family-friendly activities
        if any(word in q for word in ["family", "families", "kid", "child", "children", "baby", "toddler"]):
            return (
                "Bled is wonderful for families! Here are some great options:\n"
                "• Row to Bled Island — kids love the traditional pletna boat ride\n"
                "• Swimming in the lake — safe, clean, and free!\n"
                "• Vintgar Gorge walk — an easy and spectacular nature walk\n"
                "• Horse-drawn carriage rides around Bled\n"
                "• Mini golf and cycling around the lake\n"
                "• Bled Castle — explorers of all ages will enjoy it\n"
                "The Island Suite is perfect for families as it sleeps 4 with 2 bedrooms! "
                "Which activity sounds most fun for your family?"
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

    # Amenities
    if actual_topic == "amenities":
        return (
            f"We offer: {', '.join(h['amenities'][:8])}. "
            f"Would you like the full list, or is there something specific you're looking for?"
        )

    # Room Service
    if actual_topic == "room_service":
        return (
            "Room service is available! You can enjoy meals and drinks in the comfort of your suite. "
            "Our kitchen can accommodate dietary requirements — just let us know your preferences. "
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
        return (
            f"We also offer {vp.get('name', 'Villa Pomona')} — {vp.get('type', 'a luxury villa retreat')}. "
            f"Located on {vp.get('location', 'the most picturesque street in Bled')}. "
            f"It features {vp.get('accommodations', {}).get('bedrooms', 3)} bedrooms with ensuite bathrooms, "
            f"a swimming pool, sauna, and garden. "
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
            "I'd love to help you book a room! We have 7 beautiful suites with stunning lake views. "
            "To get started, I'll need your name, check-in and check-out dates, and your preferred room. "
            "Which suite catches your eye, or would you like me to help you choose?"
        )

    # Fallback
    return (
        f"Villa Adora Bled is a heritage-protected villa from 1878, converted into a luxury design hotel "
        f"right on Lake Bled. We have 7 unique suites with panoramic lake views. "
        f"What would you like to know — rooms, booking, or things to do in Bled?"
    )


app = Flask(__name__)
sessions = {}


@app.route("/")
def index():
    return render_template("index.html", hotel=hotel_info, hotel_name=hotel_info["name"])


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.json
    session_id = data.get("session_id", "default")
    user_message = data.get("message", "")
    if not user_message.strip():
        return jsonify({"replies": [{"type": "text", "content": "Empty input."}]})
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
    is_non_english = detected_lang != "English"

    try:
        lang_messages = list(messages)
        # Detect topic for potential direct response (both English and non-English)
        topic = _detect_topic(user_message) if is_non_english else _detect_topic(user_message)

        if is_non_english:
            # For non-English messages, detect topic and fetch hotel data directly.
            # Check if we have a pre-translated response for rooms/experiences
            # Use direct response to bypass LLM and avoid timeout issues
            direct_response = None
            topic_direct_map = {
                "rooms": _ROOM_LISTINGS_TRANSLATED,
                "experiences": _EXPERIENCES_TRANSLATED,
                "activities": _EXPERIENCES_TRANSLATED,
                "restaurant": _RESTAURANT_TRANSLATED,
                "location": _LOCATION_TRANSLATED,
                "breakfast": _BREAKFAST_TRANSLATED,
                "parking": _PARKING_TRANSLATED,
                "pets": _PETS_TRANSLATED,
                "check_in": _CHECKIN_TRANSLATED,
                "check_out": _CHECKIN_TRANSLATED,
                "late_check_in": _CHECKIN_TRANSLATED,
                "late_check_out": _CHECKIN_TRANSLATED,
                "wine": _WINE_TRANSLATED,
                "bar": _BAR_TRANSLATED,
                "shuttle": _SHUTTLE_TRANSLATED,
            }
            if topic in topic_direct_map and detected_lang in topic_direct_map[topic]:
                direct_response = topic_direct_map[topic][detected_lang]

            if direct_response:
                messages.append({"role": "user", "content": user_message})
                messages.append({"role": "assistant", "content": direct_response})
                sessions[session_id] = messages
                return jsonify({"replies": [{"type": "text", "content": direct_response}]})

            # For other topics, use LLM with pre-fetched data
            hotel_answer = get_hotel_info_response(topic, user_message)
            if topic == "general" and detected_lang != "English":
                localized = _get_localized_fallback(detected_lang, user_message)
                if localized and localized.strip():
                    messages.append({"role": "user", "content": user_message})
                    messages.append({"role": "assistant", "content": localized})
                    sessions[session_id] = messages
                    response_text = fix_spacing(localized)
                    response_text = _ensure_follow_up(response_text, "", detected_lang)
                    return jsonify({"replies": [{"type": "text", "content": response_text}]})
                lang_messages.append({
                    "role": "system",
                    "content": f"MANDATORY: The guest wrote in {detected_lang}. Respond ENTIRELY in {detected_lang}. Be warm, concise, and end with a follow-up question in {detected_lang}. The FINAL character MUST be '?'."
                })
            elif hotel_answer and hotel_answer.strip():
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
            if topic == "rooms":
                hotel_answer = get_hotel_info_response("rooms", user_message)
                if hotel_answer and hotel_answer.strip():
                    messages.append({"role": "user", "content": user_message})
                    messages.append({"role": "assistant", "content": hotel_answer})
                    sessions[session_id] = messages
                    return jsonify({"replies": [{"type": "text", "content": hotel_answer}]})
            elif topic in ("experiences", "activities"):
                hotel_answer = get_hotel_info_response("experiences", user_message)
                if hotel_answer and hotel_answer.strip():
                    messages.append({"role": "user", "content": user_message})
                    messages.append({"role": "assistant", "content": hotel_answer})
                    sessions[session_id] = messages
                    return jsonify({"replies": [{"type": "text", "content": hotel_answer}]})

        # For non-English messages, exclude query_hotel_info tool since we provide
        # hotel data via context. This prevents the LLM from calling the tool
        # and getting English responses. Keep booking/shuttle tools available.
        if is_non_english:
            available_tools = [book_room_function, book_shuttle_function, request_human_agent_function]
        else:
            available_tools = [book_room_function, query_hotel_info_function, book_shuttle_function, request_human_agent_function]

        tool_params = {
            "model": MODEL,
            "messages": lang_messages,
            "tools": available_tools,
            "temperature": 0.3 if is_non_english else 0.5,
            "max_tokens": 2000 if is_non_english else 1500,
            "timeout": 50,
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
                room_key = args["room_name"].lower().replace(" ", "_")
                price = hotel_info["rooms"].get(room_key, {}).get("price", "")
                price_str = f" ({price} EUR/night)" if price else ""
                replies.append(
                    {
                        "type": "confirmation_request",
                        "content": (
                            f"Booking Confirmation\n\n"
                            f"• Guest: {args['guest_name']}\n"
                            f"• Check-in: {args['check_in']}\n"
                            f"• Check-out: {args['check_out']}\n"
                            f"• Room: {args['room_name']}{price_str}\n\n"
                            "Reply yes to confirm or no to cancel."
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
                            notes=f"Guest requested {event_type.replace('_', ' ')} at {extracted_time}. Original message: {user_message}"
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
                    notes=f"Guest requested {event_type.replace('_', ' ')} at {extracted_time}. Message: {user_message}"
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
                # Ensure the response ends with a question mark
                reply["content"] = _ensure_ends_with_question(reply["content"])
                if reply.get("type") == "text" and reply.get("content"):
                    reply["content"] = _ensure_follow_up(reply["content"], "", detected_lang)
                # Post-process: if response was supposed to be non-English but came back in English,
                # replace with a translated fallback
                if is_non_english and reply.get("content"):
                    content = reply["content"]
                    # Check if response is still mostly English (simple heuristic)
                    english_words = ["the ", "we ", "our ", "you ", "have ", "are ", "with ", "and ", "for ", "this ", "that ", "here ", "there ", "would ", "could ", "should ", "will ", "can ", "your"]
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
                        f"We have 7 unique suites with lake views, a pop-up restaurant, free parking and WiFi. "
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
                )
            else:
                response = "❌ Canceled."
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5173))
    print(f"🏔️  {hotel_info['name']} — Fast Mode")
    print(f"📍 http://localhost:{port} | 📊 /admin")
    app.run(host="0.0.0.0", port=port, debug=True, threaded=True)

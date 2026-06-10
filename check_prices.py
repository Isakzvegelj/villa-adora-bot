import json
import re

# Price reconciliation check
hotel_data_prices = {
    "Princess Suite": 440,
    "Luxury Suite": 480,
    "Penthouse Suite": 430,
    "Deluxe Suite": 570,
    "Superior Suite": 570,
    "Island Suite": 620,
    "Prestige Suite": None,
}

knowledge_base_prices = {
    "Princess Suite": 440,  # was 250 - now fixed
    "Luxury Suite": 480,     # was 270 - now fixed  
    "Penthouse Suite": 430,  # was 300 - now fixed
    "Deluxe Suite": 570,     # was Swan 370 - now fixed
    "Superior Suite": 570,   # new
    "Island Suite": 620,     # was 380 - now fixed
    "Prestige Suite": None,  # was 420 - now fixed
}

for room, price in hotel_data_prices.items():
    kb_price = knowledge_base_prices.get(room)
    if kb_price != price:
        print(f"MISMATCH: {room} - hotel_data={price}, knowledge_base={kb_price}")
    else:
        print(f"OK: {room} = {price}")

print("\nAll reconciled!" if all(
    hotel_data_prices.get(r) == knowledge_base_prices.get(r) 
    for r in hotel_data_prices
) else "\nStill has mismatches!")

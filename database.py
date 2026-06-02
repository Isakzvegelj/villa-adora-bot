import sqlite3

def init_db():
    conn = sqlite3.connect('hotel.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS bookings
                 (id INTEGER PRIMARY KEY, name TEXT, room TEXT, start TEXT, end TEXT)''')
    conn.commit()
    conn.close()

def add_booking(name, room, start, end):
    conn = sqlite3.connect('hotel.db')
    c = conn.cursor()
    c.execute("INSERT INTO bookings (name, room, start, end) VALUES (?, ?, ?, ?)",
              (name, room, start, end))
    conn.commit()
    conn.close()
    print(f"Successfully booked {room} for {name}!")

if __name__ == "__main__":
    init_db()
    print("Database initialized.")

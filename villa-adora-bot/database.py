import sqlite3

DB_PATH = "hotel.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guest_name TEXT,
            room_name TEXT,
            check_in TEXT,
            check_out TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS calendar_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            event_type TEXT,
            guest_name TEXT,
            time TEXT,
            date TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS shuttle_bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            guest_name TEXT,
            pickup_location TEXT,
            dropoff_location TEXT,
            date TEXT,
            time TEXT,
            passengers INTEGER DEFAULT 1,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS human_agent_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            reason TEXT,
            guest_name TEXT,
            summary TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def add_booking(guest_name, room_name, check_in, check_out):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO bookings (guest_name, room_name, check_in, check_out) VALUES (?, ?, ?, ?)",
        (guest_name, room_name, check_in, check_out),
    )
    conn.commit()
    conn.close()


def get_all_bookings():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM bookings ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return rows


def add_calendar_event(session_id, event_type, guest_name, time, notes="", date=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO calendar_events (session_id, event_type, guest_name, time, notes, date) VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, event_type, guest_name, time, notes, date),
    )
    conn.commit()
    conn.close()


def get_all_calendar_events():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM calendar_events ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return rows


def add_shuttle_booking(session_id, guest_name, pickup_location, dropoff_location, date, time, passengers=1, notes=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO shuttle_bookings (session_id, guest_name, pickup_location, dropoff_location, date, time, passengers, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, guest_name, pickup_location, dropoff_location, date, time, passengers, notes),
    )
    conn.commit()
    conn.close()


def add_human_agent_request(session_id, reason, guest_name="", summary=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO human_agent_requests (session_id, reason, guest_name, summary) VALUES (?, ?, ?, ?)",
        (session_id, reason, guest_name, summary),
    )
    conn.commit()
    conn.close()

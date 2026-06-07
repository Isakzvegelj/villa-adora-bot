import sqlite3
from datetime import datetime

def init_db():
    conn = sqlite3.connect('hotel.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS bookings
                 (id INTEGER PRIMARY KEY, name TEXT, room TEXT, start TEXT, end TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS calendar_events
                 (id INTEGER PRIMARY KEY,
                  session_id TEXT,
                  event_type TEXT,
                  guest_name TEXT,
                  time TEXT,
                  date TEXT,
                  notes TEXT,
                  created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS shuttle_bookings
                 (id INTEGER PRIMARY KEY,
                  session_id TEXT,
                  guest_name TEXT,
                  pickup_location TEXT,
                  dropoff_location TEXT,
                  date TEXT,
                  time TEXT,
                  passengers INTEGER,
                  notes TEXT,
                  status TEXT DEFAULT 'pending',
                  created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS human_agent_requests
                 (id INTEGER PRIMARY KEY,
                  session_id TEXT,
                  reason TEXT,
                  guest_name TEXT,
                  summary TEXT,
                  status TEXT DEFAULT 'pending',
                  created_at TEXT)''')
    conn.commit()
    conn.close()

def add_booking(name, room, start, end):
    conn = sqlite3.connect('hotel.db')
    c = conn.cursor()
    c.execute("INSERT INTO bookings (name, room, start, end) VALUES (?, ?, ?)",
              (name, room, start, end))
    conn.commit()
    conn.close()
    print(f"Successfully booked {room} for {name}!")

def add_calendar_event(session_id, event_type, guest_name, time, date=None, notes=None):
    """Add a late check-in or check-out event to the calendar."""
    conn = sqlite3.connect('hotel.db')
    c = conn.cursor()
    created_at = datetime.now().isoformat()
    c.execute("""INSERT INTO calendar_events 
                 (session_id, event_type, guest_name, time, date, notes, created_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?)""",
              (session_id, event_type, guest_name, time, date, notes, created_at))
    conn.commit()
    event_id = c.lastrowid
    conn.close()
    return event_id

def get_calendar_events(event_type=None, date=None):
    """Get calendar events, optionally filtered by type and/or date."""
    conn = sqlite3.connect('hotel.db')
    c = conn.cursor()
    query = "SELECT * FROM calendar_events WHERE 1=1"
    params = []
    if event_type:
        query += " AND event_type = ?"
        params.append(event_type)
    if date:
        query += " AND date = ?"
        params.append(date)
    query += " ORDER BY created_at DESC"
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return rows

def add_shuttle_booking(session_id, guest_name, pickup_location, dropoff_location, date, time, passengers=1, notes=None):
    """Add a shuttle booking."""
    conn = sqlite3.connect('hotel.db')
    c = conn.cursor()
    created_at = datetime.now().isoformat()
    c.execute("""INSERT INTO shuttle_bookings 
                 (session_id, guest_name, pickup_location, dropoff_location, date, time, passengers, notes, created_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
              (session_id, guest_name, pickup_location, dropoff_location, date, time, passengers, notes, created_at))
    conn.commit()
    booking_id = c.lastrowid
    conn.close()
    return booking_id

def add_human_agent_request(session_id, reason, guest_name="Guest", summary=""):
    """Log a human agent request."""
    conn = sqlite3.connect('hotel.db')
    c = conn.cursor()
    created_at = datetime.now().isoformat()
    c.execute("""INSERT INTO human_agent_requests 
                 (session_id, reason, guest_name, summary, created_at)
                 VALUES (?, ?, ?, ?, ?)""",
              (session_id, reason, guest_name, summary, created_at))
    conn.commit()
    request_id = c.lastrowid
    conn.close()
    return request_id

def get_all_calendar_events():
    """Get all calendar events."""
    return get_calendar_events()

if __name__ == "__main__":
    init_db()
    print("Database initialized.")

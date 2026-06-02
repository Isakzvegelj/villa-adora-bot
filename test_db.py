#!/usr/bin/env python3
"""Test script to verify hotel bot database operations"""

from database import add_booking, init_db
import sqlite3
import os

def test_database():
    print("🧪 Testing hotel bot database...\n")
    
    # Clean start
    if os.path.exists('hotel.db'):
        os.remove('hotel.db')
        print("✓ Removed existing database")
    
    init_db()
    print("✓ Database initialized\n")
    
    # Test bookings
    test_bookings = [
        ("Alice Johnson", "Deluxe", "2026-05-15", "2026-05-20"),
        ("Bob Smith", "Standard", "2026-06-01", "2026-06-05"),
        ("Carol Davis", "Suite", "2026-07-10", "2026-07-15"),
    ]
    
    for name, room, check_in, check_out in test_bookings:
        add_booking(name, room, check_in, check_out)
    
    print("\n📊 Verifying stored bookings:")
    conn = sqlite3.connect('hotel.db')
    c = conn.cursor()
    c.execute("SELECT * FROM bookings")
    rows = c.fetchall()
    conn.close()
    
    if len(rows) == 3:
        print(f"✓ {len(rows)} bookings stored correctly\n")
        print("ID  | Guest              | Room    | Check-In   | Check-Out  ")
        print("----|--------------------|---------|------------|------------")
        for row in rows:
            print(f"{row[0]:<4} | {row[1]:<18} | {row[2]:<7} | {row[3]:<10} | {row[4]:<10}")
        print("\n✅ All tests passed! Database is working.")
        return True
    else:
        print(f"❌ Expected 3 bookings, got {len(rows)}")
        return False

if __name__ == "__main__":
    success = test_database()
    exit(0 if success else 1)

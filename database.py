import sqlite3

# SQLite has no 'ADD COLUMN IF NOT EXISTS', so the users table is inspected first.
PROFILE_PHOTO_COLUMN_DDL = 'ALTER TABLE users ADD COLUMN profile_photo TEXT'


def ensure_schema():
    """Create the extra tables and the profile photo column if they are missing.

    Safe to run repeatedly: the CREATE TABLE statements are guarded, and the
    users.profile_photo column is only added when PRAGMA table_info does not
    already list it.
    """
    conn = sqlite3.connect('database.db')
    try:
        # Create allorders table only if it doesn't exist
        conn.execute('''CREATE TABLE IF NOT EXISTS allorders (
    orderId INTEGER PRIMARY KEY AUTOINCREMENT,
    userId INTEGER,
    productId INTEGER,
    quantity INTEGER,
    total_price REAL,
    order_date TEXT,
    FOREIGN KEY(userId) REFERENCES users(userId),
    FOREIGN KEY(productId) REFERENCES products(productId)
)''')

        # Create wishlist table only if it doesn't exist
        conn.execute('''CREATE TABLE IF NOT EXISTS wishlist (
    wishlistId INTEGER PRIMARY KEY AUTOINCREMENT,
    userId INTEGER,
    productId INTEGER,
    FOREIGN KEY(userId) REFERENCES users(userId),
    FOREIGN KEY(productId) REFERENCES products(productId)
)''')

        # Add users.profile_photo only if the users table exists without it
        cur = conn.cursor()
        cur.execute('PRAGMA table_info(users)')
        user_columns = [column[1] for column in cur.fetchall()]
        if user_columns and 'profile_photo' not in user_columns:
            conn.execute(PROFILE_PHOTO_COLUMN_DDL)

        conn.commit()
    finally:
        conn.close()


if __name__ == '__main__':
    ensure_schema()
    print("Tables created successfully!")

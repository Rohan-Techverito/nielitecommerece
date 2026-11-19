import sqlite3, os

conn = sqlite3.connect(os.environ.get('NIELIT_DB_PATH', 'database.db'))

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

# Create notifications table only if it doesn't exist
notifications_table_ddl = '''CREATE TABLE IF NOT EXISTS notifications (
    notificationId INTEGER PRIMARY KEY AUTOINCREMENT,
    userId INTEGER NOT NULL,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    is_read INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(userId) REFERENCES users(userId)
)'''
conn.execute(notifications_table_ddl)

conn.commit()
conn.close()

print("Tables created successfully!")

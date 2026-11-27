import os
import sqlite3

# Use the same database file as the app so tables are created where the app reads them.
DATABASE = os.environ.get('NIELIT_DATABASE', 'database.db')

conn = sqlite3.connect(DATABASE)

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
conn.execute('''CREATE TABLE IF NOT EXISTS notifications (
    notificationId INTEGER PRIMARY KEY AUTOINCREMENT,
    userId INTEGER NOT NULL,
    message TEXT NOT NULL,
    createdAt TEXT NOT NULL,
    isRead INTEGER NOT NULL DEFAULT 0
)''')

conn.execute('''CREATE INDEX IF NOT EXISTS idx_notifications_user_read
    ON notifications (userId, isRead, createdAt)''')

conn.commit()
conn.close()

print("Tables created successfully!")

import sqlite3

conn = sqlite3.connect('database.db')

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

# Create reviews table only if it doesn't exist
conn.execute('''CREATE TABLE IF NOT EXISTS reviews (
    reviewId INTEGER PRIMARY KEY AUTOINCREMENT,
    productId INTEGER NOT NULL,
    userId INTEGER NOT NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    title TEXT,
    comment TEXT,
    review_date TEXT NOT NULL,
    hidden INTEGER NOT NULL DEFAULT 0,
    hidden_reason TEXT,
    UNIQUE(userId, productId),
    FOREIGN KEY(productId) REFERENCES products(productId),
    FOREIGN KEY(userId) REFERENCES users(userId)
)''')

conn.commit()
conn.close()

print("Tables created successfully!")

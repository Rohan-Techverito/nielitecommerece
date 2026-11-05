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

# Create kart table only if it doesn't exist
conn.execute('''CREATE TABLE IF NOT EXISTS kart (
    kartId INTEGER PRIMARY KEY AUTOINCREMENT,
    userId INTEGER NOT NULL,
    productId INTEGER NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY(userId) REFERENCES users(userId),
    FOREIGN KEY(productId) REFERENCES products(productId)
)''')

# Older databases may already have a kart table without the quantity column
kart_columns = [row[1] for row in conn.execute('PRAGMA table_info(kart)')]
if 'quantity' not in kart_columns:
    conn.execute('ALTER TABLE kart ADD COLUMN quantity INTEGER NOT NULL DEFAULT 1')

# Collapse duplicate (userId, productId) lines, summing their quantities into the oldest row
conn.execute('''UPDATE kart
                SET quantity = (
                    SELECT SUM(k2.quantity) FROM kart k2
                    WHERE k2.userId = kart.userId AND k2.productId = kart.productId
                )
                WHERE rowid IN (SELECT MIN(rowid) FROM kart GROUP BY userId, productId)''')
conn.execute('''DELETE FROM kart
                WHERE rowid NOT IN (SELECT MIN(rowid) FROM kart GROUP BY userId, productId)''')

# Enforce one kart line per product per user
conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_kart_user_product ON kart(userId, productId)')

conn.commit()
conn.close()

print("Tables created successfully!")

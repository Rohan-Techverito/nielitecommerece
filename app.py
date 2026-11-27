from flask import *
import sqlite3, hashlib, os
from werkzeug.utils import secure_filename
import requests
from datetime import datetime
import pytz

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-in-production'  # Change this in production
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'jpeg', 'jpg', 'png', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
# Database location; configurable so tests can point at a temporary database.
app.config.setdefault('DATABASE', os.environ.get('NIELIT_DATABASE', 'database.db'))

# Accounts treated as administrators
ADMIN_EMAILS = ('admin@nielit.gov.in',)

# Ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

NOTIFICATIONS_TABLE_DDL = '''CREATE TABLE IF NOT EXISTS notifications (
    notificationId INTEGER PRIMARY KEY AUTOINCREMENT,
    userId INTEGER NOT NULL,
    message TEXT NOT NULL,
    createdAt TEXT NOT NULL,
    isRead INTEGER NOT NULL DEFAULT 0
)'''

NOTIFICATIONS_INDEX_DDL = '''CREATE INDEX IF NOT EXISTS idx_notifications_user_read
    ON notifications (userId, isRead, createdAt)'''

# Open a connection to the configured database
def connect_db():
    return sqlite3.connect(app.config.get('DATABASE', 'database.db'))

# Idempotently create the notifications table for existing databases
def ensure_notifications_table():
    try:
        conn = connect_db()
        try:
            conn.execute(NOTIFICATIONS_TABLE_DDL)
            conn.execute(NOTIFICATIONS_INDEX_DDL)
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error as e:
        print(f"Could not ensure notifications table: {e}")

ensure_notifications_table()

# Check if user is admin
def is_admin():
    return 'email' in session and session['email'] in ADMIN_EMAILS

# Return the signed-in user's details, or None when signed out or unknown
def get_session_user(cur):
    email = session.get('email')
    if not email:
        return None
    cur.execute("SELECT userId, firstName FROM users WHERE email = ?", (email,))
    row = cur.fetchone()
    if not row:
        return None
    return {'userId': row[0], 'firstName': row[1], 'email': email}

# Count only the given user's unread notifications
def get_unread_count(cur, userId):
    if userId is None:
        return 0
    cur.execute("SELECT COUNT(*) FROM notifications WHERE userId = ? AND isRead = 0", (userId,))
    row = cur.fetchone()
    count = row[0] if row else 0
    try:
        count = int(count)
    except (TypeError, ValueError):
        count = 0
    return max(0, count)

# Return the user ids of every configured administrator
def get_admin_user_ids(cur):
    if not ADMIN_EMAILS:
        return []
    placeholders = ','.join('?' for _ in ADMIN_EMAILS)
    cur.execute(
        "SELECT userId FROM users WHERE email IN ({})".format(placeholders),
        list(ADMIN_EMAILS)
    )
    return [row[0] for row in cur.fetchall()]

# Expose the signed-in user's unread count to every template
@app.context_processor
def inject_unread_notification_count():
    try:
        conn = connect_db()
        try:
            cur = conn.cursor()
            user = get_session_user(cur)
            if user is None:
                return {'unreadNotificationCount': None}
            return {'unreadNotificationCount': get_unread_count(cur, user['userId'])}
        finally:
            conn.close()
    except sqlite3.Error as e:
        print(f"Could not load unread notification count: {e}")
        return {'unreadNotificationCount': None}

# Home page
@app.route("/")
def root():
    loggedIn, firstName, noOfItems = getLoginDetails()
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute('SELECT productId, name, price, description, image, stock FROM products')
        itemData = cur.fetchall()
        cur.execute('SELECT categoryId, name FROM categories')
        categoryData = cur.fetchall()
    itemData = parse(itemData)   
    return render_template('home.html', itemData=itemData, loggedIn=loggedIn, firstName=firstName, noOfItems=noOfItems, categoryData=categoryData)

# Fetch user details if logged in
def getLoginDetails():
    with connect_db() as conn:
        cur = conn.cursor()
        if 'email' not in session:
            loggedIn = False
            firstName = ''
            noOfItems = 0
        else:
            loggedIn = True
            cur.execute("SELECT userId, firstName FROM users WHERE email = ?", (session['email'],))
            result = cur.fetchone()
            if result:
                userId, firstName = result
                cur.execute("SELECT count(productId) FROM kart WHERE userId = ?", (userId,))
                noOfItems = cur.fetchone()[0]
            else:
                loggedIn = False
                firstName = ''
                noOfItems = 0
    return (loggedIn, firstName, noOfItems)

@app.route("/admin")
def admin_dashboard():
    if not is_admin():
        return redirect(url_for('root'))
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute('SELECT * FROM products')
        products = cur.fetchall()
    return render_template("admin.html", products=products)

# Add new product (Admin only)
@app.route("/admin/add", methods=["GET", "POST"])
def add_product():
    if not is_admin():
        return redirect(url_for('root'))

    if request.method == "POST":
        name = request.form['name']
        price = float(request.form['price'])
        description = request.form['description']
        stock = int(request.form['stock'])
        categoryId = int(request.form['category'])

        # Upload image
        image = request.files['image']
        if image and allowed_file(image.filename):
            filename = secure_filename(image.filename)
            image.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            imagename = filename
        else:
            imagename = "product-default.png"  # Fallback image

        with connect_db() as conn:
            try:
                cur = conn.cursor()
                cur.execute('''INSERT INTO products (name, price, description, image, stock, categoryId) 
                               VALUES (?, ?, ?, ?, ?, ?)''', (name, price, description, imagename, stock, categoryId))
                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"Error adding product: {e}")

        return redirect(url_for('admin_dashboard'))

    # Fetch categories for dropdown
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute('SELECT categoryId, name FROM categories')
        categories = cur.fetchall()

    return render_template('add_product.html', categories=categories)

# Delete product (Admin only)
@app.route("/admin/delete/<int:productId>")
def delete_product(productId):
    if not is_admin():
        return redirect(url_for('root'))
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM products WHERE productId = ?", (productId,))
        conn.commit()
    return redirect(url_for('admin_dashboard'))

@app.route("/admin/edit/<int:productId>", methods=["GET", "POST"])
def edit_product(productId):
    if not is_admin():
        return redirect(url_for('root'))

    with connect_db() as conn:
        cur = conn.cursor()

        if request.method == "POST":
            name = request.form['name']
            price = float(request.form['price'])
            description = request.form['description']
            stock = int(request.form['stock'])
            categoryId = int(request.form['category'])

            # Handle image update
            image = request.files['image']
            if image and image.filename != "":  # If a new image is uploaded
                filename = secure_filename(image.filename)
                image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                image.save(image_path)

                cur.execute('''UPDATE products 
                               SET name=?, price=?, description=?, image=?, stock=?, categoryId=? 
                               WHERE productId=?''',
                            (name, price, description, filename, stock, categoryId, productId))
            else:
                cur.execute('''UPDATE products 
                               SET name=?, price=?, description=?, stock=?, categoryId=? 
                               WHERE productId=?''',
                            (name, price, description, stock, categoryId, productId))

            conn.commit()
            return redirect(url_for('admin_dashboard'))

        # Fetch product details
        cur.execute("SELECT * FROM products WHERE productId = ?", (productId,))
        product = cur.fetchone()

        # Fetch categories for dropdown
        cur.execute('SELECT categoryId, name FROM categories')
        categories = cur.fetchall()

    return render_template("edit_product.html", product=product, categories=categories)

# Display all items of a category
@app.route("/displayCategory")
def displayCategory():
    loggedIn, firstName, noOfItems = getLoginDetails()
    categoryId = request.args.get("categoryId")
    
    if not categoryId or not categoryId.isdigit():
        return redirect(url_for('root'))
    
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("""SELECT products.productId, products.name, products.price, products.image, categories.name 
                       FROM products, categories 
                       WHERE products.categoryId = categories.categoryId 
                       AND categories.categoryId = ?""", (categoryId,))
        data = cur.fetchall()
    
    if not data:
        return redirect(url_for('root'))
    
    categoryName = data[0][4]
    data = parse(data)
    return render_template('displayCategory.html', data=data, loggedIn=loggedIn, firstName=firstName, noOfItems=noOfItems, categoryName=categoryName)

@app.route("/account/profile")
def profileHome():
    if 'email' not in session:
        return redirect(url_for('root'))
    loggedIn, firstName, noOfItems = getLoginDetails()
    return render_template("profileHome.html", loggedIn=loggedIn, firstName=firstName, noOfItems=noOfItems)

@app.route("/account/profile/edit")
def editProfile():
    if 'email' not in session:
        return redirect(url_for('root'))
    loggedIn, firstName, noOfItems = getLoginDetails()
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT userId, email, firstName, lastName, address1, address2, zipcode, city, state, country, phone FROM users WHERE email = ?", (session['email'],))
        profileData = cur.fetchone()
    return render_template("editProfile.html", profileData=profileData, loggedIn=loggedIn, firstName=firstName, noOfItems=noOfItems)

@app.route("/account/profile/changePassword", methods=["GET", "POST"])
def changePassword():
    if 'email' not in session:
        return redirect(url_for('loginForm'))
    if request.method == "POST":
        oldPassword = request.form['oldpassword']
        oldPassword = hashlib.md5(oldPassword.encode()).hexdigest()
        newPassword = request.form['newpassword']
        newPassword = hashlib.md5(newPassword.encode()).hexdigest()
        with connect_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT userId, password FROM users WHERE email = ?", (session['email'],))
            result = cur.fetchone()
            if result:
                userId, password = result
                if password == oldPassword:
                    try:
                        cur.execute("UPDATE users SET password = ? WHERE userId = ?", (newPassword, userId))
                        conn.commit()
                        msg = "Changed successfully"
                    except:
                        conn.rollback()
                        msg = "Failed"
                else:
                    msg = "Wrong password"
            else:
                msg = "User not found"
        return render_template("changePassword.html", msg=msg)
    else:
        return render_template("changePassword.html")

@app.route("/updateProfile", methods=["GET", "POST"])
def updateProfile():
    if 'email' not in session:
        return redirect(url_for('root'))
    
    if request.method == 'POST':
        email = request.form['email']
        firstName = request.form['firstName']
        lastName = request.form['lastName']
        address1 = request.form['address1']
        address2 = request.form['address2']
        zipcode = request.form['zipcode']
        city = request.form['city']
        state = request.form['state']
        country = request.form['country']
        phone = request.form['phone']
        
        with connect_db() as con:
            try:
                cur = con.cursor()
                cur.execute('UPDATE users SET firstName = ?, lastName = ?, address1 = ?, address2 = ?, zipcode = ?, city = ?, state = ?, country = ?, phone = ? WHERE email = ?', 
                           (firstName, lastName, address1, address2, zipcode, city, state, country, phone, session['email']))
                con.commit()
                msg = "Saved Successfully"
            except Exception as e:
                con.rollback()
                msg = "Error occurred"
                print(f"Error updating profile: {e}")
        
        return redirect(url_for('editProfile'))

@app.route("/loginForm")
def loginForm():
    if 'email' in session:
        return redirect(url_for('root'))
    else:
        return render_template('login.html', error='')

@app.route("/login", methods=['POST', 'GET'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        if is_valid(email, password):
            session['email'] = email
            return redirect(url_for('root'))
        else:
            error = 'Invalid UserId / Password'
            return render_template('login.html', error=error)

@app.route("/productDescription")
def productDescription():
    loggedIn, firstName, noOfItems = getLoginDetails()
    productId = request.args.get('productId')
    
    if not productId or not productId.isdigit():
        return redirect(url_for('root'))
    
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute('SELECT productId, name, price, description, image, stock FROM products WHERE productId = ?', (productId,))
        productData = cur.fetchone()
    
    if not productData:
        return redirect(url_for('root'))
    
    return render_template("productDescription.html", data=productData, loggedIn=loggedIn, firstName=firstName, noOfItems=noOfItems)

@app.route("/addToCart")
def addToCart():
    if 'email' not in session:
        return redirect(url_for('loginForm'))
    else:
        productId = request.args.get('productId')
        if not productId or not productId.isdigit():
            return redirect(url_for('root'))
        
        productId = int(productId)
        with connect_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT userId FROM users WHERE email = ?", (session['email'],))
            result = cur.fetchone()
            if result:
                userId = result[0]
                try:
                    cur.execute("INSERT INTO kart (userId, productId) VALUES (?, ?)", (userId, productId))
                    conn.commit()
                    msg = "Added successfully"
                except:
                    conn.rollback()
                    msg = "Error occurred"
        return redirect(url_for('root'))

@app.route("/cart")
def cart():
    if 'email' not in session:
        return redirect(url_for('loginForm'))
    loggedIn, firstName, noOfItems = getLoginDetails()
    email = session['email']
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT userId FROM users WHERE email = ?", (email,))
        result = cur.fetchone()
        if result:
            userId = result[0]
            cur.execute("SELECT products.productId, products.name, products.price, products.image FROM products, kart WHERE products.productId = kart.productId AND kart.userId = ?", (userId,))
            products = cur.fetchall()
        else:
            products = []
    
    totalPrice = 0
    for row in products:
        totalPrice += row[2]
    return render_template("cart.html", products=products, totalPrice=totalPrice, loggedIn=loggedIn, firstName=firstName, noOfItems=noOfItems)

@app.route("/addToWishlist", methods=["GET", "POST"])
def add_to_wishlist():
    if 'email' not in session:
        return redirect(url_for('loginForm'))

    product_id = request.args.get('productId')
    if not product_id:
        product_id = request.form.get('productId')

    if not product_id or not product_id.isdigit():
        return redirect(url_for('root'))

    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT userId FROM users WHERE email = ?", (session['email'],))
        result = cur.fetchone()
        if result:
            user_id = result[0]
            # Check if product is already in the wishlist
            cur.execute("SELECT * FROM wishlist WHERE userId = ? AND productId = ?", (user_id, product_id))
            if not cur.fetchone():
                cur.execute("INSERT INTO wishlist (userId, productId) VALUES (?, ?)", (user_id, product_id))
                conn.commit()
    
    return redirect(url_for('wishlist'))

@app.route('/removeFromWishlist', methods=['POST'])
def remove_from_wishlist():
    if 'email' not in session:
        return redirect(url_for('loginForm'))

    product_id = request.form.get('productId')
    if not product_id:
        return redirect(url_for('wishlist'))

    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT userId FROM users WHERE email = ?", (session['email'],))
        result = cur.fetchone()
        if result:
            user_id = result[0]
            cur.execute("DELETE FROM wishlist WHERE userId=? AND productId=?", (user_id, product_id))
            conn.commit()

    return redirect(url_for('wishlist'))

@app.route('/wishlist')
def wishlist():
    if 'email' not in session:
        return redirect(url_for('loginForm'))

    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT userId FROM users WHERE email = ?", (session['email'],))
        result = cur.fetchone()
        if result:
            user_id = result[0]
            cur.execute('''SELECT products.productId, products.name, products.price, products.image
                            FROM wishlist
                            JOIN products ON wishlist.productId = products.productId
                            WHERE wishlist.userId = ?''', (user_id,))
            wishlist_items = cur.fetchall()
        else:
            wishlist_items = []

    return render_template('wishlist.html', wishlist_items=wishlist_items)

@app.route("/checkout")
def checkout():
    if 'email' not in session:
        return redirect(url_for('loginForm'))
    loggedIn, firstName, noOfItems = getLoginDetails()
    email = session['email']
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT userId FROM users WHERE email = ?", (email,))
        result = cur.fetchone()
        if result:
            userId = result[0]
            cur.execute("SELECT products.productId, products.name, products.price, products.image FROM products, kart WHERE products.productId = kart.productId AND kart.userId = ?", (userId,))
            products = cur.fetchall()
        else:
            products = []
    
    totalPrice = 0
    for row in products:
        totalPrice += row[2]
    return render_template("checkout.html", products=products, totalPrice=totalPrice, loggedIn=loggedIn, firstName=firstName, noOfItems=noOfItems)

@app.route("/saveorder")
def saveorder():
    if 'email' not in session:
        return redirect(url_for('loginForm'))

    ensure_notifications_table()

    # Get current IST timestamp
    ist = pytz.timezone('Asia/Kolkata')
    order_date = datetime.now(ist).strftime('%Y-%m-%d %H:%M:%S')

    with connect_db() as conn:
        cur = conn.cursor()

        # Get the signed-in shopper
        user = get_session_user(cur)
        if user is None:
            return redirect(url_for('root'))

        userId = user['userId']
        firstName = user['firstName']

        # Fetch products from the user's cart
        cur.execute("""
            SELECT kart.productId, COUNT(kart.productId) AS quantity, SUM(products.price) AS total_price
            FROM kart 
            JOIN products ON kart.productId = products.productId
            WHERE kart.userId = ?
            GROUP BY kart.productId
        """, (userId,))
        
        cart_items = cur.fetchall()

        # Save each cart item as an order, collecting ids and the summed total
        order_ids = []
        order_total = 0.0
        for item in cart_items:
            productId, quantity, total_price = item
            cur.execute("INSERT INTO allorders (userId, productId, quantity, total_price, order_date) VALUES (?, ?, ?, ?, ?)",
                        (userId, productId, quantity, total_price, order_date))
            order_ids.append(cur.lastrowid)
            try:
                order_total += float(total_price or 0)
            except (TypeError, ValueError):
                pass

        # Notify the shopper and every admin only when orders were created
        if order_ids:
            order_references = ', '.join('#{}'.format(order_id) for order_id in order_ids)
            if len(order_ids) == 1:
                shopper_message = "Your order {} was placed successfully. Total paid: Rs {:.2f}".format(
                    order_references, order_total)
            else:
                shopper_message = "Your orders {} were placed successfully. Total paid: Rs {:.2f}".format(
                    order_references, order_total)
            cur.execute(
                "INSERT INTO notifications (userId, message, createdAt, isRead) VALUES (?, ?, ?, 0)",
                (userId, shopper_message, order_date)
            )

            admin_message = "New order from {}. Order total: Rs {:.2f}".format(
                firstName or user['email'], order_total)
            for admin_user_id in get_admin_user_ids(cur):
                cur.execute(
                    "INSERT INTO notifications (userId, message, createdAt, isRead) VALUES (?, ?, ?, 0)",
                    (admin_user_id, admin_message, order_date)
                )

        # Clear the cart
        cur.execute("DELETE FROM kart WHERE userId = ?", (userId,))
        
        conn.commit()

    return render_template("order_confirmation.html", order_date=order_date)

def _extract_notification_ids():
    """Return the requested notification ids, or None when none were supplied."""
    payload = request.get_json(silent=True)
    raw_ids = None
    if isinstance(payload, dict):
        for key in ('ids', 'notificationIds'):
            if key in payload:
                raw_ids = payload[key]
                break
    elif isinstance(payload, list):
        raw_ids = payload

    if raw_ids is None:
        for key in ('ids', 'notificationIds'):
            values = request.form.getlist(key) or request.args.getlist(key)
            if values:
                raw_ids = values
                break

    if raw_ids is None:
        return None

    if isinstance(raw_ids, str):
        raw_ids = [part for part in raw_ids.split(',') if part.strip()]
    elif not isinstance(raw_ids, (list, tuple, set)):
        raw_ids = [raw_ids]

    expanded_ids = []
    for value in raw_ids:
        if isinstance(value, str):
            expanded_ids.extend(part for part in value.split(',') if part.strip())
        else:
            expanded_ids.append(value)

    ids = []
    for value in expanded_ids:
        if isinstance(value, bool):
            continue
        try:
            notification_id = int(value)
        except (TypeError, ValueError):
            continue
        if notification_id > 0:
            ids.append(notification_id)
    return ids

@app.route("/notifications")
def notifications():
    if 'email' not in session:
        return jsonify({'error': 'Authentication required'}), 401

    ensure_notifications_table()
    try:
        conn = connect_db()
        try:
            cur = conn.cursor()
            user = get_session_user(cur)
            if user is None:
                return jsonify({'error': 'Authentication required'}), 401
            userId = user['userId']

            cur.execute("""
                SELECT notificationId, message, createdAt, isRead
                FROM notifications
                WHERE userId = ?
                ORDER BY createdAt DESC, notificationId DESC
                LIMIT 20
            """, (userId,))
            rows = cur.fetchall()
            unread_count = get_unread_count(cur, userId)
        finally:
            conn.close()
    except sqlite3.Error as e:
        print(f"Error loading notifications: {e}")
        return jsonify({'error': 'Unable to load notifications'}), 500

    notification_rows = [{
        'id': row[0],
        'message': row[1],
        'createdAt': row[2],
        'isRead': bool(row[3])
    } for row in rows]

    return jsonify({
        'notifications': notification_rows,
        'unreadCount': unread_count
    })

@app.route("/notifications/mark-read", methods=["POST"])
def mark_notifications_read():
    if 'email' not in session:
        return jsonify({'error': 'Authentication required'}), 401

    ensure_notifications_table()
    ids = _extract_notification_ids()
    try:
        conn = connect_db()
        try:
            cur = conn.cursor()
            user = get_session_user(cur)
            if user is None:
                return jsonify({'error': 'Authentication required'}), 401
            userId = user['userId']

            if ids is None:
                cur.execute(
                    "UPDATE notifications SET isRead = 1 WHERE userId = ? AND isRead = 0",
                    (userId,)
                )
            elif ids:
                placeholders = ','.join('?' for _ in ids)
                cur.execute(
                    "UPDATE notifications SET isRead = 1 "
                    "WHERE userId = ? AND isRead = 0 AND notificationId IN ({})".format(placeholders),
                    [userId] + ids
                )
            conn.commit()
            unread_count = get_unread_count(cur, userId)
        finally:
            conn.close()
    except sqlite3.Error as e:
        print(f"Error marking notifications read: {e}")
        return jsonify({'error': 'Unable to update notifications'}), 500

    return jsonify({
        'success': True,
        'unreadCount': unread_count
    })

@app.route("/vieworders")
def vieworders():
    if not is_admin():
        return "Access Denied! Only admin can view orders.", 403

    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT allorders.orderId, users.firstName, users.lastName, users.email, 
                   products.name, allorders.quantity, allorders.total_price, allorders.order_date
            FROM allorders
            JOIN users ON allorders.userId = users.userId
            JOIN products ON allorders.productId = products.productId
            ORDER BY allorders.order_date DESC
        """)
        orders = cur.fetchall()

    return render_template("vieworders.html", orders=orders)

@app.route("/account/orders")
def user_orders():
    if 'email' not in session:
        return redirect(url_for('loginForm'))
    
    email = session['email']

    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT userId FROM users WHERE email = ?", (email,))
        result = cur.fetchone()

        if not result:
            return "User not found.", 404

        userId = result[0]

        # Fetch orders for the logged-in user
        cur.execute("""
            SELECT allorders.orderId, products.name, allorders.quantity, allorders.total_price, allorders.order_date
            FROM allorders
            JOIN products ON allorders.productId = products.productId
            WHERE allorders.userId = ?
            ORDER BY allorders.order_date DESC
        """, (userId,))

        orders = cur.fetchall()

    return render_template("user_orders.html", orders=orders)

@app.route("/removeFromCart")
def removeFromCart():
    if 'email' not in session:
        return redirect(url_for('loginForm'))
    
    email = session['email']
    productId = request.args.get('productId')
    
    if not productId or not productId.isdigit():
        return redirect(url_for('root'))
    
    productId = int(productId)
    
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT userId FROM users WHERE email = ?", (email,))
        result = cur.fetchone()
        if result:
            userId = result[0]
            try:
                cur.execute("DELETE FROM kart WHERE userId = ? AND productId = ?", (userId, productId))
                conn.commit()
                msg = "removed successfully"
            except:
                conn.rollback()
                msg = "error occurred"
    
    return redirect(url_for('root'))

@app.route("/logout")
def logout():
    session.pop('email', None)
    return redirect(url_for('root'))

def is_valid(email, password):
    with connect_db() as con:
        cur = con.cursor()
        cur.execute('SELECT email, password FROM users WHERE email = ?', (email,))
        result = cur.fetchone()
        if result and result[1] == hashlib.md5(password.encode()).hexdigest():
            return True
    return False

@app.route("/register", methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # Parse form data    
        password = request.form['password']
        email = request.form['email']
        firstName = request.form['firstName']
        lastName = request.form['lastName']
        address1 = request.form['address1']
        address2 = request.form['address2']
        zipcode = request.form['zipcode']
        city = request.form['city']
        state = request.form['state']
        country = request.form['country']
        phone = request.form['phone']

        with connect_db() as con:
            try:
                cur = con.cursor()
                cur.execute('INSERT INTO users (password, email, firstName, lastName, address1, address2, zipcode, city, state, country, phone) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', 
                           (hashlib.md5(password.encode()).hexdigest(), email, firstName, lastName, address1, address2, zipcode, city, state, country, phone))
                con.commit()
                msg = "Registered Successfully"
            except Exception as e:
                con.rollback()
                msg = "Error occurred"
                print(f"Registration error: {e}")
        
        return render_template("login.html", error=msg)

@app.route("/registerationForm")
def registrationForm():
    return render_template("register.html")

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def parse(data):
    ans = []
    i = 0
    while i < len(data):
        curr = []
        for j in range(7):
            if i >= len(data):
                break
            curr.append(data[i])
            i += 1
        ans.append(curr)
    return ans

if __name__ == '__main__':
    app.run(debug=True)

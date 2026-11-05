from __future__ import annotations

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

# Stock at or below this count is considered low ("Only N left")
STOCK_LOW_THRESHOLD: int = 5

# Availability label for a given stock count
def stock_status(stock: int | float | None) -> tuple[str, str]:
    available = int(stock or 0)
    if available <= 0:
        return ('Out of stock', 'stock-out')
    if available <= STOCK_LOW_THRESHOLD:
        return (f'Only {available} left', 'stock-low')
    return (f'In stock ({available} available)', 'stock-in')

# Make the availability label available in every template
app.jinja_env.globals['stock_status'] = stock_status

# Ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Check if user is admin
def is_admin():
    return 'email' in session and session['email'] == 'admin@nielit.gov.in'

# Home page
@app.route("/")
def root():
    loggedIn, firstName, noOfItems = getLoginDetails()
    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()
        cur.execute('SELECT productId, name, price, description, image, stock FROM products')
        itemData = cur.fetchall()
        cur.execute('SELECT categoryId, name FROM categories')
        categoryData = cur.fetchall()
    # Flat rows (productId, name, price, description, image, stock) so the grid can show availability
    return render_template('home.html', itemData=itemData, loggedIn=loggedIn, firstName=firstName, noOfItems=noOfItems, categoryData=categoryData)

# Fetch user details if logged in
def getLoginDetails() -> tuple[bool, str, int]:
    with sqlite3.connect('database.db') as conn:
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
                # Cart count is the total number of units, not the number of lines
                cur.execute("SELECT COALESCE(SUM(quantity), 0) FROM kart WHERE userId = ?", (userId,))
                noOfItems = cur.fetchone()[0]
            else:
                loggedIn = False
                firstName = ''
                noOfItems = 0
    return (loggedIn, firstName, noOfItems)

# Build the cart lines of a user with live price and stock read from products
def get_cart_items(userId: int) -> list[dict]:
    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()
        cur.execute("""SELECT products.productId, products.name, products.price, products.image, products.stock, kart.quantity
                       FROM kart
                       JOIN products ON kart.productId = products.productId
                       WHERE kart.userId = ?
                       ORDER BY products.name""", (userId,))
        rows = cur.fetchall()
    items = []
    for productId, name, price, image, stock, quantity in rows:
        items.append({
            'productId': productId,
            'name': name,
            'price': price,
            'image': image,
            'stock': stock,
            'quantity': quantity,
            'line_total': round(price * quantity, 2)
        })
    return items

# Carry a message (or per cart line messages) to the next cart page render
def set_cart_notice(message: str | None, line_messages: dict[int, str] | None = None) -> None:
    session['cart_notice'] = {'message': message, 'lines': dict(line_messages or {})}

def pop_cart_notice() -> dict:
    notice = session.pop('cart_notice', None)
    if not notice:
        return {'message': None, 'lines': {}}
    lines = {}
    # Keys come back from the session cookie as strings, so normalise them to ids
    for productId, text in (notice.get('lines') or {}).items():
        try:
            lines[int(productId)] = text
        except (TypeError, ValueError):
            continue
    return {'message': notice.get('message'), 'lines': lines}

@app.route("/admin")
def admin_dashboard():
    if not is_admin():
        return redirect(url_for('root'))
    with sqlite3.connect('database.db') as conn:
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

        with sqlite3.connect('database.db') as conn:
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
    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()
        cur.execute('SELECT categoryId, name FROM categories')
        categories = cur.fetchall()

    return render_template('add_product.html', categories=categories)

# Delete product (Admin only)
@app.route("/admin/delete/<int:productId>")
def delete_product(productId):
    if not is_admin():
        return redirect(url_for('root'))
    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM products WHERE productId = ?", (productId,))
        conn.commit()
    return redirect(url_for('admin_dashboard'))

@app.route("/admin/edit/<int:productId>", methods=["GET", "POST"])
def edit_product(productId):
    if not is_admin():
        return redirect(url_for('root'))

    with sqlite3.connect('database.db') as conn:
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
    
    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()
        cur.execute("""SELECT products.productId, products.name, products.price, products.image, products.stock, categories.name 
                       FROM products, categories 
                       WHERE products.categoryId = categories.categoryId 
                       AND categories.categoryId = ?""", (categoryId,))
        data = cur.fetchall()
    
    if not data:
        return redirect(url_for('root'))
    
    # Flat rows so every product renders its own image, price and availability
    categoryName = data[0][5]
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
    with sqlite3.connect('database.db') as conn:
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
        with sqlite3.connect('database.db') as conn:
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
        
        with sqlite3.connect('database.db') as con:
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

# Only local absolute paths are accepted, so 'next' cannot redirect off-site
def safe_redirect_target(target: str | None) -> str:
    if target and target.startswith('/') and not target.startswith('//'):
        return target
    return url_for('root')

@app.route("/loginForm")
def loginForm() -> Response:
    if 'email' in session:
        return redirect(url_for('root'))
    else:
        return render_template('login.html', error='', next=request.args.get('next', ''))

@app.route("/login", methods=['POST', 'GET'])
def login() -> Response:
    next_target = request.form.get('next') or request.args.get('next')
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        if is_valid(email, password):
            session['email'] = email
            return redirect(safe_redirect_target(next_target))
        else:
            error = 'Invalid UserId / Password'
            return render_template('login.html', error=error, next=next_target or '')
    return render_template('login.html', error='', next=next_target or '')

@app.route("/productDescription")
def productDescription():
    loggedIn, firstName, noOfItems = getLoginDetails()
    productId = request.args.get('productId')
    
    if not productId or not productId.isdigit():
        return redirect(url_for('root'))
    
    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()
        cur.execute('SELECT productId, name, price, description, image, stock FROM products WHERE productId = ?', (productId,))
        productData = cur.fetchone()
    
    if not productData:
        return redirect(url_for('root'))
    
    return render_template("productDescription.html", data=productData, loggedIn=loggedIn, firstName=firstName, noOfItems=noOfItems)

@app.route("/addToCart")
def addToCart() -> Response:
    if 'email' not in session:
        return redirect(url_for('loginForm', next=url_for('cart')))

    productId = request.args.get('productId')
    if not productId or not productId.isdigit():
        return redirect(url_for('root'))

    productId = int(productId)
    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()
        cur.execute("SELECT userId FROM users WHERE email = ?", (session['email'],))
        result = cur.fetchone()
        if not result:
            return redirect(url_for('root'))

        userId = result[0]

        # Stock is read live on every request, so admin edits apply to the next action
        cur.execute("SELECT stock FROM products WHERE productId = ?", (productId,))
        product = cur.fetchone()
        if not product:
            return redirect(url_for('root'))

        stock = int(product[0] or 0)
        if stock <= 0:
            # Out of stock: nothing is added and products.stock is never written
            return redirect(url_for('root'))

        cur.execute("SELECT quantity FROM kart WHERE userId = ? AND productId = ?", (userId, productId))
        line = cur.fetchone()

        line_messages = None
        try:
            if line:
                # Already in the cart: raise the quantity instead of adding a second line
                if int(line[0] or 0) >= stock:
                    line_messages = {productId: f'Only {stock} available'}
                else:
                    cur.execute("UPDATE kart SET quantity = MIN(quantity + 1, ?) WHERE userId = ? AND productId = ?",
                                (stock, userId, productId))
                    conn.commit()
            else:
                cur.execute("INSERT INTO kart (userId, productId, quantity) VALUES (?, ?, 1)", (userId, productId))
                conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            print(f"Error adding to cart: {e}")

    if line_messages:
        set_cart_notice(None, line_messages)

    return redirect(url_for('root'))

@app.route("/cart")
def cart() -> Response:
    if 'email' not in session:
        return redirect(url_for('loginForm', next=url_for('cart')))
    loggedIn, firstName, noOfItems = getLoginDetails()
    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()
        cur.execute("SELECT userId FROM users WHERE email = ?", (session['email'],))
        result = cur.fetchone()

    userId = result[0] if result else None
    items = get_cart_items(userId) if userId is not None else []
    totalPrice = round(sum(item['line_total'] for item in items), 2)
    return render_template("cart.html", items=items, totalPrice=totalPrice, notice=pop_cart_notice(), loggedIn=loggedIn, firstName=firstName, noOfItems=noOfItems)

# Change the quantity of a cart line (or remove it); stock is only ever read here
@app.route('/cart/update', methods=['POST'])
def update_cart_quantity() -> Response:
    if 'email' not in session:
        return redirect(url_for('loginForm', next=url_for('cart')))

    productId = request.form.get('productId')
    action = request.form.get('action')
    if not productId or not productId.isdigit() or action not in ('increase', 'decrease', 'remove'):
        return redirect(url_for('cart'))

    productId = int(productId)
    line_messages = None

    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()
        cur.execute("SELECT userId FROM users WHERE email = ?", (session['email'],))
        result = cur.fetchone()
        if not result:
            return redirect(url_for('cart'))

        userId = result[0]

        if action == 'remove':
            cur.execute("DELETE FROM kart WHERE userId = ? AND productId = ?", (userId, productId))
            conn.commit()
            return redirect(url_for('cart'))

        # Quantity and stock are re-read on every action; products.stock is never written here
        cur.execute("""SELECT kart.quantity, products.stock
                       FROM kart
                       JOIN products ON kart.productId = products.productId
                       WHERE kart.userId = ? AND kart.productId = ?""", (userId, productId))
        line = cur.fetchone()
        if not line:
            # The line, or the product behind it, is gone: drop the leftover kart row
            cur.execute("DELETE FROM kart WHERE userId = ? AND productId = ?", (userId, productId))
            conn.commit()
            return redirect(url_for('cart'))

        quantity = int(line[0] or 0)
        stock = int(line[1] or 0)

        if action == 'decrease':
            # Decrementing a single unit removes the line from the cart
            new_quantity = min(quantity - 1, stock)
            if new_quantity <= 0:
                cur.execute("DELETE FROM kart WHERE userId = ? AND productId = ?", (userId, productId))
            else:
                cur.execute("UPDATE kart SET quantity = ? WHERE userId = ? AND productId = ?",
                            (new_quantity, userId, productId))
            conn.commit()
            return redirect(url_for('cart'))

        # action == 'increase': the line never goes above the available stock
        new_quantity = min(quantity + 1, stock)
        if new_quantity > quantity:
            cur.execute("UPDATE kart SET quantity = ? WHERE userId = ? AND productId = ?",
                        (new_quantity, userId, productId))
            conn.commit()
        else:
            if new_quantity < quantity:
                # Stock fell below the stored quantity: clamp the line down to what is available
                if new_quantity <= 0:
                    cur.execute("DELETE FROM kart WHERE userId = ? AND productId = ?", (userId, productId))
                else:
                    cur.execute("UPDATE kart SET quantity = ? WHERE userId = ? AND productId = ?",
                                (new_quantity, userId, productId))
                conn.commit()
            line_messages = {productId: f'Only {stock} available'}

    if line_messages:
        set_cart_notice(None, line_messages)

    return redirect(url_for('cart'))

@app.route("/addToWishlist", methods=["GET", "POST"])
def add_to_wishlist():
    if 'email' not in session:
        return redirect(url_for('loginForm'))

    product_id = request.args.get('productId')
    if not product_id:
        product_id = request.form.get('productId')

    if not product_id or not product_id.isdigit():
        return redirect(url_for('root'))

    with sqlite3.connect('database.db') as conn:
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

    with sqlite3.connect('database.db') as conn:
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

    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()
        cur.execute("SELECT userId FROM users WHERE email = ?", (session['email'],))
        result = cur.fetchone()
        if result:
            user_id = result[0]
            cur.execute('''SELECT products.productId, products.name, products.price, products.image, products.stock
                            FROM wishlist
                            JOIN products ON wishlist.productId = products.productId
                            WHERE wishlist.userId = ?''', (user_id,))
            wishlist_items = cur.fetchall()
        else:
            wishlist_items = []

    return render_template('wishlist.html', wishlist_items=wishlist_items)

@app.route("/checkout")
def checkout() -> Response:
    if 'email' not in session:
        return redirect(url_for('loginForm', next=url_for('cart')))
    loggedIn, firstName, noOfItems = getLoginDetails()
    email = session['email']
    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()
        cur.execute("SELECT userId FROM users WHERE email = ?", (email,))
        result = cur.fetchone()

    userId = result[0] if result else None
    # Same rows the cart page shows, so the prices displayed here are the prices the order will use
    items = get_cart_items(userId) if userId is not None else []
    totalPrice = round(sum(item['line_total'] for item in items), 2)
    return render_template("checkout.html", items=items, totalPrice=totalPrice, loggedIn=loggedIn, firstName=firstName, noOfItems=noOfItems)

# Place an order for a user's cart atomically: validate stock, decrement it, record the order rows
# and clear the cart in one transaction, so nothing is oversold and stock never goes negative
def place_order(userId: int, order_date: str) -> dict:
    result = {'status': 'empty', 'lines': [], 'total': 0.0, 'message': '', 'line_messages': {}}
    # isolation_level=None so BEGIN IMMEDIATE can be issued by hand and held for the whole order
    conn = sqlite3.connect('database.db', isolation_level=None)
    in_transaction = False
    try:
        cur = conn.cursor()

        # Cart lines whose product was deleted by an admin leave the cart and the order
        cur.execute('BEGIN IMMEDIATE')
        in_transaction = True
        cur.execute("""SELECT kart.productId
                       FROM kart
                       LEFT JOIN products ON kart.productId = products.productId
                       WHERE kart.userId = ? AND products.productId IS NULL""", (userId,))
        missing = [row[0] for row in cur.fetchall()]
        if missing:
            cur.executemany("DELETE FROM kart WHERE userId = ? AND productId = ?",
                            [(userId, productId) for productId in missing])
            cur.execute('COMMIT')
            in_transaction = False
            result.update({
                'status': 'removed',
                'message': 'An item in your cart is no longer available, so it has been removed from your '
                           'cart. No order was placed - please review your cart.'
            })
            return result

        # Re-read the cart with live prices and stock inside the write transaction
        cur.execute("""SELECT kart.productId, products.name, products.price, products.stock, kart.quantity
                       FROM kart
                       JOIN products ON kart.productId = products.productId
                       WHERE kart.userId = ?
                       ORDER BY products.name""", (userId,))
        rows = cur.fetchall()

        lines = []
        shortages = []
        for productId, name, price, stock, quantity in rows:
            stock = int(stock or 0)
            quantity = int(quantity or 0)
            if quantity <= 0:
                continue
            lines.append({
                'productId': productId,
                'name': name,
                'unit_price': price,
                'quantity': quantity,
                'line_total': round(price * quantity, 2)
            })
            if quantity > stock:
                shortages.append((productId, name, stock))

        if not lines:
            cur.execute('ROLLBACK')
            in_transaction = False
            return result

        if shortages:
            # Nothing is ordered: every offending line drops to what is available (0 removes it)
            for productId, name, stock in shortages:
                if stock > 0:
                    cur.execute("UPDATE kart SET quantity = ? WHERE userId = ? AND productId = ?",
                                (stock, userId, productId))
                else:
                    cur.execute("DELETE FROM kart WHERE userId = ? AND productId = ?", (userId, productId))
            cur.execute('COMMIT')
            in_transaction = False
            result.update({
                'status': 'short',
                'message': 'Your order was not placed because these items are no longer available in the '
                           'requested quantity: '
                           + '; '.join(f'{name} (only {stock} available)' for productId, name, stock in shortages)
                           + '. Your cart has been adjusted - please review it before ordering.',
                'line_messages': {productId: f'{name}: only {stock} available' for productId, name, stock in shortages}
            })
            return result

        # Every line fits: decrement conditionally, record the order and clear the cart in one commit
        lines_total = 0.0
        for line in lines:
            productId = line['productId']
            quantity = line['quantity']
            cur.execute("UPDATE products SET stock = stock - ? WHERE productId = ? AND stock >= ?",
                        (quantity, productId, quantity))
            if cur.rowcount != 1:
                # Another shopper took the stock first: undo the whole order
                cur.execute('ROLLBACK')
                in_transaction = False
                result.update({
                    'status': 'short',
                    'lines': [],
                    'total': 0.0,
                    'message': f'{line["name"]} just sold out, so your order was not placed. '
                               'Please review your cart.',
                    'line_messages': {productId: f'{line["name"]} just sold out'}
                })
                return result
            cur.execute("INSERT INTO allorders (userId, productId, quantity, total_price, order_date) VALUES (?, ?, ?, ?, ?)",
                        (userId, productId, quantity, line['line_total'], order_date))
            lines_total += line['line_total']

        cur.execute("DELETE FROM kart WHERE userId = ?", (userId,))
        cur.execute('COMMIT')
        in_transaction = False
        result.update({'status': 'placed', 'lines': lines, 'total': round(lines_total, 2)})
        return result
    except sqlite3.Error as e:
        if in_transaction:
            try:
                conn.execute('ROLLBACK')
            except sqlite3.Error:
                pass
        print(f"Error placing order: {e}")
        return {
            'status': 'short',
            'lines': [],
            'total': 0.0,
            'message': 'Your order could not be placed. Please review your cart and try again.',
            'line_messages': {}
        }
    finally:
        conn.close()

@app.route("/saveorder", methods=['POST'])
def saveorder() -> Response:
    if 'email' not in session:
        return redirect(url_for('loginForm', next=url_for('cart')))

    email = session['email']

    # Get current IST timestamp
    ist = pytz.timezone('Asia/Kolkata')
    order_date = datetime.now(ist).strftime('%Y-%m-%d %H:%M:%S')

    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()
        cur.execute("SELECT userId FROM users WHERE email = ?", (email,))
        result = cur.fetchone()

    if not result:
        return redirect(url_for('root'))

    # All database work (validation, stock decrement, order rows) happens inside place_order
    outcome = place_order(result[0], order_date)

    if outcome['status'] == 'placed':
        return render_template("order_confirmation.html", order_lines=outcome['lines'],
                               order_total=outcome['total'], order_date=order_date)

    if outcome['status'] == 'empty':
        set_cart_notice('Your cart is empty.')
        return redirect(url_for('cart'))

    # 'removed' or 'short': tell the shopper what changed and send them back to the cart
    set_cart_notice(outcome['message'], outcome['line_messages'])
    return redirect(url_for('cart'))

@app.route("/vieworders")
def vieworders():
    if not is_admin():
        return "Access Denied! Only admin can view orders.", 403

    with sqlite3.connect('database.db') as conn:
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

    with sqlite3.connect('database.db') as conn:
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
    
    with sqlite3.connect('database.db') as conn:
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
    with sqlite3.connect('database.db') as con:
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

        with sqlite3.connect('database.db') as con:
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

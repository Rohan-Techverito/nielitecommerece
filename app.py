from flask import *
import sqlite3, hashlib, os
from werkzeug.utils import secure_filename
import requests
from datetime import datetime
import pytz

from validators import (
    validate_category,
    validate_confirmation,
    validate_email,
    validate_name,
    validate_optional_text,
    validate_password,
    validate_phone,
    validate_price,
    validate_required_text,
    validate_stock,
    validate_zipcode,
)

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-in-production'  # Change this in production
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'jpeg', 'jpg', 'png', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Check if user is admin
def is_admin():
    return 'email' in session and session['email'] == 'admin@nielit.gov.in'


def _product_form_values(form):
    """Return the submitted product values used for validation and display."""
    return {
        'name': (form.get('name') or '').strip(),
        'price': (form.get('price') or '').strip(),
        'description': form.get('description') or '',
        'stock': (form.get('stock') or '').strip(),
        'category': (form.get('category') or '').strip(),
    }


def _validate_product_form(form, categories):
    """Validate an add/edit product submission.

    Returns ``(errors, values, cleaned)``.  ``values`` keeps what the person
    typed so the form can be repopulated, while ``cleaned`` contains the typed
    values converted for use in SQL.
    """
    values = _product_form_values(form)
    errors = {}

    name, error = validate_name(values['name'], 'Product name')
    if error:
        errors['name'] = error

    price, error = validate_price(values['price'], 'Price')
    if error:
        errors['price'] = error

    description, error = validate_optional_text(values['description'], 'Description')
    if error:
        errors['description'] = error

    stock, error = validate_stock(values['stock'], 'Stock')
    if error:
        errors['stock'] = error

    category_id, error = validate_category(values['category'], categories)
    if error:
        errors['category'] = error

    cleaned = {
        'name': name,
        'price': price,
        'description': description,
        'stock': stock,
        'categoryId': category_id,
    }
    return errors, values, cleaned


def _fetch_categories(cur):
    cur.execute('SELECT categoryId, name FROM categories')
    return cur.fetchall()

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
    itemData = parse(itemData)   
    return render_template('home.html', itemData=itemData, loggedIn=loggedIn, firstName=firstName, noOfItems=noOfItems, categoryData=categoryData)

# Fetch user details if logged in
def getLoginDetails():
    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()
        if 'email' not in session:
            loggedIn = False
            firstName = ''
            noOfItems = 0
        else:
            loggedIn = True
            cur.execute("SELECT userId, firstName FROM users WHERE LOWER(email) = LOWER(?)", (session['email'],))
            result = cur.fetchone()
            if result:
                userId, firstName = result
                try:
                    cur.execute("SELECT count(productId) FROM kart WHERE userId = ?", (userId,))
                    noOfItems = cur.fetchone()[0]
                except sqlite3.Error:
                    noOfItems = 0
            else:
                loggedIn = False
                firstName = ''
                noOfItems = 0
    return (loggedIn, firstName, noOfItems)

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

    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()
        categories = _fetch_categories(cur)

    if request.method == "POST":
        errors, values, cleaned = _validate_product_form(request.form, categories)
        if errors:
            return render_template('add_product.html', categories=categories, errors=errors, values=values)

        # Upload image only after the submitted values have passed validation.
        image = request.files.get('image')
        imagename = "product-default.png"  # Fallback image
        saved_image_path = None
        if image and allowed_file(image.filename):
            filename = secure_filename(image.filename)
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            try:
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                image.save(image_path)
                imagename = filename
                saved_image_path = image_path
            except Exception:
                errors['form'] = "Something went wrong while saving the image. Please try again."
                return render_template('add_product.html', categories=categories, errors=errors, values=values)

        with sqlite3.connect('database.db') as conn:
            try:
                cur = conn.cursor()
                cur.execute('''INSERT INTO products (name, price, description, image, stock, categoryId) 
                               VALUES (?, ?, ?, ?, ?, ?)''', (cleaned['name'], cleaned['price'], cleaned['description'], imagename, cleaned['stock'], cleaned['categoryId']))
                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"Error adding product: {e}")
                if saved_image_path and os.path.exists(saved_image_path):
                    try:
                        os.remove(saved_image_path)
                    except OSError:
                        pass
                errors['form'] = "Could not add the product. Please try again."
                return render_template('add_product.html', categories=categories, errors=errors, values=values)

        return redirect(url_for('admin_dashboard'))

    return render_template('add_product.html', categories=categories, errors={}, values={})

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

        # Fetch product details
        cur.execute("SELECT * FROM products WHERE productId = ?", (productId,))
        product = cur.fetchone()

        # Fetch categories for dropdown
        categories = _fetch_categories(cur)

        if product is None:
            return redirect(url_for('admin_dashboard'))

        if request.method == "POST":
            errors, values, cleaned = _validate_product_form(request.form, categories)
            if errors:
                return render_template("edit_product.html", product=product, categories=categories, errors=errors, values=values)

            # Handle image update only after the submitted values are valid.
            image = request.files.get('image')
            filename = None
            saved_image_path = None
            if image and image.filename != "":  # If a new image is uploaded
                filename = secure_filename(image.filename)
                image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                try:
                    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                    image.save(image_path)
                    saved_image_path = image_path
                except Exception:
                    errors['form'] = "Something went wrong while saving the image. Please try again."
                    return render_template("edit_product.html", product=product, categories=categories, errors=errors, values=values)

            try:
                if filename is not None:
                    cur.execute('''UPDATE products 
                                   SET name=?, price=?, description=?, image=?, stock=?, categoryId=? 
                                   WHERE productId=?''',
                                (cleaned['name'], cleaned['price'], cleaned['description'], filename, cleaned['stock'], cleaned['categoryId'], productId))
                else:
                    cur.execute('''UPDATE products 
                                   SET name=?, price=?, description=?, stock=?, categoryId=? 
                                   WHERE productId=?''',
                                (cleaned['name'], cleaned['price'], cleaned['description'], cleaned['stock'], cleaned['categoryId'], productId))

                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"Error updating product: {e}")
                if saved_image_path and os.path.exists(saved_image_path):
                    try:
                        os.remove(saved_image_path)
                    except OSError:
                        pass
                errors['form'] = "Could not save the product. Please try again."
                return render_template("edit_product.html", product=product, categories=categories, errors=errors, values=values)

            return redirect(url_for('admin_dashboard'))

    return render_template("edit_product.html", product=product, categories=categories, errors={}, values={})

# Display all items of a category
@app.route("/displayCategory")
def displayCategory():
    loggedIn, firstName, noOfItems = getLoginDetails()
    categoryId = request.args.get("categoryId")
    
    if not categoryId or not categoryId.isdigit():
        return redirect(url_for('root'))
    
    with sqlite3.connect('database.db') as conn:
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

@app.route("/account/profile/edit", methods=["GET", "POST"])
def editProfile():
    if request.method == "POST":
        return updateProfile()
    if 'email' not in session:
        return redirect(url_for('root'))
    loggedIn, firstName, noOfItems = getLoginDetails()
    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()
        cur.execute("SELECT userId, email, firstName, lastName, address1, address2, zipcode, city, state, country, phone FROM users WHERE LOWER(email) = LOWER(?)", (session['email'],))
        profileData = cur.fetchone()
    return render_template("editProfile.html", profileData=profileData, loggedIn=loggedIn, firstName=firstName, noOfItems=noOfItems, errors={}, values={})

@app.route("/account/profile/changePassword", methods=["GET", "POST"])
def changePassword():
    if 'email' not in session:
        return redirect(url_for('loginForm'))
    if request.method == "POST":
        oldPasswordValue = request.form.get('oldpassword') or ''
        newPasswordValue = request.form.get('newpassword') or ''
        confirmPasswordValue = request.form.get('cpassword') or ''
        errors = {}

        if not oldPasswordValue:
            errors['oldpassword'] = "Current password is required."

        newPassword, error = validate_password(newPasswordValue)
        if error:
            errors['newpassword'] = error

        if not confirmPasswordValue:
            errors['cpassword'] = "Please confirm the new password."
        elif confirmPasswordValue != newPasswordValue:
            errors['cpassword'] = "Passwords do not match."

        try:
            with sqlite3.connect('database.db') as conn:
                cur = conn.cursor()
                cur.execute("SELECT userId, password FROM users WHERE LOWER(email) = LOWER(?)", (session['email'],))
                result = cur.fetchone()
                if not result:
                    errors['form'] = "We could not find your account. Please sign in again."
                else:
                    userId, password = result
                    oldPassword = hashlib.md5(oldPasswordValue.encode()).hexdigest()
                    if oldPasswordValue and password != oldPassword:
                        errors['oldpassword'] = "Current password is incorrect."

                    if newPassword and hashlib.md5(newPassword.encode()).hexdigest() == password:
                        errors['newpassword'] = "New password must be different from the current password."

                    if not errors:
                        cur.execute("UPDATE users SET password = ? WHERE userId = ?",
                                    (hashlib.md5(newPassword.encode()).hexdigest(), userId))
                        conn.commit()
                        msg = "Changed successfully"
        except Exception:
            errors['form'] = "Unable to change your password right now. Please try again."

        if errors:
            return render_template("changePassword.html", errors=errors)
        return render_template("changePassword.html", msg=msg, errors={})
    else:
        return render_template("changePassword.html", errors={})

@app.route("/updateProfile", methods=["GET", "POST"])
def updateProfile():
    if 'email' not in session:
        return redirect(url_for('root'))
    
    if request.method == 'POST':
        values = {
            'email': (request.form.get('email') or '').strip(),
            'firstName': (request.form.get('firstName') or '').strip(),
            'lastName': (request.form.get('lastName') or '').strip(),
            'address1': request.form.get('address1') or '',
            'address2': request.form.get('address2') or '',
            'zipcode': (request.form.get('zipcode') or '').strip(),
            'city': (request.form.get('city') or '').strip(),
            'state': (request.form.get('state') or '').strip(),
            'country': (request.form.get('country') or '').strip(),
            'phone': (request.form.get('phone') or '').strip(),
        }
        errors = {}

        email, error = validate_email(values['email'])
        if error:
            errors['email'] = error

        firstName, error = validate_name(values['firstName'], 'First name')
        if error:
            errors['firstName'] = error

        lastName, error = validate_name(values['lastName'], 'Last name')
        if error:
            errors['lastName'] = error

        address1, error = validate_optional_text(values['address1'], 'Address line 1')
        if error:
            errors['address1'] = error

        address2, error = validate_optional_text(values['address2'], 'Address line 2')
        if error:
            errors['address2'] = error

        zipcode, error = validate_zipcode(values['zipcode'])
        if error:
            errors['zipcode'] = error

        city, error = validate_required_text(values['city'], 'City')
        if error:
            errors['city'] = error

        state, error = validate_required_text(values['state'], 'State')
        if error:
            errors['state'] = error

        country, error = validate_required_text(values['country'], 'Country')
        if error:
            errors['country'] = error

        phone, error = validate_phone(values['phone'])
        if error:
            errors['phone'] = error

        if 'email' not in errors:
            with sqlite3.connect('database.db') as conn:
                cur = conn.cursor()
                cur.execute("SELECT userId FROM users WHERE LOWER(email) = LOWER(?)", (session['email'],))
                currentUser = cur.fetchone()
                if currentUser:
                    cur.execute("SELECT userId FROM users WHERE LOWER(email) = LOWER(?) AND userId != ?", (email, currentUser[0]))
                    if cur.fetchone():
                        errors['email'] = "This email address belongs to another account."
                else:
                    cur.execute("SELECT userId FROM users WHERE LOWER(email) = LOWER(?)", (email,))
                    if cur.fetchone():
                        errors['email'] = "This email address belongs to another account."

        if errors:
            loggedIn, navFirstName, noOfItems = getLoginDetails()
            with sqlite3.connect('database.db') as conn:
                cur = conn.cursor()
                cur.execute("SELECT userId, email, firstName, lastName, address1, address2, zipcode, city, state, country, phone FROM users WHERE LOWER(email) = LOWER(?)", (session['email'],))
                profileData = cur.fetchone()
            return render_template("editProfile.html", profileData=profileData, loggedIn=loggedIn, firstName=navFirstName, noOfItems=noOfItems, errors=errors, values=values)

        try:
            with sqlite3.connect('database.db') as con:
                cur = con.cursor()
                cur.execute('UPDATE users SET firstName = ?, lastName = ?, address1 = ?, address2 = ?, zipcode = ?, city = ?, state = ?, country = ?, phone = ? WHERE LOWER(email) = LOWER(?)', 
                           (firstName, lastName, address1, address2, zipcode, city, state, country, phone, session['email']))
                con.commit()
        except Exception as e:
            print(f"Error updating profile: {e}")
            errors['form'] = "Could not save your profile right now. Please try again."
            loggedIn, navFirstName, noOfItems = getLoginDetails()
            with sqlite3.connect('database.db') as conn:
                cur = conn.cursor()
                cur.execute("SELECT userId, email, firstName, lastName, address1, address2, zipcode, city, state, country, phone FROM users WHERE LOWER(email) = LOWER(?)", (session['email'],))
                profileData = cur.fetchone()
            return render_template("editProfile.html", profileData=profileData, loggedIn=loggedIn, firstName=navFirstName, noOfItems=noOfItems, errors=errors, values=values)

        return redirect(url_for('editProfile'))

    loggedIn, firstName, noOfItems = getLoginDetails()
    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()
        cur.execute("SELECT userId, email, firstName, lastName, address1, address2, zipcode, city, state, country, phone FROM users WHERE LOWER(email) = LOWER(?)", (session['email'],))
        profileData = cur.fetchone()
    return render_template("editProfile.html", profileData=profileData, loggedIn=loggedIn, firstName=firstName, noOfItems=noOfItems, errors={}, values={})

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
    
    with sqlite3.connect('database.db') as conn:
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
        with sqlite3.connect('database.db') as conn:
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
    with sqlite3.connect('database.db') as conn:
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
    with sqlite3.connect('database.db') as conn:
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
    
    email = session['email']
    
    # Get current IST timestamp
    ist = pytz.timezone('Asia/Kolkata')
    order_date = datetime.now(ist).strftime('%Y-%m-%d %H:%M:%S')

    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()

        # Get user ID
        cur.execute("SELECT userId FROM users WHERE email = ?", (email,))
        result = cur.fetchone()
        if not result:
            return redirect(url_for('root'))
        
        userId = result[0]

        # Fetch products from the user's cart
        cur.execute("""
            SELECT kart.productId, COUNT(kart.productId) AS quantity, SUM(products.price) AS total_price
            FROM kart 
            JOIN products ON kart.productId = products.productId
            WHERE kart.userId = ?
            GROUP BY kart.productId
        """, (userId,))
        
        cart_items = cur.fetchall()

        # Save each cart item as an order
        for item in cart_items:
            productId, quantity, total_price = item
            cur.execute("INSERT INTO allorders (userId, productId, quantity, total_price, order_date) VALUES (?, ?, ?, ?, ?)",
                        (userId, productId, quantity, total_price, order_date))

        # Clear the cart
        cur.execute("DELETE FROM kart WHERE userId = ?", (userId,))
        
        conn.commit()

    return render_template("order_confirmation.html", order_date=order_date)

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
        # Collect values defensively so a direct POST without every field is
        # reported next to the field instead of raising an exception.
        values = {
            'email': (request.form.get('email') or '').strip(),
            'firstName': (request.form.get('firstName') or '').strip(),
            'lastName': (request.form.get('lastName') or '').strip(),
            'address1': request.form.get('address1') or '',
            'address2': request.form.get('address2') or '',
            'zipcode': (request.form.get('zipcode') or '').strip(),
            'city': (request.form.get('city') or '').strip(),
            'state': (request.form.get('state') or '').strip(),
            'country': (request.form.get('country') or '').strip(),
            'phone': (request.form.get('phone') or '').strip(),
        }
        passwordValue = request.form.get('password') or ''
        confirmPasswordValue = request.form.get('cpassword') or ''
        errors = {}

        email, error = validate_email(values['email'])
        if error:
            errors['email'] = error

        firstName, error = validate_name(values['firstName'], 'First name')
        if error:
            errors['firstName'] = error

        lastName, error = validate_name(values['lastName'], 'Last name')
        if error:
            errors['lastName'] = error

        address1, error = validate_optional_text(values['address1'], 'Address line 1')
        if error:
            errors['address1'] = error

        address2, error = validate_optional_text(values['address2'], 'Address line 2')
        if error:
            errors['address2'] = error

        zipcode, error = validate_zipcode(values['zipcode'])
        if error:
            errors['zipcode'] = error

        city, error = validate_required_text(values['city'], 'City')
        if error:
            errors['city'] = error

        state, error = validate_required_text(values['state'], 'State')
        if error:
            errors['state'] = error

        country, error = validate_required_text(values['country'], 'Country')
        if error:
            errors['country'] = error

        phone, error = validate_phone(values['phone'])
        if error:
            errors['phone'] = error

        password, error = validate_password(passwordValue)
        if error:
            errors['password'] = error
        else:
            _, error = validate_confirmation(confirmPasswordValue, password)
            if error:
                errors['cpassword'] = error

        if 'email' not in errors:
            with sqlite3.connect('database.db') as con:
                cur = con.cursor()
                cur.execute('SELECT userId FROM users WHERE LOWER(email) = LOWER(?)', (email,))
                if cur.fetchone():
                    errors['email'] = "An account with this email already exists."

        if errors:
            return render_template("register.html", errors=errors, values=values)

        with sqlite3.connect('database.db') as con:
            try:
                cur = con.cursor()
                cur.execute('INSERT INTO users (password, email, firstName, lastName, address1, address2, zipcode, city, state, country, phone) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', 
                           (hashlib.md5(password.encode()).hexdigest(), email, firstName, lastName, address1, address2, zipcode, city, state, country, phone))
                con.commit()
            except Exception as e:
                con.rollback()
                print(f"Registration error: {e}")
                errors['form'] = "Could not create your account right now. Please try again."
                return render_template("register.html", errors=errors, values=values)

        return render_template("login.html", error="Registered Successfully")

    return render_template("register.html", errors={}, values={})

@app.route("/registerationForm")
def registrationForm():
    return render_template("register.html", errors={}, values={})

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

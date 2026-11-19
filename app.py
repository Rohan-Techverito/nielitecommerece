from flask import *
import sqlite3, hashlib, os
from werkzeug.utils import secure_filename
import requests
from datetime import datetime
import pytz

import validators

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-in-production'  # Change this in production
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'jpeg', 'jpg', 'png', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Friendly error pages: never show a raw error page or technical detail
@app.errorhandler(400)
def handle_bad_request(error):
    return render_template('error.html', message='We could not understand that request.'), 400

@app.errorhandler(404)
def handle_not_found(error):
    return render_template('error.html', message='We could not find the page you were looking for.'), 404

@app.errorhandler(500)
def handle_server_error(error):
    app.logger.exception('Unhandled error while serving %s', request.path)
    return render_template('error.html', message='Something went wrong on our side. Please try again.'), 500

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
        form = {
            'name': request.form.get('name', ''),
            'price': request.form.get('price', ''),
            'description': request.form.get('description', ''),
            'stock': request.form.get('stock', ''),
            'category': request.form.get('category', ''),
        }
        errors = {}

        with sqlite3.connect('database.db') as conn:
            cur = conn.cursor()
            cur.execute('SELECT categoryId, name FROM categories')
            categories = cur.fetchall()
        validCategoryIds = [category[0] for category in categories]

        form['name'], error = validators.text_field(form['name'], 'Product name')
        if error:
            errors['name'] = error
        error = validators.price_error(form['price'])
        if error:
            errors['price'] = error
        error = validators.stock_error(form['stock'])
        if error:
            errors['stock'] = error
        error = validators.category_error(form['category'], validCategoryIds)
        if error:
            errors['category'] = error

        if errors:
            return render_template('add_product.html', errors=errors, form=form, categories=categories)

        name = form['name']
        price = float(form['price'])
        description = form['description']
        stock = int(form['stock'])
        categoryId = int(form['category'])

        # Upload image
        image = request.files.get('image')
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

    return render_template('add_product.html', categories=categories, errors={}, form={})

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
        cur.execute('SELECT categoryId, name FROM categories')
        categories = cur.fetchall()

        if not product:
            return redirect(url_for('admin_dashboard'))

        if request.method == "GET":
            return render_template("edit_product.html", product=product, categories=categories, errors={}, form={})

        form = {
            'name': request.form.get('name', ''),
            'price': request.form.get('price', ''),
            'description': request.form.get('description', ''),
            'stock': request.form.get('stock', ''),
            'category': request.form.get('category', ''),
        }
        errors = {}
        validCategoryIds = [category[0] for category in categories]

        form['name'], error = validators.text_field(form['name'], 'Product name')
        if error:
            errors['name'] = error
        error = validators.price_error(form['price'])
        if error:
            errors['price'] = error
        error = validators.stock_error(form['stock'])
        if error:
            errors['stock'] = error
        error = validators.category_error(form['category'], validCategoryIds)
        if error:
            errors['category'] = error

        if errors:
            return render_template("edit_product.html", errors=errors, form=form, product=product, categories=categories)

        name = form['name']
        price = float(form['price'])
        description = form['description']
        stock = int(form['stock'])
        categoryId = int(form['category'])

        # Handle image update
        image = request.files.get('image')
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

@app.route("/account/profile/edit")
def editProfile():
    if 'email' not in session:
        return redirect(url_for('root'))
    loggedIn, firstName, noOfItems = getLoginDetails()
    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()
        cur.execute("SELECT userId, email, firstName, lastName, address1, address2, zipcode, city, state, country, phone FROM users WHERE email = ?", (session['email'],))
        profileData = cur.fetchone()
    form = {}
    if profileData:
        form = {
            'email': profileData[1] or '',
            'firstName': profileData[2] or '',
            'lastName': profileData[3] or '',
            'address1': profileData[4] or '',
            'address2': profileData[5] or '',
            'zipcode': profileData[6] or '',
            'city': profileData[7] or '',
            'state': profileData[8] or '',
            'country': profileData[9] or '',
            'phone': profileData[10] or '',
        }
    return render_template("editProfile.html", profileData=profileData, form=form, errors={}, loggedIn=loggedIn, firstName=firstName, noOfItems=noOfItems)

@app.route("/account/profile/changePassword", methods=["GET", "POST"])
def changePassword():
    if 'email' not in session:
        return redirect(url_for('loginForm'))
    if request.method == "POST":
        oldPassword = request.form.get('oldpassword', '')
        newPassword = request.form.get('newpassword', '')
        cpassword = request.form.get('cpassword', '')

        oldHash = hashlib.md5(oldPassword.encode()).hexdigest()
        newHash = hashlib.md5(newPassword.encode()).hexdigest()

        errors = {}
        with sqlite3.connect('database.db') as conn:
            cur = conn.cursor()
            cur.execute("SELECT userId, password FROM users WHERE email = ?", (session['email'],))
            result = cur.fetchone()
            if not result:
                return render_template("changePassword.html", msg="User not found", errors={})

            userId, password = result
            if password != oldHash:
                errors['oldpassword'] = validators.MESSAGES['old_password_wrong']

            newPasswordError = validators.password_error(newPassword)
            if newPasswordError:
                errors['newpassword'] = newPasswordError
            elif newHash == password:
                errors['newpassword'] = validators.MESSAGES['password_same']

            if cpassword != newPassword:
                errors['cpassword'] = validators.MESSAGES['confirm_mismatch']

            if errors:
                return render_template("changePassword.html", errors=errors)

            try:
                cur.execute("UPDATE users SET password = ? WHERE userId = ?", (newHash, userId))
                conn.commit()
                msg = "Changed successfully"
            except Exception:
                conn.rollback()
                msg = "Failed"
        return render_template("changePassword.html", msg=msg, errors={})
    else:
        return render_template("changePassword.html", errors={})

@app.route("/updateProfile", methods=["GET", "POST"])
def updateProfile():
    if 'email' not in session:
        return redirect(url_for('root'))
    
    if request.method == 'POST':
        form = {
            'email': validators.trim(request.form.get('email', '')),
            'firstName': request.form.get('firstName', ''),
            'lastName': request.form.get('lastName', ''),
            'address1': request.form.get('address1', ''),
            'address2': request.form.get('address2', ''),
            'zipcode': request.form.get('zipcode', ''),
            'city': request.form.get('city', ''),
            'state': request.form.get('state', ''),
            'country': request.form.get('country', ''),
            'phone': request.form.get('phone', ''),
        }

        errors = {}
        for field, label in (('firstName', 'First name'), ('lastName', 'Last name'),
                             ('city', 'City'), ('state', 'State'), ('country', 'Country')):
            form[field], error = validators.text_field(form[field], label)
            if error:
                errors[field] = error
        for field, label in (('address1', 'Address line 1'), ('address2', 'Address line 2')):
            form[field], error = validators.text_field(form[field], label, required=False)
            if error:
                errors[field] = error

        error = validators.email_error(form['email'])
        if error:
            errors['email'] = error
        error = validators.phone_error(form['phone'])
        if error:
            errors['phone'] = error
        error = validators.zipcode_error(form['zipcode'])
        if error:
            errors['zipcode'] = error

        with sqlite3.connect('database.db') as con:
            cur = con.cursor()
            cur.execute("SELECT userId FROM users WHERE email = ?", (session['email'],))
            result = cur.fetchone()
            currentUserId = result[0] if result else None
            if 'email' not in errors and validators.email_in_use(con, form['email'], exclude_user_id=currentUserId):
                errors['email'] = validators.MESSAGES['email_in_use']

        if errors:
            loggedIn, firstName, noOfItems = getLoginDetails()
            return render_template("editProfile.html", errors=errors, form=form, loggedIn=loggedIn, firstName=firstName, noOfItems=noOfItems)

        email = form['email']
        firstName = form['firstName']
        lastName = form['lastName']
        address1 = form['address1']
        address2 = form['address2']
        zipcode = form['zipcode']
        city = form['city']
        state = form['state']
        country = form['country']
        phone = form['phone']
        
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
        # Parse form data    
        form = {
            'email': validators.trim(request.form.get('email', '')),
            'password': request.form.get('password', ''),
            'firstName': request.form.get('firstName', ''),
            'lastName': request.form.get('lastName', ''),
            'address1': request.form.get('address1', ''),
            'address2': request.form.get('address2', ''),
            'zipcode': request.form.get('zipcode', ''),
            'city': request.form.get('city', ''),
            'state': request.form.get('state', ''),
            'country': request.form.get('country', ''),
            'phone': request.form.get('phone', ''),
        }
        cpassword = request.form.get('cpassword', '')

        errors = {}
        for field, label in (('firstName', 'First name'), ('lastName', 'Last name'),
                             ('city', 'City'), ('state', 'State'), ('country', 'Country')):
            form[field], error = validators.text_field(form[field], label)
            if error:
                errors[field] = error
        for field, label in (('address1', 'Address line 1'), ('address2', 'Address line 2')):
            form[field], error = validators.text_field(form[field], label, required=False)
            if error:
                errors[field] = error

        error = validators.email_error(form['email'])
        if error:
            errors['email'] = error
        error = validators.password_error(form['password'])
        if error:
            errors['password'] = error
        if cpassword != form['password']:
            errors['cpassword'] = validators.MESSAGES['confirm_mismatch']
        error = validators.phone_error(form['phone'])
        if error:
            errors['phone'] = error
        error = validators.zipcode_error(form['zipcode'])
        if error:
            errors['zipcode'] = error

        if 'email' not in errors:
            with sqlite3.connect('database.db') as con:
                if validators.email_in_use(con, form['email']):
                    errors['email'] = validators.MESSAGES['email_in_use']

        if errors:
            return render_template('register.html', errors=errors, form=form)

        password = form['password']
        email = form['email']
        firstName = form['firstName']
        lastName = form['lastName']
        address1 = form['address1']
        address2 = form['address2']
        zipcode = form['zipcode']
        city = form['city']
        state = form['state']
        country = form['country']
        phone = form['phone']

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

    return render_template('register.html', errors={}, form={})

@app.route("/registerationForm")
def registrationForm():
    return render_template("register.html", errors={}, form={})

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

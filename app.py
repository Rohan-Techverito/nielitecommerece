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

# Reviews table definition, byte-for-byte the same DDL as database.py.
# app.py never imports database.py and database.db is committed, so the table is
# also created from here at import time to upgrade an already deployed database.
REVIEWS_TABLE_DDL = '''CREATE TABLE IF NOT EXISTS reviews (
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
)'''

# Create the reviews table if it is missing
def ensure_reviews_table() -> None:
    with sqlite3.connect('database.db') as conn:
        conn.execute(REVIEWS_TABLE_DDL)
        conn.commit()

# Ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Ensure the reviews table exists
ensure_reviews_table()

# Fetch a shopper's userId from their email, None when there is no such user
def get_user_id(email: str) -> int | None:
    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()
        cur.execute("SELECT userId FROM users WHERE email = ?", (email,))
        result = cur.fetchone()
    return result[0] if result else None

# A shopper may review a product only once they have ordered it.
# Any order row is enough, however many times the product was ordered.
def has_purchased(userId: int, productId: int) -> bool:
    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM allorders WHERE userId = ? AND productId = ? LIMIT 1", (userId, productId))
        return cur.fetchone() is not None

# Average rating (one decimal place) and count of the visible reviews only,
# (None, 0) when the product has no visible review so callers can tell that
# apart from an average of 0.0
def get_rating_summary(productId: int) -> tuple[float | None, int]:
    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()
        cur.execute("SELECT AVG(rating), COUNT(*) FROM reviews WHERE productId = ? AND hidden = 0", (productId,))
        avg, count = cur.fetchone()
    if not count:
        return (None, 0)
    return (round(avg, 1), count)

# Average rating (one decimal place) and visible review count of every product
# that has at least one visible review. A product without reviews is simply
# absent from the dict, so the catalogue can skip it instead of testing for 0.
def get_rating_summaries() -> dict[int, tuple[float, int]]:
    summaries: dict[int, tuple[float, int]] = {}
    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()
        cur.execute("SELECT productId, AVG(rating), COUNT(*) FROM reviews WHERE hidden = 0 GROUP BY productId")
        for productId, avg, count in cur.fetchall():
            summaries[productId] = (round(avg, 1), count)
    return summaries

# All visible reviews of a product, newest first, with the author's first name
def get_reviews(productId: int) -> list[sqlite3.Row]:
    with sqlite3.connect('database.db') as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""SELECT reviews.reviewId, reviews.productId, reviews.userId, reviews.rating,
                              reviews.title, reviews.comment, reviews.review_date, reviews.hidden,
                              reviews.hidden_reason, users.firstName
                       FROM reviews
                       JOIN users ON reviews.userId = users.userId
                       WHERE reviews.productId = ? AND reviews.hidden = 0
                       ORDER BY reviews.review_date DESC, reviews.reviewId DESC""", (productId,))
        return cur.fetchall()

# The shopper's own review of a product. Hidden reviews are returned as well so
# the UNIQUE(userId, productId) constraint can be honoured.
def get_review_for_user(productId: int, userId: int) -> sqlite3.Row | None:
    with sqlite3.connect('database.db') as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM reviews WHERE productId = ? AND userId = ?", (productId, userId))
        return cur.fetchone()

# Average rating for display, '' when the product has no visible review
def format_rating(value: float | None) -> str:
    if value is None:
        return ''
    return f'{value:.1f}'

# Everything the product page's review section needs: the average and count of
# the visible reviews, the visible reviews themselves, the shopper's own review
# and whether they may write one. A hidden review is invisible to its author
# too, so it counts as no review at all and the author gets the ordinary
# create form back.
def build_review_context(productId: int, email: str | None) -> dict:
    userId = get_user_id(email) if email else None
    signedIn = userId is not None
    purchased = has_purchased(userId, productId) if signedIn else False
    avg, count = get_rating_summary(productId)
    ownReview = get_review_for_user(productId, userId) if signedIn else None
    visibleReview = ownReview if ownReview is not None and not ownReview['hidden'] else None
    return {
        'avg_rating': format_rating(avg),
        'review_count': count,
        'reviews': get_reviews(productId),
        'user_review': visibleReview,
        'can_review': signedIn and purchased and visibleReview is None,
        'purchased': purchased,
        'signed_in': signedIn,
    }

# Delete every review of a product. Pass an open connection to delete the
# reviews in the same transaction as the product row itself.
def delete_product_reviews(productId: int, conn: sqlite3.Connection | None = None) -> None:
    if conn is None:
        with sqlite3.connect('database.db') as ownConn:
            ownConn.execute("DELETE FROM reviews WHERE productId = ?", (productId,))
            ownConn.commit()
        return
    conn.execute("DELETE FROM reviews WHERE productId = ?", (productId,))

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
    return render_template('home.html', itemData=itemData, loggedIn=loggedIn, firstName=firstName, noOfItems=noOfItems, categoryData=categoryData, ratingSummary=get_rating_summaries())

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
def delete_product(productId: int):
    if not is_admin():
        return redirect(url_for('root'))
    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()
        # Remove the product's reviews in the same transaction, so a deleted
        # product leaves no review behind on the admin reviews page
        delete_product_reviews(productId, conn)
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
        cur.execute("""SELECT products.productId, products.name, products.price, products.image, categories.name 
                       FROM products, categories 
                       WHERE products.categoryId = categories.categoryId 
                       AND categories.categoryId = ?""", (categoryId,))
        data = cur.fetchall()
    
    if not data:
        return redirect(url_for('root'))
    
    categoryName = data[0][4]
    data = parse(data)
    # Only products with at least one visible review are in the dict, so the
    # category page can skip the rating of every other product
    return render_template('displayCategory.html', data=data, loggedIn=loggedIn, firstName=firstName, noOfItems=noOfItems, categoryName=categoryName, ratingSummary=get_rating_summaries())

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
    
    # Anonymous shoppers have no email, so they get the sign-in prompt instead
    # of a review form
    reviewContext = build_review_context(int(productId), session.get('email'))

    # ?edit=1 swaps the shopper's own review for a form pre-filled with it
    editing = request.args.get('edit') == '1' and reviewContext['user_review'] is not None
    review_form: dict = {}
    if editing:
        ownReview = reviewContext['user_review']
        review_form = {
            'rating': str(ownReview['rating']),
            'title': ownReview['title'] or '',
            'comment': ownReview['comment'] or '',
        }

    return render_template("productDescription.html", data=productData, loggedIn=loggedIn, firstName=firstName, noOfItems=noOfItems,
                           editing=editing, review_form=review_form, review_errors={}, **reviewContext)

# Render the product page again from a review route, so a rejected submission
# can show a message next to its own field and keep what the shopper typed
def render_product_page(productId: int, review_form: dict | None = None,
                        review_errors: dict | None = None, editing: bool = False,
                        status: int = 200):
    loggedIn, firstName, noOfItems = getLoginDetails()
    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()
        cur.execute('SELECT productId, name, price, description, image, stock FROM products WHERE productId = ?', (productId,))
        productData = cur.fetchone()

    if not productData:
        return redirect(url_for('root'))

    reviewContext = build_review_context(productId, session.get('email'))
    rendered = render_template("productDescription.html", data=productData, loggedIn=loggedIn,
                               firstName=firstName, noOfItems=noOfItems, editing=editing,
                               review_form=review_form or {}, review_errors=review_errors or {},
                               **reviewContext)
    return rendered, status

# One user-facing message per invalid review field. A field with no entry in the
# returned dict is valid; title and comment are optional.
def validate_review_submission(form) -> dict[str, str]:
    errors: dict[str, str] = {}

    rating = (form.get('rating') or '').strip()
    if not rating:
        errors['rating'] = 'Please choose a rating of 1 to 5 stars.'
    elif not rating.isdigit() or not 1 <= int(rating) <= 5:
        errors['rating'] = 'Rating must be a whole number from 1 to 5 stars.'

    title = form.get('title') or ''
    if len(title) > 80:
        errors['title'] = 'Title must be 80 characters or fewer.'

    comment = form.get('comment') or ''
    if len(comment) > 1000:
        errors['comment'] = 'Comment must be 1000 characters or fewer.'

    return errors

# Create the signed-in shopper's review of a product they have bought
@app.route('/product/<int:productId>/review', methods=['POST'])
def add_review(productId: int):
    email = session.get('email')
    if not email:
        return redirect(url_for('loginForm'))

    userId = get_user_id(email)
    if userId is None:
        return redirect(url_for('loginForm'))

    # Reviews are limited to customers who bought the product
    if not has_purchased(userId, productId):
        return render_product_page(productId, status=403)

    errors = validate_review_submission(request.form)
    if errors:
        review_form = {
            'rating': request.form.get('rating', ''),
            'title': request.form.get('title', ''),
            'comment': request.form.get('comment', ''),
        }
        return render_product_page(productId, review_form=review_form, review_errors=errors, status=400)

    rating = int(request.form.get('rating'))
    # Stored exactly as typed: Jinja escapes on output, so nothing is escaped or
    # truncated here
    title = request.form.get('title') or ''
    comment = request.form.get('comment') or ''
    review_date = datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%Y-%m-%d %H:%M:%S')

    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()
        # UNIQUE(userId, productId) enforces one review per shopper per product,
        # so submitting again updates that same row. hidden and hidden_reason are
        # deliberately left untouched: a shopper whose review was hidden who
        # submits again updates it in place and it stays hidden.
        cur.execute('''INSERT INTO reviews (productId, userId, rating, title, comment, review_date, hidden)
                       VALUES (?, ?, ?, ?, ?, ?, 0)
                       ON CONFLICT(userId, productId) DO UPDATE SET
                           rating = excluded.rating,
                           title = excluded.title,
                           comment = excluded.comment,
                           review_date = excluded.review_date''',
                    (productId, userId, rating, title, comment, review_date))
        conn.commit()

    return redirect(url_for('productDescription', productId=productId))

# Edit the shopper's own review; only ever the row they own
@app.route('/product/<int:productId>/review/edit', methods=['POST'])
def edit_review(productId: int):
    email = session.get('email')
    if not email:
        return redirect(url_for('loginForm'))

    userId = get_user_id(email)
    if userId is None:
        return redirect(url_for('loginForm'))

    reviewId = request.form.get('reviewId', '')
    if not reviewId.isdigit():
        return 'Review not found.', 403

    errors = validate_review_submission(request.form)
    if errors:
        review_form = {
            'rating': request.form.get('rating', ''),
            'title': request.form.get('title', ''),
            'comment': request.form.get('comment', ''),
        }
        return render_product_page(productId, review_form=review_form, review_errors=errors, editing=True, status=400)

    rating = int(request.form.get('rating'))
    title = request.form.get('title') or ''
    comment = request.form.get('comment') or ''
    review_date = datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%Y-%m-%d %H:%M:%S')

    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()
        # Filtering on reviewId AND userId leaves another shopper's row untouched
        cur.execute("UPDATE reviews SET rating = ?, title = ?, comment = ?, review_date = ? WHERE reviewId = ? AND userId = ?",
                    (rating, title, comment, review_date, int(reviewId), userId))
        if cur.rowcount == 0:
            conn.rollback()
            return 'Review not found.', 403
        conn.commit()

    return redirect(url_for('productDescription', productId=productId))

# Delete the shopper's own review; only ever the row they own
@app.route('/product/<int:productId>/review/delete', methods=['POST'])
def delete_review(productId: int):
    email = session.get('email')
    if not email:
        return redirect(url_for('loginForm'))

    userId = get_user_id(email)
    if userId is None:
        return redirect(url_for('loginForm'))

    reviewId = request.form.get('reviewId', '')
    if not reviewId.isdigit():
        return 'Review not found.', 403

    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM reviews WHERE reviewId = ? AND userId = ?", (int(reviewId), userId))
        if cur.rowcount == 0:
            conn.rollback()
            return 'Review not found.', 403
        conn.commit()

    return redirect(url_for('productDescription', productId=productId))

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

# Every review, visible and hidden, with the product name and its author, for
# the admin reviews page. Newest first.
def get_all_reviews() -> list[sqlite3.Row]:
    with sqlite3.connect('database.db') as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""SELECT reviews.*, products.name AS product_name,
                              users.firstName, users.lastName
                       FROM reviews
                       JOIN products ON reviews.productId = products.productId
                       JOIN users ON reviews.userId = users.userId
                       ORDER BY reviews.review_date DESC, reviews.reviewId DESC""")
        return cur.fetchall()

# Admin reviews page: hidden reviews are listed too, with the reason they were
# hidden, and each row carries a hide or a restore control
@app.route('/admin/reviews')
def admin_reviews() -> str:
    if not is_admin():
        return redirect(url_for('root'))
    return render_template('admin_reviews.html', reviews=get_all_reviews(), error=request.args.get('error', ''), error_review=request.args.get('error_review', type=int))

# Hide a review, which keeps it but removes it from the product page, the
# average and the counts. A reason must be typed before anything is hidden.
@app.route('/admin/reviews/<int:reviewId>/hide', methods=['POST'])
def hide_review(reviewId: int):
    if not is_admin():
        return redirect(url_for('root'))

    reason = (request.form.get('reason') or '').strip()
    if not reason:
        return redirect(url_for('admin_reviews', error='A reason is required to hide a review', error_review=reviewId))

    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()
        cur.execute("UPDATE reviews SET hidden = 1, hidden_reason = ? WHERE reviewId = ?", (reason, reviewId))
        conn.commit()

    return redirect(url_for('admin_reviews'))

# Restore a hidden review and clear the reason it was hidden
@app.route('/admin/reviews/<int:reviewId>/restore', methods=['POST'])
def restore_review(reviewId: int):
    if not is_admin():
        return redirect(url_for('root'))

    with sqlite3.connect('database.db') as conn:
        cur = conn.cursor()
        cur.execute("UPDATE reviews SET hidden = 0, hidden_reason = NULL WHERE reviewId = ?", (reviewId,))
        conn.commit()

    return redirect(url_for('admin_reviews'))

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

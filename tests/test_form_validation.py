"""Regression tests for server-side form validation.

Run with ``python -m unittest`` from the repository root.  The tests use only
the standard library plus the project's existing Flask dependency.
"""

import hashlib
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from validators import (  # noqa: E402
    validate_category,
    validate_confirmation,
    validate_email,
    validate_name,
    validate_password,
    validate_phone,
    validate_price,
    validate_stock,
    validate_zipcode,
)


class ValidatorTests(unittest.TestCase):
    """Direct unit coverage for the framework-free rules."""

    def test_price_accepts_zero_and_two_decimal_places(self):
        for value in ('0', '12', '12.5', '12.50'):
            with self.subTest(value=value):
                cleaned, error = validate_price(value)
                self.assertIsNone(error)
                self.assertAlmostEqual(cleaned, float(value))

    def test_price_rejects_invalid_values_with_specific_messages(self):
        cases = (
            ('-1', 'Price cannot be negative.'),
            ('12.555', 'Price can have at most two decimal places.'),
            ('abc', 'Price must be a number.'),
            ('', 'Price is required.'),
        )
        for value, message in cases:
            with self.subTest(value=value):
                cleaned, error = validate_price(value)
                self.assertIsNone(cleaned)
                self.assertEqual(error, message)

    def test_stock_accepts_whole_numbers_and_rejects_invalid_values(self):
        for value in ('0', '3'):
            with self.subTest(value=value):
                cleaned, error = validate_stock(value)
                self.assertIsNone(error)
                self.assertEqual(cleaned, int(value))

        cases = (
            ('3.5', 'Stock must be a whole number.'),
            ('-2', 'Stock cannot be negative.'),
            ('abc', 'Stock must be a whole number.'),
        )
        for value, message in cases:
            with self.subTest(value=value):
                cleaned, error = validate_stock(value)
                self.assertIsNone(cleaned)
                self.assertEqual(error, message)

    def test_phone_accepts_exactly_ten_digits(self):
        cleaned, error = validate_phone('9876543210')
        self.assertIsNone(error)
        self.assertEqual(cleaned, '9876543210')

        for value in ('98765 43210', '+919876543210', '987654321'):
            with self.subTest(value=value):
                cleaned, error = validate_phone(value)
                self.assertIsNone(cleaned)
                self.assertEqual(error, 'Phone number must be exactly 10 digits.')

    def test_zipcode_accepts_exactly_six_digits(self):
        cleaned, error = validate_zipcode('110001')
        self.assertIsNone(error)
        self.assertEqual(cleaned, '110001')

        for value in ('11001', '1100011', 'abcdef'):
            with self.subTest(value=value):
                cleaned, error = validate_zipcode(value)
                self.assertIsNone(cleaned)
                self.assertEqual(error, 'Zipcode must be exactly 6 digits.')

    def test_email_is_trimmed_and_checked(self):
        cleaned, error = validate_email('  User@Example.com  ')
        self.assertIsNone(error)
        self.assertEqual(cleaned, 'User@Example.com')

        for value in ('user@@example.com', 'user@example', 'user@exa mple.com', 'userexample.com'):
            with self.subTest(value=value):
                cleaned, error = validate_email(value)
                self.assertIsNone(cleaned)
                self.assertIn('Enter a valid email address', error)

    def test_name_is_required_trimmed_and_length_limited(self):
        cleaned, error = validate_name('  Ada  ', 'First name')
        self.assertIsNone(error)
        self.assertEqual(cleaned, 'Ada')

        cleaned, error = validate_name('   ', 'First name')
        self.assertIsNone(cleaned)
        self.assertEqual(error, 'First name is required.')

        cleaned, error = validate_name('a' * 201, 'First name')
        self.assertIsNone(cleaned)
        self.assertEqual(error, 'First name must be 200 characters or fewer.')

    def test_password_rules(self):
        for value in ('short1', '12345678', 'abcdefgh'):
            with self.subTest(value=value):
                cleaned, error = validate_password(value)
                self.assertIsNone(cleaned)
                self.assertIsNotNone(error)

        cleaned, error = validate_password('Secret123')
        self.assertIsNone(error)
        self.assertEqual(cleaned, 'Secret123')

    def test_confirmation_is_optional_for_registration_but_must_match(self):
        self.assertEqual(validate_confirmation('', 'Secret123'), (None, None))

        _, error = validate_confirmation('Other123', 'Secret123')
        self.assertEqual(error, 'Passwords do not match.')

    def test_category_must_exist(self):
        categories = [(1, 'Electronics'), (2, 'Books')]

        cleaned, error = validate_category('2', categories)
        self.assertIsNone(error)
        self.assertEqual(cleaned, 2)

        cleaned, error = validate_category('99', categories)
        self.assertIsNone(cleaned)
        self.assertEqual(error, 'Select a valid category.')


class FormValidationTests(unittest.TestCase):
    """End-to-end tests for every validated form."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.original_cwd = os.getcwd()
        os.chdir(cls.temp_dir.name)

        import app as app_module
        cls.app_module = app_module
        cls.app = app_module.app
        cls._original_testing = cls.app.config.get('TESTING', False)
        cls.app.config['TESTING'] = True
        os.makedirs('static/uploads', exist_ok=True)
        cls._create_schema()

    @classmethod
    def tearDownClass(cls):
        cls.app.config['TESTING'] = cls._original_testing
        os.chdir(cls.original_cwd)
        cls.temp_dir.cleanup()

    @classmethod
    def _create_schema(cls):
        connection = sqlite3.connect('database.db')
        connection.executescript(
            '''
            CREATE TABLE users (
                userId INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT,
                password TEXT,
                firstName TEXT,
                lastName TEXT,
                address1 TEXT,
                address2 TEXT,
                zipcode TEXT,
                city TEXT,
                state TEXT,
                country TEXT,
                phone TEXT
            );
            CREATE TABLE categories (
                categoryId INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT
            );
            CREATE TABLE products (
                productId INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                price REAL,
                description TEXT,
                image TEXT,
                stock INTEGER,
                categoryId INTEGER
            );
            CREATE TABLE kart (
                userId INTEGER,
                productId INTEGER
            );
            CREATE TABLE wishlist (
                wishlistId INTEGER PRIMARY KEY AUTOINCREMENT,
                userId INTEGER,
                productId INTEGER
            );
            CREATE TABLE allorders (
                orderId INTEGER PRIMARY KEY AUTOINCREMENT,
                userId INTEGER,
                productId INTEGER,
                quantity INTEGER,
                total_price REAL,
                order_date TEXT
            );
            '''
        )
        connection.commit()
        connection.close()

    def setUp(self):
        self.client = self.app.test_client()
        self._seed_database()

    def _seed_database(self):
        connection = sqlite3.connect('database.db')
        cur = connection.cursor()
        for table in ('allorders', 'wishlist', 'kart', 'products', 'categories', 'users'):
            cur.execute('DELETE FROM %s' % table)

        cur.execute(
            'INSERT INTO users (userId, email, password, firstName, lastName, address1, '
            'address2, zipcode, city, state, country, phone) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (1, 'alice@example.com', hashlib.md5(b'Password1').hexdigest(), 'Alice',
             'Anderson', '1 Main St', '', '110001', 'Delhi', 'Delhi', 'India', '9876543210'),
        )
        cur.execute(
            'INSERT INTO users (userId, email, password, firstName, lastName, address1, '
            'address2, zipcode, city, state, country, phone) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (2, 'bob@example.com', hashlib.md5(b'Password2').hexdigest(), 'Bob',
             'Brown', '2 Side St', '', '400001', 'Mumbai', 'MH', 'India', '9123456780'),
        )

        cur.execute("INSERT INTO categories (categoryId, name) VALUES (1, 'Electronics')")
        cur.execute("INSERT INTO categories (categoryId, name) VALUES (2, 'Books')")
        cur.execute(
            "INSERT INTO products (productId, name, price, description, image, stock, categoryId) "
            "VALUES (1, 'Widget', 10.0, 'A widget', 'product-default.png', 5, 1)"
        )
        connection.commit()
        connection.close()

    def _connect(self):
        return sqlite3.connect('database.db')

    def _count(self, table):
        connection = self._connect()
        try:
            return connection.execute('SELECT COUNT(*) FROM %s' % table).fetchone()[0]
        finally:
            connection.close()

    def _login_as(self, email):
        with self.client.session_transaction() as session:
            session['email'] = email

    def _login_admin(self):
        self._login_as('admin@nielit.gov.in')

    def _registration_data(self, **overrides):
        data = {
            'email': 'new.user@example.com',
            'password': 'Secret123',
            'cpassword': 'Secret123',
            'firstName': 'New',
            'lastName': 'User',
            'address1': '1 New Road',
            'address2': '',
            'zipcode': '110001',
            'city': 'Delhi',
            'state': 'Delhi',
            'country': 'India',
            'phone': '9876543210',
        }
        data.update(overrides)
        return data

    def _profile_data(self, **overrides):
        data = {
            'email': 'alice@example.com',
            'firstName': 'Alice',
            'lastName': 'Anderson',
            'address1': '1 Main St',
            'address2': '',
            'zipcode': '110001',
            'city': 'Delhi',
            'state': 'Delhi',
            'country': 'India',
            'phone': '9876543210',
        }
        data.update(overrides)
        return data

    def _product_data(self, **overrides):
        data = {
            'name': 'New Gadget',
            'price': '12.50',
            'description': 'A useful gadget',
            'stock': '3',
            'category': '1',
        }
        data.update(overrides)
        return data

    def _alice_row(self):
        connection = self._connect()
        try:
            return connection.execute(
                'SELECT firstName, lastName, address1, address2, zipcode, city, state, '
                'country, phone, email FROM users WHERE email = ?',
                ('alice@example.com',),
            ).fetchone()
        finally:
            connection.close()

    def _product_row(self, product_id=1):
        connection = self._connect()
        try:
            return connection.execute(
                'SELECT name, price, description, image, stock, categoryId '
                'FROM products WHERE productId = ?',
                (product_id,),
            ).fetchone()
        finally:
            connection.close()

    # ---------------------------------------------------------------- register

    def test_registration_invalid_data_shows_field_messages_and_saves_nothing(self):
        data = self._registration_data(
            email='not-an-email',
            firstName='   ',
            lastName='',
            password='short',
            cpassword='short',
            phone='98765 43210',
            zipcode='11001',
            city=' ',
            state='',
            country='   ',
        )
        response = self.client.post('/register', data=data)
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        for message in (
            'Enter a valid email address',
            'First name is required.',
            'Last name is required.',
            'Password must be at least 8 characters long.',
            'Phone number must be exactly 10 digits.',
            'Zipcode must be exactly 6 digits.',
            'City is required.',
            'State is required.',
            'Country is required.',
        ):
            self.assertIn(message, html)
        self.assertNotIn('Traceback', html)
        self.assertEqual(self._count('users'), 2)

    def test_registration_missing_fields_do_not_raise(self):
        response = self.client.post('/register', data={})
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('Email is required.', html)
        self.assertIn('Password is required.', html)
        self.assertIn('First name is required.', html)
        self.assertEqual(self._count('users'), 2)

    def test_registration_rejects_case_insensitive_duplicate_email(self):
        data = self._registration_data(email='ALICE@EXAMPLE.COM')
        response = self.client.post('/register', data=data)
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('An account with this email already exists.', html)
        self.assertEqual(self._count('users'), 2)

    def test_registration_password_rules_are_enforced(self):
        cases = (
            ('short1', 'Password must be at least 8 characters long.'),
            ('12345678', 'Password must contain at least one letter.'),
            ('abcdefgh', 'Password must contain at least one number.'),
        )
        for password, message in cases:
            with self.subTest(password=password):
                data = self._registration_data(password=password, cpassword=password)
                response = self.client.post('/register', data=data)
                self.assertIn(message, response.get_data(as_text=True))
                self.assertEqual(self._count('users'), 2)

    def test_registration_confirmation_mismatch_is_reported(self):
        data = self._registration_data(cpassword='OtherSecret1')
        response = self.client.post('/register', data=data)
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('Passwords do not match.', html)
        self.assertEqual(self._count('users'), 2)

    def test_registration_preserves_non_secret_values_after_failure(self):
        data = self._registration_data(
            email='  carol@example.com  ',
            firstName='  Carol  ',
            lastName='  Clark  ',
            city='Mumbai',
            address1='9 Marine Drive',
            phone='123',
        )
        response = self.client.post('/register', data=data)
        html = response.get_data(as_text=True)

        self.assertIn('value="carol@example.com"', html)
        self.assertIn('value="Carol"', html)
        self.assertIn('value="Clark"', html)
        self.assertIn('value="Mumbai"', html)
        self.assertIn('value="9 Marine Drive"', html)
        self.assertIn('value="123"', html)
        self.assertNotIn('Secret123', html)
        self.assertNotIn('alert(', html)
        self.assertEqual(self._count('users'), 2)

    def test_registration_valid_data_still_creates_user(self):
        data = self._registration_data(
            email='  Carol@Example.com  ',
            firstName='  Carol  ',
            lastName='  Clark  ',
        )
        response = self.client.post('/register', data=data)
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('Registered Successfully', html)
        self.assertEqual(self._count('users'), 3)

        connection = self._connect()
        try:
            row = connection.execute(
                'SELECT email, firstName, lastName, password FROM users WHERE email = ?',
                ('Carol@Example.com',),
            ).fetchone()
        finally:
            connection.close()

        self.assertIsNotNone(row)
        self.assertEqual(row[1], 'Carol')
        self.assertEqual(row[2], 'Clark')
        self.assertEqual(row[3], hashlib.md5(b'Secret123').hexdigest())

    # ----------------------------------------------------------- edit profile

    def test_profile_invalid_data_shows_field_messages_and_keeps_row(self):
        self._login_as('alice@example.com')
        data = self._profile_data(
            email='not-an-email',
            firstName='   ',
            lastName='',
            phone='98765 43210',
            zipcode='11001',
            city='',
            state='',
            country='',
        )
        response = self.client.post('/updateProfile', data=data)
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        for message in (
            'Enter a valid email address',
            'First name is required.',
            'Last name is required.',
            'Phone number must be exactly 10 digits.',
            'Zipcode must be exactly 6 digits.',
            'City is required.',
            'State is required.',
            'Country is required.',
        ):
            self.assertIn(message, html)
        self.assertNotIn('Traceback', html)

        row = self._alice_row()
        self.assertEqual(row[0], 'Alice')
        self.assertEqual(row[1], 'Anderson')
        self.assertEqual(row[4], '110001')
        self.assertEqual(row[5], 'Delhi')
        self.assertEqual(row[8], '9876543210')

    def test_profile_preserves_submitted_values_after_failure(self):
        self._login_as('alice@example.com')
        data = self._profile_data(
            firstName='  Alicia  ',
            address1='99 Test Road',
            city='',
            phone='123',
        )
        response = self.client.post('/updateProfile', data=data)
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('value="Alicia"', html)
        self.assertIn('value="99 Test Road"', html)
        self.assertIn('value="123"', html)
        self.assertEqual(self._alice_row()[0], 'Alice')

    def test_profile_rejects_another_accounts_email_case_insensitively(self):
        self._login_as('alice@example.com')
        data = self._profile_data(email='BOB@EXAMPLE.COM')
        response = self.client.post('/updateProfile', data=data)
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('This email address belongs to another account.', html)

        row = self._alice_row()
        self.assertEqual(row[0], 'Alice')
        self.assertEqual(row[9], 'alice@example.com')

    def test_profile_rejects_value_longer_than_200_characters(self):
        self._login_as('alice@example.com')
        data = self._profile_data(firstName='a' * 201)
        response = self.client.post('/updateProfile', data=data)
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('First name must be 200 characters or fewer.', html)
        self.assertEqual(self._alice_row()[0], 'Alice')

    def test_profile_valid_update_still_redirects_and_saves(self):
        self._login_as('alice@example.com')
        data = self._profile_data(
            email='ALICE@EXAMPLE.COM',
            firstName='Alicia',
            lastName='Anderson',
            address1='2 Main St',
            address2='Apt 4',
            zipcode='110002',
            city='Mumbai',
            state='MH',
            country='India',
            phone='9123456789',
        )
        response = self.client.post('/updateProfile', data=data)

        self.assertEqual(response.status_code, 302)
        self.assertIn('/account/profile/edit', response.headers['Location'])

        row = self._alice_row()
        self.assertEqual(row[0], 'Alicia')
        self.assertEqual(row[2], '2 Main St')
        self.assertEqual(row[3], 'Apt 4')
        self.assertEqual(row[4], '110002')
        self.assertEqual(row[5], 'Mumbai')
        self.assertEqual(row[6], 'MH')
        self.assertEqual(row[8], '9123456789')

    # -------------------------------------------------------- change password

    def _stored_password(self, email='alice@example.com'):
        connection = self._connect()
        try:
            return connection.execute(
                'SELECT password FROM users WHERE email = ?', (email,)
            ).fetchone()[0]
        finally:
            connection.close()

    def test_password_wrong_current_and_mismatch_have_distinct_messages(self):
        self._login_as('alice@example.com')
        original = self._stored_password()

        wrong_current = self.client.post(
            '/account/profile/changePassword',
            data={'oldpassword': 'WrongPass1', 'newpassword': 'NewSecret1', 'cpassword': 'NewSecret1'},
        )
        wrong_html = wrong_current.get_data(as_text=True)
        self.assertIn('Current password is incorrect.', wrong_html)
        self.assertNotIn('Passwords do not match.', wrong_html)
        self.assertEqual(self._stored_password(), original)

        mismatch = self.client.post(
            '/account/profile/changePassword',
            data={'oldpassword': 'Password1', 'newpassword': 'NewSecret1', 'cpassword': 'OtherSecret1'},
        )
        mismatch_html = mismatch.get_data(as_text=True)
        self.assertIn('Passwords do not match.', mismatch_html)
        self.assertNotIn('Current password is incorrect.', mismatch_html)
        self.assertEqual(self._stored_password(), original)
        self.assertNotIn('alert(', mismatch_html)

    def test_password_new_must_differ_from_current(self):
        self._login_as('alice@example.com')
        original = self._stored_password()

        response = self.client.post(
            '/account/profile/changePassword',
            data={'oldpassword': 'Password1', 'newpassword': 'Password1', 'cpassword': 'Password1'},
        )
        html = response.get_data(as_text=True)

        self.assertIn('New password must be different from the current password.', html)
        self.assertEqual(self._stored_password(), original)

    def test_password_rules_are_enforced_without_updating(self):
        self._login_as('alice@example.com')
        original = self._stored_password()

        cases = (
            ('Short1', 'Password must be at least 8 characters long.'),
            ('12345678', 'Password must contain at least one letter.'),
            ('abcdefgh', 'Password must contain at least one number.'),
        )
        for new_password, message in cases:
            with self.subTest(new_password=new_password):
                response = self.client.post(
                    '/account/profile/changePassword',
                    data={
                        'oldpassword': 'Password1',
                        'newpassword': new_password,
                        'cpassword': new_password,
                    },
                )
                self.assertIn(message, response.get_data(as_text=True))
                self.assertEqual(self._stored_password(), original)

    def test_password_valid_change_still_updates(self):
        self._login_as('alice@example.com')

        response = self.client.post(
            '/account/profile/changePassword',
            data={'oldpassword': 'Password1', 'newpassword': 'NewSecret1', 'cpassword': 'NewSecret1'},
        )
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('Changed successfully', html)
        self.assertEqual(
            self._stored_password(), hashlib.md5(b'NewSecret1').hexdigest()
        )

    # ------------------------------------------------------------ add product

    def test_add_product_invalid_values_show_messages_and_save_nothing(self):
        self._login_admin()
        cases = (
            ({'price': '12.555'}, 'Price can have at most two decimal places.'),
            ({'price': '-1'}, 'Price cannot be negative.'),
            ({'price': 'abc'}, 'Price must be a number.'),
            ({'stock': '3.5'}, 'Stock must be a whole number.'),
            ({'stock': '-2'}, 'Stock cannot be negative.'),
            ({'category': '999'}, 'Select a valid category.'),
            ({'name': '   '}, 'Product name is required.'),
        )
        before = self._count('products')
        for overrides, message in cases:
            with self.subTest(overrides=overrides):
                response = self.client.post('/admin/add', data=self._product_data(**overrides))
                html = response.get_data(as_text=True)
                self.assertEqual(response.status_code, 200)
                self.assertIn(message, html)
                self.assertNotIn('Traceback', html)
                self.assertEqual(self._count('products'), before)

    def test_add_product_does_not_save_an_image_on_failure(self):
        self._login_admin()
        data = self._product_data(name='   ')
        data['image'] = (io.BytesIO(b'not a real image'), 'should-not-save.png')
        before = self._count('products')

        response = self.client.post(
            '/admin/add', data=data, content_type='multipart/form-data'
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('Product name is required.', response.get_data(as_text=True))
        self.assertEqual(self._count('products'), before)
        self.assertFalse(
            os.path.exists(os.path.join('static', 'uploads', 'should-not-save.png'))
        )

    def test_add_product_preserves_values_and_selected_category(self):
        self._login_admin()
        data = self._product_data(
            name='Gadget X',
            price='12.555',
            stock='3.5',
            category='2',
            description='Nice gadget',
        )
        response = self.client.post('/admin/add', data=data)
        html = response.get_data(as_text=True)

        self.assertIn('value="Gadget X"', html)
        self.assertIn('value="12.555"', html)
        self.assertIn('value="3.5"', html)
        self.assertIn('>Nice gadget</textarea>', html)
        self.assertIn('value="2" selected', html)

    def test_add_product_valid_data_still_inserts_and_redirects(self):
        self._login_admin()
        data = self._product_data(price='12.50', stock='3', category='2')

        response = self.client.post('/admin/add', data=data)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers['Location'].endswith('/admin'))
        self.assertEqual(self._count('products'), 2)

        connection = self._connect()
        try:
            row = connection.execute(
                'SELECT price, stock, categoryId, image FROM products WHERE name = ?',
                ('New Gadget',),
            ).fetchone()
        finally:
            connection.close()

        self.assertIsNotNone(row)
        self.assertAlmostEqual(row[0], 12.5)
        self.assertEqual(row[1], 3)
        self.assertEqual(row[2], 2)
        self.assertEqual(row[3], 'product-default.png')

    # ----------------------------------------------------------- edit product

    def test_edit_product_invalid_values_keep_row_and_save_no_image(self):
        self._login_admin()
        before = self._product_row()
        data = self._product_data(
            name='Edited Widget',
            price='12.555',
            stock='3.5',
            category='999',
            description='Edited description',
        )
        data['image'] = (io.BytesIO(b'not a real image'), 'bad-edit.png')

        response = self.client.post(
            '/admin/edit/1', data=data, content_type='multipart/form-data'
        )
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('Price can have at most two decimal places.', html)
        self.assertIn('Stock must be a whole number.', html)
        self.assertIn('Select a valid category.', html)
        self.assertNotIn('Traceback', html)
        self.assertEqual(self._product_row(), before)
        self.assertFalse(
            os.path.exists(os.path.join('static', 'uploads', 'bad-edit.png'))
        )

    def test_edit_product_preserves_values_and_selected_category(self):
        self._login_admin()
        data = self._product_data(
            name='Edited Name',
            price='abc',
            stock='3',
            category='2',
            description='Edited description',
        )
        response = self.client.post('/admin/edit/1', data=data)
        html = response.get_data(as_text=True)

        self.assertIn('value="Edited Name"', html)
        self.assertIn('value="abc"', html)
        self.assertIn('value="3"', html)
        self.assertIn('>Edited description</textarea>', html)
        self.assertIn('value="2" selected', html)

    def test_edit_product_valid_data_still_updates_and_redirects(self):
        self._login_admin()
        data = self._product_data(
            name='Edited Widget',
            price='12.50',
            stock='3',
            category='2',
            description='Updated description',
        )

        response = self.client.post('/admin/edit/1', data=data)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers['Location'].endswith('/admin'))

        row = self._product_row()
        self.assertEqual(row[0], 'Edited Widget')
        self.assertAlmostEqual(row[1], 12.5)
        self.assertEqual(row[2], 'Updated description')
        self.assertEqual(row[3], 'product-default.png')
        self.assertEqual(row[4], 3)
        self.assertEqual(row[5], 2)


if __name__ == '__main__':
    unittest.main()

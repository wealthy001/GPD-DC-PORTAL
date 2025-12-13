# app.py
import os
import sqlite3
from flask import Flask, request, jsonify, send_from_directory, session, redirect, url_for
from flask_cors import CORS
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from functools import wraps
from db_converter import DatabaseConverter

app = Flask(__name__)
CORS(app)
app.secret_key = 'gpd_super_secure_key_2025_change_this_later'

# === PATHS ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
DATABASE_FOLDER = os.path.join(BASE_DIR, 'database')
IMAGES_FOLDER = os.path.join(BASE_DIR, 'images')
DATABASE_PATH = os.path.join(DATABASE_FOLDER, 'gpd_portal.db')
PUBLIC_FOLDER = os.path.join(BASE_DIR, 'public')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(DATABASE_FOLDER, exist_ok=True)
os.makedirs(IMAGES_FOLDER, exist_ok=True)

db = DatabaseConverter(DATABASE_PATH, UPLOAD_FOLDER)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated


# =============== PUBLIC ROUTES ===============
@app.route('/')
def index():
    return send_from_directory(PUBLIC_FOLDER, 'index.html')

@app.route('/public/<path:filename>')
def public_files(filename):
    return send_from_directory(PUBLIC_FOLDER, filename)

@app.route('/images/<filename>')
def uploaded_image(filename):
    return send_from_directory(IMAGES_FOLDER, filename)


# =============== SEARCH API (PUBLIC) - NOW INCLUDES KC_ID ===============
@app.route('/api/search')
def search():
    query = request.args.get('q', '').strip().lower()
    if not query:
        return jsonify([])

    results = []
    conn = sqlite3.connect(DATABASE_PATH)
    cur = conn.cursor()

    cur.execute(f"""
        SELECT name, designation, blw_zone, image_path, region, chapter, group_name, kc_id
        FROM gpd_records
        WHERE LOWER(name) LIKE ? 
           OR LOWER(designation) LIKE ? 
           OR LOWER(blw_zone) LIKE ?
           OR LOWER(kc_id) LIKE ?
        ORDER BY name
    """, (f'%{query}%', f'%{query}%', f'%{query}%', f'%{query}%'))
    
    for row in cur.fetchall():
        results.append({
            'name': row[0],
            'designation': row[1] or '',
            'blw_zone': row[2] or '',
            'photo': row[3] if row[3] else '/public/default-photo.jpg',
            'region': row[4] or '',
            'chapter': row[5] or '',
            'group': row[6] or '',
            'kc_id': row[7] or ''  # ← KC ID now included and searchable
        })

    conn.close()
    return jsonify(results)


# =============== ADMIN ROUTES ===============
@app.route('/admin')
@login_required
def admin():
    return send_from_directory(BASE_DIR, 'admin.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        conn = sqlite3.connect(DATABASE_PATH)
        cur = conn.cursor()
        cur.execute("SELECT id, password FROM users WHERE username = ?", (username,))
        user = cur.fetchone()
        conn.close()

        if user and check_password_hash(user[1], password):
            session['logged_in'] = True
            return redirect(request.args.get('next') or '/admin')
        else:
            error = '<div style="color:red;text-align:center;margin:20px;font-weight:bold;">Invalid username or password</div>'
            html = open(os.path.join(BASE_DIR, 'login.html'), 'r', encoding='utf-8').read()
            return html.replace('</body>', error + '</body>')

    return send_from_directory(BASE_DIR, 'login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/<path:filename>')
@login_required
def admin_files(filename):
    return send_from_directory(BASE_DIR, filename)


# =============== ADMIN APIs ===============
@app.route('/api/upload-image', methods=['POST'])
@login_required
def upload_image():
    try:
        if 'image' not in request.files:
            return jsonify({'success': False, 'error': 'No image'}), 400
        file = request.files['image']
        name = request.form.get('name', '').strip()
        if not name:
            return jsonify({'success': False, 'error': 'Name required'}), 400

        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in {'.jpg', '.jpeg', '.png', '.gif', '.webp'}:
            return jsonify({'success': False, 'error': 'Invalid format'}), 400

        timestamp = datetime.now().strftime('%Y%m%d')
        safe_name = secure_filename(name.replace(' ', '_'))
        filename = f"{safe_name}_{timestamp}{ext}"
        filepath = os.path.join(IMAGES_FOLDER, filename)
        file.save(filepath)

        image_url = f"/images/{filename}"

        conn = sqlite3.connect(DATABASE_PATH)
        cur = conn.cursor()
        cur.execute("UPDATE gpd_records SET image_path = ? WHERE TRIM(LOWER(name)) = TRIM(LOWER(?))", (image_url, name))
        affected = cur.rowcount
        conn.commit()
        conn.close()

        if affected == 0:
            os.remove(filepath)
            return jsonify({'success': False, 'error': f'No record found: "{name}"'}), 404

        return jsonify({'success': True, 'message': 'Photo linked!', 'image_path': image_url})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/upload-dataset', methods=['POST'])
@login_required
def upload_dataset():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file'}), 400
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        if not db.allowed_file(file.filename):
            return jsonify({'error': 'Only Excel/CSV'}), 400

        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
        saved_name = timestamp + "_" + filename
        filepath = os.path.join(UPLOAD_FOLDER, saved_name)
        file.save(filepath)

        result = db.convert_excel_to_sql(filepath)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/add-record', methods=['POST'])
@login_required
def add_record():
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        if not name:
            return jsonify({'success': False, 'error': 'Name required'}), 400

        conn = sqlite3.connect(DATABASE_PATH)
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO gpd_records (region, designation, name, kc_id, blw_zone, group_name, chapter)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            data.get('region', ''),
            data.get('designation', ''),
            name,
            data.get('kc_id', ''),
            data.get('blw_zone', ''),
            data.get('group_name', ''),
            data.get('chapter', '')
        ))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'Record added'})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'error': 'Name already exists'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    db.init_db()
    db.add_image_path_column_if_missing()
    print("GPD PORTAL RUNNING")
    print("Public: http://127.0.0.1:5000/")
    print("Admin: http://127.0.0.1:5000/admin")
    print("Default login: super / superuser")
    app.run(debug=True, port=5000)
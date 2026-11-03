from flask import Flask, render_template, request, redirect, url_for, Response, jsonify, session, send_from_directory
import os
import cv2
import pickle
import numpy as np
import mysql.connector
from datetime import datetime
import base64
import time
import smtplib
from email.message import EmailMessage
import threading
import webbrowser
import random
from werkzeug.security import generate_password_hash, check_password_hash

# ML Pipeline Import
from ml_pipeline.face_engine import get_face_embeddings, add_user_embeddings, train_admin_svm, remove_user_from_embeddings

app = Flask(__name__)
app.secret_key = 'securehome_advanced_workspace_secret_key'

# Directories Setup
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
COLLECTED_DIR = os.path.join(BASE_DIR, 'CollectedImages')
os.makedirs(COLLECTED_DIR, exist_ok=True)

# ================= EMAIL CONFIGURATION =================
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587
SENDER_EMAIL = 'shakirjalal44@gmail.com' 
SENDER_PASSWORD = 'jpif khvb hews vyrf' 

def _send_email_thread(image_path, capture_time, receiver_email):
    try:
        clean_password = SENDER_PASSWORD.replace(" ", "").strip()
        msg = EmailMessage()
        msg['Subject'] = '🚨 SECURITY ALERT: Unknown Visitor Detected!'
        msg['From'] = SENDER_EMAIL
        msg['To'] = receiver_email
        msg.set_content(
            f'SecureHome Workspace Alert!\n\n'
            f'An unknown visitor has been detected on your camera.\n'
            f'Time: {capture_time}\n\n'
            f'The captured photo is attached with this email. Please check your dashboard.'
        )

        if os.path.exists(image_path):
            with open(image_path, 'rb') as f:
                msg.add_attachment(f.read(), maintype='image', subtype='jpeg', filename=os.path.basename(image_path))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=20) as server:
            server.ehlo()
            server.starttls()
            server.login(SENDER_EMAIL, clean_password)
            server.send_message(msg)
        print(f'📧 Alert email successfully sent to {receiver_email}!')
    except Exception as e:
        print(f'❌ Error sending email: {e}')

def send_alert_email(image_path, capture_time, receiver_email):
    t = threading.Thread(target=_send_email_thread, args=(image_path, capture_time, receiver_email), daemon=True)
    t.start()

def send_otp_email(receiver_email, otp_code):
    try:
        clean_password = SENDER_PASSWORD.replace(" ", "").strip()
        msg = EmailMessage()
        msg['Subject'] = '🔐 SecureHome - Password Reset & Verification OTP'
        msg['From'] = SENDER_EMAIL
        msg['To'] = receiver_email
        msg.set_content(
            f'SecureHome Workspace Verification\n\n'
            f'Your verification OTP code is: {otp_code}\n\n'
            f'This code is valid for 10 minutes. Do not share this code with anyone.'
        )

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=20) as server:
            server.ehlo()
            server.starttls()
            server.login(SENDER_EMAIL, clean_password)
            server.send_message(msg)
        print(f'📧 OTP email successfully sent to {receiver_email}!')
    except Exception as e:
        print(f'❌ Error sending OTP email: {e}')

# ================= AUTO DATABASE SETUP FUNCTION =================
def initialize_database_automatically():
    try:
        db = mysql.connector.connect(host='localhost', user='root', password='mysql')
        cursor = db.cursor()
        
        cursor.execute("CREATE DATABASE IF NOT EXISTS secure_home_db")
        cursor.execute("USE secure_home_db")
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                admin_id INT AUTO_INCREMENT PRIMARY KEY,
                full_name VARCHAR(100),
                username VARCHAR(50) NOT NULL UNIQUE,
                phone VARCHAR(15),
                email VARCHAR(100) UNIQUE,
                gender VARCHAR(20),
                profession VARCHAR(100),
                dob DATE,
                password VARCHAR(255) NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS authorized_users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                admin_id INT,
                name VARCHAR(100) NOT NULL,
                role VARCHAR(50),
                email VARCHAR(100),
                photo_path VARCHAR(255),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (admin_id) REFERENCES admins(admin_id) ON DELETE CASCADE
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS unknown_alerts (
                id INT AUTO_INCREMENT PRIMARY KEY,
                admin_id INT,
                image_path VARCHAR(255),
                status VARCHAR(20) DEFAULT 'New',
                capture_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (admin_id) REFERENCES admins(admin_id) ON DELETE CASCADE
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS security_logs (
                log_id INT AUTO_INCREMENT PRIMARY KEY,
                admin_id INT,
                person_name VARCHAR(100),
                event_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                event_type VARCHAR(50),
                details TEXT,
                FOREIGN KEY (admin_id) REFERENCES admins(admin_id) ON DELETE CASCADE
            )
        ''')
        
        db.commit()
        cursor.close()
        db.close()
        print("✅ Database & Tables verified/created successfully automatically!")
    except Exception as e:
        print(f"❌ Auto Database Setup Error: {e}")

def get_db():
    try:
        return mysql.connector.connect(host='localhost', user='root', password='mysql', database='secure_home_db')
    except Exception as e:
        print(f'❌ Database connection error: {e}')
        return None

# ================= VIDEO FEED & RECOGNITION =================
def generate_frames(admin_id):
    admin_folder = os.path.join(COLLECTED_DIR, f"admin_{admin_id}")
    model_path = os.path.join(admin_folder, "svm_model.pkl")
    features_path = os.path.join(admin_folder, "features.pkl")
    
    svm_model = None
    if os.path.exists(model_path):
        with open(model_path, 'rb') as f:
            svm_model = pickle.load(f)

    cap = cv2.VideoCapture(0)
    face_cascade = cv2.CascadeClassifier('haarcascade_frontalface_default.xml')
    unknown_counter = 0
    cooldown = 0
    last_logged_time = {}
    
    while True:
        success, frame = cap.read()
        if not success: break
        
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
        
        if cooldown > 0: cooldown -= 1
        
        for (x, y, w, h) in faces:
            face_img = frame[y:y+h, x:x+w]
            name = "Unknown Visitor"
            color = (139, 127, 255) # Red Color
            
            if svm_model is not None:
                embedding = get_face_embeddings(face_img)
                if embedding:
                    preds = svm_model.predict_proba([embedding])[0]
                    best_idx = np.argmax(preds)
                    
                    # 🟢 Increased confidence threshold from 0.60 to 0.75 to prevent false recognitions
                    if preds[best_idx] > 0.75:
                        name = str(svm_model.classes_[best_idx])
                        color = (162, 224, 93) # Green Color
                        unknown_counter = 0
                        
                        current_time = time.time()
                        if name not in last_logged_time or (current_time - last_logged_time[name]) > 30:
                            last_logged_time[name] = current_time
                            db = get_db()
                            if db:
                                cursor = db.cursor()
                                cursor.execute(
                                    'INSERT INTO security_logs (admin_id, person_name, event_type, details) VALUES (%s, %s, %s, %s)', 
                                    (admin_id, name, 'Authorized Entry', f'{name} successfully authenticated.')
                                )
                                db.commit()
                                db.close()

            if name == "Unknown Visitor":
                unknown_counter += 1
                
            cv2.rectangle(frame, (x, y), (x+w, y+h), color, 2)
            cv2.rectangle(frame, (x, y+h), (x+w, y+h+30), color, cv2.FILLED)
            cv2.putText(frame, name, (x+6, y+h+20), cv2.FONT_HERSHEY_DUPLEX, 0.6, (0,0,0), 1)

            if unknown_counter >= 15 and cooldown == 0:
                capture_dt = datetime.now()
                filename = f"Alert_{capture_dt.strftime('%Y%m%d_%H%M%S')}.jpg"
                os.makedirs(admin_folder, exist_ok=True)
                abs_img_path = os.path.join(admin_folder, filename)
                rel_img_path = f"admin_{admin_id}/{filename}"
                
                cv2.imwrite(abs_img_path, frame)
                
                db = get_db()
                if db:
                    cursor = db.cursor(dictionary=True)
                    cursor.execute('SELECT email FROM admins WHERE admin_id = %s', (admin_id,))
                    admin_data = cursor.fetchone()
                    admin_email = admin_data['email'] if admin_data else None

                    cursor.execute('INSERT INTO unknown_alerts (admin_id, image_path) VALUES (%s, %s)', (admin_id, rel_img_path))
                    cursor.execute('INSERT INTO security_logs (admin_id, person_name, event_type, details) VALUES (%s, %s, %s, %s)', 
                                   (admin_id, 'Unknown', 'Alert', 'Unknown visitor photo captured'))
                    db.commit()
                    db.close()
                    
                    if admin_email:
                        send_alert_email(abs_img_path, capture_dt.strftime('%b %d, %Y %H:%M:%S'), admin_email)

                unknown_counter = 0
                cooldown = 150
                
        ret, buffer = cv2.imencode('.jpg', frame)
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

# ================= ROUTES =================

@app.route('/CollectedImages/<path:filename>')
def serve_collected_images(filename):
    return send_from_directory(COLLECTED_DIR, filename)

@app.route('/api/check_session')
def check_session():
    if 'admin_id' not in session: return jsonify({'status': 'unauthorized'}), 401
    return jsonify({'status': 'authorized'}), 200

@app.route('/')
def index():
    if 'admin_id' in session: return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        db = get_db()
        if db:
            cursor = db.cursor(dictionary=True)
            cursor.execute("SELECT * FROM admins WHERE username=%s", (username,))
            admin = cursor.fetchone()
            db.close()
            
            if admin and check_password_hash(admin['password'], password):
                session['admin_id'] = admin['admin_id']
                session['admin_name'] = admin['full_name']
                return redirect(url_for('dashboard'))
            return render_template('login.html', error="Invalid Username or Password.")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'send_otp':
            email = request.form.get('email')
            db = get_db()
            if db:
                cursor = db.cursor(dictionary=True)
                cursor.execute("SELECT * FROM admins WHERE email = %s", (email,))
                existing = cursor.fetchone()
                db.close()
                if existing:
                    return render_template('register.html', error="Email already registered! Please login.")
            
            otp = str(random.randint(100000, 999999))
            session['reg_otp'] = otp
            session['reg_data'] = {
                'fullname': request.form.get('fullname'),
                'username': request.form.get('username'),
                'email': email,
                'phone': request.form.get('phone'),
                'gender': request.form.get('gender'),
                'profession': request.form.get('profession'),
                'dob': request.form.get('dob'),
                'password': request.form.get('password')
            }
            send_otp_email(email, otp)
            return render_template('register.html', show_otp_box=True, email=email)

        elif action == 'verify_and_register':
            user_otp = request.form.get('otp')
            if user_otp == session.get('reg_otp'):
                data = session.get('reg_data')
                hashed_password = generate_password_hash(data['password'])
                
                db = get_db()
                if db:
                    cursor = db.cursor()
                    try:
                        cursor.execute("""
                            INSERT INTO admins (full_name, username, email, phone, gender, profession, dob, password) 
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """, (data['fullname'], data['username'], data['email'], data['phone'], data['gender'], data['profession'], data['dob'], hashed_password))
                        db.commit()
                        new_admin_id = cursor.lastrowid
                        os.makedirs(os.path.join(COLLECTED_DIR, f"admin_{new_admin_id}"), exist_ok=True)
                        
                        session.pop('reg_otp', None)
                        session.pop('reg_data', None)
                        return redirect(url_for('login'))
                    except mysql.connector.Error:
                        return render_template('register.html', error="Username already exists! Try another.")
                    finally:
                        db.close()
            else:
                return render_template('register.html', show_otp_box=True, email=session.get('reg_data', {}).get('email'), error="Invalid OTP! Please try again.")
                
    return render_template('register.html', show_otp_box=False)

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'send_reset_otp':
            email = request.form.get('email')
            db = get_db()
            if db:
                cursor = db.cursor(dictionary=True)
                cursor.execute("SELECT * FROM admins WHERE email = %s", (email,))
                admin = cursor.fetchone()
                db.close()
                
                if admin:
                    otp = str(random.randint(100000, 999999))
                    session['reset_otp'] = otp
                    session['reset_email'] = email
                    send_otp_email(email, otp)
                    return render_template('forgot_password.html', step='verify_otp', email=email)
                else:
                    return render_template('forgot_password.html', step='request_email', error="Email address not found in system.")
        
        elif action == 'update_password':
            user_otp = request.form.get('otp')
            new_password = request.form.get('new_password')
            email = session.get('reset_email')
            
            if user_otp == session.get('reset_otp'):
                hashed_password = generate_password_hash(new_password)
                db = get_db()
                if db:
                    cursor = db.cursor()
                    cursor.execute("UPDATE admins SET password = %s WHERE email = %s", (hashed_password, email))
                    db.commit()
                    db.close()
                    
                session.pop('reset_otp', None)
                session.pop('reset_email', None)
                return redirect(url_for('login'))
            else:
                return render_template('forgot_password.html', step='verify_otp', email=email, error="Invalid OTP code.")
                
    return render_template('forgot_password.html', step='request_email')

@app.route('/profile')
def profile():
    if 'admin_id' not in session: return redirect(url_for('login'))
    admin_id = session['admin_id']
    db = get_db()
    admin_data = None
    if db:
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT full_name, username, email, phone, gender, profession, dob FROM admins WHERE admin_id = %s", (admin_id,))
        admin_data = cursor.fetchone()
        db.close()
    return render_template('profile.html', admin=admin_data)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'admin_id' not in session: return redirect(url_for('login'))
    admin_id = session['admin_id']
    db = get_db()
    data = {'user_count': 0, 'unknown_count': 0, 'recent_logs': []}
    
    if db:
        cursor = db.cursor(dictionary=True)
        cursor.execute('SELECT COUNT(*) as c FROM authorized_users WHERE admin_id = %s', (admin_id,))
        data['user_count'] = cursor.fetchone()['c']
        
        cursor.execute("SELECT COUNT(*) as c FROM unknown_alerts WHERE admin_id = %s AND status = 'New'", (admin_id,))
        data['unknown_count'] = cursor.fetchone()['c']
        
        cursor.execute("SELECT person_name, DATE_FORMAT(event_time, '%b %d, %H:%i') as event_time, event_type, details FROM security_logs WHERE admin_id = %s ORDER BY event_time DESC LIMIT 5", (admin_id,))
        logs = cursor.fetchall()
        data['recent_logs'] = [{'person': l['person_name'], 'time': l['event_time'], 'type': l['event_type'], 'details': l['details']} for l in logs]
        db.close()
        
    return render_template('dashboard.html', **data)

@app.route('/camera')
def camera():
    if 'admin_id' not in session: return redirect(url_for('login'))
    return render_template('camera.html')

@app.route('/api/video_feed')
def video_feed():
    if 'admin_id' not in session: return "Unauthorized", 401
    return Response(generate_frames(session['admin_id']), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/users')
def users():
    if 'admin_id' not in session: return redirect(url_for('login'))
    admin_id = session['admin_id']
    db = get_db()
    users_list = []
    
    if db:
        cursor = db.cursor(dictionary=True)
        cursor.execute('SELECT id, name, role, email FROM authorized_users WHERE admin_id = %s ORDER BY created_at DESC', (admin_id,))
        users_list = cursor.fetchall()
        db.close()
    return render_template('users.html', users=users_list)

@app.route('/api/upload_frame', methods=['POST'])
def upload_frame():
    if 'admin_id' not in session: return jsonify({'error': 'Unauthorized'}), 401
    
    admin_id = session['admin_id']
    data = request.get_json()
    name = data.get('name').strip().replace(' ', '_')
    frame_idx = data.get('frame_idx')
    photo_b64 = data.get('photo_base64')
    
    if not name or not photo_b64: return jsonify({'error': 'Missing data'}), 400
        
    user_dir = os.path.join(COLLECTED_DIR, f"admin_{admin_id}", name)
    os.makedirs(user_dir, exist_ok=True)
    
    _, encoded = photo_b64.split(',', 1)
    with open(os.path.join(user_dir, f'capture_{frame_idx}.jpg'), 'wb') as f:
        f.write(base64.b64decode(encoded))
        
    return jsonify({'status': 'success'})

@app.route('/api/add_user', methods=['POST'])
def add_user():
    if 'admin_id' not in session: return redirect(url_for('login'))
    
    admin_id = session['admin_id']
    name = request.form.get('name')
    role = request.form.get('role')
    email = request.form.get('email')
    
    if name:
        safe_user = name.strip().replace(' ', '_')
        user_dir = os.path.join(COLLECTED_DIR, f"admin_{admin_id}", safe_user)
        
        if os.path.exists(user_dir):
            image_paths = [os.path.join(user_dir, f) for f in os.listdir(user_dir) if f.endswith('.jpg')]
            
            if image_paths:
                success = add_user_embeddings(admin_id, name, image_paths, COLLECTED_DIR)
                
                if success:
                    db = get_db()
                    if db:
                        cursor = db.cursor()
                        cursor.execute('INSERT INTO authorized_users (admin_id, name, role, email) VALUES (%s, %s, %s, %s)', 
                                       (admin_id, name, role, email))
                        cursor.execute('INSERT INTO security_logs (admin_id, person_name, event_type, details) VALUES (%s, %s, %s, %s)', 
                                       (admin_id, name, 'System Update', 'New user enrolled & model trained'))
                        db.commit()
                        db.close()
                    
    return redirect(url_for('users', added=True))

@app.route('/api/delete_user/<int:user_id>')
def delete_user(user_id):
    if 'admin_id' not in session: return redirect(url_for('login'))
    admin_id = session['admin_id']
    
    db = get_db()
    if db:
        cursor = db.cursor(dictionary=True)
        cursor.execute('SELECT name FROM authorized_users WHERE id = %s AND admin_id = %s', (user_id, admin_id))
        user = cursor.fetchone()
        
        if user:
            user_name = user['name']
            cursor.execute('DELETE FROM authorized_users WHERE id = %s', (user_id,))
            cursor.execute('INSERT INTO security_logs (admin_id, person_name, event_type, details) VALUES (%s, %s, %s, %s)', 
                           (admin_id, user_name, 'System Update', 'User removed from authorized workspace'))
            db.commit()
            db.close()
            
            remove_user_from_embeddings(admin_id, user_name, COLLECTED_DIR)
            
    return redirect(url_for('users'))

@app.route('/alerts')
def alerts():
    if 'admin_id' not in session: return redirect(url_for('login'))
    admin_id = session['admin_id']
    db = get_db()
    alerts_list = []
    
    if db:
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT id, image_path, DATE_FORMAT(capture_time, '%b %d, %Y %H:%i') as time, status FROM unknown_alerts WHERE admin_id = %s ORDER BY capture_time DESC", (admin_id,))
        alerts_list = cursor.fetchall()
        db.close()
    return render_template('alerts.html', alerts=alerts_list)

@app.route('/api/resolve_alert/<int:alert_id>')
def resolve_alert(alert_id):
    if 'admin_id' not in session: return redirect(url_for('login'))
    admin_id = session['admin_id']
    db = get_db()
    if db:
        cursor = db.cursor()
        cursor.execute("UPDATE unknown_alerts SET status = 'Resolved' WHERE id = %s AND admin_id = %s", (alert_id, admin_id))
        cursor.execute('INSERT INTO security_logs (admin_id, person_name, event_type, details) VALUES (%s, %s, %s, %s)', 
                       (admin_id, 'System', 'Admin Action', f'Alert #{alert_id} resolved'))
        db.commit()
        db.close()
    return redirect(url_for('alerts'))

@app.route('/logs')
def logs():
    if 'admin_id' not in session: return redirect(url_for('login'))
    admin_id = session['admin_id']
    db = get_db()
    logs_list = []
    
    if db:
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT person_name as person, DATE_FORMAT(event_time, '%b %d, %Y %H:%i') as time, event_type as type, details FROM security_logs WHERE admin_id = %s ORDER BY event_time DESC", (admin_id,))
        logs_list = cursor.fetchall()
        db.close()
    return render_template('logs.html', logs=logs_list)

@app.route('/api/clear_logs')
def clear_logs():
    if 'admin_id' not in session: return redirect(url_for('login'))
    admin_id = session['admin_id']
    
    db = get_db()
    if db:
        cursor = db.cursor()
        cursor.execute("DELETE FROM security_logs WHERE admin_id = %s", (admin_id,))
        cursor.execute('INSERT INTO security_logs (admin_id, person_name, event_type, details) VALUES (%s, %s, %s, %s)', 
                       (admin_id, 'System', 'Admin Action', 'All security logs cleared by admin'))
        db.commit()
        db.close()
    return redirect(url_for('logs'))

if __name__ == '__main__':
    initialize_database_automatically()
    threading.Timer(1.2, lambda: webbrowser.open("http://127.0.0.1:5000/")).start()
    app.run(debug=True, port=5000, threaded=True)
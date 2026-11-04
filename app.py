"""SecureHome - face recognition home security (Flask + MySQL + DeepFace/ArcFace)."""
import os, re, io, csv, time, base64, random, secrets, smtplib, threading, webbrowser
from datetime import datetime
from email.message import EmailMessage
from functools import wraps

import cv2
import numpy as np
import mysql.connector
from flask import (Flask, render_template, request, redirect, url_for, Response,
                   jsonify, session, send_from_directory, flash, abort)
from werkzeug.security import generate_password_hash, check_password_hash


from ml_pipeline.face_engine import (get_face_embeddings, add_user_embeddings,
                                     remove_user_from_embeddings, identify, count_samples)

# ======================================================================
#  SETTINGS. Put your REAL passwords in local_settings.py (git-ignored), not here.
#  The values below are safe placeholders. Environment variables also override them.
# ======================================================================
CONFIG = {
    'SECRET_KEY': 'change-this-secret-key',
    'DB_HOST': 'localhost',
    'DB_USER': 'root',
    'DB_PASSWORD': 'your-mysql-password',
    'DB_NAME': 'secure_homedb',
    'SMTP_SERVER': 'smtp.gmail.com',
    'SMTP_PORT': 587,
    'SENDER_EMAIL': 'your-gmail@gmail.com',
    'SENDER_PASSWORD': 'your-16-letter-gmail-app-password',   # Gmail app password (spaces are ignored)
    'CAMERA_INDEX': 0,
    'UNKNOWN_SECONDS': 5,                         # how long a stranger must stay in view before an alert
    'ALERT_COOLDOWN_SECONDS': 60,                 # minimum wait between two alerts
    # Default admin, created automatically if it does not exist. Change the password in My profile.
    'DEFAULT_ADMIN_NAME': 'Administrator',
    'DEFAULT_ADMIN_USERNAME': 'admin',
    'DEFAULT_ADMIN_PASSWORD': 'admin123',
    'DEFAULT_ADMIN_EMAIL': 'admin@example.com',   # alert emails are sent to this address
    'DEFAULT_ADMIN_PHONE': '0000000000',
    'DEFAULT_ADMIN_GENDER': 'Male',
    'DEFAULT_ADMIN_PROFESSION': 'Admin',
    'DEFAULT_ADMIN_DOB': '2000-01-01',
}

# Private overrides: create local_settings.py (it is git-ignored) with your real passwords.
try:
    from local_settings import CONFIG as _LOCAL
    CONFIG.update(_LOCAL)
except ImportError:
    pass



def cfg(name):
    return os.environ.get(name, CONFIG[name])


# ----------------------------------------------------------------- config
app = Flask(__name__)
app.secret_key = cfg('SECRET_KEY')
if app.secret_key == 'change-this-secret-key':
    print('WARNING: set a real SECRET_KEY in local_settings.py (see README).')
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', MAX_CONTENT_LENGTH=4 * 1024 * 1024)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
COLLECTED_DIR = os.path.join(BASE_DIR, 'CollectedImages')
os.makedirs(COLLECTED_DIR, exist_ok=True)
CASCADE_PATH = os.path.join(BASE_DIR, 'haarcascade_frontalface_default.xml')

DB = dict(host=cfg('DB_HOST'), user=cfg('DB_USER'),
          password=cfg('DB_PASSWORD'))
DB_NAME = cfg('DB_NAME')
SMTP_SERVER = cfg('SMTP_SERVER')
SMTP_PORT = int(cfg('SMTP_PORT'))
SENDER_EMAIL = cfg('SENDER_EMAIL')
SENDER_PASSWORD = cfg('SENDER_PASSWORD').replace(' ', '')

CAMERA_INDEX = int(cfg('CAMERA_INDEX'))
UNKNOWN_SECONDS = float(cfg('UNKNOWN_SECONDS'))
ALERT_COOLDOWN = float(cfg('ALERT_COOLDOWN_SECONDS'))
RECOGNIZE_EVERY = 6          # run the heavy recogniser every N frames (boxes still update every frame)
DEFAULT_ADMIN = dict(          # created automatically on first run if there are no admins yet
    full_name=cfg('DEFAULT_ADMIN_NAME'),
    username=cfg('DEFAULT_ADMIN_USERNAME'),
    email=cfg('DEFAULT_ADMIN_EMAIL'),
    phone=cfg('DEFAULT_ADMIN_PHONE'),
    gender=cfg('DEFAULT_ADMIN_GENDER'),
    profession=cfg('DEFAULT_ADMIN_PROFESSION'),
    dob=cfg('DEFAULT_ADMIN_DOB'),
    password=cfg('DEFAULT_ADMIN_PASSWORD'),
)
OTP_TTL = 600                # seconds
ENROLL_FRAMES = 50


# ----------------------------------------------------------------- database
def get_db():
    try:
        return mysql.connector.connect(database=DB_NAME, **DB)
    except Exception as e:
        print(f'Database connection error: {e}')
        return None


def query(sql, params=(), one=False, commit=False):
    """Tiny helper: run one statement, return rows (dicts) or lastrowid."""
    db = get_db()
    if not db:
        return None if one else []
    try:
        cur = db.cursor(dictionary=True)
        cur.execute(sql, params)
        if commit:
            db.commit()
            return cur.lastrowid
        return cur.fetchone() if one else cur.fetchall()
    finally:
        db.close()


def count(sql, params=()):
    row = query(sql, params, one=True)
    return row['c'] if row else 0


def fmt_dates(rows, field, pattern):
    """Turn datetime values into readable text, e.g. 'Nov 05, 2026 14:30'."""
    for r in rows or []:
        v = r.get(field)
        r[field] = v.strftime(pattern) if hasattr(v, 'strftime') else (v or '')
    return rows


def log_event(admin_id, person, event_type, details):
    query('INSERT INTO security_logs (admin_id, person_name, event_type, details) VALUES (%s,%s,%s,%s)',
          (admin_id, person, event_type, details), commit=True)


def initialize_database():
    try:
        db = mysql.connector.connect(**DB)
        c = db.cursor()
        c.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME}")
        c.execute(f"USE {DB_NAME}")
        c.execute('''CREATE TABLE IF NOT EXISTS admins (
            admin_id INT AUTO_INCREMENT PRIMARY KEY, full_name VARCHAR(100),
            username VARCHAR(50) NOT NULL UNIQUE, phone VARCHAR(15), email VARCHAR(100) UNIQUE,
            gender VARCHAR(20), profession VARCHAR(100), dob DATE, password VARCHAR(255) NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS authorized_users (
            id INT AUTO_INCREMENT PRIMARY KEY, admin_id INT, name VARCHAR(100) NOT NULL, role VARCHAR(50),
            email VARCHAR(100), photo_path VARCHAR(255), created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (admin_id) REFERENCES admins(admin_id) ON DELETE CASCADE)''')
        c.execute('''CREATE TABLE IF NOT EXISTS unknown_alerts (
            id INT AUTO_INCREMENT PRIMARY KEY, admin_id INT, image_path VARCHAR(255),
            status VARCHAR(20) DEFAULT 'New', capture_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (admin_id) REFERENCES admins(admin_id) ON DELETE CASCADE)''')
        c.execute('''CREATE TABLE IF NOT EXISTS security_logs (
            log_id INT AUTO_INCREMENT PRIMARY KEY, admin_id INT, person_name VARCHAR(100),
            event_time DATETIME DEFAULT CURRENT_TIMESTAMP, event_type VARCHAR(50), details TEXT,
            FOREIGN KEY (admin_id) REFERENCES admins(admin_id) ON DELETE CASCADE)''')
        db.commit()
        d = DEFAULT_ADMIN
        c.execute('SELECT COUNT(*) FROM admins WHERE username=%s OR email=%s', (d['username'], d['email']))
        if c.fetchone()[0] == 0:                      # make sure the default admin always exists
            c.execute('''INSERT INTO admins (full_name, username, email, phone, gender, profession, dob, password)
                         VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''',
                      (d['full_name'], d['username'], d['email'], d['phone'], d['gender'], d['profession'],
                       d['dob'], generate_password_hash(d['password'])))
            db.commit()
            os.makedirs(os.path.join(COLLECTED_DIR, f'admin_{c.lastrowid}'), exist_ok=True)
            print(f"Default admin created. Log in with username '{d['username']}'. Change the password in My profile.")
        c.close(); db.close()
        print('Database ready.')
    except Exception as e:
        print(f'Database setup error: {e}')


# ----------------------------------------------------------------- email
def _smtp_send(msg):
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        print('Email not configured (set SENDER_EMAIL / SENDER_PASSWORD in the CONFIG block of app.py).')
        return False
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=20) as s:
            s.ehlo(); s.starttls(); s.login(SENDER_EMAIL, SENDER_PASSWORD); s.send_message(msg)
        return True
    except Exception as e:
        print(f'Email error: {e}')
        return False


def send_alert_email(image_path, when, to):
    def work():
        msg = EmailMessage()
        msg['Subject'], msg['From'], msg['To'] = 'SecureHome alert: unknown visitor detected', SENDER_EMAIL, to
        msg.set_content(f'An unknown visitor stayed in front of your camera.\nTime: {when}\n\n'
                        'The photo is attached. Open your SecureHome dashboard to review it.')
        if os.path.exists(image_path):
            with open(image_path, 'rb') as f:
                msg.add_attachment(f.read(), maintype='image', subtype='jpeg', filename=os.path.basename(image_path))
        _smtp_send(msg)
    threading.Thread(target=work, daemon=True).start()


def send_otp_email(to, code, purpose='verification'):
    msg = EmailMessage()
    msg['Subject'], msg['From'], msg['To'] = f'SecureHome {purpose} code', SENDER_EMAIL, to
    msg.set_content(f'Your SecureHome code is {code}.\nIt is valid for 10 minutes. Do not share it with anyone.')
    return _smtp_send(msg)


# ----------------------------------------------------------------- live camera worker
class CameraWorker(threading.Thread):
    """One background thread per admin: reads the camera, recognises faces, raises alerts.
    Every browser tab watching the feed shares the same worker (no more camera conflicts)."""

    def __init__(self, admin_id):
        super().__init__(daemon=True)
        self.admin_id = admin_id
        self.cond = threading.Condition()
        self.jpeg, self.seq = None, 0
        self.viewers, self.last_viewer = 0, time.time()
        self.alive = True
        self.status = dict(running=True, fps=0, faces=0, people=[], unknown_for=0, last_alert=None, error=None)

    # --- viewer bookkeeping
    def acquire(self):
        self.viewers += 1; self.last_viewer = time.time()

    def release(self):
        self.viewers = max(0, self.viewers - 1); self.last_viewer = time.time()

    # --- main loop
    def run(self):
        cap = cv2.VideoCapture(CAMERA_INDEX)
        if not cap.isOpened():
            self.status.update(running=False, error='Camera not available. Check that no other app is using it.')
            self._publish(self._message_frame('Camera not available'))
            self.alive = False
            return
        cascade = cv2.CascadeClassifier(CASCADE_PATH)
        admin_folder = os.path.join(COLLECTED_DIR, f'admin_{self.admin_id}')
        tracked = []                         # [(box, name, conf)] from the last recognition pass
        frame_no, fps_t, fps_n = 0, time.time(), 0
        unknown_since, last_face_seen, last_alert = None, 0, 0
        last_logged = {}

        try:
            while self.alive:
                if self.viewers == 0 and time.time() - self.last_viewer > 8:
                    break                                          # nobody watching: free the camera
                ok, frame = cap.read()
                if not ok:
                    self.status['error'] = 'Lost connection to camera.'
                    break
                frame_no += 1
                gray = cv2.equalizeHist(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
                faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(60, 60))

                if len(faces):
                    last_face_seen = time.time()
                recognise = frame_no % RECOGNIZE_EVERY == 1 or len(faces) != len(tracked)
                results = []
                for (x, y, w, h) in faces:
                    box = (int(x), int(y), int(w), int(h))
                    name, conf = None, 0.0
                    if recognise:
                        emb = get_face_embeddings(frame[y:y + h, x:x + w])
                        name, conf = identify(self.admin_id, emb, COLLECTED_DIR)
                    else:                                          # reuse the nearest previous result
                        near = min(tracked, key=lambda t: abs(t[0][0] - x) + abs(t[0][1] - y), default=None)
                        if near and abs(near[0][0] - x) + abs(near[0][1] - y) < w:
                            name, conf = near[1], near[2]
                    results.append((box, name, conf))
                tracked = results

                now = time.time()
                known = [r for r in results if r[1]]
                if known:
                    unknown_since = None
                    for _, name, _ in known:
                        if now - last_logged.get(name, 0) > 30:
                            last_logged[name] = now
                            log_event(self.admin_id, name, 'Authorized Entry', f'{name} was recognised by the camera.')
                elif results:
                    unknown_since = unknown_since or now
                elif now - last_face_seen > 3:
                    unknown_since = None

                unknown_for = (now - unknown_since) if unknown_since else 0
                if unknown_for >= UNKNOWN_SECONDS and now - last_alert > ALERT_COOLDOWN:
                    last_alert = now
                    self._raise_alert(frame.copy(), admin_folder)
                    unknown_since = None

                self._draw(frame, results, unknown_for)
                fps_n += 1
                if now - fps_t >= 1:
                    self.status['fps'] = round(fps_n / (now - fps_t), 1); fps_t, fps_n = now, 0
                self.status.update(faces=len(results), people=sorted({r[1] for r in known}),
                                   unknown_for=round(unknown_for, 1))
                ok, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok:
                    self._publish(buf.tobytes())
        finally:
            cap.release()
            self.alive = False
            self.status['running'] = False
            if _workers.get(self.admin_id) is self:
                _workers.pop(self.admin_id, None)

    def _raise_alert(self, frame, admin_folder):
        dt = datetime.now()
        fname = f"Alert_{dt.strftime('%Y%m%d_%H%M%S')}.jpg"
        os.makedirs(admin_folder, exist_ok=True)
        abs_path = os.path.join(admin_folder, fname)
        cv2.imwrite(abs_path, frame)
        query('INSERT INTO unknown_alerts (admin_id, image_path) VALUES (%s,%s)',
              (self.admin_id, f'admin_{self.admin_id}/{fname}'), commit=True)
        log_event(self.admin_id, 'Unknown', 'Alert', 'Unknown visitor photo captured')
        row = query('SELECT email FROM admins WHERE admin_id=%s', (self.admin_id,), one=True)
        if row and row['email']:
            send_alert_email(abs_path, dt.strftime('%b %d, %Y %H:%M:%S'), row['email'])
        self.status['last_alert'] = dt.strftime('%H:%M:%S')

    @staticmethod
    def _draw(frame, results, unknown_for):
        """Viewfinder-style corner brackets + label chip."""
        for (x, y, w, h), name, conf in results:
            col = (140, 224, 93) if name else (110, 125, 255)         # BGR: green / red
            L = max(14, w // 5)
            for (px, py, dx, dy) in ((x, y, 1, 1), (x + w, y, -1, 1), (x, y + h, 1, -1), (x + w, y + h, -1, -1)):
                cv2.line(frame, (px, py), (px + dx * L, py), col, 3)
                cv2.line(frame, (px, py), (px, py + dy * L), col, 3)
            label = f'{name}  {int(conf * 100)}%' if name else f'Unknown  {int(unknown_for)}s'
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
            cv2.rectangle(frame, (x, y + h + 6), (x + tw + 14, y + h + th + 18), col, cv2.FILLED)
            cv2.putText(frame, label, (x + 7, y + h + th + 11), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (10, 10, 10), 1, cv2.LINE_AA)
        stamp = datetime.now().strftime('%d %b %Y  %H:%M:%S')
        cv2.putText(frame, stamp, (12, frame.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (235, 235, 235), 1, cv2.LINE_AA)

    @staticmethod
    def _message_frame(text):
        img = np.full((360, 640, 3), 18, np.uint8)
        cv2.putText(img, text, (150, 185), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 1, cv2.LINE_AA)
        return cv2.imencode('.jpg', img)[1].tobytes()

    def _publish(self, jpeg):
        with self.cond:
            self.jpeg, self.seq = jpeg, self.seq + 1
            self.cond.notify_all()


_workers, _workers_lock = {}, threading.Lock()


def get_worker(admin_id):
    with _workers_lock:
        w = _workers.get(admin_id)
        if not w or not w.alive:
            w = CameraWorker(admin_id); _workers[admin_id] = w; w.start()
        return w


def stream(worker):
    worker.acquire()
    last = -1
    try:
        while worker.alive or worker.seq != last:
            with worker.cond:
                worker.cond.wait_for(lambda: worker.seq != last or not worker.alive, timeout=2)
                jpeg, last = worker.jpeg, worker.seq
            if jpeg:
                yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg + b'\r\n'
            if not worker.alive:
                break
    finally:
        worker.release()


# ----------------------------------------------------------------- security helpers
def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if 'admin_id' not in session:
            if request.path.startswith('/api/'):
                return jsonify(error='Unauthorized'), 401
            return redirect(url_for('login'))
        return f(*a, **kw)
    return wrapper


@app.before_request
def csrf_protect():
    if request.method == 'POST':
        token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
        if not token or token != session.get('csrf'):
            if request.path.startswith('/api/'):
                return jsonify(error='Invalid or missing security token. Reload the page.'), 400
            abort(400, 'Your session expired. Go back, reload the page and try again.')


@app.context_processor
def inject_globals():
    session.setdefault('csrf', secrets.token_hex(16))
    ctx = {'csrf_token': session['csrf'], 'year': datetime.now().year, 'new_alerts': 0}
    if 'admin_id' in session:
        ctx['new_alerts'] = count("SELECT COUNT(*) c FROM unknown_alerts WHERE admin_id=%s AND status='New'", (session['admin_id'],))
    return ctx


def safe_name(name):
    return re.sub(r'[^A-Za-z0-9_-]', '', (name or '').strip().replace(' ', '_'))[:60]


def strong_password(p):
    return len(p or '') >= 8 and re.search(r'[A-Za-z]', p) and re.search(r'\d', p)


def new_otp(kind, **extra):
    code = str(random.randint(100000, 999999))
    session[kind] = dict(code=code, ts=time.time(), tries=0, **extra)
    return code


def check_otp(kind, entered):
    o = session.get(kind)
    if not o:
        return False, 'Request a new code first.'
    if time.time() - o['ts'] > OTP_TTL:
        session.pop(kind, None); return False, 'That code has expired. Request a new one.'
    o['tries'] += 1; session.modified = True
    if o['tries'] > 5:
        session.pop(kind, None); return False, 'Too many wrong attempts. Request a new code.'
    if (entered or '').strip() != o['code']:
        return False, 'That code is not correct.'
    return True, ''


# ----------------------------------------------------------------- public pages
@app.route('/')
def index():
    if 'admin_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html', unknown_seconds=int(UNKNOWN_SECONDS))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = query('SELECT * FROM admins WHERE username=%s', (request.form.get('username', '').strip(),), one=True)
        if user and check_password_hash(user['password'], request.form.get('password', '')):
            session.clear()
            session.update(admin_id=user['admin_id'], admin_name=user['full_name'], csrf=secrets.token_hex(16))
            return redirect(url_for('dashboard'))
        return render_template('login.html', error='Wrong username or password.')
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'send_otp':
            f = {k: request.form.get(k, '').strip() for k in
                 ('fullname', 'username', 'email', 'phone', 'gender', 'profession', 'dob')}
            f['password'] = request.form.get('password', '')
            if not strong_password(f['password']):
                return render_template('register.html', error='Use a password with 8+ characters, including a letter and a number.', form=f)
            if query('SELECT 1 FROM admins WHERE email=%s OR username=%s', (f['email'], f['username']), one=True):
                return render_template('register.html', error='That email or username is already registered.', form=f)
            f['password'] = generate_password_hash(f['password'])         # never keep the plain password in the session
            code = new_otp('reg_otp', data=f)
            if not send_otp_email(f['email'], code, 'registration'):
                return render_template('register.html', error='Could not send the email. Check SENDER_EMAIL and SENDER_PASSWORD in the settings at the top of app.py.', form=f)
            return render_template('register.html', show_otp_box=True, email=f['email'])
        if action == 'verify_and_register':
            ok, msg = check_otp('reg_otp', request.form.get('otp'))
            if not ok:
                return render_template('register.html', show_otp_box='reg_otp' in session, email=(session.get('reg_otp') or {}).get('data', {}).get('email'), error=msg)
            d = session['reg_otp']['data']
            try:
                aid = query('''INSERT INTO admins (full_name, username, email, phone, gender, profession, dob, password)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''',
                            (d['fullname'], d['username'], d['email'], d['phone'], d['gender'], d['profession'], d['dob'], d['password']), commit=True)
            except mysql.connector.Error:
                return render_template('register.html', error='That username is already taken.')
            os.makedirs(os.path.join(COLLECTED_DIR, f'admin_{aid}'), exist_ok=True)
            session.pop('reg_otp', None)
            flash('Workspace created. Log in to continue.', 'ok')
            return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'send_reset_otp':
            email = request.form.get('email', '').strip()
            if query('SELECT 1 FROM admins WHERE email=%s', (email,), one=True):
                send_otp_email(email, new_otp('reset_otp', email=email), 'password reset')
            # same answer either way, so nobody can test which emails are registered
            session['reset_pending'] = email
            return render_template('forgot_password.html', step='verify_otp', email=email)
        if action == 'update_password':
            email = session.get('reset_pending')
            ok, msg = check_otp('reset_otp', request.form.get('otp'))
            if not ok:
                return render_template('forgot_password.html', step='verify_otp', email=email, error=msg)
            pw = request.form.get('new_password', '')
            if not strong_password(pw):
                return render_template('forgot_password.html', step='verify_otp', email=email, error='Use 8+ characters with a letter and a number.')
            query('UPDATE admins SET password=%s WHERE email=%s', (generate_password_hash(pw), session['reset_otp']['email']), commit=True)
            session.pop('reset_otp', None); session.pop('reset_pending', None)
            flash('Password updated. Log in with your new password.', 'ok')
            return redirect(url_for('login'))
    return render_template('forgot_password.html', step='request_email')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/api/check_session')
def check_session():
    return (jsonify(status='authorized'), 200) if 'admin_id' in session else (jsonify(status='unauthorized'), 401)


# ----------------------------------------------------------------- images (own folder only)
@app.route('/CollectedImages/<path:filename>')
@login_required
def serve_collected_images(filename):
    if not filename.startswith(f"admin_{session['admin_id']}/") or not filename.lower().endswith(('.jpg', '.jpeg', '.png')):
        abort(404)
    return send_from_directory(COLLECTED_DIR, filename)


# ----------------------------------------------------------------- dashboard
def dashboard_data(aid):
    d = {}
    d['user_count'] = count('SELECT COUNT(*) c FROM authorized_users WHERE admin_id=%s', (aid,))
    d['unknown_count'] = count("SELECT COUNT(*) c FROM unknown_alerts WHERE admin_id=%s AND status='New'", (aid,))
    d['entries_today'] = count("SELECT COUNT(*) c FROM security_logs WHERE admin_id=%s AND event_type='Authorized Entry' AND DATE(event_time)=CURDATE()", (aid,))
    d['alerts_today'] = count("SELECT COUNT(*) c FROM unknown_alerts WHERE admin_id=%s AND DATE(capture_time)=CURDATE()", (aid,))
    rows = query("""SELECT DATE(event_time) d, event_type t, COUNT(*) c FROM security_logs
                    WHERE admin_id=%s AND event_time >= CURDATE() - INTERVAL 6 DAY AND event_type IN ('Authorized Entry','Alert')
                    GROUP BY d, t""", (aid,))
    days = [(datetime.now().date().fromordinal(datetime.now().date().toordinal() - i)) for i in range(6, -1, -1)]
    lookup = {(str(r['d']), r['t']): r['c'] for r in rows}
    d['series'] = [dict(label=x.strftime('%a'), entries=lookup.get((x.isoformat(), 'Authorized Entry'), 0),
                        alerts=lookup.get((x.isoformat(), 'Alert'), 0)) for x in days]
    d['recent'] = query("""SELECT person_name person, event_time time, event_type type, details
                           FROM security_logs WHERE admin_id=%s ORDER BY event_time DESC LIMIT 8""", (aid,))
    fmt_dates(d['recent'], 'time', '%b %d, %H:%M')
    w = _workers.get(aid)
    d['camera'] = dict(w.status) if w and w.alive else dict(running=False, fps=0, faces=0, people=[], unknown_for=0, last_alert=None, error=None)
    return d


@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', **dashboard_data(session['admin_id']))


@app.route('/api/stats')
@login_required
def api_stats():
    return jsonify(dashboard_data(session['admin_id']))


# ----------------------------------------------------------------- camera
@app.route('/camera')
@login_required
def camera():
    return render_template('camera.html', unknown_seconds=int(UNKNOWN_SECONDS))


@app.route('/api/video_feed')
@login_required
def video_feed():
    return Response(stream(get_worker(session['admin_id'])), mimetype='multipart/x-mixed-replace; boundary=frame',
                    headers={'Cache-Control': 'no-store'})


@app.route('/api/camera_status')
@login_required
def camera_status():
    w = _workers.get(session['admin_id'])
    return jsonify(w.status if w and w.alive else dict(running=False, fps=0, faces=0, people=[], unknown_for=0, last_alert=None, error=None))


# ----------------------------------------------------------------- authorized users
@app.route('/users')
@login_required
def users():
    aid = session['admin_id']
    rows = query('SELECT id, name, role, email, photo_path, created_at added FROM authorized_users WHERE admin_id=%s ORDER BY created_at DESC', (aid,))
    fmt_dates(rows, 'added', '%b %d, %Y')
    samples = count_samples(aid, COLLECTED_DIR)
    for u in rows:
        u['samples'] = samples.get(u['name'], 0)
    return render_template('users.html', users=rows, enroll_frames=ENROLL_FRAMES)


@app.route('/api/upload_frame', methods=['POST'])
@login_required
def upload_frame():
    """Receives one webcam frame during enrolment; only keeps it if a face is visible."""
    data = request.get_json(silent=True) or {}
    name, b64 = safe_name(data.get('name')), data.get('photo_base64', '')
    if not name or ',' not in b64:
        return jsonify(error='Missing name or photo'), 400
    try:
        raw = base64.b64decode(b64.split(',', 1)[1])
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    except Exception:
        return jsonify(error='Bad image'), 400
    faces = cv2.CascadeClassifier(CASCADE_PATH).detectMultiScale(gray, 1.1, 5, minSize=(80, 80))
    if len(faces) != 1:
        return jsonify(status='skipped', reason='no face' if len(faces) == 0 else 'more than one face')
    user_dir = os.path.join(COLLECTED_DIR, f"admin_{session['admin_id']}", name)
    os.makedirs(user_dir, exist_ok=True)
    idx = int(data.get('frame_idx', 0))
    with open(os.path.join(user_dir, f'capture_{idx}.jpg'), 'wb') as f:
        f.write(raw)
    return jsonify(status='saved')


@app.route('/api/reset_enrollment', methods=['POST'])
@login_required
def reset_enrollment():
    """Clears half-finished captures before a new enrolment attempt."""
    name = safe_name((request.get_json(silent=True) or {}).get('name'))
    d = os.path.join(COLLECTED_DIR, f"admin_{session['admin_id']}", name)
    if name and os.path.isdir(d):
        for f in os.listdir(d):
            if f.startswith('capture_') and f.endswith('.jpg'):
                os.remove(os.path.join(d, f))
    return jsonify(status='ok')


@app.route('/api/add_user', methods=['POST'])
@login_required
def add_user():
    aid = session['admin_id']
    name, role, email = request.form.get('name', '').strip(), request.form.get('role'), request.form.get('email', '').strip()
    safe = safe_name(name)
    user_dir = os.path.join(COLLECTED_DIR, f'admin_{aid}', safe)
    images = sorted(os.path.join(user_dir, f) for f in os.listdir(user_dir) if f.endswith('.jpg')) if safe and os.path.isdir(user_dir) else []
    if not name or len(images) < 10:
        flash('Not enough clear face photos were captured. Try again in better light, facing the camera.', 'bad')
        return redirect(url_for('users'))
    if not add_user_embeddings(aid, name, images, COLLECTED_DIR):
        flash('No face could be read from the photos. Try again.', 'bad')
        return redirect(url_for('users'))
    existing = query('SELECT id FROM authorized_users WHERE admin_id=%s AND name=%s', (aid, name), one=True)
    photo = f'CollectedImages/admin_{aid}/{safe}/{os.path.basename(images[0])}'
    if existing:
        query('UPDATE authorized_users SET role=%s, email=%s, photo_path=%s WHERE id=%s', (role, email, photo, existing['id']), commit=True)
    else:
        query('INSERT INTO authorized_users (admin_id, name, role, email, photo_path) VALUES (%s,%s,%s,%s,%s)', (aid, name, role, email, photo), commit=True)
    log_event(aid, name, 'System Update', f'{name} enrolled with {len(images)} photos.')
    flash(f'{name} was added and the recogniser is updated.', 'ok')
    return redirect(url_for('users'))


@app.route('/api/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    aid = session['admin_id']
    u = query('SELECT name FROM authorized_users WHERE id=%s AND admin_id=%s', (user_id, aid), one=True)
    if u:
        query('DELETE FROM authorized_users WHERE id=%s AND admin_id=%s', (user_id, aid), commit=True)
        remove_user_from_embeddings(aid, u['name'], COLLECTED_DIR)
        log_event(aid, u['name'], 'System Update', 'Removed from authorized people.')
        flash(f"{u['name']} was removed.", 'ok')
    return redirect(url_for('users'))


# ----------------------------------------------------------------- alerts
@app.route('/alerts')
@login_required
def alerts():
    rows = query("SELECT id, image_path, capture_time time, status FROM unknown_alerts WHERE admin_id=%s ORDER BY capture_time DESC", (session['admin_id'],))
    fmt_dates(rows, 'time', '%b %d, %Y %H:%M')
    return render_template('alerts.html', alerts=rows)


@app.route('/api/resolve_alert/<int:alert_id>', methods=['POST'])
@login_required
def resolve_alert(alert_id):
    aid = session['admin_id']
    query("UPDATE unknown_alerts SET status='Resolved' WHERE id=%s AND admin_id=%s", (alert_id, aid), commit=True)
    log_event(aid, 'System', 'Admin Action', f'Alert #{alert_id} marked resolved')
    return redirect(url_for('alerts'))


@app.route('/api/resolve_all_alerts', methods=['POST'])
@login_required
def resolve_all_alerts():
    aid = session['admin_id']
    query("UPDATE unknown_alerts SET status='Resolved' WHERE admin_id=%s AND status='New'", (aid,), commit=True)
    log_event(aid, 'System', 'Admin Action', 'All alerts marked resolved')
    return redirect(url_for('alerts'))


@app.route('/api/delete_alert/<int:alert_id>', methods=['POST'])
@login_required
def delete_alert(alert_id):
    aid = session['admin_id']
    a = query('SELECT image_path FROM unknown_alerts WHERE id=%s AND admin_id=%s', (alert_id, aid), one=True)
    if a:
        query('DELETE FROM unknown_alerts WHERE id=%s AND admin_id=%s', (alert_id, aid), commit=True)
        path = os.path.join(COLLECTED_DIR, a['image_path'])
        if path.startswith(COLLECTED_DIR) and os.path.exists(path):
            os.remove(path)
    return redirect(url_for('alerts'))


# ----------------------------------------------------------------- logs
LOG_SQL = "SELECT person_name person, event_time time, event_type type, details FROM security_logs WHERE admin_id=%s ORDER BY event_time DESC"


@app.route('/logs')
@login_required
def logs():
    return render_template('logs.html', logs=fmt_dates(query(LOG_SQL, (session['admin_id'],)), 'time', '%b %d, %Y %H:%M'))


@app.route('/logs/export.csv')
@login_required
def export_logs():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['Person', 'Time', 'Event', 'Details'])
    for r in fmt_dates(query(LOG_SQL, (session['admin_id'],)), 'time', '%Y-%m-%d %H:%M:%S'):
        w.writerow([r['person'], r['time'], r['type'], r['details']])
    return Response(buf.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f"attachment; filename=securehome_logs_{datetime.now():%Y%m%d}.csv"})


@app.route('/api/clear_logs', methods=['POST'])
@login_required
def clear_logs():
    aid = session['admin_id']
    query('DELETE FROM security_logs WHERE admin_id=%s', (aid,), commit=True)
    log_event(aid, 'System', 'Admin Action', 'All security logs cleared')
    return redirect(url_for('logs'))


# ----------------------------------------------------------------- profile
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    aid = session['admin_id']
    if request.method == 'POST':
        if request.form.get('action') == 'password':
            row = query('SELECT password FROM admins WHERE admin_id=%s', (aid,), one=True)
            new = request.form.get('new_password', '')
            if not check_password_hash(row['password'], request.form.get('current_password', '')):
                flash('Your current password is not correct.', 'bad')
            elif not strong_password(new):
                flash('Use 8+ characters with a letter and a number.', 'bad')
            else:
                query('UPDATE admins SET password=%s WHERE admin_id=%s', (generate_password_hash(new), aid), commit=True)
                flash('Password changed.', 'ok')
        else:
            query('UPDATE admins SET full_name=%s, phone=%s, profession=%s WHERE admin_id=%s',
                  (request.form.get('full_name', '').strip(), request.form.get('phone', '').strip(),
                   request.form.get('profession', '').strip(), aid), commit=True)
            session['admin_name'] = request.form.get('full_name', '').strip() or session.get('admin_name')
            flash('Profile saved.', 'ok')
        return redirect(url_for('profile'))
    admin = query('SELECT full_name, username, email, phone, gender, profession, dob, created_at joined FROM admins WHERE admin_id=%s', (aid,), one=True) or {}
    if admin.get('joined'):
        admin['joined'] = admin['joined'].strftime('%b %d, %Y')
    return render_template('profile.html', admin=admin)


if __name__ == '__main__':
    initialize_database()
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':          # open the browser once, not on every reload
        threading.Timer(1.2, lambda: webbrowser.open('http://127.0.0.1:5000/')).start()
    app.run(debug=True, port=5000, threaded=True)

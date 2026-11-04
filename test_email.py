"""Run:  python test_email.py
Sends one test email to yourself using the settings in app.py and prints the exact reason if it fails."""
import ast, os, smtplib
from email.message import EmailMessage

src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.py'), encoding='utf-8').read()
start = src.index('CONFIG = {'); end = src.index('\n}\n', start) + 2
C = ast.literal_eval(src[start + len('CONFIG = '):end])
local = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'local_settings.py')
if os.path.exists(local):
    lsrc = open(local, encoding='utf-8').read()
    ls = lsrc.index('CONFIG = {')
    C.update(ast.literal_eval(lsrc[ls + len('CONFIG = '):lsrc.index('\n}\n', ls) + 2]))
else:
    print('local_settings.py not found: using the placeholder values from app.py')

sender, password = C['SENDER_EMAIL'], C['SENDER_PASSWORD'].replace(' ', '')
print('Sender:', sender, '| password length:', len(password), '(a Gmail app password is exactly 16)')
if len(password) != 16:
    print('WARNING: the password is not 16 characters. Copy it again from Google, all four groups of four.')

msg = EmailMessage()
msg['Subject'], msg['From'], msg['To'] = 'SecureHome test email', sender, sender
msg.set_content('If you can read this, SecureHome email alerts and OTP codes will work.')
try:
    with smtplib.SMTP(C['SMTP_SERVER'], int(C['SMTP_PORT']), timeout=20) as s:
        s.ehlo(); s.starttls(); s.login(sender, password); s.send_message(msg)
    print('SUCCESS: test email sent to', sender)
except smtplib.SMTPAuthenticationError:
    print('FAILED: Gmail rejected the login. The app password is wrong or revoked, or 2-Step Verification is off.')
except Exception as e:
    print('FAILED:', type(e).__name__, e)

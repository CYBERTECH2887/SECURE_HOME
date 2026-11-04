/* SecureHome shared UI: theme, toasts, confirm dialog, password helpers. No external libraries (works offline). */
(function () {
  const root = document.documentElement;
  const csrf = () => (document.querySelector('meta[name="csrf"]') || {}).content || '';
  window.SH = { csrf };

  // theme
  const themeBtns = document.querySelectorAll('[data-theme-toggle]');
  const paint = () => themeBtns.forEach(b => {
    const dark = root.dataset.theme !== 'light';
    b.innerHTML = '<svg class="i"><use href="#i-' + (dark ? 'sun' : 'moon') + '"/></svg>';
    b.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
  });
  themeBtns.forEach(b => b.addEventListener('click', () => {
    root.dataset.theme = root.dataset.theme === 'light' ? 'dark' : 'light';
    try { localStorage.setItem('sh_theme', root.dataset.theme); } catch (e) {}
    paint();
  }));
  paint();

  // toasts
  window.toast = (msg, kind) => {
    let box = document.querySelector('.toasts');
    if (!box) { box = document.createElement('div'); box.className = 'toasts'; box.setAttribute('role', 'status'); document.body.appendChild(box); }
    const t = document.createElement('div'); t.className = 'toast ' + (kind || ''); t.textContent = msg;
    box.appendChild(t); setTimeout(() => t.remove(), 5000);
  };
  document.querySelectorAll('[data-flash]').forEach(el => { window.toast(el.dataset.flash, el.dataset.kind); el.remove(); });

  // confirm dialog for <form data-confirm="..."> and <button data-confirm>
  const modal = document.getElementById('confirmModal');
  if (modal) {
    let pending = null;
    const close = () => { modal.classList.remove('open'); pending = null; };
    document.addEventListener('submit', e => {
      const f = e.target; if (!f.dataset.confirm || f.dataset.ok) return;
      e.preventDefault(); pending = f;
      modal.querySelector('[data-title]').textContent = f.dataset.confirmTitle || 'Are you sure?';
      modal.querySelector('[data-text]').textContent = f.dataset.confirm;
      modal.querySelector('[data-yes]').textContent = f.dataset.confirmYes || 'Confirm';
      modal.classList.add('open'); modal.querySelector('[data-no]').focus();
    });
    modal.querySelector('[data-yes]').addEventListener('click', () => { if (pending) { pending.dataset.ok = '1'; pending.submit(); } });
    modal.querySelector('[data-no]').addEventListener('click', close);
    modal.addEventListener('click', e => { if (e.target === modal) close(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
  }

  // password show/hide + strength
  document.querySelectorAll('[data-pw-toggle]').forEach(b => b.addEventListener('click', () => {
    const inp = document.getElementById(b.dataset.pwToggle); const show = inp.type === 'password';
    inp.type = show ? 'text' : 'password'; b.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
  }));
  document.querySelectorAll('[data-pw-meter]').forEach(inp => {
    const bar = document.querySelector(inp.dataset.pwMeter + ' i'), hint = document.querySelector(inp.dataset.pwMeter + ' + .hint');
    inp.addEventListener('input', () => {
      const v = inp.value; let s = 0;
      if (v.length >= 8) s++; if (/[A-Za-z]/.test(v) && /\d/.test(v)) s++; if (v.length >= 12) s++; if (/[^A-Za-z0-9]/.test(v)) s++;
      bar.style.width = (s * 25) + '%'; bar.style.background = ['var(--bad)', 'var(--bad)', 'var(--warn)', 'var(--ok)', 'var(--ok)'][s];
      if (hint) hint.textContent = v ? ['Too weak', 'Weak: add a number and use 8+ characters', 'Okay', 'Good', 'Strong'][s] : 'Use 8+ characters with a letter and a number.';
    });
  });

  // mobile sidebar
  const side = document.querySelector('.sidebar'), mb = document.querySelector('.menu-btn');
  if (side && mb) {
    mb.addEventListener('click', () => side.classList.toggle('open'));
    document.addEventListener('click', e => { if (side.classList.contains('open') && !side.contains(e.target) && !mb.contains(e.target)) side.classList.remove('open'); });
  }

  // back button after logout
  window.addEventListener('pageshow', e => {
    if (document.querySelector('.sidebar') && (e.persisted || (performance.getEntriesByType('navigation')[0] || {}).type === 'back_forward')) {
      fetch('/api/check_session').then(r => { if (r.status === 401) location.replace('/login'); }).catch(() => {});
    }
  });
})();

# -*- coding: utf-8 -*-
"""
بوت متجر STORE PLAY POINT  (نسخة محسّنة)

التثبيت:   pip install -U pyTelegramBotAPI   (يُفضّل الإصدار 4.14 فما فوق)
التشغيل:   python app.py

مهم: يجب أن يكون البوت أدمن في قنوات الاشتراك الإجباري حتى يكشف المغادرين لحظياً.
كل شيء يُدار من الأمر /admin (أسماء الأزرار، إظهار/إخفاء الأقسام، الأسعار، الدعوات، الصيانة...).

يمكن وضع الإعدادات في متغيرات بيئة (الأفضل) أو تعديل القيم الافتراضية بالأسفل:
STORE_TOKEN, LOGS_BOT_TOKEN (اختياري), ADMIN_ID, PUBLIC_CHANNEL
"""
import functools
import html
import json
import logging
import os
import re
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from urllib.parse import quote

import telebot
from telebot.apihelper import ApiTelegramException
from telebot.types import (BotCommand, InlineKeyboardButton,
                           InlineKeyboardMarkup, LabeledPrice)

# ============================ الإعدادات ============================
STORE_TOKEN = os.getenv('STORE_TOKEN', '')
LOGS_BOT_TOKEN = os.getenv('LOGS_BOT_TOKEN', '')  # اختياري
if ':' not in STORE_TOKEN:
    sys.exit('❌ ضع توكن بوت المتجر في متغير البيئة STORE_TOKEN (وتوكن بوت الطلبات في LOGS_BOT_TOKEN)')
ADMIN_ID = int(os.getenv('ADMIN_ID', '8579922078'))
PUBLIC_CHANNEL = os.getenv('PUBLIC_CHANNEL', '@playpo4')  # اتركه فارغاً لإيقاف الإعلانات
STORE_NAME = 'STORE PLAY POINT'
VERSION = '2026-10-11.20'
INSTANCE_ID = f'{os.getpid()}-{time.time():.0f}'
def _default_db_path():
    # على الاستضافة: إن وُجد مجلد تخزين دائم /data نستعمله تلقائياً حتى لا تُمسح البيانات عند إعادة التشغيل
    if os.access('/data', os.W_OK):
        return '/data/store.db'
    return 'store.db'


DB_PATH = os.getenv('DB_PATH') or _default_db_path()

SERVERS = {  # الرمز: (الاسم, العلم)
    'us': ('امريكي', '🇺🇸'),
    'jp': ('ياباني', '🇯🇵'),
    'uk': ('بريطاني', '🇬🇧'),
    'fr': ('فرنسي', '🇫🇷'),
}
CATS = {  # الأسماء الظاهرة تُعدَّل من لوحة الأدمن (الأقسام والأزرار)
    'accounts': '🛒 حسابات مجانية',
    'codes': '🎁 قسائم الصناديق',
}
PER_PAGE = 6
LINE = '━━━━━━━━━━━━━━'
BACKUP_MINUTES = float(os.getenv('BACKUP_MINUTES', '5'))
RECHECK_MINUTES = float(os.getenv('RECHECK_MINUTES', '60'))  # فحص دوري لمن غادر القنوات
SUB_TTL = 30  # مدة تخزين نتيجة فحص الاشتراك (ثانية)

DEFAULT_TERMS = (
    "1️⃣ مدة تنفيذ الطلبات من ساعة إلى 24 ساعة حسب الضغط.\n"
    "2️⃣ تأكد من صحة بياناتك (البريد/الرابط) قبل الإرسال، فالخطأ في البيانات مسؤوليتك.\n"
    "3️⃣ تُعاد نقاطك كاملة إذا لم نتمكن من تنفيذ الطلب.\n"
    "4️⃣ الحسابات والأكواد الفورية لا تُسترجع بعد تسليمها.\n"
    "5️⃣ يُمنع الاحتيال وإنشاء حسابات وهمية لجمع النقاط، ويُحظر المخالف.\n"
    "6️⃣ بإرسالك أي طلب فأنت توافق على هذه الشروط."
)

MENU_ITEMS = [  # (المعرّف, الاسم الافتراضي, callback) — بنفس ترتيب ظهورها
    ('pp', '🌐 تفعيل نقاط تشغيل', 'pp'),
    ('wk', '✨ تفعيل الجائزة الأسبوعية', 'wk'),
    ('accounts', '🛒 حسابات مجانية', 'cat:accounts:0'),
    ('codes', '🎁 قسائم الصناديق', 'cat:codes:0'),
    ('earn', '💰 اربح نقاط', 'earn'),
    ('daily', '🎁 هدية يومية', 'daily'),
    ('orders', '📋 طلباتي', 'orders'),
    ('mine', '📦 مشترياتي', 'mine'),
    ('acc', '👤 حسابي', 'acc'),
    ('promo', '🎟️ كود هدية', 'promo'),
    ('sup', '🎧 الدعم', 'sup'),
    ('terms', '📜 الشروط', 'terms'),
    ('dev', '❤️ دعم المطور بنجمة ⭐️', 'dev'),
]
MENU_IDS = [i for i, _d, _c in MENU_ITEMS]
MENU_DEFAULT_LABELS = {i: d for i, d, _c in MENU_ITEMS}

DEFAULT_WELCOME = ('✨ متجر {store} ✨\n{line}\n👋 أهلاً {name}\n💎 رصيدك: {points} نقطة\n{line}\n'
                   'اختر خدمتك من الأزرار 👇')

DEFAULT_SETTINGS = {
    'price_امريكي': '3', 'price_ياباني': '3', 'price_بريطاني': '3', 'price_فرنسي': '3',
    'price_weekly_link': '4', 'price_weekly_acc': '2',
    'status_playpoint': 'active', 'status_weekly_acc': 'active', 'status_weekly_link': 'active',
    'maintenance': 'off',
    'daily_bonus': '1', 'ref_reward': '0', 'ref_join_reward': '1', 'ref_daily_limit': '20',
    'force_channels': '[]', 'terms_text': DEFAULT_TERMS,
    'store_name': STORE_NAME, 'welcome_text': DEFAULT_WELCOME,
    'maintenance_text': '🛠️ البوت تحت الصيانة حالياً، سنعود قريباً.',
}
for _i, _d, _c in MENU_ITEMS:
    DEFAULT_SETTINGS['label_' + _i] = _d
    DEFAULT_SETTINGS['show_' + _i] = 'active'

NUMERIC_KEYS = ({k for k in DEFAULT_SETTINGS if k.startswith('price_')} |
                {'daily_bonus', 'ref_reward', 'ref_join_reward', 'ref_daily_limit'})
TOGGLE_KEYS = ({'status_playpoint', 'status_weekly_acc', 'status_weekly_link', 'maintenance'} |
               {'show_' + i for i in MENU_IDS})
SETTING_LABELS = {
    'daily_bonus': '🎁 نقاط الهدية اليومية',
    'ref_join_reward': '🔗 نقاط الدعوة (عند اشتراك المدعو بالقنوات)',
    'ref_daily_limit': '🛡️ أقصى دعوات محتسبة لكل شخص يومياً (0 = بلا حد)',
    'ref_reward': '🛍️ مكافأة الدعوة عند أول طلب (0 = متوقفة)',
}
TEXT_KEYS = {  # المفتاح: (العنوان, أقصى طول)
    'store_name': ('اسم المتجر', 40),
    'welcome_text': ('رسالة الترحيب', 1000),
    'maintenance_text': ('رسالة الصيانة', 500),
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log = logging.getLogger('store')

if ':' not in STORE_TOKEN:
    sys.exit('❌ ضع توكن بوت المتجر الصحيح في STORE_TOKEN')
USE_LOGS_BOT = ':' in LOGS_BOT_TOKEN and LOGS_BOT_TOKEN != STORE_TOKEN

bot = telebot.TeleBot(STORE_TOKEN, parse_mode='HTML', num_threads=8)
logs_bot = telebot.TeleBot(LOGS_BOT_TOKEN, parse_mode='HTML', num_threads=2) if USE_LOGS_BOT else None
notifier = logs_bot or bot  # البوت الذي تصل عليه طلبات الإدارة
BOT_USERNAME = ''
BOT_ID = 0

h = html.escape
EMAIL_RE = re.compile(r'^[\w.+\-]+@[\w\-]+(\.[\w\-]+)+$')
URL_RE = re.compile(r'^https?://\S+$', re.I)


def _safe(fn):
    """يمنع أي خطأ داخل المعالج من إيقاف البوت، ويُبلغ المستخدم برسالة بدل الصمت."""
    @functools.wraps(fn)
    def wrapper(*a, **k):
        try:
            return fn(*a, **k)
        except Exception as e:
            log.exception('handler %s failed', fn.__name__)
            try:
                chat = getattr(a[0], 'chat', None)
                if chat is not None and chat.type == 'private':
                    note = f'\n<code>{h(repr(e))[:300]}</code>' if chat.id == ADMIN_ID else ''
                    bot.send_message(chat.id, '⚠️ حدث خطأ مؤقت، حاول مرة أخرى بعد قليل.' + note)
            except Exception:
                pass
    return wrapper


# ============================ قاعدة البيانات ============================
class DB:
    """اتصال واحد آمن مع الخيوط (قفل + معاملات)."""

    def __init__(self, path):
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA busy_timeout=10000')
        try:  # ملف واحد كامل (WAL يسبب فقدان بيانات على تخزين الهاتف)
            self.conn.execute('PRAGMA journal_mode=DELETE')
        except sqlite3.OperationalError as e:
            logging.warning('تعذر تحويل القاعدة (هل هناك نسخة أخرى من البوت تعمل؟): %s', e)
        self.conn.execute('PRAGMA synchronous=FULL')

    def run(self, sql, params=()):
        with self.lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def one(self, sql, params=()):
        with self.lock:
            return self.conn.execute(sql, params).fetchone()

    def all(self, sql, params=()):
        with self.lock:
            return self.conn.execute(sql, params).fetchall()

    @contextmanager
    def tx(self):
        with self.lock:
            try:
                yield self.conn
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise


db = DB(DB_PATH)

SCHEMA = '''
CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT, name TEXT,
    price INTEGER, content TEXT, stock INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS referrals (user_id INTEGER PRIMARY KEY, invited_by INTEGER, is_valid INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS purchases (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, product_name TEXT,
    content TEXT, date TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS daily_bonus (user_id INTEGER PRIMARY KEY, last_claim REAL);
CREATE TABLE IF NOT EXISTS promo_codes (code TEXT PRIMARY KEY, reward INTEGER, max_uses INTEGER,
    current_uses INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS redeemed_codes (user_id INTEGER, code TEXT, PRIMARY KEY(user_id, code));
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT,
    service TEXT, kind TEXT, cost INTEGER DEFAULT 0, currency TEXT DEFAULT 'points', charge_id TEXT,
    details TEXT DEFAULT '', status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
'''

def ensure_column(table, column, ddl):
    cols = [r['name'] for r in db.all(f'PRAGMA table_info({table})')]
    if column not in cols:
        db.run(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}')


def init_db():
    with db.lock:
        db.conn.executescript(SCHEMA)
    ensure_column('products', 'stock', 'INTEGER DEFAULT 1')
    ensure_column('users', 'username', 'TEXT')
    ensure_column('users', 'banned', 'INTEGER DEFAULT 0')
    ensure_column('users', 'joined_at', 'REAL')
    ensure_column('users', 'terms_ok', 'INTEGER DEFAULT 0')
    ensure_column('referrals', 'rewarded', 'INTEGER DEFAULT 0')
    ensure_column('referrals', 'join_rewarded', 'INTEGER DEFAULT 0')
    ensure_column('referrals', 'blocked', 'INTEGER DEFAULT 0')   # دعوة ملغاة نهائياً (وهمية)
    ensure_column('referrals', 'join_amount', 'INTEGER')          # النقاط الممنوحة فعلياً
    ensure_column('referrals', 'join_at', 'REAL')
    for k, v in DEFAULT_SETTINGS.items():
        db.run('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (k, v))
    db.run('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', ('db_id', os.urandom(3).hex()))
    db.run('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', ('db_first_seen', str(time.time())))
    set_setting('active_instance', INSTANCE_ID)
    if not db.one("SELECT 1 FROM settings WHERE key='migr_v2'"):  # ترحيل لمرة واحدة من النسخة القديمة
        db.run("DELETE FROM products WHERE category IN ('paid','paid_link')")  # حذف قسم الخدمات المدفوعة
        set_setting('daily_bonus', 1)
        set_setting('ref_reward', 0)
        db.run('UPDATE referrals SET join_amount=? WHERE join_rewarded=1 AND join_amount IS NULL',
               (int_setting('ref_join_reward'),))
        set_setting('migr_v2', '1')
    if not db.one("SELECT 1 FROM settings WHERE key='migr_v3'"):
        if get_setting('store_name') in ('ROBO POINT', ''):
            set_setting('store_name', STORE_NAME)
        set_setting('migr_v3', '1')


def get_setting(key):
    r = db.one('SELECT value FROM settings WHERE key=?', (key,))
    if r and r['value'] is not None and str(r['value']).strip() != '':
        return r['value']
    return DEFAULT_SETTINGS.get(key, '')


def int_setting(key):
    try:
        return int(get_setting(key))
    except ValueError:
        return int(DEFAULT_SETTINGS.get(key, 0))


def set_setting(key, value):
    db.run('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, str(value)))


AR_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')


def parse_int(text, signed=False):
    """يحوّل نصاً إلى رقم صحيح (يدعم الأرقام العربية). يرجع None إذا كان غير صالح."""
    t = (text or '').strip().translate(AR_DIGITS)
    return int(t) if re.fullmatch(r'-?[0-9]{1,9}' if signed else r'[0-9]{1,9}', t) else None


def store_name():
    return get_setting('store_name') or STORE_NAME


def label(item_id):
    return get_setting('label_' + item_id) or MENU_DEFAULT_LABELS.get(item_id, item_id)


def section_on(item_id):
    return get_setting('show_' + item_id) != 'off'


def fmt_price(p):
    return 'مجاني' if not p else f'{p} نقطة'


def get_points(uid):
    r = db.one('SELECT points FROM users WHERE user_id=?', (uid,))
    return r['points'] if r else 0


def is_banned(uid):
    r = db.one('SELECT banned FROM users WHERE user_id=?', (uid,))
    return bool(r and r['banned'])


def ensure_user(user):
    """يسجل المستخدم ويرجع True إذا كان جديداً."""
    with db.tx() as c:
        exists = c.execute('SELECT 1 FROM users WHERE user_id=?', (user.id,)).fetchone()
        if exists:
            c.execute('UPDATE users SET username=? WHERE user_id=?', (user.username, user.id))
            return False
        c.execute('INSERT INTO users (user_id, points, username, joined_at) VALUES (?,?,?,?)',
                  (user.id, 10000 if user.id == ADMIN_ID else 0, user.username, time.time()))
        return True


# ============================ أدوات الواجهة ============================
def btn(text, data):
    return InlineKeyboardButton(text, callback_data=data)


def url_btn(text, url):
    return InlineKeyboardButton(text, url=url)


def kb(*rows):
    m = InlineKeyboardMarkup()
    for row in rows:
        m.row(*row)
    return m


BTN_BACK = btn('🏠 الرئيسية', 'home')
CANCEL_KB = kb([btn('❌ إلغاء', 'home')])
ADMIN_CANCEL_KB = kb([btn('❌ إلغاء', 'a_home')])


def answer(call, text=None, alert=False):
    """يرد على الضغطة مرة واحدة فقط."""
    if getattr(call, '_answered', False):
        return
    call._answered = True
    try:
        bot.answer_callback_query(call.id, text[:200] if text else text, show_alert=alert)
    except Exception as e:
        log.debug('answer failed: %s', e)


def edit(call, text, markup=None):
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    except ApiTelegramException as e:
        if 'message is not modified' in str(e):
            return
        bot.send_message(call.message.chat.id, text, reply_markup=markup)


def ask(cid, text, markup=None):
    return bot.send_message(cid, text, reply_markup=markup or CANCEL_KB)


def delete_msg(m):
    try:
        bot.delete_message(m.chat.id, m.message_id)
    except Exception:
        pass


def clean_email(text):
    t = (text or '').strip()
    return t if len(t) <= 100 and EMAIL_RE.match(t) else None


def clean_url(text):
    t = (text or '').strip()
    return t if len(t) <= 500 and URL_RE.match(t) else None


# ============================ حالة المحادثة ============================
STATE = {}
STATE_LOCK = threading.Lock()
STEPS = {}


def step(name):
    def deco(fn):
        STEPS[name] = fn
        return fn
    return deco


def set_state(uid, step_name, ttl=1800, sticky=False, **data):
    with STATE_LOCK:
        if len(STATE) > 5000:
            now = time.time()
            for k in [k for k, v in STATE.items() if v['exp'] < now]:
                STATE.pop(k, None)
        STATE[uid] = {'step': step_name, 'data': data, 'ttl': ttl, 'sticky': sticky,
                      'exp': time.time() + ttl}


def next_step(uid, step_name, **data):
    with STATE_LOCK:
        st = STATE.get(uid)
        if st:
            st['step'] = step_name
            st['data'].update(data)
            st['exp'] = time.time() + st['ttl']


def get_state(uid):
    with STATE_LOCK:
        st = STATE.get(uid)
        if st and st['exp'] < time.time():
            STATE.pop(uid, None)
            return None
        return st


def clear_state(uid, force=False):
    with STATE_LOCK:
        st = STATE.get(uid)
        if st and (force or not st['sticky']):
            STATE.pop(uid, None)


# ============================ الطلبات ============================
STATUS_TXT = {'pending': '⏳ بانتظار المعالجة', 'done': '✅ <b>[تم بنجاح]</b>',
              'refunded': '❌ <b>[أُلغي وتم إرجاع المبلغ للعميل]</b>'}


def get_order(oid):
    return db.one('SELECT * FROM orders WHERE id=?', (oid,))


def order_text(o):
    cur = 'نقطة' if o['currency'] == 'points' else 'نجمة ⭐️'
    who = f"@{h(o['username'])}" if o['username'] else 'بدون يوزر'
    text = (f"📦 <b>طلب #{o['id']}</b>\n\n"
            f"🛍️ الخدمة: {h(o['service'])}\n"
            f"👤 العميل: {who} — <a href=\"tg://user?id={o['user_id']}\">فتح المحادثة</a>\n"
            f"🆔 الآيدي: <code>{o['user_id']}</code>\n"
            f"💰 التكلفة: {o['cost']} {cur}")
    if o['details']:
        text += '\n' + o['details']
    return text


def order_buttons(oid):
    t = get_setting('db_id') or ''
    return kb([btn('✅ تم بنجاح', f'od:{oid}:{t}'), btn('❌ إلغاء وإرجاع', f'or:{oid}:{t}')])


def notify(text, markup=None):
    """يرسل للأدمن عبر بوت الطلبات، وإن فشل عبر بوت المتجر."""
    for b in dict.fromkeys([notifier, bot]):
        try:
            return b.send_message(ADMIN_ID, text, reply_markup=markup)
        except Exception as e:
            log.error('notify failed: %s', e)
    return None


def place_order(user, kind, service, cost, details, secret='', currency='points',
                charge_id=None, deduct=True):
    """ينشئ الطلب ويخصم النقاط بشكل ذري. يرجع رقم الطلب أو None إذا الرصيد لا يكفي."""
    with db.tx() as c:
        if deduct and cost > 0:
            cur = c.execute('UPDATE users SET points=points-? WHERE user_id=? AND points>=?',
                            (cost, user.id, cost))
            if cur.rowcount == 0:
                return None
        oid = c.execute(
            'INSERT INTO orders (user_id, username, service, kind, cost, currency, charge_id, details) '
            'VALUES (?,?,?,?,?,?,?,?)',
            (user.id, user.username, service, kind, cost, currency, charge_id, details)).lastrowid
    o = get_order(oid)
    text = order_text(o) + (('\n' + secret) if secret else '') + '\n\n' + STATUS_TXT['pending']
    notify(text, order_buttons(oid))
    announce(o)
    return oid


def settle(oid, status):
    """يغلق الطلب مرة واحدة فقط (يمنع الإرجاع المزدوج)."""
    with db.tx() as c:
        o = c.execute('SELECT * FROM orders WHERE id=?', (oid,)).fetchone()
        if not o or o['status'] != 'pending':
            return None
        c.execute('UPDATE orders SET status=? WHERE id=?', (status, oid))
        if status == 'refunded' and o['currency'] == 'points':
            c.execute('UPDATE users SET points=points+? WHERE user_id=?', (o['cost'], o['user_id']))
        return o


def reward_referrer(uid):
    """مكافأة اختيارية للداعي عند أول طلب منفذ للمدعو (متوقفة افتراضياً = 0)."""
    amount = int_setting('ref_reward')
    if amount <= 0:
        return None
    with db.tx() as c:
        r = c.execute('SELECT r.invited_by FROM referrals r JOIN users u ON u.user_id=r.invited_by '
                      'WHERE r.user_id=? AND r.rewarded=0 AND r.blocked=0 AND r.join_rewarded=1 AND u.banned=0',
                      (uid,)).fetchone()
        if not r:
            return None
        c.execute('UPDATE referrals SET rewarded=1, is_valid=1 WHERE user_id=?', (uid,))
        c.execute('UPDATE users SET points=points+? WHERE user_id=?', (amount, r['invited_by']))
        return r['invited_by'], amount


def mask_user(o):
    if o['username']:
        return f"@{h(o['username'][:3])}***"
    return f"مستخدم #{str(o['user_id'])[-4:]}"


def buyer_tag(o):
    if o['username']:
        return f"@{h(o['username'])}"
    return f"مستخدم #{str(o['user_id'])[-4:]}"


def announce(o):
    """رسالة القناة العامة عند اكتمال أي طلب (بدون أي بيانات حساسة)."""
    if not PUBLIC_CHANNEL or not o:
        return
    L = '━━━━━━━━━━━━━━━━━━'
    try:
        bot.send_message(PUBLIC_CHANNEL,
                         f"🎉 <b>تم تنفيذ الطلب بنجاح!</b> ✅\n\n{L}\n"
                         f"💎 <b>{h(store_name())}</b>\n{L}\n\n"
                         f"🛍️ الخدمة: {h(o['service'])}\n"
                         f"👤 العميل: {buyer_tag(o)}\n"
                         f"🧾 رقم الطلب: #{o['id']}\n"
                         f"🟢 حالة الطلب: مكتمل بنجاح\n\n{L}\n\n"
                         f"🚀 تم تنفيذ طلبك بنجاح، شكرًا لثقتك بنا!\n\n"
                         f"⭐ <b>{h(store_name())}</b>\n"
                         f"💎 الجودة • السرعة • المصداقية\n\n"
                         f"❤️ نسعد بخدمتكم دائمًا!")
    except Exception as e:
        log.warning('announce failed: %s', e)


def order_received(cid, oid, extra=''):
    if oid is None:
        bot.send_message(cid, '❌ رصيدك لا يكفي لإتمام الطلب.', reply_markup=kb([BTN_BACK]))
        return
    bot.send_message(cid, f'✅ <b>تم استلام طلبك!</b>\n{LINE}\n🔢 رقم الطلب: <b>#{oid}</b>\n'
                          f'{extra}\n⏳ الحالة: قيد التنفيذ\n🔔 سيصلك إشعار هنا فور الانتهاء.',
                     reply_markup=kb([btn('📋 طلباتي', 'orders')], [BTN_BACK]))


# مستمع أزرار الإدارة (✅/❌) على البوت الذي أرسل الرسالة
def run_selftest(b):
    """فحص ذاتي: يختبر النشر في القناة والإرسال للعميل ويعرض سبب أي فشل بدقة."""
    lines = [f'🧪 <b>فحص البوت</b> (نسخة {VERSION})',
             f'📁 القاعدة: <code>{h(os.path.abspath(DB_PATH))}</code>',
             f'🤖 بوت المتجر: @{h(BOT_USERNAME or "?")} • بوت الطلبات: '
             f'{"منفصل" if logs_bot else "نفس بوت المتجر"}']
    ch = PUBLIC_CHANNEL
    if not ch:
        lines.append('❌ القناة: متغير PUBLIC_CHANNEL فارغ، فالنشر في القناة متوقف. احذف المتغير من الاستضافة أو ضع @playpo4.')
    else:
        lines.append(f'📣 القناة: <code>{h(ch)}</code>')
        try:
            m = bot.get_chat_member(ch, BOT_ID)
            lines.append(f'👮 حالة بوت المتجر في القناة: {h(str(m.status))}')
        except Exception as e:
            lines.append(f'⚠️ تعذّر فحص عضوية البوت في القناة: {h(str(e))[:160]}')
        try:
            t = bot.send_message(ch, '🧪 رسالة اختبار (ستُحذف)')
            lines.append('✅ النشر في القناة يعمل')
            try:
                bot.delete_message(ch, t.message_id)
            except Exception:
                pass
        except Exception as e:
            lines.append(f'❌ فشل النشر في القناة: {h(str(e))[:200]}\n'
                         'الحل: اجعل <b>بوت المتجر</b> أدمن في القناة بصلاحية نشر الرسائل.')
    try:
        bot.send_message(ADMIN_ID, '🧪 اختبار: هكذا تصل رسالة اكتمال الطلب للعميل ✅')
        lines.append('✅ بوت المتجر يستطيع مراسلة المستخدمين')
    except Exception as e:
        lines.append(f'❌ بوت المتجر لا يستطيع مراسلتك: {h(str(e))[:200]}\n'
                     'الحل: افتح بوت المتجر نفسه واضغط Start (إشعار العميل يُرسل من بوت المتجر وليس من بوت الطلبات).')
    b.send_message(ADMIN_ID, '\n'.join(lines))


def register_order_handlers(b):
    @b.message_handler(commands=['test'])
    def on_selftest(m):
        if m.from_user.id == ADMIN_ID and m.chat.type == 'private':
            try:
                run_selftest(b)
            except Exception as e:
                log.exception('selftest failed')
                b.send_message(ADMIN_ID, f'❌ فشل الفحص: {h(str(e))[:200]}')

    @b.callback_query_handler(func=lambda c: bool(c.data) and c.data.split(':')[0] in ('od', 'or'))
    def on_order_action(call):
        try:
            if call.from_user.id != ADMIN_ID:
                return b.answer_callback_query(call.id, 'غير مصرح', show_alert=True)
            parts = call.data.split(':')
            act, oid = parts[0], int(parts[1])
            if len(parts) > 2 and parts[2] and parts[2] != (get_setting('db_id') or ''):
                return b.answer_callback_query(
                    call.id, '⚠️ هذا الطلب تابع لنسخة أخرى من البوت (قاعدة بيانات مختلفة). '
                             'أغلق أي نسخة أخرى تعمل بنفس التوكن (الهاتف أو استضافة قديمة).',
                    show_alert=True)
            o = get_order(oid)
            if not o or o['status'] != 'pending':
                return b.answer_callback_query(call.id, 'تمت معالجة هذا الطلب مسبقاً', show_alert=True)
            if act == 'or' and o['currency'] == 'stars':
                try:
                    bot.refund_star_payment(o['user_id'], o['charge_id'])
                except Exception as e:
                    log.warning('star refund failed: %s', e)
                    return b.answer_callback_query(
                        call.id, '⚠️ تعذّر استرداد النجوم تلقائياً (حدّث المكتبة أو استرد يدوياً).',
                        show_alert=True)
            status = 'done' if act == 'od' else 'refunded'
            if not settle(oid, status):
                return b.answer_callback_query(call.id, 'تمت معالجة هذا الطلب مسبقاً', show_alert=True)
            fresh = get_order(oid)
            # 1) إشعار العميل أولاً (حتى لا يمنعه أي خطأ في تعديل رسالة الأدمن)
            sent = False
            try:
                if status == 'done':
                    bot.send_message(o['user_id'],
                                     f"✅ <b>تم تنفيذ طلبك بنجاح!</b>\n\n🛍️ الخدمة: {h(o['service'])}\n"
                                     f"🧾 رقم الطلب: #{oid}\n\nشكراً لثقتك بنا 🌟")
                elif o['currency'] == 'points':
                    bot.send_message(o['user_id'], f"❌ عذراً، لم نتمكن من إتمام طلبك #{oid} "
                                                   f"وتم <b>إرجاع {o['cost']} نقطة</b> إلى رصيدك.")
                else:
                    bot.send_message(o['user_id'], f'❌ عذراً، لم نتمكن من إتمام طلبك #{oid} '
                                                   f'وتم استرداد نجومك.')
                sent = True
            except Exception as e:
                log.warning('notify customer failed: %s', e)
            # 2) تعديل رسالة الأدمن (لا يوقف باقي الخطوات إن فشل)
            note = '' if sent else '\n⚠️ تعذّر إرسال إشعار للعميل (ربما لم يبدأ البوت أو حظره).'
            try:
                b.edit_message_text(order_text(fresh) + '\n\n' + STATUS_TXT[status] + note,
                                    call.message.chat.id, call.message.message_id,
                                    reply_markup=InlineKeyboardMarkup())
            except Exception as e:
                log.warning('edit order message failed: %s', e)
                try:
                    b.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                                reply_markup=InlineKeyboardMarkup())
                except Exception:
                    pass
            try:
                b.answer_callback_query(call.id, 'تم ✅ وأُرسل إشعار للعميل' if sent else 'تم ✅ لكن تعذّر إشعار العميل',
                                        show_alert=not sent)
            except Exception:
                pass
            if status == 'done':
                rr = reward_referrer(o['user_id'])
                if rr:
                    try:
                        bot.send_message(rr[0], f'🎉 أكمل أحد المدعوين أول طلب! حصلت على <b>{rr[1]}</b> نقاط.')
                    except Exception:
                        pass
        except Exception as e:
            log.exception('order action failed')
            try:
                b.answer_callback_query(call.id, f'❌ خطأ: {str(e)[:150]}', show_alert=True)
            except Exception:
                pass


for _b in dict.fromkeys([notifier, bot]):
    register_order_handlers(_b)


# ============================ القائمة الرئيسية ============================
def render_welcome(uid, name):
    """رسالة الترحيب (قابلة للتعديل من الأدمن) مع استبدال آمن للمتغيرات."""
    vals = {'store': f'<b>{h(store_name())}</b>', 'name': f'<b>{h(name)}</b>',
            'points': f'<b>{get_points(uid)}</b>', 'line': LINE}
    return re.sub(r'\{(store|name|points|line)\}', lambda mo: vals[mo.group(1)], h(get_setting('welcome_text')))


def show_menu(uid, call=None, name=None):
    try:
        text = render_welcome(uid, name or 'عزيزي العميل')
    except Exception:
        log.exception('render_welcome failed')
        text = ''
    if not re.sub(r'<[^>]+>|\s|[\u200b-\u200f\u2060\ufeff]', '', text):  # لا شيء مرئي
        log.error('welcome text empty: %r', get_setting('welcome_text'))
        text = f'✨ <b>{h(store_name())}</b> ✨\n{LINE}\nاختر خدمتك من الأزرار 👇'
    btns = [btn(label(i), cb) for i, _d, cb in MENU_ITEMS if i != 'dev' and section_on(i)]
    rows = [btns[k:k + 2] for k in range(0, len(btns), 2)]
    if section_on('dev'):
        rows.append([btn(label('dev'), 'dev')])
    if uid == ADMIN_ID:
        rows.append([btn('👑 لوحة الأدمن', 'a_home')])
    markup = kb(*rows) if rows else None
    try:
        if call:
            edit(call, text, markup)
        else:
            bot.send_message(uid, text, reply_markup=markup)
    except Exception as e:  # آخر خط دفاع: تظهر القائمة بنص بسيط مهما كان السبب
        log.exception('show_menu failed: %r', text[:300])
        alert_admin_once('menu_fail', f'⚠️ فشل عرض القائمة: {h(str(e))[:200]}\n'
                                      f'النص: <code>{h(repr(text))[:300]}</code>', every=600)
        bot.send_message(uid, 'القائمة الرئيسية 👇', reply_markup=markup)


# ============================ الاشتراك الإجباري والشروط ============================
SUB_CACHE = {}
GATE_EXEMPT = {'chk', 'tok'}
ALERTS = {}
LEAVE_MSG = {}


def alert_admin_once(key, text, every=3600):
    now = time.time()
    if now - ALERTS.get(key, 0) < every:
        return
    ALERTS[key] = now
    notify(text)


def get_channels():
    try:
        return json.loads(get_setting('force_channels') or '[]')
    except ValueError:
        return []


def forget_member(uid):
    for k in list(SUB_CACHE):
        if k[0] == uid:
            SUB_CACHE.pop(k, None)


def is_member(uid, chat):
    key = (uid, str(chat))
    now = time.time()
    if SUB_CACHE.get(key, 0) > now:
        return True
    try:
        mem = bot.get_chat_member(chat, uid)
        ok = mem.status in ('member', 'administrator', 'creator') or (
            mem.status == 'restricted' and getattr(mem, 'is_member', False))
    except Exception as e:
        log.warning('تعذر فحص الاشتراك في %s: %s', chat, type(e).__name__)
        if not isinstance(e, ApiTelegramException):
            return True  # انقطاع اتصال مؤقت بتيليغرام: لا نزعج الأدمن ولا نكشف التوكن في الرسائل
        alert_admin_once(f'chk:{chat}', f'⚠️ تعذر فحص الاشتراك في القناة <code>{h(str(chat))}</code>.\n'
                                        f'تأكد أن البوت <b>أدمن</b> فيها.\nالخطأ: {h(str(e))[:150]}')
        return True  # لا نحجب العملاء إذا تعذر الفحص (البوت ليس أدمن / خطأ مؤقت)
    if ok:
        if len(SUB_CACHE) > 20000:
            for k, v in list(SUB_CACHE.items()):
                if v < now:
                    SUB_CACHE.pop(k, None)
        SUB_CACHE[key] = now + SUB_TTL
    return ok


def missing_channels(uid):
    return [c for c in get_channels() if not is_member(uid, c['chat'])]


def terms_ok(uid):
    r = db.one('SELECT terms_ok FROM users WHERE user_id=?', (uid,))
    return bool(r and r['terms_ok'])


def show_screen(cid, call, text, markup):
    if call:
        edit(call, text, markup)
    else:
        bot.send_message(cid, text, reply_markup=markup)


def show_terms(cid, call=None, first=False):
    text = f"📜 <b>شروط الاستخدام</b>\n{LINE}\n{h(get_setting('terms_text'))}"
    markup = kb([btn('✅ أوافق وأبدأ', 'tok')]) if first else kb([BTN_BACK])
    show_screen(cid, call, text, markup)


LEAVE_WARN = '⚠️ <b>تنبيه:</b> لا تغادر القنوات بعد الاشتراك، فمغادرتها توقف استخدام البوت حتى تعيد الاشتراك.'


def sub_screen(cid, call, missing, left=False):
    rows = [[url_btn(f"📢 {c['title']}", c['link'])] for c in missing]
    rows.append([btn('✅ تحققت من اشتراكي', 'chk')])
    head = ('⚠️ <b>غادرت قناة الاشتراك الإجباري!</b>\n' if left else '') + \
           f'🔒 <b>الاشتراك الإجباري</b>\n{LINE}\n'
    show_screen(cid, call, head +
                           f'يجب الاشتراك في القنوات التالية لتتمكن من استخدام البوت 👇\n'
                           f'بعد الاشتراك اضغط «تحققت» للمتابعة 🎁\n\n{LEAVE_WARN}', kb(*rows))


def grant_join_reward(uid):
    """نقاط لصاحب رابط الدعوة عندما يكمل المدعو (الاشتراك بكل القنوات + الموافقة على الشروط).
    آمن ضد التكرار، ويحترم الحد اليومي وحظر الدعوات الملغاة."""
    amount = int_setting('ref_join_reward')
    if amount <= 0 or not get_channels():
        return
    with db.tx() as c:
        r = c.execute('SELECT invited_by, join_at FROM referrals WHERE user_id=? AND join_rewarded=0 AND blocked=0',
                      (uid,)).fetchone()
        if not r:
            return
        inviter, first = r['invited_by'], r['join_at'] is None
        inv = c.execute('SELECT banned FROM users WHERE user_id=?', (inviter,)).fetchone()
        if not inv or inv['banned'] or inviter == uid:
            return
        limit = int_setting('ref_daily_limit')
        if limit > 0:
            n = c.execute('SELECT COUNT(*) FROM referrals WHERE invited_by=? AND join_rewarded=1 AND join_at>?',
                          (inviter, time.time() - 86400)).fetchone()[0]
            if n >= limit:
                return
        c.execute('UPDATE referrals SET join_rewarded=1, join_amount=?, join_at=? WHERE user_id=?',
                  (amount, time.time(), uid))
        c.execute('UPDATE users SET points=points+? WHERE user_id=?', (amount, inviter))
    if first:
        try:
            bot.send_message(inviter, f'🎉 انضم شخص عبر رابطك واشترك في القنوات!\n'
                                      f'💎 حصلت على <b>+{amount}</b> نقطة.')
        except Exception:
            pass


def revoke_join_reward(uid, block=False, notify_inviter=True):
    """يسحب نقطة الدعوة من الداعي (إن كانت ممنوحة). block=True يلغي الدعوة نهائياً. يرجع النقاط المسحوبة."""
    with db.tx() as c:
        r = c.execute('SELECT invited_by, join_rewarded, join_amount FROM referrals WHERE user_id=?',
                      (uid,)).fetchone()
        if not r:
            return 0
        amt = 0
        if r['join_rewarded']:
            amt = r['join_amount'] if r['join_amount'] is not None else int_setting('ref_join_reward')
            c.execute('UPDATE referrals SET join_rewarded=0 WHERE user_id=?', (uid,))
            if amt > 0:
                c.execute('UPDATE users SET points=MAX(points-?,0) WHERE user_id=?', (amt, r['invited_by']))
        if block:
            c.execute('UPDATE referrals SET blocked=1 WHERE user_id=?', (uid,))
        inviter = r['invited_by']
    if amt > 0 and notify_inviter:
        try:
            bot.send_message(inviter, f'⚠️ أحد المدعوين غادر قنوات الاشتراك الإجباري، '
                                      f'فتم خصم <b>{amt}</b> نقطة من رصيدك.')
        except Exception:
            pass
    return amt


def gate(uid, cid, call=None):
    """True = تابع. False = عُرضت شاشة (صيانة / اشتراك إجباري / شروط)."""
    if uid == ADMIN_ID:
        return True
    if get_setting('maintenance') == 'active':
        show_screen(cid, call, h(get_setting('maintenance_text')), kb([btn('🔄 تحديث', 'home')]))
        return False
    channels = get_channels()
    if channels:
        missing = missing_channels(uid)
        if missing:
            sub_screen(cid, call, missing)  # لا خصم من الداعي، فقط رسالة الاشتراك
            return False
    if not terms_ok(uid):
        show_terms(cid, call, first=True)
        return False
    if channels:
        grant_join_reward(uid)
    return True


def channel_of(chat):
    """يرجع قناة الاشتراك الإجباري المطابقة لدردشة معيّنة أو None."""
    for c in get_channels():
        ref = c['chat']
        if c.get('id') == chat.id or ref == chat.id:
            return c
        if isinstance(ref, str) and chat.username and ref.lstrip('@').lower() == chat.username.lower():
            return c
    return None


@bot.chat_member_handler()
def on_chat_member(upd):
    """لحظة مغادرة المستخدم لقناة إجبارية: تصله رسالة الاشتراك من جديد (بدون خصم من الداعي)."""
    try:
        ch = channel_of(upd.chat)
        nm = upd.new_chat_member
        if not ch or nm.user.is_bot or nm.user.id == ADMIN_ID:
            return
        left = nm.status in ('left', 'kicked') or (nm.status == 'restricted' and not getattr(nm, 'is_member', True))
        if not left:
            return
        uid = nm.user.id
        forget_member(uid)
        if not db.one('SELECT 1 FROM users WHERE user_id=?', (uid,)) or is_banned(uid):
            return
        now = time.time()
        if now - LEAVE_MSG.get(uid, 0) < 10:
            return
        LEAVE_MSG[uid] = now
        sub_screen(uid, None, missing_channels(uid) or [ch], left=True)
    except Exception:
        log.exception('chat_member update failed')


def recheck_loop():
    """فحص دوري احتياطي للمدعوين المحتسبين: من غادر القنوات يُطالَب بالاشتراك (بدون خصم من الداعي)."""
    time.sleep(120)
    while True:
        try:
            if get_channels():
                for r in db.all('SELECT user_id FROM referrals WHERE join_rewarded=1'):
                    uid = r['user_id']
                    forget_member(uid)
                    miss = missing_channels(uid)
                    if miss and time.time() - LEAVE_MSG.get(uid, 0) > 12 * 3600:
                        LEAVE_MSG[uid] = time.time()
                        try:
                            sub_screen(uid, None, miss, left=True)
                        except Exception:
                            pass
                    time.sleep(0.05)
        except Exception:
            log.exception('recheck failed')
        time.sleep(max(RECHECK_MINUTES, 5) * 60)


@bot.message_handler(commands=['start', 'menu'])
@_safe
def cmd_start(m):
    if m.chat.type != 'private':
        return
    uid = m.from_user.id
    is_new = ensure_user(m.from_user)
    if is_banned(uid):
        return bot.send_message(uid, '🚫 حسابك محظور من استخدام المتجر.')
    clear_state(uid)
    parts = (m.text or '').split()
    if is_new and len(parts) > 1 and re.fullmatch(r'[0-9]{1,15}', parts[1]):
        ref = int(parts[1])
        if ref != uid and db.one('SELECT 1 FROM users WHERE user_id=? AND banned=0', (ref,)):
            db.run('INSERT OR IGNORE INTO referrals (user_id, invited_by) VALUES (?,?)', (uid, ref))
    if gate(uid, m.chat.id):
        show_menu(uid, name=m.from_user.first_name)


# ============================ موجّه الأزرار ============================
ROUTES = {}


def route(name, admin=False):
    def deco(fn):
        ROUTES[name] = (fn, admin)
        return fn
    return deco


ROUTE_SECTION = {'pp': 'pp', 'sv': 'pp', 'wk': 'wk', 'wl': 'wk', 'wa': 'wk', 'earn': 'earn', 'daily': 'daily',
                 'orders': 'orders', 'mine': 'mine', 'acc': 'acc', 'promo': 'promo', 'sup': 'sup',
                 'terms': 'terms', 'dev': 'dev'}


def section_for(action, args):
    if action in ROUTE_SECTION:
        return ROUTE_SECTION[action]
    if action == 'cat' and args:
        return args[0]
    if action in ('pv', 'by') and args and args[0].isdigit():
        r = db.one('SELECT category FROM products WHERE id=?', (int(args[0]),))
        return r['category'] if r else None
    return None


@bot.callback_query_handler(func=lambda c: True)
def on_callback(call):
    uid = call.from_user.id
    try:
        if call.message.chat.type != 'private':
            return answer(call)
        ensure_user(call.from_user)
        if is_banned(uid):
            return answer(call, '🚫 حسابك محظور.', True)
        action, *args = call.data.split(':')
        entry = ROUTES.get(action)
        if not entry:
            return answer(call)
        if action not in GATE_EXEMPT and not gate(uid, call.message.chat.id, call):
            return answer(call)
        fn, admin_only = entry
        if uid != ADMIN_ID:
            sec = section_for(action, args)
            if sec and not section_on(sec):
                return answer(call, '⚠️ هذا القسم غير متاح حالياً.', True)
        if admin_only and uid != ADMIN_ID:
            return answer(call, 'غير مصرح', True)
        fn(call, args)
        answer(call)
    except Exception:
        log.exception('callback error: %s', call.data)
        answer(call, '⚠️ حدث خطأ، حاول مرة أخرى.', True)


@route('home')
def r_home(call, a):
    clear_state(call.from_user.id)
    show_menu(call.from_user.id, call, call.from_user.first_name)


# ---------------- تفعيل PlayPoint ----------------
@route('pp')
def r_pp(call, a):
    if get_setting('status_playpoint') != 'active':
        return answer(call, '❌ خدمة تفعيل نقاط تشغيل متوقفة مؤقتاً من الإدارة.', True)
    btns = [btn(f"{flag} {name} ({int_setting('price_' + name)} نقطة)", f'sv:{code}')
            for code, (name, flag) in SERVERS.items()]
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)] + [[BTN_BACK]]
    edit(call, f'🌍 <b>تفعيل نقاط تشغيل</b>\n{LINE}\nاختر السيرفر المناسب 👇\n\n'
               f'⚠️ لا يتم فتح الجائزة الأسبوعية', kb(*rows))


@route('sv')
def r_sv(call, a):
    uid = call.from_user.id
    if a[0] not in SERVERS or get_setting('status_playpoint') != 'active':
        return answer(call, '❌ الخدمة غير متاحة.', True)
    name = SERVERS[a[0]][0]
    price = int_setting('price_' + name)
    if get_points(uid) < price:
        return answer(call, f'❌ رصيدك لا يكفي! التكلفة {price} نقطة.', True)
    set_state(uid, 'pp_mail', server=a[0], price=price)
    answer(call)
    ask(call.message.chat.id, f'✅ السيرفر المختار: <b>{name}</b> (التكلفة: {price} نقطة)\n\n'
                              f'📧 الخطوة 1: أرسل <b>البريد الإلكتروني (Gmail)</b> فقط:')


@step('pp_mail')
def s_pp_mail(m, d):
    email = clean_email(m.text)
    if not email:
        return ask(m.chat.id, '❌ البريد غير صالح، أعد إرساله بالشكل الصحيح:')
    next_step(m.from_user.id, 'pp_pass', email=email)
    ask(m.chat.id, '🔑 الخطوة 2: أرسل <b>كلمة المرور</b> الخاصة بالحساب:\n'
                   '🔒 سيتم حذف رسالتك تلقائياً من المحادثة.')


@step('pp_pass')
def s_pp_pass(m, d):
    password = (m.text or '').strip()
    delete_msg(m)
    if not password or len(password) > 128:
        return ask(m.chat.id, '❌ كلمة المرور غير صالحة، أعد إرسالها:')
    uid = m.from_user.id
    name = SERVERS[d['server']][0]
    oid = place_order(m.from_user, 'play', f'تحويل الحساب إلى {name}', d['price'],
                      f"📧 البريد: <code>{h(d['email'])}</code>",
                      secret=f'🔑 كلمة المرور: <code>{h(password)}</code>')
    clear_state(uid, force=True)
    order_received(m.chat.id, oid, f'🌍 السيرفر: <b>{name}</b>\n⏳ المدة: من ساعة إلى 24 ساعة.')


# ---------------- الجائزة الأسبوعية ----------------
@route('wk')
def r_wk(call, a):
    rows = []
    if get_setting('status_weekly_link') == 'active':
        rows.append([btn(f"🔗 برابط دفع ({int_setting('price_weekly_link')} نقاط)", 'wl')])
    if get_setting('status_weekly_acc') == 'active':
        rows.append([btn(f"🔑 بالحساب وكلمة السر ({int_setting('price_weekly_acc')} نقاط)", 'wa')])
    if not rows:
        return answer(call, '❌ هذه الخدمة متوقفة حالياً.', True)
    rows.append([BTN_BACK])
    edit(call, f'✨ <b>تفعيل الجائزة الأسبوعية</b>\n{LINE}\nاختر الطريقة المناسبة 👇', kb(*rows))


@route('wl')
def r_wl(call, a):
    uid = call.from_user.id
    if get_setting('status_weekly_link') != 'active':
        return answer(call, '❌ هذه الطريقة متوقفة حالياً.', True)
    price = int_setting('price_weekly_link')
    if get_points(uid) < price:
        return answer(call, f'❌ رصيدك لا يكفي! التكلفة {price} نقاط.', True)
    set_state(uid, 'wl_1', price=price)
    answer(call)
    ask(call.message.chat.id, '⚠️ <b>ملاحظة هامة:</b>\nابحث عن هذين التطبيقين في قوقل بلاي وأرسل رابط دفع لكل منهما:\n'
                              '1️⃣ Upping Floors Stack Blocks\n2️⃣ Neon Valley AMOLED\n\n'
                              '📥 <b>أرسل الآن رابط دفع التطبيق الأول:</b>')


@step('wl_1')
def s_wl_1(m, d):
    link = clean_url(m.text)
    if not link:
        return ask(m.chat.id, '❌ أرسل رابطاً صحيحاً يبدأ بـ https://')
    next_step(m.from_user.id, 'wl_2', link1=link)
    ask(m.chat.id, '📥 ممتاز. الآن أرسل <b>رابط دفع التطبيق الثاني</b> (Neon Valley AMOLED):')


@step('wl_2')
def s_wl_2(m, d):
    link = clean_url(m.text)
    if not link:
        return ask(m.chat.id, '❌ أرسل رابطاً صحيحاً يبدأ بـ https://')
    next_step(m.from_user.id, 'wl_mail', link2=link)
    ask(m.chat.id, '📧 رائع. الآن أرسل <b>البريد الإلكتروني (Gmail فقط بدون كلمة سر)</b>:')


@step('wl_mail')
def s_wl_mail(m, d):
    email = clean_email(m.text)
    if not email:
        return ask(m.chat.id, '❌ البريد غير صالح، أعد إرساله:')
    details = (f"🔗 الرابط الأول: <code>{h(d['link1'])}</code>\n"
               f"🔗 الرابط الثاني: <code>{h(d['link2'])}</code>\n"
               f"📧 البريد: <code>{h(email)}</code>")
    oid = place_order(m.from_user, 'weekly_link', 'تفعيل الجائزة الاسبوعية برابط دفع', d['price'], details)
    clear_state(m.from_user.id, force=True)
    order_received(m.chat.id, oid)


@route('wa')
def r_wa(call, a):
    uid = call.from_user.id
    if get_setting('status_weekly_acc') != 'active':
        return answer(call, '❌ هذه الطريقة متوقفة حالياً.', True)
    price = int_setting('price_weekly_acc')
    if get_points(uid) < price:
        return answer(call, f'❌ رصيدك لا يكفي! التكلفة {price} نقاط.', True)
    set_state(uid, 'wa_mail', price=price)
    answer(call)
    ask(call.message.chat.id, '⚠️ <b>ملاحظة هامة:</b>\nيجب أن يكون حسابك بدون مصادقة ثنائية حتى نستطيع الدخول.\n\n'
                              '📧 أرسل <b>البريد الإلكتروني (Gmail)</b> لحسابك:')


@step('wa_mail')
def s_wa_mail(m, d):
    email = clean_email(m.text)
    if not email:
        return ask(m.chat.id, '❌ البريد غير صالح، أعد إرساله:')
    next_step(m.from_user.id, 'wa_pass', email=email)
    ask(m.chat.id, '🔑 أرسل الآن <b>كلمة المرور</b> الخاصة بالحساب:\n🔒 سيتم حذف رسالتك تلقائياً.')


@step('wa_pass')
def s_wa_pass(m, d):
    password = (m.text or '').strip()
    delete_msg(m)
    if not password or len(password) > 128:
        return ask(m.chat.id, '❌ كلمة المرور غير صالحة، أعد إرسالها:')
    oid = place_order(m.from_user, 'weekly_acc', 'تفعيل الجائزة الاسبوعية عبر الحساب', d['price'],
                      f"📧 البريد: <code>{h(d['email'])}</code>",
                      secret=f'🔑 كلمة المرور: <code>{h(password)}</code>')
    clear_state(m.from_user.id, force=True)
    order_received(m.chat.id, oid)


# ---------------- المنتجات الفورية (حسابات / قسائم) ----------------
@route('cat')
def r_cat(call, a):
    cat, page = a[0], int(a[1])
    if cat not in CATS:
        return
    items = db.all('SELECT MIN(id) AS id, name, price, SUM(stock) AS stock FROM products '
                   'WHERE category=? AND stock>0 GROUP BY name, price ORDER BY 1', (cat,))
    if not items:
        return answer(call, 'القسم فارغ أو نفذت الكمية حالياً.', True)
    pages = (len(items) - 1) // PER_PAGE + 1
    page = max(0, min(page, pages - 1))
    rows = [[btn(f"{i['name']} | {fmt_price(i['price'])} (متوفر: {i['stock']})", f"pv:{i['id']}")]
            for i in items[page * PER_PAGE:(page + 1) * PER_PAGE]]
    nav = []
    if page > 0:
        nav.append(btn('⬅️ السابق', f'cat:{cat}:{page - 1}'))
    if page < pages - 1:
        nav.append(btn('التالي ➡️', f'cat:{cat}:{page + 1}'))
    if nav:
        rows.append(nav)
    rows.append([BTN_BACK])
    edit(call, f'<b>{h(label(cat))}</b>\n{LINE}\nاختر المنتج 👇  (صفحة {page + 1}/{pages})', kb(*rows))


@route('pv')
def r_pv(call, a):
    pid = int(a[0])
    p = db.one('SELECT category, name, price FROM products WHERE id=?', (pid,))
    if not p:
        return answer(call, '❌ هذا المنتج لم يعد متوفراً.', True)
    stock = db.one('SELECT COALESCE(SUM(stock),0) AS s FROM products WHERE category=? AND name=? AND price=?',
                   (p['category'], p['name'], p['price']))['s']
    edit(call, f"🛍️ <b>{h(p['name'])}</b>\n💰 السعر: {fmt_price(p['price'])}\n📦 المتوفر: {stock}\n"
               f"💳 رصيدك: {get_points(call.from_user.id)} نقطة\n\nهل تريد تأكيد الشراء؟",
         kb([btn('✅ تأكيد الشراء', f'by:{pid}')], [btn('⬅️ رجوع', f"cat:{p['category']}:0")]))


def buy_product(user, pid):
    """شراء ذري: يرجع (الحالة, الوحدة, رقم الطلب)."""
    with db.tx() as c:
        ref = c.execute('SELECT category, name, price FROM products WHERE id=?', (pid,)).fetchone()
        if not ref:
            return 'gone', None, None
        unit = c.execute('SELECT * FROM products WHERE category=? AND name=? AND price=? AND stock>0 '
                         'ORDER BY id LIMIT 1', tuple(ref)).fetchone()
        if not unit:
            return 'gone', None, None
        cur = c.execute('UPDATE users SET points=points-? WHERE user_id=? AND points>=?',
                        (unit['price'], user.id, unit['price']))
        if cur.rowcount == 0:
            return 'nofunds', unit, None
        c.execute('UPDATE products SET stock=stock-1 WHERE id=?', (unit['id'],))  # لا نحذف الصف حتى تبقى الأزرار القديمة صالحة
        c.execute('INSERT INTO purchases (user_id, product_name, content) VALUES (?,?,?)',
                  (user.id, unit['name'], unit['content']))
        oid = c.execute("INSERT INTO orders (user_id, username, service, kind, cost, status) "
                        "VALUES (?,?,?,?,?, 'done')",
                        (user.id, user.username, unit['name'], 'product', unit['price'])).lastrowid
        return 'ok', unit, oid


@route('by')
def r_by(call, a):
    status, unit, oid = buy_product(call.from_user, int(a[0]))
    if status == 'ok':
        answer(call, '✅ تم الشراء بنجاح')
        bot.send_message(call.message.chat.id,
                         f"✅ <b>تم الشراء بنجاح!</b>\n🛍️ المنتج: {h(unit['name'])}\n\n"
                         f"<code>{h(unit['content'])}</code>", reply_markup=kb([BTN_BACK]))
        announce(get_order(oid))
    elif status == 'nofunds':
        answer(call, f"❌ رصيدك لا يكفي. السعر {unit['price']} نقطة.", True)
    else:
        answer(call, '❌ عذراً، نفذت كمية هذا المنتج!', True)


SKIP_KB = kb([btn('⏭️ تخطي (سأتواصل مع الدعم)', 'skip')])


@route('skip')
def r_skip(call, a):
    clear_state(call.from_user.id, force=True)
    show_menu(call.from_user.id, call, call.from_user.first_name)


@bot.pre_checkout_query_handler(func=lambda q: True)
def on_pre_checkout(q):
    payload = q.invoice_payload
    ok = payload == 'dev'
    if payload.startswith('ps:'):  # فواتير قديمة فقط (القسم محذوف)
        ok = payload[3:].isdigit() and bool(db.one('SELECT 1 FROM products WHERE id=? AND stock>0',
                                                   (int(payload[3:]),)))
    bot.answer_pre_checkout_query(q.id, ok=ok, error_message=None if ok else 'الخدمة غير متاحة حالياً.')


@bot.message_handler(content_types=['successful_payment'])
@_safe
def on_payment(m):
    sp = m.successful_payment
    payload = sp.invoice_payload
    uid = m.from_user.id
    if payload == 'dev':
        who = f'@{h(m.from_user.username)}' if m.from_user.username else 'بدون يوزر'
        notify(f'❤️ <b>دعم جديد للمطور!</b>\n👤 {who}\n🆔 <code>{uid}</code>\n⭐ {sp.total_amount} نجمة')
        return bot.send_message(uid, '❤️ شكراً جزيلاً لدعمك الغالي! ربي يسعدك 🥰')
    if payload.startswith('ps:'):
        p = db.one('SELECT name FROM products WHERE id=?', (int(payload[3:]),))
        name = p['name'] if p else 'خدمة مدفوعة بالنجوم'
        oid = place_order(m.from_user, 'paid', name, sp.total_amount,
                          '⏳ بانتظار الرابط والبريد من العميل', currency='stars',
                          charge_id=sp.telegram_payment_charge_id, deduct=False)
        set_state(uid, 'ps_link', ttl=7 * 86400, sticky=True, order_id=oid)
        ask(m.chat.id, f'✅ تم الدفع بنجاح! طلبك رقم <b>#{oid}</b>\n\n'
                       f'📥 أرسل الآن <b>رابط الدفع</b> الخاص بالخدمة:', SKIP_KB)


@step('ps_link')
def s_ps_link(m, d):
    link = clean_url(m.text)
    if not link:
        return ask(m.chat.id, '❌ أرسل رابط دفع صحيحاً يبدأ بـ https://', SKIP_KB)
    next_step(m.from_user.id, 'ps_mail', link=link)
    ask(m.chat.id, '📧 الآن أرسل <b>البريد الإلكتروني (Gmail فقط بدون كلمة سر)</b>:', SKIP_KB)


@step('ps_mail')
def s_ps_mail(m, d):
    email = clean_email(m.text)
    if not email:
        return ask(m.chat.id, '❌ البريد غير صالح، أعد إرساله:', SKIP_KB)
    details = f"🔗 رابط الدفع: <code>{h(d['link'])}</code>\n📧 البريد: <code>{h(email)}</code>"
    db.run('UPDATE orders SET details=? WHERE id=?', (details, d['order_id']))
    notify(f"📎 <b>بيانات الطلب #{d['order_id']}:</b>\n{details}")
    clear_state(m.from_user.id, force=True)
    bot.send_message(m.chat.id, f"✅ تم إرسال بياناتك للإدارة (الطلب #{d['order_id']}).\n"
                                f"🔔 سيصلك إشعار فور التنفيذ.", reply_markup=kb([BTN_BACK]))


@route('dev')
def r_dev(call, a):
    answer(call)
    try:
        bot.send_invoice(call.message.chat.id, title='دعم المطور ❤️',
                         description='شكراً لك على دعم استمرار وتطوير البوت بـ 1 نجمة تلجرام!',
                         invoice_payload='dev', provider_token='', currency='XTR',
                         prices=[LabeledPrice('دعم المطور', 1)])
    except Exception as e:
        log.warning('dev invoice failed: %s', e)
        bot.send_message(call.message.chat.id, '❌ تعذر إنشاء الفاتورة حالياً.')


# ---------------- الحساب والنقاط ----------------
@route('acc')
def r_acc(call, a):
    uid = call.from_user.id
    n_buy = db.one('SELECT COUNT(*) AS c FROM purchases WHERE user_id=?', (uid,))['c']
    n_ord = db.one("SELECT COUNT(*) AS c FROM orders WHERE user_id=? AND kind!='product'", (uid,))['c']
    n_ref = db.one('SELECT COUNT(*) AS c FROM referrals WHERE invited_by=?', (uid,))['c']
    edit(call, f'👤 <b>حسابي</b>\n{LINE}\n🆔 الآيدي: <code>{uid}</code>\n'
               f'💎 الرصيد: <b>{get_points(uid)}</b> نقطة\n🛒 المشتريات: {n_buy}\n'
               f'📋 الطلبات: {n_ord}\n👥 المدعوون: {n_ref}', kb([BTN_BACK]))


@route('mine')
def r_mine(call, a):
    rows = db.all('SELECT product_name, content, date FROM purchases WHERE user_id=? ORDER BY id DESC LIMIT 8',
                  (call.from_user.id,))
    if not rows:
        return answer(call, 'لا توجد مشتريات بعد.', True)
    parts = [f"🛍️ <b>{h(r['product_name'])}</b>\n<code>{h((r['content'] or '')[:300])}</code>\n🕒 {r['date']}"
             for r in rows]
    edit(call, '📦 <b>آخر مشترياتي:</b>\n\n' + '\n\n'.join(parts), kb([BTN_BACK]))


@route('orders')
def r_orders(call, a):
    rows = db.all("SELECT id, service, status, created_at FROM orders WHERE user_id=? AND kind!='product' "
                  "ORDER BY id DESC LIMIT 10", (call.from_user.id,))
    if not rows:
        return answer(call, 'لا توجد طلبات بعد.', True)
    st = {'pending': '⏳ قيد التنفيذ', 'done': '✅ مكتمل', 'refunded': '↩️ أُرجعت النقاط'}
    parts = [f"<b>#{r['id']}</b> • {h(r['service'])}\n{st.get(r['status'], r['status'])} • {str(r['created_at'])[:16]}"
             for r in rows]
    edit(call, f'📋 <b>طلباتي</b>\n{LINE}\n' + '\n\n'.join(parts), kb([BTN_BACK]))


@route('terms')
def r_terms(call, a):
    show_terms(call.message.chat.id, call)


@route('chk')
def r_chk(call, a):
    uid = call.from_user.id
    forget_member(uid)
    missing = missing_channels(uid)
    if missing:
        return answer(call, '❌ لم تشترك بعد في: ' + '، '.join(c['title'] for c in missing), True)
    answer(call, '✅ تم التحقق، أهلاً بك!')
    if gate(uid, call.message.chat.id, call):
        show_menu(uid, call, call.from_user.first_name)


@route('tok')
def r_tok(call, a):
    db.run('UPDATE users SET terms_ok=1 WHERE user_id=?', (call.from_user.id,))
    answer(call, '✅ شكراً لموافقتك!')
    if gate(call.from_user.id, call.message.chat.id, call):
        show_menu(call.from_user.id, call, call.from_user.first_name)


@route('earn')
def r_earn(call, a):
    uid = call.from_user.id
    n = db.one('SELECT COUNT(*) AS c FROM referrals WHERE invited_by=?', (uid,))['c']
    n_ok = db.one('SELECT COUNT(*) AS c FROM referrals WHERE invited_by=? AND join_rewarded=1', (uid,))['c']
    link = f'https://t.me/{BOT_USERNAME}?start={uid}'
    text = (f"💰 <b>اربح نقاط مجاناً</b>\n{LINE}\n🔗 رابط دعوتك:\n<code>{link}</code>\n\n"
            f"🎁 <b>+{int_setting('ref_join_reward')}</b> نقطة عن كل صديق يدخل من رابطك ويشترك في قنوات البوت الإجبارية.\n")
    if int_setting('ref_reward') > 0:
        text += f"🛍️ <b>+{int_setting('ref_reward')}</b> نقاط إضافية عندما يُكمل أول طلب.\n"
    text += "⚠️ تُسحب النقطة إذا غادر صديقك أي قناة، وتُلغى الدعوات الوهمية.\n"
    if not get_channels():
        text += "\n⏸️ مكافآت الدعوة متوقفة مؤقتاً.\n"
    text += f"{LINE}\n👥 المدعوون: {n}  •  ✅ المحتسبون: {n_ok}\n🎁 ولا تنسَ الهدية اليومية!"
    share = 'https://t.me/share/url?url=' + quote(link, safe='') + '&text=' + quote('🎁 انضم واحصل على خدمات مجانية!')
    edit(call, text, kb([url_btn('📤 مشاركة رابط الدعوة', share)], [BTN_BACK]))


@route('daily')
def r_daily(call, a):
    uid, bonus = call.from_user.id, int_setting('daily_bonus')
    remain = 0
    with db.tx() as c:
        r = c.execute('SELECT last_claim FROM daily_bonus WHERE user_id=?', (uid,)).fetchone()
        t = time.time()
        if r and t - r['last_claim'] < 86400:
            remain = int(86400 - (t - r['last_claim']))
        else:
            c.execute('INSERT OR REPLACE INTO daily_bonus (user_id, last_claim) VALUES (?,?)', (uid, t))
            c.execute('UPDATE users SET points=points+? WHERE user_id=?', (bonus, uid))
    if remain:
        return answer(call, f'❌ استلمت مكافأتك اليوم. متبقي {remain // 3600} ساعة و{remain % 3600 // 60} دقيقة.', True)
    answer(call, f'🎁 مبروك! حصلت على {bonus} نقطة مجانية.', True)


@route('promo')
def r_promo(call, a):
    set_state(call.from_user.id, 'promo')
    answer(call)
    ask(call.message.chat.id, '🎟️ أرسل كود الهدية الآن:')


@step('promo')
def s_promo(m, d):
    uid, code = m.from_user.id, (m.text or '').strip()
    with db.tx() as c:
        p = c.execute('SELECT * FROM promo_codes WHERE code=? COLLATE NOCASE', (code,)).fetchone()
        if not p or p['current_uses'] >= p['max_uses']:
            res = 'bad'
        elif c.execute('SELECT 1 FROM redeemed_codes WHERE user_id=? AND code=?', (uid, p['code'])).fetchone():
            res = 'used'
        else:
            c.execute('UPDATE promo_codes SET current_uses=current_uses+1 WHERE code=?', (p['code'],))
            c.execute('UPDATE users SET points=points+? WHERE user_id=?', (p['reward'], uid))
            c.execute('INSERT INTO redeemed_codes (user_id, code) VALUES (?,?)', (uid, p['code']))
            res = 'ok'
    clear_state(uid, force=True)
    msg = {'bad': '❌ الكود غير صحيح أو انتهت صلاحيته.', 'used': '❌ استخدمت هذا الكود مسبقاً.',
           'ok': f"🎉 مبروك! حصلت على {p['reward'] if p else 0} نقطة من الكود."}[res]
    bot.send_message(m.chat.id, msg, reply_markup=kb([BTN_BACK]))


# ---------------- الدعم ----------------
@route('sup')
def r_sup(call, a):
    set_state(call.from_user.id, 'support')
    answer(call)
    ask(call.message.chat.id, '✍️ اكتب رسالتك للإدارة:')


@step('support')
def s_support(m, d):
    text = (m.text or '').strip()[:1500]
    who = f'@{h(m.from_user.username)}' if m.from_user.username else 'بدون يوزر'
    notify(f"📩 <b>رسالة دعم جديدة</b>\n👤 {who} — <a href=\"tg://user?id={m.from_user.id}\">فتح المحادثة</a>\n"
           f"🆔 <code>{m.from_user.id}</code>\n\n{h(text)}\n\n↩️ للرد: <code>/reply {m.from_user.id} نص الرد</code>")
    clear_state(m.from_user.id, force=True)
    bot.send_message(m.chat.id, '✅ تم إرسال رسالتك للإدارة، سنرد عليك قريباً.', reply_markup=kb([BTN_BACK]))


@bot.message_handler(commands=['reply'])
@_safe
def cmd_reply(m):
    if m.from_user.id != ADMIN_ID:
        return
    parts = (m.text or '').split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        return bot.send_message(ADMIN_ID, 'الصيغة: /reply آيدي النص')
    try:
        bot.send_message(int(parts[1]), f'📩 <b>رد الإدارة:</b>\n\n{h(parts[2])}')
        bot.send_message(ADMIN_ID, '✅ تم إرسال الرد.')
    except Exception as e:
        bot.send_message(ADMIN_ID, f'❌ تعذر الإرسال: {h(str(e))}')


@bot.message_handler(commands=['pending'])
@_safe
def cmd_pending(m):
    if m.from_user.id != ADMIN_ID:
        return
    rows = db.all("SELECT id, service, user_id, username FROM orders WHERE status='pending' ORDER BY id DESC LIMIT 15")
    if not rows:
        return bot.send_message(ADMIN_ID, '✅ لا توجد طلبات معلّقة.')
    lines = [f"#{r['id']} — {h(r['service'])} — {('@' + h(r['username'])) if r['username'] else r['user_id']}"
             for r in rows]
    bot.send_message(ADMIN_ID, '⏳ <b>الطلبات المعلّقة:</b>\n\n' + '\n'.join(lines))


# ============================ لوحة الأدمن ============================
@bot.message_handler(commands=['diag'])
@_safe
def cmd_diag(m):
    if m.from_user.id != ADMIN_ID:
        return
    mode = db.one('PRAGMA journal_mode')[0]
    bot.send_message(ADMIN_ID, (
        f"🔧 <b>تشخيص</b>\n🧩 نسخة الكود: <code>{VERSION}</code>\n"
        f"🐍 Python: <code>{h(sys.version.split()[0])}</code> • telebot: <code>{h(str(getattr(telebot, '__version__', '?')))}</code>\n"
        f"📁 <code>{h(os.path.abspath(DB_PATH))}</code> • الوضع: <code>{mode}</code>\n"
        f"🏪 الاسم: <code>{h(repr(get_setting('store_name')))}</code>\n"
        f"👋 الترحيب: <code>{h(repr(get_setting('welcome_text'))[:200])}</code>\n"
        f"📢 قنوات: {len(get_channels())} • 🛠️ صيانة: {get_setting('maintenance')}"))


@bot.message_handler(commands=['warn'])
@_safe
def cmd_warn(m):
    if m.from_user.id == ADMIN_ID and m.chat.type == 'private':
        txt = re.sub(r'<[^>]+>', '', LEAVE_WARN)
        threading.Thread(target=do_broadcast, args=(txt,), daemon=True).start()
        bot.send_message(ADMIN_ID, '⏳ جاري إرسال التحذير لكل المستخدمين...')


@bot.message_handler(commands=['admin'])
@_safe
def cmd_admin(m):
    if m.from_user.id == ADMIN_ID and m.chat.type == 'private':
        clear_state(ADMIN_ID, force=True)
        bot.send_message(ADMIN_ID, '👑 <b>لوحة تحكم الأدمن:</b>', reply_markup=admin_markup())


def admin_markup():
    return kb(
        [btn('📊 الإحصائيات', 'a_stats'), btn('🔎 بحث عن مستخدم', 'a_find')],
        [btn('🌐 تفعيل نقاط تشغيل', 'a_pp'), btn('✨ تفعيل الجائزة الأسبوعية', 'a_wk')],
        [btn('➕ إضافة منتج', 'a_add'), btn('🗑️ حذف منتج', 'a_del:0')],
        [btn('✏️ تعديل سعر منتج', 'a_ep:0'), btn('⏳ الطلبات المعلقة', 'a_pend')],
        [btn('👥 تعديل نقاط', 'a_pts'), btn('🚫 حظر/فك حظر', 'a_ban')],
        [btn('🎟️ أكواد الهدايا', 'a_promo'), btn('📢 إذاعة', 'a_bc')],
        [btn('📢 الاشتراك الإجباري', 'a_fs'), btn('📜 الشروط', 'a_terms')],
        [btn('🧩 الأقسام والأزرار', 'a_sec'), btn('⚙️ الإعدادات', 'a_set')],
        [btn('💾 نسخة احتياطية', 'a_bk')],
        [BTN_BACK])


def back_admin():
    return kb([btn('👑 لوحة الأدمن', 'a_home')])


@route('a_home', admin=True)
def r_a_home(call, a):
    clear_state(ADMIN_ID, force=True)
    edit(call, '👑 <b>لوحة تحكم الأدمن:</b>', admin_markup())


@route('a_stats', admin=True)
def r_a_stats(call, a):
    def q(sql, params=()):
        return db.one(sql, params)[0]
    day = time.time() - 86400
    edit(call, f"📊 <b>الإحصائيات</b>\n\n"
               f"👥 المستخدمون: {q('SELECT COUNT(*) FROM users')} (جدد خلال 24 ساعة: "
               f"{q('SELECT COUNT(*) FROM users WHERE joined_at>?', (day,))})\n"
               f"🚫 المحظورون: {q('SELECT COUNT(*) FROM users WHERE banned=1')}\n"
               f"🔗 الدعوات المحتسبة: {q('SELECT COUNT(*) FROM referrals WHERE join_rewarded=1')} "
               f"من أصل {q('SELECT COUNT(*) FROM referrals')}\n"
               f"⏳ طلبات معلّقة: {q('SELECT COUNT(*) FROM orders WHERE status=?', ('pending',))}\n"
               f"✅ طلبات منفذة: {q('SELECT COUNT(*) FROM orders WHERE status=?', ('done',))}\n"
               f"📦 وحدات متاحة: {q('SELECT COALESCE(SUM(stock),0) FROM products WHERE stock>0')}\n"
               f"💰 نقاط المستخدمين: {q('SELECT COALESCE(SUM(points),0) FROM users WHERE user_id != ?', (ADMIN_ID,))}",
         back_admin())


def toggle_label(key, label_text):
    return btn(f"{label_text}: {'🟢 مفعلة' if get_setting(key) == 'active' else '🔴 متوقفة'}", f'a_toggle:{key}')


@route('a_pp', admin=True)
def r_a_pp(call, a):
    rows = [[toggle_label('status_playpoint', 'حالة الخدمة')]]
    for _, (name, _f) in SERVERS.items():
        rows.append([btn(f"💵 سعر {name} ({int_setting('price_' + name)})", f'a_price:price_{name}')])
    rows.append([btn('⬅️ عودة', 'a_home')])
    edit(call, '🌐 <b>تحكم بأسعار وتفعيل نقاط تشغيل:</b>', kb(*rows))


@route('a_wk', admin=True)
def r_a_wk(call, a):
    edit(call, '✨ <b>تحكم بتفعيل الجائزة الأسبوعية:</b>', kb(
        [btn(f"🔗 سعر برابط دفع ({int_setting('price_weekly_link')})", 'a_price:price_weekly_link')],
        [btn(f"🔑 سعر بالحساب ({int_setting('price_weekly_acc')})", 'a_price:price_weekly_acc')],
        [toggle_label('status_weekly_link', 'طريقة رابط الدفع')],
        [toggle_label('status_weekly_acc', 'طريقة الحساب وكلمة السر')],
        [btn('⬅️ عودة', 'a_home')]))


@route('a_toggle', admin=True)
def r_a_toggle(call, a):
    key = a[0]
    if key not in TOGGLE_KEYS:
        return
    set_setting(key, 'off' if get_setting(key) == 'active' else 'active')
    if key == 'status_playpoint':
        r_a_pp(call, [])
    elif key.startswith('status_weekly'):
        r_a_wk(call, [])
    elif key.startswith('show_'):
        r_a_sec(call, [])
    else:
        r_a_set(call, [])


@route('a_set', admin=True)
def r_a_set(call, a):
    rows = [[btn(f"{lbl} ({int_setting(k)})", f'a_price:{k}')] for k, lbl in SETTING_LABELS.items()]
    rows += [[toggle_label('maintenance', '🛠️ وضع الصيانة')],
             [btn('🏪 اسم المتجر', 'a_txt:store_name')],
             [btn('👋 رسالة الترحيب', 'a_txt:welcome_text')],
             [btn('🛠️ رسالة الصيانة', 'a_txt:maintenance_text')],
             [btn('⬅️ عودة', 'a_home')]]
    edit(call, '⚙️ <b>الإعدادات العامة:</b>', kb(*rows))


@route('a_price', admin=True)
def r_a_price(call, a):
    key = a[0]
    if key not in NUMERIC_KEYS:
        return
    set_state(ADMIN_ID, 'adm_set', key=key)
    answer(call)
    ask(ADMIN_ID, f"أرسل القيمة الجديدة (رقم) لـ <b>{h(SETTING_LABELS.get(key, key))}</b>\n"
                  f"الحالية: <b>{int_setting(key)}</b>", ADMIN_CANCEL_KB)


@step('adm_set')
def s_adm_set(m, d):
    v = parse_int(m.text)
    if v is None:
        return ask(m.chat.id, '❌ أرسل رقماً صحيحاً.', ADMIN_CANCEL_KB)
    set_setting(d['key'], v)
    clear_state(ADMIN_ID, force=True)
    bot.send_message(m.chat.id, f"✅ تم التحديث إلى {v}", reply_markup=back_admin())


@route('a_txt', admin=True)
def r_a_txt(call, a):
    key = a[0]
    if key not in TEXT_KEYS:
        return
    set_state(ADMIN_ID, 'adm_txt', key=key)
    answer(call)
    extra = ''
    if key == 'welcome_text':
        extra = ('\n\nالمتغيرات: <code>{name}</code> اسم العميل، <code>{points}</code> رصيده، '
                 '<code>{store}</code> اسم المتجر، <code>{line}</code> خط فاصل')
    ask(ADMIN_ID, f"✍️ <b>{TEXT_KEYS[key][0]}</b>\nالحالي:\n<code>{h(get_setting(key))}</code>{extra}\n\n"
                  f"أرسل النص الجديد:", ADMIN_CANCEL_KB)


@step('adm_txt')
def s_adm_txt(m, d):
    text = (m.text or '').strip()
    limit = TEXT_KEYS[d['key']][1]
    if not text or len(text) > limit:
        return ask(m.chat.id, f'❌ النص فارغ أو أطول من {limit} حرفاً.', ADMIN_CANCEL_KB)
    set_setting(d['key'], text)
    clear_state(ADMIN_ID, force=True)
    bot.send_message(m.chat.id, '✅ تم الحفظ.', reply_markup=kb([btn('⚙️ الإعدادات', 'a_set')],
                                                              [btn('👑 لوحة الأدمن', 'a_home')]))


@route('a_sec', admin=True)
def r_a_sec(call, a):
    rows = []
    for sid in MENU_IDS:
        rows.append([btn(f"{'🟢' if section_on(sid) else '🔴'} {label(sid)}", f'a_toggle:show_{sid}'),
                     btn('✏️', f'a_secren:{sid}')])
    rows.append([btn('⬅️ عودة', 'a_home')])
    edit(call, '🧩 <b>الأقسام والأزرار</b>\n🟢 ظاهر • 🔴 مخفي (اضغط على الاسم للتبديل)\n'
               '✏️ لتغيير اسم الزر', kb(*rows))


@route('a_secren', admin=True)
def r_a_secren(call, a):
    sid = a[0]
    if sid not in MENU_IDS:
        return
    set_state(ADMIN_ID, 'adm_label', sid=sid)
    answer(call)
    ask(ADMIN_ID, f"✏️ أرسل الاسم الجديد للزر (يمكنك إضافة إيموجي).\nالحالي: <code>{h(label(sid))}</code>",
        ADMIN_CANCEL_KB)


@step('adm_label')
def s_adm_label(m, d):
    t = (m.text or '').strip()
    if not t or len(t) > 40 or '\n' in t:
        return ask(m.chat.id, '❌ الاسم فارغ أو أطول من 40 حرفاً أو يحتوي على أكثر من سطر.', ADMIN_CANCEL_KB)
    set_setting('label_' + d['sid'], t)
    clear_state(ADMIN_ID, force=True)
    bot.send_message(m.chat.id, '✅ تم تغيير الاسم.', reply_markup=kb([btn('🧩 الأقسام والأزرار', 'a_sec')],
                                                                    [btn('👑 لوحة الأدمن', 'a_home')]))


# ---- الطلبات المعلقة ----
@route('a_pend', admin=True)
def r_a_pend(call, a):
    rows = db.all("SELECT id FROM orders WHERE status='pending' AND kind!='product' ORDER BY id LIMIT 10")
    if not rows:
        return answer(call, '✅ لا توجد طلبات معلّقة.', True)
    answer(call)
    for r in rows:
        o = get_order(r['id'])
        bot.send_message(ADMIN_ID, order_text(o) + '\n\n' + STATUS_TXT['pending'] +
                         '\n🔒 كلمة المرور (إن وُجدت) في رسالة الطلب الأصلية.', reply_markup=order_buttons(o['id']))
    bot.send_message(ADMIN_ID, f'⏳ عُرض {len(rows)} طلب (الأقدم أولاً).', reply_markup=back_admin())


# ---- إضافة منتج ----
@route('a_add', admin=True)
def r_a_add(call, a):
    edit(call, 'اختر القسم المراد الإضافة إليه:', kb(
        [btn(label('accounts'), 'a_ac:accounts')],
        [btn(label('codes'), 'a_ac:codes')],
        [btn('⬅️ عودة', 'a_home')]))


@route('a_ac', admin=True)
def r_a_ac(call, a):
    if a[0] not in CATS:
        return
    set_state(ADMIN_ID, 'adm_name', category=a[0])
    answer(call)
    ask(ADMIN_ID, 'أرسل اسم المنتج:', ADMIN_CANCEL_KB)


@step('adm_name')
def s_adm_name(m, d):
    name = (m.text or '').strip()
    if not name or len(name) > 100:
        return ask(m.chat.id, '❌ اسم غير صالح.', ADMIN_CANCEL_KB)
    next_step(ADMIN_ID, 'adm_price', name=name)
    ask(m.chat.id, 'أرسل السعر بالنقاط (رقم صحيح، 0 = مجاني):', ADMIN_CANCEL_KB)


@step('adm_price')
def s_adm_price(m, d):
    price = parse_int(m.text)
    if price is None:
        return ask(m.chat.id, '❌ أرسل رقماً صحيحاً (0 = مجاني).', ADMIN_CANCEL_KB)
    next_step(ADMIN_ID, 'adm_content', price=price)
    ask(m.chat.id, 'أرسل المحتوى (إيميل/كود...).\n📌 <b>كل سطر = وحدة منفصلة</b> تُباع لعميل واحد.\n'
                   'يمكنك لصق عدة أسطر دفعة واحدة.', ADMIN_CANCEL_KB)


@step('adm_content')
def s_adm_content(m, d):
    lines = [l.strip() for l in (m.text or '').splitlines() if l.strip()]
    if not lines:
        return ask(m.chat.id, '❌ المحتوى فارغ.', ADMIN_CANCEL_KB)
    with db.tx() as c:
        c.executemany('INSERT INTO products (category, name, price, content, stock) VALUES (?,?,?,?,1)',
                      [(d['category'], d['name'], d['price'], l) for l in lines])
    clear_state(ADMIN_ID, force=True)
    bot.send_message(m.chat.id, f"✅ تمت إضافة <b>{len(lines)}</b> وحدة من «{h(d['name'])}».", reply_markup=back_admin())


# ---- قائمة المنتجات (للحذف وتعديل السعر) ----
def product_groups():
    return db.all("SELECT MIN(id) AS id, category, name, price, SUM(stock) AS stock FROM products "
                  "WHERE stock>0 AND category IN ('accounts','codes') GROUP BY category, name, price ORDER BY MIN(id)")


def product_list(call, page, list_cb, item_cb, icon, title):
    groups = product_groups()
    if not groups:
        return answer(call, 'لا توجد منتجات.', True)
    per = 8
    pages = (len(groups) - 1) // per + 1
    page = max(0, min(page, pages - 1))
    cat_name = {'accounts': 'حسابات', 'codes': 'قسائم'}
    buttons = [[btn(f"{icon} {g['name']} • {fmt_price(g['price'])} • ×{g['stock']} [{cat_name[g['category']]}]",
                    f"{item_cb}:{g['id']}:{page}")] for g in groups[page * per:(page + 1) * per]]
    nav = []
    if page > 0:
        nav.append(btn('⬅️', f'{list_cb}:{page - 1}'))
    if page < pages - 1:
        nav.append(btn('➡️', f'{list_cb}:{page + 1}'))
    if nav:
        buttons.append(nav)
    buttons.append([btn('⬅️ عودة', 'a_home')])
    edit(call, f'{title} (صفحة {page + 1}/{pages}):', kb(*buttons))


@route('a_del', admin=True)
def r_a_del(call, a):
    product_list(call, int(a[0]), 'a_del', 'a_dx', '❌', '🗑️ اختر المنتج لحذفه بكل وحداته')


@route('a_dx', admin=True)
def r_a_dx(call, a):
    ref = db.one('SELECT category, name, price FROM products WHERE id=?', (int(a[0]),))
    if ref:
        db.run('DELETE FROM products WHERE category=? AND name=? AND price=? AND stock>0', tuple(ref))
        answer(call, '✅ تم حذف المنتج بكل وحداته.')
    if product_groups():
        r_a_del(call, [a[1]])
    else:
        r_a_home(call, [])


@route('a_ep', admin=True)
def r_a_ep(call, a):
    product_list(call, int(a[0]), 'a_ep', 'a_epx', '✏️', '✏️ اختر المنتج لتعديل سعره')


@route('a_epx', admin=True)
def r_a_epx(call, a):
    ref = db.one('SELECT name, price FROM products WHERE id=?', (int(a[0]),))
    if not ref:
        return answer(call, '❌ المنتج غير موجود.', True)
    set_state(ADMIN_ID, 'adm_ep', pid=int(a[0]))
    answer(call)
    ask(ADMIN_ID, f"✏️ <b>{h(ref['name'])}</b>\nالسعر الحالي: {fmt_price(ref['price'])}\n"
                  f"أرسل السعر الجديد (رقم، 0 = مجاني):", ADMIN_CANCEL_KB)


@step('adm_ep')
def s_adm_ep(m, d):
    price = parse_int(m.text)
    if price is None:
        return ask(m.chat.id, '❌ أرسل رقماً صحيحاً.', ADMIN_CANCEL_KB)
    ref = db.one('SELECT category, name, price FROM products WHERE id=?', (d['pid'],))
    clear_state(ADMIN_ID, force=True)
    if not ref:
        return bot.send_message(m.chat.id, '❌ المنتج لم يعد موجوداً.', reply_markup=back_admin())
    db.run('UPDATE products SET price=? WHERE category=? AND name=? AND price=?',
           (price, ref['category'], ref['name'], ref['price']))
    bot.send_message(m.chat.id, f"✅ تم تعديل سعر «{h(ref['name'])}» إلى {fmt_price(price)}.", reply_markup=back_admin())


# ---- نقاط / حظر / بحث ----
def set_ban(uid, banned):
    db.run('UPDATE users SET banned=? WHERE user_id=?', (1 if banned else 0, uid))
    if banned:
        revoke_join_reward(uid)  # المحظور لا تُحتسب دعوته


def find_user(text):
    t = (text or '').strip()
    if t.startswith('@'):
        return db.one('SELECT user_id FROM users WHERE username=? COLLATE NOCASE', (t[1:],))
    n = parse_int(t)
    return db.one('SELECT user_id FROM users WHERE user_id=?', (n,)) if n is not None else None


def user_card(uid):
    u = db.one('SELECT * FROM users WHERE user_id=?', (uid,))
    inv = db.one('SELECT invited_by, join_rewarded, blocked FROM referrals WHERE user_id=?', (uid,))
    n_ref = db.one('SELECT COUNT(*) AS c FROM referrals WHERE invited_by=?', (uid,))['c']
    n_ok = db.one('SELECT COUNT(*) AS c FROM referrals WHERE invited_by=? AND join_rewarded=1', (uid,))['c']
    n_ord = db.one("SELECT COUNT(*) AS c FROM orders WHERE user_id=? AND kind!='product'", (uid,))['c']
    who = f"@{h(u['username'])}" if u['username'] else 'بدون يوزر'
    text = (f"👤 <b>بيانات المستخدم</b>\n{LINE}\n"
            f"🆔 <code>{uid}</code> — {who} — <a href=\"tg://user?id={uid}\">فتح المحادثة</a>\n"
            f"💎 الرصيد: <b>{u['points']}</b>\n"
            f"🚦 الحالة: {'🚫 محظور' if u['banned'] else '✅ نشط'}\n"
            f"👥 دعا: {n_ref} (محتسب: {n_ok})\n"
            f"📋 الطلبات: {n_ord}")
    if inv:
        state = 'ملغاة' if inv['blocked'] else ('محتسبة' if inv['join_rewarded'] else 'غير محتسبة')
        text += f"\n🔗 دعاه: <code>{inv['invited_by']}</code> (الدعوة {state})"
    markup = kb([btn('➕/➖ نقاط', f'a_upt:{uid}'), btn('🔓 فك الحظر' if u['banned'] else '🚫 حظر', f'a_ubn:{uid}')],
                [btn('💬 مراسلته', f'a_umsg:{uid}'), btn('🧹 إلغاء دعواته', f'a_uref:{uid}')],
                [btn('👑 لوحة الأدمن', 'a_home')])
    return text, markup


@route('a_find', admin=True)
def r_a_find(call, a):
    set_state(ADMIN_ID, 'adm_find')
    answer(call)
    ask(ADMIN_ID, '🔎 أرسل آيدي المستخدم أو يوزره (<code>@username</code>):', ADMIN_CANCEL_KB)


@step('adm_find')
def s_adm_find(m, d):
    row = find_user(m.text)
    if not row:
        return ask(m.chat.id, '❌ المستخدم غير موجود. أعد المحاولة:', ADMIN_CANCEL_KB)
    clear_state(ADMIN_ID, force=True)
    text, markup = user_card(row['user_id'])
    bot.send_message(m.chat.id, text, reply_markup=markup)


def _valid_target(call, a):
    uid = int(a[0])
    if uid == ADMIN_ID or not db.one('SELECT 1 FROM users WHERE user_id=?', (uid,)):
        answer(call, '❌ غير ممكن.', True)
        return None
    return uid


@route('a_ubn', admin=True)
def r_a_ubn(call, a):
    uid = _valid_target(call, a)
    if uid is None:
        return
    set_ban(uid, not is_banned(uid))
    text, markup = user_card(uid)
    edit(call, text, markup)


@route('a_upt', admin=True)
def r_a_upt(call, a):
    uid = _valid_target(call, a)
    if uid is None:
        return
    set_state(ADMIN_ID, 'adm_upt', target=uid)
    answer(call)
    ask(ADMIN_ID, f'أرسل عدد النقاط للمستخدم <code>{uid}</code> (سالب للخصم):', ADMIN_CANCEL_KB)


@step('adm_upt')
def s_adm_upt(m, d):
    amount = parse_int(m.text, signed=True)
    if amount is None:
        return ask(m.chat.id, '❌ أرسل رقماً صحيحاً (مثال: 50 أو -10).', ADMIN_CANCEL_KB)
    db.run('UPDATE users SET points=MAX(points+?,0) WHERE user_id=?', (amount, d['target']))
    clear_state(ADMIN_ID, force=True)
    text, markup = user_card(d['target'])
    bot.send_message(m.chat.id, '✅ تم التعديل.\n\n' + text, reply_markup=markup)


@route('a_umsg', admin=True)
def r_a_umsg(call, a):
    uid = _valid_target(call, a)
    if uid is None:
        return
    set_state(ADMIN_ID, 'adm_umsg', target=uid)
    answer(call)
    ask(ADMIN_ID, f'✍️ أرسل الرسالة التي تريد إرسالها للمستخدم <code>{uid}</code>:', ADMIN_CANCEL_KB)


@step('adm_umsg')
def s_adm_umsg(m, d):
    text = (m.text or '').strip()[:3000]
    if not text:
        return ask(m.chat.id, '❌ الرسالة فارغة.', ADMIN_CANCEL_KB)
    clear_state(ADMIN_ID, force=True)
    try:
        bot.send_message(d['target'], f'📩 <b>رسالة من الإدارة:</b>\n\n{h(text)}')
        bot.send_message(m.chat.id, '✅ تم الإرسال.', reply_markup=back_admin())
    except Exception as e:
        bot.send_message(m.chat.id, f'❌ تعذر الإرسال: {h(str(e))[:200]}', reply_markup=back_admin())


@route('a_uref', admin=True)
def r_a_uref(call, a):
    uid = _valid_target(call, a)
    if uid is None:
        return
    total = n = 0
    for r in db.all('SELECT user_id FROM referrals WHERE invited_by=?', (uid,)):
        total += revoke_join_reward(r['user_id'], block=True, notify_inviter=False)
        n += 1
    answer(call, f'✅ أُلغيت {n} دعوة وسُحب {total} نقطة.', True)
    text, markup = user_card(uid)
    edit(call, text, markup)


@route('a_pts', admin=True)
def r_a_pts(call, a):
    set_state(ADMIN_ID, 'adm_points')
    answer(call)
    ask(ADMIN_ID, 'أرسل آيدي المستخدم ثم عدد النقاط (سالب للخصم)\nمثال: <code>123456 50</code>', ADMIN_CANCEL_KB)


@step('adm_points')
def s_adm_points(m, d):
    parts = (m.text or '').split()
    uid = parse_int(parts[0]) if len(parts) == 2 else None
    amount = parse_int(parts[1], signed=True) if len(parts) == 2 else None
    if uid is None or amount is None:
        return ask(m.chat.id, '❌ خطأ بالصيغة. مثال: 123456 50', ADMIN_CANCEL_KB)
    if not db.one('SELECT 1 FROM users WHERE user_id=?', (uid,)):
        return ask(m.chat.id, '❌ المستخدم غير موجود.', ADMIN_CANCEL_KB)
    db.run('UPDATE users SET points=MAX(points+?,0) WHERE user_id=?', (amount, uid))
    clear_state(ADMIN_ID, force=True)
    bot.send_message(m.chat.id, f'✅ تم التعديل. الرصيد الجديد: <b>{get_points(uid)}</b>', reply_markup=back_admin())


@route('a_ban', admin=True)
def r_a_ban(call, a):
    set_state(ADMIN_ID, 'adm_ban')
    answer(call)
    ask(ADMIN_ID, 'أرسل آيدي المستخدم أو يوزره لتبديل حالة الحظر:', ADMIN_CANCEL_KB)


@step('adm_ban')
def s_adm_ban(m, d):
    row = find_user(m.text)
    if not row or row['user_id'] == ADMIN_ID:
        return ask(m.chat.id, '❌ المستخدم غير موجود أو غير صالح.', ADMIN_CANCEL_KB)
    uid = row['user_id']
    new = not is_banned(uid)
    set_ban(uid, new)
    clear_state(ADMIN_ID, force=True)
    bot.send_message(m.chat.id, '🚫 تم حظر المستخدم.' if new else '✅ تم فك الحظر.', reply_markup=back_admin())


# ---- أكواد الهدايا ----
@route('a_promo', admin=True)
def r_a_promo(call, a):
    rows = db.all('SELECT rowid AS rid, code, reward, max_uses, current_uses FROM promo_codes '
                  'ORDER BY rowid DESC LIMIT 20')
    buttons = [[btn(f"🗑️ {r['code']} • +{r['reward']} • {r['current_uses']}/{r['max_uses']}", f"a_pdx:{r['rid']}")]
               for r in rows]
    buttons += [[btn('➕ إنشاء كود جديد', 'a_pnew')], [btn('⬅️ عودة', 'a_home')]]
    edit(call, '🎟️ <b>أكواد الهدايا</b>\n' + ('اضغط على كود لحذفه 👇\n(المكافأة • المستخدم/الأقصى)' if rows
                                              else 'لا توجد أكواد بعد.'), kb(*buttons))


@route('a_pdx', admin=True)
def r_a_pdx(call, a):
    r = db.one('SELECT code FROM promo_codes WHERE rowid=?', (int(a[0]),))
    if r:
        with db.tx() as c:
            c.execute('DELETE FROM promo_codes WHERE rowid=?', (int(a[0]),))
            c.execute('DELETE FROM redeemed_codes WHERE code=?', (r['code'],))
        answer(call, '✅ تم حذف الكود.')
    r_a_promo(call, [])


@route('a_pnew', admin=True)
def r_a_pnew(call, a):
    set_state(ADMIN_ID, 'adm_promo')
    answer(call)
    ask(ADMIN_ID, 'أرسل: <code>الكود المكافأة عدد_الاستخدامات</code>\nمثال: <code>EID2026 5 100</code>', ADMIN_CANCEL_KB)


@step('adm_promo')
def s_adm_promo(m, d):
    parts = (m.text or '').split()
    reward = parse_int(parts[1]) if len(parts) == 3 else None
    uses = parse_int(parts[2]) if len(parts) == 3 else None
    if reward is None or uses is None or uses < 1:
        return ask(m.chat.id, '❌ الصيغة: الكود المكافأة العدد', ADMIN_CANCEL_KB)
    if db.one('SELECT 1 FROM promo_codes WHERE code=? COLLATE NOCASE', (parts[0],)):
        return ask(m.chat.id, '❌ هذا الكود موجود مسبقاً.', ADMIN_CANCEL_KB)
    db.run('INSERT INTO promo_codes (code, reward, max_uses) VALUES (?,?,?)', (parts[0], reward, uses))
    clear_state(ADMIN_ID, force=True)
    bot.send_message(m.chat.id, f'✅ تم إنشاء الكود <code>{h(parts[0])}</code>', reply_markup=kb(
        [btn('🎟️ أكواد الهدايا', 'a_promo')], [btn('👑 لوحة الأدمن', 'a_home')]))


@route('a_bc', admin=True)
def r_a_bc(call, a):
    set_state(ADMIN_ID, 'adm_bc')
    answer(call)
    ask(ADMIN_ID, '📢 أرسل نص الإذاعة (سيصل لكل المستخدمين):', ADMIN_CANCEL_KB)


@step('adm_bc')
def s_adm_bc(m, d):
    text = (m.text or '').strip()
    if not text:
        return ask(m.chat.id, '❌ النص فارغ.', ADMIN_CANCEL_KB)
    n = db.one('SELECT COUNT(*) AS c FROM users WHERE banned=0')['c']
    next_step(ADMIN_ID, 'adm_bc_wait', text=text)
    bot.send_message(m.chat.id, f'سيتم إرسال الرسالة إلى <b>{n}</b> مستخدم:\n\n{h(text)}',
                     reply_markup=kb([btn('✅ إرسال الآن', 'a_bcy')], [btn('❌ إلغاء', 'a_home')]))


@step('adm_bc_wait')
def s_adm_bc_wait(m, d):
    ask(m.chat.id, 'اضغط «إرسال الآن» أو «إلغاء».', ADMIN_CANCEL_KB)


def do_broadcast(text):
    ids = [r['user_id'] for r in db.all('SELECT user_id FROM users WHERE banned=0')]
    ok = fail = 0
    for i in ids:
        try:
            bot.send_message(i, h(text))
            ok += 1
        except Exception:
            fail += 1
        time.sleep(0.05)
    bot.send_message(ADMIN_ID, f'📢 اكتملت الإذاعة: ✅ {ok} | ❌ {fail}', reply_markup=back_admin())


@route('a_bcy', admin=True)
def r_a_bcy(call, a):
    st = get_state(ADMIN_ID)
    if not st or st['step'] != 'adm_bc_wait':
        return answer(call, 'انتهت الجلسة.', True)
    text = st['data']['text']
    clear_state(ADMIN_ID, force=True)
    threading.Thread(target=do_broadcast, args=(text,), daemon=True).start()
    edit(call, '⏳ جاري الإرسال...', None)


# ---- الاشتراك الإجباري ----
@route('a_fs', admin=True)
def r_a_fs(call, a):
    chans = get_channels()
    rows = [[btn(f"🗑️ حذف: {c['title']}", f'a_fsd:{i}')] for i, c in enumerate(chans)]
    rows += [[btn('➕ إضافة قناة', 'a_fsa')], [btn('⬅️ عودة', 'a_home')]]
    state = 'اضغط على قناة لحذفها 👇' if chans else '⚪ لا توجد قنوات (الاشتراك الإجباري متوقف)'
    edit(call, f'📢 <b>الاشتراك الإجباري</b>\n{LINE}\n{state}\n\n'
               f'⚠️ يجب أن يكون البوت <b>أدمن</b> في كل قناة (ليكشف المغادرين فوراً).\n'
               f'نقاط الدعوة تُمنح فقط عند وجود قناة واحدة على الأقل، وتُسحب إذا غادر المدعو أي قناة.',
         kb(*rows))


@route('a_fsd', admin=True)
def r_a_fsd(call, a):
    chans = get_channels()
    i = int(a[0])
    if 0 <= i < len(chans):
        chans.pop(i)
        set_setting('force_channels', json.dumps(chans, ensure_ascii=False))
    r_a_fs(call, [])


@route('a_fsa', admin=True)
def r_a_fsa(call, a):
    set_state(ADMIN_ID, 'adm_fs')
    answer(call)
    ask(ADMIN_ID, 'أرسل معرف القناة العامة مثل <code>@channel</code>\n'
                  'أو للقناة الخاصة: <code>-100123456789 https://t.me/+رابط_الدعوة</code>', ADMIN_CANCEL_KB)


@step('adm_fs')
def s_adm_fs(m, d):
    parts = (m.text or '').split()
    try:
        if len(parts) == 1 and parts[0].startswith('@'):
            chat, link = parts[0], f'https://t.me/{parts[0][1:]}'
        elif len(parts) == 2 and re.match(r'^-?\d+$', parts[0]) and clean_url(parts[1]):
            chat, link = int(parts[0]), parts[1]
        else:
            return ask(m.chat.id, '❌ صيغة غير صحيحة.', ADMIN_CANCEL_KB)
        info = bot.get_chat(chat)
        me = bot.get_chat_member(info.id, BOT_ID)
        if me.status not in ('administrator', 'creator'):
            return ask(m.chat.id, '❌ ارفع البوت <b>أدمن</b> في القناة أولاً ثم أعد المحاولة.', ADMIN_CANCEL_KB)
    except Exception as e:
        return ask(m.chat.id, f'❌ تعذر الوصول للقناة: {h(str(e))[:200]}', ADMIN_CANCEL_KB)
    chans = get_channels()
    if any(c.get('id') == info.id or c['chat'] == chat for c in chans):
        return ask(m.chat.id, '❌ هذه القناة مضافة مسبقاً.', ADMIN_CANCEL_KB)
    chans.append({'chat': chat, 'id': info.id, 'title': info.title or str(chat), 'link': link})
    set_setting('force_channels', json.dumps(chans, ensure_ascii=False))
    clear_state(ADMIN_ID, force=True)
    bot.send_message(m.chat.id, f"✅ تمت إضافة <b>{h(info.title or '')}</b>", reply_markup=kb(
        [btn('📢 القنوات', 'a_fs')], [btn('👑 لوحة الأدمن', 'a_home')]))


# ---- الشروط ----
@route('a_terms', admin=True)
def r_a_terms(call, a):
    set_state(ADMIN_ID, 'adm_terms')
    answer(call)
    bot.send_message(ADMIN_ID, f"📜 <b>الشروط الحالية:</b>\n{LINE}\n{h(get_setting('terms_text'))}\n{LINE}\n"
                               f"✍️ أرسل النص الجديد للشروط:", reply_markup=ADMIN_CANCEL_KB)


@step('adm_terms')
def s_adm_terms(m, d):
    text = (m.text or '').strip()
    if len(text) < 10 or len(text) > 3000:
        return ask(m.chat.id, '❌ النص قصير أو طويل جداً.', ADMIN_CANCEL_KB)
    set_setting('terms_text', text)
    clear_state(ADMIN_ID, force=True)
    bot.send_message(m.chat.id, '✅ تم تحديث الشروط (ستظهر للمستخدمين الجدد).', reply_markup=back_admin())


# ---- تقرير التشغيل والاسترجاع ----
def startup_report():
    """يرسل للأدمن حالة القاعدة عند كل تشغيل، فإن رجعت لنسخة قديمة تلاحظ ذلك فوراً."""
    path = os.path.abspath(DB_PATH)
    q = lambda sql: db.one(sql)[0]
    try:
        first = time.strftime('%Y-%m-%d %H:%M', time.localtime(float(get_setting('db_first_seen'))))
    except ValueError:
        first = '—'
    last = db.one('SELECT id, created_at FROM orders ORDER BY id DESC LIMIT 1')
    notify(f"🟢 <b>البوت اشتغل</b> (نسخة {VERSION})\n📁 القاعدة: <code>{h(path)}</code>\n"
           f"🕒 أول ظهور للقاعدة: {first}\n"
           f"👥 المستخدمون: {q('SELECT COUNT(*) FROM users')} • 📦 الطلبات: {q('SELECT COUNT(*) FROM orders')}"
           f" • آخر طلب: {('#%s %s' % (last['id'], str(last['created_at'])[:16])) if last else '—'}\n"
           f"⚠️ إذا بدت هذه الأرقام أقدم مما تتوقع فالقاعدة رجعت لنسخة قديمة (التخزين غير دائم).\n"
           f"↩️ للاسترجاع: أرسل ملف النسخة الاحتياطية .db مع التعليق <code>/restore</code>")


def restore_db(path):
    chk = sqlite3.connect(path)
    try:
        tables = {r[0] for r in chk.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'users', 'settings', 'orders', 'products'} <= tables:
            raise ValueError('الملف ليس نسخة احتياطية صالحة لهذا البوت')
        with db.lock:
            chk.backup(db.conn)
    finally:
        chk.close()
    init_db()


def _make_restore(b):
    @b.message_handler(content_types=['document'],
                         func=lambda m: m.from_user.id == ADMIN_ID and (m.caption or '').strip().startswith('/restore'))
    def on_restore(m):
        path = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), 'restore_tmp.db')
        try:
            if (m.document.file_size or 0) > 50 * 1024 * 1024:
                return b.send_message(m.chat.id, '❌ الملف كبير جداً.')
            data = b.download_file(b.get_file(m.document.file_id).file_path)
            with open(path, 'wb') as f:
                f.write(data)
            restore_db(path)
            b.send_message(m.chat.id, '✅ تم استرجاع النسخة الاحتياطية بنجاح.')
            startup_report()
        except Exception as e:
            log.exception('restore failed')
            b.send_message(m.chat.id, f'❌ فشل الاسترجاع: {h(str(e))[:200]}')
        finally:
            if os.path.exists(path):
                os.remove(path)


for _b in dict.fromkeys([notifier, bot]):
    _make_restore(_b)


# ---- منع تشغيل نسختين معاً ----
def instance_stale():
    """True إذا بدأت نسخة أحدث من البوت على نفس القاعدة (فتتوقف هذه تلقائياً)."""
    r = db.one("SELECT value FROM settings WHERE key='active_instance'")
    return bool(r and r['value'] != INSTANCE_ID)


def instance_watchdog():
    while True:
        time.sleep(5)
        try:
            if instance_stale():
                log.error('⛔ بدأت نسخة أحدث من البوت على نفس القاعدة، سيتوقف هذا الإصدار القديم الآن.')
                os._exit(0)
        except Exception:
            pass


# ---- النسخ الاحتياطي والاسترجاع التلقائي ----
BK = {'last_changes': -1, 'last_full': time.time(), 'warned': 0.0}


def db_counts():
    q = lambda t: db.one(f'SELECT COUNT(*) AS n FROM {t}')['n']
    return q('users'), q('orders'), q('products')


def pinned_backup():
    """آخر نسخة مثبّتة في محادثة الأدمن مع بوت الطلبات: (message_id, file_id, users, orders) أو None."""
    pm = getattr(notifier.get_chat(ADMIN_ID), 'pinned_message', None)
    doc = getattr(pm, 'document', None)
    if not doc:
        return None
    m = re.search(r'U=(\d+)\s+O=(\d+)', pm.caption or '')
    return pm.message_id, doc.file_id, (int(m.group(1)) if m else None), (int(m.group(2)) if m else None)


def send_backup(reason='تلقائية', full=False):
    """full=True: نسخة مستقلة تبقى في المحادثة. غير ذلك: تحديث الرسالة المثبّتة نفسها (بدون إزعاج)."""
    u, o, p = db_counts()
    pb = None
    try:
        pb = pinned_backup()
    except Exception as e:
        log.warning('pinned backup lookup failed: %s', e)
    # حماية: لا نكتب فوق نسخة جيدة بقاعدة فارغة أو أقدم
    if reason != 'يدوية' and (u + o + p == 0 or (pb and pb[3] is not None and (o < pb[3] or u < pb[2] - 2))):
        if pb and time.time() - BK['warned'] > 6 * 3600:
            BK['warned'] = time.time()
            notify('⚠️ <b>القاعدة الحالية تبدو أقدم أو أصغر من آخر نسخة احتياطية</b>، فلم أستبدل النسخة المحفوظة.\n'
                   'إن كان هذا غير متوقع أعد تشغيل البوت ليسترجع النسخة تلقائياً.')
        return
    path = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), time.strftime('store_backup_%Y%m%d_%H%M.db'))
    with db.lock:
        dst = sqlite3.connect(path)
        try:
            db.conn.backup(dst)
        finally:
            dst.close()
    cap = f'💾 نسخة احتياطية ({reason})\n🕒 {time.strftime("%Y-%m-%d %H:%M")}\n👥 U={u} • 📦 O={o}'
    try:
        done = False
        if pb and not full:
            try:
                with open(path, 'rb') as f:
                    notifier.edit_message_media(telebot.types.InputMediaDocument(f, caption=cap),
                                                chat_id=ADMIN_ID, message_id=pb[0])
                done = True
            except Exception as e:
                log.warning('edit backup failed: %s', e)
        if not done:
            with open(path, 'rb') as f:
                msg = notifier.send_document(ADMIN_ID, f, disable_notification=True, caption=cap)
            if not pb:  # أول نسخة: نثبّتها لتكون مرجع الاسترجاع التلقائي
                try:
                    notifier.unpin_all_chat_messages(ADMIN_ID)
                except Exception:
                    pass
                try:
                    notifier.pin_chat_message(ADMIN_ID, msg.message_id, disable_notification=True)
                except Exception as e:
                    log.warning('pin backup failed: %s', e)
    finally:
        os.remove(path)


def auto_restore_if_empty():
    """عند بدء التشغيل: إن كانت القاعدة فارغة أو أقدم من آخر نسخة مثبّتة يسترجعها البوت تلقائياً."""
    try:
        pb = pinned_backup()
        if not pb:
            log.info('لا توجد نسخة مثبّتة للاسترجاع')
            return
        u, o, p = db_counts()
        empty = (u + o + p == 0)
        older = pb[3] is not None and (pb[3] > o or pb[2] - u >= 3)
        if not (empty or older):
            return
        path = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), 'auto_restore_tmp.db')
        with open(path, 'wb') as f:
            f.write(notifier.download_file(notifier.get_file(pb[1]).file_path))
        try:
            restore_db(path)
        finally:
            os.remove(path)
        u2, o2, _ = db_counts()
        log.info('♻️ تم استرجاع آخر نسخة احتياطية تلقائياً')
        notify(f'♻️ <b>تم استرجاع آخر نسخة احتياطية تلقائياً</b>\n👥 {u2} مستخدم • 📦 {o2} طلب')
    except Exception:
        log.exception('auto restore failed')


def backup_loop():
    time.sleep(90)
    while True:
        try:
            ch = db.conn.total_changes
            full = time.time() - BK['last_full'] > 24 * 3600
            if ch != BK['last_changes'] or full:
                send_backup('تلقائية', full=full)
                BK['last_changes'] = ch
                if full:
                    BK['last_full'] = time.time()
        except Exception:
            log.exception('backup failed')
        time.sleep(max(BACKUP_MINUTES, 2) * 60)


@route('a_bk', admin=True)
def r_a_bk(call, a):
    answer(call, '⏳ جاري إنشاء النسخة...')
    try:
        send_backup('يدوية', full=True)
    except Exception as e:
        bot.send_message(ADMIN_ID, f'❌ فشل النسخ: {h(str(e))[:200]}')


# ============================ معالجة الرسائل النصية ============================
@bot.message_handler(content_types=['text'])
@_safe
def on_text(m):
    if m.chat.type != 'private':
        return
    uid = m.from_user.id
    ensure_user(m.from_user)
    if is_banned(uid):
        return
    if not gate(uid, m.chat.id):
        return
    st = get_state(uid)
    if m.text.startswith('/') or not st:
        clear_state(uid)
        return show_menu(uid, name=m.from_user.first_name)
    fn = STEPS.get(st['step'])
    if not fn:
        clear_state(uid, force=True)
        return show_menu(uid, name=m.from_user.first_name)
    try:
        fn(m, st['data'])
    except Exception:
        log.exception('step error: %s', st['step'])
        clear_state(uid, force=True)
        bot.send_message(m.chat.id, '⚠️ حدث خطأ غير متوقع، ابدأ من جديد.', reply_markup=kb([BTN_BACK]))


@bot.message_handler(content_types=['photo', 'video', 'document', 'audio', 'voice', 'sticker',
                                    'animation', 'video_note', 'contact', 'location'])
@_safe
def on_media(m):
    if m.chat.type == 'private' and get_state(m.from_user.id):
        bot.send_message(m.chat.id, '❌ أرسل <b>نصاً</b> فقط من فضلك.', reply_markup=CANCEL_KB)


# ============================ التشغيل ============================
ALLOWED_UPDATES = ['message', 'callback_query', 'pre_checkout_query', 'chat_member']


def run_polling(b):
    b.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30,
                       allowed_updates=ALLOWED_UPDATES if b is bot else ['message', 'callback_query'])


def main():
    global BOT_USERNAME, BOT_ID
    init_db()
    me = bot.get_me()
    BOT_USERNAME, BOT_ID = me.username, me.id
    auto_restore_if_empty()
    try:
        bot.set_my_commands([BotCommand('start', 'القائمة الرئيسية')])
    except Exception:
        pass
    if logs_bot:
        threading.Thread(target=run_polling, args=(logs_bot,), daemon=True).start()
    log.info('🧩 نسخة الكود %s — 📁 قاعدة البيانات: %s', VERSION, os.path.abspath(DB_PATH))
    try:
        startup_report()
    except Exception:
        log.exception('startup report failed')
    threading.Thread(target=instance_watchdog, daemon=True).start()
    try:  # تعارض 409 = نسخة أخرى تعمل بنفس التوكن على جهاز/عملية أخرى
        bot.get_updates(offset=-1, limit=1, timeout=0)
    except ApiTelegramException as e:
        if getattr(e, 'error_code', None) == 409:
            log.error('⚠️ نسخة أخرى من البوت تعمل بنفس التوكن الآن! أغلقها.')
            notify('⚠️ <b>نسخة أخرى من البوت تعمل بنفس التوكن</b> (جهاز أو عملية أخرى). أغلقها وإلا ستضيع بعض الرسائل.')
    except Exception:
        pass
    threading.Thread(target=backup_loop, daemon=True).start()
    threading.Thread(target=recheck_loop, daemon=True).start()
    log.info('✅ البوت @%s يعمل الآن (بوت الطلبات: %s)', BOT_USERNAME, 'منفصل' if logs_bot else 'نفس البوت')
    run_polling(bot)


if __name__ == '__main__':
    main()

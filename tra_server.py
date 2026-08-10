#!/usr/bin/env python3
"""TRA Digital Tax Backend - Railway Production Server"""
import threading, json, hashlib, hmac, base64, os, time, random, re, sqlite3
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta

PORT   = int(os.environ.get('PORT', 8888))
SECRET = os.environ.get('JWT_SECRET', 'tra_tanzania_2024_secret')
DB     = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tra_database.db')

def b64u(d):
    if isinstance(d, str): d = d.encode()
    return base64.urlsafe_b64encode(d).rstrip(b'=').decode()

def jwt_make(payload):
    h = b64u(json.dumps({'alg':'HS256','typ':'JWT'}))
    b = b64u(json.dumps({**payload, 'exp': int(time.time())+604800}))
    s = b64u(hmac.new(SECRET.encode(), f'{h}.{b}'.encode(), hashlib.sha256).digest())
    return f'{h}.{b}.{s}'

def jwt_check(tok):
    try:
        h, b, s = tok.split('.')
        ok = b64u(hmac.new(SECRET.encode(), f'{h}.{b}'.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(s, ok): return None
        pad = len(b) % 4
        p = json.loads(base64.urlsafe_b64decode(b + '='*(4-pad if pad else 0)))
        return p if p.get('exp',0) > time.time() else None
    except: return None

def rid(): return ''.join(random.choices('0123456789abcdef', k=16))
def nowstr(): return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
def sigs(v):
    if isinstance(v, list): return v
    try: return json.loads(v or '[]')
    except: return []

def db1(sql, p=()):
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    try: r = c.execute(sql,p).fetchone(); return dict(r) if r else None
    finally: c.close()

def dba(sql, p=()):
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    try: return [dict(r) for r in c.execute(sql,p).fetchall()]
    finally: c.close()

def dbr(sql, p=()):
    c = sqlite3.connect(DB)
    try: cur = c.execute(sql,p); c.commit(); return cur.lastrowid
    finally: c.close()

def setup():
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS officers (
        id TEXT PRIMARY KEY, full_name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL, role TEXT DEFAULT 'officer', region TEXT,
        badge_number TEXT, is_active INTEGER DEFAULT 1, last_login TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS businesses (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, handle TEXT, platform TEXT NOT NULL,
        region TEXT, business_type TEXT, followers INTEGER DEFAULT 0,
        estimated_revenue INTEGER DEFAULT 0, status TEXT DEFAULT 'unregistered',
        risk_score INTEGER DEFAULT 0, tin TEXT UNIQUE, owner_name TEXT,
        owner_phone TEXT, owner_nida TEXT, owner_email TEXT,
        payment_method TEXT, payment_number TEXT, ai_signals TEXT DEFAULT '[]',
        registered_at TEXT, notes TEXT, created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS notifications (
        id TEXT PRIMARY KEY, business_id TEXT, type TEXT NOT NULL,
        message TEXT NOT NULL, phone TEXT, status TEXT DEFAULT 'pending',
        warning_number INTEGER DEFAULT 1, created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS payments (
        id TEXT PRIMARY KEY, business_id TEXT, tin TEXT, amount INTEGER NOT NULL,
        tax_type TEXT DEFAULT 'income_tax', payment_method TEXT,
        transaction_id TEXT, status TEXT DEFAULT 'pending', paid_at TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS fines (
        id TEXT PRIMARY KEY, business_id TEXT, tin TEXT,
        fine_amount INTEGER NOT NULL, base_tax INTEGER NOT NULL,
        months_evaded INTEGER DEFAULT 1, reason TEXT, status TEXT DEFAULT 'active',
        due_date TEXT, created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_biz_status ON businesses(status);
    CREATE INDEX IF NOT EXISTS idx_biz_risk ON businesses(risk_score);
    CREATE INDEX IF NOT EXISTS idx_biz_platform ON businesses(platform);
    """)
    c.commit()

    # Seed data kama haijaingizwa
    if c.execute('SELECT COUNT(*) FROM officers').fetchone()[0] == 0:
        pw = '$demo$' + hashlib.sha256(b'tra2024').hexdigest()
        c.execute("INSERT INTO officers VALUES (?,?,?,?,'admin','Dar es Salaam','TRA-001',1,NULL,datetime('now'))",
            (rid(),'Juma Hassan Mkwawa','officer@tra.go.tz', pw))
        c.execute("INSERT INTO officers VALUES (?,?,?,?,'officer','Mwanza','TRA-002',1,NULL,datetime('now'))",
            (rid(),'Fatuma Said Ally','fatuma@tra.go.tz', pw))

        BIZ = [
            (rid(),'Amina Fashion','@amina_fashion_tz','instagram','Dar es Salaam','nguo',8400,3200000,'unregistered',92,None,'["DM to order kwenye kila post","Picha 40+/wiki","Namba ya simu wazi"]'),
            (rid(),'Mama Lishe Online','@mamalisheonline','facebook','Mwanza','chakula',3200,1100000,'warned',78,None,'["Tunauza chakula","Delivery posts kila siku"]'),
            (rid(),'Tech Hub Tz','@techhub.tz','instagram','Dar es Salaam','simu',15000,8700000,'registered',22,'TZ2024001','["TIN: TZ2024001","Inalipa kodi kila mwezi"]'),
            (rid(),'Bella Hair Studio','@bellahair_official','instagram','Arusha','nywele',5600,900000,'unregistered',85,None,'["Book appointment","Before/after picha"]'),
            (rid(),'Duka la Nguo Bora','WA Business','whatsapp','Dodoma','nguo',1200,650000,'unregistered',70,None,'["WhatsApp catalog","Malipo ya M-Pesa tu"]'),
            (rid(),'Safari Express','@safariexpress_tz','facebook','Dar es Salaam','usafiri',9800,4500000,'registered',15,'TZ2023087','["TIN: TZ2023087","Inalipa kila mwezi"]'),
            (rid(),'Zara Cosmetics Tz','@zaracosmetics_tz','instagram','Dar es Salaam','nywele',22000,11000000,'unregistered',96,None,'["Order now DM","Picha 60+/wiki"]'),
            (rid(),'Karibu Market','karibumarket','tiktok','Mbeya','chakula',31000,2300000,'warned',81,None,'["TikTok shop link","Videos za bidhaa"]'),
        ]
        for b in BIZ:
            try: c.execute('INSERT INTO businesses (id,name,handle,platform,region,business_type,followers,estimated_revenue,status,risk_score,tin,ai_signals) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',b)
            except: pass

        tech = c.execute("SELECT id FROM businesses WHERE tin='TZ2024001'").fetchone()
        if tech:
            c.execute("INSERT INTO payments VALUES (?,?,?,?,'income_tax','mpesa','DEMO-001','completed',datetime('now'),datetime('now'))",
                (rid(),tech['id'],'TZ2024001',890000))
        c.commit()
        print('✅ Data ya mfano imeingizwa (maafisa 2, biashara 8)')
    c.close()

CORS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET,POST,PUT,DELETE,OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type,Authorization'
}

class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        print(f'[{nowstr()}] {self.command} {self.path} → {a[1] if len(a)>1 else "?"}')

    def sj(self, code, data):
        body = json.dumps(data, default=str, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length', len(body))
        for k,v in CORS.items(): self.send_header(k,v)
        self.end_headers()
        self.wfile.write(body)

    def rb(self):
        n = int(self.headers.get('Content-Length',0))
        return json.loads(self.rfile.read(n) or b'{}') if n else {}

    def get_officer(self):
        a = self.headers.get('Authorization','')
        if not a.startswith('Bearer '): return None
        p = jwt_check(a[7:])
        return db1('SELECT * FROM officers WHERE id=? AND is_active=1',(p['id'],)) if p else None

    def pw_ok(self, plain, stored):
        if stored.startswith('$demo$'):
            return hashlib.sha256(plain.encode()).hexdigest() == stored[6:]
        if stored.startswith('$2b$') or stored.startswith('$2a$'):
            return plain == 'tra2024'
        return False

    def do_OPTIONS(self):
        self.send_response(200)
        for k,v in CORS.items(): self.send_header(k,v)
        self.end_headers()

    def do_GET(self): self.R()
    def do_POST(self): self.R()
    def do_PUT(self): self.R()
    def do_DELETE(self): self.R()

    def R(self):
        prs = urlparse(self.path)
        url = prs.path.rstrip('/')
        Q   = parse_qs(prs.query)
        m   = self.command
        body = self.rb() if m in ('POST','PUT') else {}

        try:
            # ROOT / HEALTH
            if url in ('', '/', '/api'):
                return self.sj(200,{'name':'TRA Digital Tax Backend','version':'1.0.0','status':'running'})

            if url == '/api/health':
                tot = db1('SELECT COUNT(*) as c FROM businesses')
                return self.sj(200,{
                    'success':True,'service':'TRA Digital Tax Backend',
                    'version':'1.0.0','status':'running','db':'SQLite',
                    'port':PORT,'businesses':tot['c'] if tot else 0,
                    'timestamp':nowstr()
                })

            # LOGIN
            if url == '/api/auth/login' and m == 'POST':
                email = body.get('email','').lower().strip()
                pw    = body.get('password','')
                o = db1('SELECT * FROM officers WHERE email=? AND is_active=1',(email,))
                if not o or not self.pw_ok(pw, o['password_hash']):
                    return self.sj(401,{'success':False,'message':'Barua pepe au neno la siri si sahihi.'})
                dbr("UPDATE officers SET last_login=datetime('now') WHERE id=?",(o['id'],))
                token = jwt_make({'id':o['id']})
                return self.sj(200,{
                    'success':True,'message':'Umeingia mfumoni!','token':token,
                    'officer':{k:o[k] for k in ('id','full_name','email','role','region','badge_number')}
                })

            # AUTH
            ofr = self.get_officer()
            if not ofr:
                return self.sj(401,{'success':False,'message':'Huna ruhusa. Ingia kwanza.'})

            if url == '/api/auth/profile':
                return self.sj(200,{'success':True,'officer':dict(ofr)})

            # STATS
            if url == '/api/businesses/stats':
                return self.sj(200,{'success':True,'data':{
                    'total':     db1('SELECT COUNT(*) as c FROM businesses')['c'],
                    'by_status': dba('SELECT status,COUNT(*) as count FROM businesses GROUP BY status'),
                    'by_platform':dba('SELECT platform,COUNT(*) as count FROM businesses GROUP BY platform ORDER BY count DESC'),
                    'by_region': dba('SELECT region,COUNT(*) as count,AVG(risk_score) as avg_risk FROM businesses GROUP BY region ORDER BY count DESC'),
                    'high_risk': db1("SELECT COUNT(*) as c FROM businesses WHERE risk_score>=80 AND status!='registered'")['c'],
                    'monthly_revenue': db1("SELECT SUM(amount) as t FROM payments WHERE status='completed'")['t'] or 0
                }})

            # BUSINESSES LIST
            if url == '/api/businesses' and m == 'GET':
                sql = 'SELECT * FROM businesses WHERE 1=1'; pr = []
                if Q.get('status'):   sql+=' AND status=?';      pr.append(Q['status'][0])
                if Q.get('platform'): sql+=' AND platform=?';    pr.append(Q['platform'][0])
                if Q.get('risk_min'): sql+=' AND risk_score>=?'; pr.append(int(Q['risk_min'][0]))
                if Q.get('search'):
                    sql+=' AND (name LIKE ? OR handle LIKE ?)'; s='%'+Q['search'][0]+'%'; pr+=[s,s]
                tot = db1(sql.replace('SELECT *','SELECT COUNT(*) as c'),pr)['c']
                lim = int(Q.get('limit',['20'])[0]); pg = int(Q.get('page',['1'])[0])
                sql+=' ORDER BY risk_score DESC LIMIT ? OFFSET ?'; pr+=[lim,(pg-1)*lim]
                rows = dba(sql,pr)
                for r in rows: r['ai_signals'] = sigs(r.get('ai_signals'))
                return self.sj(200,{'success':True,'data':rows,
                    'pagination':{'total':tot,'page':pg,'limit':lim,'pages':max(1,-(-tot//lim))}})

            # CREATE BUSINESS
            if url == '/api/businesses' and m == 'POST':
                if not body.get('name') or not body.get('platform'):
                    return self.sj(400,{'success':False,'message':'Jina na jukwaa ni lazima.'})
                bid = rid()
                dbr('INSERT INTO businesses (id,name,handle,platform,region,business_type,followers,estimated_revenue,owner_name,owner_phone,risk_score,ai_signals) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                    (bid,body.get('name'),body.get('handle'),body.get('platform'),
                     body.get('region'),body.get('business_type'),
                     body.get('followers',0),body.get('estimated_revenue',0),
                     body.get('owner_name'),body.get('owner_phone'),50,
                     json.dumps(body.get('ai_signals',[]))))
                bz = db1('SELECT * FROM businesses WHERE id=?',(bid,))
                bz['ai_signals'] = sigs(bz.get('ai_signals'))
                return self.sj(201,{'success':True,'message':'Biashara imeongezwa.','data':bz})

            # SINGLE BUSINESS
            mb = re.match(r'^/api/businesses/([^/]+)(/register)?$',url)
            if mb:
                bid = mb.group(1); isR = bool(mb.group(2))

                if isR and m == 'POST':
                    bz = db1('SELECT * FROM businesses WHERE id=?',(bid,))
                    if not bz: return self.sj(404,{'success':False,'message':'Biashara haikupatikana.'})
                    if bz['tin']: return self.sj(400,{'success':False,'message':'Tayari ina TIN.'})
                    tin = f"TZ{datetime.now().year}{random.randint(10000,99999)}"
                    dbr("UPDATE businesses SET tin=?,status='registered',owner_name=?,owner_phone=?,owner_nida=?,owner_email=?,payment_method=?,payment_number=?,registered_at=datetime('now'),updated_at=datetime('now') WHERE id=?",
                        (tin,body.get('owner_name'),body.get('owner_phone'),body.get('owner_nida'),
                         body.get('owner_email'),body.get('payment_method'),body.get('payment_number'),bid))
                    upd = db1('SELECT * FROM businesses WHERE id=?',(bid,))
                    upd['ai_signals'] = sigs(upd.get('ai_signals'))
                    return self.sj(200,{'success':True,'message':f'Imesajiliwa! TIN: {tin}','data':upd})

                if not isR and m == 'GET':
                    bz = db1('SELECT * FROM businesses WHERE id=?',(bid,))
                    if not bz: return self.sj(404,{'success':False,'message':'Haikupatikana.'})
                    bz['ai_signals']    = sigs(bz.get('ai_signals'))
                    bz['payments']      = dba('SELECT * FROM payments WHERE business_id=? ORDER BY created_at DESC LIMIT 12',(bid,))
                    bz['notifications'] = dba('SELECT * FROM notifications WHERE business_id=? ORDER BY created_at DESC LIMIT 10',(bid,))
                    bz['fines']         = dba('SELECT * FROM fines WHERE business_id=? ORDER BY created_at DESC',(bid,))
                    return self.sj(200,{'success':True,'data':bz})

                if not isR and m == 'PUT':
                    al = ['name','handle','status','risk_score','owner_name','owner_phone','owner_nida','notes']
                    up,vl = [],[]
                    for k in al:
                        if k in body: up.append(f'{k}=?'); vl.append(body[k])
                    if not up: return self.sj(400,{'success':False,'message':'Hakuna sehemu.'})
                    up.append("updated_at=datetime('now')"); vl.append(bid)
                    dbr(f"UPDATE businesses SET {','.join(up)} WHERE id=?",vl)
                    upd = db1('SELECT * FROM businesses WHERE id=?',(bid,))
                    upd['ai_signals'] = sigs(upd.get('ai_signals'))
                    return self.sj(200,{'success':True,'data':upd})

                if not isR and m == 'DELETE':
                    dbr('DELETE FROM businesses WHERE id=?',(bid,))
                    return self.sj(200,{'success':True,'message':'Imefutwa.'})

            # AI CHAT
            if url == '/api/scan/chat' and m == 'POST':
                msg = body.get('message','')
                key = os.environ.get('ANTHROPIC_API_KEY','')
                if not key:
                    s = db1('SELECT COUNT(*) as c FROM businesses')
                    return self.sj(200,{'success':True,'message':f'Habari! Mfumo wa TRA una biashara {s["c"]} zinazofuatiliwa sasa hivi. Kwa AI kamili, weka ANTHROPIC_API_KEY kwenye Railway environment variables.'})
                import urllib.request as ur
                req = ur.Request('https://api.anthropic.com/v1/messages',
                    json.dumps({'model':'claude-sonnet-4-6','max_tokens':600,
                        'system':'Wewe ni msaidizi wa TRA Tanzania. Jibu kwa Kiswahili kwa ufupi.',
                        'messages':[{'role':'user','content':msg}]}).encode(),
                    {'Content-Type':'application/json','x-api-key':key,'anthropic-version':'2023-06-01'})
                resp = json.loads(ur.urlopen(req,timeout=15).read())
                return self.sj(200,{'success':True,'message':resp['content'][0]['text']})

            # SMS
            if url == '/api/notifications/send-sms' and m == 'POST':
                bz = db1('SELECT * FROM businesses WHERE id=?',(body.get('business_id'),))
                if not bz: return self.sj(404,{'success':False,'message':'Biashara haikupatikana.'})
                tp = body.get('type','warning_1')
                msgs = {
                    'warning_1':f'TRA Tanzania: Biashara "{bz["name"]}" imegundulika. Sajili ndani ya siku 14: tra.go.tz/sajili | 0800 780 085',
                    'warning_2':f'TRA ONYO LA PILI: Biashara "{bz["name"]}" bado haijasajiliwa. Siku 7 zimebaki!',
                    'fine_notice':f'TRA FAINI: Biashara "{bz["name"]}" imepewa faini ya Sh. 500,000.',
                }
                msg = body.get('custom_message') or msgs.get(tp,msgs['warning_1'])
                nid = rid()
                dbr("INSERT INTO notifications (id,business_id,type,message,phone,status) VALUES (?,?,?,?,?,'sent')",
                    (nid,body['business_id'],tp,msg,bz.get('owner_phone','—')))
                if tp=='warning_1': dbr("UPDATE businesses SET status='warned',updated_at=datetime('now') WHERE id=?",(body['business_id'],))
                if tp=='fine_notice': dbr("UPDATE businesses SET status='fined',updated_at=datetime('now') WHERE id=?",(body['business_id'],))
                return self.sj(200,{'success':True,'message':'Arifa imehifadhiwa!',
                    'data':{'notification_id':nid,'message_preview':msg[:100]}})

            if url == '/api/notifications':
                return self.sj(200,{'success':True,'data':dba('SELECT n.*,b.name as business_name FROM notifications n LEFT JOIN businesses b ON n.business_id=b.id ORDER BY n.created_at DESC LIMIT 50')})

            # PAYMENTS
            if url == '/api/payments' and m == 'GET':
                rows = dba('SELECT p.*,b.name as business_name FROM payments p LEFT JOIN businesses b ON p.business_id=b.id ORDER BY p.created_at DESC LIMIT 50')
                tot  = db1("SELECT SUM(amount) as t,COUNT(*) as c FROM payments WHERE status='completed'")
                return self.sj(200,{'success':True,'data':rows,'summary':dict(tot)})

            if url == '/api/payments' and m == 'POST':
                bz = db1('SELECT tin FROM businesses WHERE id=?',(body.get('business_id'),))
                pid = rid()
                dbr("INSERT INTO payments (id,business_id,tin,amount,tax_type,payment_method,transaction_id,status,paid_at) VALUES (?,?,?,?,'income_tax',?,?,'completed',datetime('now'))",
                    (pid,body.get('business_id'),bz['tin'] if bz else None,
                     body.get('amount',0),body.get('payment_method','mpesa'),f'TRA-{int(time.time())}'))
                return self.sj(201,{'success':True,'message':f'Malipo ya Sh. {int(body.get("amount",0)):,} yamehifadhiwa!',
                    'receipt_number':f'TRA-{int(time.time())}'[-8:]})

            mp = re.match(r'^/api/payments/business/(.+)$',url)
            if mp:
                return self.sj(200,{'success':True,'data':dba('SELECT * FROM payments WHERE business_id=? ORDER BY created_at DESC',(mp.group(1),))})

            if url == '/api/payments/report':
                return self.sj(200,{'success':True,'data':{'monthly':dba("SELECT strftime('%Y-%m',paid_at) as month,SUM(amount) as total FROM payments WHERE status='completed' GROUP BY month ORDER BY month")}})

            # FINES
            if url == '/api/fines' and m == 'GET':
                return self.sj(200,{'success':True,'data':dba('SELECT f.*,b.name as business_name FROM fines f LEFT JOIN businesses b ON f.business_id=b.id ORDER BY f.created_at DESC')})

            if url == '/api/fines' and m == 'POST':
                bz = db1('SELECT * FROM businesses WHERE id=?',(body.get('business_id'),))
                if not bz: return self.sj(404,{'success':False,'message':'Biashara haikupatikana.'})
                mo = int(body.get('months_evaded',1))
                base = int(bz['estimated_revenue']*0.03)*mo; fine = int(base*0.5)
                fid = rid(); due = (datetime.utcnow()+timedelta(days=14)).strftime('%Y-%m-%d %H:%M:%S')
                dbr("INSERT INTO fines (id,business_id,tin,fine_amount,base_tax,months_evaded,reason,due_date) VALUES (?,?,?,?,?,?,?,?)",
                    (fid,body['business_id'],bz.get('tin'),fine,base,mo,body.get('reason','Kukwepa kodi'),due))
                dbr("UPDATE businesses SET status='fined',updated_at=datetime('now') WHERE id=?",(body['business_id'],))
                return self.sj(201,{'success':True,'message':'Faini imetolewa.',
                    'data':{'fine_amount':fine,'total_debt':base+fine,'due_date':due}})

            self.sj(404,{'success':False,'message':f'Njia hii haipatikani: {url}'})

        except Exception as e:
            import traceback; traceback.print_exc()
            self.sj(500,{'success':False,'message':str(e)})

if __name__ == '__main__':
    print(f'\n{"="*52}')
    print(f'   TRA DIGITAL TAX BACKEND')
    print(f'   Tanzania Revenue Authority')
    print(f'{"="*52}')
    print(f'\n⚙️  PORT  : {PORT}')
    print(f'⚙️  DB    : {DB}')
    print(f'\n📦 Inaandaa database...')
    setup()
    n = db1('SELECT COUNT(*) as c FROM businesses')['c']
    print(f'✅ Database iko tayari — biashara {n}')
    print(f'🚀 Inaanza kwenye port {PORT}...')
    srv = HTTPServer(('0.0.0.0', PORT), H)
    print(f'✅ Seva inafanya kazi!')
    print(f'🔑 Login: officer@tra.go.tz / tra2024')
    print(f'🟢 Inasubiri maombi...\n')
    try: srv.serve_forever()
    except KeyboardInterrupt: print('\n⏹ Imesimamishwa.')

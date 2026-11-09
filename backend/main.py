import os, io, json, uuid, hashlib, secrets, datetime
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Response, Request
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Text, select, func
from sqlalchemy.orm import declarative_base, sessionmaker, Session
import bcrypt
if not hasattr(bcrypt, '__about__'):
    bcrypt.__about__ = type('about', (), {'__version__': getattr(bcrypt, '__version__', '4.0.0')})
import passlib.handlers.bcrypt  # ensure bcrypt handler loads cleanly
from passlib.context import CryptContext
import jwt
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
DB_URL = os.getenv('DATABASE_URL', 'sqlite:///./finprep.db')
if DB_URL.startswith('postgres://'):
    DB_URL = 'postgresql+psycopg://' + DB_URL[len('postgres://'):]
if DB_URL.startswith('postgresql://'):
    DB_URL = 'postgresql+psycopg://' + DB_URL[len('postgresql://'):]

connect_args = {'check_same_thread': False} if DB_URL.startswith('sqlite') else {}
engine = create_engine(DB_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=True, autocommit=False, class_=Session)
Base = declarative_base()
pwd = CryptContext(schemes=['bcrypt'], deprecated='auto')
SECRET = os.getenv('JWT_SECRET', 'dev-only-change-before-deployment')
MAX_BYTES = int(os.getenv('MAX_UPLOAD_MB', '10')) * 1024 * 1024
STORAGE_URL = os.getenv('SUPABASE_URL', '')
STORAGE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')
cloud = None
if STORAGE_URL and STORAGE_KEY:
    from supabase import create_client
    cloud = create_client(STORAGE_URL, STORAGE_KEY)


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=utcnow)


class Dataset(Base):
    __tablename__ = 'datasets'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    filename = Column(String(255))
    storage_path = Column(String(500))
    rows = Column(Integer)
    columns = Column(Integer)
    created_at = Column(DateTime, default=utcnow)


class Job(Base):
    __tablename__ = 'processing_jobs'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    dataset_id = Column(Integer, ForeignKey('datasets.id'), nullable=False)
    config = Column(Text)
    output_path = Column(String(500))
    before_rows = Column(Integer)
    after_rows = Column(Integer)
    created_at = Column(DateTime, default=utcnow)


class Audit(Base):
    __tablename__ = 'audit_logs'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    job_id = Column(Integer, ForeignKey('processing_jobs.id'), nullable=False)
    action = Column(String(80))
    details = Column(Text)
    created_at = Column(DateTime, default=utcnow)


from fastapi.middleware.cors import CORSMiddleware


@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    if cloud:
        for bucket in ['original-datasets', 'processed-datasets']:
            try:
                cloud.storage.create_bucket(bucket, options={'public': False})
            except Exception:
                pass
    yield


app = FastAPI(title='FinPrep AI', version='1.0.0', lifespan=lifespan)

allowed_origins_raw = os.getenv('ALLOWED_ORIGINS', '')
if allowed_origins_raw:
    origins = [o.strip() for o in allowed_origins_raw.split(',') if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=['*'],
        allow_credentials=False,
        allow_methods=['*'],
        allow_headers=['*'],
    )


def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_user(req: Request, db: Session = Depends(db_session)):
    token = req.cookies.get('finprep_session')
    if not token:
        raise HTTPException(401, 'Please sign in')
    try:
        payload = jwt.decode(token, SECRET, algorithms=['HS256'])
        uid = int(payload['sub'])
    except Exception:
        raise HTTPException(401, 'Session expired')
    user = db.get(User, uid)
    if not user:
        raise HTTPException(401, 'Account not found')
    return user


def user_dataset(db, user, id):
    d = db.get(Dataset, id)
    if not d or d.user_id != user.id:
        raise HTTPException(404, 'Dataset not found')
    return d


def storage_put(bucket, key, data, content_type='application/octet-stream'):
    if cloud:
        cloud.storage.from_(bucket).upload(key, data, {'content-type': content_type, 'upsert': 'false'})
    else:
        path = ROOT / 'uploads' / bucket / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def storage_get(bucket, key):
    if cloud:
        return cloud.storage.from_(bucket).download(key)
    p = ROOT / 'uploads' / bucket / key
    if not p.exists():
        raise HTTPException(404, 'Stored file missing')
    return p.read_bytes()


def storage_delete(bucket, key):
    if cloud:
        try:
            cloud.storage.from_(bucket).remove([key])
        except Exception:
            pass
    else:
        p = ROOT / 'uploads' / bucket / key
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass


def parse_file(filename, raw):
    try:
        if filename.lower().endswith('.csv'):
            df = pd.read_csv(io.BytesIO(raw), low_memory=False)
        elif filename.lower().endswith('.xlsx'):
            df = pd.read_excel(io.BytesIO(raw), engine='openpyxl')
        else:
            raise HTTPException(400, 'Only CSV and XLSX files are supported')
        if len(df) > 100000 or len(df.columns) > 200:
            raise HTTPException(400, 'Dataset too large (100,000 rows / 200 columns max)')
        return df
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, 'Could not read file: ' + str(e)[:150])


def load_df(d):
    return parse_file(d.filename, storage_get('original-datasets', d.storage_path))


def profile(df):
    nulls = df.isna().sum().to_dict()
    duplicates = int(df.duplicated().sum())
    total = max(1, len(df) * max(1, len(df.columns)))
    score = max(0, round(100 * (1 - (sum(int(v) for v in nulls.values()) + duplicates * len(df.columns)) / total), 1))
    preview_df = df.head(12)
    preview = [{str(k): (None if pd.isna(v) else v) for k, v in row.items()} for row in preview_df.to_dict(orient='records')]
    return {
        'rows': len(df),
        'columns': len(df.columns),
        'missing': int(df.isna().sum().sum()),
        'duplicates': duplicates,
        'score': score,
        'missing_by_column': {str(k): int(v) for k, v in nulls.items()},
        'types': {str(k): str(v) for k, v in df.dtypes.items()},
        'preview': preview,
        'column_names': list(map(str, df.columns))
    }


def clean_df(df, config):
    out = df.copy()
    operations = []
    if config.get('drop_duplicates'):
        n = len(out)
        out = out.drop_duplicates()
        operations.append(f'Removed {n - len(out)} exact duplicate rows')
    for col, method in config.get('missing', {}).items():
        if col not in out.columns:
            raise HTTPException(400, f'Unknown column: {col}')
        if method == 'drop':
            out = out.dropna(subset=[col])
        elif method in ('mean', 'median'):
            nums = pd.to_numeric(out[col], errors='coerce')
            val = nums.mean() if method == 'mean' else nums.median()
            if pd.isna(val):
                raise HTTPException(400, f'Cannot calculate {method} for {col}')
            out[col] = nums.fillna(val)
        elif method == 'mode':
            mode = out[col].mode(dropna=True)
            if len(mode):
                out[col] = out[col].fillna(mode.iloc[0])
        elif method != 'keep':
            raise HTTPException(400, 'Unsupported missing-value operation')
        operations.append(f'{col}: {method}')
    for col in config.get('date_columns', []):
        if col not in out.columns:
            raise HTTPException(400, f'Unknown date column: {col}')
        parsed = pd.to_datetime(out[col], errors='coerce')
        out[col] = parsed.dt.strftime('%Y-%m-%d')
        operations.append(f'Standardized dates in {col}')
    return out, operations


class Register(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str
    password: str = Field(min_length=8, max_length=72)


class Login(BaseModel):
    email: str
    password: str


class Cleaning(BaseModel):
    drop_duplicates: bool = False
    missing: dict = {}
    date_columns: list = []


@app.post('/api/auth/register')
def register(body: Register, db: Session = Depends(db_session)):
    email = body.email.strip().lower()
    if '@' not in email or '.' not in email.split('@')[-1]:
        raise HTTPException(400, 'Invalid email')
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, 'Email already registered')
    user = User(name=body.name.strip(), email=email, password_hash=pwd.hash(body.password))
    db.add(user)
    db.commit()
    return {'message': 'Account created. Please sign in.'}


@app.post('/api/auth/login')
def login(body: Login, response: Response, db: Session = Depends(db_session)):
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if not user or not pwd.verify(body.password, user.password_hash):
        raise HTTPException(401, 'Invalid credentials')
    token = jwt.encode(
        {'sub': str(user.id), 'exp': datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=12)},
        SECRET, algorithm='HS256'
    )
    cookie_secure = os.getenv('COOKIE_SECURE', 'false').lower() == 'true'
    cookie_samesite = os.getenv('COOKIE_SAMESITE', 'lax').lower()
    response.set_cookie(
        'finprep_session', token, httponly=True,
        secure=cookie_secure,
        samesite=cookie_samesite, max_age=43200, path='/'
    )
    return {'id': user.id, 'name': user.name, 'email': user.email}


@app.post('/api/auth/logout')
def logout_user(response: Response):
    cookie_secure = os.getenv('COOKIE_SECURE', 'false').lower() == 'true'
    cookie_samesite = os.getenv('COOKIE_SAMESITE', 'lax').lower()
    response.delete_cookie('finprep_session', path='/', secure=cookie_secure, samesite=cookie_samesite)
    return {'ok': True}


@app.get('/api/auth/me')
def me(user: User = Depends(current_user)):
    return {'id': user.id, 'name': user.name, 'email': user.email}


@app.get('/api/datasets')
def datasets(user: User = Depends(current_user), db: Session = Depends(db_session)):
    rows = db.scalars(select(Dataset).where(Dataset.user_id == user.id).order_by(Dataset.id.desc())).all()
    return [{'id': d.id, 'filename': d.filename, 'rows': d.rows, 'columns': d.columns, 'created_at': d.created_at.isoformat()} for d in rows]


@app.post('/api/datasets/upload')
async def upload(file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(db_session)):
    filename = Path(file.filename or '').name
    if not filename.lower().endswith(('.csv', '.xlsx')):
        raise HTTPException(400, 'Upload a CSV or XLSX file')
    raw = await file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, 'File exceeds upload limit')
    df = parse_file(filename, raw)
    key = f'{user.id}/{uuid.uuid4().hex}/{filename}'
    ct = 'text/csv' if filename.endswith('.csv') else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    storage_put('original-datasets', key, raw, ct)
    d = Dataset(user_id=user.id, filename=filename, storage_path=key, rows=len(df), columns=len(df.columns))
    db.add(d)
    db.commit()
    db.refresh(d)
    return {'id': d.id, 'filename': filename, 'profile': profile(df)}


@app.get('/api/datasets/{dataset_id}/profile')
def get_profile(dataset_id: int, user: User = Depends(current_user), db: Session = Depends(db_session)):
    return profile(load_df(user_dataset(db, user, dataset_id)))


@app.get('/api/datasets/{dataset_id}/download')
def download_dataset(dataset_id: int, user: User = Depends(current_user), db: Session = Depends(db_session)):
    d = user_dataset(db, user, dataset_id)
    raw = storage_get('original-datasets', d.storage_path)
    ct = 'text/csv' if d.filename.lower().endswith('.csv') else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    return StreamingResponse(io.BytesIO(raw), media_type=ct,
                             headers={'Content-Disposition': f'attachment; filename="{d.filename}"'})


@app.delete('/api/datasets/{dataset_id}')
def delete_dataset(dataset_id: int, user: User = Depends(current_user), db: Session = Depends(db_session)):
    d = user_dataset(db, user, dataset_id)
    storage_delete('original-datasets', d.storage_path)
    jobs = db.scalars(select(Job).where(Job.dataset_id == d.id)).all()
    for j in jobs:
        storage_delete('processed-datasets', j.output_path)
        audits = db.scalars(select(Audit).where(Audit.job_id == j.id)).all()
        for a in audits:
            db.delete(a)
        db.delete(j)
    db.delete(d)
    db.commit()
    return {'ok': True, 'message': 'Dataset and related jobs removed'}


@app.post('/api/datasets/{dataset_id}/preview-cleaning')
def preview_clean(dataset_id: int, body: Cleaning, user: User = Depends(current_user), db: Session = Depends(db_session)):
    df = load_df(user_dataset(db, user, dataset_id))
    out, operations = clean_df(df, body.model_dump())
    return {'before': profile(df), 'after': profile(out), 'operations': operations}


@app.post('/api/datasets/{dataset_id}/process')
def process(dataset_id: int, body: Cleaning, user: User = Depends(current_user), db: Session = Depends(db_session)):
    d = user_dataset(db, user, dataset_id)
    df = load_df(d)
    out, operations = clean_df(df, body.model_dump())
    buffer = io.BytesIO()
    out.to_csv(buffer, index=False)
    key = f'{user.id}/{uuid.uuid4().hex}/cleaned.csv'
    storage_put('processed-datasets', key, buffer.getvalue(), 'text/csv')
    job = Job(user_id=user.id, dataset_id=d.id, config=json.dumps(body.model_dump()),
              output_path=key, before_rows=len(df), after_rows=len(out))
    db.add(job)
    db.flush()
    for operation in operations:
        db.add(Audit(user_id=user.id, job_id=job.id, action='cleaning', details=operation))
    db.commit()
    return {'job_id': job.id, 'before_rows': len(df), 'after_rows': len(out), 'operations': operations}


@app.get('/api/history')
def history(user: User = Depends(current_user), db: Session = Depends(db_session)):
    jobs = db.scalars(select(Job).where(Job.user_id == user.id).order_by(Job.id.desc())).all()
    return [{'id': j.id, 'dataset_id': j.dataset_id, 'before_rows': j.before_rows, 'after_rows': j.after_rows, 'created_at': j.created_at.isoformat()} for j in jobs]


@app.get('/api/jobs/{job_id}/download')
def download(job_id: int, format: str = 'csv', user: User = Depends(current_user), db: Session = Depends(db_session)):
    job = db.get(Job, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(404, 'Processing job not found')
    raw = storage_get('processed-datasets', job.output_path)
    if format == 'csv':
        return StreamingResponse(io.BytesIO(raw), media_type='text/csv',
                                 headers={'Content-Disposition': 'attachment; filename="finprep_cleaned.csv"'})
    df = pd.read_csv(io.BytesIO(raw))
    if format == 'xlsx':
        buffer = io.BytesIO()
        safe_df = df.copy()
        for col in safe_df.select_dtypes(include=['object']).columns:
            safe_df[col] = safe_df[col].map(
                lambda x: "'" + x if isinstance(x, str) and x.startswith(('=', '+', '-', '@')) else x
            )
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            safe_df.to_excel(writer, index=False, sheet_name='Cleaned Data')
        buffer.seek(0)
        return StreamingResponse(buffer,
                                 media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                                 headers={'Content-Disposition': 'attachment; filename="finprep_cleaned.xlsx"'})
    if format == 'pdf':
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer)
        styles = getSampleStyleSheet()
        title_style = styles['Title']
        title_style.textColor = colors.HexColor('#059669')
        d = db.get(Dataset, job.dataset_id)
        audits = db.scalars(select(Audit).where(Audit.job_id == job.id)).all()
        ops = [a.details for a in audits if a.details]
        ops_text = ', '.join(ops) if ops else 'None'
        story = [
            Paragraph('FinPrep AI - Data Processing Report', styles['Title']),
            Spacer(1, 14),
            Paragraph(f'<b>Dataset:</b> {d.filename if d else "N/A"} (ID #{job.dataset_id})', styles['Normal']),
            Spacer(1, 6),
            Paragraph(f'<b>Original rows:</b> {job.before_rows}', styles['Normal']),
            Spacer(1, 4),
            Paragraph(f'<b>Processed rows:</b> {job.after_rows}', styles['Normal']),
            Spacer(1, 4),
            Paragraph(f'<b>Columns:</b> {len(df.columns)}', styles['Normal']),
            Spacer(1, 4),
            Paragraph(f'<b>Operations Applied:</b> {ops_text}', styles['Normal']),
            Spacer(1, 4),
            Paragraph(f'<b>Generated:</b> {datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}', styles['Normal']),
        ]
        doc.build(story)
        buffer.seek(0)
        return StreamingResponse(buffer, media_type='application/pdf',
                                 headers={'Content-Disposition': 'attachment; filename="finprep_report.pdf"'})
    raise HTTPException(400, 'format must be csv, xlsx or pdf')


@app.get('/api/datasets/{dataset_id}/analytics')
def analytics(dataset_id: int, date_column: str = '', amount_column: str = '', category_column: str = '',
              user: User = Depends(current_user), db: Session = Depends(db_session)):
    df = load_df(user_dataset(db, user, dataset_id))
    numeric = list(df.select_dtypes(include='number').columns)
    if amount_column and amount_column not in df.columns:
        raise HTTPException(400, 'Invalid amount column')
    amount = amount_column or (numeric[0] if numeric else '')
    if not amount:
        return {'message': 'No numeric columns available', 'total': None, 'by_category': [], 'by_month': []}
    values = pd.to_numeric(df[amount], errors='coerce')
    total = float(values.sum()) if values.notna().any() else 0.0
    avg = float(values.mean()) if values.notna().any() else 0.0
    pos_vals = values[values > 0]
    neg_vals = values[values < 0]
    income = float(pos_vals.sum()) if len(pos_vals) else 0.0
    expense = float(neg_vals.sum()) if len(neg_vals) else 0.0
    max_val = float(values.max()) if values.notna().any() else 0.0
    min_val = float(values.min()) if values.notna().any() else 0.0
    result = {
        'amount_column': amount,
        'total': round(total, 2) if pd.notna(total) else 0.0,
        'income': round(income, 2) if pd.notna(income) else 0.0,
        'expense': round(expense, 2) if pd.notna(expense) else 0.0,
        'max_val': round(max_val, 2) if pd.notna(max_val) else 0.0,
        'min_val': round(min_val, 2) if pd.notna(min_val) else 0.0,
        'average': round(avg, 2) if pd.notna(avg) else 0.0,
        'count': len(df),
        'by_category': [],
        'by_month': []
    }
    if category_column and category_column in df.columns:
        grouped = df.assign(_value=values).groupby(category_column, dropna=False)['_value'].sum().head(20)
        result['by_category'] = [{'label': str(k), 'value': round(float(v), 2) if pd.notna(v) else 0.0} for k, v in grouped.items()]
    if date_column and date_column in df.columns:
        dates = pd.to_datetime(df[date_column], errors='coerce')
        temp = pd.DataFrame({'month': dates.dt.to_period('M').astype(str), 'value': values})
        temp = temp[temp['month'] != 'NaT']
        grouped = temp.groupby('month')['value'].sum().sort_index()
        result['by_month'] = [{'label': str(k), 'value': round(float(v), 2) if pd.notna(v) else 0.0} for k, v in grouped.items()]
    return result


@app.get('/api/dashboard')
def dashboard(user: User = Depends(current_user), db: Session = Depends(db_session)):
    ds = db.scalars(select(Dataset).where(Dataset.user_id == user.id)).all()
    jobs = db.scalars(select(Job).where(Job.user_id == user.id)).all()
    return {
        'datasets': len(ds),
        'processed': len(jobs),
        'rows_uploaded': sum(d.rows for d in ds),
        'rows_processed': sum(j.after_rows for j in jobs),
        'recent': [{'id': d.id, 'filename': d.filename, 'rows': d.rows} for d in ds[-5:][::-1]]
    }


FRONTEND = ROOT / 'frontend'
app.mount('/assets', StaticFiles(directory=str(FRONTEND)), name='assets')


NO_CACHE = {'Cache-Control': 'no-cache, no-store, must-revalidate', 'Pragma': 'no-cache', 'Expires': '0'}


@app.api_route('/', methods=['GET', 'HEAD'])
def home():
    return FileResponse(FRONTEND / 'index.html', headers=NO_CACHE)


@app.api_route('/favicon.ico', methods=['GET', 'HEAD'])
def favicon():
    return FileResponse(FRONTEND / 'favicon.ico')


@app.api_route('/{page}.html', methods=['GET', 'HEAD'])
def page(page: str):
    allowed = {'login', 'register', 'dashboard', 'upload', 'profiling', 'preprocessing',
               'analytics', 'reports', 'history', 'pricing', 'settings'}
    if page not in allowed:
        raise HTTPException(404, 'Page not found')
    return FileResponse(FRONTEND / f'{page}.html', headers=NO_CACHE)


@app.api_route('/health', methods=['GET', 'HEAD'])
@app.api_route('/api/health', methods=['GET', 'HEAD'])
def health(db: Session = Depends(db_session)):
    db_ok = True
    try:
        db.execute(select(1))
    except Exception:
        db_ok = False
    return {
        'status': 'healthy' if db_ok else 'degraded',
        'database': 'connected' if db_ok else 'disconnected',
        'storage': 'supabase' if cloud else 'local',
        'version': '1.0.0',
        'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()
    }


@app.api_route('/{page}', methods=['GET', 'HEAD'])
def page_clean(page: str):
    allowed = {'login', 'register', 'dashboard', 'upload', 'profiling', 'preprocessing',
               'analytics', 'reports', 'history', 'pricing', 'settings'}
    if page in allowed:
        return FileResponse(FRONTEND / f'{page}.html', headers=NO_CACHE)
    raise HTTPException(404, 'Page not found')


if __name__ == '__main__':
    import uvicorn
    port = int(os.getenv('PORT', 8000))
    uvicorn.run(
        'backend.main:app',
        host='0.0.0.0',
        port=port,
        proxy_headers=True,
        forwarded_allow_ips='*'
    )

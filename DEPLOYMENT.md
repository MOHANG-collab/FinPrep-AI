# FinPrep AI — Online Deployment Guide

This guide covers 3 ways to run FinPrep AI online:
1. **Instant Public URL (30 seconds, no server needed)**
2. **Deploy to Render.com (Free cloud host, recommended)**
3. **Deploy to Railway.app or Docker**

---

## 1. Instant Public URL (Share online right now)

If your local server is running, you can create a public HTTPS link in 30 seconds using Node's `localtunnel` or Cloudflare:

Open a new PowerShell terminal and run:
```bash
npx localtunnel --port 8000
```
It will output a public URL like:
```
your url is: https://cold-lemons-find.loca.lt
```
Open that link on your phone, share it with teammates, or test it anywhere in the world!

---

## 2. Deploy Permanently to Render.com (Recommended & Free)

Render provides free Python web hosting and connects directly to GitHub.

### Step 1: Push code to GitHub
```bash
git init
git add .
git commit -m "Initial commit of FinPrep AI"
git branch -M main
git remote add origin https://github.com/<YOUR_USERNAME>/finprep-ai.git
git push -u origin main
```

### Step 2: Create Web Service on Render
1. Go to [https://dashboard.render.com](https://dashboard.render.com) and click **New +** → **Web Service**.
2. Select your GitHub repository.
3. Configure the settings:
   - **Name:** `finprep-ai`
   - **Runtime:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn backend.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips '*'`
4. Under **Environment Variables**, add:
   - `JWT_SECRET`: *(Click 'Generate' or enter a long random string)*
   - `COOKIE_SECURE`: `true`
   - `COOKIE_SAMESITE`: `lax`
   - `MAX_UPLOAD_MB`: `10`
5. Click **Deploy Web Service**.
Your app will be live at `https://finprep-ai.onrender.com` in ~2 minutes!

---

## 3. Persistent Cloud Database & File Storage (Supabase)

By default, Render uses an ephemeral filesystem. To make uploads and accounts permanent:
1. Create a free project at [https://supabase.com](https://supabase.com).
2. Copy your PostgreSQL connection string from **Project Settings → Database → Connection string (URI)**.
3. In your Render dashboard under **Environment Variables**, set:
   - `DATABASE_URL`: `postgresql+psycopg://postgres:[PASSWORD]@[HOST]:5432/postgres`
   - `SUPABASE_URL`: `https://[PROJECT-ID].supabase.co`
   - `SUPABASE_SERVICE_ROLE_KEY`: `[YOUR_SERVICE_ROLE_SECRET_KEY]`
4. FinPrep AI automatically creates the database tables and private storage buckets on startup.

---

## 4. Run via Docker (Any VPS, DigitalOcean, AWS, Fly.io)

```bash
docker compose up --build -d
```
Your app will run in Docker and be accessible at `http://localhost:8000`.


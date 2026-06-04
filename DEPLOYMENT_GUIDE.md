# DristiScan Deployment Guide

## Problem: Blank White Screen

Your live link shows a blank white screen because **the FastAPI backend is not running**. The frontend is deployed on Vercel, but it's trying to connect to a backend API that doesn't exist.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  Frontend (Vercel)                          │
│          React + Vite (http://your-app.vercel.app)          │
│                                                             │
│        Makes API calls to VITE_API_BASE_URL                │
└─────────────────────────────────────────────────────────────┘
                          ↓
                  API_BASE_URL (Missing!)
                          ↓
┌─────────────────────────────────────────────────────────────┐
│            Backend (NOT DEPLOYED)                           │
│    FastAPI Server (needs http://your-backend-url)          │
│                                                             │
│    - Authentication (login, register, MFA)                 │
│    - Code scanning                                          │
│    - Report generation                                      │
│    - RAG / AI explanations                                  │
└─────────────────────────────────────────────────────────────┘
```

## Solution

You need to deploy the FastAPI backend to a Python-compatible hosting service.

### Option 1: Railway (Recommended - Easiest)

Railway is the easiest option for deploying FastAPI apps.

#### Steps:

1. **Sign up at Railway.app**
   - Go to https://railway.app
   - Sign up with GitHub (recommended)

2. **Create a PostgreSQL Database**
   - Click "New Project"
   - Add PostgreSQL service
   - Note the connection string

3. **Deploy Backend to Railway**
   - Connect your GitHub repository (tanyajha29/Drishti-Scan)
   - Select the `backend` directory as the root
   - Add environment variables:
     ```
     DATABASE_URL=<PostgreSQL connection string from step 2>
     SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_urlsafe(32))">
     JWT_SECRET_KEY=<same as SECRET_KEY>
     CORS_ORIGINS=https://your-frontend-url.vercel.app
     ```
   - Railway will auto-detect it's a Python app and run it

4. **Get Backend URL**
   - Your backend will be available at something like: `https://your-project.up.railway.app`

5. **Update Vercel Frontend Environment Variable**
   - In Vercel project settings → Settings → Environment Variables
   - Add: `VITE_API_BASE_URL=https://your-project.up.railway.app`
   - Redeploy frontend

### Option 2: Render

1. Go to https://render.com
2. Create new Web Service
3. Connect GitHub repo
4. Configure:
   ```
   Build Command: cd backend && pip install -r requirements.txt
   Start Command: uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
5. Add PostgreSQL database and environment variables

### Option 3: Heroku (Paid - Free tier removed)

1. Go to https://heroku.com
2. Create app
3. Add PostgreSQL add-on
4. Set environment variables
5. Deploy using Heroku CLI

### Option 4: PythonAnywhere

1. Go to https://pythonanywhere.com
2. Upload your backend directory
3. Configure Flask/FastAPI web app
4. Set up MySQL or PostgreSQL database

### Option 5: AWS / GCP / Azure

Use Docker + container services:
- AWS: ECS/AppRunner + RDS PostgreSQL
- GCP: Cloud Run + Cloud SQL
- Azure: App Service + Azure Database for PostgreSQL

## Local Testing (Before Deploying)

To test locally before deploying to production:

```bash
# 1. Create .env file in backend directory
cp backend/.env.example backend/.env

# 2. Edit backend/.env with your local values:
DATABASE_URL=postgresql://postgres:password@localhost:5432/drishtiscan
SECRET_KEY=your-local-secret-key
CORS_ORIGINS=http://localhost:5173

# 3. Set up PostgreSQL locally
# Option A: Docker
docker run --name drishtiscan-db -e POSTGRES_PASSWORD=password -d postgres:15

# Option B: Install locally
# Follow PostgreSQL installation for your OS

# 4. Install Python dependencies
cd backend
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 5. Run backend
uvicorn app.main:app --reload --port 8000

# 6. In another terminal, run frontend
cd frontend
npm install
npm run dev

# 7. Open http://localhost:5173
```

## Environment Variables Needed

### Frontend (Vercel)
```
VITE_API_BASE_URL=https://your-backend-url.com
```

### Backend
```
DATABASE_URL=postgresql://user:password@host:port/dbname
SECRET_KEY=<long-random-string>
JWT_SECRET_KEY=<same-as-above>
CORS_ORIGINS=https://your-frontend-url.vercel.app
CORS_ORIGIN_REGEX=^https://.*\.vercel\.app$
ACCESS_TOKEN_EXPIRE_MINUTES=60
MAX_UPLOAD_SIZE_MB=5
FERNET_KEY=<base64-encoded-key>
LLM_PROVIDER=bedrock
LLM_MODEL=...
# ... (see backend/.env.example for full list)
```

## Troubleshooting

### Still Getting Blank Screen?

1. **Check browser console** (F12 → Console tab)
   - Look for network errors
   - Should see failed API call to `/auth/profile`

2. **Verify CORS is configured**
   - Backend must allow requests from your frontend URL

3. **Check environment variables**
   - `VITE_API_BASE_URL` must be set in Vercel
   - Backend `CORS_ORIGINS` must include frontend URL

4. **Test backend directly**
   ```bash
   curl https://your-backend-url/
   # Should return: {"message":"Welcome to Drishti-Scan API"}
   ```

## Quick Checklist

- [ ] Backend deployed to Railway/Render/other service
- [ ] PostgreSQL database created
- [ ] Backend environment variables configured
- [ ] Backend URL accessible (test with curl)
- [ ] `VITE_API_BASE_URL` set in Vercel
- [ ] Frontend redeployed after environment variable change
- [ ] Browser console shows no CORS errors

## Next Steps

1. Choose a deployment platform (Railway recommended)
2. Deploy backend
3. Get backend URL
4. Update `VITE_API_BASE_URL` in Vercel
5. Redeploy frontend
6. Test the live link

Questions? Check the backend README.md for more details on configuration.

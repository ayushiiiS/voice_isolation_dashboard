# Voice Isolation Dashboard

Production-grade SaaS web application for isolating user/agent audio from call recordings and generating Blue Machines-style interaction analytics.

## Architecture

```
voice_isolation/
├── src/                    # FastAPI backend
│   ├── api/                # REST endpoints (auth, upload, jobs, analytics)
│   ├── analytics/          # Call metrics engine
│   ├── auth/               # JWT + bcrypt
│   ├── db/                 # MongoDB (Motor)
│   ├── diarization/        # pyannote Community-1
│   ├── isolation/          # Audio extraction pipeline
│   ├── reports/            # PDF / CSV / JSON exports
│   ├── services/           # Job processor + GCS upload
│   └── workers/            # Celery tasks (optional)
├── frontend/               # Next.js 15 + Tailwind + ShadCN-style UI
├── scripts/seed.py         # Demo user seed script
├── sample_recordings.csv   # Example batch upload CSV
└── docker-compose.yml      # Full stack deployment
```

## Features

- **Authentication**: Register, login, forgot password (JWT + bcrypt)
- **Upload**: Single recording URL or CSV batch upload with drag-and-drop
- **Processing**: pyannote diarization → user/agent separation → GCS upload
- **Analytics**: Latency, talk time, confidence, interruptions, sentiment, WPM
- **Dashboard**: KPI cards, recent jobs table, progress tracking
- **Call Details**: Audio players, transcript, timeline, charts
- **Interaction Viewer**: Blue Machines-style waveform + analytics view
- **Reports**: Export PDF, CSV, JSON per call
- **Retry**: Re-process failed batch jobs

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | Next.js 15, TypeScript, TailwindCSS, Recharts |
| Backend | FastAPI, Python 3.11 |
| Database | MongoDB Atlas |
| Storage | Google Cloud Storage (`cadence-audio`) |
| Queue | Celery + Redis (optional) |
| ML | pyannote Community-1, pydub, ffmpeg |

## Prerequisites

- Python 3.11+
- Node.js 20+
- ffmpeg
- MongoDB Atlas cluster
- Hugging Face token ([Community-1 license](https://huggingface.co/pyannote/speaker-diarization-community-1))
- GCS service account JSON (for uploads/signing)

## Quick Start

### 1. Clone and configure

```bash
cp .env.example .env
cp frontend/.env.local.example frontend/.env.local
```

Edit `.env` with your credentials:

```env
MONGODB_URI=mongodb+srv://USER:PASSWORD@cluster.mongodb.net
MONGODB_DB=voice_isolation
JWT_SECRET=your-long-random-secret
BUCKET_NAME=cadence-audio
REGION=asia-south1
GOOGLE_APPLICATION_CREDENTIALS=secrets/bm-gcs-credentials.json
HF_TOKEN=your_huggingface_token
```

### 2. Backend setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Seed demo user (demo@voiceisolation.app / demo12345)
python scripts/seed.py

# Start API
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Frontend setup

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

### 4. Docker (full stack)

```bash
docker compose up --build
```

Services: `backend:8000`, `frontend:3000`, `redis:6379`, `worker` (Celery)

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/register` | Create account |
| POST | `/auth/login` | Get JWT token |
| POST | `/auth/forgot-password` | Password reset request |
| POST | `/upload/url` | Upload single recording URL |
| POST | `/upload/csv` | Batch CSV upload |
| GET | `/jobs` | List jobs |
| GET | `/jobs/dashboard` | Dashboard KPIs |
| GET | `/jobs/{id}` | Job detail + recordings |
| POST | `/jobs/{id}/retry` | Retry failed recordings |
| GET | `/analytics/{id}` | Call analytics (recording ID) |
| GET | `/reports/{id}` | Report export URLs |
| GET | `/health` | Health check |

All upload/job/analytics routes require `Authorization: Bearer <token>`.

## CSV Batch Format

Use `sample_recordings.csv` as a template:

```csv
url
https://storage.googleapis.com/.../recording.ogg
https://storage.googleapis.com/.../recording2.ogg
```

Batch results are written to `output/reports/{job_id}/results.csv` with columns:

`recording_url, user_audio_url, agent_audio_url, duration_seconds, user_talk_time, agent_talk_time, avg_latency_ms, avg_confidence, interruptions, status`

## GCS Storage Layout

```
gs://cadence-audio/
├── uploads/
├── user_audio/{recording_id}/user_only.wav
├── agent_audio/{recording_id}/agent_only.wav
└── reports/{recording_id}/
    ├── diarization.json
    ├── report.json
    ├── report.csv
    └── report.pdf
```

## Pages

| Route | Description |
|-------|-------------|
| `/login` | Sign in |
| `/register` | Create account |
| `/forgot-password` | Password reset |
| `/dashboard` | KPI cards + recent jobs |
| `/upload` | URL or CSV upload |
| `/jobs/{id}` | Job progress + retry |
| `/calls/{id}` | Call details + charts |
| `/interaction/{id}` | Blue Machines interaction viewer |

## Environment Variables

See `.env.example` for the full list. Key variables:

| Variable | Description |
|----------|-------------|
| `MONGODB_URI` | MongoDB Atlas connection string |
| `JWT_SECRET` | JWT signing secret |
| `BUCKET_NAME` | GCS bucket (`cadence-audio`) |
| `HF_TOKEN` | Hugging Face token for pyannote |
| `USE_CELERY` | Enable Celery worker (`true`/`false`) |
| `REDIS_URL` | Redis broker URL |
| `NEXT_PUBLIC_API_URL` | Frontend → backend URL |

## Development Notes

- Without GCS credentials, processed audio stays on local disk (dev mode).
- Set `USE_CELERY=true` and run `celery -A src.workers.celery_app worker` for async processing.
- The existing `/isolate` endpoints remain available for direct pipeline access.

## License

Integrates [pyannote Community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) (CC-BY-4.0).

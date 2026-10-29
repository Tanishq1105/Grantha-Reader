# Grantha Reader

An AI scripture reader built with React, Vite, Flask, Supabase and Gemini.

## Features

- Read original scripture books.
- Ask questions with source citations.
- English, Hindi and Sanskrit explanations.
- Bookmarks, notes and reading progress.
- Zoom, fullscreen and reading themes.

## Run Locally

Open Command Prompt in the project folder:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
npm ci
```

For a new installation, copy `.env.example` to `.env`. Do not overwrite an existing working `.env`.

Add your credentials and settings:

```dotenv
SUPABASE_DB_URL=your_database_connection
GEMINI_API_KEY=your_api_key
AI_ENABLED=true
GEMINI_MODEL=gemini-3.1-flash-lite
GEMINI_MAX_OUTPUT_TOKENS=512
GEMINI_CONTEXT_CHARACTERS=2000
GEMINI_THINKING_LEVEL=low
GEMINI_SECOND_PASS=false
```

Prepare search and start:

```bash
python -m backend.manage setup-rag
npm run dev
```

Open http://127.0.0.1:3000.

## Deploy on Render

Start Docker Desktop and create a private Docker Hub repository.

Replace `YOUR_USERNAME`, then run:

```bash
docker login
docker build --platform linux/amd64 -t YOUR_USERNAME/grantha-reader:v1 .
docker push YOUR_USERNAME/grantha-reader:v1
```

In Render:

1. Select **New → Web Service → Existing Image**.
2. Enter `YOUR_USERNAME/grantha-reader:v1`.
3. Add your Docker Hub registry credentials.
4. Add your working environment variables.
5. Set these production values:

```dotenv
APP_ENV=production
SESSION_COOKIE_SECURE=true
SECRET_KEY=your_random_secret
```

Generate the secret locally:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Leave **Docker Command** blank, use one service instance, and set the health-check path to `/api/health`.

Deploy, then test login, reading, bookmarks and an AI question.

## Important

- Exclude `.env` from Git and Docker images.
- Include the original PDFs and required retrieval data in the Docker build.
- Users and bookmarks are stored in Supabase.
- AI can make mistakes. Check the cited original pages.
# Retail Radar Frontend

Standalone Vite/React dashboard for `retail-radar-ai`.

## Run

```bash
npm install
npm run dev
```

Default local URLs:

- Frontend: `http://localhost:5173`
- EEP API: `http://localhost:8000`
- IE2 API: `http://localhost:8002`

## Data Modes

- `mock-report`: seeded local demo data
- `ie2-live`: live recommendation calls to IE2 only
- `eep-live`: live report, ops, and recommendation data through EEP
- `supabase-ready`: reserved for later backend work

## Environment

Create `frontend/.env` from `frontend/.env.example` if you want non-default URLs.

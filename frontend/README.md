# RiskUW Frontend

React + TypeScript + Vite + Ant Design 5 frontend for the RiskUW Automated Underwriting Platform.

## Stack

| Layer | Choice |
|---|---|
| Framework | React 18 + TypeScript |
| Build | Vite 6 |
| UI | Ant Design 5 (dark theme, custom tokens) |
| HTTP | Axios with Bearer interceptor |
| State | Zustand (auth store) |
| Router | React Router 6 |
| Fonts | Sora (display) · DM Sans (body) · JetBrains Mono (data) |

## Quick start

```bash
# 1. Install
npm install

# 2. Point at your FastAPI backend
cp .env.example .env
# Edit VITE_API_BASE=http://localhost:8000   (or https://riskuw.online)

# 3. Run dev server
npm run dev
# → http://localhost:5173
```

## Pages

| Route | Page | Description |
|---|---|---|
| `/login` | LoginPage | Credentials + TOTP MFA (auto-redirects if already logged in) |
| `/` | DashboardPage | Decision metrics, approval rate bar, recent cases |
| `/evaluate` | **EvaluatePage** | Full intake form → live decision panel (key demo page) |
| `/cases` | CasesPage | Searchable queue table with all decisions |

## API endpoints consumed

```
POST /auth/login              { username, password }
POST /auth/verify-mfa         { totp_code, username, session_token }
GET  /products                → Product[]
POST /underwriting/evaluate   → UWDecision
GET  /queue/?page_size=N      → QueueCase[]
```

## Evaluate payload (complete)

The `EvaluatePage` builds the full 40+ field payload matching your FastAPI schema:
- Applicant: ref, age, gender, state
- Coverage: face_amount, product_code, term, policy dates
- Build: height_inches, weight_lbs (BMI calculated live)
- Tobacco: status + quit years
- Blood pressure: systolic, diastolic, meds
- Diabetes: type, dx_age, A1c
- Cardiac: condition + years ago
- Medical flags: HIV, cirrhosis, stroke, kidney, depression, epilepsy, COPD
- Occupation: class (1–4, D) + title
- Driving: DUI count, major violations
- Lifestyle: alcohol drinks/week, hazardous activities
- Lab values: total cholesterol, HDL, LDL, eGFR
- Family history: CVD before 60, stroke before 65
- Financial: annual_income, existing_life_coverage

## Decision card

The right panel shows:
- Outcome hero (APPROVED / DECLINED / POSTPONED / REFERRED) with glow effect
- STP vs Referred badge
- Animated debit points progress bar (colour-coded)
- Risk class, table rating, flat extra, approved premium
- All rules fired with individual debit points
- Adverse action text
- Download Decision Report button

## Production deploy

```bash
npm run build
# → dist/   (copy to your nginx static root)
```

Nginx config: serve `dist/` for all routes, proxy `/api` → FastAPI on port 8000.

```nginx
location / {
    root /var/www/riskuw-frontend/dist;
    try_files $uri $uri/ /index.html;
}
location /api {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Authorization $http_authorization;
}
```

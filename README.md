# APAAR Pramaan

**APAAR ID–Based Student Data Management & Verification Platform**  
**Smart India Hackathon 2026 · Problem Statement 26263 · Smart Automation**

APAAR Pramaan is a hackathon prototype for managing student-level enrolment records across AICTE-approved institutions. It demonstrates how institution uploads, APAAR-format checks, enrolment validation, compliance monitoring, consent-based record disclosure, and verifiable credentials can be brought together in one web application.

> **Prototype notice:** This project is an independent demonstration and is **not an official AICTE, APAAR, ABC, DigiLocker, or Government of India service**. The APAAR/ABC registry is simulated with local demo data. No live government integration is included. Use only synthetic data when running or demonstrating this repository.

## Contents

- [Problem addressed](#problem-addressed)
- [Key features](#key-features)
- [Application workflow](#application-workflow)
- [Architecture](#architecture)
- [Technology stack](#technology-stack)
- [Repository structure](#repository-structure)
- [Run locally on Windows](#run-locally-on-windows)
- [Demo accounts](#demo-accounts)
- [REST API](#rest-api)
- [Security mechanisms in the prototype](#security-mechanisms-in-the-prototype)
- [Current scope and limitations](#current-scope-and-limitations)
- [Potential next steps](#potential-next-steps)

## Problem addressed

The project responds to **SIH 2026 Problem Statement 26263**: *Development of an APAAR ID-Based Student Data Management and Verification Platform for AICTE-Approved Institutions.* The intended workflow in the problem statement calls for institution-level student data submission, validation, monitoring, and authorised verification.

APAAR Pramaan demonstrates that workflow with synthetic records. It is intended to make common data-quality and enrolment issues visible to institutions and administrators, while providing a consent step before a verifier receives a signed student-record credential.

## Key features

### Institution portal

- Upload student enrolment data in CSV format.
- Validate records row by row and show accepted, updated, warning, and rejected outcomes.
- Check APAAR ID format and lookup against the **simulated local registry**.
- Detect duplicate IDs in an upload and potential enrolment in another institution.
- Flag identity mismatches, missing or invalid dates of birth, ages below 16, missing student IDs, quota-category conflicts, missing approved intake, and enrolment beyond approved intake plus supernumerary seats.
- Add or update an individual student record using a registry lookup.
- View the seat matrix and student list, and generate a printable certificate with a QR code.

### AICTE administrator dashboard

- View aggregated enrolment metrics and institution-level dashboards.
- Highlight programmes whose enrolment exceeds the configured intake limit.
- Review institution compliance-risk scores and the reasons contributing to those scores.
- Inspect potential cross-institution duplicate enrolments and search records.
- View the audit-chain status and export a CSV compliance report.

### Authorised verifier portal

- Request consent before releasing enrolment information.
- In the demo, confirm consent using an OTP displayed in the application.
- Issue an Ed25519-signed credential containing a limited set of student/enrolment claims.
- Generate a QR code that opens a public credential-verification page.

### Additional capabilities

- English, Hindi, and Tamil interface text.
- Session-based role separation for institution, AICTE, and verifier demo users.
- REST API endpoints for student uploads, AICTE risk results, and credential verification.
- Synthetic seed data for demonstrations, including deliberately injected data-quality issues.

## Application workflow

1. An institution signs in and uploads student-level data.
2. The application validates the rows against policy rules and the local mock APAAR registry.
3. Accepted records are stored; warning and rejection reasons are returned for review.
4. The AICTE dashboard aggregates institution and enrolment information, including intake and anomaly indicators.
5. An authorised verifier requests a record and completes the prototype consent step.
6. The application issues a signed credential with a QR code; the public page checks the credential signature and reports whether it is valid.

## Architecture

```mermaid
flowchart TD
    I[Institution user] --> UI[Web portal: Jinja2 templates]
    A[AICTE officer] --> UI
    V[Authorised verifier] --> UI
    UI --> API[FastAPI application and REST endpoints]
    API --> ING[CSV ingestion and row validation]
    ING --> RULES[Intake and policy rules]
    RULES --> DB[(SQLite database)]
    API --> RISK[Isolation Forest + rule-based risk score]
    DB --> RISK
    RISK --> DASH[AICTE monitoring dashboard]
    API --> CONSENT[Consent workflow]
    CONSENT --> SIGN[Ed25519-signed credential + QR]
    SIGN --> VERIFY[Public credential verification page]
    REG[(Simulated APAAR / ABC registry)] --> ING
    REG --> API
```

The diagram describes the **current local prototype**, not a deployed national architecture. The live APAAR/ABC, DigiLocker, NAD, and AICTE integrations are not connected.

## Technology stack

| Layer | Technology | Purpose in this project |
|---|---|---|
| Web framework | FastAPI, Uvicorn | Web routes and REST API |
| UI | Jinja2, HTML, CSS | Role-based web pages and printable views |
| Local data store | SQLite, SQLAlchemy | Demo institutions, enrolments, registry entries, consent records, and audit events |
| Data processing | pandas | CSV processing and dashboard/report calculations |
| Anomaly scoring | scikit-learn `IsolationForest` plus policy rules | Prototype institution-level compliance-risk score |
| Application security | `cryptography` | AES-GCM field encryption, password hashing helpers, and Ed25519 credential signatures |
| QR generation | `qrcode[pil]` | QR codes for verification links |
| Languages | English, Hindi, Tamil | Localised interface strings |

The risk score is a **prototype prioritisation signal**, not a validated regulatory decision system. The Isolation Forest output is combined with rule-based indicators such as intake overshoot, late admissions, invalid IDs, and duplicate records; the displayed reasons are intended to help a human reviewer understand the flags.

## Repository structure

```text
apaar-pramaan/
├── README.md
├── .gitignore
├── requirements.txt
└── backend/
    ├── main.py               # FastAPI routes and application entry point
    ├── services.py           # Validation, dashboards, risk scoring, credentials and audit logic
    ├── models.py             # SQLAlchemy models and SQLite configuration
    ├── security.py           # Encryption, HMAC, and password-hash helpers
    ├── i18n.py                # English, Hindi, and Tamil strings
    ├── seed_data.py          # Synthetic demo-data generator
    ├── static/
    │   ├── style.css
    │   └── img/
    └── templates/            # Jinja2 portal pages
```

The database, generated secret-key files, demo-ID files, upload samples, and report exports are local runtime artifacts and should not be committed.

## Run locally on Windows

### Prerequisites

- Windows 10/11
- Python 3.10 or newer
- Git (only needed to clone or contribute to the repository)
- PowerShell or the VS Code integrated terminal configured for PowerShell

### 1. Open the project folder

Open the `apaar-pramaan` folder in VS Code. In **Terminal → New Terminal**, make sure the terminal is at the project root—the folder containing `requirements.txt`.

If needed, navigate there using your own project path, for example:

```powershell
cd "C:\MY COLLEGE\PROJECTS\apaar-pramaan"
```

### 2. Create and activate a virtual environment

Run this when setting up a fresh checkout. If a `.venv` already exists and works, you can skip the creation command.

```powershell
py -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Create or reset the synthetic demo data

```powershell
cd backend
python seed_data.py
```

This creates the local SQLite demo database, a mock APAAR registry, demo users, and generated sample files. **Running `seed_data.py` resets/recreates the demo dataset.** Run it when you intentionally want a fresh demo; do not rerun it if you need to retain records entered during a session.

On first application startup, the application also seeds the database automatically if the database file does not exist.

### 5. Start the application

Run this from the `backend` directory:

```powershell
python -m uvicorn main:app --reload
```

Open these addresses in your browser:

- **Portal:** http://127.0.0.1:8000
- **Demo guide:** http://127.0.0.1:8000/demo-guide
- **Interactive REST API docs:** http://127.0.0.1:8000/api/docs

Keep the terminal running while using the application. Press `Ctrl+C` to stop the development server.

## Demo accounts

These accounts are created by the synthetic seed script. They are for local demonstrations only.

| Role | Username | Password |
|---|---|---|
| AICTE officer | `aicte` | `aicte123` |
| Institution nodal officer | `inst001` | `inst123` |
| Verifier (employer/regulator) | `employer` | `verify123` |

The demo uses randomly generated synthetic student records. The seeded APAAR IDs are written to `backend/demo_apaar_ids.txt` after data generation and are intentionally excluded from Git. Do not enter real student information or expose a publicly hosted instance with these demo credentials.

## REST API

The interactive API documentation is available at `/api/docs` while the server is running.

| Method | Endpoint | Purpose | Access in this prototype |
|---|---|---|---|
| `POST` | `/api/v1/students/upload` | Upload a CSV and return row-level validation outcomes | HTTP Basic authentication; institution role required |
| `GET` | `/api/v1/institutions/risk` | Return institution risk results | HTTP Basic authentication; AICTE role required |
| `GET` | `/api/v1/credentials/verify?token=<signed-token>` | Verify a signed credential and return its claims | Public verification endpoint |

The CSV upload endpoint expects a multipart file upload. Refer to `/api/docs` for request schemas and interactive testing.

## Security mechanisms in the prototype

The code demonstrates the following mechanisms in a local proof of concept:

- **AES-256-GCM:** encrypts APAAR ID and student-name fields stored through the model's encrypted string type.
- **HMAC-SHA256:** creates a keyed identifier for lookup and duplicate matching without using the raw APAAR ID as the lookup key.
- **PBKDF2-HMAC-SHA256:** hashes demo passwords with a per-password salt.
- **Ed25519:** signs issued credential payloads; the public verification route checks the signature.
- **Hash-chained audit log:** links audit entries so changes to prior entries can be detected by the audit-chain check.
- **Role checks and sessions:** separate institution, AICTE, and verifier portal access.

These mechanisms are educational prototype implementations and are **not a claim of production security certification or regulatory compliance**. Before real deployment, the system requires independent security review, secure secret management and key rotation, hardened authentication, rate limiting, operational monitoring, database and backup controls, privacy/legal review, and end-to-end testing.

## Current scope and limitations

The following boundaries are important when evaluating or extending the project:

- **Mock identity source:** the APAAR/ABC registry is a local SQLite table populated with synthetic records. No official APAAR, ABC, DigiLocker, NAD, or AICTE API is called.
- **Simulated consent delivery:** the consent OTP is displayed in the demo UI; it is not delivered through a production SMS, email, or identity-provider service.
- **Demo authentication:** the project includes seeded demo accounts and is not configured for public production use.
- **Local database:** SQLite is used for the prototype. Production-scale deployment would require a reviewed database, migrations, backup/recovery, and scaling plan.
- **Planned production integrations:** SFTP/webhooks, live government registry connections, multi-factor authentication, production identity federation, and scheduled PDF/accreditation reporting are not implemented as live production services in this repository.
- **Risk model:** the Isolation Forest and policy thresholds are demonstration logic. They need representative, authorised data, evaluation, monitoring, fairness review, and human oversight before any operational use.

## Potential next steps

1. Obtain formal authorisation and technical specifications for official APAAR/ABC and relevant institutional integrations.
2. Introduce production-grade identity federation, MFA, a real consent-delivery workflow, key management, and audited access policies.
3. Move to a production database and deployment architecture with migrations, observability, backups, and automated tests.
4. Evaluate and calibrate the anomaly-detection model using authorised, representative data, with explanations and a human-review process.
5. Add institution ERP adapters, controlled bulk-transfer options, scheduled reports, and accessibility/security testing.

## License

No open-source license is currently included. Unless a license is added, reuse and redistribution are not expressly granted. Add a suitable `LICENSE` file before publishing the project for unrestricted reuse.

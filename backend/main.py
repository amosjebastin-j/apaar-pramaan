import io, os, base64, random
from urllib.parse import urlparse
import pandas as pd
from fastapi import FastAPI, Request, Form, UploadFile, File, Depends, HTTPException
from fastapi.responses import RedirectResponse, Response, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.middleware.sessions import SessionMiddleware
from jinja2 import pass_context
from services import *
from security import SESSION_SECRET
from i18n import tr, LANGS

STATIC = os.path.join(BASE, "static")
TPL = os.path.join(BASE, "templates")

# first run (e.g. on a fresh host): build the demo database automatically
if not os.path.exists(DB_PATH):
    import seed_data
    seed_data.main()

app = FastAPI(title="APAAR Student Data Management & Verification Portal – API",
              docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, max_age=3600)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
T = Jinja2Templates(directory=TPL)


def logo(name):
    """Official logo files can be dropped into static/img as emblem/moe/aicte/apaar with any of these extensions."""
    for ext in ("png", "jpg", "jpeg", "webp", "svg"):
        if os.path.exists(os.path.join(STATIC, "img", f"{name}.{ext}")):
            return f"/static/img/{name}.{ext}"
    return ""


@pass_context
def _(ctx, s, **kw):
    return tr(ctx.get("lang", "en"), s, **kw)


T.env.globals.update({"_": _, "logo": logo, "LANGS": LANGS, "REASONS": REASON_TEXT})

HOME = {"AICTE": "/aicte", "INSTITUTION": "/institution", "VERIFIER": "/verifier"}
TITLES = {"AICTE": "AICTE Officer Login", "INSTITUTION": "Institution Nodal Officer Login",
          "VERIFIER": "Authorised Verifier Login (Employer / Regulator)"}
DEMO = {"AICTE": "aicte / aicte123", "INSTITUTION": "inst001 / inst123", "VERIFIER": "employer / verify123"}


def lang(req):
    return req.session.get("lang", "en")


def L(req, s, **kw):
    return tr(lang(req), s, **kw)


def render(req, name, **c):
    return T.TemplateResponse(req, name, {"u": req.session.get("u"), "lang": lang(req), "demo_ids": demo_ids(), **c})


def who(req, role):
    u = req.session.get("u")
    return u if u and u["role"] == role else None


# ---------------- language ----------------
@app.get("/lang/{code}")
def set_lang(req: Request, code: str):
    if code in LANGS: req.session["lang"] = code
    ref = urlparse(req.headers.get("referer") or "/")
    back = (ref.path or "/") + (("?" + ref.query) if ref.query else "")
    return RedirectResponse(back, 303)


# ---------------- public ----------------
@app.get("/")
def home(req: Request):
    s = Session(); k = kpis()
    k["verif"] = s.query(Audit).filter_by(action="CREDENTIAL_ISSUED").count()
    return render(req, "home.html", k=k)


@app.get("/demo-guide")
def demo_guide(req: Request):
    return render(req, "demo_guide.html")


def login_ctx(req, role, err=None):
    role = role if role in TITLES else "INSTITUTION"
    a, b = random.randint(2, 9), random.randint(2, 9); req.session["cap"] = a + b
    return dict(role=role, title=L(req, TITLES[role]), demo=DEMO[role], a=a, b=b, err=err)


@app.get("/login")
def login_page(req: Request, role: str = "INSTITUTION"):
    return render(req, "login.html", **login_ctx(req, role))


@app.post("/login")
def login_post(req: Request, role: str = Form(...), username: str = Form(...),
               password: str = Form(...), captcha: str = Form(...)):
    if captcha.strip() != str(req.session.get("cap")):
        return render(req, "login.html", **login_ctx(req, role, L(req, "Incorrect security check answer.")))
    s = Session(); x = login(s, username.strip(), password)
    if not x or x.role != role:
        audit(s, username, "LOGIN_FAILED", role)
        return render(req, "login.html", **login_ctx(req, role, L(req, "Invalid User ID or password for this portal.")))
    req.session["u"] = dict(name=x.username, role=x.role, inst=x.inst_id); audit(s, x.username, "LOGIN")
    return RedirectResponse(HOME[x.role], 303)


@app.get("/logout")
def logout(req: Request):
    l = lang(req); req.session.clear(); req.session["lang"] = l
    return RedirectResponse("/", 303)


@app.get("/verify-credential")
def verify_public(req: Request, t: str = ""):
    valid, claims = (verify_token(t) if t else (None, None))
    return render(req, "verify_public.html", t=t, valid=valid, claims=claims)


# ---------------- AICTE ----------------
@app.get("/aicte")
def aicte_dash(req: Request, q: str = ""):
    if not (u := who(req, "AICTE")): return RedirectResponse("/login?role=AICTE", 303)
    s = Session(); f = risk_table(s); k = kpis(); d = cross_dups()
    k["flagged"] = int((f.risk >= 40).sum()); k["dups"] = int(d.apaar_id.nunique())
    fc = f.sort_values("inst_id"); st = f.groupby("state").enrolled.sum()
    qt = pd.read_sql("select quota, count(*) n from enrolment group by quota", engine)
    aud = pd.read_sql("select ts,actor,action,detail,substr(hash,1,16) hash from audit order by id desc limit 60", engine)
    res = None
    q = q.strip()
    if q:
        hh = h(q)
        rows = s.query(Enrolment, Institution).join(Institution, Institution.id == Enrolment.inst_id).filter(Enrolment.apaar_hash == hh).all()
        res = [dict(apaar=mask(e.apaar_id), student_id=e.student_id or "-", name=e.name, inst=i.name, inst_id=i.id,
                    program=e.program, year=e.year, quota=e.quota, status=e.status, flags=e.flags) for e, i in rows]
        audit(s, u["name"], "RECORD_SEARCH", mask(q))
    return render(req, "aicte.html", k=k, risk=f.to_dict("records"), dups=d.to_dict("records"),
        alerts=over_intake_programs().head(12).to_dict("records"), activity=recent_activity(10),
        labels=fc.inst_id.tolist(), ratios=fc.fill_ratio.round(2).tolist(), risks=fc.risk.tolist(),
        st_l=st.index.tolist(), st_v=st.astype(int).tolist(), q_l=qt.quota.tolist(), q_v=qt.n.astype(int).tolist(),
        aud=aud.to_dict("records"), chain=audit_ok(s), q=q, res=res, tab="search" if q else "ov")


@app.get("/aicte/institution/{iid}")
def aicte_inst(req: Request, iid: str):
    if not who(req, "AICTE"): return RedirectResponse("/login?role=AICTE", 303)
    s = Session(); inst = s.get(Institution, iid)
    if not inst: raise HTTPException(404, "Institution not found")
    f = risk_table(s); row = f[f.inst_id == iid].iloc[0].to_dict()
    return render(req, "aicte_inst.html", inst=inst, row=row, rows=seat_matrix(s, iid).to_dict("records"),
                  activity=recent_activity(10, iid))


@app.get("/aicte/report")
def aicte_report_page(req: Request):
    if not who(req, "AICTE"): return RedirectResponse("/login?role=AICTE", 303)
    return render(req, "report.html", **report_data(Session()))


@app.get("/aicte/report.csv")
def aicte_report(req: Request):
    if not who(req, "AICTE"): return RedirectResponse("/login?role=AICTE", 303)
    return Response(risk_table(Session()).to_csv(index=False), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=AICTE_Institution_Compliance_Report.csv"})


# ---------------- Institution ----------------
def inst_ctx(s, u, **extra):
    m = seat_matrix(s, u["inst"]); i = s.get(Institution, u["inst"])
    base = dict(inst=i, rows=m.to_dict("records"), students=[], total_students=0, q="", flash=None, res=None,
                tot=dict(approved=int(m.approved.sum()), sup=int(m.supernumerary.sum()), enrolled=int(m.enrolled.sum())),
                programs=[r["program"] for r in m.to_dict("records")], err=None, tab="seat")
    base.update(extra); return base


@app.get("/institution")
def inst_dash(req: Request, tab: str = "seat", q: str = ""):
    if not (u := who(req, "INSTITUTION")): return RedirectResponse("/login?role=INSTITUTION", 303)
    s = Session(); tab = tab if tab in ("seat", "up", "add", "students") else "seat"
    students, total = find_students(s, u["inst"], q) if tab == "students" else ([], 0)
    return render(req, "institution.html", **inst_ctx(s, u, students=students, total_students=total, q=q, tab=tab))


@app.get("/institution/lookup")
def inst_lookup(req: Request, apaar: str = ""):
    if not who(req, "INSTITUTION"): return JSONResponse({"found": False, "reason": "auth"}, status_code=401)
    return lookup_registry(Session(), apaar)


@app.post("/institution/add")
async def inst_add(req: Request):
    if not (u := who(req, "INSTITUTION")): return RedirectResponse("/login?role=INSTITUTION", 303)
    s = Session(); form = dict((await req.form()).items())
    r = add_single(s, u["inst"], u["name"], form)
    flash = dict(r, apaar=mask(form.get("apaar_id", "")), name=form.get("name", ""))
    return render(req, "institution.html", **inst_ctx(s, u, flash=flash, tab="add"))


@app.get("/institution/sample.csv")
def inst_sample(req: Request):
    if not who(req, "INSTITUTION"): return RedirectResponse("/login?role=INSTITUTION", 303)
    return FileResponse(os.path.join(BASE, "sample_upload_dirty.csv"), filename="sample_student_data.csv")


@app.post("/institution/upload")
async def inst_upload(req: Request, file: UploadFile = File(...)):
    if not (u := who(req, "INSTITUTION")): return RedirectResponse("/login?role=INSTITUTION", 303)
    s = Session()
    try:
        df = pd.read_csv(io.BytesIO(await file.read()), dtype=str)
        if df.empty: raise ValueError("empty")
    except Exception:
        return render(req, "institution.html", **inst_ctx(s, u, tab="up", err=L(req, "Unable to read the file. Please upload a valid CSV.")))
    r = validate_upload(s, df, u["inst"], u["name"])
    os.makedirs(os.path.join(STATIC, "reports"), exist_ok=True)
    fname = f"{u['inst']}_error_report.csv"
    r.to_csv(os.path.join(STATIC, "reports", fname), index=False)
    for col in ("apaar_id", "student_id", "name", "program"):
        if col not in r.columns: r[col] = ""
    order = {"REJECTED": 0, "WARNING": 1, "UPDATED": 2, "ACCEPTED": 3}
    rows = r.assign(_o=r.status.map(order)).sort_values("_o", kind="stable").head(500)
    res = dict(cnt=r.status.value_counts().to_dict(), total=len(r), link=f"/static/reports/{fname}",
               rows=rows.to_dict("records"))
    return render(req, "institution.html", **inst_ctx(s, u, res=res, tab="res"))


@app.get("/institution/certificate/{eid}")
def inst_cert(req: Request, eid: int):
    if not (u := who(req, "INSTITUTION")): return RedirectResponse("/login?role=INSTITUTION", 303)
    s = Session(); e = s.get(Enrolment, eid)
    if not e or e.inst_id != u["inst"]: raise HTTPException(404, "Record not found")
    inst = s.get(Institution, e.inst_id)
    tok = issue(claims_for(e, inst))
    url = str(req.base_url) + "verify-credential?t=" + tok
    audit(s, u["name"], "CERTIFICATE_GENERATED", mask(e.apaar_id))
    return render(req, "certificate.html", e=e, inst=inst, qr=base64.b64encode(qr_png(url)).decode())


# ---------------- Verifier ----------------
@app.get("/verifier")
def ver_page(req: Request):
    if not who(req, "VERIFIER"): return RedirectResponse("/login?role=VERIFIER", 303)
    return render(req, "verifier.html", step=1, err=None)


@app.post("/verifier/request")
def ver_request(req: Request, apaar: str = Form(...)):
    if not (u := who(req, "VERIFIER")): return RedirectResponse("/login?role=VERIFIER", 303)
    r = request_consent(Session(), u["name"], apaar)
    if not r: return render(req, "verifier.html", step=1, err=L(req, "No student record found for the entered APAAR ID."))
    req.session["cid"], req.session["otp"], req.session["ap"] = r[0], r[1], mask(apaar.strip())
    return render(req, "verifier.html", step=2, otp=r[1], ap=req.session["ap"], err=None)


@app.post("/verifier/confirm")
def ver_confirm(req: Request, otp: str = Form(...)):
    if not (u := who(req, "VERIFIER")): return RedirectResponse("/login?role=VERIFIER", 303)
    cid = req.session.get("cid")
    if cid is None: return RedirectResponse("/verifier", 303)
    tok = release(Session(), cid, otp.strip(), u["name"])
    if not tok:
        return render(req, "verifier.html", step=2, otp=req.session.get("otp"), ap=req.session.get("ap"),
                      err=L(req, "Invalid OTP. Consent not granted."))
    valid, claims = verify_token(tok)
    url = str(req.base_url) + "verify-credential?t=" + tok
    qr = base64.b64encode(qr_png(url)).decode()
    return render(req, "verifier.html", step=3, claims=claims, qr=qr, token=tok, url=url, err=None)


# ---------------- REST API (integration) ----------------
sec = HTTPBasic()


def api_user(c: HTTPBasicCredentials = Depends(sec)):
    x = login(Session(), c.username, c.password)
    if not x: raise HTTPException(401, "Invalid credentials")
    return x


@app.post("/api/v1/students/upload", tags=["Institution API"])
async def api_upload(file: UploadFile, x=Depends(api_user)):
    if x.role != "INSTITUTION": raise HTTPException(403, "Institution role required")
    r = validate_upload(Session(), pd.read_csv(io.BytesIO(await file.read()), dtype=str), x.inst_id, x.username)
    return {"summary": r.status.value_counts().to_dict(), "rows": r.to_dict("records")}


@app.get("/api/v1/institutions/risk", tags=["AICTE API"])
def api_risk(x=Depends(api_user)):
    if x.role != "AICTE": raise HTTPException(403, "AICTE role required")
    return risk_table(Session()).to_dict("records")


@app.get("/api/v1/credentials/verify", tags=["Verification API"])
def api_verify(token: str):
    valid, claims = verify_token(token); return {"valid": valid, "claims": claims}

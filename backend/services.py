import json, base64, os, io, random, difflib, hashlib, datetime as dt
import pandas as pd, qrcode
from sqlalchemy import func, text
from sklearn.ensemble import IsolationForest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from models import *
from security import h, mask, dec, check_pw, BASE


def _now():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def login(s, u, p):
    x = s.get(User, u)
    return x if x and check_pw(p, x.pw_hash) else None


# ---------- audit (hash-chained) ----------
def audit(s, actor, action, detail=""):
    last = s.query(Audit).order_by(Audit.id.desc()).first()
    prev = last.hash if last else "0" * 64
    ts = _now()
    hs = hashlib.sha256(f"{prev}{ts}{actor}{action}{detail}".encode()).hexdigest()
    s.add(Audit(ts=ts, actor=actor, action=action, detail=detail, prev_hash=prev, hash=hs)); s.commit()


def audit_ok(s):
    prev = "0" * 64
    for a in s.query(Audit).order_by(Audit.id):
        x = hashlib.sha256(f"{prev}{a.ts}{a.actor}{a.action}{a.detail}".encode()).hexdigest()
        if a.prev_hash != prev or x != a.hash: return False
        prev = a.hash
    return True


# ---------- upload validation ----------
REASON_TEXT = {
    "INVALID_APAAR": "APAAR ID is missing or is not a 12-digit number",
    "APAAR_NOT_FOUND": "APAAR ID is not present in the national APAAR registry",
    "DUPLICATE": "The same APAAR ID appears more than once in this upload",
    "IDENTITY_MISMATCH": "Name or date of birth does not match the APAAR registry",
    "AGE_INVALID": "Date of birth is missing or the student is under 16",
    "QUOTA_CATEGORY_MISMATCH": "NRI / Foreign National student is marked with a reserved category",
    "NO_APPROVED_INTAKE": "This programme has no approved intake for the institution",
    "OVER_INTAKE": "Admissions exceed the approved intake plus supernumerary seats",
    "CROSS_INSTITUTION_ENROLMENT": "The student is already enrolled in another institution",
    "STUDENT_ID_MISSING": "The institution's Student ID is missing",
}
REJ = {"INVALID_APAAR", "APAAR_NOT_FOUND", "DUPLICATE", "NO_APPROVED_INTAKE", "AGE_INVALID"}
RESERVED = ("SC", "ST", "OBC", "EWS")


def _sim(a, b):
    return difflib.SequenceMatcher(None, str(a).lower().strip(), str(b).lower().strip()).ratio()


def _norm_cols(df):
    df = df.copy()
    df.columns = [str(c).strip().lower().replace(" ", "_").replace("-", "_") for c in df.columns]
    return df


def validate_upload(s, df, inst_id, actor, action="UPLOAD"):
    df = _norm_cols(df).fillna("").astype(str)
    cap = {i.program: i.approved + i.supernumerary for i in s.query(Intake).filter_by(inst_id=inst_id, year=2026)}
    cnt = dict(s.query(Enrolment.program, func.count()).filter(Enrolment.inst_id == inst_id, Enrolment.year == 2026)
               .group_by(Enrolment.program).all())
    mine = {e.apaar_hash: e for e in s.query(Enrolment).filter(Enrolment.inst_id == inst_id, Enrolment.year == 2026,
                                                                Enrolment.apaar_hash.isnot(None))}
    other = {r[0] for r in s.query(Enrolment.apaar_hash).filter(Enrolment.inst_id != inst_id, Enrolment.year == 2026)}
    seen, st_l, fl_l = set(), [], []
    for _, row in df.iterrows():
        r = row.to_dict(); fl = []; upd = None
        a = r.get("apaar_id", "").strip()
        hh = h(a) if a.isdigit() and len(a) == 12 else None
        b = lambda c: str(r.get(c, "")).strip().lower() in ("true", "1", "yes")
        nri, oci, fn = b("nri"), b("oci"), b("fn")
        dob = pd.to_datetime(r.get("dob"), errors="coerce")
        reg = s.get(ApaarRegistry, a) if hh else None
        if not hh: fl.append("INVALID_APAAR")
        elif hh in seen: fl.append("DUPLICATE")
        elif reg is None: fl.append("APAAR_NOT_FOUND")
        else:
            if hh in mine: upd = mine[hh]
            elif hh in other: fl.append("CROSS_INSTITUTION_ENROLMENT")
            if pd.isna(dob) or reg.dob != dob.date() or _sim(reg.name, r.get("name", "")) < .8:
                fl.append("IDENTITY_MISMATCH")
        if pd.isna(dob) or 2026 - dob.year < 16: fl.append("AGE_INVALID")
        if (fn or nri) and r.get("category") in RESERVED: fl.append("QUOTA_CATEGORY_MISMATCH")
        p = r.get("program")
        if p not in cap: fl.append("NO_APPROVED_INTAKE")
        elif upd is None and cnt.get(p, 0) >= cap[p]: fl.append("OVER_INTAKE")
        if not r.get("student_id", "").strip(): fl.append("STUDENT_ID_MISSING")
        if hh: seen.add(hh)
        if set(fl) & REJ: st = "REJECTED"
        elif upd is not None: st = "UPDATED"
        else: st = "WARNING" if fl else "ACCEPTED"
        if st != "REJECTED":
            ad = pd.to_datetime(r.get("admission_date"), errors="coerce")
            vals = dict(name=r.get("name"), dob=dob.date(), gender=r.get("gender"), category=r.get("category"),
                        program=p, quota=r.get("quota"), nri=nri, oci=oci, fn=fn,
                        student_id=r.get("student_id", "").strip(), status=st, flags=",".join(fl),
                        admission_date=None if pd.isna(ad) else ad.date())
            if upd is not None:
                for k, v in vals.items(): setattr(upd, k, v)
            else:
                s.add(Enrolment(apaar_id=a, apaar_hash=hh, inst_id=inst_id, year=2026, **vals))
                cnt[p] = cnt.get(p, 0) + 1
        st_l.append(st); fl_l.append(", ".join(fl))
    s.commit()
    out = df.copy(); out["status"] = st_l; out["flags"] = fl_l
    counts = ", ".join(f"{k.title()} {v}" for k, v in out.status.value_counts().items())
    audit(s, actor, action, f"{inst_id}: {counts}")
    return out


# ---------- seat matrix ----------
def seat_matrix(s, inst_id):
    it = pd.read_sql(text("select program,approved,supernumerary from intake where inst_id=:i"), engine, params={"i": inst_id})
    e = pd.read_sql(text("select program,nri,oci,fn from enrolment where inst_id=:i"), engine, params={"i": inst_id})
    g = e.groupby("program").agg(enrolled=("nri", "size"), NRI=("nri", "sum"), OCI=("oci", "sum"), FN=("fn", "sum"))
    m = it.merge(g, left_on="program", right_index=True, how="left").fillna(0)
    m["allowed"] = m.approved + m.supernumerary
    m["fill_%"] = (m.enrolled / m.allowed * 100).round(1)
    return m


# ---------- anomaly / risk ----------
def risk_table(s):
    e = pd.read_sql("select inst_id,apaar_hash,nri,oci,fn,admission_date from enrolment", engine)
    ins = pd.read_sql("select * from institution", engine).set_index("id")
    it = pd.read_sql("select inst_id,sum(approved) approved,sum(supernumerary) sup from intake group by inst_id", engine).set_index("inst_id")
    e["late"] = pd.to_datetime(e.admission_date) >= "2026-09-10"
    e["inv"] = e.apaar_hash.isna()
    e["dupf"] = e.apaar_hash.notna() & e.duplicated(["apaar_hash", "inst_id"], keep="first")
    e["spl"] = (e.nri.astype(int) + e.oci.astype(int) + e.fn.astype(int)) > 0
    g = e.groupby("inst_id")
    f = g[["late", "inv", "dupf", "spl"]].mean(); f["enrolled"] = g.size()
    f = f.join(it); f["cap"] = f.approved + f["sup"]; f["fill_ratio"] = f.enrolled / f.cap
    X = f[["fill_ratio", "late", "inv", "dupf", "spl"]]
    iso = -IsolationForest(contamination=.1, random_state=0).fit(X).score_samples(X)
    iso = (iso - iso.min()) / (iso.max() - iso.min() + 1e-9) * 100
    rule = 40 * (f.fill_ratio > 1) + 20 * (f.late > .2) + 20 * (f.inv > .05) + 20 * (f.dupf > .03)
    f["risk"] = (.5 * iso + .5 * rule).round(0)

    def why(r):
        w = []
        if r.fill_ratio > 1: w.append(f"Enrolment at {r.fill_ratio:.0%} of approved+supernumerary intake")
        if r.late > .2: w.append(f"{r.late:.0%} of admissions in the final days")
        if r.inv > .05: w.append(f"{r.inv:.0%} invalid APAAR IDs")
        if r.dupf > .03: w.append(f"{r.dupf:.0%} duplicate records")
        return "; ".join(w) or "Normal pattern"
    f["reasons"] = f.apply(why, axis=1)
    return f.join(ins[["name", "state"]]).reset_index().sort_values("risk", ascending=False)


def cross_dups():
    e = pd.read_sql("select apaar_id,apaar_hash,name,inst_id,program from enrolment where apaar_hash is not null", engine)
    ids = e.groupby("apaar_hash").inst_id.nunique(); ids = ids[ids > 1].index
    d = e[e.apaar_hash.isin(ids)].sort_values("apaar_hash").copy()
    d["apaar_id"] = d.apaar_id.map(lambda x: mask(dec(x)))
    d["name"] = d.name.map(dec)
    return d.drop(columns="apaar_hash")


def kpis():
    q = lambda x: int(pd.read_sql(x, engine).iloc[0, 0])
    return dict(total=q("select count(*) from enrolment"), inst=q("select count(*) from institution"),
        invalid=q("select count(*) from enrolment where apaar_hash is null"),
        nri=q("select count(*) from enrolment where nri=1"), oci=q("select count(*) from enrolment where oci=1"),
        fn=q("select count(*) from enrolment where fn=1"))


def find_students(s, inst_id, q="", limit=40):
    rows = s.query(Enrolment).filter(Enrolment.inst_id == inst_id, Enrolment.apaar_hash.isnot(None)) \
        .order_by(Enrolment.id.desc()).all()
    q = q.strip(); ql = q.lower()
    hq = h(q) if q.isdigit() and len(q) == 12 else None
    out = []
    for e in rows:
        if ql and not (ql in (e.name or "").lower() or ql in (e.student_id or "").lower() or e.apaar_hash == hq):
            continue
        out.append(dict(id=e.id, student_id=e.student_id or "-", name=e.name, apaar=e.apaar_id,
                        program=e.program, status=e.status))
        if len(out) >= limit: break
    return out, len(rows)


# ---------- credentials ----------
_KEY = None


def _key():
    global _KEY
    if _KEY: return _KEY
    pem = os.environ.get("VERISEAT_SIGNING_KEY")
    if pem:
        _KEY = serialization.load_pem_private_key(pem.replace("\\n", "\n").encode(), None)
        return _KEY
    p = os.path.join(BASE, "signing.pem")
    if os.path.exists(p):
        _KEY = serialization.load_pem_private_key(open(p, "rb").read(), None)
    else:
        _KEY = Ed25519PrivateKey.generate()
        open(p, "wb").write(_KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
    return _KEY


def _b(x): return base64.urlsafe_b64encode(x).decode()
def _u(x): return base64.urlsafe_b64decode(x + "=" * (-len(x) % 4))


def issue(payload):
    raw = json.dumps(payload, sort_keys=True).encode()
    return _b(raw) + "." + _b(_key().sign(raw))


def verify_token(t):
    try:
        a, b = t.strip().split(".")
        raw = _u(a); _key().public_key().verify(_u(b), raw)
        return True, json.loads(raw)
    except Exception:
        return False, None


def qr_png(data):
    buf = io.BytesIO(); qrcode.make(data).save(buf, format="PNG"); return buf.getvalue()


def claims_for(e, inst):
    return {"apaar": mask(e.apaar_id), "student_id": e.student_id or "-", "name": e.name,
            "institution": inst.name, "program": e.program, "year": e.year, "status": "ENROLLED",
            "issuer": "AICTE", "issued": str(dt.date.today())}


def request_consent(s, verifier, apaar_id):
    apaar_id = apaar_id.strip()
    hh = h(apaar_id)
    if not s.query(Enrolment).filter_by(apaar_hash=hh).first():
        audit(s, verifier, "VERIFY_NOT_FOUND", mask(apaar_id)); return None
    otp = f"{random.randint(0, 999999):06d}"
    c = Consent(apaar_hash=hh, verifier=verifier, otp=otp); s.add(c); s.commit()
    audit(s, verifier, "CONSENT_REQUESTED", mask(apaar_id)); return c.id, otp


def release(s, cid, otp, verifier):
    c = s.get(Consent, cid)
    if not c or c.otp != otp or c.status != "PENDING":
        audit(s, verifier, "CONSENT_DENIED", str(cid)); return None
    c.status = "GRANTED"; s.commit()
    e = s.query(Enrolment).filter_by(apaar_hash=c.apaar_hash).filter(Enrolment.status != "REJECTED").first()
    inst = s.get(Institution, e.inst_id)
    tok = issue(claims_for(e, inst))
    audit(s, verifier, "CREDENTIAL_ISSUED", mask(e.apaar_id)); return tok


# ---------- demo helpers, registry lookup, single entry ----------
def demo_ids():
    p = os.path.join(BASE, "demo_ids.json")
    try:
        with open(p) as f: return json.load(f)
    except Exception:
        return {"enrolled": [], "pool": []}


def lookup_registry(s, apaar):
    apaar = (apaar or "").strip()
    if not (apaar.isdigit() and len(apaar) == 12):
        return {"found": False, "reason": "format"}
    reg = s.get(ApaarRegistry, apaar)
    if not reg: return {"found": False, "reason": "missing"}
    ins = [r[0] for r in s.query(Enrolment.inst_id).filter(Enrolment.apaar_hash == h(apaar)).distinct()]
    return {"found": True, "name": reg.name, "dob": reg.dob.isoformat(), "enrolled_in": ins}


def add_single(s, inst_id, actor, f):
    row = {k: (f.get(k) or "").strip() for k in ["apaar_id", "student_id", "name", "dob", "gender", "category",
                                                  "program", "admission_date", "quota"]}
    for k in ("nri", "oci", "fn"): row[k] = "true" if f.get(k) else "false"
    row["year"] = "2026"
    out = validate_upload(s, pd.DataFrame([row]), inst_id, actor, action="STUDENT_ENTRY")
    r = out.iloc[0]
    return {"status": r["status"], "flags": [c for c in r["flags"].split(", ") if c]}


def over_intake_programs():
    df = pd.read_sql("""select i.inst_id, n.name inst_name, i.program, i.approved, i.supernumerary,
        (select count(*) from enrolment e where e.inst_id=i.inst_id and e.program=i.program and e.year=i.year) enrolled
        from intake i join institution n on n.id=i.inst_id""", engine)
    df["allowed"] = df.approved + df.supernumerary
    df["fill_pct"] = (df.enrolled / df.allowed * 100).round(0).astype(int)
    df["excess"] = df.enrolled - df.allowed
    return df[df.enrolled > df.allowed].sort_values("fill_pct", ascending=False)


def recent_activity(limit=10, inst_id=None):
    if inst_id:
        df = pd.read_sql(text("select ts,actor,action,detail from audit where action in ('UPLOAD','STUDENT_ENTRY') "
                              "and detail like :p order by id desc limit :n"), engine, params={"p": f"{inst_id}:%", "n": limit})
    else:
        df = pd.read_sql(text("select ts,actor,action,detail from audit where action in "
                              "('UPLOAD','STUDENT_ENTRY','CREDENTIAL_ISSUED','CERTIFICATE_GENERATED','CONSENT_REQUESTED') "
                              "order by id desc limit :n"), engine, params={"n": limit})
    df["ts"] = df.ts.astype(str).str.slice(0, 19)
    return df.to_dict("records")


def report_data(s):
    f = risk_table(s)
    return dict(k=kpis(), risk=f.to_dict("records"), over=over_intake_programs().to_dict("records"),
                dups=int(cross_dups().apaar_id.nunique()), now=_now().strftime("%d %b %Y, %H:%M UTC"))

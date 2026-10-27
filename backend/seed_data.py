"""Creates the demo database: 30 institutions, ~10k student records with injected problems,
a mock APAAR registry, demo users and a dirty sample CSV for the live upload demo."""
import os, random, csv, datetime as dt
from collections import defaultdict
from models import *
from security import h, hash_pw, BASE

FN_ = "Aarav Vihaan Ananya Diya Rohan Priya Karthik Meena Arjun Sneha Ishaan Kavya Rahul Divya Vikram Neha Suresh Lakshmi Imran Fatima".split()
LN_ = "Sharma Reddy Nair Iyer Khan Patel Singh Das Gupta Menon Rao Kumar Joshi Verma Pillai".split()
STATES = ["TN", "KA", "MH", "DL", "UP", "WB", "TS", "GJ"]
PROGS = ["B.Tech CSE", "B.Tech ECE", "B.Tech MECH", "MBA", "MCA"]
PC = {"B.Tech CSE": "CSE", "B.Tech ECE": "ECE", "B.Tech MECH": "MECH", "MBA": "MBA", "MCA": "MCA"}
CATS = ["General", "OBC", "SC", "ST", "EWS"]
OVER = {"INST005", "INST012", "INST024"}


def main():
    random.seed(7)
    used, seq = set(), defaultdict(int)

    def gen():
        while True:
            a = "".join(random.choices("0123456789", k=12))
            if a not in used:
                used.add(a); return a

    def sid(inst, prog):
        seq[(inst, prog)] += 1
        return f"{inst}-{PC[prog]}-26-{seq[(inst, prog)]:04d}"

    def mk(inst, prog, late=False):
        d = dt.date(2026, 9, 10) + dt.timedelta(random.randint(0, 5)) if late \
            else dt.date(2026, 7, 1) + dt.timedelta(random.randint(0, 70))
        q, nri, oci, fn, r = "Regular", False, False, False, random.random()
        if r < .03: q, nri = "NRI", True
        elif r < .05: q, oci = "OCI", True
        elif r < .07: q, fn = "FN", True
        elif r < .10: q = "Supernumerary"
        a = gen()
        return Enrolment(apaar_id=a, apaar_hash=h(a), student_id=sid(inst, prog),
            name=f"{random.choice(FN_)} {random.choice(LN_)}",
            dob=dt.date(random.randint(2002, 2007), random.randint(1, 12), random.randint(1, 28)),
            gender=random.choice("MF"), category=random.choice(CATS), inst_id=inst, program=prog, year=2026,
            admission_date=d, quota=q, nri=nri, oci=oci, fn=fn, status="ACCEPTED", flags="")

    def clone(e, **kw):
        d = {c.name: getattr(e, c.name) for c in Enrolment.__table__.columns if c.name != "id"}
        d.update(kw); return Enrolment(**d)

    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    s = Session(); rows = []; inst_progs = {}; demo_prog = None
    for i in range(1, 31):
        iid = f"INST{i:03d}"
        s.add(Institution(id=iid, name=f"{random.choice(LN_)} Institute of Technology {i}", state=random.choice(STATES)))
        s.add(User(username=f"inst{i:03d}", pw_hash=hash_pw("inst123"), role="INSTITUTION", inst_id=iid))
        inst_progs[iid] = []
        plist = random.sample(PROGS, 3)
        caps = {p: random.choice([60, 120, 180]) for p in plist}
        big = max(plist, key=lambda p: caps[p])
        if iid == "INST001": demo_prog = big
        for p in plist:
            ap = caps[p]; sup = ap // 20
            s.add(Intake(inst_id=iid, program=p, year=2026, approved=ap, supernumerary=sup))
            inst_progs[iid].append((ap + sup, p))
            n = int((ap + sup) * (random.uniform(1.2, 1.4) if iid in OVER else random.uniform(.8, .98)))
            if iid == "INST001" and p == big:
                n = (ap + sup) - 40                      # demo institution: 40 free seats
            rows += [mk(iid, p, late=(iid in OVER and k > n * .6)) for k in range(n)]

    # ---- injected problems ----
    for e in random.sample(rows, int(len(rows) * .02)):                    # invalid / missing APAAR IDs
        e.apaar_id = random.choice(["12345", "", e.apaar_id[:9]]); e.apaar_hash = None
    valid = [r for r in rows if r.apaar_hash]
    dups = [clone(e) for e in random.sample(valid, int(len(rows) * .01))]  # same-institution duplicates
    cross = []                                                             # same student in two institutions
    for e in random.sample(valid, 40):
        o = f"INST{random.choice([x for x in range(1, 31) if f'INST{x:03d}' != e.inst_id]):03d}"
        p = random.choice(inst_progs[o])[1]
        cross.append(clone(e, inst_id=o, program=p, student_id=sid(o, p)))
    for e in random.sample([r for r in rows if r.fn], 8): e.category = "SC"  # FN + domestic category

    s.add_all(rows + dups + cross)
    s.add(User(username="aicte", pw_hash=hash_pw("aicte123"), role="AICTE"))
    s.add(User(username="employer", pw_hash=hash_pw("verify123"), role="VERIFIER"))
    s.commit()

    # ---- mock APAAR registry (the national identity source) ----
    s.add_all([ApaarRegistry(apaar_id=e.apaar_id, name=e.name, dob=e.dob) for e in valid])
    s.commit()

    # ---- demo CSV for INST001 (its biggest programme, 40 free seats) ----
    target = "INST001"; prog = demo_prog
    fresh = [mk(target, prog) for _ in range(46)]
    for k, e in enumerate(fresh):
        if k != 9:                                        # row 9 -> ID not present in the registry
            s.add(ApaarRegistry(apaar_id=e.apaar_id, name=e.name, dob=e.dob))
    # registered APAAR IDs that are not enrolled anywhere yet (used for the single-student demo)
    pool = []
    for _ in range(20):
        a = gen(); nm = f"{random.choice(FN_)} {random.choice(LN_)}"
        s.add(ApaarRegistry(apaar_id=a, name=nm, dob=dt.date(random.randint(2003, 2007), random.randint(1, 12), random.randint(1, 28))))
        pool.append(a)
    s.commit()
    with open(os.path.join(BASE, "sample_upload_dirty.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow("apaar_id,student_id,name,dob,gender,category,program,year,admission_date,quota,nri,oci,fn".split(","))
        for k, e in enumerate(fresh):
            a, name, dob = e.apaar_id, e.name, e.dob
            cat = "General" if (e.fn or e.nri) else e.category      # keep the rest of the file clean
            fn = e.fn
            if k == 3: a = a[:8]                          # invalid APAAR format      -> REJECTED
            if k == 9: pass                               # not in registry           -> REJECTED
            if k == 14: a = fresh[0].apaar_id             # duplicate inside the file -> REJECTED
            if k == 20: name = "Rohan Verma"              # name differs from registry-> WARNING
            if k == 26: fn, cat = True, "SC"              # FN with reserved category -> WARNING
            if k == 31: dob = dob + dt.timedelta(days=40) # DOB differs from registry -> WARNING
            w.writerow([a, f"{target}-{PC[prog]}-26-{900 + k:04d}", name, dob, e.gender, cat, prog, 2026,
                        e.admission_date, e.quota, e.nri, e.oci, fn])

    enrolled_demo = [e.apaar_id for e in valid if e.inst_id == target and e.program == prog][:3]
    import json
    with open(os.path.join(BASE, "demo_ids.json"), "w") as f:
        json.dump({"enrolled": enrolled_demo, "pool": pool[:8]}, f)
    with open(os.path.join(BASE, "demo_apaar_ids.txt"), "w") as f:
        f.write("ENROLLED students (use in Verifier portal and AICTE search):\n" + "\n".join(enrolled_demo) +
                "\n\nREGISTERED but not enrolled yet (use in Institution > Add / Update Student):\n" + "\n".join(pool[:8]) + "\n")
    print(len(rows) + len(dups) + len(cross), "enrolments seeded; over-admitting:", sorted(OVER))
    print("Enrolled demo IDs (verifier / AICTE search):", ", ".join(enrolled_demo))
    print("Registered, not enrolled (Add Student demo):", ", ".join(pool[:3]), "...")


if __name__ == "__main__":
    main()

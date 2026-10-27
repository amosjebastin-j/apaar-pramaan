import os
from sqlalchemy import *
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.types import TypeDecorator
from security import enc, dec, BASE


class EncStr(TypeDecorator):
    """Transparently encrypts the value (AES-256-GCM) when written and decrypts it when read."""
    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return enc(value)

    def process_result_value(self, value, dialect):
        return dec(value)


DB_PATH = os.environ.get("VERISEAT_DB", os.path.join(BASE, "apaar.db"))
Base = declarative_base()
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False, "timeout": 30})
Session = sessionmaker(bind=engine)


class Institution(Base):
    __tablename__ = "institution"
    id = Column(String, primary_key=True); name = Column(String); state = Column(String)


class Intake(Base):
    __tablename__ = "intake"
    id = Column(Integer, primary_key=True)
    inst_id = Column(String, ForeignKey("institution.id")); program = Column(String)
    year = Column(Integer); approved = Column(Integer); supernumerary = Column(Integer, default=0)


class ApaarRegistry(Base):
    """Mock of the national APAAR / ABC registry (in production: DigiLocker / ABC API)."""
    __tablename__ = "apaar_registry"
    apaar_id = Column(String, primary_key=True); name = Column(String); dob = Column(Date)


class Enrolment(Base):
    __tablename__ = "enrolment"
    id = Column(Integer, primary_key=True)
    apaar_id = Column(EncStr)            # encrypted at rest
    apaar_hash = Column(String, index=True)
    student_id = Column(String)          # institution's own student / roll number
    name = Column(EncStr)                # encrypted at rest
    dob = Column(Date); gender = Column(String); category = Column(String)
    inst_id = Column(String, ForeignKey("institution.id")); program = Column(String); year = Column(Integer)
    admission_date = Column(Date); quota = Column(String)
    nri = Column(Boolean, default=False); oci = Column(Boolean, default=False); fn = Column(Boolean, default=False)
    status = Column(String, default="ACCEPTED"); flags = Column(Text, default="")


class User(Base):
    __tablename__ = "user"
    username = Column(String, primary_key=True); pw_hash = Column(String)
    role = Column(String); inst_id = Column(String, nullable=True)


class Consent(Base):
    __tablename__ = "consent"
    id = Column(Integer, primary_key=True)
    apaar_hash = Column(String); verifier = Column(String); otp = Column(String); status = Column(String, default="PENDING")


class Audit(Base):
    __tablename__ = "audit"
    id = Column(Integer, primary_key=True); ts = Column(DateTime)
    actor = Column(String); action = Column(String); detail = Column(Text)
    prev_hash = Column(String); hash = Column(String)

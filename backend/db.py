from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import create_engine, event, Column, String, Text, Integer, Boolean,inspect
from sqlalchemy.orm import declarative_base, sessionmaker
from .config import DATA

def uid(): return uuid4().hex
def now(): return datetime.now(timezone.utc).isoformat()
engine = create_engine(f'sqlite:///{(DATA / "store.db").as_posix()}', connect_args={'check_same_thread': False, 'timeout': 20})
@event.listens_for(engine, 'connect')
def configure(conn, _):
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
Session = sessionmaker(engine, expire_on_commit=False)
Base = declarative_base()

class User(Base):
    __tablename__='users'
    id=Column(String,primary_key=True,default=uid)
    username=Column(String,unique=True,nullable=False)
    display_name=Column(String,nullable=False)
    password=Column(String,nullable=False)
    role=Column(String,default='customer')
    active=Column(Boolean,default=True)
    created_at=Column(String,default=now)

class LoginSession(Base):
    __tablename__='sessions'
    id=Column(String,primary_key=True)
    user_id=Column(String,nullable=False)
    expires=Column(String,nullable=False)

class Conversation(Base):
    __tablename__='conversations'
    id=Column(String,primary_key=True,default=uid)
    customer_id=Column(String,nullable=False,index=True)
    customer_name=Column(String,default='访客')
    owner_id=Column(String,nullable=True)
    status=Column(String,default='waiting')
    stage=Column(String,default='新咨询')
    seq=Column(Integer,default=0)
    analysis=Column(Text,default='{}')
    analysis_seq=Column(Integer,default=0)
    locked=Column(Text,default='{}')
    created_at=Column(String,default=now)
    updated_at=Column(String,default=now)

class Message(Base):
    __tablename__='messages'
    id=Column(String,primary_key=True,default=uid)
    conversation_id=Column(String,nullable=False,index=True)
    sender_id=Column(String,nullable=False)
    role=Column(String,nullable=False)
    content=Column(Text,nullable=False)
    card=Column(Text,default='{}')
    client_id=Column(String,unique=True,nullable=False)
    seq=Column(Integer,nullable=False)
    created_at=Column(String,default=now)

class ConversationDismissal(Base):
    __tablename__='conversation_dismissals'
    user_id=Column(String,primary_key=True)
    conversation_id=Column(String,primary_key=True)
    created_at=Column(String,default=now)

class DialogueState(Base):
    __tablename__='dialogue_states'
    conversation_id=Column(String,primary_key=True)
    revision=Column(Integer,default=0,nullable=False)
    message_seq=Column(Integer,default=0,nullable=False)
    state=Column(Text,default='{}',nullable=False)
    updated_at=Column(String,default=now)

class DialogueRun(Base):
    __tablename__='dialogue_runs'
    id=Column(String,primary_key=True,default=uid)
    conversation_id=Column(String,index=True,nullable=False)
    input_revision=Column(Integer,nullable=False)
    input_seq=Column(Integer,nullable=False)
    status=Column(String,default='running')
    trace=Column(Text,default='{}')
    created_at=Column(String,default=now)

class PriceRule(Base):
    __tablename__='price_rules'
    id=Column(String,primary_key=True,default=uid)
    product_id=Column(String,index=True,nullable=False)
    variant_id=Column(String,nullable=False)
    payload=Column(Text,nullable=False)
    author_id=Column(String,nullable=False)
    approved_by=Column(String,default='')
    status=Column(String,default='draft')
    created_at=Column(String,default=now)

class QuoteQualification(Base):
    __tablename__='quote_qualifications'
    id=Column(String,primary_key=True,default=uid)
    customer_id=Column(String,index=True,nullable=False)
    qualification=Column(String,nullable=False)
    evidence_ref=Column(String,nullable=False)
    reviewed_by=Column(String,nullable=False)
    valid_until=Column(String,nullable=False)

class ReadPosition(Base):
    __tablename__='read_positions'
    id=Column(String,primary_key=True)
    seq=Column(Integer,default=0)

class Job(Base):
    __tablename__='jobs'
    id=Column(String,primary_key=True,default=uid)
    kind=Column(String,nullable=False)
    actor_id=Column(String,nullable=False)
    target_id=Column(String,default='')
    status=Column(String,default='queued')
    step=Column(String,default='等待执行')
    payload=Column(Text,default='{}')
    result=Column(Text,default='{}')
    error=Column(Text,default='')
    remote_id=Column(String,default='')
    created_at=Column(String,default=now)
    updated_at=Column(String,default=now)

class Work(Base):
    __tablename__='works'
    id=Column(String,primary_key=True,default=uid)
    actor_id=Column(String,nullable=False)
    brief=Column(Text,default='{}')
    content=Column(Text,default='{}')
    report=Column(Text,default='{}')
    version=Column(Integer,default=1)
    created_at=Column(String,default=now)
    updated_at=Column(String,default=now)

class WorkVersion(Base):
    __tablename__='work_versions'
    id=Column(String,primary_key=True,default=uid)
    work_id=Column(String,nullable=False,index=True)
    version=Column(Integer,nullable=False)
    content=Column(Text,nullable=False)
    report=Column(Text,nullable=False)
    created_at=Column(String,default=now)

class Followup(Base):
    __tablename__='followups'
    id=Column(String,primary_key=True,default=uid)
    conversation_id=Column(String,nullable=False,index=True)
    owner_id=Column(String,nullable=False)
    due_at=Column(String,nullable=False)
    purpose=Column(String,nullable=False)
    script=Column(Text,default='')
    status=Column(String,default='pending')
    feedback=Column(Text,default='')
    generated=Column(Boolean,default=False)
    offset_days=Column(Integer,default=0)
    created_at=Column(String,default=now)

class Asset(Base):
    __tablename__='assets'
    id=Column(String,primary_key=True,default=uid)
    actor_id=Column(String,nullable=False)
    kind=Column(String,nullable=False)
    path=Column(String,nullable=False)
    metadata_json=Column(Text,default='{}')
    created_at=Column(String,default=now)

class Setting(Base):
    __tablename__='settings'
    key=Column(String,primary_key=True)
    value=Column(Text,nullable=False)

class Audit(Base):
    __tablename__='audit'
    id=Column(String,primary_key=True,default=uid)
    actor_id=Column(String,nullable=False)
    action=Column(String,nullable=False)
    target=Column(String,default='')
    created_at=Column(String,default=now)

def init_db():
    Base.metadata.create_all(engine)
    # Additive migration: preserve existing reminders and all manually edited text.
    columns={c['name'] for c in inspect(engine).get_columns('followups')}
    with engine.begin() as connection:
        if 'generated' not in columns:connection.exec_driver_sql('ALTER TABLE followups ADD COLUMN generated BOOLEAN NOT NULL DEFAULT 0')
        if 'offset_days' not in columns:connection.exec_driver_sql('ALTER TABLE followups ADD COLUMN offset_days INTEGER NOT NULL DEFAULT 0')

"""SQLite como índice local. Excel y snapshots versionados permanecen en disco."""
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4

from app.storage import write_json
from app.week_calendar import BRANCHES, as_date, week_bounds, week_days, week_id

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_version VALUES(1);
CREATE TABLE IF NOT EXISTS weeks(
 id TEXT PRIMARY KEY, start_date TEXT UNIQUE NOT NULL, end_date TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'EN_CURSO', reopened INTEGER NOT NULL DEFAULT 0,
 revision INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, closed_at TEXT);
CREATE TABLE IF NOT EXISTS workdays(
 week_id TEXT NOT NULL REFERENCES weeks(id), date TEXT NOT NULL, branch TEXT NOT NULL,
 worked INTEGER NOT NULL DEFAULT 1 CHECK(worked IN (0,1)), reason TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(week_id,date,branch));
CREATE TABLE IF NOT EXISTS uploads(
 id INTEGER PRIMARY KEY, week_id TEXT NOT NULL REFERENCES weeks(id), type TEXT NOT NULL,
 logical_key TEXT NOT NULL, file_path TEXT NOT NULL, original_filename TEXT NOT NULL,
 hash TEXT NOT NULL, detected_start_date TEXT, detected_end_date TEXT,
 coverage_start TEXT NOT NULL, coverage_end TEXT NOT NULL, branch TEXT,
 version INTEGER NOT NULL, active INTEGER NOT NULL CHECK(active IN (0,1)),
 metadata TEXT NOT NULL, uploaded_at TEXT NOT NULL,
 UNIQUE(week_id,logical_key,version));
CREATE UNIQUE INDEX IF NOT EXISTS one_active_upload
 ON uploads(week_id,logical_key) WHERE active=1;
CREATE INDEX IF NOT EXISTS uploads_hash ON uploads(hash);
CREATE TABLE IF NOT EXISTS liquidation_day_status(
 week_id TEXT NOT NULL REFERENCES weeks(id), date TEXT NOT NULL,
 confirmed_complete INTEGER NOT NULL DEFAULT 0, confirmed_at TEXT,
 count_at_confirmation INTEGER, note TEXT NOT NULL DEFAULT '', PRIMARY KEY(week_id,date));
CREATE TABLE IF NOT EXISTS reviews(
 id INTEGER PRIMARY KEY, week_id TEXT NOT NULL REFERENCES weeks(id),
 source_revision INTEGER NOT NULL, file_path TEXT NOT NULL, payload TEXT NOT NULL,
 created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS snapshots(
 id INTEGER PRIMARY KEY, week_id TEXT NOT NULL REFERENCES weeks(id), kind TEXT NOT NULL,
 source_revision INTEGER NOT NULL, file_path TEXT NOT NULL, hash TEXT NOT NULL,
 created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_events(
 id INTEGER PRIMARY KEY, week_id TEXT NOT NULL REFERENCES weeks(id),
 action TEXT NOT NULL, timestamp TEXT NOT NULL, details TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS legacy_loads(
 folder TEXT PRIMARY KEY, week_id TEXT NOT NULL REFERENCES weeks(id), date TEXT NOT NULL);
"""


def timestamp():
    return datetime.now().astimezone().isoformat(timespec="microseconds")


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def default_data_root():
    return Path.home() / "Documents" / "SHES-Control-Datos"


class WeekStore:
    def __init__(self, root=None):
        self.root = Path(root or default_data_root()).resolve()
        repo = Path(__file__).resolve().parents[1]
        if self.root == repo or repo in self.root.parents:
            raise ValueError("Los datos y SQLite deben estar fuera del repositorio")
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "shes_index.sqlite3"
        with self.connect() as db:
            db.executescript(SCHEMA)
            from app.rewards import SCHEMA as REWARD_SCHEMA
            db.executescript(REWARD_SCHEMA)
            db.execute("BEGIN IMMEDIATE")
            if "removed_at" not in {row["name"] for row in db.execute("PRAGMA table_info(uploads)")}:
                db.execute("ALTER TABLE uploads ADD COLUMN removed_at TEXT")
            db.execute("INSERT OR IGNORE INTO schema_version VALUES(2)")
            db.execute("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS settings_history(timestamp TEXT NOT NULL, details TEXT NOT NULL)")
            db.execute("INSERT OR IGNORE INTO settings VALUES('excluded_sellers', ?)",
                       (json.dumps(["HUGO", "ROLON BRAIAN", "OJEDA DIEGO"]),))

    def default_exclusions(self):
        return set(json.loads(self.query("SELECT value FROM settings WHERE key='excluded_sellers'")[0]["value"]))

    def set_default_exclusions(self, names):
        with self.connect() as db:
            db.execute("UPDATE settings SET value=? WHERE key='excluded_sellers'", (json.dumps(sorted(set(names))),))
            db.execute("INSERT INTO settings_history VALUES(?,?)", (timestamp(), json.dumps(sorted(set(names)))))
            for week in db.execute("SELECT id FROM weeks WHERE status!='CERRADA' AND NOT EXISTS (SELECT 1 FROM reviews WHERE week_id=weeks.id)").fetchall():
                self.changed(db, week["id"])

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def query(self, sql, params=()):
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, params)]

    def ensure_week(self, day):
        start, end = week_bounds(day)
        key = week_id(day)
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO weeks(id,start_date,end_date,created_at) VALUES(?,?,?,?)",
                       (key, start.isoformat(), end.isoformat(), timestamp()))
            for d in week_days(start):
                for branch in BRANCHES:
                    db.execute("INSERT OR IGNORE INTO workdays(week_id,date,branch) VALUES(?,?,?)",
                               (key, d.isoformat(), branch))
                db.execute("INSERT OR IGNORE INTO liquidation_day_status(week_id,date) VALUES(?,?)",
                           (key, d.isoformat()))
        return self.week(key)

    def week(self, key):
        rows = self.query("SELECT * FROM weeks WHERE id=?", (key,))
        if not rows:
            raise ValueError("Semana inexistente")
        return rows[0]

    def folder(self, key):
        self.week(key)  # Validar identificador antes de construir rutas.
        return self.root / "HISTORIAL" / key

    def assert_open(self, db, key, expected_revision=None):
        row = db.execute("SELECT * FROM weeks WHERE id=?", (key,)).fetchone()
        if row is None or row["status"] == "CERRADA":
            raise ValueError("Semana cerrada: reabrila explícitamente para modificarla")
        if expected_revision is not None and row["revision"] != expected_revision:
            raise ValueError("La semana cambió. Actualizá la pantalla y revisá nuevamente")
        return row

    def audit(self, db, key, action, details):
        db.execute("INSERT INTO audit_events(week_id,action,timestamp,details) VALUES(?,?,?,?)",
                   (key, action, timestamp(), json.dumps(details, ensure_ascii=False)))

    def changed(self, db, key, invalidate_liquidations=True):
        db.execute("UPDATE weeks SET revision=revision+1 WHERE id=?", (key,))
        if invalidate_liquidations:
            db.execute("UPDATE liquidation_day_status SET confirmed_complete=0 WHERE week_id=?", (key,))

    def uploads(self, key, active=False):
        return self.query("SELECT * FROM uploads WHERE week_id=?" +
                          (" AND active=1" if active else "") + " ORDER BY id", (key,))

    def duplicate(self, digest, key=None):
        rows = self.query("SELECT * FROM uploads WHERE hash=? AND active=1 AND removed_at IS NULL" +
                          (" AND week_id=?" if key else "") + " LIMIT 1", (digest, key) if key else (digest,))
        return rows[0] if rows else None

    def workdays(self, key):
        return self.query("SELECT * FROM workdays WHERE week_id=? ORDER BY date,branch", (key,))

    def set_worked(self, key, day, branches, worked, reason=""):
        day = as_date(day)
        week = self.week(key)
        if not week["start_date"] <= day.isoformat() <= week["end_date"] or day.weekday() == 6:
            raise ValueError("Elegí una jornada de lunes a sábado de esta semana")
        if not branches or not set(branches) <= set(BRANCHES):
            raise ValueError("Sucursal inválida")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.assert_open(db, key)
            for branch in branches:
                db.execute("UPDATE workdays SET worked=?,reason=? WHERE week_id=? AND date=? AND branch=?",
                           (int(worked), reason if not worked else "", key, day.isoformat(), branch))
            self.audit(db, key, "revertir_no_trabajado" if worked else "no_trabajado",
                       {"date": day.isoformat(), "branches": list(branches), "reason": reason})
            self.changed(db, key)

    def commit_uploads(self, key, candidates, expected_revision):
        """Batch confirmado: copia bytes, registra metadatos y activa solo reemplazos válidos."""
        results = []
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            week = self.assert_open(db, key, expected_revision)
            for candidate in candidates:
                digest = file_hash(candidate.path)
                if digest != candidate.hash:
                    raise ValueError("El archivo cambió después de la revisión previa")
                duplicate = db.execute("SELECT id, original_filename FROM uploads WHERE hash=? AND week_id=? AND active=1 AND removed_at IS NULL",
                                       (digest, key)).fetchone()
                if duplicate:
                    self.audit(db, key, "duplicado_rechazado", {"hash": digest, "upload_id": duplicate["id"]})
                    results.append({"status": "DUPLICADO", "name": candidate.path.name,
                                    "detail": f"Ya está activo como carga #{duplicate['id']}: {duplicate['original_filename']}"})
                    continue
                candidate.validate(week)
                logical_key = candidate.logical_key
                prior = db.execute("SELECT * FROM uploads WHERE week_id=? AND logical_key=? AND active=1",
                                   (key, logical_key)).fetchone()
                version = db.execute("SELECT COALESCE(MAX(version),0)+1 FROM uploads WHERE week_id=? AND logical_key=?",
                                     (key, logical_key)).fetchone()[0]
                active = candidate.kind in {"porcliente", "puntos"} or not prior or (candidate.coverage_start <= prior["coverage_start"] and
                                       candidate.coverage_end >= prior["coverage_end"])
                destination = self.folder(key) / candidate.kind / f"v{version}_{uuid4().hex}.xlsx"
                destination.parent.mkdir(parents=True, exist_ok=True)
                # Un fallo de BD puede dejar una copia huérfana; nunca se consume sin índice.
                with candidate.path.open("rb") as source, destination.open("xb") as target:
                    shutil.copyfileobj(source, target)
                if file_hash(destination) != digest:
                    raise ValueError("No coincide el hash de la copia guardada")
                if active:
                    db.execute("UPDATE uploads SET active=0 WHERE week_id=? AND logical_key=?", (key, logical_key))
                    if candidate.kind == "puntos":
                        db.execute("UPDATE uploads SET active=0 WHERE week_id=? AND type='puntos' AND branch=?", (key, candidate.branch))
                cursor = db.execute("""INSERT INTO uploads(week_id,type,logical_key,file_path,original_filename,hash,
                    detected_start_date,detected_end_date,coverage_start,coverage_end,branch,version,active,metadata,uploaded_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (key, candidate.kind, logical_key, str(destination), candidate.path.name, digest,
                     candidate.detected_start, candidate.detected_end, candidate.coverage_start, candidate.coverage_end,
                     candidate.branch, version, int(active), json.dumps(candidate.metadata, ensure_ascii=False), timestamp()))
                self.audit(db, key, "nueva_version" if version > 1 else "upload",
                           {"id": cursor.lastrowid, "hash": digest, "version": version, "active": bool(active)})
                if active:
                    self.audit(db, key, "cambio_activa", {"id": cursor.lastrowid, "previous": prior["id"] if prior else None})
                    self.changed(db, key)
                results.append({"status": "ACTIVA" if active else "HISTÓRICA (rango menor o diferente)",
                                "id": cursor.lastrowid, "version": version, "name": candidate.path.name})
        return results

    def remove_uploads(self, key, upload_ids, expected_revision=None):
        ids = list(dict.fromkeys(upload_ids))
        if not ids:
            raise ValueError("Seleccioná al menos una carga")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.assert_open(db, key, expected_revision)
            rows = []
            for upload_id in ids:
                row = db.execute("SELECT * FROM uploads WHERE id=? AND week_id=? AND removed_at IS NULL",
                                 (upload_id, key)).fetchone()
                if row is None:
                    raise ValueError("Una carga ya fue eliminada o no pertenece a esta semana. Actualizá la pantalla")
                rows.append(row)
            removed_at = timestamp()
            for row in rows:
                db.execute("UPDATE uploads SET active=0, removed_at=? WHERE id=?", (removed_at, row["id"]))
                self.audit(db, key, "eliminar_carga", {"id": row["id"], "nombre": row["original_filename"],
                           "era_activa": bool(row["active"]), "archivo_conservado": row["file_path"]})
            self.changed(db, key)

    def activate(self, key, upload_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.assert_open(db, key)
            row = db.execute("SELECT * FROM uploads WHERE id=? AND week_id=?", (upload_id, key)).fetchone()
            if not row:
                raise ValueError("Archivo inexistente")
            if row["removed_at"]:
                raise ValueError("Esta carga fue eliminada. Podés subir el Excel nuevamente")
            if file_hash(row["file_path"]) != row["hash"]:
                raise ValueError("El archivo guardado fue modificado fuera de la aplicación")
            db.execute("UPDATE uploads SET active=0 WHERE week_id=? AND logical_key=?", (key, row["logical_key"]))
            if row["type"] == "puntos":
                db.execute("UPDATE uploads SET active=0 WHERE week_id=? AND type='puntos' AND branch=?", (key, row["branch"]))
            db.execute("UPDATE uploads SET active=1 WHERE id=?", (upload_id,))
            self.audit(db, key, "cambio_activa", {"id": upload_id, "explicit": True})
            self.changed(db, key)

    def save_review(self, key, payload, expected_revision):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.assert_open(db, key, expected_revision)
            path = self.folder(key) / "auditoria" / f"revision_{uuid4().hex}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json(path, payload)
            self.changed(db, key)
            revision = expected_revision + 1
            db.execute("INSERT INTO reviews(week_id,source_revision,file_path,payload,created_at) VALUES(?,?,?,?,?)",
                       (key, revision, str(path), json.dumps(payload, ensure_ascii=False), timestamp()))
            self.audit(db, key, "confirmar_revision", {"path": str(path), "revision": revision})
        return path

    def latest_review(self, key):
        rows = self.query("SELECT * FROM reviews WHERE week_id=? ORDER BY id DESC LIMIT 1", (key,))
        return rows[0] if rows else None

    def liquidations(self, key):
        return self.query("""SELECT s.*, (SELECT COUNT(*) FROM uploads u WHERE u.week_id=s.week_id
            AND u.type='liquidacion' AND u.active=1 AND u.coverage_start=s.date) AS count_uploaded
            FROM liquidation_day_status s WHERE week_id=? ORDER BY date""", (key,))

    def confirm_liquidations(self, key, day, note=""):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.assert_open(db, key)
            day = as_date(day).isoformat()
            if not db.execute("SELECT 1 FROM liquidation_day_status WHERE week_id=? AND date=?", (key, day)).fetchone():
                raise ValueError("Jornada fuera de semana")
            count = db.execute("SELECT COUNT(*) FROM uploads WHERE week_id=? AND type='liquidacion' AND active=1 AND coverage_start=?",
                               (key, day)).fetchone()[0]
            if not count and not note.strip():
                raise ValueError("Sin archivos, explicá por qué no hubo liquidaciones/repartos")
            db.execute("""UPDATE liquidation_day_status SET confirmed_complete=1,confirmed_at=?,
                count_at_confirmation=?,note=? WHERE week_id=? AND date=?""", (timestamp(), count, note, key, day))
            self.audit(db, key, "confirmar_liquidaciones", {"date": day, "count": count, "note": note})

    def save_snapshot(self, key, data, kind="procesado", close=False):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            week = self.assert_open(db, key, data["source_revision"])
            awards = data.get("awards")
            if awards and awards["revision"] != db.execute("SELECT revision FROM reward_meta WHERE id=1").fetchone()[0]:
                raise ValueError("Los premios cambiaron durante el cálculo; actualizá antes de guardar")
            path = self.folder(key) / "procesado" / f"{kind}_{uuid4().hex}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json(path, data)
            db.execute("INSERT INTO snapshots(week_id,kind,source_revision,file_path,hash,created_at) VALUES(?,?,?,?,?,?)",
                       (key, kind, week["revision"], str(path), file_hash(path), timestamp()))
            if close:
                db.execute("UPDATE weeks SET status='CERRADA',closed_at=? WHERE id=?", (timestamp(), key))
            if awards:
                from app.rewards import write_results
                write_results(db,key,awards)
            self.audit(db, key, "cierre_semana" if close else "procesar_semana", {"snapshot": str(path)})
        return path

    def reopen(self, key, reason):
        if not reason.strip():
            raise ValueError("Indicá el motivo de reapertura")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT status FROM weeks WHERE id=?", (key,)).fetchone()[0] != "CERRADA":
                raise ValueError("La semana no está cerrada")
            db.execute("UPDATE weeks SET status='REABIERTA',reopened=1 WHERE id=?", (key,))
            self.changed(db, key)
            self.audit(db, key, "reabrir_semana", {"reason": reason})

    def snapshots(self, key):
        return self.query("SELECT * FROM snapshots WHERE week_id=? ORDER BY id DESC", (key,))

    def scan_legacy(self):
        """Indexación no destructiva: no activa ni suma cargas históricas entre sí."""
        history = self.root / "HISTORIAL"
        if not history.exists():
            return
        for folder in history.iterdir():
            try:
                day = as_date(folder.name)
            except ValueError:
                continue
            if not folder.is_dir():
                continue
            week = self.ensure_week(day)
            with self.connect() as db:
                for load in folder.glob("carga_*"):
                    if load.is_dir():
                        db.execute("INSERT OR IGNORE INTO legacy_loads VALUES(?,?,?)", (str(load), week["id"], day.isoformat()))

"""Initialize the unified installation without selecting an old warehouse file."""
from contextlib import closing
from pathlib import Path
import sqlite3
import os
import tempfile

from models.database import DatabaseManager
from models.shop_schema import initialize_shop_schema


def initialize_application(path):
    path = Path(path).resolve()
    if path.exists():
        with closing(sqlite3.connect(path)) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='application_schema'").fetchone():
                raise ValueError('application_migration_required')
            initialize_shop_schema(db)
        return str(path)
    if (path.parent/'User Stories/qa-runtime/qa.db').exists() or (path.parent/'accounts.db').exists():
        raise ValueError('application_migration_required')
    path.parent.mkdir(parents=True,exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.new-application-',suffix='.db',dir=path.parent)
    os.close(descriptor)
    staging = Path(name)
    try:
        DatabaseManager(str(staging))
        with closing(sqlite3.connect(staging)) as db:
            initialize_shop_schema(db)
        os.link(staging,path)
    finally:
        staging.unlink(missing_ok=True)
    return str(path)

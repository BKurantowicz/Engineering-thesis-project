"""Preserve and adapt the selected legacy database without in-place source writes."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from models.database import DatabaseManager
from models.shop_schema import initialize_shop_schema


class MigrationConflict(ValueError):
    pass


def readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)


def inventory(db):
    """Compare every original business value, including blobs and saved documents."""
    result = {}
    tables = [r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    for table in tables:
        quoted = '"' + table.replace('"', '""') + '"'
        columns = [r[1] for r in db.execute(f'PRAGMA table_info({quoted})')]
        rows = sorted(db.execute(f'SELECT * FROM {quoted}').fetchall(), key=repr)
        result[table] = (columns, rows)
    return result


def verify_preserved(before, db):
    for table, (columns, expected) in before.items():
        quote = lambda value: '"' + value.replace('"', '""') + '"'
        actual = sorted(db.execute(f'SELECT {",".join(map(quote, columns))} FROM {quote(table)}').fetchall(), key=repr)
        if actual != expected:
            raise MigrationConflict('business_values_changed:' + table)
    if db.execute('PRAGMA foreign_key_check').fetchone():
        raise MigrationConflict('foreign_key_conflict')
    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise MigrationConflict('database_integrity_conflict')


def validate_source(before):
    for table,field,key in (('products','sku','product_id'),('customers','email','customer_id')):
        if table not in before:
            raise MigrationConflict('missing_source_table:'+table)
        columns,rows = before[table]
        seen = {}
        for row in rows:
            value = row[columns.index(field)]
            normalized = str(value or '').strip().casefold()
            if not normalized:
                continue
            if normalized in seen:
                raise MigrationConflict(f'source_{field}_conflict:{seen[normalized]}:{row[columns.index(key)]}')
            seen[normalized] = row[columns.index(key)]


def _snapshot(source, target):
    with closing(readonly(source)) as original, closing(sqlite3.connect(target)) as backup:
        original.backup(backup)


def _accounts(source, target):
    if source is None:
        return 0
    with closing(readonly(source)) as accounts:
        columns = ('user_id','login','password_hash','role','must_change','version')
        try:
            rows = accounts.execute(f'SELECT {",".join(columns)} FROM accounts').fetchall()
        except sqlite3.Error as error:
            raise MigrationConflict('invalid_account_source') from error
    if target.execute('SELECT 1 FROM accounts').fetchone():
        raise MigrationConflict('account_sources_conflict')
    target.executemany(f'INSERT INTO accounts({",".join(columns)}) VALUES(?,?,?,?,?,?)', rows)
    target.executemany('INSERT INTO account_shops(user_id,shop_id) VALUES(?,1)', [(r[0],) for r in rows])
    return len(rows)


def complete_cutover(target, config_path, backup_dir, *, remove_obsolete=False):
    """Select the verified target and optionally remove only its obsolete sibling.

    Run after validating the adapted application. Preserve every unrelated config
    value and a byte-exact recovery copy; never remove the selected source.
    """
    from models.application_runtime import initialize_application
    target, config_path, backup_dir = (Path(p).resolve() for p in (target,config_path,backup_dir))
    if target.name != 'application.db' or config_path.parent != target.parent:
        raise MigrationConflict('invalid_cutover_paths')
    with closing(readonly(target)) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchone():
            raise MigrationConflict('cutover_integrity_conflict')
        source = Path(db.execute('SELECT source_path FROM migration_provenance').fetchone()[0]).resolve()
    initialize_application(target)
    original = config_path.read_bytes()
    configuration = json.loads(original.decode('utf-8'))
    configuration.setdefault('paths',{})['database'] = 'application.db'
    backup_dir.mkdir(parents=True,exist_ok=True)
    backup = backup_dir/f'config-before-shops-{hashlib.sha256(original).hexdigest()[:16]}.json'
    if backup.exists() and backup.read_bytes() != original:
        raise MigrationConflict('backup_conflict')
    if not backup.exists():
        with backup.open('xb') as stream:
            stream.write(original)
    obsolete = target.parent/'warehouse.db'
    if remove_obsolete and obsolete.resolve() == source:
        raise MigrationConflict('cannot_remove_selected_source')
    descriptor,name = tempfile.mkstemp(prefix='.config-',suffix='.json',dir=target.parent)
    staging = Path(name)
    published = False
    removed = False
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8') as stream:
            json.dump(configuration,stream,indent=4,ensure_ascii=False)
        os.replace(staging,config_path)
        published = True
        if remove_obsolete and obsolete.exists():
            obsolete.unlink()
            removed = True
    except BaseException:
        if published:
            staging.write_bytes(original)
            os.replace(staging,config_path)
        raise
    finally:
        staging.unlink(missing_ok=True)
    return {'configuration':str(config_path),'configuration_backup':str(backup),
            'obsolete_removed':removed}


def adapt_database(source, target, *, backup_dir, accounts=None, configuration=None):
    """Publish once, after comparison; a retry verifies provenance and never resets.

    Configuration is copied into the initial shop. This function does not modify
    config.json, remove the legacy database, or replace an existing target.
    """
    source, target, backup_dir = map(lambda p: Path(p).resolve(), (source, target, backup_dir))
    if not source.is_file() or source == target:
        raise MigrationConflict('invalid_migration_paths')
    if accounts is not None:
        accounts = Path(accounts).resolve()
        if not accounts.is_file() or accounts in (source, target):
            raise MigrationConflict('invalid_account_source')
    target.parent.mkdir(parents=True, exist_ok=True)
    backup_dir.mkdir(parents=True, exist_ok=True)
    descriptor, staging_name = tempfile.mkstemp(prefix='.application-', suffix='.db', dir=target.parent)
    os.close(descriptor)
    staging = Path(staging_name)
    try:
        _snapshot(source, staging)
        with closing(readonly(staging)) as original:
            if original.execute('PRAGMA quick_check').fetchone()[0] != 'ok' or original.execute('PRAGMA foreign_key_check').fetchone():
                raise MigrationConflict('source_integrity_conflict')
            before = inventory(original)
            validate_source(before)
        digest = hashlib.sha256(staging.read_bytes()).hexdigest()
        backup = backup_dir / f'qa-before-shops-{digest[:16]}.db'
        try:
            os.link(staging, backup)
        except FileExistsError:
            if hashlib.sha256(backup.read_bytes()).hexdigest() != digest:
                raise MigrationConflict('backup_conflict') from None
        # The backup must not share the inode that will be migrated.
        staging.unlink()
        _snapshot(backup, staging)
        if target.exists():
            with closing(readonly(target)) as existing:
                try:
                    row = existing.execute('SELECT source_digest FROM migration_provenance').fetchone()
                except sqlite3.Error:
                    row = None
                if row != (digest,):
                    raise MigrationConflict('existing_target_conflict')
                if existing.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or existing.execute('PRAGMA foreign_key_check').fetchone():
                    raise MigrationConflict('existing_target_integrity_conflict')
            return {'target': str(target), 'backup': str(backup), 'reused': True}
        DatabaseManager(str(staging))
        with closing(sqlite3.connect(staging)) as db:
            initialize_shop_schema(db)
            with db:
                count = _accounts(accounts, db)
                settings = {k: v for k, v in (configuration or {}).items() if k in ('company', 'company_info', 'email_smtp')}
                db.execute('UPDATE shop_settings SET configuration=? WHERE shop_id=1', (json.dumps(settings, ensure_ascii=False),))
                verify_preserved(before, db)
                db.execute('''CREATE TABLE migration_provenance(
                    source_path TEXT NOT NULL, source_digest TEXT NOT NULL, backup_path TEXT NOT NULL,
                    account_source TEXT, migrated_accounts INTEGER NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
                db.execute('INSERT INTO migration_provenance(source_path,source_digest,backup_path,account_source,migrated_accounts) VALUES(?,?,?,?,?)',
                           (str(source), digest, str(backup), str(accounts) if accounts else None, count))
        # Exclusive publication: never overwrite another process's or the leader's target.
        try:
            os.link(staging, target)
        except FileExistsError:
            raise MigrationConflict('existing_target_conflict') from None
        return {'target': str(target), 'backup': str(backup), 'reused': False,
                'tables_verified': len(before), 'accounts_migrated': count}
    finally:
        staging.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--backup-dir', required=True)
    parser.add_argument('--accounts')
    parser.add_argument('--config')
    parser.add_argument('--cutover',action='store_true')
    parser.add_argument('--remove-obsolete',action='store_true')
    args = parser.parse_args()
    if args.cutover and not args.config or args.remove_obsolete and not args.cutover:
        parser.error('--cutover requires --config; --remove-obsolete requires --cutover')
    configuration = json.loads(Path(args.config).read_text(encoding='utf-8')) if args.config else None
    result = adapt_database(args.source, args.target, backup_dir=args.backup_dir,
                            accounts=args.accounts, configuration=configuration)
    if args.cutover:
        result.update(complete_cutover(args.target,args.config,args.backup_dir,remove_obsolete=args.remove_obsolete))
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()

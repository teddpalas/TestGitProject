"""Export private migration state only while the local bot is stopped.

Run from the project directory with its virtual-environment Python. The output
contains credentials: transfer directly to the destination over SSH, never Git.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tarfile
import tempfile

from rentbot.config import Settings, load_env
from rentbot.service import single_instance


def sqlite_backup(source: Path, target: Path) -> None:
    with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as original:
        with closing(sqlite3.connect(target)) as snapshot:
            original.backup(snapshot)
            if snapshot.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Database integrity check failed')


def export(output: Path) -> None:
    load_env()
    settings = Settings.from_env()
    if settings.validate():
        raise RuntimeError('Local configuration is incomplete')
    source_files = {
        'data/reader.session': Path(settings.session_path + '.session'),
        'data/rentbot.sqlite3': settings.data_dir / 'rentbot.sqlite3',
    }
    if not Path('.env').is_file() or any(not path.is_file() for path in source_files.values()):
        raise RuntimeError('Required local state is missing')
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    # Keep this lock until the snapshot is complete; another reader must not run.
    with single_instance(settings.data_dir / 'run.lock'):
        with tempfile.TemporaryDirectory(prefix='rentbot-migration-', dir=output.parent) as directory:
            staging = Path(directory)
            (staging / 'data').mkdir()
            for archive_path, source in source_files.items():
                sqlite_backup(source, staging / archive_path)
            shutil.copyfile('.env', staging / '.env')
            if settings.locations_file.is_file():
                shutil.copyfile(settings.locations_file, staging / 'data/locations.json')
            (staging / 'migration.json').write_text(json.dumps({
                'created_at': datetime.now(timezone.utc).isoformat(),
                'format_version': 1,
            }), encoding='utf-8')
            # Exclusive create prevents accidental replacement of an earlier backup.
            with output.open('xb') as stream:
                os.chmod(output, 0o600)
                with tarfile.open(fileobj=stream, mode='w:gz') as archive:
                    for source in sorted(staging.rglob('*')):
                        if source.is_file():
                            info = archive.gettarinfo(str(source), source.relative_to(staging).as_posix())
                            info.mode = 0o600
                            info.uid = info.gid = 0
                            info.uname = info.gname = ''
                            with source.open('rb') as content:
                                archive.addfile(info, content)
    print('PRIVATE_STATE_EXPORTED; keep the local bot stopped during migration')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        export(args.output)
    except Exception as error:
        print('STATE_EXPORT_FAILED:', type(error).__name__)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

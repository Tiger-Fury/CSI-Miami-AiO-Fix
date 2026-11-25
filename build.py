#!/usr/bin/env python3
"""Rebuild Tiger Fury's CSI: Miami fix from hash-verified original files."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


def patch(original, spec):
    if sha(original) != spec['input_sha256']:
        raise ValueError('Patch input hash mismatch')
    previous_end = 0
    for edit in spec['edits']:
        offset, count = edit['offset'], edit['delete']
        if offset < previous_end or count < 0 or offset + count > len(original):
            raise ValueError('Invalid/overlapping patch range')
        bytes.fromhex(edit['hex'])
        previous_end = offset + count
    result = bytearray(original)
    for edit in reversed(spec['edits']):
        start = edit['offset']
        result[start:start + edit['delete']] = bytes.fromhex(edit['hex'])
    if len(result) != spec['output_size'] or sha(result) != spec['output_sha256']:
        raise ValueError('Patched output verification failed')
    return bytes(result)


def archive(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, (2026, 11, 25, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    result = buf.getvalue()
    with zipfile.ZipFile(io.BytesIO(result)) as z:
        if z.testzip() is not None:
            raise ValueError('ZIP integrity check failed')
        for name, data in files.items():
            if z.read(name) != data:
                raise ValueError('ZIP payload mismatch')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path, required=True, help='Matching unmodified full game installation (read-only input)')
    parser.add_argument('--output', type=Path, required=True, help='New or empty output folder outside the game installation')
    args = parser.parse_args()
    game, output = args.game.resolve(), args.output.resolve()
    if output == game or game in output.parents or output in game.parents:
        parser.error('Output must be separate from the game input')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error('Output must be new or empty; existing files will not be overwritten')
    manifest = json.loads((ROOT / 'patches/miami-1.0.0.json').read_text())
    originals = {}
    for key, name in manifest['inputs'].items():
        path = game / name
        if not path.is_file():
            parser.error('Missing required input: ' + name)
        originals[key] = path.read_bytes()
        if sha(originals[key]) != manifest['input_sha256'][key]:
            parser.error('Unrecognised or already-modified original: ' + name)
    modified = {key: patch(originals[spec['input']], spec) for key, spec in manifest['patches'].items()}
    relative_library = manifest['inputs']['library']
    relative_renderer = manifest['inputs']['renderer']
    rollback = archive({relative_library: originals['library'], relative_renderer: originals['renderer']})
    common = {relative_library: modified['library'], relative_renderer: modified['renderer'], 'Rollback-original-shared-files.zip': rollback}
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    report = {'version': manifest['version'], 'credit': 'Made by Tiger Fury', 'validation': 'Original, Fit and Fill reported working by the project tester; rebuilt payload hashes verified', 'packages': []}
    output.mkdir(parents=True, exist_ok=True)
    for mode in ['Original', 'Fit', 'Fill']:
        launcher = 'CSI-Miami.exe' if mode == 'Original' else f'CSI-Miami-{mode}.exe'
        exe = originals['exe'] if mode == 'Original' else modified['exe-' + mode.lower()]
        files = dict(common)
        files[launcher] = exe
        files[launcher[:-4] + '.ini'] = b'[Settings]\r\nSingleInstance=1\r\n[Lingo]\r\nDisplayFullLingoErrorText=1\r\nMessageWindow=0\r\n'
        files['README.md'] = (f'# {mode} package — version {manifest["version"]}\n\nLaunch **{launcher}** after installation.\n\n' + readme).encode('utf-8')
        checksums = {name: sha(data) for name, data in files.items()}
        files['SHA256SUMS.txt'] = ''.join(h + '  ' + name + '\n' for name, h in sorted(checksums.items())).encode()
        folder = output / mode
        folder.mkdir()
        for name, data in files.items():
            target = folder / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        name = f'CSI-Miami-{mode}-v{manifest["version"]}.zip'
        data = archive(files)
        (output / name).write_bytes(data)
        report['packages'].append({'mode': mode, 'file': name, 'sha256': sha(data), 'bytes': len(data), 'launcherSha256': sha(exe), 'librarySha256': sha(modified['library']), 'rendererSha256': sha(modified['renderer'])})
    (output / 'SHA256SUMS.txt').write_text(''.join(p['sha256'] + '  ' + p['file'] + '\n' for p in report['packages']), encoding='utf-8')
    (output / 'release-manifest.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    # Confirm source files remained unchanged after all packaging operations.
    for key, name in manifest['inputs'].items():
        if sha((game / name).read_bytes()) != manifest['input_sha256'][key]:
            raise ValueError('Input changed during build: ' + name)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()

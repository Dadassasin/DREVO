"""Decode private GitHub JSON parts into a JPEG, without any external image URL.

Usage: python decode_image_payload.py response.json downloaded-parts-folder output.jpg
Each part may be stored under its part-NNNN.json name or its full repository path.
"""
import base64
import hashlib
import json
from pathlib import Path
import re
import sys


def assemble(response, load_part):
    payload = response['image_payload']
    if response['status'] != 'completed' or payload['delivery'] != 'github_base64_parts':
        raise ValueError('Response is not a completed GitHub byte payload')
    identifier = response['request_id']
    if not re.fullmatch(r'[a-f0-9-]{36}', identifier):
        raise ValueError('Invalid request_id')
    parts = payload['parts']
    if not 0 < len(parts) == payload['part_count'] <= 489 or not 0 < payload['bytes'] <= 2_000_000:
        raise ValueError('Invalid byte/part limit')
    output = bytearray()
    for index, descriptor in enumerate(parts):
        path = f'responses/images/{identifier}/part-{index:04d}.json'
        if descriptor['path'] != path or descriptor['index'] != index or descriptor['offset'] != len(output):
            raise ValueError('Part order, path or offset mismatch')
        part = load_part(path)
        if part['request_id'] != identifier or part['encoding'] != 'base64':
            raise ValueError('Wrong request or encoding')
        for field in ('index', 'offset', 'bytes', 'sha256'):
            if part[field] != descriptor[field]:
                raise ValueError('Part metadata mismatch: ' + field)
        if not 0 < part['bytes'] <= 49152 or len(part['data']) > 65536:
            raise ValueError('Part size limit exceeded')
        chunk = base64.b64decode(part['data'], validate=True)
        if len(chunk) != part['bytes'] or hashlib.sha256(chunk).hexdigest() != part['sha256']:
            raise ValueError('Part SHA-256 or byte size mismatch')
        output.extend(chunk)
        if len(output) > 2_000_000:
            raise ValueError('Image too large')
    data = bytes(output)
    if len(data) != payload['bytes'] or hashlib.sha256(data).hexdigest() != payload['sha256']:
        raise ValueError('Image SHA-256 or byte size mismatch')
    if payload['mime_type'] != 'image/jpeg' or not data.startswith(b'\xff\xd8') or not data.endswith(b'\xff\xd9'):
        raise ValueError('Not a JPEG')
    return data


def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    response = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))
    folder = Path(sys.argv[2])
    def load(path):
        nested = folder / path
        target = nested if nested.is_file() else folder / Path(path).name
        return json.loads(target.read_text(encoding='utf-8-sig'))
    data = assemble(response, load)
    Path(sys.argv[3]).write_bytes(data)
    print(json.dumps({'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'output': sys.argv[3]}))


if __name__ == '__main__':
    main()

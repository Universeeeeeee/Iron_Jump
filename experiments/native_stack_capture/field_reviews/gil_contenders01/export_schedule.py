"""Re-export an existing ETL with the existing reader; never enables tracing."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

EXPECTED = '0e0c71ccd8f77f09075d35bdc1936a5d02290624f6765a6acd14d42881067523'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(args):
    assert sha(args.etl) == EXPECTED
    argv = [str(args.reader), str(args.etl), '17752', args.tids, str(args.output / 'decoded')]
    subprocess.run(argv, check=True)
    decoded = args.output / 'decoded'
    with (decoded / 'events.jsonl').open() as source, gzip.open(args.output / 'schedule01.jsonl.gz', 'xt') as out:
        for line in source:
            event = json.loads(line)
            if event['provider'].startswith('3d6fa8d1'):
                out.write(line)
    assert sha(args.etl) == EXPECTED
    result = dict(etl_sha256=EXPECTED, reader_sha256=sha(args.reader), command=argv,
                  requested_tids=list(map(int, args.tids.split(','))),
                  script_sha256=sha(Path(__file__)),
                  files={name: sha(args.output / name) for name in
                         ('schedule01.jsonl.gz', 'decoded/events.jsonl', 'decoded/metadata.json')},
                  metadata=json.loads((decoded / 'metadata.json').read_text()),
                  scope='Offline expansion of thread scheduling coverage only. Original calibration/quality failures remain unchanged; no thread counters are invented for added TIDs.')
    with (args.output / 'export01.json').open('x') as out:
        json.dump(result, out, indent=2)
        out.write('\n')
    print('Expanded offline thread count:', len(result['requested_tids']))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--etl', type=Path, required=True)
    parser.add_argument('--reader', type=Path, required=True)
    parser.add_argument('--tids', required=True)
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args())

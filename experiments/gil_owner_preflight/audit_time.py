"""Offline audit only: fixed-weight profiles do not supply sample timestamps."""
import argparse
import hashlib
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(raw):
    review = read(HERE / 'review01.json')
    for name in ('records01.json', 'plan01.json'):
        assert sha(HERE / name) == review['artifact_sha256'][name]
    records = read(HERE / 'records01.json')
    plan = read(HERE / 'plan01.json')
    rows = []
    for mode in plan['controls']:
        path = raw / mode / 'profile.json'
        relative = 'run01/' + mode + '/profile.json'
        assert sha(path) == review['raw_evidence']['files_sha256'][relative]
        record = records[mode]
        bracket = record['sampler_bracket_ns']
        for profile in read(path)['profiles']:
            count = len(profile['samples'])
            assert len(profile['weights']) == count
            assert profile['unit'] == 'seconds' and profile['startValue'] == 0
            assert all(math.isclose(w, 1 / plan['sample_rate_hz']) for w in profile['weights'])
            assert math.isclose(profile['endValue'], count / plan['sample_rate_hz'])
            rows.append(dict(control=mode, thread=profile['name'], samples=count,
                displayed_seconds=profile['endValue'],
                external_process_bracket_seconds=(bracket[1] - bracket[0]) / 1e9,
                source_sha256=sha(path)))
    return dict(rows=rows, absolute_sample_timestamps_available=False,
        interpolate_sample_index_to_QPC_allowed=False,
        explanation='Each retained sample has weight 1/rate. Filtered gaps and observer startup are not represented. '
                    'Only the entire externally recorded sampler bracket can bound these observations; '
                    'weights do not locate a sample inside it or measure a continuous GIL hold.',
        held_released_correctness_results_changed=False,
        field_owner_identified=False, quantitative_field_attribution_ready=False,
        inputs_sha256={name: sha(HERE / name) for name in ('plan01.json', 'records01.json', 'review01.json')})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--raw', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.raw)
    with args.output.open('x') as out:
        json.dump(result, out, indent=2)
        out.write('\n')

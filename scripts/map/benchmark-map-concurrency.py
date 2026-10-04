#!/usr/bin/env python3
"""Compare immutable Map binaries on identical live QScrape bounds."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
import time


def signature(outcome):
    pages = sorted((page['url'], page['minimum_link_depth'], json.dumps(page['exploration'], sort_keys=True)) for page in outcome['pages'])
    edges = sorted(json.dumps(edge, sort_keys=True) for edge in outcome['relationships'])
    return {'pages': pages, 'relationships': edges, 'termination': outcome['termination']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rounds', type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.rounds <= 5:
        parser.error('rounds must be between one and five')
    args.output.mkdir(parents=True, exist_ok=True)
    cases = [('baseline', args.baseline.resolve(), 1), ('one', args.candidate.resolve(), 1),
             ('two', args.candidate.resolve(), 2), ('four', args.candidate.resolve(), 4)]
    records = []
    expected = None
    with tempfile.TemporaryDirectory() as config:
        env = os.environ.copy()
        env['XDG_CONFIG_HOME'] = config
        for round_index in range(args.rounds):
            ordered = cases if round_index % 2 == 0 else list(reversed(cases))
            for label, binary, concurrency in ordered:
                prefix = args.output / f'{round_index + 1}-{label}'
                command = [str(binary), 'map', 'https://qscrape.dev/', '--depth', '5',
                           '--max-requests', '1000', '--timeout-ms', '180000',
                           '--max-concurrency', str(concurrency), '--json', '--stats']
                started = time.monotonic()
                with prefix.with_suffix('.json').open('wb') as output:
                    completed = subprocess.run(command, env=env, stdout=output,
                                               stderr=subprocess.PIPE, timeout=200)
                elapsed = time.monotonic() - started
                prefix.with_suffix('.stderr').write_bytes(completed.stderr)
                outcome = json.loads(prefix.with_suffix('.json').read_bytes())
                actual = signature(outcome)
                if expected is None:
                    expected = actual
                record = {'round': round_index + 1, 'case': label, 'concurrency': concurrency,
                          'elapsed_seconds': elapsed, 'exit': completed.returncode,
                          'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                          'policy_identity': outcome['policy_identity'], 'limits': outcome['map_policy']['limits'],
                          'summary': outcome['summary'], 'same_inventory_and_graph': actual == expected,
                          'inspected': sum(page['exploration']['status'] == 'inspected' for page in outcome['pages']),
                          'termination': outcome['termination']}
                records.append(record)
                (args.output / 'runs.json').write_text(json.dumps(records, indent=2) + '\n')
                print(json.dumps(record), flush=True)
                if completed.returncode not in (0, 3) or actual != expected:
                    raise RuntimeError(f'coverage, graph, state or termination changed in {label}; inspect saved JSON')
    medians = {label: statistics.median(record['elapsed_seconds'] for record in records if record['case'] == label)
               for label, _, _ in cases}
    report = {'medians_seconds': medians, 'speedup_from_original': {
        label: medians['baseline'] / elapsed for label, elapsed in medians.items()},
        'runs': records, 'note': 'Live HTTP timings; alternating order, equal inventory/graph gate, no universal speed guarantee.'}
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'medians_seconds': medians, 'speedup_from_original': report['speedup_from_original']}, indent=2))


if __name__ == '__main__':
    main()

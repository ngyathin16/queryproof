"""Materialize the agent's reviewed case/mode rubric decisions for every retained trial.

Assignments below follow inspection of the complete, unique explanation texts and
executed evidence. They are a review record, not a general-purpose prose grader.
"""
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent / 'v2' / 'pinned-model-comparison'

MISLEADING_TOOLS = {
    'v2-attributions-unknown-row-loss': 'Calls COALESCE preservation of NULL semantics. That substitution only happens to leave these nonempty fixture groups unchanged; the broader null claim is misleading.',
    'v2-subscriptions-repeated-branch': 'Describes a one-to-many tags relationship as many-to-one; the returned revision also fails executed semantic checks.',
    'v2-readings-unknown-row-loss': 'Claims to remove an enabled WHERE filter, but the original query contains no enabled filter.',
    'v2-inventory-repeated-branch': 'Claims removal of a nonexistent sku join reference; the original join uses warehouse and the base schema does contain sku.',
}


def main():
    raw = (ROOT / 'model-trials.jsonl').read_bytes()
    trials = [json.loads(line) for line in raw.splitlines()]
    if len(trials) != 144:
        raise SystemExit('Review requires all 144 scheduled trials; do not publish partial denominators.')
    records = []
    for trial in trials:
        proposal = trial['assistance'].get('proposal')
        record = {key: trial[key] for key in ('case_id', 'mode', 'trial')}
        if proposal is None:
            record.update(explanation=None, supported='unavailable', intent_preserved='unavailable', limits_stated='unavailable', actionable='unavailable', notes='No completed explanation; provider failure retained in denominator: ' + str(trial['assistance'].get('error', 'failed')))
        else:
            record['explanation'] = proposal['explanation']
            correct = trial['grade']['success']
            if trial['mode'] == 'baseline':
                supported = correct
                notes = 'The population-filter change agrees with the contract and executed result.' if correct else 'The explanation endorses an incorrect query or claims irrelevant floating-point casts are the needed repair; executed evidence contradicts the diagnosis.'
                actionable = correct or trial['case_id'].startswith('v2-subscriptions-') or trial['case_id'] == 'v2-sessions-unknown-denominator'
            else:
                supported = trial['case_id'] not in MISLEADING_TOOLS and correct
                notes = MISLEADING_TOOLS.get(trial['case_id'], 'The stated query operation and reason agree with the recorded revision and executed findings.' if correct else 'The claimed repair does not satisfy the executed checks.')
                actionable = True
            record.update(supported='pass' if supported else 'fail', intent_preserved='pass' if correct else 'fail',
                          limits_stated='unclear', actionable='pass' if actionable else 'fail',
                          notes=notes + ' No explicit snapshot limitation appears in this explanation; the UI supplies a separate limitation notice.')
        records.append(record)
    report = {'reviewer': 'OpenAI Codex agent, 17 November 2026; not human or blinded review',
              'method': 'Read unique explanation texts against original SQL, schema, contract and executed grades; apply the same case/mode assessment to repeated explanations; retain failures as unavailable. The per-case decisions are inspectable in review_v2_explanations.py.',
              'source_sha256': hashlib.sha256(raw).hexdigest(),
              'rubric': {'supported': 'Factual claims follow executed evidence, original SQL and declared relationships.',
                         'intent_preserved': 'Executed groups/population and semantic checks agree on this snapshot.',
                         'limits_stated': 'Explicitly conditional on this snapshot/contract; no universal-proof claim.',
                         'actionable': 'Names the query operation to change and why.'},
              'trials': len(records),
              'counts_by_mode': {mode: {dimension: dict(Counter(r[dimension] for r in records if r['mode'] == mode)) for dimension in ('supported', 'intent_preserved', 'limits_stated', 'actionable')} for mode in ('baseline', 'tools')},
              'records': records}
    (ROOT / 'explanation-review.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report['counts_by_mode'], indent=2))


if __name__ == '__main__':
    main()

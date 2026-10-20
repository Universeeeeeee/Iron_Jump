"""Synthesize retained P0/P1 evidence without starting a workload."""
import hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    sources={
      'pmc':ROOT/'experiments/pmc_accounting_scope_review/conclusion02.json',
      'timed':ROOT/'experiments/vision_process_timed_ab/evidence/completed_plan03_summary.json',
      'spacing':ROOT/'experiments/slow_state_spacing/result01.json',
      'qt_gil':ROOT/'experiments/native_thread_accounting_review/qt_label_wait_summary01.json',
      'preview_bridge':ROOT/'experiments/preview_gil_ab/result01.json',
      'cold_process':ROOT/'experiments/cold_boot_vision_process_ab/evidence/two_window_result03.json',
      'consumer_capacity':ROOT/'experiments/consumer_capacity_synthesis/result01.json',
      'batch40':ROOT/'experiments/consumer_batch40_candidate/evidence/summary01.json',
      'field':ROOT/'experiments/p1_field_reentry_review/result01.json'}
    values={name:read(path) for name,path in sources.items()};pmc=values['pmc'];timed=values['timed'];spacing=values['spacing']
    assert abs(pmc['unresolved_residual_ms']-83.5967)<1e-6 and not pmc['original_four_window_usability']['frozen_cross_state_quantitative_attribution']
    assert timed['decision']['advance'] is False and timed['decision']['aa_stable'] is False
    assert spacing['controlled_five_minute_condition_supported'] is False
    assert values['cold_process']['process_first_severe'] is True
    matrix=[
      dict(question='Is the old PMC CPU share quantitatively usable?',finding='No',evidence='83.5967ms remains unresolved after lifecycle, clipping, duplicate and clock checks; old 31.25ms gate remains failed.',grade='verified boundary',next='Do not compute CPU/GIL/cache/frequency contribution shares from the old four windows.'),
      dict(question='Where does field latency accumulate?',finding='Host consumer FIFO before publication/paint',evidence='1000Hz receipt remained accurate while pending age and contact-to-paint reached seconds; final drain does not restore real-time compliance.',grade='verified',next='Keep FIFO age and scheduled contact-to-paint as field endpoints.'),
      dict(question='Is a real GIL/Qt synchronization path present?',finding='Yes, as an additive mechanism',evidence='Consumer take_gil chains and Qt QLabel/latch overlap are retained; waiter stacks do not identify the holder or quantitative share.',grade='verified mechanism, unquantified contribution',next='Do not relabel all waiting or wall-minus-CPU as GIL.'),
      dict(question='Does video+MediaPipe process isolation give stable fast-state benefit?',finding='No meaningful stable benefit',evidence='Four timed pairs changed latency -3.6%, +0.9%, +5.5%, -5.3%; geometric change -0.69%, with process queue lower bounds slightly higher in all pairs.',grade='rejected in fast state',next='Do not optimize or merge this boundary based on fast windows.'),
      dict(question='Is video+MediaPipe process isolation sufficient in a severe cold-first window?',finding='No',evidence='The process-first cold window still reached queue lower/upper 1614/1694 and scheduled contact-to-paint 1491ms with input lateness 93ms.',grade='rejected as a sufficient fix',next='Return to consumer worst-state service capacity; do not add more visual isolation windows.'),
      dict(question='Does isolating the consumer close the capacity deficit?',finding='Mostly, but not to acceptance',evidence='Whole-contact service rose to994.7fps, but the first2.27s ran at846.8fps, peaked346 frames and reached646ms before recovering at1129fps.',grade='supported primary software boundary; insufficient fix',next='Localize at least5% or0.056ms/frame in the isolated early phase.'),
      dict(question='Does reducing isolated-consumer Qt wake frequency close the retained gap?',finding='Yes for saved input',evidence='Batch cap40 produced queue lower/upper51/117, scheduled contact-to-paint207.6ms and input lateness79.8ms with exact reports.',grade='saved-input candidate pass',next='Productionize consumer isolation plus batch40; then perform one real single-USB Walk acceptance.'),
      dict(question='Do model and consumer share a slow execution state?',finding='Strong covariance',evidence='Severe A/A model medians were 40.5-40.8ms with queue lower 3981-4239; fast A/A model medians 23.1-23.9ms with queue lower 91, while work counts differed only 3-4%. PMC also retained Core/OS about1.00 slow versus1.66-1.68 fast.',grade='supported common-state hypothesis',next='Name only execution-delivery state; frequency, cache, power, thermal and exact native function remain unknown.'),
      dict(question='Do process restart or five-minute quiet gaps control the state?',finding='No',evidence='Six fixed-work windows stayed slow across 5s and qualified 300s low-load gaps; other GUI sequences recovered after two windows.',grade='rejected as sufficient conditions',next='Do not add ordinary spacing windows.')]
    ranking=[
      dict(rank=1,hypothesis='Consumer sharing the GUI process lacks worst-state synchronization/scheduling margin',status='strongest actionable boundary; isolation restores sustained rate but leaves a transient'),
      dict(rank=2,hypothesis='Shared native/CPU execution-delivery state and input-dependent work amplify the early deficit',status='supported covariance; mechanism unnamed'),
      dict(rank=3,hypothesis='Moving video/model alone controls severe backlog',status='rejected as sufficient in a severe process-first cold window'),
      dict(rank=4,hypothesis='USB/grating power state is the primary cause',status='weak field correlation only; host saved-input severe state exists without live USB')]
    capacity=dict(scope='Productionize the saved-input-passing consumer-process plus batch40 boundary behind a reversible ground-mode controller.',
      requirements=['live USB frames delivered in order without loss or coalescing','same quality/filter/Processor/report semantics and bad-beam handling','bounded commands/output transport and confirmed child shutdown','existing lifecycle, walking, report and UI tests pass'],
      field_acceptance=['single USB Walk reproduces 1000Hz input','FIFO upper <=250 and scheduled contact-to-paint <=250ms','all expected footprints and exact quality/report semantics','no camera/SDK/model or process cleanup failure'],
      constraints=['No Run or unrelated business changes','No CPU/GIL/frequency percentage from failed PMC accounting','Keep a reversible original-controller fallback until field acceptance'])
    result=dict(current_root_conclusion='The primary actionable software root is Qt-event-loop wake dependent consumer capacity in the GUI-process architecture. Consumer process isolation removes the sustained deficit; increasing the isolated inbox batch cap from20 to40 removes the remaining wake-sensitive transient on saved input. The physical execution-state cause remains unidentified, and formal/field verification is still pending.',
      matrix=matrix,hypothesis_ranking=ranking,next_minimal_validation=capacity,root_function_identified=False,formal_fix_verified=False,field_fix_verified=False,
      bindings={name:dict(path=str(path.relative_to(ROOT)),sha256=sha(path)) for name,path in sources.items()})
    (HERE/'result01.json').write_text(json.dumps(result,indent=2)+'\n')
    (HERE/'next_consumer_capacity_plan01.json').write_text(json.dumps(capacity,indent=2)+'\n')
    print(json.dumps(result,indent=2))

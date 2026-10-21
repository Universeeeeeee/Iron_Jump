"""Summarize and publish only this lab on its dedicated experiment worktree."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE=Path(__file__).resolve().parent
WORKTREE=Path('/Users/vae/.codex/worktrees/sparse-processing-experiments/Iron_Jump')
REL=Path('exports/sparse_processing_20261021')


def command(args):
    return subprocess.check_output(args,cwd=WORKTREE,text=True).strip()


def main():
    label=sys.argv[1]
    if label=='E0':
        data=json.loads((HERE/'diagnostic.json').read_text())
        rows=[]
        for r in data['runs']:
            assert r['activity']['formal_calls']==r['frames'],r['case']
            rows.append(f"| {r['case']} | {r['frames']} | {r['wire_same_pct']:.2f}% | "
                        f"{r['wire_segment_same_pct']:.2f}% | {r['activity']['idle_eligible']} |")
        text=('## E0：完整处理覆盖率与重复率\n\n'
              '所有计时输入已确认完整进入正式算法。阶段墙钟来自带包装的诊断轮，不能作为无观察器 CPU 收益，也不能叠加嵌套阶段。\n\n'
              '| 输入 | 帧数／正式调用 | 相邻整份载荷相同 | 相邻逐段载荷相同 | 严格空场条件帧数 |\n'
              '|---|---:|---:|---:|---:|\n'+'\n'.join(rows)+'\n\n'
              '旧合成稀疏输入每周期返回原点，触发既有折返停止，造成正式算法仅处理 3330/60000 帧；旧诊断和未完成计时保留在 exploratory_v1，全部撤出本轮计分。新输入分别使用原地重复遮挡和单向跨段移动，并断言正式调用数、最后完成样本及结束原因。\n\n'
              'E1 的独立逐位 wire oracle 和真实 assembler 比较通过；E2/E3 的初轮逐帧比较及领域回归证据保留。稀疏缓存曾在布局替换时错误复用旧几何，现已修正并通过 423 项回归及两条实录重新核对。\n')
        summary={'experiment':label,'complete':True,'full_formal_coverage':True,'input_cases':len(rows)}
    elif label in ('E1','E2a','E2b','E3'):
        stages=json.loads((HERE/f'{label}_stage.json').read_text())
        pipelines=json.loads((HERE/f'{label}_pipeline.json').read_text())
        assert stages['complete'] and pipelines['complete']
        consumer_only=pipelines.get('scope')=='consumer_only'
        rows=[]
        for r in pipelines['results']:
            rows.append(f"| {r['case']} | {r['variant']} | {r['median_cpu_reduction']*100:.2f}% | {r['positive_pairs']}/4 |")
        decisions=[]
        for variant in pipelines['selected_variants']:
            rs=[r for r in pipelines['results'] if r['variant']==variant]
            qualify=bool(rs and any(r['median_cpu_reduction']>=.05 and r['positive_pairs']>=3 for r in rs)
                         and all(r['median_cpu_reduction']>=-.05 for r in rs))
            decisions.append({'variant':variant,'local_cpu_gate':qualify,
                'measurement_scope':'consumer_only' if consumer_only else 'serial_reader_and_consumer',
                'reason':'Requires >=5% complete-consumer CPU saving in at least one intended case (>=3/4 improving pairs) and no case median regression >5%.',
                'windows_latency_and_queue_gate':'not measured by these CPU runs'})
        summary={'experiment':label,'complete':True,'decisions':decisions,
                 'segmented_decoder_beats_simple_cache':pipelines.get('segmented_decoder_beats_simple_cache')}
        if label=='E1':
            summary['reader_decoder_gate']=any(r['median_cpu_reduction']>=.2 and r['positive_pairs']>=3
                                               for r in stages['results'] if r['variant']=='decode_full')
            summary['reader_benefit_is_not_consumer_thread_benefit']=True
        scope=('原质量、滤波、Processor、发布和停止 flush；解码、输入构造及保存位于计时之外。'
               if consumer_only else '接收端解码、质量、滤波、Processor、发布和停止 flush 的串行模型；不等同于生产消费者线程。')
        title='消费者专用' if consumer_only else '含读端解码的串行处理链路'
        text=(f'## {label}：独立阶段与完整消费者 CPU 对照\n\n'
              f'每项输入执行 AB、BA、AB、BA 四组配对，每次新进程。下表为{title} CPU 的配对改善中位数。范围：{scope}负值表示退化。\n\n'
              f'| 输入 | 候选 | {title} CPU 改善 | 改善配对 |\n|---|---|---:|---:|\n'
              +'\n'.join(rows)+'\n\n'+ '\n'.join(f"- {d['variant']}：本地 CPU 门槛{'通过' if d['local_cpu_gate'] else '未通过'}。" for d in decisions)
              +'\n\n这些是本地 macOS、无节奏、无 GUI/硬件的计算成本结果；不能据此声称 Windows FIFO、显示延迟或现场积压已经改善。\n')
        if label=='E1':
            text+='\nE1 的主要作用于读端。消费者计时是否通过与解码计时是否通过分别报告；旧串行模型数据保留在 E1_serial_pipeline.json，计时口径修正见 CONSUMER_SCOPE_CORRECTION.md。\n'
    elif label=='E4':
        data=json.loads((HERE/'diagnostic.json').read_text())
        controls=data['shadow_adversarial']
        assert all(r['revoked_on_trigger_sample'] for r in controls)
        rows=[]
        for r in data['runs']:
            s=r['retirement']
            rows.append(f"| {r['case']} | {s['eligible_segment_samples']} | {s['total_segment_samples']} | {len(s['events'])} |")
        summary={'experiment':label,'complete':True,'shadow_only':True,'adversarial_controls':len(controls),
                 'actual_retirement_enabled':False,'cpu_savings_proven':False}
        text=('## E4：单向退役影子验证\n\n'
              '仅标记潜在可退役区域，原算法仍完整执行。方向未知／反向、重新遮挡、待处理接触、有效性异常、缺帧和 stream 变化均在触发样本撤销标记，七组反例通过。\n\n'
              '| 输入 | 可退役段采样数 | 全部段采样数 | 标记／撤销事件数 |\n|---|---:|---:|---:|\n'
              +'\n'.join(rows)+'\n\n'
              '诊断保存的是存在退役标记时整个簇提取函数的受扰动墙钟上界，不是退役段独占 CPU。该上界不能证明达到消费者 CPU 5% 的推进门槛，因此本轮不引入实际退役；可退役时间占比也不换算为收益。\n')
    else:
        raise SystemExit('E0 | E1 | E2a | E2b | E3 | E4')
    (HERE/f'{label}_RESULTS.md').write_text(text,encoding='utf-8')
    (HERE/f'{label}_decision.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    # All files are this task's isolated artifacts. The user's original checkout
    # and pre-existing uncommitted changes never enter this worktree's index.
    destination=WORKTREE/REL
    shutil.copytree(HERE,destination,dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    command(['git','add','--',str(REL)])
    names=command(['git','diff','--cached','--name-only']).splitlines()
    assert names and all(n.startswith(str(REL)+'/') for n in names),names
    command(['git','diff','--cached','--check','--',str(REL),
             ':(exclude)'+str(REL/'baseline'),
             ':(exclude,glob)'+str(REL/'**/*.stdout'),
             ':(exclude,glob)'+str(REL/'**/*.stderr')])
    message=f'Record {label} sparse processing experiment and evidence'
    print(command(['git','commit','-m',message]),flush=True)
    sha=command(['git','rev-parse','HEAD'])
    push=subprocess.run(['git','push','-u','origin','HEAD'],cwd=WORKTREE,text=True,capture_output=True)
    print(push.stdout,push.stderr,flush=True)
    record={'experiment':label,'commit':sha,'branch':command(['git','branch','--show-current']),
            'push_exit_code':push.returncode,'pushed':push.returncode==0,
            'remote':'https://github.com/Universeeeeeee/Iron_Jump'}
    ledger=HERE/'publish_ledger.json'
    previous=json.loads(ledger.read_text()) if ledger.exists() else []
    previous.append(record);ledger.write_text(json.dumps(previous,indent=2))
    if push.returncode:raise SystemExit(push.returncode)
    print(json.dumps(record),flush=True)


if __name__=='__main__':main()

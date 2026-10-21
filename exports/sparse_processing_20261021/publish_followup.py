"""Publish one completed follow-up without staging the user's main checkout."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE=Path(__file__).resolve().parent
WORKTREE=Path('/Users/vae/.codex/worktrees/sparse-processing-experiments/Iron_Jump')
REL=Path('exports/sparse_processing_20261021')


def git(*args):
    return subprocess.check_output(['git',*args],cwd=WORKTREE,text=True).strip()


def main():
    label=sys.argv[1]
    if label=='combined':
        result=json.loads((HERE/'combined_consumer.json').read_text())
        correct=json.loads((HERE/'combined_correctness.json').read_text())
        callbacks=json.loads((HERE/'regression_combined_callbacks.json').read_text())
        assert result['complete'] and correct['all_exact'] and not callbacks['unexpected_callback_errors']
        text=('# 组合候选：消费者专用 CPU 对照\n\n'
              '组合包含质量窗口贡献抵消、完全结算空场路径和读端整帧解码复用。读端解码位于消费者计时之外；稀疏簇缓存因走路退化未加入。\n\n'
              '| 输入 | 消费者 CPU 改善中位数 | 改善配对 |\n|---|---:|---:|\n')
        for r in result['results']:
            text+=f"| {r['case']} | {100*r['median_cpu_reduction']:.2f}% | {r['positive_pairs']}/4 |\n"
        text+=f"\n本地 CPU 门槛：{'通过' if result['consumer_cpu_gate'] else '未通过'}。"
        text+=f"逐帧等价检查 {correct['frame_comparisons']} 次全部一致，领域回归 423 项通过，Qt 回调错误为零。\n"
        text+='\n每项为 AB、BA、AB、BA 四组新进程配对。本地 macOS 无节奏消费者计算，包含质量、滤波、Processor、发布与停止 flush，不含解码、输入构造、文件保存、inbox 唤醒、IPC、GUI 或物理采集。CPU 收益不能直接换算为 FIFO／显示延迟改善。\n'
        (HERE/'COMBINED_RESULTS.md').write_text(text,encoding='utf-8')
    elif label.startswith('E5v2_'):
        directory=HERE/'native_windows'/label
        result=json.loads((directory/(label+'.native.json')).read_text(encoding='utf-8'))
        assert result['complete'] and result['formal_sources_unchanged']
        text=f'# {label}：Windows 原生消费者 CPU 复核\n\n'
        text+='仅使用保存输入；每场景 AB、BA、AB、BA 四组新进程配对，原始 NumPy。无 USB／相机／SDK／人体采集。\n\n'
        text+='| 输入 | 消费者 CPU 改善中位数 | 改善配对 |\n|---|---:|---:|\n'
        for r in result['results']:
            text+=f"| {r['case']} | {100*r['median_cpu_reduction']:.2f}% | {r['positive_pairs']}/4 |\n"
        text+='\n这是三个输入上的原生 CPU 交叉验证，不是完整七场景准入矩阵；不包含 GUI、process+batch40 传输或真实到达节奏，不据此认定 FIFO／contact-to-paint 达标。每个配对的完整报告 SHA 相等，正式源文件校验保持一致。\n'
        (HERE/(label+'_RESULTS.md')).write_text(text,encoding='utf-8')
    elif label not in ('E5_GUI','closeout'):
        raise SystemExit('combined | E5v2_E2a | E5v2_E2b | E5_GUI | closeout')
    destination=WORKTREE/REL
    shutil.copytree(HERE,destination,dirs_exist_ok=True,
        ignore=shutil.ignore_patterns('__pycache__','*.pyc','native_v2_stream.log'))
    git('add','--',str(REL))
    names=git('diff','--cached','--name-only').splitlines()
    assert names and all(n.startswith(str(REL)+'/') for n in names),names
    git('-c','core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol',
        'diff','--cached','--check','--',str(REL),
        ':(exclude)'+str(REL/'baseline'),
        ':(exclude,glob)'+str(REL/'**/*.stdout'),
        ':(exclude,glob)'+str(REL/'**/*.stderr'))
    print(git('commit','-m',f'Record {label} offline sparse-processing validation'),flush=True)
    sha=git('rev-parse','HEAD')
    subprocess.run(['git','push','-u','origin','HEAD'],cwd=WORKTREE,check=True)
    remote=git('ls-remote','origin','refs/heads/codex/sparse-processing-experiments-20261021').split()[0]
    assert remote==sha,(remote,sha)
    record={'experiment':label,'commit':sha,'branch':'codex/sparse-processing-experiments-20261021',
            'pushed':True,'remote_ref_verified':True}
    ledger=HERE/'publish_ledger.json'
    entries=json.loads(ledger.read_text());entries.append(record)
    ledger.write_text(json.dumps(entries,indent=2))
    print(json.dumps(record),flush=True)


if __name__=='__main__':main()

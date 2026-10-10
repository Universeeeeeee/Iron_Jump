"""Chinese field-capture instructions, kept outside cmd.exe batch parsing."""
from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
MODES = {
    '1': ('minimal', 'A1-fixed', 'A1固定物：纯命令行，自动采集60秒，无图形界面'),
    '2': ('main', 'B-fixed', 'B固定物：打开主程序界面，需要手动结束'),
    '3': ('minimal', 'A2-fixed', 'A2固定物：纯命令行，自动采集60秒，无图形界面'),
    '4': ('main', 'ground-walk', '正常走路：打开主程序界面，同时录制原始USB数据'),
    '5': ('main', 'ground-run', '正常跑步：打开主程序界面，同时录制原始USB数据'),
}
NEXT_STEPS = {
    '1': '下一步选2：先移走固定物，再打开主程序完成空场预检。',
    '2': '下一步选3：固定物留在同一标记位置，再进行60秒最小采集。',
    '3': '下一步选4：移走固定物，准备正常走路测试。',
    '4': '下一步选5：准备正常跑步测试。',
    '5': '五轮完成后，请整理原始数据、录屏、明细TXT和Excel。',
}


def main():
    os.chdir(ROOT)
    print('请依次完成1、2、3、4、5，每次只打开一个采集程序。')
    for number, (_, _, description) in MODES.items():
        print(f'{number}. {description}')
    print('0. 取消退出')
    choice = input('请选择采集项目 [0-5]，输入数字后按回车：').strip()
    while choice not in MODES and choice != '0':
        choice = input('请输入0到5之间的数字，再按回车：').strip()
    if choice == '0':
        print('已取消，没有启动采集。')
        return 0
    condition, label, _ = MODES[choice]
    print()
    if condition == 'minimal':
        print('当前是固定物最小采集，不会打开图形界面。')
        print('开始前：在第3段中部放好不透明固定物，连续遮挡约20厘米，避开接缝。')
        print('人站在跑道外。采集期间物体保持不动，不拔插设备或更换USB接口。')
        print('确认开始后自动采集60秒，请等待完成提示。')
    elif choice == '2':
        print('开始前：先移走固定物，让跑道保持空场。')
        print('确认后打开主程序，选择8米地面走路，结束条件选软件手动结束。')
        print('完成空场预检并点击开始后，把固定物放回第3段的同一标记位置。')
        print('稳定保持60秒，再手动结束。录屏须包含相机预览和报告概览。')
        print('保存报告后关闭整个主程序，返回此窗口等待日志写完。')
    else:
        print('确认后打开主程序，请选择8米地面' + ('走路。' if choice == '4' else '跑步。'))
        print('结束条件选软件手动结束；展开滤波参数，将最小接触时间设为60毫秒。')
        print('完成空场预检，点击开始后先留约3秒空场，再正常走或跑过整个设备末端。')
        print('从跑道外返回，离场后留约3秒空场，再手动结束；独立记实际落脚次数。')
        print('录屏须包含相机预览和报告概览，另保存明细TXT并导出Excel。')
        print('保存后关闭整个主程序，返回此窗口等待日志写完。')
    if input('\n准备好后按回车开始；输入0再回车取消：').strip() == '0':
        print('已取消，没有启动采集，也没有创建采集目录。')
        return 0
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
    output = ROOT / 'exports' / 'ground_field_20261010' / f'{label}_{stamp}'
    print(f'本轮保存目录：{output}', flush=True)
    if condition == 'minimal':
        print('正在启动采集，请保持固定物不动，等待约60秒。', flush=True)
    result = subprocess.run([
        sys.executable, '-X', 'utf8', '-m', 'tools.ground_capture_condition',
        '--condition', condition, '--label', label, '--output-dir', str(output),
    ]).returncode
    if result == 0:
        print('本轮采集完成，程序已正常退出。')
        print(NEXT_STEPS[choice])
    else:
        print(f'本轮采集异常退出，错误码：{result}。请保留目录并反馈窗口中的报错。')
    print(f'数据保存目录：{output}')
    return result


if __name__ == '__main__':
    try:
        exit_code = main()
        input('按回车关闭此窗口。')
    except (KeyboardInterrupt, EOFError):
        print('\n已取消。若采集已经开始，请保留当轮数据目录。')
        exit_code = 130
    sys.exit(exit_code)

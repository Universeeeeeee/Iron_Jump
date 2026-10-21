"""Ordered same-host command and notification contract."""
COMMANDS = {'prepare', 'start', 'stop', 'discard', 'close', 'retry_device', 'refresh_led_health'}
NOTIFICATIONS = {'hop_event', 'jump_quality_notice', 'gait_step_event', 'device_message',
                 'device_state_changed', 'device_layout_changed', 'led_health_changed',
                 'beam_quality_notice', 'pause_state_changed'}
OUTPUTS = {'actor_ready', 'prepared', 'readiness', 'snapshot', 'visual', 'notification',
           'started', 'command_completed', 'report', 'terminal'}


def validate(value, sequence, kinds, pid=None):
    if value.get('sequence') != sequence + 1 or value.get('kind') not in kinds:
        raise ValueError('Invalid measurement message order/kind')
    if pid is not None and value.get('pid') != pid:
        raise ValueError('Invalid measurement process identity')
    return value['sequence']

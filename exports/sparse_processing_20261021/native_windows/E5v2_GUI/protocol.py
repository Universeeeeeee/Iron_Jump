"""Live ground-session command/output contracts."""
COMMANDS={'prepare','start','stop','discard','refresh_led_health'}
NOTIFICATIONS={'hop_event','jump_quality_notice','gait_step_event','device_message','device_state_changed','device_layout_changed','led_health_changed','beam_quality_notice','pause_state_changed'}
OUTPUTS={'actor_ready','prepared','readiness','snapshot','visual','notification','started','source_exhausted','command_received','command_completed','report_value','terminal'}
def validate_command(value,last):
 if value.get('sequence')!=last+1 or value.get('kind') not in COMMANDS:raise ValueError('Invalid live command sequence or kind')
 return value['sequence']
def validate_output(value,last,pid):
 if value.get('sequence')!=last+1 or value.get('pid')!=pid or value.get('kind') not in OUTPUTS:raise ValueError('Invalid live output identity/order/kind')
 return value['sequence']

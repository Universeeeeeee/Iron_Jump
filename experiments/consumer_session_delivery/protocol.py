def validate_message(message,sequence,pid):
    if message['sequence']!=sequence+1:raise ValueError('Output order mismatch')
    if message['pid']!=pid:raise ValueError('Actor PID mismatch')
    if message['kind'] not in {'actor_ready','prepared','readiness','visual','snapshot','ready_to_start','started','drained_eof','report_value','terminal'}:raise ValueError('Unknown output kind')
    return message['sequence']

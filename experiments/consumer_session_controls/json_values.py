"""JSON evidence representation only; live IPC retains original typed values."""
from dataclasses import asdict,is_dataclass

def json_value(value):
    if is_dataclass(value) and not isinstance(value,type):
        return dict(value_type=type(value).__module__+'.'+type(value).__qualname__,fields=asdict(value))
    raise TypeError('Unsupported JSON evidence value type: '+type(value).__name__)

"""Prepared isolated-process intervention; never installed at import time."""
import ast
import hashlib
import inspect
import textwrap
import numpy as np

def runtime_mask_equal(left,right):
    # Only this original caller's exact canonical bool[768] boundary is changed.
    # Noncanonical bool storage can compare equal despite unequal raw bytes.
    if (type(left) is np.ndarray and type(right) is np.ndarray
            and left.dtype==right.dtype==np.dtype(bool)
            and left.shape==right.shape==(768,)
            and left.flags.c_contiguous and right.flags.c_contiguous):
        a=left.tobytes();b=right.tobytes()
        if not a.translate(None,b'\x00\x01') and not b.translate(None,b'\x00\x01'):
            return a==b
    return np.array_equal(left,right)

def transformed(source):
    tree=ast.parse(textwrap.dedent(source));matches=[]
    for node in ast.walk(tree):
        if (isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
                and isinstance(node.func.value,ast.Name) and node.func.value.id=='np'
                and node.func.attr=='array_equal' and len(node.args)==2 and not node.keywords
                and isinstance(node.args[0],ast.Name) and node.args[0].id=='flagged'
                and isinstance(node.args[1],ast.Attribute) and isinstance(node.args[1].value,ast.Name)
                and node.args[1].value.id=='self' and node.args[1].attr=='_runtime_suspicious_mask'):
            matches.append(node)
    if len(matches)!=1:raise ValueError('Expected exactly one frozen runtime mask equality call')
    matches[0].func=ast.Name(id='_diagnostic_runtime_mask_equal',ctx=ast.Load())
    return ast.fix_missing_locations(tree)

def prepare(original,expected_source_sha256):
    source=textwrap.dedent(inspect.getsource(original))
    if hashlib.sha256(source.encode()).hexdigest()!=expected_source_sha256:
        raise ValueError('Original function source differs from frozen proposal')
    env=dict(original.__globals__);env['_diagnostic_runtime_mask_equal']=runtime_mask_equal
    exec(compile(transformed(source),inspect.getsourcefile(original),'exec'),env)
    return env[original.__name__]

def install(expected_source_sha256):
    """Only an explicitly invoked experiment may call this, after scope approval."""
    from engine.device_quality_session import DeviceQualitySession
    original=DeviceQualitySession.on_frame
    DeviceQualitySession.on_frame=prepare(original,expected_source_sha256)
    return original

"""Run the existing fault suite against this adapter's unchanged cleanup body."""
import importlib.util
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent;OLD=HERE.parent/'native_stack_capture'
sys.path.insert(0,str(OLD))
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
suite=load('fixed_lifecycle_original_cleanup_tests',OLD/'test_record_cleanup.py')
suite.record=load('fixed_lifecycle_cleanup',HERE/'capture.py')
RecordCleanupTests=suite.RecordCleanupTests

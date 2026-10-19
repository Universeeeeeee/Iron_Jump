"""Post-cohort read-only configuration; no settings, images or workloads changed."""
import hashlib
import json
from pathlib import Path
import cv2

if __name__=='__main__':
    binary=Path(cv2.__file__).parent/'cv2.pyd'
    print(json.dumps(dict(version=cv2.__version__,configured_threads=cv2.getNumThreads(),reported_CPUs=cv2.getNumberOfCPUs(),parallel_build_lines=[x.strip() for x in cv2.getBuildInformation().splitlines() if 'Parallel framework' in x],binary_path=str(binary),binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),scope='Read-only post-cohort metadata, not proof of delivered thread count during prior windows.')))

"""
engine — L2 算法引擎层

包含簇提取、跨帧追踪、纵跳/步态检测状态机、高阶派生参数。
"""
from .spatial_clusterer import ClusterTracker, extract_clusters
from .single_foot_tracker import SingleFootDetector, LedFrame, FootEvent
from .contact_tracker import ContactBasedGaitTracker, GaitStepEvent
from .extra_parameter import compute_extra_parameters
from .gait_engine import GaitEngine

__all__ = [
    "ClusterTracker", "extract_clusters",
    "SingleFootDetector", "LedFrame", "FootEvent",
    "ContactBasedGaitTracker", "GaitStepEvent",
    "compute_extra_parameters",
    "GaitEngine",
]

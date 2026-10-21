"""
camera.py

功能说明
--------
本模块用于**打开并显示电脑摄像头的实时视频流**，仅作为视觉参考与对照工具，
不参与任何计算机视觉算法、不做步态参数提取、不与后端分析流程耦合。

设计目的
--------
1. 为光电阵列步态分析提供**直观的同步视觉参照**；
2. 便于实验演示、结果解释与调试，对比"真实动作"与"信号推断结果"；
3. 避免将系统复杂度引入计算机视觉路径，保持主算法链路的可控性与可复现性。

使用方式
--------
- 通过 OpenCV 调用本地摄像头；
- 实时显示视频流，不做帧缓存、不做处理、不保存数据；
- 作为独立模块导入，在前端通过 Camera 类统一管理。

前端集成建议
------------
- 在主界面增加"相机 / Camera"按钮；
- 点击后调用 Camera.open_camera() 方法；
- 相机窗口与步态分析界面并行显示，互不阻塞、互不依赖。

设计约束
--------
- 本模块 **不属于步态分析算法的一部分**；
- 不引入 OpenPose、MediaPipe 等视觉模型；
- 不承担"精度提升"责任，仅承担"认知对齐"与"展示"功能。
"""

import cv2
import threading


class Camera:
    """
    摄像头管理类
    
    提供简单的摄像头打开、显示和关闭功能。
    支持在独立线程中运行，避免阻塞主界面。
    """
    
    def __init__(self, camera_index: int = 0):
        """
        初始化 Camera 实例
        
        Parameters
        ----------
        camera_index : int, optional
            摄像头索引，默认为 0（系统默认摄像头）
        """
        self.camera_index = camera_index
        self.cap = None
        self.is_running = False
        self._thread = None
        self.window_name = "Camera - Live Video (Press Q or ESC to Exit)"
    
    def open_camera(self, threaded: bool = True) -> bool:
        """
        打开摄像头并显示实时视频流
        
        Parameters
        ----------
        threaded : bool, optional
            是否在独立线程中运行，默认为 True（推荐，避免阻塞前端）
        
        Returns
        -------
        bool
            摄像头是否成功打开
        """
        if self.is_running:
            print("[Camera] 摄像头已在运行中")
            return True
        
        if threaded:
            self._thread = threading.Thread(target=self._camera_loop, daemon=True)
            self._thread.start()
            return True
        else:
            return self._camera_loop()
    
    def _camera_loop(self) -> bool:
        """
        摄像头主循环（内部方法）
        
        Returns
        -------
        bool
            运行是否成功
        """
        self.cap = cv2.VideoCapture(self.camera_index)
        
        if not self.cap.isOpened():
            print(f"[Camera] 无法打开摄像头 (索引: {self.camera_index})")
            return False
        
        print(f"[Camera] 摄像头已打开 (索引: {self.camera_index})")
        self.is_running = True
        
        # 设置窗口大小为 1000x600
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.window_name, 1000, 600)
        
        try:
            while self.is_running:
                ret, frame = self.cap.read()
                
                if not ret:
                    print("[Camera] 无法读取视频帧")
                    break
                
                # 水平翻转，消除镜像效果
                frame = cv2.flip(frame, 1)
                
                # 显示帧（不做任何处理）
                cv2.imshow(self.window_name, frame)
                
                # 检测退出按键：Q 或 ESC
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q') or key == ord('Q') or key == 27:
                    print("[Camera] 用户请求退出")
                    break
                
                # 检测窗口是否被关闭
                if cv2.getWindowProperty(self.window_name, cv2.WND_PROP_VISIBLE) < 1:
                    print("[Camera] 窗口已关闭")
                    break
                    
        except Exception as e:
            print(f"[Camera] 发生异常: {e}")
        finally:
            self._cleanup()
        
        return True
    
    def close_camera(self):
        """
        关闭摄像头并释放资源
        """
        self.is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._cleanup()
    
    def _cleanup(self):
        """
        清理资源（内部方法）
        """
        self.is_running = False
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        cv2.destroyAllWindows()
        print("[Camera] 资源已释放")


# 便捷函数：快速打开摄像头
def open_camera(camera_index: int = 0, threaded: bool = False):
    """
    便捷函数：快速打开摄像头
    
    Parameters
    ----------
    camera_index : int, optional
        摄像头索引，默认为 0
    threaded : bool, optional
        是否在独立线程中运行，默认为 False（阻塞模式，适合独立测试）
    
    Returns
    -------
    Camera
        Camera 实例（threaded=True 时可用于后续控制）
    """
    cam = Camera(camera_index)
    cam.open_camera(threaded=threaded)
    return cam


# 模块独立运行时的测试入口
if __name__ == "__main__":
    print("=" * 50)
    print("摄像头测试模式")
    print("按 Q 或 ESC 键退出")
    print("=" * 50)
    
    # 阻塞模式运行，便于独立测试
    open_camera(threaded=False)
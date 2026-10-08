#pragma once

#include <stdint.h>

#ifdef _WIN32
#  ifdef OBSBOT_C_API_EXPORTS
#    define OBSBOT_C_API __declspec(dllexport)
#  else
#    define OBSBOT_C_API __declspec(dllimport)
#  endif
#else
#  define OBSBOT_C_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

enum {
    OBSBOT_OK = 0,
    OBSBOT_ERR = -1,
    OBSBOT_ERR_BAD_ARG = -2,
    OBSBOT_ERR_NO_DEVICE = -3,
    OBSBOT_ERR_EXCEPTION = -4,
};

typedef struct ObsbotDeviceInfo {
    char sn[64];
    char name[128];
    char version[64];
    char video_path[512];
    char video_friendly_name[256];
    int32_t product_type;
    int32_t dev_mode;
} ObsbotDeviceInfo;

typedef struct ObsbotVideoFormatInfo {
    int32_t width;
    int32_t height;
    int32_t fps_min;
    int32_t fps_max;
    int32_t format;
} ObsbotVideoFormatInfo;

typedef struct ObsbotEncodeParam {
    int32_t width;
    int32_t height;
    int32_t fps;
    int32_t bitrate;
    int32_t encode_format;
} ObsbotEncodeParam;

typedef struct ObsbotCameraStatusInfo {
    int32_t query_ret;
    int32_t product_type;
    int32_t dev_mode;
    int32_t tiny_fps;
    int32_t tiny_dev_status;
    int32_t tiny_hdr;
    int32_t tiny_live_stream_mode;
    int32_t tiny_fov;
    int32_t tiny_vertical;
    int32_t tiny_usb_status;
} ObsbotCameraStatusInfo;

OBSBOT_C_API int32_t obsbot_refresh_devices(int32_t wait_ms);
OBSBOT_C_API int32_t obsbot_get_device_count(void);
OBSBOT_C_API int32_t obsbot_get_device_info(int32_t index, ObsbotDeviceInfo *out_info);
OBSBOT_C_API int32_t obsbot_get_video_formats(
    int32_t index,
    ObsbotVideoFormatInfo *out_formats,
    int32_t max_formats);

OBSBOT_C_API int32_t obsbot_set_record_encode_param(
    int32_t index,
    const ObsbotEncodeParam *param,
    int32_t night_flag);
OBSBOT_C_API int32_t obsbot_get_record_encode_param(
    int32_t index,
    ObsbotEncodeParam *out_param,
    int32_t night_flag);
OBSBOT_C_API int32_t obsbot_get_output_encode_param(
    int32_t index,
    ObsbotEncodeParam *out_param,
    int32_t night_flag);
OBSBOT_C_API int32_t obsbot_set_output_encode_param(
    int32_t index,
    const ObsbotEncodeParam *param,
    int32_t night_flag);
OBSBOT_C_API int32_t obsbot_get_live_encode_param(
    int32_t index,
    ObsbotEncodeParam *out_param,
    int32_t night_flag);
OBSBOT_C_API int32_t obsbot_get_camera_status(
    int32_t index,
    ObsbotCameraStatusInfo *out_status,
    int32_t force_query);
OBSBOT_C_API int32_t obsbot_get_media_operate_param(
    int32_t index,
    int32_t stream_id,
    int32_t *out_action);
OBSBOT_C_API int32_t obsbot_get_usb_mode(int32_t index, int32_t *out_mode);
OBSBOT_C_API int32_t obsbot_set_usb_mode(int32_t index, int32_t mode);
OBSBOT_C_API int32_t obsbot_is_mtp_stream_enabled(int32_t index, int32_t *out_enabled);
OBSBOT_C_API int32_t obsbot_set_mtp_stream_enabled(int32_t index, int32_t enabled);
OBSBOT_C_API int32_t obsbot_is_mtp_transferring_file(int32_t index, int32_t *out_transferring);
OBSBOT_C_API int32_t obsbot_set_media_operate_param(
    int32_t index,
    int32_t stream_id,
    int32_t action);
OBSBOT_C_API int32_t obsbot_set_record_resolution(int32_t index, int32_t res_type);
OBSBOT_C_API int32_t obsbot_set_video_record(
    int32_t index,
    uint32_t operation,
    uint32_t param);
/* ── 图像 / 控制新增 ── */
OBSBOT_C_API int32_t obsbot_set_camera_mirror(int32_t index, int32_t mirror);
OBSBOT_C_API int32_t obsbot_set_ai_mode(int32_t index, int32_t mode, int32_t sub_mode);
OBSBOT_C_API int32_t obsbot_set_auto_focus(int32_t index, int32_t auto_mode);
OBSBOT_C_API int32_t obsbot_set_manual_focus(int32_t index, int32_t focus_val);
OBSBOT_C_API int32_t obsbot_set_exposure_compensation(int32_t index, int32_t ev_index);
OBSBOT_C_API int32_t obsbot_set_anti_flicker(int32_t index, int32_t freq);
OBSBOT_C_API int32_t obsbot_set_fov(int32_t index, int32_t fov_type);
OBSBOT_C_API int32_t obsbot_set_wdr(int32_t index, int32_t wdr_mode);
/* Manual gimbal control: disable AI tracking first; zero speeds stop motion. */
OBSBOT_C_API int32_t obsbot_set_gimbal_speed(int32_t index, double pitch, double pan);
/* Output order: roll, pitch, pan, in degrees. */
OBSBOT_C_API int32_t obsbot_get_gimbal_angles(int32_t index, float angles[3]);

OBSBOT_C_API void obsbot_close(void);

#ifdef __cplusplus
}
#endif

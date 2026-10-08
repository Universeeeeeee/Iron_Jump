#include "obsbot_c_api.h"

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#endif

#include <algorithm>
#include <chrono>
#include <cmath>
#include <codecvt>
#include <cstring>
#include <locale>
#include <memory>
#include <string>
#include <thread>
#include <vector>

#include "dev/devs.hpp"

#ifdef _WIN32
#include <windows.h>
#endif

namespace {

std::vector<std::shared_ptr<Device>> g_devices;

template <size_t N>
void copy_string(char (&dst)[N], const std::string &src)
{
    static_assert(N > 0, "destination must not be empty");
    const size_t n = std::min(N - 1, src.size());
    std::memcpy(dst, src.data(), n);
    dst[n] = '\0';
}

#ifdef _WIN32
std::string utf8_from_wstring(const std::wstring &value)
{
    std::wstring_convert<std::codecvt_utf8<wchar_t>> converter;
    return converter.to_bytes(value);
}
#endif

std::shared_ptr<Device> get_device(int32_t index)
{
    if (index < 0 || static_cast<size_t>(index) >= g_devices.size()) {
        return nullptr;
    }
    return g_devices[static_cast<size_t>(index)];
}

#ifdef _WIN32
FARPROC get_libdev_symbol(const char *name)
{
    HMODULE module = GetModuleHandleW(L"libdev.dll");
    if (module == nullptr) {
        module = LoadLibraryW(L"libdev.dll");
    }
    if (module == nullptr) {
        return nullptr;
    }
    return GetProcAddress(module, name);
}
#endif

void copy_encode_param(const Device::DevMediaEncodeParam &src, ObsbotEncodeParam *dst)
{
    dst->width = src.width;
    dst->height = src.height;
    dst->fps = src.fps;
    dst->bitrate = src.bitrate;
    dst->encode_format = static_cast<int32_t>(src.encode_format);
}

Device::DevMediaEncodeParam make_sdk_encode_param(const ObsbotEncodeParam *param)
{
    Device::DevMediaEncodeParam sdk_param;
    sdk_param.width = param->width;
    sdk_param.height = param->height;
    sdk_param.fps = param->fps;
    sdk_param.bitrate = param->bitrate;
    sdk_param.encode_format =
        static_cast<Device::DevVideoEncoderFormat>(param->encode_format);
    return sdk_param;
}

}  // namespace

extern "C" {

int32_t obsbot_refresh_devices(int32_t wait_ms)
{
    try {
        Devices::get();  // trigger detection thread first
        if (wait_ms > 0) {
            std::this_thread::sleep_for(std::chrono::milliseconds(wait_ms));
        }
        auto list = Devices::get().getDevList();
        g_devices.assign(list.begin(), list.end());
        return static_cast<int32_t>(g_devices.size());
    } catch (...) {
        return OBSBOT_ERR_EXCEPTION;
    }
}

int32_t obsbot_get_device_count(void)
{
    return static_cast<int32_t>(g_devices.size());
}

int32_t obsbot_get_device_info(int32_t index, ObsbotDeviceInfo *out_info)
{
    if (out_info == nullptr) {
        return OBSBOT_ERR_BAD_ARG;
    }
    std::memset(out_info, 0, sizeof(*out_info));

    try {
        auto dev = get_device(index);
        if (!dev) {
            return OBSBOT_ERR_NO_DEVICE;
        }

        copy_string(out_info->sn, dev->devSn());
        copy_string(out_info->name, dev->devName());
        copy_string(out_info->version, dev->devVersion());
        out_info->product_type = static_cast<int32_t>(dev->productType());
        out_info->dev_mode = static_cast<int32_t>(dev->devMode());

#ifdef _WIN32
        if (dev->devMode() == Device::DevModeUvc) {
            copy_string(out_info->video_path, utf8_from_wstring(dev->videoDevPath()));
            copy_string(
                out_info->video_friendly_name,
                utf8_from_wstring(dev->videoFriendlyName()));
        }
#endif
        return OBSBOT_OK;
    } catch (...) {
        return OBSBOT_ERR_EXCEPTION;
    }
}

int32_t obsbot_get_video_formats(
    int32_t index,
    ObsbotVideoFormatInfo *out_formats,
    int32_t max_formats)
{
    if (max_formats < 0 || (max_formats > 0 && out_formats == nullptr)) {
        return OBSBOT_ERR_BAD_ARG;
    }

    try {
        auto dev = get_device(index);
        if (!dev) {
            return OBSBOT_ERR_NO_DEVICE;
        }

        auto formats = dev->videoFormatInfo();
        const int32_t total = static_cast<int32_t>(formats.size());
        const int32_t count = std::min(total, max_formats);
        for (int32_t i = 0; i < count; ++i) {
            const auto &src = formats[static_cast<size_t>(i)];
            auto &dst = out_formats[i];
            dst.width = src.width_;
            dst.height = src.height_;
            dst.fps_min = src.fps_min_;
            dst.fps_max = src.fps_max_;
            dst.format = static_cast<int32_t>(src.format_);
        }
        return total;
    } catch (...) {
        return OBSBOT_ERR_EXCEPTION;
    }
}

int32_t obsbot_set_record_encode_param(
    int32_t index,
    const ObsbotEncodeParam *param,
    int32_t night_flag)
{
    if (param == nullptr) {
        return OBSBOT_ERR_BAD_ARG;
    }

    try {
        auto dev = get_device(index);
        if (!dev) {
            return OBSBOT_ERR_NO_DEVICE;
        }

        Device::DevMediaEncodeParam sdk_param = make_sdk_encode_param(param);
        return dev->cameraSetRecordEncodeParamR(sdk_param, night_flag != 0);
    } catch (...) {
        return OBSBOT_ERR_EXCEPTION;
    }
}

int32_t obsbot_get_record_encode_param(
    int32_t index,
    ObsbotEncodeParam *out_param,
    int32_t night_flag)
{
    if (out_param == nullptr) {
        return OBSBOT_ERR_BAD_ARG;
    }
    std::memset(out_param, 0, sizeof(*out_param));

    try {
        auto dev = get_device(index);
        if (!dev) {
            return OBSBOT_ERR_NO_DEVICE;
        }

        Device::DevMediaEncodeParam sdk_param;
        const int32_t ret = dev->cameraGetRecordEncodeParamR(sdk_param, night_flag != 0);
        if (ret != OBSBOT_OK) {
            return ret;
        }
        copy_encode_param(sdk_param, out_param);
        return ret;
    } catch (...) {
        return OBSBOT_ERR_EXCEPTION;
    }
}

int32_t obsbot_get_output_encode_param(
    int32_t index,
    ObsbotEncodeParam *out_param,
    int32_t night_flag)
{
    if (out_param == nullptr) {
        return OBSBOT_ERR_BAD_ARG;
    }
    std::memset(out_param, 0, sizeof(*out_param));

    try {
        auto dev = get_device(index);
        if (!dev) {
            return OBSBOT_ERR_NO_DEVICE;
        }

        Device::DevMediaEncodeParam sdk_param;
        const int32_t ret = dev->cameraGetOutputEncodeParamR(sdk_param, night_flag != 0);
        if (ret != OBSBOT_OK) {
            return ret;
        }
        copy_encode_param(sdk_param, out_param);
        return ret;
    } catch (...) {
        return OBSBOT_ERR_EXCEPTION;
    }
}

int32_t obsbot_set_output_encode_param(
    int32_t index,
    const ObsbotEncodeParam *param,
    int32_t night_flag)
{
    if (param == nullptr) {
        return OBSBOT_ERR_BAD_ARG;
    }

    try {
        auto dev = get_device(index);
        if (!dev) {
            return OBSBOT_ERR_NO_DEVICE;
        }

        Device::DevMediaEncodeParam sdk_param = make_sdk_encode_param(param);
        return dev->cameraSetOutputEncodeParamR(sdk_param, night_flag != 0);
    } catch (...) {
        return OBSBOT_ERR_EXCEPTION;
    }
}

int32_t obsbot_get_live_encode_param(
    int32_t index,
    ObsbotEncodeParam *out_param,
    int32_t night_flag)
{
    if (out_param == nullptr) {
        return OBSBOT_ERR_BAD_ARG;
    }
    std::memset(out_param, 0, sizeof(*out_param));

    try {
        auto dev = get_device(index);
        if (!dev) {
            return OBSBOT_ERR_NO_DEVICE;
        }

        Device::DevMediaEncodeParam sdk_param;
        const int32_t ret = dev->cameraGetLiveEncodeParamR(sdk_param, night_flag != 0);
        if (ret != OBSBOT_OK) {
            return ret;
        }
        copy_encode_param(sdk_param, out_param);
        return ret;
    } catch (...) {
        return OBSBOT_ERR_EXCEPTION;
    }
}

int32_t obsbot_get_camera_status(
    int32_t index,
    ObsbotCameraStatusInfo *out_status,
    int32_t force_query)
{
    if (out_status == nullptr) {
        return OBSBOT_ERR_BAD_ARG;
    }
    std::memset(out_status, 0, sizeof(*out_status));
    out_status->query_ret = OBSBOT_ERR;

    try {
        auto dev = get_device(index);
        if (!dev) {
            return OBSBOT_ERR_NO_DEVICE;
        }

        Device::CameraStatus status;
        int32_t ret = OBSBOT_OK;
        if (force_query != 0) {
            ret = dev->cameraGetCameraStatusU(status);
        } else {
            status = dev->cameraStatus();
        }

        out_status->query_ret = ret;
        out_status->product_type = static_cast<int32_t>(dev->productType());
        out_status->dev_mode = static_cast<int32_t>(dev->devMode());
        out_status->tiny_fps = status.tiny.fps;
        out_status->tiny_dev_status = status.tiny.dev_status;
        out_status->tiny_hdr = status.tiny.hdr;
        out_status->tiny_live_stream_mode = status.tiny.live_stream_mode;
        out_status->tiny_fov = status.tiny.fov;
        out_status->tiny_vertical = status.tiny.vertical;
        out_status->tiny_usb_status = -1;
        return ret;
    } catch (...) {
        return OBSBOT_ERR_EXCEPTION;
    }
}

int32_t obsbot_get_media_operate_param(
    int32_t index,
    int32_t stream_id,
    int32_t *out_action)
{
    if (out_action == nullptr) {
        return OBSBOT_ERR_BAD_ARG;
    }
    *out_action = -1;

    try {
        auto dev = get_device(index);
        if (!dev) {
            return OBSBOT_ERR_NO_DEVICE;
        }

        Device::DevMediaParamOperation action = Device::DevMediaParamOperationAuto;
        const int32_t ret = dev->cameraGetMediaOperateParamR(
            static_cast<Device::DevMediaStreamId>(stream_id), action);
        *out_action = static_cast<int32_t>(action);
        return ret;
    } catch (...) {
        return OBSBOT_ERR_EXCEPTION;
    }
}

int32_t obsbot_get_usb_mode(int32_t index, int32_t *out_mode)
{
    if (out_mode == nullptr) {
        return OBSBOT_ERR_BAD_ARG;
    }
    *out_mode = -1;

    try {
        auto dev = get_device(index);
        if (!dev) {
            return OBSBOT_ERR_NO_DEVICE;
        }
#ifdef _WIN32
        using Fn = int32_t(__fastcall *)(Device *, Device::DevUSBModeType *);
        auto fn = reinterpret_cast<Fn>(get_libdev_symbol(
            "?cameraGetUSBModeR@Device@@QEAAHAEAW4DevUSBModeType@1@@Z"));
        if (fn == nullptr) {
            return OBSBOT_ERR;
        }
        Device::DevUSBModeType mode = Device::DevUSBModeIdle;
        const int32_t ret = fn(dev.get(), &mode);
        *out_mode = static_cast<int32_t>(mode);
        return ret;
#else
        return OBSBOT_ERR;
#endif
    } catch (...) {
        return OBSBOT_ERR_EXCEPTION;
    }
}

int32_t obsbot_set_usb_mode(int32_t index, int32_t mode)
{
    try {
        auto dev = get_device(index);
        if (!dev) {
            return OBSBOT_ERR_NO_DEVICE;
        }
#ifdef _WIN32
        using Fn = int32_t(__fastcall *)(Device *, Device::DevUSBModeType);
        auto fn = reinterpret_cast<Fn>(get_libdev_symbol(
            "?cameraSetUSBModeR@Device@@QEAAHW4DevUSBModeType@1@@Z"));
        if (fn == nullptr) {
            return OBSBOT_ERR;
        }
        return fn(dev.get(), static_cast<Device::DevUSBModeType>(mode));
#else
        return OBSBOT_ERR;
#endif
    } catch (...) {
        return OBSBOT_ERR_EXCEPTION;
    }
}

int32_t obsbot_is_mtp_stream_enabled(int32_t index, int32_t *out_enabled)
{
    if (out_enabled == nullptr) {
        return OBSBOT_ERR_BAD_ARG;
    }
    *out_enabled = -1;

    try {
        auto dev = get_device(index);
        if (!dev) {
            return OBSBOT_ERR_NO_DEVICE;
        }
#ifdef _WIN32
        using Fn = bool(__fastcall *)(Device *);
        auto fn = reinterpret_cast<Fn>(get_libdev_symbol(
            "?isMtpStreamEnabled@Device@@QEAA_NXZ"));
        if (fn == nullptr) {
            return OBSBOT_ERR;
        }
        *out_enabled = fn(dev.get()) ? 1 : 0;
        return OBSBOT_OK;
#else
        return OBSBOT_ERR;
#endif
    } catch (...) {
        return OBSBOT_ERR_EXCEPTION;
    }
}

int32_t obsbot_set_mtp_stream_enabled(int32_t index, int32_t enabled)
{
    try {
        auto dev = get_device(index);
        if (!dev) {
            return OBSBOT_ERR_NO_DEVICE;
        }
#ifdef _WIN32
        using Fn = void(__fastcall *)(Device *, bool);
        auto fn = reinterpret_cast<Fn>(get_libdev_symbol(
            "?setMtpStreamEnabled@Device@@QEAAX_N@Z"));
        if (fn == nullptr) {
            return OBSBOT_ERR;
        }
        fn(dev.get(), enabled != 0);
        return OBSBOT_OK;
#else
        return OBSBOT_ERR;
#endif
    } catch (...) {
        return OBSBOT_ERR_EXCEPTION;
    }
}

int32_t obsbot_is_mtp_transferring_file(int32_t index, int32_t *out_transferring)
{
    if (out_transferring == nullptr) {
        return OBSBOT_ERR_BAD_ARG;
    }
    *out_transferring = -1;

    try {
        auto dev = get_device(index);
        if (!dev) {
            return OBSBOT_ERR_NO_DEVICE;
        }
#ifdef _WIN32
        using Fn = bool(__fastcall *)(Device *);
        auto fn = reinterpret_cast<Fn>(get_libdev_symbol(
            "?devTransferringFileByMtp@Device@@QEAA_NXZ"));
        if (fn == nullptr) {
            return OBSBOT_ERR;
        }
        *out_transferring = fn(dev.get()) ? 1 : 0;
        return OBSBOT_OK;
#else
        return OBSBOT_ERR;
#endif
    } catch (...) {
        return OBSBOT_ERR_EXCEPTION;
    }
}

int32_t obsbot_set_media_operate_param(int32_t index, int32_t stream_id, int32_t action)
{
    try {
        auto dev = get_device(index);
        if (!dev) {
            return OBSBOT_ERR_NO_DEVICE;
        }
        return dev->cameraSetMediaOperateParamR(
            static_cast<Device::DevMediaStreamId>(stream_id),
            static_cast<Device::DevMediaParamOperation>(action));
    } catch (...) {
        return OBSBOT_ERR_EXCEPTION;
    }
}

int32_t obsbot_set_record_resolution(int32_t index, int32_t res_type)
{
    try {
        auto dev = get_device(index);
        if (!dev) {
            return OBSBOT_ERR_NO_DEVICE;
        }
        return dev->cameraSetRecordResolutionR(
            static_cast<Device::DevVideoResType>(res_type));
    } catch (...) {
        return OBSBOT_ERR_EXCEPTION;
    }
}

int32_t obsbot_set_video_record(int32_t index, uint32_t operation, uint32_t param)
{
    try {
        auto dev = get_device(index);
        if (!dev) {
            return OBSBOT_ERR_NO_DEVICE;
        }
        return dev->cameraSetVideoRecordR(operation, param);
    } catch (...) {
        return OBSBOT_ERR_EXCEPTION;
    }
}

/* ── 图像 / 控制新增 ── */

int32_t obsbot_set_camera_mirror(int32_t index, int32_t mirror)
{
    try {
        auto dev = get_device(index);
        if (!dev) return OBSBOT_ERR_NO_DEVICE;
        return dev->cameraSetMirrorFlipR(mirror);
    } catch (...) { return OBSBOT_ERR_EXCEPTION; }
}

int32_t obsbot_set_ai_mode(int32_t index, int32_t mode, int32_t sub_mode)
{
    try {
        auto dev = get_device(index);
        if (!dev) return OBSBOT_ERR_NO_DEVICE;
        return dev->cameraSetAiModeU(
            static_cast<Device::AiWorkModeType>(mode), sub_mode);
    } catch (...) { return OBSBOT_ERR_EXCEPTION; }
}

int32_t obsbot_set_auto_focus(int32_t index, int32_t auto_mode)
{
    try {
        auto dev = get_device(index);
        if (!dev) return OBSBOT_ERR_NO_DEVICE;
        return dev->cameraSetAutoFocusModeR(
            static_cast<Device::DevAutoFocusType>(auto_mode));
    } catch (...) { return OBSBOT_ERR_EXCEPTION; }
}

int32_t obsbot_set_manual_focus(int32_t index, int32_t focus_val)
{
    try {
        auto dev = get_device(index);
        if (!dev) return OBSBOT_ERR_NO_DEVICE;
        return dev->cameraSetFocusPosR(focus_val);
    } catch (...) { return OBSBOT_ERR_EXCEPTION; }
}

int32_t obsbot_set_exposure_compensation(int32_t index, int32_t ev_index)
{
    try {
        auto dev = get_device(index);
        if (!dev) return OBSBOT_ERR_NO_DEVICE;
        return dev->cameraSetSAEEvBiasR(
            static_cast<Device::DevAEEvBiasType>(ev_index));
    } catch (...) { return OBSBOT_ERR_EXCEPTION; }
}

int32_t obsbot_set_anti_flicker(int32_t index, int32_t freq)
{
    try {
        auto dev = get_device(index);
        if (!dev) return OBSBOT_ERR_NO_DEVICE;
        return dev->cameraSetAntiFlickR(freq);
    } catch (...) { return OBSBOT_ERR_EXCEPTION; }
}

int32_t obsbot_set_fov(int32_t index, int32_t fov_type)
{
    try {
        auto dev = get_device(index);
        if (!dev) return OBSBOT_ERR_NO_DEVICE;
        return dev->cameraSetFovU(static_cast<Device::FovType>(fov_type));
    } catch (...) { return OBSBOT_ERR_EXCEPTION; }
}

int32_t obsbot_set_zoom(int32_t index, float zoom)
{
    if (!std::isfinite(zoom) || zoom < 1.0f || zoom > 2.0f) return OBSBOT_ERR_BAD_ARG;
    try {
        auto dev = get_device(index);
        if (!dev) return OBSBOT_ERR_NO_DEVICE;
        return dev->cameraSetZoomAbsoluteR(zoom);
    } catch (...) { return OBSBOT_ERR_EXCEPTION; }
}

int32_t obsbot_get_zoom(int32_t index, float *out_zoom)
{
    if (!out_zoom) return OBSBOT_ERR_BAD_ARG;
    try {
        auto dev = get_device(index);
        if (!dev) return OBSBOT_ERR_NO_DEVICE;
        return dev->cameraGetZoomAbsoluteR(*out_zoom);
    } catch (...) { return OBSBOT_ERR_EXCEPTION; }
}

int32_t obsbot_set_wdr(int32_t index, int32_t wdr_mode)
{
    try {
        auto dev = get_device(index);
        if (!dev) return OBSBOT_ERR_NO_DEVICE;
        return dev->cameraSetWdrR(wdr_mode);
    } catch (...) { return OBSBOT_ERR_EXCEPTION; }
}

int32_t obsbot_set_gimbal_speed(int32_t index, double pitch, double pan)
{
    if (!std::isfinite(pitch) || !std::isfinite(pan) ||
        std::abs(pitch) > 90.0 || std::abs(pan) > 180.0) {
        return OBSBOT_ERR_BAD_ARG;
    }
    try {
        auto dev = get_device(index);
        if (!dev) return OBSBOT_ERR_NO_DEVICE;
        return dev->aiSetGimbalSpeedCtrlR(pitch, pan, 0.0);
    } catch (...) { return OBSBOT_ERR_EXCEPTION; }
}

int32_t obsbot_get_gimbal_angles(int32_t index, float angles[3])
{
    if (!angles) return OBSBOT_ERR_BAD_ARG;
    try {
        auto dev = get_device(index);
        if (!dev) return OBSBOT_ERR_NO_DEVICE;
        return dev->gimbalGetAttitudeInfoR(angles);
    } catch (...) { return OBSBOT_ERR_EXCEPTION; }
}

void obsbot_close(void)
{
    try {
        g_devices.clear();
        Devices::get().close();
    } catch (...) {
    }
}

}  // extern "C"

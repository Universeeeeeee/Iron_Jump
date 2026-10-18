#define _WIN32_WINNT 0x0A00
#include <windows.h>
#include <stddef.h>

/* Read-only OS metadata; no affinity, priority, power or timer setters. */
__declspec(dllexport) void __cdecl CurrentCpu(DWORD *out)
{
    PROCESSOR_NUMBER p;
    GetCurrentProcessorNumberEx(&p);
    out[0] = p.Group; out[1] = p.Number;
}

__declspec(dllexport) DWORD __cdecl CpuSets(void *buffer, DWORD bytes, DWORD *needed)
{
    return GetSystemCpuSetInformation((PSYSTEM_CPU_SET_INFORMATION)buffer, bytes, needed, NULL, 0)
        ? ERROR_SUCCESS : GetLastError();
}

__declspec(dllexport) void __cdecl CpuSetLayout(DWORD *out)
{
    out[0] = (DWORD)sizeof(SYSTEM_CPU_SET_INFORMATION);
    out[1] = (DWORD)offsetof(SYSTEM_CPU_SET_INFORMATION, CpuSet.Id);
    out[2] = (DWORD)offsetof(SYSTEM_CPU_SET_INFORMATION, CpuSet.Group);
    out[3] = (DWORD)offsetof(SYSTEM_CPU_SET_INFORMATION, CpuSet.LogicalProcessorIndex);
    out[4] = (DWORD)offsetof(SYSTEM_CPU_SET_INFORMATION, CpuSet.CoreIndex);
    out[5] = (DWORD)offsetof(SYSTEM_CPU_SET_INFORMATION, CpuSet.EfficiencyClass);
}

__declspec(dllexport) DWORD __cdecl PowerState(DWORD *out)
{
    PROCESS_POWER_THROTTLING_STATE s = {0};
    s.Version = PROCESS_POWER_THROTTLING_CURRENT_VERSION;
    if (!GetProcessInformation(GetCurrentProcess(), ProcessPowerThrottling, &s, sizeof(s)))
        return GetLastError();
    out[0] = s.Version; out[1] = s.ControlMask; out[2] = s.StateMask;
    return ERROR_SUCCESS;
}

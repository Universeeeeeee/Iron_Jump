#include <windows.h>
#include <Python.h>

static HANDLE beat_thread, waiter_thread, request_event;
static volatile LONG stop_threads;
static volatile LONG64 *oracle;

static DWORD WINAPI free_heartbeat(LPVOID unused)
{
    (void)unused;
    while (!InterlockedCompareExchange(&stop_threads, 0, 0)) {
        InterlockedIncrement64(oracle + 3);
        YieldProcessor();
    }
    return 0;
}

static DWORD WINAPI acquire_gil(LPVOID unused)
{
    (void)unused;
    for (;;) {
        LONG64 phase;
        PyGILState_STATE gil;
        if (WaitForSingleObject(request_event, 15000) != WAIT_OBJECT_0) return 1;
        if (InterlockedCompareExchange(&stop_threads, 0, 0)) return 0;
        phase = InterlockedCompareExchange64(oracle + 1, 0, 0);
        InterlockedExchange64(oracle + 4, phase);
        gil = PyGILState_Ensure();
        InterlockedExchange64(oracle + 5, phase);
        PyGILState_Release(gil);
    }
}

__declspec(dllexport) DWORD __cdecl Prepare(volatile LONG64 *state)
{
    DWORD beat_tid = 0, waiter_tid = 0;
    oracle = state;
    request_event = CreateEventW(NULL, FALSE, FALSE, NULL);
    if (!request_event) return 0;
    beat_thread = CreateThread(NULL, 0, free_heartbeat, NULL, 0, &beat_tid);
    waiter_thread = CreateThread(NULL, 0, acquire_gil, NULL, 0, &waiter_tid);
    if (!beat_thread || !waiter_thread) return 0;
    InterlockedExchange64(oracle + 6, beat_tid);
    return waiter_tid;
}

/* PyDLL owns the GIL throughout both marker boundaries and the wait. */
__declspec(dllexport) void __cdecl HoldNative(volatile LONG64 *state, int phase)
{
    InterlockedIncrement64(state);
    InterlockedExchange64(state + 1, phase);
    InterlockedExchange64(state + 2, GetCurrentThreadId());
    InterlockedIncrement64(state);
    SetEvent(request_event);
    Sleep(2500);
    InterlockedIncrement64(state);
    InterlockedExchange64(state + 1, 0);
    InterlockedExchange64(state + 2, 0);
    InterlockedIncrement64(state);
}

__declspec(dllexport) int __cdecl Finish(void)
{
    DWORD a = 1, b = 1;
    InterlockedExchange(&stop_threads, 1);
    if (!SetEvent(request_event)) return 0;
    if (WaitForSingleObject(waiter_thread, 10000) != WAIT_OBJECT_0 ||
        WaitForSingleObject(beat_thread, 10000) != WAIT_OBJECT_0) return 0;
    if (!GetExitCodeThread(waiter_thread, &a) || !GetExitCodeThread(beat_thread, &b)) return 0;
    CloseHandle(waiter_thread); CloseHandle(beat_thread); CloseHandle(request_event);
    return a == 0 && b == 0;
}

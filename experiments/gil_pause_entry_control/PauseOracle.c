#include <windows.h>
#include <Python.h>

static volatile LONG64 *state;
static volatile LONG stopping;
static HANDLE heartbeat, waiter;

static DWORD WINAPI beat(LPVOID unused)
{
    (void)unused;
    while (!InterlockedCompareExchange(&stopping, 0, 0)) {
        InterlockedIncrement64(state + 3);
        Sleep(1);
    }
    return 0;
}

static DWORD WINAPI request(LPVOID unused)
{
    LONG64 gate;
    PyGILState_STATE gil;
    (void)unused;
    do {
        gate = InterlockedCompareExchange64(state + 8, 0, 0);
        if (!gate) Sleep(1);
    } while (!gate && !InterlockedCompareExchange(&stopping, 0, 0));
    if (gate == 1) {
        InterlockedExchange64(state + 4, 1);
        gil = PyGILState_Ensure();
        InterlockedExchange64(state + 5, 1);
        PyGILState_Release(gil);
    }
    InterlockedExchange64(state + 11, gate);
    return 0;
}

__declspec(dllexport) DWORD __cdecl Prepare(volatile LONG64 *shared)
{
    DWORD beat_tid = 0, waiter_tid = 0;
    state = shared;
    heartbeat = CreateThread(NULL, 0, beat, NULL, 0, &beat_tid);
    waiter = CreateThread(NULL, 0, request, NULL, 0, &waiter_tid);
    if (!heartbeat || !waiter) return 0;
    InterlockedExchange64(state + 6, beat_tid);
    InterlockedExchange64(state + 7, waiter_tid);
    return waiter_tid;
}

/* PyDLL holds the GIL; owner heartbeat independently tests delivered suspension. */
__declspec(dllexport) void __cdecl HoldNative(void)
{
    DWORD i;
    InterlockedIncrement64(state);
    InterlockedExchange64(state + 1, 1);
    InterlockedExchange64(state + 2, GetCurrentThreadId());
    InterlockedIncrement64(state);
    for (i = 0; i < 10000; ++i) {
        if (InterlockedCompareExchange64(state + 10, 0, 0)) break;
        InterlockedIncrement64(state + 9);
        Sleep(1);
    }
    InterlockedIncrement64(state);
    InterlockedExchange64(state + 1, 0);
    InterlockedExchange64(state + 2, 0);
    InterlockedIncrement64(state);
}

__declspec(dllexport) int __cdecl Finish(void)
{
    DWORD a = 1, b = 1;
    InterlockedExchange(&stopping, 1);
    if (WaitForSingleObject(waiter, 10000) != WAIT_OBJECT_0 ||
        WaitForSingleObject(heartbeat, 10000) != WAIT_OBJECT_0) return 0;
    if (!GetExitCodeThread(waiter, &a) || !GetExitCodeThread(heartbeat, &b)) return 0;
    CloseHandle(waiter); CloseHandle(heartbeat);
    return a == 0 && b == 0;
}

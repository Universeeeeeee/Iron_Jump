#include <windows.h>

static HANDLE beat_thread;
static volatile LONG stop_beat;
static volatile LONG64 *oracle;

/* This OS thread never attaches to Python and never acquires the GIL. */
static DWORD WINAPI free_heartbeat(LPVOID unused)
{
    (void)unused;
    while (!InterlockedCompareExchange(&stop_beat, 0, 0)) {
        InterlockedIncrement64(oracle + 3);
        YieldProcessor();
    }
    return 0;
}

__declspec(dllexport) DWORD __cdecl PrepareBeat(volatile LONG64 *state)
{
    DWORD tid = 0;
    oracle = state;
    beat_thread = CreateThread(NULL, 0, free_heartbeat, NULL, 0, &tid);
    return beat_thread ? tid : 0;
}

__declspec(dllexport) int __cdecl FinishBeat(void)
{
    DWORD code = 1;
    InterlockedExchange(&stop_beat, 1);
    if (WaitForSingleObject(beat_thread, 10000) != WAIT_OBJECT_0) return 0;
    if (!GetExitCodeThread(beat_thread, &code)) return 0;
    CloseHandle(beat_thread);
    return code == 0;
}

/* PyDLL retains the GIL across this call. No Python marker boundary gap. */
__declspec(dllexport) void __cdecl HoldNative(volatile LONG64 *state, int phase, DWORD milliseconds)
{
    InterlockedIncrement64(state);
    InterlockedExchange64(state + 1, phase);
    InterlockedExchange64(state + 2, GetCurrentThreadId());
    InterlockedIncrement64(state);
    Sleep(milliseconds);
    InterlockedIncrement64(state);
    InterlockedExchange64(state + 1, 0);
    InterlockedExchange64(state + 2, 0);
    InterlockedIncrement64(state);
}

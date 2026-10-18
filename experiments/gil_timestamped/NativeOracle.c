#include <windows.h>

/* Called through ctypes.PyDLL. Mark only the native interval, with no Python
   bytecode checkpoint between the marker and the protected native wait. */
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

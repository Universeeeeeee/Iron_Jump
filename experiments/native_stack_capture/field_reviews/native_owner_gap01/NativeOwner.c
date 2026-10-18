#include <windows.h>
#include <Python.h>

static HANDLE thread_handle, go_event;
static volatile LONG64 *oracle;

static DWORD WINAPI hold_without_python_frame(LPVOID unused)
{
    PyGILState_STATE gil;
    (void)unused;
    if (WaitForSingleObject(go_event, 10000) != WAIT_OBJECT_0) return 1;
    gil = PyGILState_Ensure();
    InterlockedIncrement64(oracle);
    InterlockedExchange64(oracle + 1, 1);
    InterlockedExchange64(oracle + 2, GetCurrentThreadId());
    InterlockedIncrement64(oracle);
    Sleep(5000);
    InterlockedIncrement64(oracle);
    InterlockedExchange64(oracle + 1, 0);
    InterlockedExchange64(oracle + 2, 0);
    InterlockedIncrement64(oracle);
    PyGILState_Release(gil);
    return 0;
}

__declspec(dllexport) DWORD __cdecl Prepare(volatile LONG64 *state)
{
    DWORD tid = 0;
    oracle = state;
    go_event = CreateEventW(NULL, TRUE, FALSE, NULL);
    if (!go_event) return 0;
    thread_handle = CreateThread(NULL, 0, hold_without_python_frame, NULL, 0, &tid);
    if (!thread_handle) { CloseHandle(go_event); return 0; }
    return tid;
}

__declspec(dllexport) int __cdecl Go(void) { return SetEvent(go_event) != 0; }

__declspec(dllexport) int __cdecl Finish(void)
{
    DWORD code = 1;
    if (WaitForSingleObject(thread_handle, 15000) != WAIT_OBJECT_0) return 0;
    if (!GetExitCodeThread(thread_handle, &code)) return 0;
    CloseHandle(thread_handle);
    CloseHandle(go_event);
    return code == 0;
}

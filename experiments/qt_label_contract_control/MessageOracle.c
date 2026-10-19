#include <windows.h>
#include <Python.h>
#include <string.h>

typedef struct {
    DWORD tid;
    LONG phase;
    LONG message_type;
    LONG gil;
    LONGLONG qpc;
} Row;

static Row rows[32];
static volatile LONG count = 0, phase = 0, failed = 0;

__declspec(dllexport) LONG OracleRowSize(void) { return (LONG)sizeof(Row); }

__declspec(dllexport) void OracleReset(void) {
    memset(rows, 0, sizeof(rows));
    count = phase = failed = 0;
}

__declspec(dllexport) void OraclePhase(LONG value) {
    InterlockedExchange(&phase, value);
}

/* QtMsgHandler has three scalar/reference arguments under the Windows x64 ABI.
   Never dereference Qt data or enter a Python callback. PyGILState_Check does
   not acquire the GIL; the direct-call negative control checks its sensitivity. */
__declspec(dllexport) void OracleMessage(int type, const void *context, const void *message) {
    LONG current = InterlockedCompareExchange(&phase, 0, 0), i;
    LARGE_INTEGER qpc;
    (void)context;
    (void)message;
    if (!current) return;
    i = InterlockedIncrement(&count) - 1;
    if (i >= 32 || !QueryPerformanceCounter(&qpc)) {
        InterlockedExchange(&failed, 1);
        return;
    }
    rows[i].tid = GetCurrentThreadId();
    rows[i].phase = current;
    rows[i].message_type = (LONG)type;
    rows[i].gil = (LONG)PyGILState_Check();
    rows[i].qpc = qpc.QuadPart;
}

__declspec(dllexport) LONG OracleCopy(Row *output, LONG capacity) {
    LONG n = InterlockedCompareExchange(&count, 0, 0);
    if (failed || n < 0 || n > capacity || n > 32) return -1;
    memcpy(output, rows, (size_t)n * sizeof(Row));
    return n;
}

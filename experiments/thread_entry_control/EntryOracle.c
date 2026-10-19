#include <windows.h>

__declspec(dllexport) DWORD WINAPI EntryA(LPVOID gate)
{
    return WaitForSingleObject((HANDLE)gate, 5000) == WAIT_OBJECT_0 ? 11 : 101;
}

__declspec(dllexport) DWORD WINAPI EntryB(LPVOID gate)
{
    return WaitForSingleObject((HANDLE)gate, 5000) == WAIT_OBJECT_0 ? 22 : 102;
}

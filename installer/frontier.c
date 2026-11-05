#define WIN32_LEAN_AND_MEAN
#include <windows.h>
int main(void) {
    DWORD written;
    HANDLE mutex = CreateMutexW(NULL, FALSE, L"Local\\FrontierConsoleRunning");
    SetConsoleTitleW(L"Frontier Console");
    WriteFile(GetStdHandle(STD_OUTPUT_HANDLE), "Hello World\r\n", 13, &written, NULL);
    Sleep(INFINITE);
    CloseHandle(mutex);
    return 0;
}

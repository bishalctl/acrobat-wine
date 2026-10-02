/* EndTask compatibility for Wine 11.18. See Microsoft's winuser.h contract.
 * This implements window/process cleanup only; it does not change Acrobat.
 */
#include <windows.h>

static void log_call(HWND window, DWORD pid, BOOL force, const char *stage)
{
    WCHAR path[32768];
    char line[256];
    DWORD count;
    HANDLE file;
    int length;
    if (!GetEnvironmentVariableW(L"ACROBAT_WINE_ENDTASK_LOG", path, 32768)) return;
    file = CreateFileW(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                       NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return;
    length = wsprintfA(line, "EndTask hwnd=%p owner=%lu caller=%lu force=%u %s\r\n",
                       window, pid, GetCurrentProcessId(), force, stage);
    WriteFile(file, line, length, &count, NULL);
    CloseHandle(file);
}

BOOL WINAPI WineEndTask(HWND window, BOOL shutdown, BOOL force)
{
    DWORD pid = 0, thread;
    DWORD_PTR result = 0;
    HANDLE process;
    BOOL terminated;
    DWORD error;
    (void)shutdown;

    thread = GetWindowThreadProcessId(window, &pid);
    if (!thread) return FALSE;
    log_call(window, pid, force, "request");
    SendMessageTimeoutW(window, WM_CLOSE, 0, 0,
                        SMTO_ABORTIFHUNG | SMTO_BLOCK, 5000, &result);
    if (!IsWindow(window)) return TRUE;
    if (!force)
    {
        SetLastError(ERROR_TIMEOUT);
        return FALSE;
    }
    if (pid == GetCurrentProcessId() && thread == GetCurrentThreadId())
        return DestroyWindow(window);

    /* A window in another process cannot be destroyed by DestroyWindow.
     * The forced form ends that window's owning process after WM_CLOSE fails.
     */
    process = OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, FALSE, pid);
    if (!process) return FALSE;
    log_call(window, pid, force, "force-close owner");
    terminated = TerminateProcess(process, 0);
    error = GetLastError();
    if (terminated) WaitForSingleObject(process, 5000);
    CloseHandle(process);
    SetLastError(error);
    return terminated;
}

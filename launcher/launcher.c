/* Stream Clipper.exe - tiny launcher: starts the app with the project's own Python (.venv).
   If the program isn't installed yet, it runs setup.bat. Build: see build_exe.bat / build_launcher.sh

   Administrator (v1.3.2): when not elevated, it asks the "Stream Clipper" scheduled task (created by the
   installer with highest privileges) to start it -> elevated, no UAC prompt over a game. No task (manual
   install): one normal UAC prompt; "No" = runs without admin. A file "no-admin.txt" next to the exe turns
   this off. */
#include <windows.h>
#include <shellapi.h>
#include <wchar.h>

static int exists(const wchar_t *p) { DWORD a = GetFileAttributesW(p); return a != INVALID_FILE_ATTRIBUTES; }

static int elevated(void) {
    HANDLE t; TOKEN_ELEVATION e; DWORD n; int r = 0;
    if (OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &t)) {
        if (GetTokenInformation(t, TokenElevation, &e, sizeof(e), &n)) r = e.TokenIsElevated != 0;
        CloseHandle(t);
    }
    return r;
}

/* 1 = an elevated copy was started (this one should exit) */
static int relaunch_elevated(const wchar_t *dir) {
    wchar_t sys[MAX_PATH], cl[MAX_PATH * 2], self[MAX_PATH];
    GetSystemDirectoryW(sys, MAX_PATH);
    swprintf(cl, MAX_PATH * 2, L"\"%ls\\schtasks.exe\" /run /tn \"Stream Clipper\"", sys);
    STARTUPINFOW si = { sizeof(si) }; PROCESS_INFORMATION pi; DWORD code = 1;
    if (CreateProcessW(NULL, cl, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, dir, &si, &pi)) {
        if (WaitForSingleObject(pi.hProcess, 15000) == WAIT_OBJECT_0) GetExitCodeProcess(pi.hProcess, &code);
        CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
        if (code == 0) return 1;
    }
    GetModuleFileNameW(NULL, self, MAX_PATH);
    SHELLEXECUTEINFOW se = { sizeof(se) };
    se.lpVerb = L"runas"; se.lpFile = self; se.lpParameters = L"--elevated"; se.lpDirectory = dir; se.nShow = SW_SHOWNORMAL;
    return ShellExecuteExW(&se) ? 1 : 0;      /* UAC "No" -> 0 -> run without admin */
}

int WINAPI wWinMain(HINSTANCE h, HINSTANCE p, PWSTR cmd, int show) {
    wchar_t dir[MAX_PATH], py[MAX_PATH], setup[MAX_PATH], cl[MAX_PATH * 2];
    GetModuleFileNameW(NULL, dir, MAX_PATH);
    wchar_t *s = wcsrchr(dir, L'\\'); if (s) *s = 0;
    swprintf(py, MAX_PATH, L"%ls\\.venv\\Scripts\\pythonw.exe", dir);
    swprintf(setup, MAX_PATH, L"%ls\\setup.bat", dir);
    if (!exists(py)) {
        if (!exists(setup)) {
            MessageBoxW(NULL, L"setup.bat not found next to Stream Clipper.exe. Put the exe in the program folder or reinstall.",
                        L"Stream Clipper", MB_ICONERROR);
            return 1;
        }
        if (MessageBoxW(NULL, L"Stream Clipper is not set up yet. Run the setup now (setup.bat)?",
                        L"Stream Clipper", MB_YESNO | MB_ICONQUESTION) == IDYES)
            ShellExecuteW(NULL, L"open", setup, NULL, dir, SW_SHOWNORMAL);
        return 0;
    }
    wchar_t optout[MAX_PATH];
    swprintf(optout, MAX_PATH, L"%ls\\no-admin.txt", dir);
    if (!elevated() && !wcsstr(cmd, L"--elevated") && !exists(optout) && relaunch_elevated(dir))
        return 0;
    swprintf(cl, MAX_PATH * 2, L"\"%ls\" -m streamclip app", py);
    STARTUPINFOW si = { sizeof(si) }; PROCESS_INFORMATION pi;
    if (!CreateProcessW(NULL, cl, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, dir, &si, &pi)) {
        MessageBoxW(NULL, L"Cannot start Python from .venv. Run setup.bat again or reinstall.", L"Stream Clipper", MB_ICONERROR);
        return 1;
    }
    CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
    return 0;
}

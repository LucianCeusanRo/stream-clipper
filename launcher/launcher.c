/* Stream Clipper.exe - tiny launcher: starts the app with the project's own Python (.venv).
   If the program isn't installed yet, it runs setup.bat. Build: see build_exe.bat / build_launcher.sh */
#include <windows.h>
#include <shellapi.h>
#include <wchar.h>

static int exists(const wchar_t *p) { DWORD a = GetFileAttributesW(p); return a != INVALID_FILE_ATTRIBUTES; }

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
    swprintf(cl, MAX_PATH * 2, L"\"%ls\" -m streamclip app", py);
    STARTUPINFOW si = { sizeof(si) }; PROCESS_INFORMATION pi;
    if (!CreateProcessW(NULL, cl, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, dir, &si, &pi)) {
        MessageBoxW(NULL, L"Cannot start Python from .venv. Run setup.bat again or reinstall.", L"Stream Clipper", MB_ICONERROR);
        return 1;
    }
    CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
    return 0;
}

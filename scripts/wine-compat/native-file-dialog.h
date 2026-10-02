/* Acrobat's opt-in Linux portal bridge. Included by Wine's itemdlg.c.
 * SPDX-License-Identifier: LGPL-2.1-or-later
 * Protocol and Linux peer: packaging/native_file_chooser.py.
 */

#define ACROBAT_PICKER_MAGIC 0x31505741
#define ACROBAT_PICKER_LIMIT (1024 * 1024)

static BOOL picker_write(HANDLE file, const void *data, DWORD size)
{
    DWORD written;
    return WriteFile(file, data, size, &written, NULL) && written == size;
}

static BOOL picker_read(HANDLE file, void *data, DWORD size)
{
    DWORD read;
    return ReadFile(file, data, size, &read, NULL) && read == size;
}

static BOOL picker_write_string(HANDLE file, const WCHAR *value)
{
    DWORD size = value ? lstrlenW(value) : 0;
    return size <= 32767 && picker_write(file, &size, sizeof(size)) &&
           picker_write(file, value, size * sizeof(WCHAR));
}

static WCHAR *picker_read_string(HANDLE file)
{
    DWORD size;
    WCHAR *value;
    if (!picker_read(file, &size, sizeof(size)) || size > 32767) return NULL;
    if (!(value = malloc((size + 1) * sizeof(WCHAR)))) return NULL;
    if (!picker_read(file, value, size * sizeof(WCHAR)))
    {
        free(value);
        return NULL;
    }
    value[size] = 0;
    if (lstrlenW(value) != size)
    {
        free(value);
        return NULL;
    }
    return value;
}

static BOOL picker_alive(const WCHAR *path)
{
    WIN32_FILE_ATTRIBUTE_DATA data;
    FILETIME now;
    ULONGLONG current, modified;
    if (!GetFileAttributesExW(path, GetFileExInfoStandard, &data)) return FALSE;
    GetSystemTimeAsFileTime(&now);
    current = ((ULONGLONG)now.dwHighDateTime << 32) | now.dwLowDateTime;
    modified = ((ULONGLONG)data.ftLastWriteTime.dwHighDateTime << 32) | data.ftLastWriteTime.dwLowDateTime;
    return current <= modified || current - modified < 100000000; /* 10 seconds */
}

static BOOL picker_has_visible_controls(FileDialogImpl *This)
{
    customctrl *control;
    LIST_FOR_EACH_ENTRY(control, &This->cctrls, customctrl, entry)
        if (control->cdcstate & CDCS_VISIBLE) return TRUE;
    return This->hmenu_opendropdown != NULL;
}

static HRESULT picker_results(FileDialogImpl *This, HANDLE file)
{
    DWORD header[4], attr, i, count, extra;
    ITEMIDLIST **pidls;
    IShellItemArray *results = NULL;
    IShellItem *first = NULL, *folder = NULL;
    WCHAR *value;
    BYTE trailing;
    HRESULT hr = E_NOTIMPL;
    LARGE_INTEGER size;

    if (!GetFileSizeEx(file, &size) || size.QuadPart > ACROBAT_PICKER_LIMIT ||
        !picker_read(file, header, sizeof(header)) || header[0] != ACROBAT_PICKER_MAGIC)
        return E_NOTIMPL;
    if (header[1] == 1) return HRESULT_FROM_WIN32(ERROR_CANCELLED);
    if (header[1] || !(count = header[3]) || count > 1024 ||
        (!(This->options & FOS_ALLOWMULTISELECT) && count != 1) ||
        (This->filterspec_count && header[2] >= This->filterspec_count))
        return E_NOTIMPL;
    if (!(pidls = calloc(count, sizeof(*pidls)))) return E_OUTOFMEMORY;
    for (i = 0; i < count; ++i)
    {
        if (!(value = picker_read_string(file))) { hr = E_NOTIMPL; goto done; }
        /* The launcher maps Z: to /. Do not accept relative, device or UNC paths. */
        attr = GetFileAttributesW(value);
        if (wcsncmp(value, L"Z:\\", 3) || attr == INVALID_FILE_ATTRIBUTES ||
            (!!(This->options & FOS_PICKFOLDERS) != !!(attr & FILE_ATTRIBUTE_DIRECTORY)))
        {
            free(value);
            hr = E_NOTIMPL;
            goto done;
        }
        hr = SHParseDisplayName(value, NULL, &pidls[i], 0, NULL);
        free(value);
        if (FAILED(hr)) { hr = E_NOTIMPL; goto done; }
    }
    if (!ReadFile(file, &trailing, 1, &extra, NULL) || extra) { hr = E_NOTIMPL; goto done; }
    hr = SHCreateShellItemArrayFromIDLists(count, (PCIDLIST_ABSOLUTE *)pidls, &results);
    if (FAILED(hr)) goto done;

    if (SUCCEEDED(IShellItemArray_GetItemAt(results, 0, &first)))
    {
        IShellItem_GetParent(first, &folder);
        IShellItem_Release(first);
    }
    if (folder)
    {
        if (events_OnFolderChanging(This, folder) != S_OK)
        {
            IShellItem_Release(folder);
            hr = E_NOTIMPL;
            goto done;
        }
        if (This->psi_folder) IShellItem_Release(This->psi_folder);
        This->psi_folder = folder;
        events_OnFolderChange(This);
    }
    if (This->psia_results) IShellItemArray_Release(This->psia_results);
    This->psia_results = results;
    results = NULL;
    if (This->psia_selection) IShellItemArray_Release(This->psia_selection);
    This->psia_selection = This->psia_results;
    IShellItemArray_AddRef(This->psia_selection);
    fill_filename_from_selection(This);
    if (This->filterspec_count && This->filetypeindex != header[2])
    {
        This->filetypeindex = header[2];
        set_current_filter(This, This->filterspecs[header[2]].pszSpec);
        events_OnTypeChange(This);
    }
    events_OnSelectionChange(This);
    /* Custom UI or a veto must still be handled by the original Wine dialog. */
    hr = !picker_has_visible_controls(This) && events_OnFileOk(This) == S_OK ? S_OK : E_NOTIMPL;
done:
    if (results) IShellItemArray_Release(results);
    for (i = 0; i < count; ++i) ILFree(pidls[i]);
    free(pidls);
    return hr;
}

static HRESULT show_native_open_dialog(FileDialogImpl *This, HWND owner)
{
    static LONG sequence;
    WCHAR directory[1024], temporary[1152], request[1152], response[1152], ready[1056];
    WCHAR *folder_path = NULL;
    IShellItem *folder;
    HWND focus = NULL;
    HANDLE file = INVALID_HANDLE_VALUE;
    DWORD length, header[5], i;
    BOOL written = FALSE, disabled = FALSE;
    HRESULT hr = E_NOTIMPL;
    MSG message;
    const DWORD supported = FOS_NOCHANGEDIR | FOS_FORCEFILESYSTEM | FOS_PICKFOLDERS |
        FOS_ALLOWMULTISELECT | FOS_PATHMUSTEXIST | FOS_FILEMUSTEXIST | FOS_DONTADDTORECENT;

    if (This->dlg_type != ITEMDLG_TYPE_OPEN || (This->options & ~supported) ||
        This->filterspec_count > 128 || picker_has_visible_controls(This)) return E_NOTIMPL;
    length = GetEnvironmentVariableW(L"ACROBAT_FILE_CHOOSER_DIR", directory, ARRAY_SIZE(directory));
    if (!length || length >= ARRAY_SIZE(directory) || wcsncmp(directory, L"Z:\\", 3)) return E_NOTIMPL;
    swprintf(ready, ARRAY_SIZE(ready), L"%s\\ready", directory);
    if (!picker_alive(ready)) return E_NOTIMPL;
    if (This->native_active || This->dlg_hwnd) return E_UNEXPECTED;
    if (!GetCurrentActCtx(&This->user_actctx)) This->user_actctx = INVALID_HANDLE_VALUE;
    This->native_active = TRUE;
    This->native_result = E_PENDING;
    if (This->filterspec_count) events_OnTypeChange(This);
    if (picker_has_visible_controls(This)) goto cleanup_context;

    swprintf(temporary, ARRAY_SIZE(temporary), L"%s\\%08lx-%08lx-%08lx.tmp", directory,
             GetCurrentProcessId(), GetCurrentThreadId(), InterlockedIncrement(&sequence));
    lstrcpyW(request, temporary);
    lstrcpyW(response, temporary);
    lstrcpyW(request + lstrlenW(request) - 3, L"req");
    lstrcpyW(response + lstrlenW(response) - 3, L"res");
    file = CreateFileW(temporary, GENERIC_WRITE, 0, NULL, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) goto cleanup_context;

    if (owner) owner = GetAncestor(owner, GA_ROOT);
    header[0] = ACROBAT_PICKER_MAGIC;
    header[1] = This->options;
    header[2] = This->filetypeindex;
    header[3] = This->filterspec_count;
    header[4] = (ULONG_PTR)GetPropW(owner, L"__wine_x11_whole_window");
    folder = This->psi_setfolder ? This->psi_setfolder :
             This->psi_folder ? This->psi_folder : This->psi_defaultfolder;
    if (folder) IShellItem_GetDisplayName(folder, SIGDN_FILESYSPATH, &folder_path);
    written = picker_write(file, header, sizeof(header)) &&
        picker_write_string(file, This->custom_title) && picker_write_string(file, This->custom_okbutton) &&
        picker_write_string(file, folder_path) && picker_write_string(file, This->set_filename);
    CoTaskMemFree(folder_path);
    for (i = 0; written && i < This->filterspec_count; ++i)
        written = picker_write_string(file, This->filterspecs[i].pszName) &&
                  picker_write_string(file, This->filterspecs[i].pszSpec);
    CloseHandle(file);
    file = INVALID_HANDLE_VALUE;
    if (!written || !MoveFileW(temporary, request)) goto cleanup_files;

    TRACE("Using desktop file picker for %p\n", owner);
    if (owner && IsWindowEnabled(owner))
    {
        focus = GetFocus();
        EnableWindow(owner, FALSE);
        disabled = TRUE;
    }
    for (;;)
    {
        if (This->native_result != E_PENDING) { hr = This->native_result; break; }
        if (owner && !IsWindow(owner)) { hr = HRESULT_FROM_WIN32(ERROR_CANCELLED); break; }
        file = CreateFileW(response, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_DELETE, NULL,
                           OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
        if (file != INVALID_HANDLE_VALUE)
        {
            hr = picker_results(This, file);
            CloseHandle(file);
            break;
        }
        if (!picker_alive(ready)) break;
        MsgWaitForMultipleObjectsEx(0, NULL, 100, QS_ALLINPUT, MWMO_INPUTAVAILABLE);
        for (i = 0; i < 64 && PeekMessageW(&message, NULL, 0, 0, PM_REMOVE); ++i)
        {
            if (message.message == WM_QUIT)
            {
                This->native_result = HRESULT_FROM_WIN32(ERROR_CANCELLED);
                PostQuitMessage(message.wParam);
                break;
            }
            TranslateMessage(&message);
            DispatchMessageW(&message);
        }
    }
    if (disabled && IsWindow(owner))
    {
        EnableWindow(owner, TRUE);
        SetActiveWindow(owner);
        if (focus && IsWindow(focus)) SetFocus(focus);
    }
cleanup_files:
    DeleteFileW(temporary);
    DeleteFileW(request);
    DeleteFileW(response);
cleanup_context:
    This->native_active = FALSE;
    if (This->user_actctx != INVALID_HANDLE_VALUE)
    {
        ReleaseActCtx(This->user_actctx);
        This->user_actctx = INVALID_HANDLE_VALUE;
    }
    TRACE("Desktop file picker returned %#lx%s\n", hr, hr == E_NOTIMPL ? "; using Wine dialog" : "");
    return hr;
}

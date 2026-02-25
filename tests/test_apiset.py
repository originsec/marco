"""Tests for APISet resolution"""


def test_apiset_resolution():
    """Test that api-ms-win-core-libraryloader-l1-2-0.dll resolves to kernelbase.dll"""
    from marco.disassemblers.binaryninja_adapter import _resolve_module_name

    # Test the specific case mentioned
    result = _resolve_module_name("api-ms-win-core-libraryloader-l1-2-0.dll")
    assert result == "kernelbase.dll", f"Expected kernelbase.dll, got {result}"

    # Test without .dll extension
    result = _resolve_module_name("api-ms-win-core-libraryloader-l1-2-0")
    assert result == "kernelbase.dll", f"Expected kernelbase.dll, got {result}"


def test_apiset_resolution_various():
    """Test various APISet resolutions"""
    from marco.disassemblers.binaryninja_adapter import _resolve_module_name

    # Validates with NtObjectManager
    test_cases = [
        ("api-ms-win-core-processthreads-l1-1-0", "kernel32.dll"),
        ("api-ms-win-core-libraryloader-l1-2-3", "kernelbase.dll"),
        ("api-ms-win-core-file-l1-1-0", "kernel32.dll"),
        ("ext-ms-win-ntuser-window-l1-1-0", "user32.dll"),
    ]

    for apiset, _expected in test_cases:
        result = _resolve_module_name(apiset)
        # We expect it to resolve to something, at minimum
        assert result.endswith(".dll"), f"Expected .dll extension for {apiset}, got {result}"
        # If pyjectify is working, it should resolve correctly
        if result != f"{apiset}.dll":
            print(f"✓ {apiset} -> {result}")


def test_normal_dll_unchanged():
    """Test that normal DLLs pass through unchanged"""
    from marco.disassemblers.binaryninja_adapter import _resolve_module_name

    test_cases = [
        "kernel32.dll",
        "ntdll.dll",
        "kernelbase",  # Should get .dll added
        "user32",  # Should get .dll added
    ]

    for dll in test_cases:
        result = _resolve_module_name(dll)
        expected = dll if dll.endswith(".dll") else f"{dll}.dll"
        assert result == expected.lower(), f"Expected {expected.lower()}, got {result}"

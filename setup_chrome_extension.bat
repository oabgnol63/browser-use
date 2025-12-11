@echo off
setlocal

:: 1. Check for Admin rights (Exit if not Admin)
net session >nul 2>&1
if %errorLevel% neq 0 exit /b

:: 2. Cleanup: Remove any incorrect or old keys silently
reg delete "HKLM\SOFTWARE\Google\Chrome\ExtensionInstallForcelist" /f >nul 2>&1
reg delete "HKLM\SOFTWARE\Policies\Google\Chrome\ExtensionInstallForcelist" /f >nul 2>&1

:: 3. Create Policy Key
reg add "HKLM\SOFTWARE\Policies\Google\Chrome\ExtensionInstallForcelist" /f >nul

:: 4. Add Extension (ID;UpdateURL)
:: Extension ID from your screenshot: ddkjiahejlhfcafbddmgiahcphecmpfh
reg add "HKLM\SOFTWARE\Policies\Google\Chrome\ExtensionInstallForcelist" /v "1" /t REG_SZ /d "ddkjiahejlhfcafbddmgiahcphecmpfh;https://clients2.google.com/service/update2/crx" /f >nul

echo Chrome extension policy updated successfully.

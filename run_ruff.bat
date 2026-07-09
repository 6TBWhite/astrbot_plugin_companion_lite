@echo off
chcp 65001 >nul
echo ============================================
echo   CompanionLite Ruff 一键检查
echo ============================================
echo.

set PLUGIN_DIR=%~dp0
set PYTHON=python

echo [1/3] 格式化中...
%PYTHON% -m ruff format "%PLUGIN_DIR%"
if errorlevel 1 (
    echo ❌ 格式化失败
    pause
    exit /b 1
)
echo ✅ 格式化完成
echo.

echo [2/3] 自动修复中...
%PYTHON% -m ruff check "%PLUGIN_DIR%" --select E,F,W --fix
echo ✅ 自动修复完成
echo.

echo [3/3] 最终检查...
%PYTHON% -m ruff check "%PLUGIN_DIR%" --select E,F,W
if errorlevel 1 (
    echo ❌ 检查未通过
    pause
    exit /b 1
)
echo ✅ 检查通过
echo.

echo ============================================
echo   CI 红线检查 (E9,F63,F7,F82)
echo ============================================
%PYTHON% -m ruff check "%PLUGIN_DIR%" --select E9,F63,F7,F82
if errorlevel 1 (
    echo ❌ CI 红线检查失败
    pause
    exit /b 1
)
echo ✅ CI 红线检查通过
echo.

echo ============================================
echo   统计
echo ============================================
echo Python 文件数:
for %%f in ("%PLUGIN_DIR%*.py") do @echo   %%~nxf
echo.
echo 全部完成 ✓
pause

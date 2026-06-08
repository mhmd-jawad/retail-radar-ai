@ECHO OFF
pushd %~dp0

if "%1" == ""      goto help
if "%1" == "clean" goto clean
if "%1" == "html"  goto html
goto help

:help
sphinx-build -M help source _build %SPHINXOPTS% %O%
goto end

:clean
rmdir /s /q _build 2>nul
goto end

:html
sphinx-build -M html source _build %SPHINXOPTS% %O%
echo.
echo Build finished. Open _build\html\index.html
goto end

:end
popd

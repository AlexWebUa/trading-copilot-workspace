@echo off
REM Windows counterpart of run_mcp.sh — launches the MCP server that the
REM `claude` CLI backend talks to.
REM
REM Everything is resolved from %~dp0 (this file's own directory). The previous
REM version hardcoded D:\Projects\vibecoding\... and a .venv_mcp that no longer
REM exists, so it broke the moment the checkout moved.
REM
REM The venv interpreter is invoked directly rather than activated: activation
REM spawns a subshell, and an MCP server communicates over stdio — the one
REM channel a subshell disturbs.
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" -m copilot.mcp_server %*

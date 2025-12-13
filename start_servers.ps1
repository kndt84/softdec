# Start RTP Stream Viewer HTTP/1.1 Servers (Frontend + Backend)
Write-Host "Starting RTP Stream Viewer HTTP/1.1 Servers..." -ForegroundColor Green
Write-Host ""

# Check if required files exist
$requiredFiles = @("index.html", "config.yaml")
$missingFiles = @()

foreach ($file in $requiredFiles) {
    if (!(Test-Path $file)) {
        $missingFiles += $file
    }
}

if ($missingFiles.Count -gt 0) {
    Write-Host "ERROR: Missing required files!" -ForegroundColor Red
    foreach ($file in $missingFiles) {
        Write-Host "  - $file" -ForegroundColor Red
    }
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

# Check if Python dependencies are installed
Write-Host "Checking dependencies..." -ForegroundColor Gray
try {
    python -c "import yaml" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "YAML not found"
    }
} catch {
    Write-Host "ERROR: Required dependencies not installed!" -ForegroundColor Red
    Write-Host "Please install:" -ForegroundColor Yellow
    Write-Host "  pip install pyyaml" -ForegroundColor Cyan
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "[OK] Required files found" -ForegroundColor Green
Write-Host "[OK] Dependencies installed" -ForegroundColor Green
Write-Host ""

# Start HTTP/1.1 Backend Server
Write-Host "Starting HTTP/1.1 Backend Server on port 8081 (HTTP)..." -ForegroundColor Yellow
$backend = Start-Process python -ArgumentList "backend_server.py" -PassThru -WindowStyle Normal

# Wait for backend to start
Write-Host "Waiting for backend server to start..." -ForegroundColor Gray
Start-Sleep -Seconds 3

# Start HTTP/1.1 Frontend Server
Write-Host "Starting HTTP/1.1 Frontend Server on port 8080 (HTTP)..." -ForegroundColor Yellow
$frontend = Start-Process python -ArgumentList "frontend_server.py" -PassThru -WindowStyle Normal

# Wait for frontend to start
Write-Host "Waiting for frontend server to start..." -ForegroundColor Gray
Start-Sleep -Seconds 3

Write-Host ""
Write-Host "HTTP/1.1 Servers started successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "=== Access Points ===" -ForegroundColor Cyan
Write-Host "   Frontend:    http://localhost:8080/" -ForegroundColor White
Write-Host "   Backend API: http://localhost:8081/" -ForegroundColor White
Write-Host ""
Write-Host "=== API Endpoints ===" -ForegroundColor Cyan
Write-Host "   MJPEG:       http://localhost:8081/mjpeg" -ForegroundColor Gray
Write-Host ""
Write-Host "=== Stable Configuration ===" -ForegroundColor Green
Write-Host "   - No SSL certificates required" -ForegroundColor Gray
Write-Host "   - No browser security warnings" -ForegroundColor Gray
Write-Host "   - Standard HTTP/1.1 protocol" -ForegroundColor Gray
Write-Host "   - Cross-origin requests supported" -ForegroundColor Gray
Write-Host ""
Write-Host "=== Connection Limits ===" -ForegroundColor Yellow
Write-Host "   - HTTP/1.1 has 6-8 stream limit per domain" -ForegroundColor Gray
Write-Host "   - Trade-off: Stability vs Stream Count" -ForegroundColor Gray
Write-Host ""
Write-Host "=== Architecture ===" -ForegroundColor Magenta
Write-Host "   - Frontend Server (port 8080): Serves HTML, JS, CSS" -ForegroundColor Gray
Write-Host "   - Backend Server (port 8081):  Provides RTP stream APIs" -ForegroundColor Gray
Write-Host "   - Both servers use HTTP/1.1 protocol" -ForegroundColor Gray
Write-Host ""
Write-Host "=== Browser Testing ===" -ForegroundColor Cyan
Write-Host "   Open browser DevTools -> Network tab -> Check 'Protocol' column shows 'http/1.1'" -ForegroundColor Gray
Write-Host ""
Write-Host "Press any key to stop all servers..." -ForegroundColor Yellow
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

Write-Host ""
Write-Host "Stopping HTTP/1.1 servers..." -ForegroundColor Red

# Stop Backend server
if (!$backend.HasExited) {
    Stop-Process -Id $backend.Id -Force
    Write-Host "[OK] Backend server stopped" -ForegroundColor Green
} else {
    Write-Host "[OK] Backend server already stopped" -ForegroundColor Gray
}

# Stop Frontend server
if (!$frontend.HasExited) {
    Stop-Process -Id $frontend.Id -Force
    Write-Host "[OK] Frontend server stopped" -ForegroundColor Green
} else {
    Write-Host "[OK] Frontend server already stopped" -ForegroundColor Gray
}

Write-Host ""
Write-Host "All servers shutdown complete." -ForegroundColor Green
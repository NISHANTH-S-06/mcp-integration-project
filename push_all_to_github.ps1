
# ============================================================
# PUSH ALL 5 PROJECTS TO GITHUB - NISHANTH-S-06
# ============================================================
# Run this script AFTER setting your GitHub PAT token below
# ============================================================

param(
    [Parameter(Mandatory=$true)]
    [string]$GitHubToken
)

$GitHubUser = "NISHANTH-S-06"
$headers = @{
    "Authorization" = "token $GitHubToken"
    "Accept" = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
}

# ============================================================
# PROJECTS CONFIGURATION
# ============================================================
$projects = @(
    @{
        Name        = "enterprise-ocr-platform"
        Description = "Enterprise OCR Platform — Intelligent document processing and automated data extraction."
        LocalPath   = "d:\OCR_MASTER\ocr-platform-complete"
        HasGit      = $true
        HasRemote   = $true
        ExistingRemote = "https://github.com/NISHANTH-S-06/ocr-platform-complete.git"
        NewRemoteName  = "nishanth"
        Branch      = "main"
        Topics      = @("ocr", "document-processing", "ai", "python", "enterprise")
    },
    @{
        Name        = "ifive-autoqa-x"
        Description = "iFive AutoQA X — AI-assisted QA testing and automation platform."
        LocalPath   = "d:\AUTO_QA_TESTING"
        HasGit      = $true
        HasRemote   = $false
        ExistingRemote = ""
        NewRemoteName  = "origin"
        Branch      = "main"
        Topics      = @("qa-automation", "testing", "ai", "python", "pytest")
    },
    @{
        Name        = "ailen-x-agent-platform"
        Description = "AILEN X — AI Agent Platform — AI agent-based assistant and automation system."
        LocalPath   = "d:\AGENT_ALINE_X_"
        HasGit      = $false
        HasRemote   = $false
        ExistingRemote = ""
        NewRemoteName  = "origin"
        Branch      = "main"
        Topics      = @("ai-agent", "automation", "llm", "python", "ollama")
    },
    @{
        Name        = "mcp-integration-project"
        Description = "MCP Integration Project — Model Context Protocol (MCP)-based tool integration for ERP data assistant."
        LocalPath   = "d:\MCP PROJECT"
        HasGit      = $false
        HasRemote   = $false
        ExistingRemote = ""
        NewRemoteName  = "origin"
        Branch      = "main"
        Topics      = @("mcp", "model-context-protocol", "erp", "fastapi", "python")
    },
    @{
        Name        = "neethivaan-ai"
        Description = "Neethivaan AI — AI-powered legal grievance platform for Tamil Nadu citizens."
        LocalPath   = "d:\Neethivaan"
        HasGit      = $true
        HasRemote   = $true
        ExistingRemote = "https://github.com/nishanthjd27/neethivaan.git"
        NewRemoteName  = "nishanth"
        Branch      = "main"
        Topics      = @("legal-tech", "ai", "nextjs", "python", "fastapi")
    }
)

# ============================================================
# GITIGNORE TEMPLATE (shared across all Python projects)
# ============================================================
$gitignoreContent = @"
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg
MANIFEST

# Virtual environments
.venv/
venv/
ENV/
env/
.env.local
.env.production

# Database files
*.db
*.sqlite
*.sqlite3

# Logs
*.log
logs/
out*.txt
backend_*.log
frontend_*.log

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Node
node_modules/
.next/
dist/
build/

# Large files / model caches
model_cache/
.paddlex/
*.paddleocr/
datasets/
uploads/
output/
*.pt
*.pth
*.onnx
*.pkl

# Backup directories
*backup*/
*BACKUP*/
*archive*/
*ARCHIVE*/
_FINAL_BACKUP*/
_codex_chrome*/

# Temp / scratch
tmp/
tmp_*/
scratch/
pytest_tmp/
.pytest_cache/
__pyrefly_virtual__/
*.tmp

# Secrets / sensitive
.env
.env.local
.env.production
*.pem
*.key

# Large SQL dumps
*.sql

# Binary / compiled
*.exe
*.dll
*.so
*.dylib

# Jupyter
.ipynb_checkpoints/

# Docker
*.tar
"@

function Write-Step { param($msg) Write-Host "`n[*] $msg" -ForegroundColor Cyan }
function Write-OK   { param($msg) Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "[!!] $msg" -ForegroundColor Yellow }
function Write-Fail { param($msg) Write-Host "[ERR] $msg" -ForegroundColor Red }

function Create-GitHubRepo {
    param($repoName, $description, $topics)
    
    Write-Step "Creating GitHub repo: $repoName"
    
    # Check if repo already exists
    try {
        $existing = Invoke-RestMethod -Uri "https://api.github.com/repos/$GitHubUser/$repoName" -Headers $headers -Method GET -ErrorAction Stop
        Write-Warn "Repo '$repoName' already exists on GitHub — skipping creation"
        return $true
    } catch {
        # 404 means doesn't exist, proceed to create
    }
    
    $body = @{
        name        = $repoName
        description = $description
        private     = $false
        auto_init   = $false
    } | ConvertTo-Json
    
    try {
        $result = Invoke-RestMethod -Uri "https://api.github.com/user/repos" -Headers $headers -Method POST -Body $body -ContentType "application/json"
        Write-OK "Created repo: https://github.com/$GitHubUser/$repoName"
        
        # Set topics
        if ($topics.Count -gt 0) {
            $topicBody = @{ names = $topics } | ConvertTo-Json
            Invoke-RestMethod -Uri "https://api.github.com/repos/$GitHubUser/$repoName/topics" -Headers $headers -Method PUT -Body $topicBody -ContentType "application/json" | Out-Null
            Write-OK "Set topics: $($topics -join ', ')"
        }
        return $true
    } catch {
        Write-Fail "Failed to create repo '$repoName': $_"
        return $false
    }
}

function Setup-GitRepo {
    param($project)
    
    $path = $project.LocalPath
    $name = $project.Name
    
    Write-Step "Setting up git for: $name (at $path)"
    
    if (-not (Test-Path $path)) {
        Write-Fail "Path does not exist: $path"
        return $false
    }
    
    # Write .gitignore
    $gitignorePath = Join-Path $path ".gitignore"
    if (-not (Test-Path $gitignorePath)) {
        Set-Content -Path $gitignorePath -Value $gitignoreContent -Encoding UTF8
        Write-OK "Created .gitignore"
    } else {
        Write-Warn ".gitignore already exists — not overwriting"
    }
    
    # Init git if needed
    $gitDir = Join-Path $path ".git"
    $gitDirHasContent = $false
    if (Test-Path $gitDir) {
        $gitContent = Get-ChildItem $gitDir -Force
        $gitDirHasContent = $gitContent.Count -gt 0
    }
    
    if (-not $gitDirHasContent) {
        Write-Step "Initializing git repository..."
        # Remove empty .git if exists
        if (Test-Path $gitDir) {
            Remove-Item $gitDir -Recurse -Force
        }
        git -C $path init -b main 2>&1 | Out-Null
        Write-OK "Initialized git repo"
    } else {
        Write-OK "Git repo already initialized"
    }
    
    # Configure git user for this repo
    git -C $path config user.name "NISHANTH-S-06" 2>&1 | Out-Null
    git -C $path config user.email "nishanthjd27@gmail.com" 2>&1 | Out-Null
    
    # Set up remote
    $remoteUrl = "https://$GitHubToken@github.com/$GitHubUser/$($project.Name).git"
    $remoteName = $project.NewRemoteName
    
    $existingRemotes = git -C $path remote 2>&1
    if ($existingRemotes -contains $remoteName) {
        git -C $path remote set-url $remoteName $remoteUrl 2>&1 | Out-Null
        Write-OK "Updated remote '$remoteName' URL"
    } else {
        git -C $path remote add $remoteName $remoteUrl 2>&1 | Out-Null
        Write-OK "Added remote '$remoteName'"
    }
    
    return $true
}

function Push-Project {
    param($project)
    
    $path = $project.LocalPath
    $name = $project.Name
    $remoteName = $project.NewRemoteName
    $branch = $project.Branch
    
    Write-Step "Adding and committing files for: $name"
    
    # Stage all files (respecting .gitignore)
    git -C $path add -A 2>&1 | Out-Null
    
    # Check if there's anything to commit
    $status = git -C $path status --porcelain 2>&1
    $hasChanges = git -C $path diff --cached --quiet; $exitCode = $LASTEXITCODE
    
    $logCount = git -C $path log --oneline -1 2>&1
    $hasCommits = ($LASTEXITCODE -eq 0)
    
    if ($hasCommits -and $exitCode -eq 0) {
        Write-OK "Nothing new to commit — pushing existing commits"
    } else {
        $commitMsg = "feat: initial commit - $($project.Description)"
        git -C $path commit -m $commitMsg 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "Commit may have issues (possibly nothing to commit)"
        } else {
            Write-OK "Committed files"
        }
    }
    
    # Ensure we're on main branch
    $currentBranch = git -C $path branch --show-current 2>&1
    if ($currentBranch -ne "main") {
        git -C $path checkout -b main 2>&1 | Out-Null
        Write-OK "Switched to main branch"
    }
    
    # Push to GitHub
    Write-Step "Pushing to GitHub: $name..."
    $pushResult = git -C $path push $remoteName main --force 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-OK "Successfully pushed: https://github.com/$GitHubUser/$name"
    } else {
        Write-Fail "Push failed for $name`n$pushResult"
        return $false
    }
    return $true
}

# ============================================================
# MAIN EXECUTION
# ============================================================
Write-Host "`n" + "="*60 -ForegroundColor Magenta
Write-Host " GITHUB PUSH SCRIPT - NISHANTH-S-06" -ForegroundColor Magenta
Write-Host " Pushing 5 Projects to GitHub" -ForegroundColor Magenta
Write-Host "="*60 -ForegroundColor Magenta

$results = @()

foreach ($project in $projects) {
    Write-Host "`n" + "-"*60 -ForegroundColor DarkCyan
    Write-Host " PROJECT: $($project.Name)" -ForegroundColor White
    Write-Host "-"*60 -ForegroundColor DarkCyan
    
    $created = Create-GitHubRepo -repoName $project.Name -description $project.Description -topics $project.Topics
    if (-not $created) {
        $results += [PSCustomObject]@{ Project = $project.Name; Status = "FAILED - Repo creation" }
        continue
    }
    
    $setup = Setup-GitRepo -project $project
    if (-not $setup) {
        $results += [PSCustomObject]@{ Project = $project.Name; Status = "FAILED - Git setup" }
        continue
    }
    
    $pushed = Push-Project -project $project
    if ($pushed) {
        $results += [PSCustomObject]@{ Project = $project.Name; Status = "SUCCESS - https://github.com/$GitHubUser/$($project.Name)" }
    } else {
        $results += [PSCustomObject]@{ Project = $project.Name; Status = "FAILED - Push error" }
    }
}

# ============================================================
# SUMMARY
# ============================================================
Write-Host "`n`n" + "="*60 -ForegroundColor Magenta
Write-Host " FINAL RESULTS" -ForegroundColor Magenta
Write-Host "="*60 -ForegroundColor Magenta
$results | ForEach-Object {
    if ($_.Status -like "SUCCESS*") {
        Write-Host "[OK]  $($_.Project)" -ForegroundColor Green
        Write-Host "      $($_.Status)" -ForegroundColor DarkGreen
    } else {
        Write-Host "[ERR] $($_.Project)" -ForegroundColor Red
        Write-Host "      $($_.Status)" -ForegroundColor DarkRed
    }
}

Write-Host "`nDone! Visit: https://github.com/$GitHubUser" -ForegroundColor Cyan

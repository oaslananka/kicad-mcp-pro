param(
    [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"

$pushTags = if ($env:PUSH_TAGS) { $env:PUSH_TAGS } else { "true" }

if ((git status --porcelain) -ne $null) {
    Write-Error "Working tree is not clean."
    exit 1
}

function Ensure-Remote {
    param(
        [string]$Name,
        [string]$Url
    )

    $existing = git remote get-url $Name 2>$null
    if ($LASTEXITCODE -ne 0) {
        git remote add $Name $Url
    }
    elseif ($existing -ne $Url) {
        git remote set-url $Name $Url
    }
}

$repoName = Split-Path -Leaf (git rev-parse --show-toplevel)
Ensure-Remote "personal" "git@github.com:oaslananka/${repoName}.git"
Ensure-Remote "org" "git@github.com:oaslananka-lab/${repoName}.git"

git push personal $Branch
git push org $Branch
if ($pushTags -eq "true") {
    git push personal --tags
    git push org --tags
}

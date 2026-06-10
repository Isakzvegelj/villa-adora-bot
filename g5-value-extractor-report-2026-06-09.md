# G5 Value Extractor Report - 2026-06-09 18:10 CET

## G5 Current State
- **Uptime**: 2 days, 3:07 | **Load**: 0.14 (idle)
- **RAM**: 5.0GB used / 16GB total (9.7GB available)
- **Swap**: 1.5GB / 2.0GB used (still high, persistent issue)
- **GPU**: GTX 1060 Max-Q 6GB, 55°C, 7W idle, 4.2GB VRAM used (1.9GB free)
  - Xorg: 133MB | Xorg (desktop): 1677MB | Cinnamon: 27MB | Firefox: 13MB | LLM server: 2292MB
- **Disk**: 184GB / 468GB used (42%), 261GB free
- **Trash**: 9.9GB (still in ~/trash, not permanently deleted!)
- **HF Cache**: 18GB (grew from 11GB last run!)
- **Ollama models**: 4.7GB on disk (service dead)

## Running Services (10 containers!)
| Service | Port | Status | Notes |
|---------|------|--------|-------|
| jellyfin | 127.0.0.1:8096 | Healthy | 17h uptime |
| syncthing | 0.0.0.0:8384 | Healthy | No auth! |
| n8n | 127.0.0.1:5678 | Running | 22h |
| vaultwarden | 127.0.0.1:8083 | Healthy | 22h |
| adguard_home | 0.0.0.0:8082 | Running | Needs initial setup |
| stirling-pdf | 0.0.0.0:8081 | Healthy | 29h |
| uptime-kuma | 127.0.0.1:3001 | Healthy | 31h |
| **gitea** | 127.0.0.1:3002 | **NEW - Running** | v1.26.2, port 3000->3002 |
| **woodpecker-server** | 127.0.0.1:8000 | **BROKEN - Restart loop** | 140 restarts! |

## What I Found / Fixed / Tested

### 🔴 CRITICAL: Woodpecker CI Restart Loop
- **Problem**: `woodpeckerci/woodpecker-server:latest` tag was removed upstream (intentional). Container enters infinite restart loop (140+ restarts).
- **Fix available**: Image `woodpeckerci/woodpecker-server:v3` is ALREADY pulled on disk. Just needs container recreated with correct tag.
- **Status**: Could not stop/rm container in cron (approval needed). **Needs manual fix**:
  ```
  ssh isak@192.168.54.148
  docker stop woodpecker-server && docker rm woodpecker-server
  docker run -d --name woodpecker-server --network ci-network \
    -p 127.0.0.1:8000:8000 \
    -v /home/isak/woodpecker-data:/var/lib/woodpecker \
    -e WOODPECKER_HOST=http://gitea-ci.local:8000 \
    -e WOODPECKER_OPEN=true \
    -e WOODPECKER_AGENT_SECRET=<existing-secret> \
    woodpeckerci/woodpecker-server:v3
  ```

### 🟢 NEW: Gitea Running
- Gitea v1.26.2 installed via Docker (port 3000 mapped to host 3002)
- Needs initial web setup (admin account, etc.)
- ROOT_URL is empty in config - needs to be set to `http://192.168.54.148:3002/`
- This completes the CI/CD stack once Woodpecker is fixed
- Value: **EUR10-25/mo** (replaces GitHub private repo + Actions minutes)

### All Existing Services Healthy
- LLM Server: Running (TinyLlama-1.1B, 24-30 tok/s)
- Jellyfin: Healthy
- n8n: Running
- Vaultwarden: Healthy
- Syncthing: Running
- AdGuard Home: Running (needs setup)
- Stirling PDF: Healthy
- Uptime Kuma: Healthy

## Updated Task Queue

### Active/Running Tasks
| ID | Task | Value | Status |
|----|------|-------|--------|
| T1 | LLM API Server (dual-model) | EUR10-20/mo | ✅ Running |
| T14 | Dual-Model Server | — | ✅ Running |
| T24 | Jellyfin Media Server | EUR5-15/mo | ✅ Running |
| T13 | Uptime Kuma | EUR5-10/mo | ✅ Running |
| T7 | AdGuard Home | EUR5-10/mo | ✅ Running (needs setup) |
| T17 | Stirling-PDF | EUR5-15/mo | ✅ Running |
| T18 | Vaultwarden | EUR3-10/mo | ✅ Running |
| T19 | n8n | EUR10-20/mo | ✅ Running |
| T22 | Syncthing | EUR5-10/mo | ✅ Running (no auth!) |
| **T32** | **Gitea** | **EUR10-25/mo** | **✅ NEW - Running** |
| **T33** | **Woodpecker CI** | **—** | **🔴 Broken (restart loop)** |

### New Tasks This Run
| ID | Task | Est. Value | Complexity | Notes |
|----|------|-----------|------------|-------|
| T32 | Gitea self-hosted | EUR10-25/mo | — | INSTALLED (new since last run) |
| T33 | Fix Woodpecker CI image tag | — | LOW | Needed: stop/pull v3/start |
| T34 | Gitea initial setup | — | LOW | Needs admin account, ROOT_URL |
| T35 | Clean ~/trash (9.9GB) | Free disk | LOW | Safe to rm -rf |
| T36 | Clean Ollama models (4.7GB) | Free disk | LOW | Service dead, remove |
| T37 | Clean HF cache (18GB→12GB) | Free disk | LOW | Remove old/unused models |
| T38 | AdGuard Home setup | EUR5-10/mo | MEDIUM | Needs user interaction |
| T39 | Syncthing auth setup | Fix security | LOW | Set admin password |
| T40 | Woodpecker+Gitea integration | Full CI/CD | MEDIUM | Connect agent, add runner |

### Skipped Tasks (tested, not viable)
| ID | Task | Reason |
|----|------|--------|
| T2 | Phi-2 | Too slow (1.8 tok/s) |
| T8 | XMR mining | EUR2-4 < power cost EUR8-12 |
| T9 | Petals | Too complex |
| T10 | GPU rental | GTX 1060 too old |
| T15 | Ollama reinstall | Custom server superior |
| T16 | Render Network | Below minimum spec |
| T21 | Gemma-2B | Gated repo, HF token needed |

## Disk Space Recovery Opportunities
| Location | Size | Action |
|----------|------|--------|
| ~/trash/ | 9.9GB | rm -rf (old HF caches, already confirmed safe) |
| ~/.ollama/models/ | 4.7GB | Remove (Ollama dead, models unused) |
| ~/.cache/huggingface/ | 18GB | Audit & clean (grew from 11GB! may have duplicates) |
| **Total recoverable** | **~32.6GB** | Would go from 42% to 27% disk usage |

## Cumulative Value Update
| Service | Monthly Value | Status |
|---------|--------------|--------|
| LLM API Server | EUR10-20 | ✅ |
| Gitea (NEW) | EUR10-25 | ✅ |
| Jellyfin | EUR5-15 | ✅ |
| n8n | EUR10-20 | ✅ |
| Stirling-PDF | EUR5-15 | ✅ |
| AdGuard Home | EUR5-10 | ✅ |
| Uptime Kuma | EUR5-10 | ✅ |
| Vaultwarden | EUR3-10 | ✅ |
| Syncthing | EUR5-10 | ✅ |
| Woodpecker CI | potential | 🔴 broken |
| **Total** | **EUR58-135/mo** | |
| Power cost | -EUR16-18/mo | |
| **Net value** | **EUR42-117/mo** | |

## Priority Next Steps
1. **Fix Woodpecker CI** (stop, pull v3 tag, restart) - loses 1 container in restart loop
2. **Set up Gitea** admin + complete install (ROOT_URL = http://192.168.54.148:3002/)
3. **Clean disk**: trash + ollama models + audit HF cache = recover ~32GB
4. **Set Syncthing auth** (security risk - no password on LAN)
5. **Fix AdGuard Home** initial setup (DNS redirect issues)
6. **Connect Woodpecker agent** to Gitea for full self-hosted CI/CD

## Recommendations for Isak
- The Gitea+Woodpecker combo is a great find - completes a self-hosted CI/CD stack
- Should empty trash and remove Ollama models to free 14.6GB with zero risk
- HF cache grew by 7GB despite cleanup - may be worth auditing for duplicates
- Once Woodpecker is fixed and agent connected, this becomes a full CI/CD platform worth EUR15-25/mo

# Google Ads MCP (okotaku fork)

Fork of [googleads/google-ads-mcp](https://github.com/googleads/google-ads-mcp) with write (mutate) tools added.

## Branch Strategy

```
upstream (googleads/google-ads-mcp)
  │
  ▼
main              ← mirrors upstream, no custom code
  │
  ▼
feat/write-tools  ← custom write tools (long-lived branch)
```

- **`main`**: Always tracks `upstream/main`. No custom commits. Updated automatically by GitHub Actions.
- **`feat/write-tools`**: Contains custom write tools (`ads_mcp/tools/mutate.py`). Merges `main` automatically when upstream updates. Used by `blue1-app/.mcp.json`.

## Upstream Sync (Automated)

GitHub Actions runs daily (and on manual trigger):

1. Fetches `upstream/main` → merges into `main`
2. Merges `main` → `feat/write-tools`
3. If merge conflict occurs, creates a PR for manual resolution

## Custom Write Tools

Located in `ads_mcp/tools/mutate.py`. 10 tools:

**Status (3):** `update_campaign_status`, `update_ad_group_status`, `update_ad_status`
**Budget/Bidding (2):** `update_campaign_budget`, `update_bidding_strategy`
**Keywords (2):** `add_keywords`, `add_negative_keywords`
**Creation (3):** `create_campaign`, `create_ad_group`, `update_ad_group_bid`

Safety:
- New campaigns/ad groups are created in PAUSED state
- Budget/bid tools are gated by `settings.json` ask permissions in Claude Code (blue1-app)

## Usage in blue1-app

```json
{
  "google-ads": {
    "command": "uvx",
    "args": [
      "--from",
      "git+https://github.com/okotaku/google-ads-mcp.git@feat/write-tools",
      "google-ads-mcp"
    ]
  }
}
```

## Adding New Write Tools

1. Edit `ads_mcp/tools/mutate.py` on `feat/write-tools` branch
2. Use `utils.get_googleads_service()` for API calls (includes MCPHeaderInterceptor)
3. Use explicit `field_mask_pb2.FieldMask(paths=[...])` for update operations
4. Catch `GoogleAdsException` and return formatted error strings
5. Add budget/bid tools to `blue1-app/.claude/settings.json` ask list

## Manual Upstream Sync

If needed manually:

```bash
git fetch upstream
git checkout main
git merge upstream/main
git push origin main
git checkout feat/write-tools
git merge main
git push origin feat/write-tools
```

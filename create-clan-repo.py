#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import urllib.request
import re
import shutil
import tempfile
import time
import webbrowser
from pathlib import Path
from datetime import datetime, timezone, timedelta

REPOS_BASE = Path.home() / "Desktop" / "Clan Reps"
PARENT_DIR = REPOS_BASE
SCRIPT_DIR = Path(__file__).parent
TEMPLATES_DIR = SCRIPT_DIR / "templates"
API_BASE = "https://playninjarift.com/api"
SEASON_API = "https://playninjarift.com/api/refresh_time_website.php"
RANKING_API = "https://playninjarift.com/api/clan_ranking_website.php"

GITHUB_USER = None
DRY_RUN = False
TARGET_TZ = timezone(timedelta(hours=8))
SERVER_TZ = timezone(timedelta(hours=-5))


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def dry_prefix():
    return "[DRY-RUN] " if DRY_RUN else ""


def gh(*args, capture=True, check=True, input_data=None):
    cmd = ["gh"] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=capture, text=True, check=check,
                          input=input_data)
        out = r.stdout.strip() if capture else None
        if out:
            return out
        return r.stderr.strip() if capture else None
    except subprocess.CalledProcessError as e:
        if capture:
            return e.stdout.strip() if e.stdout else e.stderr.strip() if e.stderr else ""
        raise
    except FileNotFoundError:
        eprint("Error: `gh` CLI not found. Install from https://cli.github.com/")
        sys.exit(1)


def detect_github_user():
    global GITHUB_USER
    try:
        GITHUB_USER = gh("api", "user", "--jq", ".login")
        return GITHUB_USER
    except Exception:
        return None


def prompt(question, default=None, validate=None):
    while True:
        suffix = f" [{default}]" if default else ""
        raw = input(f"  {question}{suffix}: ").strip()
        if not raw and default:
            raw = default
        if not raw:
            print("  This field is required.")
            continue
        if validate and not validate(raw):
            continue
        return raw


def prompt_yn(question, default="Y"):
    suffix = f" [{default}]" if default else ""
    raw = input(f"  {question}{suffix}: ").strip().lower()
    if not raw:
        raw = default.lower()
    return raw.startswith("y")


def prompt_file(question, default=None):
    suffix = f" [{default}]" if default else ""
    raw = input(f"  {question}{suffix}: ").strip()
    if not raw:
        if default:
            return default
        return None
    if raw in ("-", "clear", "none"):
        return None
    raw = raw.strip('"').strip("'")
    p = Path(raw)
    if not p.exists():
        print(f"  File not found: {raw}")
        return None
    return p


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "clan-repo-creator/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def fetch_clan_info(clan_id):
    url = f"{API_BASE}/detail_clan_website.php?clan_id={clan_id}"
    try:
        data = fetch_json(url)
        return {
            "name": data.get("clan_name", "Unknown"),
            "members": len(data.get("members", [])),
            "id": clan_id,
            "raw": data,
        }
    except Exception:
        return None


def fetch_season_info():
    try:
        return fetch_json(SEASON_API)
    except Exception:
        return None


def fetch_ranking(clan_id):
    try:
        data = fetch_json(RANKING_API)
        for entry in data:
            if entry["clan_id"] == clan_id:
                return entry
    except Exception:
        pass
    return {}


def slugify(text):
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text


def read_template(name):
    path = TEMPLATES_DIR / name
    if not path.exists():
        eprint(f"Error: template {name} not found at {path}")
        sys.exit(1)
    return path.read_text(encoding="utf-8")


def create_repo(name, visibility, description):
    pfx = dry_prefix()
    print(f"\n  {pfx}Creating repo {GITHUB_USER}/{name}...")
    if DRY_RUN:
        print(f"  {pfx}Would run: gh repo create {GITHUB_USER}/{name} --{visibility}")
        return True
    result = gh("repo", "create", f"{GITHUB_USER}/{name}",
                f"--{visibility}",
                "--description", description,
                capture=True, check=False)
    if "already exists" in result.lower():
        print(f"  Repo already exists. Delete it first or choose a different name.")
        return False
    if not result:
        print(f"  Created.")
        return True
    print(f"  {result}")
    return True


def clone_repo(name):
    pfx = dry_prefix()
    print(f"  {pfx}Cloning {GITHUB_USER}/{name}...")
    target = PARENT_DIR / name
    if DRY_RUN:
        print(f"  {pfx}Would clone to {target}")
        return target
    if target.exists():
        print(f"  Directory {target} already exists. Removing...")
        shutil.rmtree(target)
    gh("repo", "clone", f"{GITHUB_USER}/{name}", str(target), capture=False)
    return target


def write_file(path, content):
    pfx = dry_prefix()
    if DRY_RUN:
        print(f"  {pfx}Would write {path.name} to {path.parent}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def copy_file(src, dst):
    pfx = dry_prefix()
    if DRY_RUN:
        print(f"  {pfx}Would copy {src.name} -> {dst}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    size = src.stat().st_size
    print(f"  Copied {src.name} ({size//1024} KB)")


def write_templated_file(dst_path, template_name, subs):
    content = read_template(template_name)
    for key, val in subs.items():
        content = content.replace("{{" + key + "}}", str(val))
    write_file(dst_path, content)


def enable_pages(name):
    pfx = dry_prefix()
    print(f"  {pfx}Enabling GitHub Pages...")
    if DRY_RUN:
        print(f"  {pfx}Would POST repos/{GITHUB_USER}/{name}/pages")
        return
    print(f"  {pfx}Waiting for repo to settle...")
    time.sleep(5)
    body = json.dumps({"source": {"branch": "main", "path": "/"}})
    try:
        result = gh("api", f"repos/{GITHUB_USER}/{name}/pages",
                    "-X", "POST", "--input", "-",
                    input_data=body, capture=True, check=False)
        if result and "already" in result.lower():
            gh("api", f"repos/{GITHUB_USER}/{name}/pages",
               "-X", "PUT", "--input", "-",
               input_data=body, capture=False)
        print(f"  Pages enabled.")
    except Exception as e:
        print(f"  Warning: couldn't enable Pages automatically ({e})")
        print(f"  Enable manually: Settings -> Pages -> Deploy from main / (root)")


def trigger_workflow(name):
    pfx = dry_prefix()
    print(f"  {pfx}Waiting for GitHub to register workflow...")
    time.sleep(10)
    print(f"  {pfx}Triggering first workflow run...")
    if DRY_RUN:
        print(f"  {pfx}Would run: gh workflow run clan-snapshot.yml --ref main")
        return
    for attempt in range(3):
        try:
            gh("workflow", "run", "clan-snapshot.yml", "--ref", "main",
               "--repo", f"{GITHUB_USER}/{name}", capture=False)
            print(f"  Workflow triggered.")
            return
        except Exception as e:
            if attempt < 2:
                print(f"  Retrying ({attempt+1}/3)...")
                time.sleep(5)
            else:
                print(f"  Warning: couldn't trigger workflow ({e})")
                print(f"  Trigger manually: Actions -> Clan Snapshot -> Run workflow")


def check_gh_cli():
    try:
        subprocess.run(["gh", "--version"], capture_output=True, check=True)
        return True
    except FileNotFoundError:
        print("  Installing GitHub CLI via winget...")
        r = subprocess.run(["winget", "install", "--id", "GitHub.cli", "--accept-source-agreement"])
        if r.returncode != 0:
            print("  Installation failed. Download from https://cli.github.com/")
            sys.exit(1)
        print("  GitHub CLI installed.")
        return True


def check_gh_auth():
    global GITHUB_USER
    r = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if r.returncode == 0:
        GITHUB_USER = detect_github_user()
        return True
    print("  Opening browser to log in to GitHub...")
    subprocess.run(["gh", "auth", "login", "--web"])
    r2 = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if r2.returncode == 0:
        GITHUB_USER = detect_github_user()
        return True
    print("  Login failed. Run `gh auth login --web` manually.")
    sys.exit(1)


def print_header():
    pfx = dry_prefix()
    print()
    print(f"  {pfx}NinjaRift Clan Repo Creator")
    print(f"  " + "-" * 40)
    if DRY_RUN:
        print(f"  Running in DRY-RUN mode — no changes will be made.")
        print()
    print()


def print_summary(name, clan_info):
    site = f"https://{GITHUB_USER}.github.io/{name}/"
    repo = f"https://github.com/{GITHUB_USER}/{name}"
    local = str(PARENT_DIR / name)
    print()
    print("  Repo: ", repo)
    print("  Site: ", site)
    print("  Local:", local)
    print()
    print("  First snapshot will appear within ~30 min.")
    print("  Trigger manually: Actions -> Clan Snapshot -> Run workflow")
    print()


def compute_season_preview(end_str, now):
    if not end_str:
        return None
    try:
        end_dt = datetime.strptime(end_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=SERVER_TZ).astimezone(timezone.utc)
    except Exception:
        return None
    now_utc = now.astimezone(timezone.utc)
    if now_utc >= end_dt:
        return {"days_left": 0, "ended": True}
    diff = end_dt - now_utc
    return {"days_left": max(0, diff.days), "ended": False}


GOAL_TIERS = [
    (100000, "5 Stamina Rolls"),
    (500000, "20 Stamina Rolls"),
    (750000, "Back Item"),
    (1000000, "Weapon"),
    (1600000, "Jutsu"),
]


def compute_goal_preview(clan_reputation):
    next_tier = None
    progress = 100.0
    for threshold, label in GOAL_TIERS:
        if clan_reputation < threshold:
            next_tier = (threshold, label)
            progress = (clan_reputation / threshold) * 100
            break
    return {"next_tier": next_tier, "progress": min(progress, 100), "total": clan_reputation}


def generate_preview(clan_id, display_name, logo_path, favicon_path, accent_color="#999999", accent_light="#ff6b8a"):
    now = datetime.now(TARGET_TZ)
    ts_str = now.strftime("%Y-%m-%d %H:%M:%S")

    print(f"  [{ts_str}] Fetching live data for preview...")
    clan_data = fetch_json(f"{API_BASE}/detail_clan_website.php?clan_id={clan_id}")
    members = clan_data.get("members", [])
    member_count = len(members)
    clan_name = clan_data.get("clan_name", display_name)

    season_info = fetch_season_info()
    ranking = fetch_ranking(clan_id)
    clan_reputation = ranking.get("clan_reputation", 0) or sum(m["member_reputation"] for m in members)
    today_gain = ranking.get("clan_day_points", 0)

    now_dt = datetime.now(TARGET_TZ)
    season_str = ""
    season_end_str = ""
    days_left = None
    if season_info:
        season_str = season_info.get("season", "")
        season_end_str = season_info.get("season_end", "")
        preview = compute_season_preview(season_end_str, now_dt)
        if preview and not preview["ended"]:
            days_left = preview["days_left"]
        elif preview and preview["ended"]:
            days_left = 0

    season_display = f"Season {season_str}" if season_str else ""
    if days_left is not None:
        season_display += f" ({days_left}d left)" if days_left else " (ending)"

    goal = compute_goal_preview(clan_reputation)
    goal_pct = f"{goal['progress']:.1f}%"
    goal_next = f"{goal['next_tier'][1]} ({goal['next_tier'][0]:,})" if goal['next_tier'] else "Max tier reached!"
    goal_num = f"{clan_reputation:,} / {goal['next_tier'][0]:,}" if goal['next_tier'] else f"{clan_reputation:,} / Max"

    # Logo HTML
    logo_html = ""
    if logo_path:
        import base64
        b64 = base64.b64encode(logo_path.read_bytes()).decode()
        ext = logo_path.suffix.lower().lstrip(".")
        if ext == "jpg":
            ext = "jpeg"
        logo_html = f'<img class="logo" src="data:image/{ext};base64,{b64}" alt="Logo">'
    else:
        logo_html = '<div class="logo-placeholder">' + clan_name[:2].upper() + "</div>"

    # Favicon HTML
    favicon_html = ""
    if favicon_path:
        import base64
        b64 = base64.b64encode(favicon_path.read_bytes()).decode()
        ext = favicon_path.suffix.lower().lstrip(".")
        favicon_html = f'<link rel="icon" type="image/{ext}" href="data:image/{ext};base64,{b64}">'

    # Member table rows
    sorted_members = sorted(members, key=lambda m: m["member_reputation"], reverse=True)
    table_rows = ""
    for i, m in enumerate(sorted_members):
        rank = i + 1
        name = m["character_name"]
        reps = f"{m['member_reputation']:,}"
        table_rows += f"<tr><td>{rank}</td><td>{name}</td><td class=\"num\">{reps}</td><td class=\"num na\">-</td><td class=\"num na\">-</td><td class=\"num na\">-</td></tr>\n"

    stats_html = f"""
  <div class="stats-bar">
    <div class="stats-row">
      <div class="stats-col"><span class="stat-label">Today's Gain</span><span class="stat-val" id="today-gain">{today_gain:+,}</span></div>
      <div class="stats-col"><span class="stat-label">Season Total</span><span class="stat-val">{clan_reputation:,}</span></div>
      <div class="stats-col"><span class="stat-label">Members</span><span class="stat-val">{member_count}</span></div>
    </div>
    <div class="stats-row">
      <div class="stats-col"><span class="stat-label">Season</span><span class="stat-val" style="color:#eab308;font-size:14px;">{season_display}</span></div>
    </div>
  </div>"""

    goal_html = f"""
  <div class="goal-bar">
    <div class="goal-info">
      <span class="goal-num">{goal_num}</span>
      <span class="goal-next">{goal_next}</span>
    </div>
    <div class="goal-track"><div class="goal-fill" style="width:{goal_pct};"></div></div>
  </div>"""

    preview_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
{favicon_html}
<title>{display_name} [Preview]</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; background: #080810; color: #e0e0e0; min-height: 100vh; display: flex; justify-content: center; padding: 32px 16px; }}
  .container {{ max-width: 960px; width: 100%; box-shadow: 0 0 40px rgba(233, 69, 96, 0.06), 0 8px 32px rgba(0,0,0,0.5); border-radius: 16px; overflow: hidden; }}
  .header {{ text-align: center; padding: 32px 24px 24px; background: linear-gradient(135deg, #0f0f1e 0%, #1a1a30 50%, #0d1b2a 100%); position: relative; overflow: hidden; }}
  .header::before {{ content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px; background: linear-gradient(90deg, #e94560, #ff6b8a, #e94560); background-size: 200% 100%; animation: shimmer 3s ease-in-out infinite; }}
  @keyframes shimmer {{ 0%,100% {{ background-position: 0% 50%; }} 50% {{ background-position: 100% 50%; }} }}
  .logo {{ width: 132px; height: 132px; object-fit: contain; margin-bottom: 16px; filter: drop-shadow(0 0 16px rgba(233, 69, 96, 0.3)); }}
  .logo-placeholder {{ width: 132px; height: 132px; margin: 0 auto 16px; border-radius: 50%; background: linear-gradient(135deg, #e94560, #ff6b8a); display: flex; align-items: center; justify-content: center; font-size: 48px; font-weight: 700; color: #fff; text-shadow: 0 2px 8px rgba(0,0,0,0.4); }}
  .header h1 {{ font-size: 30px; font-weight: 700; color: #fff; letter-spacing: 0.5px; margin-bottom: 4px; }}
  .header .sub {{ font-size: 17px; color: #888; display: flex; justify-content: center; gap: 16px; flex-wrap: wrap; }}
  .header .sub span {{ color: #aaa; }}
  .table-wrap {{ overflow-x: auto; }}
  table {{ width: 100%; min-width: 0; border-collapse: collapse; background: #0c0c14; }}
  th {{ background: #0f0f1e; padding: 14px 18px; text-align: center; font-size: 15px; text-transform: uppercase; letter-spacing: 1px; color: #e94560; font-weight: 600; }}
  td {{ padding: 11px 18px; border-bottom: 1px solid #14141f; font-size: 14px; color: #ccc; text-align: center; }}
  tr:nth-child(even) td {{ background: rgba(255,255,255,0.015); }}
  tr:hover td {{ background: rgba(233, 69, 96, 0.04); }}
  td.num {{ font-variant-numeric: tabular-nums; }}
  td:first-child, th:first-child {{ width: 28px; min-width: 28px; text-align: center; color: #666; font-size: 12px; }}
  .stats-bar {{ display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 14px 20px; background: #0f142373; backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px); border-top: 1px solid #1a1a2e; }}
  .stats-row {{ display: flex; justify-content: center; gap: 48px; width: 100%; }}
  .stats-col {{ display: flex; flex-direction: column; align-items: center; gap: 2px; }}
  .stat-label {{ color: #888; font-size: 12px; text-transform: uppercase; letter-spacing: 0.3px; }}
  .stat-val {{ color: #e0e0e0; font-size: 18px; font-weight: 700; font-variant-numeric: tabular-nums; }}
  #today-gain {{ color: #4caf50; }}
  .goal-bar {{ display: flex; flex-direction: column; gap: 4px; padding: 14px 20px; background: #0c0c18; border-top: 1px solid #1a1a2e; }}
  .goal-track {{ width: 100%; height: 16px; background: #14141f; border-radius: 8px; overflow: hidden; }}
  .goal-fill {{ height: 100%; background: linear-gradient(90deg, #e94560, #ff6b8a); border-radius: 8px; transition: width 0.5s ease; }}
  .goal-info {{ display: flex; justify-content: space-between; font-size: 12px; color: #888; }}
  .goal-info .goal-next {{ color: #e94560; font-weight: 600; }}
  .goal-info .goal-num {{ color: #ccc; font-variant-numeric: tabular-nums; }}
  .preview-banner {{ background: #e94560; color: #fff; text-align: center; padding: 10px 20px; font-size: 13px; font-weight: 600; }}
  .footer {{ text-align: center; padding: 18px 20px; background: #08080f; color: #444; font-size: 12px; border-top: 1px solid #12121e; }}
  .footer a {{ color: #e94560; text-decoration: none; }}
</style>
</head>
<body>
<div class="container">
  <div class="preview-banner">LIVE PREVIEW &middot; Fetched {ts_str}</div>
  <div class="header">
    {logo_html}
    <h1>{display_name}</h1>
    <div class="sub">
      <span>Clan ID: {clan_id}</span>
      <span>&middot;</span>
      <span>{member_count} members</span>
    </div>
  </div>
  {stats_html}
  {goal_html}
  <div class="table-wrap">
  <table>
    <thead><tr><th>#</th><th>Name</th><th>Total Reps</th><th>1/2 Hour</th><th>Hourly</th><th>Daily</th></tr></thead>
    <tbody>{table_rows}</tbody>
  </table>
  </div>
  <div class="footer">
    Preview generated from live API data.<br>
    Once deployed, the site auto-updates every 30 minutes.
  </div>
</div>
</body>
</html>"""

    accent_r, accent_g, accent_b = int(accent_color[1:3], 16), int(accent_color[3:5], 16), int(accent_color[5:7], 16)
    preview_html = (preview_html
        .replace("#e94560", accent_color)
        .replace("#ff6b8a", accent_light)
        .replace("rgba(233, 69, 96,", f"rgba({accent_r}, {accent_g}, {accent_b},")
        .replace("rgba(233,69,96,", f"rgba({accent_r},{accent_g},{accent_b},")
    )
    tmp = tempfile.mkdtemp(prefix="nr-preview-")
    preview_path = Path(tmp) / "preview.html"
    preview_path.write_text(preview_html, encoding="utf-8")
    return preview_path, tmp


def do_dry_run_preview(clan_id, display_name, logo_path, favicon_path, accent_color="#999999", accent_light="#ff6b8a"):
    print(f"\n  {dry_prefix()}Generating live preview...")
    preview_path, tmp_dir = generate_preview(clan_id, display_name, logo_path, favicon_path, accent_color, accent_light)
    print(f"  Preview saved to: {preview_path}")
    print()
    if prompt_yn("Open preview in browser", default="Y"):
        webbrowser.open(f"file://{preview_path}")
    print()
    print("  Review the preview above. When you're ready:")
    keep = prompt_yn("  Keep preview (for comparison after real deploy)", default="N")
    if keep:
        dest = PARENT_DIR / f"preview-{slugify(display_name)}.html"
        PARENT_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(preview_path, dest)
        print(f"  Saved preview to: {dest}")
    else:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        print(f"  Preview cleaned up.")
    print()


def input_clan(state):
    print("\n  1. Clan Information")
    clan_info = state.get("clan_info")
    while True:
        raw = prompt("Clan ID (e.g. 2527)", default=str(state["clan_id"]) if state["clan_id"] else None)
        try:
            clan_id = int(raw)
            clan_info = fetch_clan_info(clan_id)
            if clan_info:
                print(f"     Found: {clan_info['name']} ({clan_info['members']} members)")
                state["clan_id"] = clan_id
                state["clan_info"] = clan_info
                return
            else:
                print(f"     Clan {clan_id} not found. Check the ID and try again.")
        except ValueError:
            print("     Enter a numeric clan ID.")


def input_repo(state):
    print("\n  2. Repository")
    clan_info = state["clan_info"]
    if state["repo_name"]:
        repo_name = prompt("Repo name", default=state["repo_name"],
                           validate=lambda v: re.match(r'^[a-zA-Z0-9_.-]+$', v) is not None)
    else:
        parts = re.split(r'[^a-zA-Z0-9]+', clan_info["name"])
        default_repo = ''.join(p[:1].upper() + p[1:] for p in parts if p) + "-Reps"
        repo_name = prompt("Repo name", default=default_repo,
                           validate=lambda v: re.match(r'^[a-zA-Z0-9_.-]+$', v) is not None)
    display_name = prompt("Display name (for HTML title)", default=state["display_name"] or clan_info["name"])
    visibility = "private"
    if prompt_yn("Public repo", default="Y" if state.get("visibility") == "public" else "N"):
        visibility = "public"
    if not state["dry_run"]:
        state["dry_run"] = prompt_yn("Dry-run mode (preview only, no changes)", default="N")
    state["repo_name"] = repo_name
    state["display_name"] = display_name
    state["visibility"] = visibility


def input_media(state):
    print("\n  3. Media (optional)")
    while True:
        p = prompt_file("Logo image (drag file here or Enter to skip)", default=state.get("logo_path"))
        if p is None:
            state["logo_path"] = None
            break
        ext = p.suffix.lower()
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            state["logo_path"] = p
            break
        print(f"  Unsupported format '{ext}'. Use PNG, JPG, GIF, or WebP.")
    while True:
        p = prompt_file("Favicon icon (drag file here or Enter to skip)", default=state.get("favicon_path"))
        if p is None:
            state["favicon_path"] = None
            break
        ext = p.suffix.lower()
        if ext in (".ico", ".png"):
            state["favicon_path"] = p
            break
        print(f"  Unsupported format '{ext}'. Use ICO or PNG.")


def input_colors(state):
    print("\n  4. Color Theme")
    accent_color = state.get("accent_color", "#999999")
    accent_light = state.get("accent_light", "#ff6b8a")
    logo_path = state.get("logo_path")
    theme_choice = None
    while theme_choice is None:
        raw = input("     Choose colors:\n"
                    "       1) Default (gray + light pink)\n"
                    + ("       2) From logo\n" if logo_path else "       2) From logo  [disabled — no logo selected]\n")
                    + "       3) Custom hex\n"
                    "     Choice [1]: ").strip()
        if not raw:
            raw = "1"
        if raw == "1":
            accent_color = "#999999"
            accent_light = "#ff6b8a"
            theme_choice = raw
        elif raw == "2":
            if not logo_path:
                print("     No logo selected. Choose option 1 or 3.")
                continue
            try:
                from colorthief import ColorThief
            except ImportError:
                print("     Installing colorthief...")
                subprocess.run([sys.executable, "-m", "pip", "install", "colorthief"])
                from colorthief import ColorThief
            ct = ColorThief(str(logo_path))
            pal = ct.get_palette(color_count=2, quality=10)
            accent_color = "#{:02X}{:02X}{:02X}".format(*pal[0])
            accent_light = "#{:02X}{:02X}{:02X}".format(*pal[1])
            print(f"     Extracted: accent={accent_color}, light={accent_light}")
            theme_choice = raw
        elif raw == "3":
            while True:
                ac = input(f"     Accent color (hex, e.g. {accent_color}): ").strip()
                if not ac:
                    ac = accent_color
                if re.match(r"^#[0-9A-Fa-f]{6}$", ac):
                    accent_color = ac.upper()
                    break
                print("     Invalid hex. Use format #RRGGBB.")
            while True:
                al = input(f"     Light accent color (hex, e.g. {accent_light}): ").strip()
                if not al:
                    al = accent_light
                if re.match(r"^#[0-9A-Fa-f]{6}$", al):
                    accent_light = al.upper()
                    break
                print("     Invalid hex. Use format #RRGGBB.")
            theme_choice = raw
        else:
            print("     Enter 1, 2, or 3.")
    state["accent_color"] = accent_color
    state["accent_light"] = accent_light


def input_beta(state):
    print("\n  5. Action Channel")
    use_beta = prompt_yn("  Use beta action (receives updates immediately)",
                         default="Y" if state.get("action_ref") == "@beta" else "N")
    state["action_ref"] = "@beta" if use_beta else "@v1"


def show_summary(state):
    pfx = dry_prefix()
    print()
    print(f"  {pfx}Confirm")
    print(f"    1) Clan ID:        {state['clan_id']} ({state['clan_info']['name']} \u00b7 {state['clan_info']['members']} members)")
    print(f"    2) Repository:     {state['repo_name']} ({state['visibility']})")
    print(f"    3) Display name:   {state['display_name']}")
    logo = state.get("logo_path")
    print(f"    4) Logo:           {logo.name + ' (' + str(logo.stat().st_size // 1024) + ' KB)' if logo else '(none)'}")
    fav = state.get("favicon_path")
    print(f"    5) Favicon:        {fav.name + ' (' + str(fav.stat().st_size // 1024) + ' KB)' if fav else '(none)'}")
    print(f"    6) Accent:         {state['accent_color']}")
    print(f"    7) Accent light:   {state['accent_light']}")
    print(f"    8) Action ref:     {state['action_ref']}")
    print(f"    9) Dry-run:        {'Yes' if state['dry_run'] else 'No'}")
    print(f"    0) Start over")
    print()


def confirm_loop(state):
    while True:
        show_summary(state)
        choice = input("  Enter # to edit, Y to proceed, N to cancel: ").strip().lower()
        if choice in ("y", "yes"):
            return True
        if choice in ("n", "no"):
            return False
        if choice == "1":
            input_clan(state)
        elif choice == "2":
            input_repo(state)
        elif choice == "3":
            input_media(state)
        elif choice in ("4", "6", "7"):
            input_colors(state)
        elif choice == "5":
            input_beta(state)
        elif choice == "8":
            input_beta(state)
        elif choice == "9":
            state["dry_run"] = not state["dry_run"]
        elif choice == "0":
            state["clan_id"] = None
            state["clan_info"] = None
            state["repo_name"] = None
            state["display_name"] = None
            state["visibility"] = "public"
            state["logo_path"] = None
            state["favicon_path"] = None
            state["accent_color"] = "#999999"
            state["accent_light"] = "#ff6b8a"
            state["action_ref"] = "@v1"
            input_clan(state)
            input_repo(state)
            input_media(state)
            input_colors(state)
            input_beta(state)
        else:
            print("  Invalid choice.")


def main():
    global GITHUB_USER, DRY_RUN, PARENT_DIR

    DRY_RUN = "--dry-run" in sys.argv

    print_header()
    check_gh_cli()
    check_gh_auth()
    if not GITHUB_USER:
        print("  Could not detect GitHub username.")
        sys.exit(1)

    PARENT_DIR = REPOS_BASE / GITHUB_USER

    state = {
        "clan_id": None,
        "clan_info": None,
        "repo_name": None,
        "display_name": None,
        "visibility": "public",
        "logo_path": None,
        "favicon_path": None,
        "accent_color": "#999999",
        "accent_light": "#ff6b8a",
        "action_ref": "@v1",
        "dry_run": DRY_RUN,
    }

    input_clan(state)
    input_repo(state)
    input_media(state)
    input_colors(state)
    input_beta(state)

    if not confirm_loop(state):
        print("  Cancelled.")
        sys.exit(0)

    DRY_RUN = state["dry_run"]
    clan_info = state["clan_info"]
    clan_id = state["clan_id"]
    repo_name = state["repo_name"]
    display_name = state["display_name"]
    visibility = state["visibility"]
    logo_path = state["logo_path"]
    favicon_path = state["favicon_path"]
    accent_color = state["accent_color"]
    accent_light = state["accent_light"]
    action_ref = state["action_ref"]
    create_desc = f"NinjaRift clan {clan_id} ({clan_info['name']}) reputation snapshots"

    # Execute
    pfx = dry_prefix()

    # Dry-run: generate live preview, then skip gh/git operations
    if DRY_RUN:
        do_dry_run_preview(clan_id, display_name, logo_path, favicon_path, accent_color, accent_light)
        print(f"  {pfx}Dry-run complete. No repos or files were created.")
        return

    PARENT_DIR.mkdir(parents=True, exist_ok=True)

    if not create_repo(repo_name, visibility, create_desc):
        sys.exit(1)

    repo_path = clone_repo(repo_name)

    if not DRY_RUN:
        os.chdir(repo_path)

    # Write files
    subs = {
        "CLAN_ID": clan_id,
        "CLAN_NAME": display_name,
        "GITHUB_USER": GITHUB_USER,
        "REPO_NAME": repo_name,
        "ACTION_REF": action_ref,
    }
    print(f"  {pfx}Writing .github/workflows/clan-snapshot.yml...")
    write_templated_file(
        repo_path / ".github" / "workflows" / "clan-snapshot.yml",
        "workflow.yml", subs,
    )
    print(f"  {pfx}Writing README.md...")
    write_templated_file(
        repo_path / "README.md",
        "README.md", subs,
    )
    print(f"  {pfx}Writing .gitignore...")
    write_templated_file(
        repo_path / ".gitignore",
        ".gitignore", subs,
    )

    # Write theme.json (locks accent colors against future action default changes)
    print(f"  {pfx}Writing theme.json...")
    theme_json = json.dumps({"accent_color": accent_color, "accent_light": accent_light}, indent=2)
    write_file(repo_path / "theme.json", theme_json)

    # Copy media files
    if logo_path:
        print(f"  {pfx}Copying logo...")
        copy_file(logo_path, repo_path / "clan_logo.png")
    if favicon_path:
        print(f"  {pfx}Copying favicon...")
        copy_file(favicon_path, repo_path / "favicon.ico")

    # Commit & push
    if not DRY_RUN:
        print(f"  Committing and pushing...")
        os.system("git add -A")
        os.system('git commit -m "init: clan snapshot setup" --allow-empty')
        os.system("git push origin main")
    else:
        print(f"  {pfx}Would commit and push 4+ files")

    # Enable Pages
    enable_pages(repo_name)

    # Trigger first workflow
    trigger_workflow(repo_name)

    # Done
    print_summary(repo_name, clan_info)

    if prompt_yn("Open site in browser", default="Y"):
        site = f"https://{GITHUB_USER}.github.io/{repo_name}/"
        webbrowser.open(site)

    os.chdir(str(PARENT_DIR))


if __name__ == "__main__":
    main()

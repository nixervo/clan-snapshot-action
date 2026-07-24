#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import urllib.request
import re
import shutil
from pathlib import Path

PARENT_DIR = Path.home() / "Desktop" / "Clan Reps"
SCRIPT_DIR = Path(__file__).parent
TEMPLATES_DIR = SCRIPT_DIR / "templates"
API_BASE = "https://playninjarift.com/api"

GITHUB_USER = None
DRY_RUN = False


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def dry_prefix():
    return "[DRY-RUN] " if DRY_RUN else ""


def gh(*args, capture=True, check=True):
    cmd = ["gh"] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=capture, text=True, check=check)
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


def prompt_file(question):
    raw = input(f"  {question}: ").strip()
    if not raw:
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
        }
    except Exception:
        return None


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
    try:
        result = gh("api", f"repos/{GITHUB_USER}/{name}/pages",
                    "-X", "POST",
                    "-f", "source.branch=main",
                    "-f", "source.path=/",
                    capture=True, check=False)
        if "already" in result.lower() or not result:
            gh("api", f"repos/{GITHUB_USER}/{name}/pages",
               "-X", "PUT",
               "-f", "source.branch=main",
               "-f", "source.path=/",
               capture=False)
        print(f"  Pages enabled.")
    except Exception as e:
        print(f"  Warning: couldn't enable Pages automatically ({e})")
        print(f"  Enable manually: Settings -> Pages -> Deploy from main / (root)")


def trigger_workflow(name):
    pfx = dry_prefix()
    print(f"  {pfx}Triggering first workflow run...")
    if DRY_RUN:
        print(f"  {pfx}Would run: gh workflow run clan-snapshot.yml --ref main")
        return
    try:
        gh("workflow", "run", "clan-snapshot.yml", "--ref", "main",
           repo=f"{GITHUB_USER}/{name}", capture=False)
        print(f"  Workflow triggered.")
    except Exception as e:
        print(f"  Warning: couldn't trigger workflow ({e})")
        print(f"  Trigger manually: Actions -> Clan Snapshot -> Run workflow")


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


def main():
    global GITHUB_USER, DRY_RUN

    DRY_RUN = "--dry-run" in sys.argv

    print_header()

    if not gh("auth", "status", capture=True, check=False):
        print("  GitHub CLI not authenticated. Run `gh auth login` first.")
        sys.exit(1)

    GITHUB_USER = detect_github_user()
    if not GITHUB_USER:
        print("  Could not detect GitHub username.")
        sys.exit(1)

    # Step 1: Clan ID
    print("  1. Clan Information")
    clan_id = None
    clan_info = None
    while clan_info is None:
        raw = prompt("Clan ID (e.g. 2527)")
        try:
            clan_id = int(raw)
            clan_info = fetch_clan_info(clan_id)
            if clan_info:
                print(f"     Found: {clan_info['name']} ({clan_info['members']} members)")
            else:
                print(f"     Clan {clan_id} not found. Check the ID and try again.")
        except ValueError:
            print("     Enter a numeric clan ID.")

    # Step 2: Repo details
    print("\n  2. Repository")
    default_repo = slugify(clan_info["name"]) + "-reps"
    repo_name = prompt("Repo name", default=default_repo,
                       validate=lambda v: re.match(r'^[a-zA-Z0-9_.-]+$', v) is not None)
    display_name = prompt("Display name (for HTML title)", default=clan_info["name"])
    visibility = "public"
    if not prompt_yn("Public repo", default="Y"):
        visibility = "private"
    create_desc = f"NinjaRift clan {clan_id} ({clan_info['name']}) reputation snapshots"

    # Step 3: Logo / Favicon
    print("\n  3. Media (optional)")
    logo_path = None
    while True:
        p = prompt_file("Logo image (drag file here or Enter to skip)")
        if p is None:
            break
        ext = p.suffix.lower()
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            logo_path = p
            break
        print(f"  Unsupported format '{ext}'. Use PNG, JPG, GIF, or WebP.")
    favicon_path = None
    while True:
        p = prompt_file("Favicon icon (drag file here or Enter to skip)")
        if p is None:
            break
        ext = p.suffix.lower()
        if ext in (".ico", ".png"):
            favicon_path = p
            break
        print(f"  Unsupported format '{ext}'. Use ICO or PNG.")

    # Step 4: Confirm
    print(f"\n  4. Confirm")
    print(f"     GitHub user:    {GITHUB_USER}")
    print(f"     Repo:           {GITHUB_USER}/{repo_name} ({visibility})")
    print(f"     Clan ID:        {clan_id} ({clan_info['name']} \u00b7 {clan_info['members']} members)")
    print(f"     Logo:           {logo_path.name + ' (' + str(logo_path.stat().st_size // 1024) + ' KB)' if logo_path else '(none)'}")
    print(f"     Favicon:        {favicon_path.name + ' (' + str(favicon_path.stat().st_size // 1024) + ' KB)' if favicon_path else '(none)'}")
    print(f"     Dry-run mode:   {'Yes' if DRY_RUN else 'No'}")
    if not prompt_yn("Proceed", default="Y"):
        print("  Cancelled.")
        sys.exit(0)

    # Execute
    pfx = dry_prefix()
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

    if not DRY_RUN and prompt_yn("Open site in browser", default="Y"):
        site = f"https://{GITHUB_USER}.github.io/{repo_name}/"
        import webbrowser
        webbrowser.open(site)

    if not DRY_RUN:
        os.chdir(str(PARENT_DIR))


if __name__ == "__main__":
    main()

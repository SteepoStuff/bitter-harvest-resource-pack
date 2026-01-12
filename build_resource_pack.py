#!/usr/bin/env python3
"""
Bitter Harvest Resource Pack Builder

Merges GUI backgrounds into ModelEngine pack with optional auto-publishing.

Usage:
    python build_resource_pack.py                    # Basic build
    python build_resource_pack.py --publish          # Build, upload, update server.properties
    python build_resource_pack.py --publish --github # Build and upload to GitHub
    python build_resource_pack.py --auto             # Full automation (build + publish + all configs)
    python build_resource_pack.py --setup            # First-time setup wizard

Server Properties:
    python build_resource_pack.py -p                                # Uses default TestServer path
    python build_resource_pack.py -p -P "D:/Server/server.properties"  # Custom path

Requirements:
    pip install Pillow requests pyyaml
"""

import sys
import io

# Fix Windows console encoding for Unicode
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid
import zipfile
from pathlib import Path
from typing import Optional

# Optional dependencies
try:
    from PIL import Image, ImageDraw
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    print("Warning: Pillow not installed. Run: pip install Pillow")

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


# ============================================
# CONFIGURATION
# ============================================

CONFIG_FILE = Path("pack_config.json")

# Background definitions: (filename, width, height, base_color)
BACKGROUNDS = {
    "pet_menu": ("pet_menu", 176, 222, (40, 40, 50)),
    "all_pets": ("all_pets", 176, 186, (30, 35, 45)),
    "feed_selector": ("feed_selector", 176, 114, (50, 40, 40)),
    "confirm_dialog": ("confirm_dialog", 176, 78, (60, 30, 30)),
    "shop": ("shop", 176, 222, (40, 50, 40)),
    "default_small": ("default_small", 176, 114, (45, 45, 45)),
    "default_large": ("default_large", 176, 222, (45, 45, 45)),
}

# Unicode codepoints for background characters
BACKGROUND_CODEPOINTS = {
    "pet_menu": 0xE000,
    "all_pets": 0xE001,
    "feed_selector": 0xE002,
    "confirm_dialog": 0xE003,
    "shop": 0xE004,
    "default_small": 0xE005,
    "default_large": 0xE006,
}

# Negative space characters
NEGATIVE_SPACE_CHARS = {
    -1: "\uF801", -2: "\uF802", -4: "\uF803", -8: "\uF804",
    -16: "\uF805", -32: "\uF806", -64: "\uF807", -128: "\uF808",
    1: "\uF811", 2: "\uF812", 4: "\uF813", 8: "\uF814",
    16: "\uF815", 32: "\uF816", 64: "\uF817", 128: "\uF818",
}

# Auto-detect paths
MODELENGINE_SEARCH_PATHS = [
    Path("../TestServer/plugins/ModelEngine/resource pack.zip"),
    Path("F:/Users/Baker/Documents/Work/MC/TestServer/plugins/ModelEngine/resource pack.zip"),
]

DEFAULT_CONFIG_PATH = Path("F:/Users/Baker/Documents/Work/MC/TestServer/plugins/BitterHarvest/config.yml")
DEFAULT_PROPERTIES_PATH = Path("F:/Users/Baker/Documents/Work/MC/TestServer/server.properties")
DEFAULT_ART_PATH = Path("my_art")  # Relative to this script
DEFAULT_OUTPUT_PATH = Path("bitter-harvest-pack.zip")  # Output in same folder as script
RESOURCE_PACK_REPO = Path(__file__).parent.resolve()  # This repo
DEFAULT_JAVA_OUTPUT = Path("F:/Users/Baker/Documents/Work/MC/Bitter-Harvest/Main/bitter-harvest/src/main/java/gg/paleraven/bitterharvest/gui/backgrounds/GeneratedBackgrounds.java")


# ============================================
# CONFIG FILE MANAGEMENT
# ============================================

def load_pack_config() -> dict:
    """Load pack_config.json or return defaults."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {
        "mc_packs_api_key": "",
        "github_token": "",
        "github_repo": "",
        "server_config_path": str(DEFAULT_CONFIG_PATH),
        "server_properties_path": str(DEFAULT_PROPERTIES_PATH),
        "auto_publish": False,
        "auto_update_config": False
    }


def save_pack_config(config: dict):
    """Save pack_config.json."""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)
    print(f"  Saved config to {CONFIG_FILE}")


# ============================================
# IMAGE GENERATION
# ============================================

def create_placeholder_background(name: str, width: int, height: int, base_color: tuple) -> Image.Image:
    """Create a placeholder GUI background image."""
    if not HAS_PIL:
        raise RuntimeError("Pillow required for image generation")

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    padding = 4
    draw.rectangle(
        [padding, padding, width - padding - 1, height - padding - 1],
        fill=(*base_color, 230)
    )

    inner_pad = 6
    highlight = tuple(min(255, c + 30) for c in base_color)
    draw.rectangle(
        [inner_pad, inner_pad, width - inner_pad - 1, height - inner_pad - 1],
        outline=(*highlight, 200),
        width=1
    )

    shadow = tuple(max(0, c - 30) for c in base_color)
    draw.rectangle(
        [padding, padding, width - padding - 1, height - padding - 1],
        outline=(*shadow, 150),
        width=1
    )

    for y in range(min(20, height // 4)):
        alpha = int(40 * (1 - y / 20))
        draw.line([(padding + 2, padding + 2 + y), (width - padding - 3, padding + 2 + y)],
                  fill=(255, 255, 255, alpha))

    return img


def generate_all_backgrounds(output_dir: Path, custom_art_dir: Optional[Path] = None) -> dict:
    """Generate background images, using custom art if available."""
    textures_dir = output_dir / "assets" / "bitterharvest" / "textures" / "gui"
    textures_dir.mkdir(parents=True, exist_ok=True)

    metadata = {}

    for name, (filename, width, height, color) in BACKGROUNDS.items():
        custom_path = custom_art_dir / f"{filename}.png" if custom_art_dir else None

        if custom_path and custom_path.exists():
            img = Image.open(custom_path).convert("RGBA")
            if img.size != (width, height):
                print(f"  \u26a0 {filename}.png is {img.size}, expected ({width}, {height})")
            img_path = textures_dir / f"{filename}.png"
            img.save(img_path, "PNG")
            print(f"  \u2713 Custom:    {filename}.png ({img.size[0]}x{img.size[1]})")
        else:
            img = create_placeholder_background(name, width, height, color)
            img_path = textures_dir / f"{filename}.png"
            img.save(img_path, "PNG")
            print(f"  \u2713 Generated: {filename}.png ({width}x{height})")

        metadata[name] = {
            "file": f"bitterharvest:gui/{filename}.png",
            "width": width,
            "height": height,
            "codepoint": BACKGROUND_CODEPOINTS[name]
        }

    return metadata


# ============================================
# FONT CONFIGURATION
# ============================================

def create_font_config(output_dir: Path, bg_metadata: dict):
    """Create font configuration for GUI backgrounds."""
    font_dir = output_dir / "assets" / "bitterharvest" / "font"
    font_dir.mkdir(parents=True, exist_ok=True)

    space_textures_dir = output_dir / "assets" / "bitterharvest" / "textures" / "font"
    space_textures_dir.mkdir(parents=True, exist_ok=True)

    spacing_img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    spacing_img.save(space_textures_dir / "space.png", "PNG")

    providers = []

    for offset, char in NEGATIVE_SPACE_CHARS.items():
        providers.append({
            "type": "bitmap",
            "file": "bitterharvest:font/space.png",
            "ascent": 0,
            "height": 1,
            "chars": [char]
        })

    for name, meta in bg_metadata.items():
        providers.append({
            "type": "bitmap",
            "file": meta["file"],
            "ascent": meta["height"] - 12,
            "height": meta["height"],
            "chars": [chr(meta["codepoint"])]
        })

    font_config = {"providers": providers}
    font_file = font_dir / "gui.json"
    with open(font_file, "w") as f:
        json.dump(font_config, f, indent=2)

    print(f"  \u2713 Created font config")


def create_pack_mcmeta(output_dir: Path):
    """Create pack.mcmeta."""
    mcmeta = {
        "pack": {
            "pack_format": 34,
            "description": "Bitter Harvest GUI Backgrounds - Pale Raven Network"
        }
    }
    with open(output_dir / "pack.mcmeta", "w") as f:
        json.dump(mcmeta, f, indent=2)
    print(f"  \u2713 Created pack.mcmeta")


# ============================================
# PACK MERGING
# ============================================

def find_modelengine_pack() -> Optional[Path]:
    """Auto-detect ModelEngine resource pack."""
    script_dir = Path(__file__).parent.resolve()

    for search_path in MODELENGINE_SEARCH_PATHS:
        if not search_path.is_absolute():
            full_path = script_dir / search_path
        else:
            full_path = search_path
        if full_path.exists():
            return full_path.resolve()
    return None


def merge_with_modelengine(me_pack_path: Optional[Path], output_dir: Path) -> bool:
    """Merge with ModelEngine pack if available."""
    if not me_pack_path or not me_pack_path.exists():
        print("  \u26a0 No ModelEngine pack - creating standalone")
        return False

    print(f"  \u2713 Merging with: {me_pack_path.name}")

    if me_pack_path.suffix == ".zip":
        with zipfile.ZipFile(me_pack_path, "r") as zf:
            zf.extractall(output_dir)
    else:
        for item in me_pack_path.iterdir():
            if item.is_dir():
                shutil.copytree(item, output_dir / item.name, dirs_exist_ok=True)
            else:
                shutil.copy2(item, output_dir / item.name)
    return True


def create_final_pack(output_dir: Path, final_path: Path) -> str:
    """Create final ZIP and return SHA-1 hash."""
    with zipfile.ZipFile(final_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(output_dir):
            for file in files:
                file_path = Path(root) / file
                arc_name = file_path.relative_to(output_dir)
                zf.write(file_path, arc_name)

    sha1 = hashlib.sha1()
    with open(final_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha1.update(chunk)

    return sha1.hexdigest()


# ============================================
# PUBLISHING
# ============================================

def upload_to_fileio(zip_path: Path) -> Optional[str]:
    """Upload pack to file.io (free, no CAPTCHA, fully automated)."""
    if not HAS_REQUESTS:
        print("  X requests library required. Run: pip install requests")
        return None

    print("\n[UPLOAD] Uploading to file.io...")

    try:
        with open(zip_path, 'rb') as f:
            response = requests.post(
                'https://file.io/',
                files={'file': (zip_path.name, f, 'application/zip')},
                data={'expires': '14d'},  # Keep for 14 days
                timeout=120
            )

        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                url = data.get('link')
                print(f"  OK Uploaded successfully!")
                print(f"  OK URL: {url}")
                print(f"  ! Note: Link expires after first download or 14 days")
                return url
            else:
                print(f"  X Upload failed: {data.get('message', 'Unknown error')}")
                return None
        else:
            print(f"  X Upload failed: HTTP {response.status_code}")
            return None

    except Exception as e:
        print(f"  X Upload error: {e}")
        return None


def upload_to_0x0(zip_path: Path) -> Optional[str]:
    """Upload pack to 0x0.st (free, no CAPTCHA, fully automated)."""
    if not HAS_REQUESTS:
        print("  X requests library required. Run: pip install requests")
        return None

    print("\n[UPLOAD] Uploading to 0x0.st...")

    try:
        with open(zip_path, 'rb') as f:
            response = requests.post(
                'https://0x0.st',
                files={'file': (zip_path.name, f, 'application/zip')},
                timeout=120
            )

        if response.status_code == 200:
            url = response.text.strip()
            print(f"  OK Uploaded successfully!")
            print(f"  OK URL: {url}")
            return url
        else:
            print(f"  X Upload failed: HTTP {response.status_code}")
            print(f"  {response.text[:200] if response.text else ''}")
            return None

    except Exception as e:
        print(f"  X Upload error: {e}")
        return None


def upload_auto(zip_path: Path) -> Optional[str]:
    """Try multiple upload services until one works."""
    # Try 0x0.st first (most reliable)
    url = upload_to_0x0(zip_path)
    if url:
        return url

    # Try file.io as backup
    print("  Trying backup host...")
    url = upload_to_fileio(zip_path)
    if url:
        return url

    print("\n  X All automatic upload services failed")
    print("  -> Please upload manually to https://mc-packs.net/")
    print(f"  -> Then run: python build_resource_pack.py --url \"YOUR_URL\"")
    return None


def upload_to_github_release(zip_path: Path, sha1_hash: str) -> Optional[str]:
    """Upload pack to GitHub Releases using gh CLI."""
    import subprocess

    if not RESOURCE_PACK_REPO.exists():
        print(f"  X Resource pack repo not found: {RESOURCE_PACK_REPO}")
        return None

    print("\n[UPLOAD] Publishing to GitHub Releases...")

    try:
        # Resolve to absolute path
        zip_abs = zip_path.resolve()
        zip_name = zip_path.name

        # Delete existing 'latest' release if exists
        subprocess.run(
            ['gh', 'release', 'delete', 'latest', '--yes'],
            cwd=RESOURCE_PACK_REPO,
            capture_output=True
        )

        # Create new release tagged 'latest'
        result = subprocess.run(
            ['gh', 'release', 'create', 'latest', str(zip_abs),
             '--title', 'Latest Resource Pack',
             '--notes', f'Auto-generated resource pack.\n\n**SHA-1:** `{sha1_hash}`'],
            cwd=RESOURCE_PACK_REPO,
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            # Get the download URL
            url_result = subprocess.run(
                ['gh', 'release', 'view', 'latest', '--json', 'assets', '--jq', '.assets[0].url'],
                cwd=RESOURCE_PACK_REPO,
                capture_output=True,
                text=True
            )
            url = url_result.stdout.strip()

            if not url:
                # Construct URL manually as fallback
                repo_result = subprocess.run(
                    ['gh', 'repo', 'view', '--json', 'nameWithOwner', '--jq', '.nameWithOwner'],
                    cwd=RESOURCE_PACK_REPO,
                    capture_output=True,
                    text=True
                )
                repo_name = repo_result.stdout.strip()
                if repo_name:
                    url = f"https://github.com/{repo_name}/releases/download/latest/{zip_name}"

            print(f"  OK Published to GitHub!")
            print(f"  OK URL: {url}")

            # Commit the updated pack
            subprocess.run(['git', 'add', zip_name], cwd=RESOURCE_PACK_REPO, capture_output=True)
            subprocess.run(
                ['git', 'commit', '-m', f'Update resource pack ({sha1_hash[:8]})'],
                cwd=RESOURCE_PACK_REPO,
                capture_output=True
            )
            subprocess.run(['git', 'push'], cwd=RESOURCE_PACK_REPO, capture_output=True)

            return url
        else:
            print(f"  X Failed to create release: {result.stderr}")
            return None

    except Exception as e:
        print(f"  X GitHub upload error: {e}")
        return None


def upload_to_mcpacks(zip_path: Path) -> Optional[str]:
    """Prompt user to upload to mc-packs.net manually (site requires CAPTCHA)."""
    import webbrowser

    print("\n[UPLOAD] mc-packs.net Upload")
    print("  ! mc-packs.net requires CAPTCHA - manual upload needed")
    print("")
    print(f"  1. Opening https://mc-packs.net/ in your browser...")
    print(f"  2. Upload: {zip_path.absolute()}")
    print(f"  3. Copy the download URL they give you")
    print("")

    # Try to open browser
    try:
        webbrowser.open('https://mc-packs.net/')
    except:
        pass

    # Prompt for URL
    print("  Paste the download URL here (or press Enter to skip):")
    user_url = input("  > ").strip()

    if user_url:
        # Clean up the URL
        if not user_url.startswith('http'):
            user_url = 'https://' + user_url
        print(f"  OK URL: {user_url}")
        return user_url

    print("  X Skipped - run with --url later to update configs")
    return None


def upload_to_github(zip_path: Path, token: str, repo: str) -> Optional[str]:
    """Upload pack to GitHub Releases."""
    if not HAS_REQUESTS:
        print("  \u2717 requests library required")
        return None

    print("\n\u2601 Uploading to GitHub Releases...")

    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json'
    }

    try:
        # Check for existing release
        release_url = f'https://api.github.com/repos/{repo}/releases/tags/resource-pack'
        response = requests.get(release_url, headers=headers, timeout=30)

        if response.status_code == 200:
            release = response.json()
            release_id = release['id']

            # Delete old asset
            for asset in release.get('assets', []):
                if asset['name'] == zip_path.name:
                    requests.delete(asset['url'], headers=headers, timeout=30)
        else:
            # Create new release
            create_response = requests.post(
                f'https://api.github.com/repos/{repo}/releases',
                headers=headers,
                json={
                    'tag_name': 'resource-pack',
                    'name': 'Resource Pack (Auto-Updated)',
                    'body': 'Automatically updated by build_resource_pack.py',
                    'draft': False,
                    'prerelease': False
                },
                timeout=30
            )
            release = create_response.json()
            release_id = release['id']

        # Upload asset
        upload_url = f'https://uploads.github.com/repos/{repo}/releases/{release_id}/assets?name={zip_path.name}'

        with open(zip_path, 'rb') as f:
            upload_response = requests.post(
                upload_url,
                headers={**headers, 'Content-Type': 'application/zip'},
                data=f,
                timeout=120
            )

        if upload_response.status_code == 201:
            asset = upload_response.json()
            url = asset['browser_download_url']
            print(f"  \u2713 Uploaded successfully!")
            print(f"  \u2713 URL: {url}")
            return url
        else:
            print(f"  \u2717 Upload failed: {upload_response.status_code}")
            return None

    except Exception as e:
        print(f"  \u2717 GitHub error: {e}")
        return None


# ============================================
# CONFIG UPDATES
# ============================================

def update_plugin_config(config_path: Path, url: str, hash_str: str) -> bool:
    """Update BitterHarvest plugin config.yml."""
    print(f"\n\U0001F4DD Updating plugin config: {config_path}")

    if not config_path.exists():
        print(f"  \u2717 Config not found")
        return False

    if not HAS_YAML:
        print(f"  \u2717 PyYAML required. Run: pip install pyyaml")
        return False

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        if 'resourcepack' not in config:
            config['resourcepack'] = {}

        config['resourcepack']['enabled'] = True
        config['resourcepack']['url'] = url
        config['resourcepack']['sha1'] = hash_str

        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        print(f"  \u2713 Updated resourcepack.url")
        print(f"  \u2713 Updated resourcepack.sha1")
        print(f"  \u2713 Enabled resourcepack")
        return True

    except Exception as e:
        print(f"  \u2717 Failed: {e}")
        return False


def generate_pack_uuid(hash_str: str) -> str:
    """Generate a consistent UUID from the pack's SHA-1 hash.

    Uses UUID v5 (SHA-1 based) with the hash as the name, ensuring the same
    pack always gets the same UUID.
    """
    # Use the DNS namespace and the hash as the name for a consistent UUID
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"bitterharvest-pack-{hash_str}"))


def update_server_properties(properties_path: Path, url: str, hash_str: str) -> bool:
    """Update server.properties - ONLY touches resource pack lines."""
    print(f"\n\U0001F4DD Updating server.properties: {properties_path}")

    if not properties_path.exists():
        print(f"  \u2717 File not found")
        return False

    try:
        with open(properties_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Generate consistent UUID for this pack
        pack_uuid = generate_pack_uuid(hash_str)

        # Escape colons in URL for server.properties format
        escaped_url = url.replace(':', '\\:')

        # Only these keys will be modified
        resource_pack_keys = {
            'resource-pack': escaped_url,
            'resource-pack-sha1': hash_str,
            'resource-pack-id': pack_uuid,
        }

        updated_keys = set()
        new_lines = []

        for line in lines:
            stripped = line.strip()

            # Skip empty lines and comments - preserve them
            if not stripped or stripped.startswith('#'):
                new_lines.append(line)
                continue

            # Check if this is a key=value line
            if '=' in stripped:
                key = stripped.split('=', 1)[0].strip()

                # Only modify resource pack keys
                if key in resource_pack_keys:
                    new_lines.append(f"{key}={resource_pack_keys[key]}\n")
                    updated_keys.add(key)
                else:
                    # Preserve all other lines exactly as-is
                    new_lines.append(line)
            else:
                new_lines.append(line)

        # Add missing resource pack keys at the end
        for key, value in resource_pack_keys.items():
            if key not in updated_keys:
                new_lines.append(f"{key}={value}\n")

        with open(properties_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)

        print(f"  \u2713 Updated resource-pack URL")
        print(f"  \u2713 Updated resource-pack-sha1")
        print(f"  \u2713 Updated resource-pack-id: {pack_uuid}")
        return True

    except Exception as e:
        print(f"  \u2717 Failed: {e}")
        return False


# ============================================
# JAVA CONSTANTS GENERATOR
# ============================================

def generate_java_constants(bg_metadata: dict, sha1_hash: str, output_file: Path):
    """Generate Java constants file."""
    lines = [
        "// AUTO-GENERATED by build_resource_pack.py",
        "// Do not edit manually",
        "",
        "package gg.paleraven.bitterharvest.gui.backgrounds;",
        "",
        "public final class GeneratedBackgrounds {",
        "",
        f'    public static final String PACK_SHA1 = "{sha1_hash}";',
        "",
        "    // Background characters",
    ]

    for name, meta in bg_metadata.items():
        const_name = name.upper()
        lines.append(f'    public static final char BG_{const_name} = \'\\u{meta["codepoint"]:04X}\';')

    lines.extend([
        "",
        "    private GeneratedBackgrounds() {}",
        "}",
        ""
    ])

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        f.write("\n".join(lines))
    print(f"  \u2713 Generated Java constants")


# ============================================
# SETUP WIZARD
# ============================================

def run_setup_wizard():
    """Interactive setup for first-time configuration."""
    print("\n\U0001F527 RESOURCE PACK BUILD SETUP WIZARD")
    print("=" * 50)

    config = load_pack_config()

    print("\n[1/4] Upload Method")
    print("  1. mc-packs.net (free, no account needed)")
    print("  2. GitHub Releases (requires token)")
    print("  3. Manual upload only")

    choice = input("\nSelect [1-3] (default: 1): ").strip() or "1"

    if choice == "2":
        print("\nGitHub Setup:")
        config['github_token'] = input("  Personal Access Token: ").strip()
        config['github_repo'] = input("  Repository (user/repo): ").strip()

    print("\n[2/4] Plugin Config Path")
    print(f"  Current: {config.get('server_config_path', 'not set')}")
    new_path = input("  New path (Enter to keep): ").strip()
    if new_path:
        config['server_config_path'] = new_path

    print("\n[3/4] server.properties Path")
    print(f"  Current: {config.get('server_properties_path', 'not set')}")
    new_path = input("  New path (Enter to keep): ").strip()
    if new_path:
        config['server_properties_path'] = new_path

    print("\n[4/4] Automation Settings")
    config['auto_publish'] = input("  Auto-publish on build? [y/N]: ").lower() == 'y'
    config['auto_update_config'] = input("  Auto-update configs? [y/N]: ").lower() == 'y'

    save_pack_config(config)

    print("\n" + "=" * 50)
    print("\u2713 Setup complete!")
    print("\nRun with:")
    print("  python build_resource_pack.py          # Basic build")
    print("  python build_resource_pack.py --auto   # Full automation")


# ============================================
# MAIN
# ============================================

def main():
    parser = argparse.ArgumentParser(description="Bitter Harvest Resource Pack Builder")
    parser.add_argument('--input', '-i', type=Path, help='ModelEngine pack (auto-detects)')
    parser.add_argument('--output', '-o', type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument('--art', type=Path, default=DEFAULT_ART_PATH, help='Custom art folder')
    parser.add_argument('--java-output', type=Path, default=DEFAULT_JAVA_OUTPUT)
    parser.add_argument('--publish', '-p', action='store_true', help='Upload to GitHub Releases')
    parser.add_argument('--mcpacks', action='store_true', help='Use mc-packs.net instead (requires manual CAPTCHA)')
    parser.add_argument('--update-config', '-u', action='store_true', help='Update server configs')
    parser.add_argument('--config-path', '-c', type=Path, help='Plugin config.yml path')
    parser.add_argument('--properties-path', '-P', type=Path,
                       default=DEFAULT_PROPERTIES_PATH,
                       help=f'server.properties path (default: {DEFAULT_PROPERTIES_PATH})')
    parser.add_argument('--auto', '-a', action='store_true', help='Build + publish + update')
    parser.add_argument('--standalone', '-s', action='store_true', help='Skip ModelEngine merge')
    parser.add_argument('--setup', action='store_true', help='Run setup wizard')
    parser.add_argument('--url', type=str, help='Manual URL (skips upload, just updates configs)')

    args = parser.parse_args()

    # Setup wizard
    if args.setup:
        run_setup_wizard()
        return

    print("=" * 60)
    print("  BITTER HARVEST RESOURCE PACK BUILDER")
    print("=" * 60)

    # Load saved config
    pack_config = load_pack_config()

    # Auto mode enables everything
    if args.auto:
        args.publish = True
        args.update_config = True
        if pack_config.get('auto_publish'):
            args.publish = True
        if pack_config.get('auto_update_config'):
            args.update_config = True

    # Auto-detect ModelEngine pack
    input_pack = args.input
    if not input_pack and not args.standalone:
        print("\n\U0001F50D Auto-detecting ModelEngine pack...")
        input_pack = find_modelengine_pack()
        if input_pack:
            print(f"  \u2713 Found: {input_pack}")
        else:
            print("  \u26a0 Not found - standalone pack")

    # Check custom art
    custom_art_dir = args.art if args.art.exists() else None
    if custom_art_dir:
        art_files = list(custom_art_dir.glob("*.png"))
        if art_files:
            print(f"\n\U0001F3A8 Custom art folder: {custom_art_dir}")
            print(f"  Found {len(art_files)} PNG file(s)")
        else:
            custom_art_dir = None

    # Create temp directory
    temp_dir = Path("temp_pack_build")
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()

    try:
        # Step 1: Merge with ModelEngine
        print("\n\U0001F4E6 [1/5] Preparing base pack...")
        merge_with_modelengine(input_pack, temp_dir)

        # Step 2: Generate backgrounds
        print("\n\U0001F3A8 [2/5] Generating background images...")
        bg_metadata = generate_all_backgrounds(temp_dir, custom_art_dir)

        # Step 3: Create font config
        print("\n\U0001F520 [3/5] Creating font configuration...")
        create_font_config(temp_dir, bg_metadata)

        # Step 4: Create pack.mcmeta
        print("\n\U0001F4C4 [4/5] Creating pack metadata...")
        create_pack_mcmeta(temp_dir)

        # Step 5: Create final ZIP
        print("\n\U0001F4E6 [5/5] Creating final pack...")
        sha1_hash = create_final_pack(temp_dir, args.output)
        file_size = args.output.stat().st_size / (1024 * 1024)
        print(f"  \u2713 Created: {args.output} ({file_size:.2f} MB)")
        print(f"  \u2713 SHA-1: {sha1_hash}")

        # Generate Java constants
        generate_java_constants(bg_metadata, sha1_hash, args.java_output)

        # Publish or use manual URL
        url = args.url  # Manual URL if provided
        if not url and args.publish:
            if args.mcpacks:
                url = upload_to_mcpacks(args.output)
            else:
                # Default: use GitHub Releases (fully automated via gh CLI)
                url = upload_to_github_release(args.output, sha1_hash)

        # Update configs
        if url:
            # --publish always updates server.properties (can skip with explicit empty path)
            if args.publish or args.update_config:
                props_path = args.properties_path
                if props_path and props_path.exists():
                    update_server_properties(props_path, url, sha1_hash)
                elif props_path and not props_path.exists():
                    print(f"\n\u26a0 server.properties not found at: {props_path}")

            # Plugin config only updated with --update-config or --auto
            if args.update_config:
                cfg_path = args.config_path or Path(pack_config.get('server_config_path', ''))
                if cfg_path and cfg_path.exists():
                    update_plugin_config(cfg_path, url, sha1_hash)

        # Summary
        print("\n" + "=" * 60)
        print("  BUILD COMPLETE!")
        print("=" * 60)
        print(f"\n  Pack:   {args.output}")
        print(f"  SHA-1:  {sha1_hash}")
        if url:
            print(f"  URL:    {url}")
            print(f"\n  \u2713 Server will use new pack on next player join!")
        else:
            print(f"\n  Next: Upload pack and update config.yml with URL + SHA-1")

    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


if __name__ == "__main__":
    main()

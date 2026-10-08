# we-still

Pick any Steam Wallpaper Engine workshop wallpaper (for example in the
[waypaper](https://github.com/anufrievroman/waypaper) GUI) and get it as a
high-quality **still** desktop background on Linux.

Why: GNOME's compositor (Mutter) has no `wlr-layer-shell`, so live wallpaper
tools such as `linux-wallpaperengine` cannot draw behind your windows there.
`we-still` skips the live part and sets one good frame instead. It never opens
a window.

## Honest limits

- Still images only. Nothing moves, and live animation is impossible on GNOME.
- Wallpaper Engine effects (shaders, particles, audio, cursor reaction) are ignored.
- Scene wallpapers are composed from their own layers (`we_still/compose.py`);
  exotic scenes can fail. Then the biggest image in the folder is used, and as a
  last resort the workshop preview (you get a notification when that happens).
- Needs the wallpaper files on disk (Steam workshop download).

## Tested on

96 workshop wallpapers (65 scene, 18 video, 8 web, 5 preset), all rendered
without a window: 64 of 65 scenes composed from their own layers (the 65th has
only a text layer and falls back), all 18 videos cut at native resolution.
A few particle-only or audio-visualizer wallpapers have no still image and come
out dark or flat. Sharpness is capped by the source art and video resolution.

## Install

```
./install.sh                 # pipx or pip --user, no sudo
sudo pacman -S --needed python-pillow python-numpy ffmpeg   # if install.sh says so
```

Or build the Arch package with the included `PKGBUILD`. Optional: `waypaper`, `libnotify`.

## Use

```
we-still doctor                          # check ffmpeg, Pillow, gsettings, Steam dir, waypaper
we-still set 3338758168                  # workshop id, folder, or any file inside it
we-still render 3338758168 -o out.png    # just write the image (--size 2560x1440)
we-still all --out ~/wallpapers          # render the whole workshop folder
```

Supported desktops: GNOME (gsettings), KDE Plasma (`plasma-apply-wallpaperimage`),
Sway/Hyprland (`awww`/`swww`, `hyprpaper`, `swaybg`), other X11 (`feh`, `xwallpaper`).

## Waypaper setup

```
we-still setup
```

Writes these keys into `~/.config/waypaper/config.ini`: `backend=none`,
`folder=<your workshop dir>`, `subfolders=True`, `all_subfolders=True`,
`post_command=we-still set $wallpaper`. Click a wallpaper in waypaper and the
still is set. It also installs a systemd user path unit (`we-still-guard.path`)
because waypaper rewrites its config from memory and can silently undo the
settings; the guard re-applies them. It only writes when something differs, so
it cannot loop.

## Troubleshooting

- Nothing changes: run `we-still set <id>` in a terminal and read the message; run `we-still doctor`.
- Wrong crop or blur: check `we-still doctor` for the detected screen size; override with `--size WxH`.
- Waypaper stopped calling us: `we-still setup` again, `systemctl --user status we-still-guard.path`.
- Steam in a custom library or Flatpak: both are found via `libraryfolders.vdf` / `~/.var/app/com.valvesoftware.Steam`.
- Old `we-guard.path` from a previous setup still active: `systemctl --user disable --now we-guard.path`.

## How it works

1. Resolve the id/path to the wallpaper folder (Steam roots + `libraryfolders.vdf`).
2. By `project.json` type: scene -> `compose.render`; video -> sharpest of a few
   ffmpeg frames at native resolution; web/preset/unknown -> biggest image in the folder.
3. Scale to cover the primary monitor's real pixel size and center-crop (never stretched).
4. Save as `~/.cache/we-still/current-<time>.png` (new name each time so GNOME reloads), set it, delete older `current-*`.

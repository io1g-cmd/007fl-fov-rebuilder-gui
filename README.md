# 007 First Light FOV Rebuilder GUI

A simple Windows GUI for building and installing custom **FOV / camera distance / camera height** patches for **007 First Light**.

This tool wraps the script-based rebuilder from Su4enka's Nexus mod and removes the need to edit values in a command prompt.

## Features

- Point-and-click game folder selection (game root or `Runtime` folder)
- Adjustable **FOV**, **camera distance (%)**, and **camera height**
- Built-in presets matching common Nexus mod packages
- One-click **Build & Install** into the game's `Runtime` folder
- **Remove patch files** to restore vanilla camera patch state
- Open the detected `Runtime` folder directly from the app

### Parameter guide

| Setting | Range | Notes |
|--------|-------|-------|
| FOV | 30–120 | Label scale matches the original mod pack (`40` = vanilla label, `90` = Better Camera Main scale) |
| Distance (%) | -60 to 60 | **Positive = farther**, **negative = closer** |
| Height | -0.75 to 0.75 | Spherical camera framing height offset |

Mission 3 freefall / skydive cameras remain excluded, same as the original rebuilder.

## Requirements

- Windows 10/11
- Python 3.8+
- Python package: `lz4`

## Quick start

1. Download or clone this repository.
2. Double-click `Launch.bat`.
3. Select your game folder, for example:
   - `D:\Games\007 First Light`
   - or `D:\SteamLibrary\steamapps\common\007 First Light\Runtime`
4. Adjust values or pick a preset.
5. Click **Build & Install**.
6. Launch the game.

Manual launch:

```bat
py -3 -m pip install -r requirements.txt
py -3 fov_rebuilder_gui.py
```

## Uninstall / revert camera patch

Use **Remove patch files** in the GUI, or manually delete:

- `Runtime\chunk0patch204.rpkg`
- `Runtime\chunk1patch204.rpkg`

If you replaced `Runtime\packagedefinition.txt`, restore the original backup if you have one.

## Credits & attribution

This GUI is a community helper built on top of existing mod tooling. **Please support and credit the original author.**

| Item | Credit |
|------|--------|
| Original mod | **Su4enka** — [Higher FOV and Camera](https://www.nexusmods.com/007firstlight/mods/15) |
| Rebuilder engine | `007FL_FOV_Rebuilder_Scripts` from the mod package above |
| Game | **007 First Light** by **IO Interactive** |
| GUI wrapper | Community contribution (this repository) |

If you share this tool on Nexus or elsewhere, please link both:

- This repository
- The original mod page: https://www.nexusmods.com/007firstlight/mods/15

## License

- GUI wrapper code in this repository: **MIT** (see `LICENSE`)
- Underlying camera patch build logic is included from Su4enka's mod rebuilder scripts and should remain credited to the original mod author

## Disclaimer

Use at your own risk. Always back up your game's `Runtime` folder before installing mods.

## 繁體中文簡介

這是一個 **007 First Light** 的 FOV / 鏡頭距離 / 鏡頭高度 GUI 安裝工具，基於 Nexus Mod 作者 **Su4enka** 的 `007FL_FOV_Rebuilder_Scripts` 製作。

- **Distance 正數 = 鏡頭更遠，負數 = 更近**
- 選好遊戲資料夾後按 **Build & Install** 即可
- 原版 Mod：https://www.nexusmods.com/007firstlight/mods/15

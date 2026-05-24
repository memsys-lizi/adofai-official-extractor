# ADOFAI Official Extractor

Experimental converter for old Unity scene-based ADOFAI official levels.

The first supported target is `Assets/scenes/Levels/1-X.unity`. It exports a vanilla-editor friendly `main.adofai`, copied image assets in the same folder, and a conversion report.

## Usage

```powershell
.\.venv\Scripts\python.exe -m adofai_official_extractor.extract_1x `
  --project "C:\Users\lizi\Documents\Doc\Unity\ADOFAI" `
  --out ".\exports\1-X"
```

## Current Scope

- Extracts old `scrLevelMaker.leveldata` into `pathData`.
- Rebuilds `SetSpeed` from serialized `scrFloor.speed`, instead of guessing from old `S` characters or `ffxSpeed`.
- Copies the referenced song and background image into the exported level folder.
- Converts scene `SpriteRenderer` objects under `BG` into `AddDecoration`, including inherited `scrParallax` where possible.
- Writes `.adofai` in the common readable style: settings are expanded, and actions/decorations are one event per line.
- Converts known floor effects into standard ADOFAI events where possible.
- Treats disabled CameraFilterPack components as the scene's filter library, and reports only enabled or event-referenced effects that cannot be mapped.

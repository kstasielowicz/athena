# ATHENA Training Tracker - Flask Product Demo

Gotowy do prezentacji moduł trackera treningów inspirowany ATHENA / Strength RIS.

## Najważniejsze funkcje

- Dashboard z liczbą treningów, serii, objętością i ostatnią wagą ciała
- Exercise Library z kartami ćwiczeń, zdjęciami i popupem szczegółów
- Dodawanie/edycja ćwiczeń oraz upload własnych zdjęć
- Routines: gotowe zestawy ćwiczeń do szybkiego uzupełnienia
- Workout Logger: historia treningów, edycja serii, notatki, RPE, mood, fatigue, focus i bodyweight
- Wellness tracking: masa ciała, sen, energia, stres, soreness
- Hevy Import:
  - iteracja po wszystkich stronach `page=1..page_count`, więc import nie kończy się na pierwszych 10 rekordach,
  - import `weight_kg` z `/v1/body_measurements`,
  - przypisanie wagi do treningu z tej samej daty albo ostatniej znanej wcześniejszej daty,
  - pomijanie duplikatów po `hevy_id`,
  - tryb demo i import JSON bez klucza API.

## Uruchomienie

### Windows

```bat
run.bat
```

### macOS / Linux

```bash
chmod +x run.sh
./run.sh
```

Następnie otwórz:

```text
http://127.0.0.1:5000
```

## Hevy API

Aplikacja obsługuje realną ścieżkę importu z Hevy API. Wklej klucz w ekranie importu albo ustaw zmienną środowiskową:

```bash
export HEVY_API_KEY="your-key"
```

Importer pobiera:

```text
GET /v1/workouts?page=1&limit=10
GET /v1/body_measurements?page=1&limit=10
```

i kontynuuje pobieranie do `page_count` lub do limitu bezpieczeństwa ustawionego w UI.

## Naprawa SQLite

Tworzenie nowego treningu działa w transakcji przez `lastrowid`, bez `RETURNING id`. Aplikacja wykonuje migracje przy starcie, więc starsza baza demo nie powinna powodować `OperationalError`.

## Polishing update

This version adds a more ATHENA-like gym interface: darker sport palette, green/gold performance accents, short loading screens between tabs, and a dedicated RIS Lab.

### RIS Lab

The RIS Lab lets the user enter sex formula, bodyweight and strength total. The app calculates and stores the RIS score in SQLite, then shows score history and categories:

- Foundation
- Developing
- Strong
- Advanced
- Elite

### ATHENA Coach Signal

The dashboard now includes a simple session advisor. It reads recent readiness, fatigue, focus and latest RIS score to suggest whether the user should push, maintain or recover.

## Latest UI/RIS revision
- RIS Lab now supports two modes: **ALL-4** (pull-up, dip, squat, muscle-up) and **UPPER** (pull-up, dip).
- Total is calculated automatically from the selected mode.
- Exercise placeholder graphics were recolored to ATHENA green/gym palette.
- Decorative UI circles no longer block clicks on selects, inputs or buttons.
- Added a product idea: a future Test Day Checklist for judging standards and video evidence.


## RIS correction update
- ALL-4 uses the public RIS 2025 formula structure with official constants shown on warisradji.com/ris.
- UPPER is clearly marked as an ATHENA demo extension for pull-up + dip only.
- Example check: Men, 88 kg BW, 60 kg pull-up + 90 kg dip gives about 70 RIS in UPPER mode, not about 29.
- The RIS page works as a calculator and saved calculations appear in history.


## Coefficient inspiration
The RIS Lab is based on the public RIS formula pattern. The app also mentions Wilks, DOTS and IPF GL as examples of strength-sport coefficient systems used to compare athletes with different bodyweights. In this demo, UPPER is not official RIS - it is an ATHENA product extension for pull-up + dip testing.

## Latest update - Exercise Type System

The workout logger now supports multiple exercise models, not only weight + reps:

- Strength - weight and repetitions
- Bodyweight - added weight and repetitions
- Timed - duration, with optional added load
- Distance - load and distance
- Cardio - duration, distance, calories and average heart rate
- Interval - rounds, work time and rest time
- Mobility - duration and notes
- Custom - mixed fields

Exercise Library includes more demo movements: Dip, Treadmill Run, Rowing Machine, Farmer Walk, Sprint Intervals, Mobility Flow and Dead Hang. The workout detail screen changes input fields automatically based on exercise type.

A new Personal Records page calculates best performances across all exercise categories.


## Product expansion added

This version includes:
- Workout Timeline with searchable history.
- ATHENA heatmap for training consistency.
- Exercise Progress screens with per-exercise history.
- Custom Exercise Tags in the library.
- Global Smart Search across workouts, exercises and routines.
- Routine Builder with Start Workout action.
- Session Score formula: readiness 35% + focus 25% + low fatigue 20% + mood 15% + duration discipline 5%.
- Muscle Group Analytics with SVG anatomy-style body map.
- Bodyweight timeline using wellness and Hevy body measurement data.
- Goals and Achievements center.
- Unified green ATHENA exercise image placeholders.

## UI revision update

This build includes a cleaner ATHENA UI pass:

- compact Workout Timeline heatmap with hover details,
- cleaner Smart Search layout and search bar,
- hover tooltips on heatmap, bodyweight chart, progress charts and muscle bars,
- Three.js anatomy muscle map with SVG fallback,
- simplified unified exercise graphics in the Exercise Library,
- reduced visual clutter in Workouts and Analytics.

## Latest UI/Product Update

This build adds:

- cleaned Workouts screen with compact timeline cards,
- compact heatmap with hover tooltips,
- command palette search from the top bar using the magnifier or Ctrl+K,
- interactive search results linking directly to workouts, exercises, routines and goals,
- anatomical SVG muscle map instead of the previous Three.js demo,
- improved Goals layout with spacing between modules,
- richer demo database with 38 workouts across recent weeks and months,
- unified exercise illustrations in the ATHENA green sport style.

The app is still fully local and runs on Flask + SQLite.


## Latest polish update
- Removed the rough anatomical map and kept analytics as clean, separate modern UI modules.
- Added editable goals: change values, target, status, notes, complete or reopen goals.
- Personal Records now link to the exact workout where the record was achieved.
- Exercise Library now uses one unified ATHENA exercise lab SVG placeholder across all exercises.

## Premium feature update

This package adds a wider ATHENA Training OS layer:

- Workout Replay - session timeline with sets, time markers and summary metrics.
- Quick Start Workout - dashboard shortcuts to continue the last session or start from a routine.
- Floating Workout Logger - quick action available while editing a workout.
- Workout Comparison - current session vs previous session with the same name.
- ATHENA Readiness v2 - one consistent formula using sleep, energy, stress, soreness and hydration.
- Bodyweight Center - timeline built from wellness and Hevy body measurement imports.
- RIS History - saved ALL-4 / UPPER RIS tests with trend visualization.
- ATHENA Level and Consistency Engine - simple product-style athlete profile score.
- Command Palette 2.0 - Ctrl+K actions for starting workouts, opening RIS, Hevy import, templates, bodyweight and coach preview.
- Workout Templates Marketplace - predefined ATHENA routines ready to start.
- Coaching Module - locked preview of future coach/athlete capability, without a separate coach dashboard.
- Exercise Progress remains linked to each movement, while PR cards link back to the source workout.
- Unified exercise SVG system - every exercise has a clean ATHENA-style placeholder image.

The app still runs locally with Flask and SQLite. Start it with:

```bash
pip install -r requirements.txt
python app.py
```

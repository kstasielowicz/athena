# ATHENA Training Tracker - omówienie

## 1. Cel produktu

ATHENA Training Tracker to prosty, ale kompletny moduł do rejestrowania treningów siłowych. Użytkownik może korzystać z biblioteki ćwiczeń, tworzyć rutyny, zapisywać treningi, edytować historię oraz śledzić wagę i samopoczucie.

## 2. Najważniejsze ekrany

- Dashboard - szybki podgląd aktywności i ostatnich danych.
- Exercise Library - ćwiczenia z opisem, zdjęciem, instrukcją, wskazówkami i błędami technicznymi.
- Routines - gotowe szablony treningowe.
- Workouts - historia treningów i edycja szczegółów.
- Wellness - masa ciała i samopoczucie.
- Hevy Import - import z zewnętrznego API.

## 3. Import Hevy

Problem: API zwraca dane stronami. Jeśli użytkownik ma 54 treningi, a API zwraca 10 na stronę, jeden request pobierze tylko 10.

Rozwiązanie: aplikacja czyta `page_count` i automatycznie pobiera strony `1..page_count`.

Dodatkowo aplikacja pobiera `body_measurements` i wykorzystuje `weight_kg`. Dla każdego treningu sprawdzana jest masa ciała z tej samej daty. Jeśli jej nie ma, używana jest ostatnia znana wcześniejsza masa ciała.

## 4. Dlaczego to jest gotowy moduł

Dane są zapisywane w SQLite, treningi można edytować, ćwiczenia mają pełne informacje, a importowane treningi z Hevy stają się normalnymi rekordami ATHENA.

## UI / product polishing points

- Added short loading transitions between tabs to make the app feel like a real product.
- Updated colors to a gym/performance style: dark interface, green energy accents and gold highlight elements.
- Added RIS Lab for bodyweight-relative strength scoring.
- Added ATHENA Coach Signal: a small recommendation card that combines readiness, fatigue and RIS into a training suggestion.

### Latest polish talking points
- RIS is split into ALL-4 and UPPER modes, matching the intended ATHENA strength testing workflow.
- The UI uses a dark gym dashboard style with green performance accents.
- Exercise cards support visual previews and detailed technical popups.
- Decorative UI effects were kept, but fixed so they do not block form controls.


## RIS correction update
- ALL-4 uses the public RIS 2025 formula structure with official constants shown on warisradji.com/ris.
- UPPER is clearly marked as an ATHENA demo extension for pull-up + dip only.
- Example check: Men, 88 kg BW, 60 kg pull-up + 90 kg dip gives about 70 RIS in UPPER mode, not about 29.
- The RIS page works as a calculator and saved calculations appear in history.


## Coefficient inspiration
The RIS Lab is based on the public RIS formula pattern. The app also mentions Wilks, DOTS and IPF GL as examples of strength-sport coefficient systems used to compare athletes with different bodyweights. In this demo, UPPER is not official RIS - it is an ATHENA product extension for pull-up + dip testing.

## New feature to mention

ATHENA is not only a gym set logger. It has a flexible exercise model. For example, bench press uses weight and reps, plank uses time, treadmill uses time and distance, and sprint intervals use rounds with work/rest time. This makes it closer to a real training tracker.


## New presentation points

- The tracker is no longer only a CRUD app. It behaves like a small Training OS.
- The user can import data from Hevy, log workouts manually, start a workout from a routine, monitor bodyweight, calculate RIS, see PRs, track consistency and inspect progress per exercise.
- Exercise types support strength, bodyweight, timed, distance, cardio, interval and mobility work.
- Session Score gives a single post-workout quality signal from readiness, focus, fatigue, mood and duration.

## Latest UI polish notes

In the newest version, ATHENA was simplified visually so that every screen has a clear purpose. Workouts now use a compact timeline and compact heatmap, Search has a cleaner modern search bar, Analytics contains hover details and a lightweight 3D anatomy model for muscle distribution. Exercise Library graphics were replaced with unified simple movement cards.

## Latest presentation highlights

- Workouts are now shown as a clean timeline/list instead of a large heatmap-first view.
- Global search works like a command palette: click the magnifier or press Ctrl+K.
- Analytics uses a simple anatomical muscle map to show trained body regions.
- Demo data contains many workouts, wellness entries and exercise types, so the presentation looks like a used product.


## Latest polish update
- Removed the rough anatomical map and kept analytics as clean, separate modern UI modules.
- Added editable goals: change values, target, status, notes, complete or reopen goals.
- Personal Records now link to the exact workout where the record was achieved.
- Exercise Library now uses one unified ATHENA exercise lab SVG placeholder across all exercises.

## New product features to mention

- Ctrl+K opens the command palette.
- Dashboard now has athlete level, readiness, consistency and quick-start training.
- Each workout can be opened as an editable log, replayed as a timeline, or compared with the previous same-named workout.
- RIS has a separate history screen, so the calculator is not just a one-time form.
- Bodyweight is treated as a first-class metric and can come from Hevy body measurements.
- Templates Marketplace makes the project feel like a finished training product instead of a basic CRUD app.
- Coaching Module communicates the future option to train under someone or become a coach inside ATHENA.

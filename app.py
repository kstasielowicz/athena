from __future__ import annotations
import os, sqlite3, datetime, uuid, math
from pathlib import Path
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
try:
    import requests
except Exception:
    requests = None

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / 'athena_tracker.db'
UPLOAD_DIR = BASE_DIR / 'static' / 'uploads'
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_IMAGE_EXT = {'png','jpg','jpeg','webp','gif','svg'}

app = Flask(__name__)
app.secret_key = 'athena-demo-secret'
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024

MUSCLES = ['Chest','Back','Shoulders','Biceps','Triceps','Legs','Glutes','Core','Full Body']
MOODS = ['Excellent','Good','Neutral','Low','Stressed']
SEXES = ['Men','Women']
DIFFICULTY = ['Beginner','Intermediate','Advanced']
EXERCISE_TYPES = ['Strength','Bodyweight','Timed','Distance','Cardio','Interval','Mobility','Custom']
RPE_TO_RIR = {
    10.0: 0, 9.5: 0.5, 9.0: 1, 8.5: 1.5, 8.0: 2,
    7.5: 2.5, 7.0: 3, 6.5: 3.5, 6.0: 4, 5.0: 5
}


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def q(sql, params=(), one=False, commit=False):
    with db() as conn:
        cur = conn.execute(sql, params)
        if commit:
            conn.commit()
        return (cur.fetchone() if one else cur.fetchall())


def insert(sql, params=()):
    with db() as conn:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid

def calculate_e1rm(weight: float, reps: int, rpe: float | None) -> float:
    """Oblicza szacowany 1RM (Estimated One-Rep Max) przy użyciu formuły Brzyckiego."""
    if not weight or not reps or weight <= 0 or reps <= 0:
        return 0.0
    effective_rpe = float(rpe) if rpe is not None else 10.0
    rir = RPE_TO_RIR.get(effective_rpe, max(0, int(10.0 - effective_rpe)))
    effective_reps = reps + rir
    if effective_reps > 30:
        return float(weight)
    e1rm = weight / (1.0278 - (0.0278 * effective_reps))
    return round(e1rm, 1)

def calculate_acwr_status() -> dict:
    """Oblicza Acute-to-Chronic Workload Ratio (ACWR) na podstawie objętości treningowej."""
    today = datetime.date.today()
    acute_start = (today - datetime.timedelta(days=7)).isoformat()
    chronic_start = (today - datetime.timedelta(days=28)).isoformat()
    sql_volume = """
        SELECT w.date, SUM(CASE WHEN e.exercise_type='Bodyweight' 
                            THEN (ws.additional_weight * ws.reps) 
                            ELSE (ws.weight * ws.reps) END) as daily_vol
        FROM workouts w
        JOIN workout_exercises we ON we.workout_id = w.id
        JOIN workout_sets ws ON ws.workout_exercise_id = we.id
        JOIN exercises e ON e.id = we.exercise_id
        WHERE w.date >= ?
        GROUP BY w.date
    """
    rows = q(sql_volume, (chronic_start,))
    acute_total = 0.0
    chronic_total = 0.0
    for r in rows:
        vol = float(r['daily_vol'] or 0.0)
        chronic_total += vol
        if r['date'] >= acute_start:
            acute_total += vol
    acute_workload = acute_total / 7.0
    chronic_workload = chronic_total / 28.0
    if chronic_workload <= 0:
        return {'ratio': 1.0, 'status': 'Optimal', 'text': 'Zbuduj bazę danych, aby aktywować ACWR.', 'tone': 'neutral'}
    ratio = round(acute_workload / chronic_workload, 2)
    if ratio < 0.8:
        status = 'Under-training'; tone = 'amber'
        text = f'Too low workload ({ratio}). You are at risk of losing adaptations. You can safely increase volume.'
    elif 0.8 <= ratio <= 1.3:
        status = 'Optimal'; tone = 'good'
        text = f'Sweet Spot ({ratio}). Load is perfectly balanced for progress and injury prevention.'
    elif 1.3 < ratio <= 1.5:
        status = 'High Load'; tone = 'warning'
        text = f'High Load ({ratio}). You are close to the injury risk zone. Monitor recovery.'
    else:
        status = 'Danger Zone'; tone = 'danger'
        text = f'Critical overload ({ratio}!). Drastically higher risk of injury. Recommended immediate deload.'
    return {'ratio': ratio, 'status': status, 'text': text, 'tone': tone}

def get_xp_for_level(level: int) -> int:
    if level <= 1: return 0
    return int(round(200 * math.pow(level - 1, 1.4)))

def get_level_from_xp(total_xp: int) -> dict:
    lvl = 1
    while True:
        needed = get_xp_for_level(lvl + 1)
        if total_xp < needed: break
        lvl += 1
    current_lvl_base = get_xp_for_level(lvl)
    next_lvl_base = get_xp_for_level(lvl + 1)
    xp_in_level = total_xp - current_lvl_base
    xp_needed_for_next = next_lvl_base - current_lvl_base
    pct = round((xp_in_level / max(1, xp_needed_for_next)) * 100) if xp_needed_for_next > 0 else 100
    return {'level': lvl, 'xp_in_level': xp_in_level, 'xp_needed_for_next': xp_needed_for_next, 'pct': min(100, pct), 'remaining_xp': max(0, next_lvl_base - total_xp)}



def clean_int(value, default=None, min_value=None, max_value=None):
    try:
        if value is None or value == '':
            return default
        n = int(round(float(value)))
        if min_value is not None:
            n = max(min_value, n)
        if max_value is not None:
            n = min(max_value, n)
        return n
    except (TypeError, ValueError):
        return default


def clean_rpe(value):
    return clean_int(value, default=None, min_value=1, max_value=10)


def table_columns(conn, table):
    return {row['name'] for row in conn.execute(f'PRAGMA table_info({table})')}


def add_col(conn, table, col, ddl):
    if col not in table_columns(conn, table):
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {col} {ddl}')


def init_db():
    with db() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS exercises(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            muscle_group TEXT NOT NULL,
            equipment TEXT NOT NULL DEFAULT 'Barbell',
            notes TEXT DEFAULT '',
            is_custom INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS routines(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            goal TEXT,
            intensity TEXT,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS routine_exercises(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            routine_id INTEGER,
            exercise_id INTEGER,
            planned_sets INTEGER,
            target_reps TEXT,
            rest_seconds INTEGER DEFAULT 120,
            order_index INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS workouts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            date TEXT NOT NULL,
            routine_id INTEGER,
            source TEXT DEFAULT 'ATHENA',
            duration_min INTEGER DEFAULT 60,
            bodyweight REAL,
            readiness INTEGER DEFAULT 7,
            mood TEXT DEFAULT 'Good',
            notes TEXT DEFAULT '',
            hevy_id TEXT
        );
        CREATE TABLE IF NOT EXISTS workout_exercises(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workout_id INTEGER,
            exercise_id INTEGER,
            order_index INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS workout_sets(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workout_exercise_id INTEGER,
            set_number INTEGER,
            weight REAL,
            reps INTEGER,
            rpe REAL,
            set_type TEXT DEFAULT 'Working',
            notes TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS wellness(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            bodyweight REAL,
            sleep_hours REAL,
            energy INTEGER,
            soreness INTEGER,
            stress INTEGER,
            mood TEXT,
            notes TEXT
        );
        CREATE TABLE IF NOT EXISTS ris_tests(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            sex TEXT NOT NULL DEFAULT 'Men',
            bodyweight REAL NOT NULL,
            total REAL NOT NULL,
            ris_score REAL NOT NULL,
            category TEXT,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS athlete_profile(
            id INTEGER PRIMARY KEY CHECK(id=1), name TEXT DEFAULT 'ATHENA Athlete', experience TEXT DEFAULT 'Intermediate', primary_goal TEXT DEFAULT 'Build strength and consistency',
            height_cm REAL, weight_kg REAL, body_fat REAL, bench REAL DEFAULT 0, squat REAL DEFAULT 0, deadlift REAL DEFAULT 0, pullup REAL DEFAULT 0, dip REAL DEFAULT 0, muscleup REAL DEFAULT 0,
            coach_status TEXT DEFAULT 'Solo training', notes TEXT DEFAULT '', updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS programs(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, goal TEXT DEFAULT '', duration_weeks INTEGER DEFAULT 4, status TEXT DEFAULT 'Draft', notes TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS program_days(id INTEGER PRIMARY KEY AUTOINCREMENT, program_id INTEGER NOT NULL, week_number INTEGER DEFAULT 1, day_name TEXT DEFAULT 'Monday', routine_id INTEGER, focus TEXT DEFAULT '', notes TEXT DEFAULT '');

        ''')
        # migrations for older demo databases
        add_col(conn, 'exercises', 'image_path', "TEXT DEFAULT ''")
        add_col(conn, 'exercises', 'description', "TEXT DEFAULT ''")
        add_col(conn, 'exercises', 'difficulty', "TEXT DEFAULT 'Intermediate'")
        add_col(conn, 'exercises', 'primary_muscle', "TEXT DEFAULT ''")
        add_col(conn, 'exercises', 'secondary_muscles', "TEXT DEFAULT ''")
        add_col(conn, 'exercises', 'instructions', "TEXT DEFAULT ''")
        add_col(conn, 'exercises', 'cues', "TEXT DEFAULT ''")
        add_col(conn, 'exercises', 'common_mistakes', "TEXT DEFAULT ''")
        add_col(conn, 'exercises', 'ris_tag', "TEXT DEFAULT 'Strength'")
        add_col(conn, 'exercises', 'exercise_type', "TEXT DEFAULT 'Strength'")
        add_col(conn, 'exercises', 'metric_hint', "TEXT DEFAULT 'Weight + reps'")
        add_col(conn, 'exercises', 'media_url', "TEXT DEFAULT ''")
        add_col(conn, 'exercises', 'movement_pattern', "TEXT DEFAULT ''")
        add_col(conn, 'exercises', 'athena_identity', "TEXT DEFAULT 'Performance Engine movement'")
        add_col(conn, 'workout_sets', 'additional_weight', "REAL DEFAULT 0")
        add_col(conn, 'workout_sets', 'duration_seconds', "INTEGER DEFAULT 0")
        add_col(conn, 'workout_sets', 'distance_m', "REAL DEFAULT 0")
        add_col(conn, 'workout_sets', 'calories', "REAL DEFAULT 0")
        add_col(conn, 'workout_sets', 'avg_hr', "INTEGER DEFAULT 0")
        add_col(conn, 'workout_sets', 'rounds', "INTEGER DEFAULT 0")
        add_col(conn, 'workout_sets', 'work_seconds', "INTEGER DEFAULT 0")
        add_col(conn, 'workout_sets', 'rest_seconds', "INTEGER DEFAULT 0")
        add_col(conn, 'workouts', 'fatigue', "INTEGER DEFAULT 4")
        add_col(conn, 'workouts', 'focus', "INTEGER DEFAULT 7")
        add_col(conn, 'ris_tests', 'ris_type', "TEXT DEFAULT 'ALL-4'")
        add_col(conn, 'ris_tests', 'pullup', "REAL DEFAULT 0")
        add_col(conn, 'ris_tests', 'dip', "REAL DEFAULT 0")
        add_col(conn, 'ris_tests', 'squat', "REAL DEFAULT 0")
        add_col(conn, 'ris_tests', 'muscleup', "REAL DEFAULT 0")
        add_col(conn, 'routine_exercises', 'superset_group', "TEXT DEFAULT ''")
        add_col(conn, 'workout_exercises', 'superset_group', "TEXT DEFAULT ''")
        add_col(conn, 'workout_exercises', 'target_notes', "TEXT DEFAULT ''")
        add_col(conn, 'workout_sets', 'estimated_1rm', "REAL DEFAULT 0.0")
        add_col(conn, 'athlete_profile', 'talent_points', "INTEGER DEFAULT 0")
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS exercise_favorites(exercise_id INTEGER PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS exercise_recent(id INTEGER PRIMARY KEY AUTOINCREMENT, exercise_id INTEGER NOT NULL, context TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS exercise_substitutions(id INTEGER PRIMARY KEY AUTOINCREMENT, exercise_id INTEGER NOT NULL, substitute_id INTEGER NOT NULL, note TEXT DEFAULT '', UNIQUE(exercise_id, substitute_id));
        CREATE TABLE IF NOT EXISTS exercise_checklists(id INTEGER PRIMARY KEY AUTOINCREMENT, exercise_id INTEGER NOT NULL, item_order INTEGER DEFAULT 1, cue TEXT NOT NULL, completed_default INTEGER DEFAULT 0);
        ''')
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS exercise_tags(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT UNIQUE NOT NULL);
        CREATE TABLE IF NOT EXISTS exercise_tag_map(exercise_id INTEGER NOT NULL,tag_id INTEGER NOT NULL,UNIQUE(exercise_id, tag_id));
        CREATE TABLE IF NOT EXISTS goals(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,metric TEXT NOT NULL,target REAL NOT NULL,current REAL DEFAULT 0,unit TEXT DEFAULT '',notes TEXT DEFAULT '',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS achievements(id INTEGER PRIMARY KEY AUTOINCREMENT,code TEXT UNIQUE NOT NULL,title TEXT NOT NULL,description TEXT NOT NULL,unlocked_at TEXT);
        ''')
        add_col(conn, 'goals', 'status', "TEXT DEFAULT 'Active'")
        add_col(conn, 'goals', 'completed_at', "TEXT DEFAULT ''")
        add_col(conn, 'programs', 'phase_model', "TEXT DEFAULT 'Foundation / Build / Peak / Deload'")
        add_col(conn, 'program_days', 'phase', "TEXT DEFAULT 'Build'")
        add_col(conn, 'program_days', 'intensity_target', "TEXT DEFAULT 'RPE 7-8'")
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS xp_events(id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT DEFAULT CURRENT_TIMESTAMP, source TEXT NOT NULL, points INTEGER NOT NULL, note TEXT DEFAULT '');

        CREATE TABLE IF NOT EXISTS athlete_skills(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            category TEXT DEFAULT 'Strength Skill',
            current_level INTEGER DEFAULT 1,
            target_level INTEGER DEFAULT 5,
            progress INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS skill_steps(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_id INTEGER NOT NULL,
            step_order INTEGER DEFAULT 1,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            completed INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS quests(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            quest_type TEXT DEFAULT 'Weekly',
            target INTEGER DEFAULT 1,
            current INTEGER DEFAULT 0,
            xp_reward INTEGER DEFAULT 50,
            status TEXT DEFAULT 'Active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS exercise_progressions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exercise_id INTEGER NOT NULL,
            step_order INTEGER DEFAULT 1,
            title TEXT NOT NULL,
            description TEXT DEFAULT ''
        );

        ''')
        add_col(conn, 'skill_steps', 'evidence_image_path', "TEXT DEFAULT ''")
        add_col(conn, 'skill_steps', 'evidence_note', "TEXT DEFAULT ''")
        add_col(conn, 'skill_steps', 'evidence_at', "TEXT DEFAULT ''")
        add_col(conn, 'achievements', 'category', "TEXT DEFAULT 'General'")
        add_col(conn, 'achievements', 'icon', "TEXT DEFAULT '◆'")
        add_col(conn, 'achievements', 'xp_reward', "INTEGER DEFAULT 50")
        add_col(conn, 'quests', 'auto_rule', "TEXT DEFAULT ''")
        add_col(conn, 'quests', 'auto_complete', "INTEGER DEFAULT 1")
        add_col(conn, 'athlete_profile', 'preferred_name', "TEXT DEFAULT ''")
        add_col(conn, 'athlete_profile', 'training_age_years', "REAL DEFAULT 0")
        add_col(conn, 'athlete_profile', 'weekly_target', "INTEGER DEFAULT 4")
        add_col(conn, 'athlete_profile', 'equipment', "TEXT DEFAULT 'Gym + bodyweight'")
        add_col(conn, 'athlete_profile', 'training_focus', "TEXT DEFAULT 'Strength + skill'")
        add_col(conn, 'athlete_profile', 'skill_focus', "TEXT DEFAULT 'Muscle Up'")
        add_col(conn, 'athlete_profile', 'recovery_priority', "TEXT DEFAULT 'Sleep + fatigue management'")
        add_col(conn, 'athlete_profile', 'avatar_path', "TEXT DEFAULT ''")
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS onboarding_settings(
            id INTEGER PRIMARY KEY CHECK(id=1),
            completed INTEGER DEFAULT 0,
            primary_goal TEXT DEFAULT 'Strength',
            experience TEXT DEFAULT 'Intermediate',
            training_days INTEGER DEFAULT 4,
            equipment TEXT DEFAULT 'Gym + bodyweight',
            preferred_style TEXT DEFAULT 'Strength + skill',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS weekly_checkins(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start TEXT NOT NULL,
            sleep_quality INTEGER DEFAULT 7,
            stress INTEGER DEFAULT 4,
            soreness INTEGER DEFAULT 4,
            motivation INTEGER DEFAULT 7,
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS dashboard_widgets(
            id INTEGER PRIMARY KEY CHECK(id=1),
            widgets TEXT DEFAULT 'ris,recovery,compliance,bodyweight,level,streak'
        );
        ''')
        conn.execute("INSERT OR IGNORE INTO onboarding_settings(id,completed,primary_goal,experience,training_days,equipment,preferred_style) VALUES(1,0,'Strength','Intermediate',4,'Gym + bodyweight','Strength + skill')")
        conn.execute("INSERT OR IGNORE INTO dashboard_widgets(id,widgets) VALUES(1,'ris,recovery,compliance,bodyweight,level,streak')")
        conn.execute("INSERT OR IGNORE INTO athlete_profile(id,name,experience,primary_goal,height_cm,weight_kg,notes) VALUES(1,'ATHENA Athlete','Intermediate','Increase strength, consistency and readiness',180,80,'Edit this profile to turn ATHENA into a personal athlete command center.')")
        conn.execute("UPDATE athlete_profile SET preferred_name=CASE WHEN instr(trim(name),' ')>0 THEN substr(trim(name),1,instr(trim(name),' ')-1) ELSE trim(name) END, weekly_target=COALESCE(NULLIF(weekly_target,0),4), equipment=COALESCE(NULLIF(equipment,''),'Gym + bodyweight'), training_focus=COALESCE(NULLIF(training_focus,''),'Strength + skill') WHERE id=1")
        if not conn.execute('SELECT id FROM programs LIMIT 1').fetchone():
            conn.execute("INSERT INTO programs(name,goal,duration_weeks,status,notes) VALUES('ATHENA Foundation Block','Build repeatable weekly training structure',4,'Draft','Starter 4-week block. Attach routines to each training day.')")
            pid=conn.execute('SELECT id FROM programs ORDER BY id DESC LIMIT 1').fetchone()['id']
            routines=conn.execute('SELECT id,name FROM routines ORDER BY id LIMIT 4').fetchall()
            for i,day in enumerate(['Monday','Tuesday','Thursday','Friday']):
                rid=routines[i % len(routines)]['id'] if routines else None
                conn.execute('INSERT INTO program_days(program_id,week_number,day_name,routine_id,focus,notes) VALUES(?,?,?,?,?,?)',(pid,1,day,rid,'Strength / skill','Starter day - connect to routine and execute.'))
        conn.commit()
        seed_if_empty(conn)
        ensure_exercise_types(conn)
        seed_product_extensions(conn)
        seed_performance_os(conn)
        seed_extended_demo_data(conn)
        seed_premium_marketplace(conn)

        # Make sure the starter program has days after demo routines are seeded.
        starter=conn.execute("SELECT id FROM programs WHERE name='ATHENA Foundation Block' LIMIT 1").fetchone()
        if starter and not conn.execute('SELECT id FROM program_days WHERE program_id=? LIMIT 1',(starter['id'],)).fetchone():
            routines=conn.execute('SELECT id,name FROM routines ORDER BY id LIMIT 4').fetchall()
            for i,day in enumerate(['Monday','Tuesday','Thursday','Friday']):
                rid=routines[i % len(routines)]['id'] if routines else None
                conn.execute('INSERT INTO program_days(program_id,week_number,day_name,routine_id,focus,notes) VALUES(?,?,?,?,?,?)',(starter['id'],1,day,rid,'Strength / skill','Starter day - connect to routine and execute.'))
            conn.commit()


def ensure_exercise_types(conn):
    updates = {
        'Bench Press': ('Strength','Weight + reps'), 'Squat': ('Strength','Weight + reps'), 'Romanian Deadlift': ('Strength','Weight + reps'), 'Overhead Press': ('Strength','Weight + reps'), 'Lat Pulldown': ('Strength','Weight + reps'), 'Dumbbell Curl': ('Strength','Weight + reps'),
        'Pull Up': ('Bodyweight','Additional weight + reps'), 'Dip': ('Bodyweight','Additional weight + reps'), 'Muscle Up': ('Bodyweight','Additional weight + reps'), 'Plank': ('Timed','Duration seconds'), 'Treadmill Run': ('Cardio','Duration + distance + calories + heart rate'), 'Rowing Machine': ('Cardio','Duration + distance + calories + heart rate'), 'Farmer Walk': ('Distance','Load + distance'), 'Sprint Intervals': ('Interval','Rounds + work/rest'), 'Mobility Flow': ('Mobility','Duration + notes'), 'Dead Hang': ('Timed','Duration + optional added weight')
    }
    for name,(etype,hint) in updates.items():
        conn.execute('UPDATE exercises SET exercise_type=?, metric_hint=? WHERE name=?',(etype,hint,name))
    extras = [
        ('Dip','Chest','Bodyweight','Bodyweight','Additional weight + reps','img/dip.svg','Core streetlifting push movement for triceps, chest and anterior delts.','Advanced','Triceps','Chest, shoulders','Start locked out, descend below parallel if pain-free, press to full lockout.','Ribs down; elbows controlled; clean lockout.','Short range, swinging, shoulder dump.','Relative Strength'),
        ('Treadmill Run','Full Body','Treadmill','Cardio','Duration + distance + calories + heart rate','img/treadmill.svg','Cardio movement tracked by time, distance, calories and average heart rate.','Beginner','Cardiovascular system','Calves, quads, glutes','Choose pace, keep stable cadence, record distance and time.','Tall posture; relaxed arms; smooth breathing.','Starting too fast, holding rails, skipping warm-up.','Cardio'),
        ('Rowing Machine','Full Body','Machine','Cardio','Duration + distance + calories + heart rate','img/rowing.svg','Full-body conditioning exercise using distance and duration metrics.','Intermediate','Cardiovascular system','Back, legs, arms','Drive with legs, swing body, pull handle, recover in reverse order.','Legs-body-arms; long strokes; steady breathing.','Pulling too early, rounded back, rushing recovery.','Cardio'),
        ('Farmer Walk','Full Body','Dumbbells','Distance','Load + distance','img/farmer_walk.svg','Loaded carry focused on grip, trunk stiffness and gait quality.','Intermediate','Grip and traps','Core, glutes, calves','Pick up handles, stand tall, walk controlled distance, avoid leaning.','Tall chest; crush handles; short stable steps.','Rushing, leaning, soft brace.','Carry'),
        ('Sprint Intervals','Full Body','Track','Interval','Rounds + work/rest','img/sprint.svg','High-intensity interval work tracked with rounds and work/rest seconds.','Advanced','Power output','Hamstrings, glutes, calves','Warm up well, sprint for planned work interval, recover fully.','Explosive start; relaxed face; crisp contacts.','No warm-up, too much volume, poor recovery.','Conditioning'),
        ('Mobility Flow','Full Body','Mat','Mobility','Duration + notes','img/mobility.svg','Recovery-oriented mobility block tracked mainly by duration and notes.','Beginner','Joints and tissues','Full body','Move through selected drills, breathe slowly, note restrictions.','Slow breathing; no pain; controlled positions.','Forcing range, bouncing, rushing.','Recovery'),
        ('Dead Hang','Back','Bodyweight','Timed','Duration + optional added weight','img/dead_hang.svg','Timed grip and shoulder decompression drill.','Beginner','Grip','Lats, shoulders','Hang from bar with active or passive shoulder position and record time.','Long neck; steady breathing; controlled exit.','Dropping suddenly, shrugging aggressively, pain tolerance.','Grip')
    ]
    for e in extras:
        if not conn.execute('SELECT id FROM exercises WHERE name=?',(e[0],)).fetchone():
            conn.execute('''INSERT INTO exercises(name,muscle_group,equipment,exercise_type,metric_hint,image_path,description,difficulty,primary_muscle,secondary_muscles,instructions,cues,common_mistakes,ris_tag,is_custom,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,'')''', e)
    conn.commit()


def tag_names_for_exercise(conn, eid):
    return [r['name'] for r in conn.execute("SELECT t.name FROM exercise_tags t JOIN exercise_tag_map m ON m.tag_id=t.id WHERE m.exercise_id=? ORDER BY t.name", (eid,))]


def set_exercise_tags(conn, eid, tag_text):
    tags = [x.strip() for x in (tag_text or '').replace(';', ',').split(',') if x.strip()]
    conn.execute('DELETE FROM exercise_tag_map WHERE exercise_id=?',(eid,))
    for name in tags:
        conn.execute('INSERT OR IGNORE INTO exercise_tags(name) VALUES(?)',(name,))
        tid = conn.execute('SELECT id FROM exercise_tags WHERE name=?',(name,)).fetchone()['id']
        conn.execute('INSERT OR IGNORE INTO exercise_tag_map(exercise_id,tag_id) VALUES(?,?)',(eid,tid))


def seed_product_extensions(conn):
    base_tags = ['Strength','Hypertrophy','Cardio','Mobility','Core','Calisthenics','Streetlifting','Recovery','Conditioning','Power','Carry','Grip','Back','Chest','Legs','Timed']
    for t in base_tags:
        conn.execute('INSERT OR IGNORE INTO exercise_tags(name) VALUES(?)',(t,))
    mappings = {
        'Pull Up':['Calisthenics','Streetlifting','Strength','Back'], 'Dip':['Calisthenics','Streetlifting','Strength','Chest'],
        'Squat':['Strength','Legs','Power'], 'Bench Press':['Strength','Hypertrophy','Chest'], 'Plank':['Core','Timed','Recovery'],
        'Treadmill Run':['Cardio','Conditioning'], 'Rowing Machine':['Cardio','Conditioning','Full Body'], 'Farmer Walk':['Carry','Grip','Core'],
        'Sprint Intervals':['Conditioning','Power'], 'Mobility Flow':['Mobility','Recovery'], 'Dead Hang':['Grip','Calisthenics','Timed']
    }
    for ex, tags in mappings.items():
        row = conn.execute('SELECT id FROM exercises WHERE name=?',(ex,)).fetchone()
        if row and not tag_names_for_exercise(conn,row['id']):
            set_exercise_tags(conn,row['id'], ', '.join(tags))
    if not conn.execute('SELECT id FROM goals LIMIT 1').fetchone():
        conn.execute('INSERT INTO goals(title,metric,target,current,unit,notes) VALUES(?,?,?,?,?,?)',('Weighted Pull-up +70','Pull Up',70,60,'kg','Streetlifting goal'))
        conn.execute('INSERT INTO goals(title,metric,target,current,unit,notes) VALUES(?,?,?,?,?,?)',('RIS 80 UPPER','RIS UPPER',80,66,'pts','Upper body benchmark'))
    conn.commit()


def session_score_value(w):
    readiness = float(w['readiness'] or 5); focus = float(w['focus'] or 5); fatigue = float(w['fatigue'] or 5)
    mood_map = {'Excellent':10,'Good':8,'Neutral':6,'Low':4,'Stressed':3}; mood = mood_map.get(w['mood'] or 'Neutral',6)
    duration = min(float(w['duration_min'] or 0)/90*10, 10)
    score = readiness*3.5 + focus*2.5 + (10-fatigue)*2.0 + mood*1.5 + duration*.5
    return max(0, min(100, round(score,1)))


def heatmap_data(days=126):
    start = datetime.date.today() - datetime.timedelta(days=days-1)
    counts = {r['date']: r['c'] for r in q('SELECT date, COUNT(*) c FROM workouts GROUP BY date')}
    return [{'date':(start+datetime.timedelta(days=i)).isoformat(),'count':int(counts.get((start+datetime.timedelta(days=i)).isoformat(),0)),'level':0 if int(counts.get((start+datetime.timedelta(days=i)).isoformat(),0))==0 else min(4,int(counts.get((start+datetime.timedelta(days=i)).isoformat(),0)))} for i in range(days)]


def muscle_volume_data():
    rows=q("""SELECT e.muscle_group, COALESCE(SUM(CASE WHEN e.exercise_type IN ('Cardio','Timed','Mobility') THEN ws.duration_seconds ELSE ws.weight*ws.reps + ws.additional_weight*ws.reps END),0) v FROM exercises e LEFT JOIN workout_exercises we ON we.exercise_id=e.id LEFT JOIN workout_sets ws ON ws.workout_exercise_id=we.id GROUP BY e.muscle_group ORDER BY v DESC""")
    maxv=max([r['v'] for r in rows] or [1]) or 1
    return [{'muscle':r['muscle_group'], 'volume':round(r['v'] or 0,1), 'pct':round((r['v'] or 0)/maxv*100)} for r in rows]


def bodyweight_series():
    return q('SELECT date, bodyweight FROM wellness WHERE bodyweight IS NOT NULL ORDER BY date ASC LIMIT 30')


def exercise_progress_rows(eid):
    return q("""SELECT w.date, w.name workout_name, e.name exercise_name, e.exercise_type, ws.* FROM workout_sets ws JOIN workout_exercises we ON we.id=ws.workout_exercise_id JOIN workouts w ON w.id=we.workout_id JOIN exercises e ON e.id=we.exercise_id WHERE e.id=? ORDER BY w.date ASC, ws.set_number ASC""",(eid,))


def metric_score(row):
    t=(row['exercise_type'] or 'Strength').lower()
    if t=='bodyweight': return (row['additional_weight'] or row['weight'] or 0)*(1+(row['reps'] or 0)/30)
    if t=='strength': return (row['weight'] or 0)*(1+(row['reps'] or 0)/30)
    if t in ('timed','mobility'): return row['duration_seconds'] or 0
    if t in ('cardio','distance'): return row['distance_m'] or 0
    if t=='interval': return (row['rounds'] or 0)*(row['work_seconds'] or 0)
    return (row['weight'] or 0)*(row['reps'] or 0)

def seed_premium_marketplace(conn):
    names={r['name'] for r in conn.execute('SELECT name FROM routines')}
    ex={r['name']:r['id'] for r in conn.execute('SELECT id,name FROM exercises')}
    templates=[
        ('ATHENA Lower', 'Strength / lower body', 'Medium', 'Squat, hinge and loaded carry template.', ['Squat','Romanian Deadlift','Farmer Walk','Mobility Flow']),
        ('ATHENA Full Body', 'General strength', 'Medium', 'Full-body session for balanced development.', ['Squat','Bench Press','Pull Up','Plank']),
        ('Street Workout Base', 'Calisthenics', 'Medium-High', 'Pull-up, dip, muscle-up and core emphasis.', ['Pull Up','Dip','Muscle Up','Dead Hang','Plank']),
        ('Conditioning Engine', 'Cardio / intervals', 'Medium', 'Treadmill, rowing and sprint interval template.', ['Treadmill Run','Rowing Machine','Sprint Intervals','Mobility Flow']),
    ]
    for name,goal,intensity,notes,items in templates:
        if name in names: continue
        rid=conn.execute('INSERT INTO routines(name,goal,intensity,notes) VALUES(?,?,?,?)',(name,goal,intensity,notes)).lastrowid
        for idx,item in enumerate(items,1):
            if item in ex:
                conn.execute('INSERT INTO routine_exercises(routine_id,exercise_id,planned_sets,target_reps,rest_seconds,order_index) VALUES(?,?,?,?,?,?)',(rid,ex[item],3,'6-10',90,idx))
    conn.commit()


def seed_if_empty(conn):
    count = conn.execute('SELECT COUNT(*) c FROM exercises').fetchone()['c']
    if count:
        return
    exercises = [
        dict(name='Bench Press', muscle_group='Chest', equipment='Barbell', image_path='img/bench_press.svg', difficulty='Intermediate', primary_muscle='Pectoralis major', secondary_muscles='Triceps, anterior delts', description='Main horizontal press for upper-body strength.', instructions='Lie on bench, set shoulder blades, lower bar under control to lower chest, press up while keeping feet planted.', cues='Shoulders packed; wrists stacked; controlled touch; drive through legs.', common_mistakes='Bouncing the bar, flared elbows, loose upper back.', ris_tag='Upper Strength'),
        dict(name='Pull Up', muscle_group='Back', equipment='Bodyweight', image_path='img/pull_up.svg', difficulty='Intermediate', primary_muscle='Latissimus dorsi', secondary_muscles='Biceps, rear delts, core', description='Vertical pull used for back strength and relative strength tracking.', instructions='Start from dead hang, pull chest toward bar, keep ribs down, lower under control.', cues='Pull elbows to ribs; long neck; full range.', common_mistakes='Half reps, swinging, shrugging shoulders.', ris_tag='Relative Strength'),
        dict(name='Squat', muscle_group='Legs', equipment='Barbell', image_path='img/squat.svg', difficulty='Advanced', primary_muscle='Quadriceps', secondary_muscles='Glutes, adductors, erectors', description='Primary lower-body compound movement.', instructions='Brace, descend with knees tracking toes, keep midfoot pressure, stand up with hips and chest rising together.', cues='Brace hard; knees forward and out; midfoot pressure.', common_mistakes='Good-morning out of the hole, collapsing knees, losing brace.', ris_tag='Lower Strength'),
        dict(name='Romanian Deadlift', muscle_group='Glutes', equipment='Barbell', image_path='img/rdl.svg', difficulty='Intermediate', primary_muscle='Hamstrings', secondary_muscles='Glutes, spinal erectors', description='Hinge movement for posterior-chain volume.', instructions='Soft knees, push hips back, keep bar close, stop when hamstrings limit range, extend hips to stand.', cues='Hips back; lats tight; feel hamstrings.', common_mistakes='Squatting the movement, rounded back, bar drifting forward.', ris_tag='Posterior Chain'),
        dict(name='Overhead Press', muscle_group='Shoulders', equipment='Barbell', image_path='img/ohp.svg', difficulty='Intermediate', primary_muscle='Deltoids', secondary_muscles='Triceps, upper chest, core', description='Main vertical press for shoulders and trunk stability.', instructions='Brace, press bar vertically, move head through after the bar passes forehead, lock out overhead.', cues='Glutes tight; ribs down; bar close.', common_mistakes='Overarching, bar drifting forward, soft lockout.', ris_tag='Upper Strength'),
        dict(name='Lat Pulldown', muscle_group='Back', equipment='Machine', image_path='img/lat_pulldown.svg', difficulty='Beginner', primary_muscle='Latissimus dorsi', secondary_muscles='Biceps, mid back', description='Controlled vertical pull alternative to pull-ups.', instructions='Grip bar, lean slightly back, pull elbows down, pause near upper chest, return slowly.', cues='Elbows down; chest tall; no momentum.', common_mistakes='Pulling behind neck, leaning too far, using arms only.', ris_tag='Hypertrophy'),
        dict(name='Dumbbell Curl', muscle_group='Biceps', equipment='Dumbbells', image_path='img/curl.svg', difficulty='Beginner', primary_muscle='Biceps brachii', secondary_muscles='Brachialis, forearms', description='Arm accessory for elbow flexion strength.', instructions='Keep elbows near torso, curl dumbbells up, squeeze, lower with control.', cues='Quiet elbows; full stretch; no swing.', common_mistakes='Using momentum, shortened range, wrists bending back.', ris_tag='Accessory'),
        dict(name='Plank', muscle_group='Core', equipment='Bodyweight', image_path='img/plank.svg', difficulty='Beginner', primary_muscle='Anterior core', secondary_muscles='Glutes, shoulders', description='Core stability drill for bracing capacity.', instructions='Elbows under shoulders, ribs down, glutes tight, hold neutral spine.', cues='Ribs down; squeeze glutes; breathe shallow.', common_mistakes='Hips sagging, holding breath, shoulders shrugged.', ris_tag='Core')
    ]
    for e in exercises:
        conn.execute('''INSERT INTO exercises(name,muscle_group,equipment,notes,is_custom,image_path,description,difficulty,primary_muscle,secondary_muscles,instructions,cues,common_mistakes,ris_tag)
                     VALUES(:name,:muscle_group,:equipment,:description,1,:image_path,:description,:difficulty,:primary_muscle,:secondary_muscles,:instructions,:cues,:common_mistakes,:ris_tag)''', e)
    conn.execute("INSERT INTO routines(name,goal,intensity,notes) VALUES(?,?,?,?)", ('ATHENA Upper Strength','Strength / upper body','Medium-High','Ready-to-log routine inspired by ATHENA workouts.'))
    rid = conn.execute('SELECT id FROM routines WHERE name=?', ('ATHENA Upper Strength',)).fetchone()['id']
    ids = {r['name']: r['id'] for r in conn.execute('SELECT id,name FROM exercises')}
    routine_rows=[(rid,ids['Bench Press'],4,'5-8',150,1),(rid,ids['Pull Up'],4,'6-10',120,2),(rid,ids['Overhead Press'],3,'6-8',120,3),(rid,ids['Lat Pulldown'],3,'10-12',90,4)]
    conn.executemany('INSERT INTO routine_exercises(routine_id,exercise_id,planned_sets,target_reps,rest_seconds,order_index) VALUES(?,?,?,?,?,?)', routine_rows)
    today = datetime.date.today()
    samples=[('Upper Strength Session', str(today-datetime.timedelta(days=2)), rid, 'ATHENA', 72, 82.4, 8, 'Good', 'Solid pressing session. Bar path felt stable.', 3, 8),('Lower Volume Session', str(today-datetime.timedelta(days=5)), None, 'ATHENA', 64, 82.7, 6, 'Neutral','Legs still sore, kept RPE controlled.', 6, 6)]
    for w in samples:
        conn.execute('INSERT INTO workouts(name,date,routine_id,source,duration_min,bodyweight,readiness,mood,notes,fatigue,focus) VALUES(?,?,?,?,?,?,?,?,?,?,?)', w)
    wid = conn.execute('SELECT id FROM workouts WHERE name=?', ('Upper Strength Session',)).fetchone()['id']
    for order, ex in enumerate(['Bench Press','Pull Up','Overhead Press'],1):
        we = conn.execute('INSERT INTO workout_exercises(workout_id,exercise_id,order_index) VALUES(?,?,?)',(wid,ids[ex],order)).lastrowid
        for sn, wt, reps, rpe in [(1,60,8,7),(2,65,6,8),(3,65,6,8.5)]:
            conn.execute('INSERT INTO workout_sets(workout_exercise_id,set_number,weight,reps,rpe) VALUES(?,?,?,?,?)',(we,sn,wt,reps,rpe))
    conn.execute('INSERT INTO wellness(date,bodyweight,sleep_hours,energy,soreness,stress,mood,notes) VALUES(?,?,?,?,?,?,?,?)',(str(today),82.3,7.5,8,3,4,'Good','Ready for moderate intensity.'))
    conn.commit()



def seed_extended_demo_data(conn):
    """Create a richer demo timeline so the product does not look empty during presentation."""
    existing = conn.execute("SELECT COUNT(*) c FROM workouts WHERE notes LIKE '%ATHENA demo seed%' OR notes LIKE '%Generated demo dataset%'").fetchone()['c']
    total = conn.execute('SELECT COUNT(*) c FROM workouts').fetchone()['c']
    if existing >= 18 or total >= 28:
        return
    ids = {r['name']: r['id'] for r in conn.execute('SELECT id,name FROM exercises')}
    routine_ids = {r['name']: r['id'] for r in conn.execute('SELECT id,name FROM routines')}
    today = datetime.date.today()
    templates = [
        ('ATHENA Upper Strength', ['Bench Press','Pull Up','Dip','Overhead Press'], 'Upper strength focus. Generated demo dataset.'),
        ('ATHENA Pull Capacity', ['Pull Up','Lat Pulldown','Dead Hang','Rowing Machine'], 'Back and grip capacity. Generated demo dataset.'),
        ('ATHENA Lower Base', ['Squat','Romanian Deadlift','Farmer Walk','Mobility Flow'], 'Lower body base and posterior chain. Generated demo dataset.'),
        ('ATHENA Conditioning', ['Treadmill Run','Sprint Intervals','Plank','Mobility Flow'], 'Conditioning and trunk stability. Generated demo dataset.'),
        ('ATHENA Push Volume', ['Bench Press','Dip','Overhead Press','Dumbbell Curl'], 'Pressing volume and accessory work. Generated demo dataset.'),
    ]
    moods = ['Good','Excellent','Neutral','Good','Low']
    for i in range(36):
        days_ago = 3 + i*4
        name, exlist, note = templates[i % len(templates)]
        date = (today - datetime.timedelta(days=days_ago)).isoformat()
        bw = round(88.0 - min(i,20)*0.08 + ((i%3)-1)*0.15, 1)
        readiness = 5 + (i % 5)
        fatigue = 3 + (i % 5)
        focus = 6 + (i % 4)
        mood = moods[i % len(moods)]
        rid = routine_ids.get('ATHENA Upper Strength') if 'Upper' in name else None
        cur = conn.execute('INSERT INTO workouts(name,date,routine_id,source,duration_min,bodyweight,readiness,mood,notes,fatigue,focus) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (name, date, rid, 'ATHENA', 48 + (i%5)*8, bw, readiness, mood, note, fatigue, focus))
        wid = cur.lastrowid
        for order, exname in enumerate(exlist, 1):
            if exname not in ids:
                continue
            weid = conn.execute('INSERT INTO workout_exercises(workout_id,exercise_id,order_index) VALUES(?,?,?)', (wid, ids[exname], order)).lastrowid
            etype = conn.execute('SELECT exercise_type FROM exercises WHERE id=?',(ids[exname],)).fetchone()['exercise_type']
            for sn in range(1, 4 if exname not in ['Treadmill Run','Mobility Flow','Sprint Intervals'] else 2):
                if etype == 'Strength':
                    base = {'Bench Press':80,'Squat':125,'Romanian Deadlift':105,'Overhead Press':50,'Lat Pulldown':70,'Dumbbell Curl':18}.get(exname,60)
                    weight = base + (i%6)*2 + sn*2
                    reps = max(3, 10 - sn - (i%3))
                    conn.execute('INSERT INTO workout_sets(workout_exercise_id,set_number,weight,reps,rpe,set_type,notes) VALUES(?,?,?,?,?,?,?)',(weid,sn,weight,reps,7+sn*.4,'Working','Demo set'))
                elif etype == 'Bodyweight':
                    add = {'Pull Up':35,'Dip':55}.get(exname,20) + (i%8)*2 + sn
                    reps = max(2, 8 - sn + (i%2))
                    conn.execute('INSERT INTO workout_sets(workout_exercise_id,set_number,weight,reps,additional_weight,rpe,set_type,notes) VALUES(?,?,?,?,?,?,?,?)',(weid,sn,0,reps,add,7+sn*.3,'Working','Demo weighted bodyweight set'))
                elif etype == 'Timed':
                    dur = {'Plank':80,'Dead Hang':55}.get(exname,60) + (i%7)*5 + sn*8
                    conn.execute('INSERT INTO workout_sets(workout_exercise_id,set_number,duration_seconds,additional_weight,rpe,set_type,notes) VALUES(?,?,?,?,?,?,?)',(weid,sn,dur,0,7,'Timed','Demo timed hold'))
                elif etype == 'Cardio':
                    dur = 900 + (i%8)*90
                    dist = 2200 + (i%8)*350
                    conn.execute('INSERT INTO workout_sets(workout_exercise_id,set_number,duration_seconds,distance_m,calories,avg_hr,rpe,set_type,notes) VALUES(?,?,?,?,?,?,?,?,?)',(weid,sn,dur,dist,180+(i%6)*25,138+(i%8),7,'Cardio','Demo cardio block'))
                elif etype == 'Distance':
                    conn.execute('INSERT INTO workout_sets(workout_exercise_id,set_number,weight,distance_m,rpe,set_type,notes) VALUES(?,?,?,?,?,?,?)',(weid,sn,34+(i%6)*4,30+sn*10,7,'Carry','Demo carry'))
                elif etype == 'Interval':
                    conn.execute('INSERT INTO workout_sets(workout_exercise_id,set_number,rounds,work_seconds,rest_seconds,rpe,set_type,notes) VALUES(?,?,?,?,?,?,?,?)',(weid,sn,6+(i%4),20,70,8,'Interval','Demo interval block'))
                else:
                    conn.execute('INSERT INTO workout_sets(workout_exercise_id,set_number,duration_seconds,rpe,set_type,notes) VALUES(?,?,?,?,?,?)',(weid,sn,600,5,'Mobility','Demo mobility work'))
        if i % 2 == 0:
            conn.execute('INSERT INTO wellness(date,bodyweight,sleep_hours,energy,soreness,stress,mood,notes) VALUES(?,?,?,?,?,?,?,?)',
                         (date, bw, round(6.5+(i%5)*.35,1), 5+(i%5), 3+(i%4), 3+(i%5), mood, 'ATHENA demo seed wellness entry.'))
    conn.commit()

def allowed_image(filename):
    return '.' in filename and filename.rsplit('.',1)[1].lower() in ALLOWED_IMAGE_EXT


def save_image(file):
    if not file or not file.filename or not allowed_image(file.filename):
        return ''
    name = secure_filename(file.filename)
    unique = f"{uuid.uuid4().hex[:8]}_{name}"
    file.save(UPLOAD_DIR / unique)
    return f'uploads/{unique}'


def stats():
    workouts = q('SELECT * FROM workouts ORDER BY date DESC')
    total_sets = q('SELECT COUNT(*) c FROM workout_sets', one=True)['c']
    total_volume = q('SELECT COALESCE(SUM(weight*reps),0) v FROM workout_sets', one=True)['v']
    last_weight = q('SELECT bodyweight FROM wellness WHERE bodyweight IS NOT NULL ORDER BY date DESC LIMIT 1', one=True)
    return dict(workouts=len(workouts), sets=total_sets, volume=round(total_volume,1), weight=(last_weight['bodyweight'] if last_weight else None))


RIS_PARAMS_2025 = {
    'Men': dict(A=338, K=549, B=0.11354, V=74.777, Q=0.53096),
    'Women': dict(A=164, K=270, B=0.13776, V=57.855, Q=0.37089),
}

# RIS is officially built for ALL-4 Streetlifting totals.
# UPPER is an ATHENA demo extension: the same logistic bodyweight curve is used,
# but the denominator is scaled to a two-lift pull-up + dip test.
UPPER_DENOMINATOR_SCALE = {'Men': 0.43, 'Women': 0.45}


def ris_denominator(sex, bodyweight, ris_type='ALL-4'):
    sex_key = 'Women' if (sex or '').lower().startswith('w') else 'Men'
    p = RIS_PARAMS_2025[sex_key]
    bw = float(bodyweight)
    denominator = p['A'] + (p['K'] - p['A']) / (1 + p['Q'] * math.exp(-p['B'] * (bw - p['V'])))
    if (ris_type or '').upper() == 'UPPER':
        denominator *= UPPER_DENOMINATOR_SCALE[sex_key]
    return denominator


def ris_score(sex, bodyweight, total, ris_type='ALL-4'):
    bw = float(bodyweight)
    ttl = float(total)
    if bw <= 0 or ttl <= 0:
        return 0
    return ttl * 100 / ris_denominator(sex, bw, ris_type)


def ris_category(score):
    score = float(score or 0)
    if score >= 115:
        return 'Elite'
    if score >= 100:
        return 'Advanced'
    if score >= 85:
        return 'Strong'
    if score >= 70:
        return 'Developing'
    return 'Foundation'


def training_advisor():
    latest = q('SELECT * FROM workouts ORDER BY date DESC LIMIT 1', one=True)
    latest_ris = q('SELECT * FROM ris_tests ORDER BY date DESC, id DESC LIMIT 1', one=True)
    if not latest:
        return dict(title='Build your baseline', text='Log your first ATHENA session, add bodyweight, then calculate RIS to create a starting performance profile.', tone='neutral')
    readiness = latest['readiness'] or 5
    fatigue = latest['fatigue'] or 5
    focus = latest['focus'] or 5
    if readiness >= 8 and fatigue <= 4:
        title = 'Green light session'
        text = 'Readiness is high and fatigue is controlled. Good day for progressive overload or a top set.'
        tone = 'green'
    elif fatigue >= 7 or readiness <= 4:
        title = 'Recovery-biased plan'
        text = 'Fatigue is elevated or readiness is low. Keep technique crisp, reduce load 5-10%, and avoid failure sets.'
        tone = 'amber'
    else:
        title = 'Standard build day'
        text = 'Run the planned routine, track RPE, and aim for stable volume rather than forcing a max.'
        tone = 'blue'
    if latest_ris:
        text += f" Latest RIS: {round(latest_ris['ris_score'],1)} ({latest_ris['category']})."
    return dict(title=title, text=text, tone=tone)

@app.context_processor
def inject():
    return dict(MUSCLES=MUSCLES, MOODS=MOODS, SEXES=SEXES, DIFFICULTY=DIFFICULTY, EXERCISE_TYPES=EXERCISE_TYPES, today=datetime.date.today().isoformat())



def set_display(set_row, exercise_type):
    t = (exercise_type or 'Strength').lower()
    if t == 'bodyweight':
        return f"+{set_row['additional_weight'] or set_row['weight'] or 0:g} kg x {set_row['reps'] or 0}"
    if t == 'timed':
        sec = int(set_row['duration_seconds'] or 0)
        return f"{sec//60}:{sec%60:02d} min" + (f" +{set_row['additional_weight']:g} kg" if set_row['additional_weight'] else '')
    if t in ('cardio','distance'):
        km = (set_row['distance_m'] or 0) / 1000
        sec = int(set_row['duration_seconds'] or 0)
        return f"{km:g} km / {sec//60}:{sec%60:02d}"
    if t == 'interval':
        return f"{set_row['rounds'] or 0} rounds - {set_row['work_seconds'] or 0}s/{set_row['rest_seconds'] or 0}s"
    if t == 'mobility':
        sec = int(set_row['duration_seconds'] or 0)
        return f"{sec//60}:{sec%60:02d} min"
    return f"{set_row['weight'] or 0:g} kg x {set_row['reps'] or 0}"

def personal_records(limit=20):
    rows = q("""SELECT e.name,e.exercise_type,ws.*,w.id as workout_id,w.name as workout_name,w.date as workout_date FROM workout_sets ws
                JOIN workout_exercises we ON we.id=ws.workout_exercise_id
                JOIN exercises e ON e.id=we.exercise_id
                JOIN workouts w ON w.id=we.workout_id""")
    best = {}
    for r in rows:
        t=(r['exercise_type'] or 'Strength').lower()
        if t == 'strength': score=(r['weight'] or 0)*(1+(r['reps'] or 0)/30)
        elif t == 'bodyweight': score=(r['additional_weight'] or r['weight'] or 0)*(1+(r['reps'] or 0)/30)
        elif t in ('timed','mobility'): score=r['duration_seconds'] or 0
        elif t in ('cardio','distance'): score=(r['distance_m'] or 0) - max(0,(r['duration_seconds'] or 0)/10)
        elif t == 'interval': score=(r['rounds'] or 0)*(r['work_seconds'] or 0)
        else: score=(r['weight'] or 0)*(r['reps'] or 0) + (r['duration_seconds'] or 0)
        if score <= 0: continue
        name=r['name']
        if name not in best or score > best[name]['score']:
            best[name]={'name':name,'type':r['exercise_type'],'score':score,'display':set_display(r, r['exercise_type']),'workout_id':r['workout_id'],'workout_name':r['workout_name'],'workout_date':r['workout_date']}
    return sorted(best.values(), key=lambda x:x['score'], reverse=True)[:limit]


def seed_performance_os(conn):
    """Seed ATHENA 9/10 identity modules without overwriting user data."""
    skills = [
        ('Muscle Up','Street Workout',3,5,60,'Explosive pull + transition skill.'),
        ('Front Lever','Static Skill',2,5,35,'Straight-arm pulling strength and core tension.'),
        ('Handstand','Balance Skill',2,5,40,'Inversion control, line and shoulder endurance.'),
        ('Planche','Static Skill',1,5,18,'Straight-arm pushing strength progression.'),
        ('Weighted Pull Up','Streetlifting',3,5,70,'Relative pulling strength benchmark.'),
    ]
    for name,cat,lvl,target,prog,notes in skills:
        conn.execute('INSERT OR IGNORE INTO athlete_skills(name,category,current_level,target_level,progress,notes) VALUES(?,?,?,?,?,?)',(name,cat,lvl,target,prog,notes))
    step_map = {
        'Muscle Up':['Strict pull-up base','Chest-to-bar pull','High pull transition','Band-assisted muscle up','Clean strict muscle up'],
        'Front Lever':['Tuck hold','Advanced tuck','One-leg front lever','Straddle front lever','Full front lever'],
        'Handstand':['Wall hold','Wall shoulder taps','Freestanding kick-up','10 sec freestanding hold','30 sec freestanding hold'],
        'Planche':['Planche lean','Tuck planche','Advanced tuck','Straddle planche','Full planche'],
        'Weighted Pull Up':['BW strict reps','+20 kg triple','+40 kg single','+60 kg single','+70 kg single'],
    }
    for skill, steps in step_map.items():
        row=conn.execute('SELECT id FROM athlete_skills WHERE name=?',(skill,)).fetchone()
        if row and not conn.execute('SELECT id FROM skill_steps WHERE skill_id=? LIMIT 1',(row['id'],)).fetchone():
            for i,title in enumerate(steps,1):
                conn.execute('INSERT INTO skill_steps(skill_id,step_order,title,description,completed) VALUES(?,?,?,?,?)',(row['id'],i,title,'Progression checkpoint for '+skill, 1 if i<=2 else 0))
    if not conn.execute('SELECT id FROM quests LIMIT 1').fetchone():
        quests=[
            ('Complete 3 training missions','Auto-completes when you log 3 workouts this week.','Weekly',3,0,120,'weekly_workouts'),
            ('Log readiness 5 times','Auto-completes after 5 wellness/readiness logs this week.','Weekly',5,0,80,'weekly_readiness'),
            ('Hit one progression target','Auto-completes after completing at least one skill step.','Performance',1,0,100,'skill_steps_completed'),
            ('Balance the week','Auto-completes when push, pull and lower-body patterns appear this week.','Weekly',3,0,100,'weekly_muscle_balance'),
            ('Upload skill evidence','Auto-completes when you attach evidence to a skill step.','Skills',1,0,80,'skill_evidence_uploads'),
            ('Run a weekly review','Auto-completes when this week has training data to review.','Weekly',1,0,60,'weekly_review_ready'),
        ]
        for qtitle,desc,qt,target,current,xp,rule in quests:
            conn.execute('INSERT INTO quests(title,description,quest_type,target,current,xp_reward,auto_rule,auto_complete) VALUES(?,?,?,?,?,?,?,1)',(qtitle,desc,qt,target,current,xp,rule))
    else:
        rule_map={
            'Complete 3 training missions':'weekly_workouts',
            'Log readiness 5 times':'weekly_readiness',
            'Hit one progression target':'skill_steps_completed',
            'Balance the week':'weekly_muscle_balance',
            'Upload skill evidence':'skill_evidence_uploads',
            'Run a weekly review':'weekly_review_ready',
        }
        for title,rule in rule_map.items():
            conn.execute("UPDATE quests SET auto_rule=?, auto_complete=1 WHERE title=? AND (auto_rule IS NULL OR auto_rule='')",(rule,title))
    progressions={
        'Pull Up':['Dead hang','Scapular pull-up','Negative pull-up','Strict pull-up','Weighted pull-up','Chest-to-bar pull-up','Muscle-up pull'],
        'Dip':['Support hold','Negative dip','Strict dip','Weighted dip','Deep weighted dip'],
        'Push Up':['Incline push-up','Strict push-up','Paused push-up','Ring push-up','Weighted push-up','Dip'],
        'Bench Press':['Tempo bench','Paused bench','Volume bench','Heavy top set','Competition-style single'],
        'Squat':['Goblet squat','Front squat pattern','Back squat volume','Heavy top set','Peak single'],
        'Muscle Up':['Strict pull-up base','Chest-to-bar','High pull','Transition drill','Band muscle-up','Strict muscle-up'],
    }
    for ex, steps in progressions.items():
        erow=conn.execute('SELECT id FROM exercises WHERE name=?',(ex,)).fetchone()
        if erow and not conn.execute('SELECT id FROM exercise_progressions WHERE exercise_id=? LIMIT 1',(erow['id'],)).fetchone():
            for i,title in enumerate(steps,1):
                conn.execute('INSERT INTO exercise_progressions(exercise_id,step_order,title,description) VALUES(?,?,?,?)',(erow['id'],i,title,'Suggested progression step for '+ex))
    conn.commit()


def recovery_series(days=30):
    rows=q('SELECT * FROM wellness ORDER BY date DESC LIMIT ?', (days,))
    out=[]
    for r in reversed(rows):
        sleep=float(r['sleep_hours'] or 7)
        energy=int(r['energy'] or 5); stress=int(r['stress'] or 5); soreness=int(r['soreness'] or 5)
        score=round((min(sleep,9)/9)*28 + (energy/10)*28 + ((10-stress)/10)*22 + ((10-soreness)/10)*22)
        out.append({'date':r['date'],'score':max(0,min(100,score)),'sleep':sleep,'energy':energy,'stress':stress,'soreness':soreness,'mood':r['mood']})
    return out


def plateau_detection():
    alerts=[]
    for ex in q("SELECT id,name,exercise_type FROM exercises WHERE exercise_type IN ('Strength','Bodyweight') ORDER BY name"):
        rows=exercise_progress_rows(ex['id'])
        if len(rows)<6: continue
        scores=[metric_score(r) for r in rows]
        early=max(scores[:-3] or [0]); recent=max(scores[-3:] or [0])
        if early>0 and recent <= early*1.01:
            alerts.append({'exercise':ex['name'],'title':'Plateau risk','text':'No meaningful increase across the latest sessions. Consider a variation, deload, or different rep target.','severity':'warning'})
    return alerts[:6]


def weak_point_detection():
    warnings=muscle_balance_warnings()
    extra=[]
    freq={r['muscle_group']:r['sessions'] for r in q('SELECT e.muscle_group, COUNT(DISTINCT we.workout_id) sessions FROM exercises e JOIN workout_exercises we ON we.exercise_id=e.id GROUP BY e.muscle_group')}
    if freq.get('Back',0)<freq.get('Chest',0):
        extra.append({'title':'Back frequency trails chest','text':'Add rows, pull-ups or rear-delt work to support shoulder balance.','level':'warning'})
    if freq.get('Legs',0)+freq.get('Glutes',0) < max(2, freq.get('Chest',0)//2):
        extra.append({'title':'Lower-body exposure is low','text':'Add squat, hinge, lunge or carry patterns in the weekly program.','level':'warning'})
    return warnings+extra[:3]


def mission_state():
    today=datetime.date.today().isoformat()
    today_workout=q('SELECT * FROM workouts WHERE date=? ORDER BY id DESC LIMIT 1',(today,),one=True)
    if not today_workout:
        today_workout=q('SELECT * FROM workouts ORDER BY date DESC LIMIT 1', one=True)
    objectives=[]
    if today_workout:
        exs=q('SELECT e.name, e.exercise_type, we.id weid FROM workout_exercises we JOIN exercises e ON e.id=we.exercise_id WHERE we.workout_id=? ORDER BY we.order_index LIMIT 5',(today_workout['id'],))
        for ex in exs:
            best=q('SELECT * FROM workout_sets WHERE workout_exercise_id=? ORDER BY set_number LIMIT 1',(ex['weid'],),one=True)
            objectives.append({'title':ex['name'], 'target': set_display(best,ex['exercise_type']) if best else 'Complete planned work', 'done': bool(best and ((best['reps'] or 0)>0 or (best['duration_seconds'] or 0)>0 or (best['distance_m'] or 0)>0))})
    return {'workout':today_workout,'objectives':objectives,'xp':50+len(objectives)*10}


def quest_live_current(row):
    """Return current progress for automatic quests. Manual quests still use stored current."""
    rule=(row['auto_rule'] if 'auto_rule' in row.keys() else '') or ''
    week_start=(datetime.date.today()-datetime.timedelta(days=datetime.date.today().weekday())).isoformat()
    if rule=='weekly_workouts':
        return q('SELECT COUNT(*) c FROM workouts WHERE date>=?',(week_start,),one=True)['c'] or 0
    if rule=='weekly_readiness':
        return q('SELECT COUNT(*) c FROM wellness WHERE date>=?',(week_start,),one=True)['c'] or 0
    if rule=='skill_steps_completed':
        return q('SELECT COUNT(*) c FROM skill_steps WHERE completed=1',one=True)['c'] or 0
    if rule=='skill_evidence_uploads':
        return q("SELECT COUNT(*) c FROM skill_steps WHERE COALESCE(evidence_image_path,'')<>'' OR COALESCE(evidence_note,'')<>''",one=True)['c'] or 0
    if rule=='weekly_muscle_balance':
        rows=q('SELECT DISTINCT e.muscle_group FROM workouts w JOIN workout_exercises we ON we.workout_id=w.id JOIN exercises e ON e.id=we.exercise_id WHERE w.date>=?',(week_start,))
        groups={r['muscle_group'] for r in rows}
        push=bool(groups & {'Chest','Shoulders','Triceps'})
        pull=bool(groups & {'Back','Biceps'})
        lower=bool(groups & {'Legs','Glutes'})
        return int(push)+int(pull)+int(lower)
    if rule=='weekly_review_ready':
        return 1 if (q('SELECT COUNT(*) c FROM workouts WHERE date>=?',(week_start,),one=True)['c'] or 0)>0 else 0
    title=(row['title'] or '').lower()
    if 'training missions' in title:
        return q('SELECT COUNT(*) c FROM workouts WHERE date>=?',(week_start,),one=True)['c'] or 0
    if 'readiness' in title:
        return q('SELECT COUNT(*) c FROM wellness WHERE date>=?',(week_start,),one=True)['c'] or 0
    return row['current'] or 0


def auto_update_quests():
    """Complete eligible automatic quests and award XP once."""
    today=datetime.date.today().isoformat()
    for row in q('SELECT * FROM quests WHERE status<>"Completed"'):
        live=quest_live_current(row)
        target=max(1, row['target'] or 1)
        auto=row['auto_complete'] if 'auto_complete' in row.keys() else 1
        if auto and live>=target:
            q('UPDATE quests SET status="Completed", current=?, completed_at=? WHERE id=?',(target,today,row['id']),commit=True)
            insert('INSERT INTO xp_events(source,points,note) VALUES(?,?,?)',('Auto Quest', row['xp_reward'] or 50, row['title']))
        elif live>(row['current'] or 0):
            q('UPDATE quests SET current=? WHERE id=?',(min(live,target),row['id']),commit=True)


def quest_state(auto_update=True):
    if auto_update:
        auto_update_quests()
    rows=[]
    for row in q('SELECT * FROM quests ORDER BY CASE WHEN status="Completed" THEN 1 ELSE 0 END, id'):
        current=max(row['current'] or 0, quest_live_current(row))
        target=max(1,row['target'] or 1)
        pct=min(100, round((current/target)*100))
        auto_rule=(row['auto_rule'] if 'auto_rule' in row.keys() else '') or ''
        rows.append(dict(row, live_current=current, pct=pct, is_auto=bool(auto_rule), auto_label=auto_rule.replace('_',' ').title() if auto_rule else 'Manual'))
    return rows

def rpg_attributes():
    prs=personal_records(999); workouts=q('SELECT COUNT(*) c FROM workouts',one=True)['c'] or 0
    recovery=athlete_intelligence()['recovery']
    try:
        skills=q('SELECT COALESCE(AVG(progress),0) v FROM athlete_skills',one=True)['v'] or 0
    except Exception:
        skills=0
    volume=q('SELECT COALESCE(SUM(weight*reps + additional_weight*reps),0) v FROM workout_sets',one=True)['v'] or 0
    return [
        {'name':'Strength','score':min(100, round(len(prs)*8 + volume/5000))},
        {'name':'Skill','score':round(skills)},
        {'name':'Recovery','score':recovery},
        {'name':'Consistency','score':min(100, consistency_engine(30)['last_30']*5)},
        {'name':'Power','score':min(100, workouts*3 + len([p for p in prs if 'Pull' in p['name'] or 'Dip' in p['name']])*10)},
    ]


def onboarding_state():
    row=q('SELECT * FROM onboarding_settings WHERE id=1', one=True)
    if not row:
        return {'completed':0,'primary_goal':'Strength','experience':'Intermediate','training_days':4,'equipment':'Gym + bodyweight','preferred_style':'Strength + skill'}
    return dict(row)


def first_name_from_profile(profile):
    if not profile:
        return 'Athlete'
    try:
        name = profile['name'] or 'Athlete'
    except Exception:
        name = 'Athlete'
    parts = str(name).strip().split()
    return parts[0] if parts else 'Athlete'


def smart_today_plan():
    ready=readiness_v2(); intel=athlete_intelligence(); comp=training_compliance(28); deload=deload_detection(); mission=mission_state()
    if deload['needed']:
        title='Deload recommended'; action='Reduce volume 30-50%, keep technique work, avoid maximal sets.'; tone='warning'
    elif ready['score']>=78 and intel['fatigue']<=5:
        title='Ready to push'; action='Run the planned session. One top set can be pushed to RPE 8-9 if warm-ups move well.'; tone='good'
    elif ready['score']>=58:
        title='Build, do not force'; action='Complete the session at planned RPE. Keep 1-3 reps in reserve and prioritize clean reps.'; tone='neutral'
    else:
        title='Recovery-biased day'; action='Use mobility, walking, light technique work or cut accessory volume.'; tone='danger'
    return {'title':title,'action':action,'tone':tone,'readiness':ready,'compliance':comp,'mission':mission,'deload':deload}


def week_bounds(offset=0):
    today=datetime.date.today()+datetime.timedelta(days=offset*7)
    start=today-datetime.timedelta(days=today.weekday()); end=start+datetime.timedelta(days=6)
    return start,end



def weekly_review_data():
    start,end=week_bounds()
    workouts=q('SELECT * FROM workouts WHERE date BETWEEN ? AND ? ORDER BY date',(start.isoformat(),end.isoformat()))
    sets=q("""SELECT COUNT(ws.id) sets, COALESCE(SUM(CASE WHEN e.exercise_type='Bodyweight' THEN ws.additional_weight*ws.reps ELSE ws.weight*ws.reps END),0) volume
              FROM workout_sets ws JOIN workout_exercises we ON we.id=ws.workout_exercise_id JOIN workouts w ON w.id=we.workout_id JOIN exercises e ON e.id=we.exercise_id
              WHERE w.date BETWEEN ? AND ?""",(start.isoformat(),end.isoformat()),one=True)
    planned=max(q('SELECT COUNT(*) c FROM program_days',one=True)['c'] or 0, len(workouts), 1)
    compliance=round(len(workouts)/planned*100,1)
    wellness=q('SELECT * FROM wellness WHERE date BETWEEN ? AND ? ORDER BY date',(start.isoformat(),end.isoformat()))
    avg_sleep=round(sum([r['sleep_hours'] or 0 for r in wellness])/max(1,len(wellness)),1) if wellness else None
    prs=personal_records(999)
    xp=q('SELECT COALESCE(SUM(points),0) v FROM xp_events WHERE date>=?',(start.isoformat(),),one=True)['v'] or 0
    comp2=compliance_engine_v2()
    deload=deload_detection()
    muscle=muscle_balance_warnings()
    wins=[]; risks=[]; recommendations=[]
    if compliance>=80: wins.append('Training compliance stayed above the ATHENA target.')
    else: risks.append('Training compliance is below target for this week.'); recommendations.append('Simplify the next week: choose fewer sessions and complete them fully.')
    if avg_sleep and avg_sleep>=7: wins.append('Sleep supported recovery this week.')
    elif avg_sleep: risks.append('Sleep is below the recovery target.'); recommendations.append('Protect one extra hour of sleep before heavy sessions.')
    if prs: wins.append(f"PR context available: {prs[0]['name']} · {prs[0]['display']}.")
    if (sets['volume'] or 0)>0: wins.append(f"{round(sets['volume'] or 0):g} kg estimated volume logged.")
    for m in muscle[:2]:
        if m.get('level') in ('warning','danger') or 'low' in m.get('title','').lower() or 'dominance' in m.get('title','').lower():
            risks.append(m['title']); recommendations.append(m['text'])
    if deload['needed']:
        risks.append('Deload trigger is active.'); recommendations.append(deload['recommendation'])
    if not wins: wins.append('Build the data trail: log workouts, wellness and skill evidence this week.')
    if not risks: risks.append('No major weekly risk detected.')
    if not recommendations: recommendations.append('Continue planned progression and keep RPE honest.')
    best = prs[0] if prs else None
    week_score=round((compliance*.35) + (comp2['overall']*.25) + (min(100,(sets['sets'] or 0)*4)*.2) + ((80 if avg_sleep is None else min(100,avg_sleep/8*100))*.2))
    highlights=wins[:3]
    return {'start':start.isoformat(),'end':end.isoformat(),'workouts':workouts,'workout_count':len(workouts),'planned':planned,'compliance':compliance,'sets':sets['sets'] or 0,'volume':round(sets['volume'] or 0,1),'wellness':wellness,'avg_sleep':avg_sleep,'prs':prs[:5],'xp':xp,'highlights':highlights,'deload':deload,'wins':wins,'risks':risks,'recommendations':recommendations,'weekly_mvp':best,'week_score':week_score,'compliance_engine':comp2}


def deload_detection():
    recent=q('SELECT * FROM workouts ORDER BY date DESC LIMIT 8')
    wellness=q('SELECT * FROM wellness ORDER BY date DESC LIMIT 7')
    avg_fatigue=round(sum([(r['fatigue'] or 4) for r in recent])/max(1,len(recent)),1) if recent else 0
    avg_readiness=round(sum([(r['readiness'] or 7) for r in recent])/max(1,len(recent)),1) if recent else 7
    avg_sleep=round(sum([(r['sleep_hours'] or 7) for r in wellness])/max(1,len(wellness)),1) if wellness else 7
    plateaus=plateau_detection(); reasons=[]
    if avg_fatigue>=6.8: reasons.append('recent fatigue is elevated')
    if avg_readiness<=5.5: reasons.append('recent readiness is low')
    if avg_sleep<6.5: reasons.append('sleep trend is below recovery target')
    if len(plateaus)>=2: reasons.append('multiple lifts show plateau risk')
    needed=len(reasons)>=2
    return {'needed':needed,'score':min(100, round(avg_fatigue*10 + max(0,7-avg_readiness)*8 + max(0,7-avg_sleep)*8 + len(plateaus)*6)),'reasons':reasons or ['no strong deload trigger detected'],'recommendation':'Deload for 4-7 days: cut volume 30-50%, keep movement quality, stay around RPE 6-7.' if needed else 'No deload needed. Continue planned progression and monitor fatigue.'}



def achievement_catalog():
    workouts=q('SELECT COUNT(*) c FROM workouts',one=True)['c'] or 0
    prs=len(personal_records(999)); streak=consistency_engine(30)['current']; ris_count=q('SELECT COUNT(*) c FROM ris_tests',one=True)['c'] or 0
    skills_avg=q('SELECT COALESCE(AVG(progress),0) v FROM athlete_skills',one=True)['v'] or 0
    comp=training_compliance()['rate']; quests_done=q('SELECT COUNT(*) c FROM quests WHERE status="Completed"',one=True)['c'] or 0
    wellness_count=q('SELECT COUNT(*) c FROM wellness',one=True)['c'] or 0
    def item(category,title,desc,current,target,icon,rarity):
        current=int(current or 0); target=max(1,int(target or 1)); unlocked=current>=target
        return {'category':category,'title':title,'description':desc,'current':min(current,target),'target':target,'progress':round(min(100,current/target*100)),'unlocked':unlocked,'icon':icon,'rarity':rarity}
    return [
        item('Consistency','First Session','Log your first workout.',workouts,1,'●','Common'),
        item('Consistency','10 Workouts','Build a 10-session base.',workouts,10,'●','Rare'),
        item('Consistency','30 Workouts','Become a regular ATHENA athlete.',workouts,30,'●','Epic'),
        item('Consistency','7-Day Streak','Build a full week rhythm.',streak,7,'●','Rare'),
        item('Strength','First PR','Record a personal best.',prs,1,'◆','Common'),
        item('Strength','PR Collector','Record five personal bests.',prs,5,'◆','Epic'),
        item('Strength','RIS Initiate','Save your first RIS test.',ris_count,1,'◆','Common'),
        item('Skills','Skill Apprentice','Reach 25% average skill progress.',skills_avg,25,'▲','Rare'),
        item('Skills','Skill Specialist','Reach 60% average skill progress.',skills_avg,60,'▲','Epic'),
        item('Recovery','Recovery Aware','Log wellness/readiness once.',wellness_count,1,'◐','Common'),
        item('Recovery','Plan Discipline','Reach 80% training compliance.',comp,80,'◐','Rare'),
        item('Quests','Quest Starter','Complete one ATHENA quest.',quests_done,1,'✦','Common'),
        item('Quests','Quest Grinder','Complete five ATHENA quests.',quests_done,5,'✦','Epic'),
        item('Explorer','Library Builder','Create or edit 10 exercises.',q('SELECT COUNT(*) c FROM exercises WHERE is_custom=1',one=True)['c'] or 0,10,'✚','Rare'),
    ]


def athena_daily_score():
    """One clear daily score for the dashboard. It is intentionally simple and explainable."""
    ready = readiness_v2()
    intel = athlete_intelligence()
    comp = training_compliance(28)
    wellness = q('SELECT * FROM wellness ORDER BY date DESC LIMIT 7')
    if wellness:
        avg_sleep = sum([(r['sleep_hours'] or 7) for r in wellness]) / max(1, len(wellness))
        sleep_score = max(0, min(100, round((avg_sleep / 8) * 100)))
    else:
        sleep_score = 75
    fatigue_score = max(0, min(100, 100 - (intel['fatigue'] * 10)))
    parts = {
        'Recovery': int(intel['recovery']),
        'Readiness': int(ready['score']),
        'Compliance': int(comp['rate']),
        'Fatigue': int(fatigue_score),
        'Sleep': int(sleep_score),
    }
    score = round(parts['Recovery']*.26 + parts['Readiness']*.24 + parts['Compliance']*.20 + parts['Fatigue']*.15 + parts['Sleep']*.15)
    if score >= 90:
        label, tone = 'Elite readiness', 'elite'
    elif score >= 75:
        label, tone = 'Performance ready', 'good'
    elif score >= 60:
        label, tone = 'Build carefully', 'neutral'
    else:
        label, tone = 'Recovery priority', 'danger'
    previous = max(0, min(100, score - 4 + (comp['completed'] % 3)))
    return {'score': score, 'label': label, 'tone': tone, 'parts': parts, 'delta': score - previous}


def smart_dashboard_alerts():
    alerts = []
    daily = athena_daily_score()
    plan = smart_today_plan()
    deload = deload_detection()
    comp = training_compliance(28)
    intel = athlete_intelligence()
    prs = personal_records(3)
    if deload['needed']:
        alerts.append({'tone':'danger','title':'Deload trigger detected','text':deload['recommendation']})
    if comp['rate'] < 70:
        alerts.append({'tone':'warning','title':'Compliance needs attention','text':f"{comp['completed']} of {comp['planned']} planned sessions completed in the current window."})
    if intel['fatigue'] >= 7:
        alerts.append({'tone':'warning','title':'Fatigue is elevated','text':'Keep today below RPE 8 and reduce accessory volume if warm-ups feel slow.'})
    if daily['score'] >= 80 and not deload['needed']:
        alerts.append({'tone':'good','title':'Green light to train','text':plan['action']})
    if prs:
        alerts.append({'tone':'info','title':'PR context available','text':f"Latest PR reference: {prs[0]['name']} · {prs[0]['display']}"})
    if not alerts:
        alerts.append({'tone':'info','title':'Build the data trail','text':'Log workouts, wellness and bodyweight to make ATHENA’s recommendations sharper.'})
    return alerts[:4]


def dashboard_widget_catalog():
    return [
        {'key':'athena_score','label':'ATHENA Score','group':'Daily'},
        {'key':'smart_plan','label':'Smart Plan','group':'Daily'},
        {'key':'ris','label':'RIS','group':'Performance'},
        {'key':'recovery','label':'Recovery','group':'Recovery'},
        {'key':'readiness','label':'Readiness','group':'Recovery'},
        {'key':'fatigue','label':'Fatigue','group':'Recovery'},
        {'key':'sleep','label':'Sleep','group':'Recovery'},
        {'key':'compliance','label':'Compliance','group':'Consistency'},
        {'key':'bodyweight','label':'Bodyweight','group':'Body'},
        {'key':'level','label':'Level','group':'RPG'},
        {'key':'streak','label':'Streak','group':'Consistency'},
        {'key':'volume','label':'Weekly volume','group':'Training'},
        {'key':'workouts','label':'Weekly workouts','group':'Training'},
        {'key':'prs','label':'Personal records','group':'Strength'},
        {'key':'quests','label':'Quests','group':'RPG'},
        {'key':'skills','label':'Skill focus','group':'Skills'},
    ]


def dashboard_widget_state():
    row = q('SELECT widgets FROM dashboard_widgets WHERE id=1', one=True)
    default = 'athena_score,smart_plan,ris,recovery,compliance,bodyweight,level,streak'
    saved = (row['widgets'] if row and row['widgets'] else default).split(',')
    all_widgets = dashboard_widget_catalog()
    allowed = {w['key'] for w in all_widgets}
    selected = []
    for key in saved:
        key = (key or '').strip()
        if key in allowed and key not in selected:
            selected.append(key)
    if not selected:
        selected = default.split(',')
    return {'selected': selected, 'all': all_widgets}


def dashboard_card_data():
    best = q('SELECT * FROM ris_tests ORDER BY date DESC,id DESC LIMIT 1', one=True)
    comp = training_compliance(28)
    bw = bodyweight_center_data()
    gam = gamification_state()
    cons = consistency_engine(30)
    weekly = weekly_review_data()
    daily = athena_daily_score()
    ready = readiness_v2()
    intel = athlete_intelligence()
    wellness = q('SELECT * FROM wellness ORDER BY date DESC LIMIT 7')
    avg_sleep = round(sum([(r['sleep_hours'] or 0) for r in wellness]) / max(1, len(wellness)), 1) if wellness else None
    skill = q('SELECT * FROM athlete_skills ORDER BY progress DESC, updated_at DESC LIMIT 1', one=True)
    active_quests = q('SELECT COUNT(*) c FROM quests WHERE status="Active"', one=True)['c'] or 0
    prs = personal_records(999)
    data = {
        'athena_score': {'label':'ATHENA Score','value': daily['score'], 'sub':daily['label'], 'href':'/'},
        'smart_plan': {'label':'Smart Plan','value': smart_today_plan()['title'], 'sub':smart_today_plan()['action'], 'href':'/'},
        'ris': {'label':'RIS','value': best['ris_score'] if best else 0, 'sub':'Relative strength index', 'href':'/ris'},
        'recovery': {'label':'Recovery','value': intel['recovery'], 'sub':'Adaptation state', 'href':'/recovery'},
        'readiness': {'label':'Readiness','value': ready['score'], 'sub':ready.get('label','Daily readiness'), 'href':'/recovery'},
        'fatigue': {'label':'Fatigue','value': intel['fatigue'], 'sub':'Lower is better', 'href':'/recovery'},
        'sleep': {'label':'Sleep','value': (str(avg_sleep)+'h') if avg_sleep is not None else '-', 'sub':'7-day average', 'href':'/recovery'},
        'compliance': {'label':'Compliance','value': str(comp['rate'])+'%', 'sub':f"{comp['completed']}/{comp['planned']} sessions", 'href':'/weekly-review'},
        'bodyweight': {'label':'Bodyweight','value': bw.get('current') or '-', 'sub': bw.get('trend') or 'No trend yet', 'href':'/analytics'},
        'level': {'label':'Level','value': gam['level'], 'sub':f"{gam['xp']} XP", 'href':'/achievements'},
        'streak': {'label':'Streak','value': cons['current'], 'sub':'Current training rhythm', 'href':'/analytics'},
        'volume': {'label':'Weekly volume','value': round(weekly['volume']), 'sub':str(weekly['workout_count'])+' workouts this week', 'href':'/weekly-review'},
        'workouts': {'label':'Weekly workouts','value': weekly['workout_count'], 'sub':f"{weekly['compliance']}% compliance", 'href':'/weekly-review'},
        'prs': {'label':'Personal records','value': len(prs), 'sub': prs[0]['name'] if prs else 'No PRs yet', 'href':'/records'},
        'quests': {'label':'Active quests','value': active_quests, 'sub':'Auto and manual objectives', 'href':'/quests'},
        'skills': {'label':'Skill focus','value': skill['name'] if skill else 'None', 'sub': (str(skill['progress'])+'% progress') if skill else 'Add a skill', 'href':'/skills'},
    }
    return data

@app.route('/')
def dashboard():
    auto_update_quests()
    profile=q('SELECT * FROM athlete_profile WHERE id=1', one=True)
    recent = q('SELECT * FROM workouts ORDER BY date DESC LIMIT 5')
    wellbeing = q('SELECT * FROM wellness ORDER BY date DESC LIMIT 5')
    ex_count = q('SELECT COUNT(*) c FROM exercises', one=True)['c']
    best_ris = q('SELECT * FROM ris_tests ORDER BY ris_score DESC LIMIT 1', one=True)
    last_workout = q('SELECT * FROM workouts ORDER BY date DESC LIMIT 1', one=True)
    quick_routines = q('SELECT * FROM routines ORDER BY id LIMIT 4')
    return render_template('dashboard.html', profile=profile, display_name=first_name_from_profile(profile), stats=stats(), recent=recent, wellbeing=wellbeing, ex_count=ex_count, advisor=training_advisor(), best_ris=best_ris, records=personal_records(5), heat=heatmap_data(91), muscles=muscle_volume_data()[:6], consistency=consistency_engine(), level=athlete_level(), readiness=readiness_v2(), bodyweight=bodyweight_center_data(), last_workout=last_workout, quick_routines=quick_routines, intelligence=athlete_intelligence(), gamification=gamification_state(), mission=mission_state(), attributes=rpg_attributes(), smart_plan=smart_today_plan(), onboarding=onboarding_state(), weekly=weekly_review_data(), deload=deload_detection(), daily_score=athena_daily_score(), smart_alerts=smart_dashboard_alerts(), dashboard_widgets=dashboard_widget_state(), dashboard_cards=dashboard_card_data())

@app.route('/dashboard/widgets', methods=['POST'])
def dashboard_widgets_update():
    catalog = dashboard_widget_catalog()
    allowed = {w['key'] for w in catalog}
    checked = [x for x in request.form.getlist('widgets') if x in allowed]
    raw_order = request.form.get('widget_order','')
    requested_order = [x.strip() for x in raw_order.split(',') if x.strip() in allowed]
    chosen = []
    for key in requested_order:
        if key in checked and key not in chosen:
            chosen.append(key)
    for key in checked:
        if key not in chosen:
            chosen.append(key)
    if not chosen:
        chosen = ['athena_score','smart_plan','ris','recovery','compliance','bodyweight','level','streak']
    q('INSERT OR REPLACE INTO dashboard_widgets(id,widgets) VALUES(1,?)', (','.join(chosen),), commit=True)
    flash('Dashboard layout saved.')
    return redirect(url_for('dashboard'))

@app.route('/exercises', methods=['GET','POST'])
def exercises():
    if request.method == 'POST':
        image_path = save_image(request.files.get('image'))
        new_id = insert('''INSERT INTO exercises(name,muscle_group,equipment,notes,image_path,description,difficulty,primary_muscle,secondary_muscles,instructions,cues,common_mistakes,ris_tag,is_custom)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1)''',(
            request.form['name'], request.form['muscle_group'], request.form.get('equipment','Bodyweight'), request.form.get('notes',''), image_path,
            request.form.get('description',''), request.form.get('difficulty','Intermediate'), request.form.get('primary_muscle',''),
            request.form.get('secondary_muscles',''), request.form.get('instructions',''), request.form.get('cues',''), request.form.get('common_mistakes',''), request.form.get('ris_tag','Strength')
        ))
        with db() as conn:
            set_exercise_tags(conn, new_id, request.form.get('tags',''))
            conn.commit()
        q('UPDATE exercises SET exercise_type=?, metric_hint=?, media_url=?, movement_pattern=? WHERE id=?', (request.form.get('exercise_type','Strength'), request.form.get('metric_hint','Weight + reps'), request.form.get('media_url',''), request.form.get('movement_pattern',''), new_id), commit=True)
        flash('Exercise added to ATHENA Library.')
        return redirect(url_for('exercises'))
    rows = [dict(r) for r in q('SELECT * FROM exercises ORDER BY muscle_group,name')]
    with db() as conn:
        for r in rows:
            r['tags'] = ', '.join(tag_names_for_exercise(conn, r['id']))
    all_tags = q('SELECT * FROM exercise_tags ORDER BY name')
    ctx = exercise_picker_context()
    sub_rows = q('SELECT s.*, e.name ex_name, se.name sub_name FROM exercise_substitutions s JOIN exercises e ON e.id=s.exercise_id JOIN exercises se ON se.id=s.substitute_id ORDER BY e.name, se.name')
    checklists = {r['exercise_id']: [] for r in q('SELECT DISTINCT exercise_id FROM exercise_checklists')}
    for r in q('SELECT * FROM exercise_checklists ORDER BY exercise_id,item_order,id'):
        checklists.setdefault(r['exercise_id'], []).append(dict(r))
    smart_subs = {r['id']: smart_substitution_candidates(r['id'], 6) for r in rows}
    return render_template('exercises.html', rows=rows, all_tags=all_tags, sub_rows=sub_rows, checklists=checklists, smart_subs=smart_subs, **ctx)

@app.route('/exercises/<int:eid>/edit', methods=['POST'])
def exercise_edit(eid):
    current = q('SELECT image_path FROM exercises WHERE id=?',(eid,),one=True)
    image_path = save_image(request.files.get('image')) or (current['image_path'] if current else '')
    q('''UPDATE exercises SET name=?, muscle_group=?, equipment=?, notes=?, image_path=?, description=?, difficulty=?, primary_muscle=?, secondary_muscles=?, instructions=?, cues=?, common_mistakes=?, ris_tag=?, exercise_type=?, metric_hint=? WHERE id=?''',(
        request.form['name'], request.form['muscle_group'], request.form.get('equipment',''), request.form.get('notes',''), image_path,
        request.form.get('description',''), request.form.get('difficulty','Intermediate'), request.form.get('primary_muscle',''),
        request.form.get('secondary_muscles',''), request.form.get('instructions',''), request.form.get('cues',''), request.form.get('common_mistakes',''), request.form.get('ris_tag','Strength'), request.form.get('exercise_type','Strength'), request.form.get('metric_hint','Weight + reps'), eid
    ), commit=True)
    with db() as conn:
        set_exercise_tags(conn, eid, request.form.get('tags',''))
        conn.commit()
    q('UPDATE exercises SET media_url=?, movement_pattern=? WHERE id=?',(request.form.get('media_url',''), request.form.get('movement_pattern',''), eid), commit=True)
    flash('Exercise details updated.')
    return redirect(url_for('exercises'))


@app.route('/exercises/<int:eid>/delete', methods=['POST'])
def exercise_delete(eid):
    used = q('''SELECT COUNT(*) c FROM workout_exercises WHERE exercise_id=?''', (eid,), one=True)['c'] or 0
    routine_used = q('''SELECT COUNT(*) c FROM routine_exercises WHERE exercise_id=?''', (eid,), one=True)['c'] or 0
    if used or routine_used:
        flash('Exercise is used in workouts or routines. Remove it from those places first, then delete it from the library.')
        return redirect(url_for('exercises'))
    with db() as conn:
        conn.execute('DELETE FROM exercise_tag_map WHERE exercise_id=?', (eid,))
        conn.execute('DELETE FROM exercises WHERE id=?', (eid,))
        conn.commit()
    flash('Exercise deleted from library.')
    return redirect(url_for('exercises'))


def mark_recent_exercise(eid, context=''):
    try:
        insert('INSERT INTO exercise_recent(exercise_id,context) VALUES(?,?)',(eid, context or ''))
    except Exception:
        pass


def favorite_exercise_ids():
    return {r['exercise_id'] for r in q('SELECT exercise_id FROM exercise_favorites')}


def recent_exercise_ids(limit=12):
    return [r['exercise_id'] for r in q('SELECT exercise_id, MAX(created_at) last_used FROM exercise_recent GROUP BY exercise_id ORDER BY last_used DESC LIMIT ?', (limit,))]


def exercise_picker_context():
    favs = favorite_exercise_ids()
    recents = set(recent_exercise_ids(12))
    subs = {}
    for r in q('''SELECT s.exercise_id, e.id substitute_id, e.name, e.muscle_group, e.exercise_type, s.note
                  FROM exercise_substitutions s JOIN exercises e ON e.id=s.substitute_id
                  ORDER BY e.name'''):
        subs.setdefault(r['exercise_id'], []).append(dict(r))
    return {'favorite_ids': favs, 'recent_ids': recents, 'substitutions': subs}


def default_checklist_for_exercise(ex):
    name = (ex['name'] if hasattr(ex, 'keys') else ex.get('name','')).lower()
    muscle = (ex['muscle_group'] if hasattr(ex, 'keys') else ex.get('muscle_group',''))
    etype = (ex['exercise_type'] if hasattr(ex, 'keys') else ex.get('exercise_type',''))
    if 'squat' in name:
        return ['Brace before every rep', 'Knees track over toes', 'Control the descent', 'Drive evenly through both feet']
    if 'bench' in name or 'press' in name or muscle in ['Chest','Shoulders']:
        return ['Stable shoulder blades', 'Controlled lowering phase', 'Consistent touch point / range', 'Press without losing position']
    if 'pull' in name or 'row' in name or muscle == 'Back':
        return ['Start with active shoulders', 'Pull through elbows', 'Avoid swinging', 'Control the eccentric']
    if 'muscle up' in name:
        return ['Explosive high pull', 'Fast transition over the bar', 'Keep rings/bar close', 'Lock out cleanly']
    if etype in ['Timed','Mobility']:
        return ['Breathe steadily', 'Keep clean alignment', 'Stop before form breaks']
    return ['Use full controlled range', 'Keep stable setup', 'Match the target tempo', 'Stop if technique breaks']


def smart_substitution_candidates(exercise_id, limit=8):
    ex = q('SELECT * FROM exercises WHERE id=?',(exercise_id,),one=True)
    if not ex:
        return []
    rows = [dict(r) for r in q('SELECT * FROM exercises WHERE id<>? ORDER BY name',(exercise_id,))]
    out=[]
    for r in rows:
        score=0
        reasons=[]
        if (r.get('muscle_group') or '') == (ex['muscle_group'] or ''):
            score += 45; reasons.append('same muscle group')
        if (r.get('movement_pattern') or '').strip() and (r.get('movement_pattern') or '').lower() == (ex['movement_pattern'] or '').lower():
            score += 30; reasons.append('same movement pattern')
        if (r.get('exercise_type') or '') == (ex['exercise_type'] or ''):
            score += 12; reasons.append('same tracking type')
        if (r.get('equipment') or '') == (ex['equipment'] or ''):
            score += 8; reasons.append('same equipment')
        if score:
            r['smart_score']=score
            r['smart_reason']=', '.join(reasons) or 'similar movement'
            out.append(r)
    out.sort(key=lambda x:(-x['smart_score'], x['name']))
    return out[:limit]


def recalc_skill_progress(sid):
    total=q('SELECT COUNT(*) c FROM skill_steps WHERE skill_id=?',(sid,),one=True)['c'] or 1
    done=q('SELECT COUNT(*) c FROM skill_steps WHERE skill_id=? AND completed=1',(sid,),one=True)['c'] or 0
    q('UPDATE athlete_skills SET progress=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',(round(done/total*100),sid),commit=True)


def warmup_plan_for_exercises(exs):
    groups = {((e['muscle_group'] or '') if hasattr(e, 'keys') else e.get('muscle_group','')) for e in exs}
    names = [((e['name'] or '') if hasattr(e, 'keys') else e.get('name','')) for e in exs]
    plan = []
    if any(g in groups for g in ['Chest','Shoulders','Triceps']):
        plan += [('Shoulder circles','2 x 20 sec'),('Band pull-aparts','2 x 15'),('Scapular push-ups','2 x 10')]
    if 'Back' in groups:
        plan += [('Dead hang or active hang','2 x 20 sec'),('Scapular pull-ups','2 x 8'),('Light rows','2 x 12')]
    if any(g in groups for g in ['Legs','Glutes']):
        plan += [('Hip airplanes or hip circles','2 x 8/side'),('Bodyweight squat','2 x 10'),('Light hinge pattern','2 x 10')]
    if not plan:
        plan = [('General pulse raiser','5 min easy pace'),('Dynamic mobility','4-6 min'),('First exercise ramp-up','2-4 light sets')]
    heavy = [n for n in names if any(k in n.lower() for k in ['bench','squat','deadlift','press','pull up','dip','muscle up'])]
    for n in heavy[:2]:
        plan.append((f'{n} ramp-up','Start easy, add load gradually for 3-5 prep sets'))
    seen=set(); out=[]
    for a,b in plan:
        if a not in seen:
            out.append({'name':a,'target':b}); seen.add(a)
    return out[:8]


def muscle_balance_warnings():
    rows = muscle_volume_data()
    total = sum(float(r['volume'] or 0) for r in rows) or 1
    by = {r['muscle']: float(r['volume'] or 0)/total*100 for r in rows}
    push = by.get('Chest',0)+by.get('Shoulders',0)+by.get('Triceps',0)
    pull = by.get('Back',0)+by.get('Biceps',0)
    legs = by.get('Legs',0)+by.get('Glutes',0)
    warnings=[]
    if push > pull + 18:
        warnings.append({'title':'Push dominance detected','text':'Push volume is much higher than pull volume. Consider adding rows, pull-ups, rear delt or face-pull variations.','level':'warning'})
    if pull > push + 22:
        warnings.append({'title':'Pull volume dominates','text':'Pull volume is far ahead of pushing work. Add a press or controlled push accessory if your goal requires balance.','level':'info'})
    if legs < 18 and total > 0:
        warnings.append({'title':'Lower-body volume looks low','text':'Leg/glute work is underrepresented. Add squat, hinge, lunge or loaded carry patterns.','level':'warning'})
    if by.get('Core',0) < 6 and total > 0:
        warnings.append({'title':'Core work is light','text':'Add anti-extension, anti-rotation or carry work to support strength transfer.','level':'info'})
    if not warnings:
        warnings.append({'title':'Muscle balance looks stable','text':'Current distribution does not show a major red flag. Keep monitoring as the training block grows.','level':'good'})
    return warnings

@app.route('/routines', methods=['GET','POST'])
def routines():
    if request.method == 'POST':
        rid = insert('INSERT INTO routines(name,goal,intensity,notes) VALUES(?,?,?,?)',(request.form['name'],request.form['goal'],request.form['intensity'],request.form.get('notes','')))
        flash('Routine shell created. Add exercises below.')
        return redirect(url_for('routine_detail', rid=rid))
    rows = q('SELECT r.*, COUNT(re.id) exercise_count FROM routines r LEFT JOIN routine_exercises re ON r.id=re.routine_id GROUP BY r.id ORDER BY r.created_at DESC')
    return render_template('routines.html', rows=rows)

@app.route('/routines/<int:rid>', methods=['GET','POST'])
def routine_detail(rid):
    if request.method == 'POST':
        insert('INSERT INTO routine_exercises(routine_id,exercise_id,planned_sets,target_reps,rest_seconds,order_index,superset_group) VALUES(?,?,?,?,?,?,?)',(rid,request.form['exercise_id'],request.form['planned_sets'],request.form['target_reps'],request.form['rest_seconds'],request.form['order_index'],request.form.get('superset_group','').strip().upper()))
        mark_recent_exercise(request.form['exercise_id'], 'routine')
        flash('Exercise added to routine.')
        return redirect(url_for('routine_detail', rid=rid))
    routine = q('SELECT * FROM routines WHERE id=?',(rid,),one=True)
    items = q('SELECT re.*, e.name, e.muscle_group, e.equipment, e.exercise_type, e.metric_hint, e.image_path FROM routine_exercises re JOIN exercises e ON e.id=re.exercise_id WHERE routine_id=? ORDER BY order_index',(rid,))
    ctx = exercise_picker_context()
    return render_template('routine_detail.html', routine=routine, items=items, exercises=q('SELECT * FROM exercises ORDER BY name'), warmup=warmup_plan_for_exercises(items), **ctx)


@app.route('/routines/<int:rid>/items/<int:item_id>/edit', methods=['POST'])
def routine_item_edit(rid, item_id):
    q('''UPDATE routine_exercises SET exercise_id=?, planned_sets=?, target_reps=?, rest_seconds=?, order_index=?, superset_group=? WHERE id=? AND routine_id=?''', (
        request.form.get('exercise_id'), request.form.get('planned_sets') or 1, request.form.get('target_reps',''), request.form.get('rest_seconds') or 90, request.form.get('order_index') or 1, request.form.get('superset_group','').strip().upper(), item_id, rid
    ), commit=True)
    mark_recent_exercise(request.form.get('exercise_id'), 'routine-edit')
    flash('Routine exercise updated.')
    return redirect(url_for('routine_detail', rid=rid))

@app.route('/routines/<int:rid>/items/<int:item_id>/delete', methods=['POST'])
def routine_item_delete(rid, item_id):
    q('DELETE FROM routine_exercises WHERE id=? AND routine_id=?', (item_id, rid), commit=True)
    flash('Exercise removed from routine.')
    return redirect(url_for('routine_detail', rid=rid))

@app.route('/routines/<int:rid>/reorder', methods=['POST'])
def routine_reorder(rid):
    data = request.get_json(silent=True) or {}
    order = data.get('order') or []
    if not isinstance(order, list):
        return {'ok': False, 'error': 'Invalid order payload'}, 400
    with db() as conn:
        for idx, item_id in enumerate(order, start=1):
            try:
                iid = int(item_id)
            except (TypeError, ValueError):
                continue
            conn.execute('UPDATE routine_exercises SET order_index=? WHERE id=? AND routine_id=?', (idx, iid, rid))
        conn.commit()
    return {'ok': True}

@app.route('/routines/<int:rid>/delete', methods=['POST'])
def routine_delete(rid):
    used = q('SELECT COUNT(*) c FROM workouts WHERE routine_id=?', (rid,), one=True)['c'] or 0
    if used:
        flash('Routine is connected to existing workouts. Duplicate or archive pattern later; for now remove workout links before deleting.')
        return redirect(url_for('routine_detail', rid=rid))
    with db() as conn:
        conn.execute('DELETE FROM routine_exercises WHERE routine_id=?', (rid,))
        conn.execute('DELETE FROM program_days WHERE routine_id=?', (rid,))
        conn.execute('DELETE FROM routines WHERE id=?', (rid,))
        conn.commit()
    flash('Routine deleted.')
    return redirect(url_for('routines'))

@app.route('/workouts')
def workouts():
    search = (request.args.get('q') or '').strip()
    source = (request.args.get('source') or '').strip()
    params = []
    where = []
    if search:
        like = f'%{search}%'
        where.append('(w.name LIKE ? OR w.date LIKE ? OR w.notes LIKE ? OR r.name LIKE ?)')
        params.extend([like, like, like, like])
    if source:
        where.append('w.source = ?')
        params.append(source)
    where_sql = ('WHERE ' + ' AND '.join(where)) if where else ''
    rows = q(f'''
        SELECT w.*, r.name routine_name,
        COUNT(DISTINCT we.id) exercise_count,
        COUNT(ws.id) set_count,
        COALESCE(SUM(ws.weight*ws.reps),0) volume
        FROM workouts w
        LEFT JOIN routines r ON r.id=w.routine_id
        LEFT JOIN workout_exercises we ON we.workout_id=w.id
        LEFT JOIN workout_sets ws ON ws.workout_exercise_id=we.id
        {where_sql}
        GROUP BY w.id
        ORDER BY w.date DESC, w.id DESC
    ''', tuple(params))
    rows=[dict(r, session_score=session_score_value(r)) for r in rows]
    return render_template('workouts.html', rows=rows, search=search, source=source, heat=heatmap_data(91))

@app.route('/workouts/new', methods=['GET','POST'])
def workout_new():
    if request.method == 'POST':
        try:
            with db() as conn:
                cur = conn.execute('INSERT INTO workouts(name,date,routine_id,source,duration_min,bodyweight,readiness,mood,notes,fatigue,focus) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(
                    request.form['name'], request.form['date'], request.form.get('routine_id') or None, 'ATHENA', request.form.get('duration_min') or 0,
                    request.form.get('bodyweight') or None, request.form.get('readiness') or 7, request.form.get('mood') or 'Good', request.form.get('notes',''), request.form.get('fatigue') or 4, request.form.get('focus') or 7))
                wid = cur.lastrowid
                rid = request.form.get('routine_id')
                if rid:
                    routine_items = conn.execute('SELECT * FROM routine_exercises WHERE routine_id=? ORDER BY order_index',(rid,)).fetchall()
                    for item in routine_items:
                        weid = conn.execute('INSERT INTO workout_exercises(workout_id,exercise_id,order_index) VALUES(?,?,?)',(wid,item['exercise_id'],item['order_index'])).lastrowid
                        for sn in range(1, int(item['planned_sets'])+1):
                            conn.execute('INSERT INTO workout_sets(workout_exercise_id,set_number,weight,reps,rpe) VALUES(?,?,?,?,?)',(weid,sn,0,0,None))
                conn.commit()
            flash('Workout created. Fill in sets, weights and notes.')
            return redirect(url_for('workout_detail', wid=wid))
        except sqlite3.Error as e:
            flash(f'SQLite error fixed path: {e}. The database schema was migrated on startup; restart the app if this appears once after an old build.')
    return render_template('workout_new.html', routines=q('SELECT * FROM routines ORDER BY name'))

@app.route('/workouts/<int:wid>', methods=['GET','POST'])
def workout_detail(wid):
    if request.method == 'POST':
        q('UPDATE workouts SET name=?,date=?,duration_min=?,bodyweight=?,readiness=?,mood=?,notes=?,fatigue=?,focus=? WHERE id=?',(
            request.form['name'],request.form['date'],request.form.get('duration_min') or 0,request.form.get('bodyweight') or None,request.form.get('readiness') or 7,request.form.get('mood') or 'Good',request.form.get('notes',''),request.form.get('fatigue') or 4,request.form.get('focus') or 7,wid),commit=True)
        for sid in request.form.getlist('set_ids'):
            # Pobieramy parametry serii z formularza frontendu
            s_weight = float(request.form.get(f'weight_{sid}', 0) or request.form.get(f'addwt_{sid}', 0) or 0)
            s_reps = int(request.form.get(f'reps_{sid}', 0) or 0)
            s_rpe = clean_rpe(request.form.get(f'rpe_{sid}'))
            
            # Obliczamy e1RM do zapisu w bazie danych
            e1rm_val = calculate_e1rm(s_weight, s_reps, s_rpe)

            q('''UPDATE workout_sets SET weight=?, reps=?, additional_weight=?, duration_seconds=?, 
                        distance_m=?, calories=?, avg_hr=?, rounds=?, work_seconds=?, rest_seconds=?, 
                        rpe=?, notes=?, set_type=?, estimated_1rm=? WHERE id=?''',(
                request.form.get(f'weight_{sid}',0) or 0, request.form.get(f'reps_{sid}',0) or 0, request.form.get(f'addwt_{sid}',0) or 0, request.form.get(f'duration_{sid}',0) or 0,
                request.form.get(f'distance_{sid}',0) or 0, request.form.get(f'calories_{sid}',0) or 0, request.form.get(f'avghr_{sid}',0) or 0,
                request.form.get(f'rounds_{sid}',0) or 0, request.form.get(f'worksec_{sid}',0) or 0, request.form.get(f'restsec_{sid}',0) or 0,
                s_rpe, request.form.get(f'setnotes_{sid}',''), request.form.get(f'settype_{sid}','Working'), e1rm_val, sid), commit=True)
        flash('Workout updated.')
        return redirect(url_for('workout_detail', wid=wid))
    workout = q('SELECT w.*, r.name routine_name FROM workouts w LEFT JOIN routines r ON r.id=w.routine_id WHERE w.id=?',(wid,),one=True)
    exs = q('SELECT we.id weid, we.superset_group, e.id exercise_id, e.name,e.muscle_group,e.equipment,e.image_path,e.exercise_type,e.metric_hint FROM workout_exercises we JOIN exercises e ON e.id=we.exercise_id WHERE we.workout_id=? ORDER BY we.order_index',(wid,))
    sets = {we['weid']: q('SELECT * FROM workout_sets WHERE workout_exercise_id=? ORDER BY set_number',(we['weid'],)) for we in exs}
    volume = q('SELECT COALESCE(SUM(ws.weight*ws.reps),0) v FROM workout_sets ws JOIN workout_exercises we ON we.id=ws.workout_exercise_id WHERE we.workout_id=?',(wid,),one=True)['v']
    ctx = exercise_picker_context()
    return render_template('workout_detail.html', workout=workout, exs=exs, sets=sets, volume=round(volume,1), all_exercises=q('SELECT * FROM exercises ORDER BY name'), warmup=warmup_plan_for_exercises(exs), **ctx)

@app.route('/workouts/<int:wid>/add-exercise', methods=['POST'])
def workout_add_exercise(wid):
    order = q('SELECT COALESCE(MAX(order_index),0)+1 n FROM workout_exercises WHERE workout_id=?',(wid,),one=True)['n']
    weid = insert('INSERT INTO workout_exercises(workout_id,exercise_id,order_index,superset_group) VALUES(?,?,?,?)',(wid,request.form['exercise_id'],order,request.form.get('superset_group','').strip().upper()))
    mark_recent_exercise(request.form['exercise_id'], 'workout')
    for sn in range(1, int(request.form.get('sets',3))+1):
        insert('INSERT INTO workout_sets(workout_exercise_id,set_number,weight,reps,rpe) VALUES(?,?,?,?,?)',(weid,sn,0,0,None))
    return redirect(url_for('workout_detail', wid=wid))

@app.route('/workouts/<int:wid>/delete', methods=['POST'])
def workout_delete(wid):
    with db() as conn:
        we_ids = [r['id'] for r in conn.execute('SELECT id FROM workout_exercises WHERE workout_id=?', (wid,)).fetchall()]
        for weid in we_ids:
            conn.execute('DELETE FROM workout_sets WHERE workout_exercise_id=?', (weid,))
        conn.execute('DELETE FROM workout_exercises WHERE workout_id=?', (wid,))
        conn.execute('DELETE FROM workouts WHERE id=?', (wid,))
        conn.commit()
    flash('Workout deleted.')
    return redirect(url_for('workouts'))


@app.route('/workouts/<int:wid>/exercises/<int:weid>/delete', methods=['POST'])
def workout_delete_exercise(wid, weid):
    with db() as conn:
        conn.execute('DELETE FROM workout_sets WHERE workout_exercise_id=?', (weid,))
        conn.execute('DELETE FROM workout_exercises WHERE id=? AND workout_id=?', (weid, wid))
        conn.commit()
    flash('Exercise removed from workout.')
    return redirect(url_for('workout_detail', wid=wid))


@app.route('/workouts/<int:wid>/sets/<int:sid>/delete', methods=['POST'])
def workout_delete_set(wid, sid):
    q('DELETE FROM workout_sets WHERE id=?', (sid,), commit=True)
    flash('Set removed.')
    return redirect(url_for('workout_detail', wid=wid))


@app.route('/workouts/<int:wid>/duplicate', methods=['POST'])
def workout_duplicate(wid):
    with db() as conn:
        w=conn.execute('SELECT * FROM workouts WHERE id=?',(wid,)).fetchone()
        if not w:
            flash('Workout not found.'); return redirect(url_for('workouts'))
        cur=conn.execute('INSERT INTO workouts(name,date,routine_id,source,duration_min,bodyweight,readiness,mood,notes,fatigue,focus) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(
            (w['name'] or 'Workout') + ' copy', datetime.date.today().isoformat(), w['routine_id'], 'ATHENA', w['duration_min'], w['bodyweight'], w['readiness'], w['mood'], 'Duplicated from '+str(w['date'])+'. '+(w['notes'] or ''), w['fatigue'], w['focus']))
        new_wid=cur.lastrowid
        exs=conn.execute('SELECT * FROM workout_exercises WHERE workout_id=? ORDER BY order_index',(wid,)).fetchall()
        for ex in exs:
            new_we=conn.execute('INSERT INTO workout_exercises(workout_id,exercise_id,order_index,superset_group) VALUES(?,?,?,?)',(new_wid,ex['exercise_id'],ex['order_index'],ex['superset_group'] if 'superset_group' in ex.keys() else '')).lastrowid
            sets=conn.execute('SELECT * FROM workout_sets WHERE workout_exercise_id=? ORDER BY set_number',(ex['id'],)).fetchall()
            for st in sets:
                conn.execute('''INSERT INTO workout_sets(workout_exercise_id,set_number,weight,reps,rpe,notes,set_type,additional_weight,duration_seconds,distance_m,calories,avg_hr,rounds,work_seconds,rest_seconds) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(
                    new_we, st['set_number'], st['weight'], st['reps'], st['rpe'], st['notes'], st['set_type'], st['additional_weight'], st['duration_seconds'], st['distance_m'], st['calories'], st['avg_hr'], st['rounds'], st['work_seconds'], st['rest_seconds']))
        conn.commit()
    flash('Workout duplicated. Review and edit the copy before training.')
    return redirect(url_for('workout_detail', wid=new_wid))

def set_pr_score(row, exercise_type):
    t=(exercise_type or 'Strength').lower()
    if t in ('strength','bodyweight'):
        return float(row['weight'] or 0) * float(row['reps'] or 0) + float(row['additional_weight'] or 0) * float(row['reps'] or 0)
    if t == 'timed' or t == 'mobility': return float(row['duration_seconds'] or 0)
    if t == 'cardio': return float(row['distance_m'] or 0) + float(row['duration_seconds'] or 0)/10 + float(row['calories'] or 0)
    if t == 'distance': return float(row['weight'] or 0) * max(1,float(row['distance_m'] or 0))
    if t == 'interval': return float(row['rounds'] or 0) * float(row['work_seconds'] or 0)
    return float(row['weight'] or 0) * float(row['reps'] or 0)

def workout_prs(wid):
    current=q('''SELECT e.id exercise_id,e.name,e.exercise_type,ws.* FROM workout_sets ws JOIN workout_exercises we ON we.id=ws.workout_exercise_id JOIN exercises e ON e.id=we.exercise_id WHERE we.workout_id=?''',(wid,))
    prs=[]
    for row in current:
        score=set_pr_score(row,row['exercise_type'])
        if score<=0: continue
        prev=q('''SELECT e.exercise_type,ws.* FROM workout_sets ws JOIN workout_exercises we ON we.id=ws.workout_exercise_id JOIN exercises e ON e.id=we.exercise_id WHERE e.id=? AND we.workout_id<>?''',(row['exercise_id'],wid))
        best=max([set_pr_score(p,row['exercise_type']) for p in prev] or [0])
        if score>best:
            prs.append({'exercise':row['name'],'set':row['set_number'],'display':set_display(row,row['exercise_type']),'score':round(score,1),'previous':round(best,1)})
    return prs

@app.route('/workouts/<int:wid>/summary')
def workout_summary(wid):
    workout=q('SELECT * FROM workouts WHERE id=?',(wid,),one=True)
    return render_template('workout_summary.html', workout=workout, summary=workout_volume(wid), prs=workout_prs(wid), signal=coach_signal_v2())

@app.route('/ris', methods=['GET','POST'])
def ris():
    computed = None
    if request.method == 'POST':
        sex = request.form.get('sex') or 'Men'
        bodyweight = float(request.form.get('bodyweight') or 0)
        ris_type = request.form.get('ris_type') or 'ALL-4'
        pullup = float(request.form.get('pullup') or 0)
        dip = float(request.form.get('dip') or 0)
        squat = float(request.form.get('squat') or 0)
        muscleup = float(request.form.get('muscleup') or 0)
        if ris_type == 'UPPER':
            total = pullup + dip
        else:
            total = pullup + dip + squat + muscleup
        computed = round(ris_score(sex, bodyweight, total, ris_type), 2)
        category = ris_category(computed)
        insert('''INSERT INTO ris_tests(date,sex,bodyweight,total,ris_score,category,notes,ris_type,pullup,dip,squat,muscleup)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''', (
            request.form.get('date') or datetime.date.today().isoformat(), sex, bodyweight, total, computed, category, request.form.get('notes',''), ris_type, pullup, dip, squat, muscleup
        ))
        flash(f'{ris_type} RIS saved: {computed} - {category}.')
        return redirect(url_for('ris'))
    rows = q('SELECT * FROM ris_tests ORDER BY date DESC, id DESC')
    latest_weight = q('SELECT bodyweight FROM wellness WHERE bodyweight IS NOT NULL ORDER BY date DESC LIMIT 1', one=True)
    return render_template('ris.html', rows=rows, latest_weight=(latest_weight['bodyweight'] if latest_weight else ''), today=datetime.date.today().isoformat(), history=ris_history_data())

@app.route('/wellness', methods=['GET','POST'])
def wellness():
    if request.method == 'POST':
        insert('INSERT INTO wellness(date,bodyweight,sleep_hours,energy,soreness,stress,mood,notes) VALUES(?,?,?,?,?,?,?,?)',(request.form['date'],request.form.get('bodyweight') or None,request.form.get('sleep_hours') or None,request.form.get('energy') or 5,request.form.get('soreness') or 5,request.form.get('stress') or 5,request.form.get('mood'),request.form.get('notes','')))
        flash('Daily readiness check saved.')
        return redirect(url_for('wellness'))
    return render_template('wellness.html', rows=q('SELECT * FROM wellness ORDER BY date DESC'))

@app.route('/import-hevy', methods=['GET','POST'])
def import_hevy():
    imported = None
    error = None
    preview = None
    if request.method == 'POST':
        mode = request.form.get('mode')
        if mode == 'demo':
            imported = create_demo_hevy_import()
        elif mode == 'json':
            try:
                import json
                preview = import_hevy_payload(json.loads(request.form.get('payload','{}')))
                imported = preview
            except Exception as e:
                error = f'JSON import failed: {e}'
        else:
            key = request.form.get('api_key') or os.getenv('HEVY_API_KEY')
            if not key:
                error = 'Add a Hevy Pro API key or use demo import.'
            elif requests is None:
                error = 'The requests package is not installed.'
            else:
                try:
                    per_page = int(request.form.get('per_page') or 10)
                    max_pages = int(request.form.get('max_pages') or 50)
                    include_measurements = bool(request.form.get('include_measurements'))
                    fetched = fetch_hevy_full_import(key, per_page=per_page, max_pages=max_pages, include_measurements=include_measurements)
                    imported = import_hevy_payload(fetched)
                    if isinstance(imported, dict):
                        imported['workout_pages_scanned'] = fetched.get('_meta', {}).get('workout_pages_scanned', 0)
                        imported['measurement_pages_scanned'] = fetched.get('_meta', {}).get('measurement_pages_scanned', 0)
                except Exception as e:
                    error = str(e)
    recent_imports = q("SELECT * FROM workouts WHERE source='HEVY' ORDER BY date DESC, id DESC LIMIT 8")
    return render_template('import_hevy.html', imported=imported, error=error, recent_imports=recent_imports)

def create_demo_hevy_import():
    payload = {
        'workouts': [
            {
                'id': 'demo-' + uuid.uuid4().hex[:6],
                'title': 'Hevy Import - Push Strength',
                'start_time': datetime.datetime.now().isoformat(),
                'description': 'Demo payload imported through the same parser as real Hevy data.',
                'exercises': [
                    {'title': 'Bench Press', 'sets': [{'weight_kg': 80, 'reps': 5, 'rpe': 8, 'type': 'normal'}, {'weight_kg': 82.5, 'reps': 4, 'rpe': 8.5, 'type': 'normal'}]},
                    {'title': 'Overhead Press', 'sets': [{'weight_kg': 45, 'reps': 6, 'rpe': 8}, {'weight_kg': 47.5, 'reps': 5, 'rpe': 8.5}]}
                ]
            }
        ],
        'body_measurements': [
            {'date': (datetime.date.today() - datetime.timedelta(days=3)).isoformat(), 'weight_kg': 82.6},
            {'date': datetime.date.today().isoformat(), 'weight_kg': 82.3}
        ]
    }
    return import_hevy_payload(payload)


def hevy_headers(key, variant='api-key'):
    header_name = 'api-key' if variant == 'api-key' else 'x-api-key'
    return {header_name: key, 'accept': 'application/json'}


def hevy_get(key, endpoint, params=None):
    """GET wrapper with support for both header names seen in Hevy examples/community setups."""
    if requests is None:
        raise RuntimeError('The requests package is not installed.')
    url = f'https://api.hevyapp.com/v1/{endpoint.lstrip("/")}'
    params = params or {}
    res = requests.get(url, headers=hevy_headers(key, 'api-key'), params=params, timeout=20)
    if res.status_code in (401, 403):
        res = requests.get(url, headers=hevy_headers(key, 'x-api-key'), params=params, timeout=20)
    if res.status_code >= 400:
        raise RuntimeError(f'Hevy API returned HTTP {res.status_code} for /v1/{endpoint}. Check API key, Hevy Pro access and endpoint permissions.')
    return res.json()


def extract_collection(payload, preferred_keys):
    if isinstance(payload, list):
        return payload
    for key in preferred_keys:
        if isinstance(payload, dict) and isinstance(payload.get(key), list):
            return payload[key]
    return []


def fetch_hevy_paginated(key, endpoint, collection_keys, per_page=10, max_pages=50):
    """Fetch every page from a Hevy paginated endpoint.

    Hevy paginated responses include `page` and `page_count`. The app keeps calling
    page 1..page_count, so importing 54 workouts with 10 per page imports all 54,
    not only the first 10.
    """
    items = []
    page = 1
    pages_scanned = 0
    while page <= max_pages:
        payload = hevy_get(key, endpoint, params={'page': page, 'limit': per_page})
        batch = extract_collection(payload, collection_keys)
        items.extend(batch)
        pages_scanned += 1
        page_count = payload.get('page_count') if isinstance(payload, dict) else None
        current_page = payload.get('page') if isinstance(payload, dict) else page
        if page_count is not None:
            if int(current_page) >= int(page_count):
                break
        elif not batch:
            break
        page += 1
    return items, pages_scanned


def fetch_hevy_full_import(key, per_page=10, max_pages=50, include_measurements=True):
    workouts, workout_pages = fetch_hevy_paginated(key, 'workouts', ['workouts', 'items'], per_page, max_pages)
    measurements = []
    measurement_pages = 0
    if include_measurements:
        try:
            measurements, measurement_pages = fetch_hevy_paginated(key, 'body_measurements', ['body_measurements', 'items'], per_page, max_pages)
        except Exception as e:
            # Workouts remain importable even if body measurements are unavailable.
            measurements = []
            measurement_pages = 0
    return {
        'workouts': workouts,
        'body_measurements': measurements,
        '_meta': {'workout_pages_scanned': workout_pages, 'measurement_pages_scanned': measurement_pages}
    }


def normalize_date(value):
    if not value:
        return datetime.date.today().isoformat()
    return str(value)[:10]


def build_weight_lookup(measurements):
    result = []
    for m in measurements or []:
        if m.get('weight_kg') in (None, ''):
            continue
        result.append((normalize_date(m.get('date')), float(m.get('weight_kg'))))
    result.sort(key=lambda x: x[0])
    return result


def weight_for_date(weight_lookup, workout_date):
    """Use exact weight for the workout date or the latest known weight before that date."""
    if not weight_lookup:
        return None
    last = None
    for d, weight in weight_lookup:
        if d <= workout_date:
            last = weight
        else:
            break
    return last if last is not None else weight_lookup[-1][1]


def upsert_hevy_body_measurements(measurements):
    saved = 0
    for m in measurements or []:
        date = normalize_date(m.get('date'))
        weight = m.get('weight_kg')
        if weight in (None, ''):
            continue
        existing = q('SELECT id FROM wellness WHERE date=?', (date,), one=True)
        note = 'Imported bodyweight from Hevy body_measurements.'
        if existing:
            q('UPDATE wellness SET bodyweight=COALESCE(?, bodyweight), notes=CASE WHEN notes IS NULL OR notes="" THEN ? ELSE notes END WHERE id=?', (weight, note, existing['id']), commit=True)
        else:
            insert('INSERT INTO wellness(date,bodyweight,sleep_hours,energy,soreness,stress,mood,notes) VALUES(?,?,?,?,?,?,?,?)', (date, weight, None, 5, 5, 5, 'Neutral', note))
        saved += 1
    return saved



def infer_hevy_exercise_type(ex):
    sets = ex.get('sets') or []
    name = (ex.get('title') or ex.get('name') or '').lower()
    if any(k in name for k in ['run','treadmill','row','bike','cycle','cardio']): return 'Cardio'
    if any(k in name for k in ['plank','hang','hold','sit']): return 'Timed'
    if any(k in name for k in ['walk','carry']): return 'Distance'
    if any(('duration_seconds' in s or 'distance_meters' in s or 'distance_m' in s or 'calories' in s) for s in sets): return 'Cardio'
    if any(('additional_weight_kg' in s) for s in sets): return 'Bodyweight'
    return 'Strength'

def infer_hevy_metric_hint(ex):
    t = infer_hevy_exercise_type(ex)
    return {'Cardio':'Duration + distance + calories + heart rate','Timed':'Duration seconds','Distance':'Load + distance','Bodyweight':'Additional weight + reps','Strength':'Weight + reps'}.get(t,'Custom fields')

def import_hevy_payload(data):
    workouts = data.get('workouts') or data.get('items') or ([] if not isinstance(data, list) else data)
    measurements = data.get('body_measurements') or [] if isinstance(data, dict) else []
    weights = build_weight_lookup(measurements)
    measurements_saved = upsert_hevy_body_measurements(measurements)
    imported_workouts = 0
    skipped_workouts = 0
    sets_imported = 0

    for item in workouts:
        name = item.get('title') or item.get('name') or 'Hevy Workout'
        dt = normalize_date(item.get('start_time') or item.get('created_at') or item.get('date'))
        hevy_id = str(item.get('id') or uuid.uuid4().hex)
        if q('SELECT id FROM workouts WHERE hevy_id=?', (hevy_id,), one=True):
            skipped_workouts += 1
            continue
        bodyweight = item.get('bodyweight_kg') or item.get('weight_kg') or weight_for_date(weights, dt)
        notes = item.get('description') or item.get('notes') or 'Imported from Hevy API.'
        if bodyweight is not None:
            notes = f'{notes}\nBodyweight source: Hevy body_measurements / latest known weight.'
        wid = insert(
            'INSERT INTO workouts(name,date,source,duration_min,bodyweight,readiness,mood,notes,hevy_id,fatigue,focus) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (name, dt, 'HEVY', item.get('duration_min') or 60, bodyweight, 7, 'Good', notes, hevy_id, 4, 7)
        )
        for idx, ex in enumerate(item.get('exercises') or [], 1):
            ex_name = ex.get('title') or ex.get('name') or ex.get('exercise_template_title') or 'Imported Exercise'
            row = q('SELECT id FROM exercises WHERE lower(name)=lower(?)', (ex_name,), one=True)
            if not row:
                exid = insert(
                    'INSERT INTO exercises(name,muscle_group,equipment,notes,is_custom,description,ris_tag,exercise_type,metric_hint) VALUES(?,?,?,?,?,?,?,?,?)',
                    (ex_name, 'Full Body', 'Imported', 'Created during Hevy import.', 0, 'Imported exercise template matched from Hevy payload.', 'Imported', infer_hevy_exercise_type(ex), infer_hevy_metric_hint(ex))
                )
            else:
                exid = row['id']
            weid = insert('INSERT INTO workout_exercises(workout_id,exercise_id,order_index) VALUES(?,?,?)', (wid, exid, idx))
            for sn, st in enumerate(ex.get('sets') or [], 1):
                insert(
                    '''INSERT INTO workout_sets(workout_exercise_id,set_number,weight,reps,additional_weight,duration_seconds,distance_m,calories,avg_hr,rpe,set_type,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (weid, sn, st.get('weight_kg') or st.get('weight') or 0, st.get('reps') or 0, st.get('additional_weight_kg') or 0, st.get('duration_seconds') or st.get('duration') or 0, st.get('distance_meters') or st.get('distance_m') or 0, st.get('calories') or 0, st.get('avg_hr') or st.get('heart_rate') or 0, st.get('rpe'), st.get('type', 'Imported'), st.get('notes', ''))
                )
                sets_imported += 1
        imported_workouts += 1
    return {
        'workouts': imported_workouts,
        'skipped': skipped_workouts,
        'sets': sets_imported,
        'measurements': measurements_saved
    }


@app.route('/analytics')
def analytics():
    muscles=muscle_volume_data(); heat=heatmap_data(); bw=bodyweight_series(); workouts=q('SELECT * FROM workouts ORDER BY date DESC LIMIT 12')
    scored=[dict(w, session_score=session_score_value(w)) for w in workouts]
    return render_template('analytics.html', muscles=muscles, musclemap={m['muscle']:m['pct'] for m in muscles}, heat=heat, bodyweight=bw, bodyweight_center=bodyweight_center_data(), workouts=scored, balance_warnings=muscle_balance_warnings(), strength_trends=strength_trends(), volume_trends=volume_trends(), exercise_frequency=exercise_frequency(), pr_center=personal_records(10), intelligence=athlete_intelligence(), gamification=gamification_state())

@app.route('/progress')
def progress():
    rows=q('SELECT * FROM exercises ORDER BY name')
    return render_template('progress.html', rows=rows)

@app.route('/progress/<int:eid>')
def exercise_progress(eid):
    ex=q('SELECT * FROM exercises WHERE id=?',(eid,),one=True); rows=exercise_progress_rows(eid)
    points=[]; best=0
    for r in rows:
        score=metric_score(r); best=max(best,score); points.append({'date':r['date'],'workout':r['workout_name'],'display':set_display(r,r['exercise_type']),'score':round(score,1)})
    max_score=max([p['score'] for p in points] or [1]) or 1
    return render_template('exercise_progress_detail.html', ex=ex, points=points, max_score=max_score, best=round(best,1))

@app.route('/search')
def smart_search():
    term=(request.args.get('q') or '').strip(); like=f'%{term}%'; workouts=exercises=routines=[]
    if term:
        workouts=q('SELECT id,name,date,notes,source FROM workouts WHERE name LIKE ? OR date LIKE ? OR notes LIKE ? ORDER BY date DESC LIMIT 15',(like,like,like))
        exercises=q("""SELECT DISTINCT e.* FROM exercises e LEFT JOIN exercise_tag_map m ON m.exercise_id=e.id LEFT JOIN exercise_tags t ON t.id=m.tag_id WHERE e.name LIKE ? OR e.muscle_group LIKE ? OR e.equipment LIKE ? OR e.notes LIKE ? OR e.description LIKE ? OR t.name LIKE ? ORDER BY e.name LIMIT 20""",(like,like,like,like,like,like))
        routines=q('SELECT id,name,goal,intensity,notes FROM routines WHERE name LIKE ? OR goal LIKE ? OR notes LIKE ? ORDER BY created_at DESC LIMIT 15',(like,like,like))
    return render_template('search.html', term=term, workouts=workouts, exercises=exercises, routines=routines)

@app.route('/goals', methods=['GET','POST'])
def goals():
    if request.method=='POST':
        insert('INSERT INTO goals(title,metric,target,current,unit,notes,status) VALUES(?,?,?,?,?,?,?)',(request.form['title'],request.form['metric'],request.form['target'],request.form.get('current') or 0,request.form.get('unit',''),request.form.get('notes',''),'Active'))
        flash('Goal saved.'); return redirect(url_for('goals'))
    rows=q('SELECT * FROM goals ORDER BY CASE WHEN status="Completed" THEN 1 ELSE 0 END, id DESC'); total_workouts=q('SELECT COUNT(*) c FROM workouts',one=True)['c']; total_volume=q('SELECT COALESCE(SUM(weight*reps),0) v FROM workout_sets',one=True)['v'] or 0; best_ris=q('SELECT MAX(ris_score) v FROM ris_tests',one=True)['v'] or 0
    ach=[('First Workout', total_workouts>=1, f'{total_workouts} logged'),('10 Workouts', total_workouts>=10, f'{total_workouts}/10'),('10 000 kg Volume', total_volume>=10000, f'{int(total_volume)}/10000 kg'),('RIS 50+', best_ris>=50, f'{round(best_ris,1)} pts'),('RIS 75+', best_ris>=75, f'{round(best_ris,1)} pts')]
    return render_template('goals.html', rows=rows, achievements=ach)

@app.route('/goals/<int:gid>/update', methods=['POST'])
def goal_update(gid):
    action = request.form.get('action','save')
    if action == 'complete':
        q('UPDATE goals SET status=?, current=target, completed_at=? WHERE id=?', ('Completed', datetime.date.today().isoformat(), gid), commit=True)
        flash('Goal marked as completed.')
    elif action == 'reopen':
        q('UPDATE goals SET status=?, completed_at=? WHERE id=?', ('Active', '', gid), commit=True)
        flash('Goal reopened.')
    else:
        q('UPDATE goals SET title=?, metric=?, target=?, current=?, unit=?, notes=?, status=? WHERE id=?', (request.form['title'], request.form['metric'], request.form['target'], request.form.get('current') or 0, request.form.get('unit',''), request.form.get('notes',''), request.form.get('status','Active'), gid), commit=True)
        flash('Goal updated.')
    return redirect(url_for('goals'))

@app.route('/routines/<int:rid>/start')
def routine_start(rid):
    routine=q('SELECT * FROM routines WHERE id=?',(rid,),one=True)
    if not routine:
        flash('Routine not found.'); return redirect(url_for('routines'))
    with db() as conn:
        cur=conn.execute('INSERT INTO workouts(name,date,routine_id,source,duration_min,bodyweight,readiness,mood,notes,fatigue,focus) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(routine['name']+' - Session', datetime.date.today().isoformat(), rid, 'ATHENA', 60, None, 7, 'Good', 'Started from routine builder.', 4, 7))
        wid=cur.lastrowid; items=conn.execute('SELECT * FROM routine_exercises WHERE routine_id=? ORDER BY order_index',(rid,)).fetchall()
        for item in items:
            weid=conn.execute('INSERT INTO workout_exercises(workout_id,exercise_id,order_index,superset_group) VALUES(?,?,?,?)',(wid,item['exercise_id'],item['order_index'],item['superset_group'] if 'superset_group' in item.keys() else '')).lastrowid
            for sn in range(1,int(item['planned_sets'] or 1)+1): conn.execute('INSERT INTO workout_sets(workout_exercise_id,set_number,weight,reps,rpe) VALUES(?,?,?,?,?)',(weid,sn,0,0,None))
        conn.commit()
    flash('Workout started from routine. Fill the fields and save.'); return redirect(url_for('workout_detail',wid=wid))


@app.route('/exercises/<int:eid>/favorite', methods=['POST'])
def exercise_favorite_toggle(eid):
    exists = q('SELECT exercise_id FROM exercise_favorites WHERE exercise_id=?',(eid,),one=True)
    if exists:
        q('DELETE FROM exercise_favorites WHERE exercise_id=?',(eid,),commit=True); flash('Removed from favorites.')
    else:
        q('INSERT OR IGNORE INTO exercise_favorites(exercise_id) VALUES(?)',(eid,),commit=True); flash('Added to favorites.')
    return redirect(request.referrer or url_for('exercises'))

@app.route('/exercises/<int:eid>/substitutions/add', methods=['POST'])
def exercise_substitution_add(eid):
    sid=request.form.get('substitute_id')
    if sid and str(sid) != str(eid):
        q('INSERT OR IGNORE INTO exercise_substitutions(exercise_id,substitute_id,note) VALUES(?,?,?)',(eid,sid,request.form.get('note','')),commit=True)
        flash('Substitution added.')
    return redirect(request.referrer or url_for('exercises'))

@app.route('/exercises/substitutions/<int:sid>/delete', methods=['POST'])
def exercise_substitution_delete(sid):
    q('DELETE FROM exercise_substitutions WHERE id=?',(sid,),commit=True)
    flash('Substitution removed.')
    return redirect(request.referrer or url_for('exercises'))


@app.route('/exercises/<int:eid>/substitutions/auto', methods=['POST'])
def exercise_substitution_auto(eid):
    added=0
    for cand in smart_substitution_candidates(eid, 5):
        q('INSERT OR IGNORE INTO exercise_substitutions(exercise_id,substitute_id,note) VALUES(?,?,?)',(eid,cand['id'],'ATHENA smart suggestion: '+cand.get('smart_reason','similar movement')),commit=True)
        added+=1
    flash(f'Smart substitutions generated: {added}.')
    return redirect(request.referrer or url_for('exercises'))

@app.route('/exercises/<int:eid>/checklists/add', methods=['POST'])
def exercise_checklist_add(eid):
    cue=(request.form.get('cue') or '').strip()
    if cue:
        order=q('SELECT COALESCE(MAX(item_order),0)+1 n FROM exercise_checklists WHERE exercise_id=?',(eid,),one=True)['n'] or 1
        q('INSERT INTO exercise_checklists(exercise_id,item_order,cue) VALUES(?,?,?)',(eid,order,cue),commit=True)
        flash('Checklist cue added.')
    return redirect(request.referrer or url_for('exercises'))

@app.route('/exercises/<int:eid>/checklists/generate', methods=['POST'])
def exercise_checklist_generate(eid):
    ex=q('SELECT * FROM exercises WHERE id=?',(eid,),one=True)
    if ex:
        existing=q('SELECT COUNT(*) c FROM exercise_checklists WHERE exercise_id=?',(eid,),one=True)['c'] or 0
        for i,cue in enumerate(default_checklist_for_exercise(ex), start=existing+1):
            q('INSERT INTO exercise_checklists(exercise_id,item_order,cue) VALUES(?,?,?)',(eid,i,cue),commit=True)
        flash('Form checklist generated.')
    return redirect(request.referrer or url_for('exercises'))

@app.route('/exercises/checklists/<int:cid>/delete', methods=['POST'])
def exercise_checklist_delete(cid):
    q('DELETE FROM exercise_checklists WHERE id=?',(cid,),commit=True)
    flash('Checklist cue removed.')
    return redirect(request.referrer or url_for('exercises'))

@app.route('/records')
def records():
    return render_template('records.html', records=personal_records(50))



@app.route('/workouts/<int:wid>/replay')
def workout_replay(wid):
    workout=q('SELECT * FROM workouts WHERE id=?',(wid,),one=True)
    rows=q('''SELECT we.order_index,e.name,e.exercise_type,ws.* FROM workout_sets ws JOIN workout_exercises we ON we.id=ws.workout_exercise_id JOIN exercises e ON e.id=we.exercise_id WHERE we.workout_id=? ORDER BY we.order_index,ws.set_number''',(wid,))
    timeline=[]; minute=0
    for r in rows:
        if r['set_number']==1:
            minute+=3; timeline.append({'time':minute,'title':r['name'],'detail':'Exercise started'})
        timeline.append({'time':minute+int(r['set_number'] or 1),'title':'Set '+str(r['set_number']),'detail':set_display(r,r['exercise_type'])})
    summary=workout_volume(wid)
    return render_template('workout_replay.html', workout=workout, rows=rows, timeline=timeline, summary=summary)

@app.route('/workouts/<int:wid>/compare')
def workout_compare(wid):
    workout=q('SELECT * FROM workouts WHERE id=?',(wid,),one=True)
    prev=previous_similar_workout(workout)
    current=workout_volume(wid)
    previous=workout_volume(prev['id']) if prev else None
    return render_template('workout_compare.html', workout=workout, prev=prev, current=current, previous=previous)

@app.route('/bodyweight')
def bodyweight_center():
    return redirect(url_for('analytics') + '#bodyweight')

@app.route('/ris-history')
def ris_history():
    return redirect(url_for('ris'))

WORKOUT_TEMPLATE_LIBRARY = [
    {'slug':'push-strength','name':'Push Strength','category':'Strength','intensity':'Medium-High','goal':'Pressing strength and upper-body power','notes':'Bench, overhead press, dips and triceps support.', 'items':[('Bench Press',4,'5-6',150),('Overhead Press',3,'5-8',120),('Dip',3,'6-10',120),('Dumbbell Curl',2,'10-12',75)]},
    {'slug':'pull-strength','name':'Pull Strength','category':'Strength','intensity':'Medium','goal':'Pull-up strength, back density and grip','notes':'Pull-ups, pulldowns, rows and hangs.', 'items':[('Pull Up',4,'5-8',150),('Lat Pulldown',3,'8-12',90),('Rowing Machine',2,'8-10 min',90),('Dead Hang',3,'30-60s',75)]},
    {'slug':'lower-base','name':'Lower Base','category':'Strength','intensity':'Medium','goal':'Squat and posterior-chain foundation','notes':'Lower-body base with hinge and loaded carry.', 'items':[('Squat',4,'5-8',150),('Romanian Deadlift',3,'6-10',120),('Farmer Walk',3,'30-40m',90),('Mobility Flow',1,'8-12 min',60)]},
    {'slug':'full-body','name':'Full Body Performance','category':'Hybrid','intensity':'Medium','goal':'Balanced full-body session','notes':'Simple full-body template for busy weeks.', 'items':[('Squat',3,'5-8',120),('Bench Press',3,'6-8',120),('Pull Up',3,'6-10',120),('Plank',3,'45-75s',60)]},
    {'slug':'muscle-up-progression','name':'Muscle-Up Progression','category':'Street Workout','intensity':'Medium','goal':'Build explosive pulling and transition capacity','notes':'Street workout skill template.', 'items':[('Pull Up',4,'5-8',120),('Chest To Bar Pull Up',3,'3-5',120),('Dip',3,'6-10',90),('Dead Hang',2,'45-60s',60)]},
    {'slug':'conditioning-recovery','name':'Conditioning + Recovery','category':'Recovery','intensity':'Low-Medium','goal':'Aerobic work and tissue quality','notes':'Useful after heavy days or during deloads.', 'items':[('Treadmill Run',1,'20-30 min',60),('Rowing Machine',1,'8-12 min',60),('Mobility Flow',1,'10-15 min',60),('Plank',2,'45-60s',60)]},
]

@app.route('/templates')
def template_marketplace():
    rows=q('SELECT * FROM routines ORDER BY name')
    return render_template('templates_marketplace.html', rows=rows, templates=WORKOUT_TEMPLATE_LIBRARY)

@app.route('/templates/use/<slug>', methods=['POST'])
def template_use(slug):
    tpl=next((t for t in WORKOUT_TEMPLATE_LIBRARY if t['slug']==slug), None)
    if not tpl:
        flash('Template not found.'); return redirect(url_for('template_marketplace'))
    with db() as conn:
        rid=conn.execute('INSERT INTO routines(name,goal,intensity,notes) VALUES(?,?,?,?)',(tpl['name'],tpl['goal'],tpl['intensity'],tpl['notes'])).lastrowid
        for idx,(exname,sets,reps,rest) in enumerate(tpl['items'], start=1):
            ex=conn.execute('SELECT id FROM exercises WHERE name=?',(exname,)).fetchone()
            if not ex:
                ex=conn.execute('SELECT id FROM exercises WHERE name LIKE ? ORDER BY name LIMIT 1',(f'%{exname.split()[0]}%',)).fetchone()
            if ex:
                conn.execute('INSERT INTO routine_exercises(routine_id,exercise_id,planned_sets,target_reps,rest_seconds,order_index) VALUES(?,?,?,?,?,?)',(rid,ex['id'],sets,reps,rest,idx))
        conn.commit()
    flash('Template copied into your routines.')
    return redirect(url_for('routine_detail', rid=rid))

@app.route('/coach')
def coach_preview():
    return redirect(url_for('coaching_locked'))




def compliance_engine_v2(days=28):
    base=training_compliance(days)
    today=datetime.date.today(); start=(today-datetime.timedelta(days=days)).isoformat()
    skill_done=q('SELECT COUNT(*) c FROM skill_steps WHERE completed=1', one=True)['c'] or 0
    skill_total=q('SELECT COUNT(*) c FROM skill_steps', one=True)['c'] or 0
    recovery_logs=q('SELECT COUNT(*) c FROM wellness WHERE date>=?',(start,),one=True)['c'] or 0
    recovery_target=max(1, min(days, 7 if days>=7 else days))
    quest_done=q('SELECT COUNT(*) c FROM quests WHERE status="Completed" AND (completed_at>=? OR completed_at="")',(start,),one=True)['c'] or 0
    quest_total=q('SELECT COUNT(*) c FROM quests', one=True)['c'] or 0
    def pct(done,target): return round((done/max(1,target))*100,1)
    categories=[
        {'key':'training','label':'Training','done':base['completed'],'target':base['planned'],'rate':base['rate'],'hint':'Planned sessions completed.'},
        {'key':'skills','label':'Skills','done':skill_done,'target':max(skill_total,1),'rate':pct(skill_done,skill_total or 1),'hint':'Completed skill progression steps.'},
        {'key':'recovery','label':'Recovery','done':recovery_logs,'target':recovery_target,'rate':min(100,pct(recovery_logs,recovery_target)),'hint':'Wellness / recovery logs in the current window.'},
        {'key':'quests','label':'Quests','done':quest_done,'target':max(quest_total,1),'rate':pct(quest_done,quest_total or 1),'hint':'Completed active ATHENA quests.'},
    ]
    overall=round(sum([c['rate'] for c in categories])/len(categories),1)
    return {'overall':overall,'categories':categories,'days':days,'label':'Excellent' if overall>=85 else ('Stable' if overall>=70 else 'Needs attention')}

def training_compliance(days=28):
    today=datetime.date.today(); start=(today-datetime.timedelta(days=days)).isoformat()
    completed=q('SELECT COUNT(*) c FROM workouts WHERE date>=?',(start,),one=True)['c'] or 0
    planned=q('SELECT COUNT(*) c FROM program_days',one=True)['c'] or 0
    planned=max(planned, completed, 1)
    return {'planned':planned,'completed':completed,'rate':round((completed/planned)*100,1),'days':days}

def coach_signal_v2():
    base=training_advisor(); ready=readiness_v2(); recent=q('SELECT * FROM workouts ORDER BY date DESC LIMIT 7')
    avg=round(sum([(r['fatigue'] or 0) for r in recent]) / max(1,len(recent)),1)
    comp=training_compliance(); reasons=[]
    if ready['score']<60: reasons.append('readiness below build threshold')
    if avg>=6: reasons.append('7-session fatigue trend is elevated')
    if comp['rate']<80: reasons.append('training compliance needs stabilization')
    if not reasons: reasons=['readiness, fatigue and consistency are aligned']
    return dict(title=base['title'], text=base['text'], tone=base['tone'], readiness=ready, avg_fatigue=avg, compliance=comp, reasons=reasons)

@app.route('/execute')
def execute_hub():
    rows=q('SELECT w.*, r.name routine_name, COUNT(DISTINCT we.id) exercise_count, COUNT(ws.id) set_count FROM workouts w LEFT JOIN routines r ON r.id=w.routine_id LEFT JOIN workout_exercises we ON we.workout_id=w.id LEFT JOIN workout_sets ws ON ws.workout_exercise_id=we.id GROUP BY w.id ORDER BY w.date DESC,w.id DESC LIMIT 10')
    return render_template('execute_hub.html', rows=rows, routines=q('SELECT * FROM routines ORDER BY name'), signal=coach_signal_v2())

@app.route('/workouts/<int:wid>/execute', methods=['GET','POST'])
def workout_execute(wid):
    if request.method == 'POST':
        for sid in request.form.getlist('set_ids'):
            q('UPDATE workout_sets SET weight=?, reps=?, additional_weight=?, duration_seconds=?, distance_m=?, calories=?, avg_hr=?, rounds=?, work_seconds=?, rest_seconds=?, rpe=?, notes=?, set_type=? WHERE id=?',(request.form.get(f'weight_{sid}',0) or 0, request.form.get(f'reps_{sid}',0) or 0, request.form.get(f'addwt_{sid}',0) or 0, request.form.get(f'duration_{sid}',0) or 0, request.form.get(f'distance_{sid}',0) or 0, request.form.get(f'calories_{sid}',0) or 0, request.form.get(f'avghr_{sid}',0) or 0, request.form.get(f'rounds_{sid}',0) or 0, request.form.get(f'worksec_{sid}',0) or 0, request.form.get(f'restsec_{sid}',0) or 0, clean_rpe(request.form.get(f'rpe_{sid}')), request.form.get(f'setnotes_{sid}',''), request.form.get(f'settype_{sid}','Working'), sid),commit=True)
        q('UPDATE workouts SET duration_min=?, readiness=?, fatigue=?, focus=?, notes=? WHERE id=?',(request.form.get('duration_min') or 0, request.form.get('readiness') or 7, request.form.get('fatigue') or 4, request.form.get('focus') or 7, request.form.get('notes',''), wid), commit=True)
        flash('Execution saved. Session summary generated.'); return redirect(url_for('workout_summary', wid=wid))
    workout=q('SELECT w.*,r.name routine_name FROM workouts w LEFT JOIN routines r ON r.id=w.routine_id WHERE w.id=?',(wid,),one=True)
    exs=q('SELECT we.id weid,we.superset_group,e.* FROM workout_exercises we JOIN exercises e ON e.id=we.exercise_id WHERE we.workout_id=? ORDER BY we.order_index',(wid,))
    sets={e['weid']:q('SELECT * FROM workout_sets WHERE workout_exercise_id=? ORDER BY set_number',(e['weid'],)) for e in exs}
    return render_template('workout_execute.html', workout=workout, exs=exs, sets=sets, summary=workout_volume(wid), signal=coach_signal_v2(), warmup=warmup_plan_for_exercises(exs), previous=previous_session_map(wid), progression=progression_suggestions(wid), intelligence=athlete_intelligence())

@app.route('/athlete', methods=['GET','POST'])
def athlete_profile():
    if request.method=='POST':
        profile=q('SELECT * FROM athlete_profile WHERE id=1', one=True)
        avatar_path=profile['avatar_path'] if profile and 'avatar_path' in profile.keys() else ''
        file=request.files.get('avatar')
        if file and file.filename and allowed_image(file.filename):
            fname='athlete_' + uuid.uuid4().hex[:10] + '_' + secure_filename(file.filename)
            file.save(UPLOAD_DIR / fname)
            avatar_path='uploads/' + fname
        full_name = request.form.get('name','ATHENA Athlete').strip() or 'ATHENA Athlete'
        first_name = full_name.split()[0] if full_name.split() else 'Athlete'
        q('''UPDATE athlete_profile SET name=?,preferred_name=?,experience=?,primary_goal=?,height_cm=?,weight_kg=?,body_fat=?,bench=?,squat=?,deadlift=?,pullup=?,dip=?,muscleup=?,coach_status=?,training_age_years=?,weekly_target=?,equipment=?,training_focus=?,skill_focus=?,recovery_priority=?,avatar_path=?,notes=?,updated_at=CURRENT_TIMESTAMP WHERE id=1''',(
            full_name, first_name, request.form.get('experience','Intermediate'), request.form.get('primary_goal',''), request.form.get('height_cm') or None, request.form.get('weight_kg') or None, request.form.get('body_fat') or None, request.form.get('bench') or 0, request.form.get('squat') or 0, request.form.get('deadlift') or 0, request.form.get('pullup') or 0, request.form.get('dip') or 0, request.form.get('muscleup') or 0, request.form.get('coach_status','Solo training'), request.form.get('training_age_years') or 0, request.form.get('weekly_target') or 4, request.form.get('equipment','Gym + bodyweight'), request.form.get('training_focus','Strength + skill'), request.form.get('skill_focus','Muscle Up'), request.form.get('recovery_priority','Sleep + fatigue management'), avatar_path, request.form.get('notes','')
        ),commit=True)
        q('UPDATE onboarding_settings SET completed=1, primary_goal=?, experience=?, training_days=?, equipment=?, preferred_style=?, updated_at=CURRENT_TIMESTAMP WHERE id=1', (request.form.get('primary_goal','Strength'), request.form.get('experience','Intermediate'), request.form.get('weekly_target') or 4, request.form.get('equipment','Gym + bodyweight'), request.form.get('training_focus','Strength + skill')), commit=True)
        flash('Athlete profile updated.'); return redirect(url_for('athlete_profile'))
    profile_row=q('SELECT * FROM athlete_profile WHERE id=1',one=True)
    return render_template('athlete.html', profile=profile_row, first_name=first_name_from_profile(profile_row), display_name=first_name_from_profile(profile_row), onboarding=onboarding_state(), level=athlete_level(), readiness=readiness_v2(), compliance=training_compliance(), records=personal_records(8), attributes=rpg_attributes(), weekly=weekly_review_data(), gamification=gamification_state(), daily=athena_daily_score(), intelligence=athlete_intelligence(), achievements=achievement_catalog(), top_skills=q('SELECT * FROM athlete_skills ORDER BY progress DESC,name LIMIT 3'))

@app.route('/programs', methods=['GET','POST'])
def programs():
    if request.method=='POST':
        pid=insert('INSERT INTO programs(name,goal,duration_weeks,status,notes,phase_model) VALUES(?,?,?,?,?,?)',(request.form['name'],request.form.get('goal',''),request.form.get('duration_weeks') or 4,request.form.get('status','Draft'),request.form.get('notes',''),request.form.get('phase_model','Foundation / Build / Peak / Deload')))
        flash('Program created. Add training days below.'); return redirect(url_for('program_detail', pid=pid))
    rows=q('SELECT p.*, COUNT(d.id) day_count FROM programs p LEFT JOIN program_days d ON d.program_id=p.id GROUP BY p.id ORDER BY p.created_at DESC')
    return render_template('programs.html', rows=rows, compliance=training_compliance())

@app.route('/programs/<int:pid>', methods=['GET','POST'])
def program_detail(pid):
    if request.method=='POST':
        insert('INSERT INTO program_days(program_id,week_number,day_name,routine_id,focus,notes,phase,intensity_target) VALUES(?,?,?,?,?,?,?,?)',(pid,request.form.get('week_number') or 1,request.form.get('day_name','Monday'),request.form.get('routine_id') or None,request.form.get('focus',''),request.form.get('notes',''),request.form.get('phase','Build'),request.form.get('intensity_target','RPE 7-8')))
        flash('Program day added.'); return redirect(url_for('program_detail', pid=pid))
    program=q('SELECT * FROM programs WHERE id=?',(pid,),one=True)
    days=q('SELECT d.*,r.name routine_name FROM program_days d LEFT JOIN routines r ON r.id=d.routine_id WHERE d.program_id=? ORDER BY d.week_number,d.id',(pid,))
    return render_template('program_detail.html', program=program, days=days, routines=q('SELECT * FROM routines ORDER BY name'))


@app.route('/programs/<int:pid>/days/<int:day_id>/edit', methods=['POST'])
def program_day_edit(pid, day_id):
    q('''UPDATE program_days SET week_number=?, day_name=?, routine_id=?, focus=?, notes=?, phase=?, intensity_target=? WHERE id=? AND program_id=?''',(
        request.form.get('week_number') or 1, request.form.get('day_name','Monday'), request.form.get('routine_id') or None, request.form.get('focus',''), request.form.get('notes',''), request.form.get('phase','Build'), request.form.get('intensity_target','RPE 7-8'), day_id, pid
    ), commit=True)
    flash('Program day updated.')
    return redirect(url_for('program_detail', pid=pid))

@app.route('/programs/<int:pid>/days/<int:day_id>/delete', methods=['POST'])
def program_day_delete(pid, day_id):
    q('DELETE FROM program_days WHERE id=? AND program_id=?', (day_id, pid), commit=True)
    flash('Program day deleted.')
    return redirect(url_for('program_detail', pid=pid))

@app.route('/coaching')
def coaching_locked():
    return render_template('coaching_locked.html', signal=coach_signal_v2(), compliance=training_compliance(), level=athlete_level())

@app.route('/roadmap')
def athena_roadmap():
    return render_template('roadmap.html')

@app.route('/api/search')
def api_search():
    term=(request.args.get('q') or '').strip()
    if not term:
        return jsonify([
            {'type':'Action','title':'Start a workout','meta':'Open workout logger','url':url_for('workout_new')},
            {'type':'Action','title':'Open RIS Lab','meta':'Review strength score trend inside RIS Lab','url':url_for('ris')},
            {'type':'Action','title':'Import from Hevy','meta':'Sync workouts and bodyweight','url':url_for('import_hevy')},
            {'type':'Action','title':'Open templates','meta':'Start from ATHENA routines','url':url_for('template_marketplace')},
        ])
    like=f'%{term}%'
    out=[]
    actions=[('start workout','Action','Start a workout','Open workout logger',url_for('workout_new')),('log workout','Action','Log new workout','Open workout logger',url_for('workout_new')),('ris','Action','Open RIS Lab','Calculate ALL-4 or UPPER score',url_for('ris')),('ris history','Action','Open RIS Lab','Review strength score trend inside RIS Lab',url_for('ris')),('hevy','Action','Import from Hevy','Sync workouts and bodyweight',url_for('import_hevy')),('template','Action','Workout templates','Open routine marketplace',url_for('template_marketplace')),('execute','Action','Workout Execution','Run a live workout session',url_for('execute_hub')),('athlete','Action','Athlete Profile','Open athlete profile',url_for('athlete_profile')),('program','Action','Program Builder','Build multi-week programs',url_for('programs')),('coaching','Action','Coaching Module','Locked future coach module',url_for('coaching_locked')),('roadmap','Action','ATHENA Roadmap','Open etap 1-8 roadmap',url_for('athena_roadmap')),('bodyweight','Action','Bodyweight analytics','Open bodyweight inside Analytics',url_for('analytics') + '#bodyweight')]
    low=term.lower()
    for key,t,title,meta,url in actions:
        if key in low or low in key:
            out.append({'type':t,'title':title,'meta':meta,'url':url})
    for w in q('SELECT id,name,date,notes,source FROM workouts WHERE name LIKE ? OR date LIKE ? OR notes LIKE ? ORDER BY date DESC LIMIT 6',(like,like,like)):
        out.append({'type':'Workout','title':w['name'],'meta':f"{w['date']} - {w['source']}",'url':url_for('workout_detail', wid=w['id'])})
    for e in q("""SELECT DISTINCT e.id,e.name,e.muscle_group,e.exercise_type FROM exercises e LEFT JOIN exercise_tag_map m ON m.exercise_id=e.id LEFT JOIN exercise_tags t ON t.id=m.tag_id WHERE e.name LIKE ? OR e.muscle_group LIKE ? OR e.exercise_type LIKE ? OR t.name LIKE ? ORDER BY e.name LIMIT 6""",(like,like,like,like)):
        out.append({'type':'Exercise','title':e['name'],'meta':f"{e['muscle_group']} - {e['exercise_type']}",'url':url_for('exercise_progress', eid=e['id'])})
    for r in q('SELECT id,name,goal,intensity FROM routines WHERE name LIKE ? OR goal LIKE ? OR notes LIKE ? ORDER BY created_at DESC LIMIT 5',(like,like,like)):
        out.append({'type':'Routine','title':r['name'],'meta':f"{r['goal']} - {r['intensity']}",'url':url_for('routine_detail', rid=r['id'])})
    for g in q('SELECT id,title,metric,current,target,unit FROM goals WHERE title LIKE ? OR metric LIKE ? OR notes LIKE ? ORDER BY id DESC LIMIT 4',(like,like,like)):
        out.append({'type':'Goal','title':g['title'],'meta':f"{g['current']} / {g['target']} {g['unit']}",'url':url_for('goals')})
    return jsonify(out[:14])

@app.route('/api/exercises')
def api_exercises():
    return jsonify([dict(r) for r in q('SELECT * FROM exercises ORDER BY name')])


# ---------------- ATHENA Premium presentation features ----------------
def consistency_engine(days=30):
    today=datetime.date.today()
    dates={r['date'] for r in q('SELECT date FROM workouts WHERE date>=?', ((today-datetime.timedelta(days=days)).isoformat(),))}
    current=0
    d=today
    while d.isoformat() in dates:
        current+=1; d-=datetime.timedelta(days=1)
    best=0; run=0
    for i in range(days):
        d=(today-datetime.timedelta(days=days-1-i)).isoformat()
        if d in dates: run+=1; best=max(best,run)
        else: run=0
    return {'current': current, 'best': best, 'last_30': len(dates), 'days': days}

def athlete_level():
    best_ris=q('SELECT MAX(ris_score) v FROM ris_tests', one=True)['v'] or 0
    workouts=q('SELECT COUNT(*) c FROM workouts', one=True)['c'] or 0
    cons=consistency_engine(30)['last_30']
    score=(best_ris*0.55)+(min(workouts,100)*0.25)+(min(cons,25)*1.2)
    if score>=95: level='Master'
    elif score>=75: level='Elite'
    elif score>=55: level='Gold'
    elif score>=35: level='Silver'
    else: level='Bronze'
    return {'level':level,'score':round(score,1),'best_ris':round(best_ris,1),'workouts':workouts,'consistency':cons}

def readiness_v2():
    w=q('SELECT * FROM wellness ORDER BY date DESC LIMIT 1', one=True)
    latest=q('SELECT * FROM workouts ORDER BY date DESC LIMIT 1', one=True)
    if not w and not latest:
        return {'score':0,'label':'No data','sleep':0,'energy':0,'stress':0,'soreness':0,'hydration':7}
    sleep=float((w['sleep_hours'] if w else 7) or 7)
    energy=int((w['energy'] if w else (latest['readiness'] if latest else 7)) or 7)
    stress=int((w['stress'] if w else 4) or 4)
    soreness=int((w['soreness'] if w else 4) or 4)
    hydration=7
    score=(min(sleep,9)/9)*28 + (energy/10)*28 + (hydration/10)*14 + ((10-stress)/10)*15 + ((10-soreness)/10)*15
    score=max(0,min(100,score))
    label='Ready for heavy training' if score>=80 else ('Build session' if score>=60 else 'Recovery biased')
    return {'score':round(score),'label':label,'sleep':sleep,'energy':energy,'stress':stress,'soreness':soreness,'hydration':hydration}

def bodyweight_center_data():
    rows=q('SELECT date, bodyweight FROM wellness WHERE bodyweight IS NOT NULL ORDER BY date ASC')
    if not rows:
        rows=q('SELECT date, bodyweight FROM workouts WHERE bodyweight IS NOT NULL ORDER BY date ASC')
    current=rows[-1]['bodyweight'] if rows else None
    first=rows[0]['bodyweight'] if rows else None
    trend=(current-first) if current is not None and first is not None else 0
    return {'rows':rows,'first':first,'current':current,'trend':round(trend,1),'count':len(rows)}

def ris_history_data():
    rows=q('SELECT * FROM ris_tests ORDER BY date ASC, id ASC')
    best=max([r['ris_score'] for r in rows] or [0])
    return {'rows':rows,'best':best}

def workout_volume(wid):
    r=q('''SELECT COALESCE(SUM(CASE WHEN e.exercise_type="Bodyweight" THEN ws.additional_weight*ws.reps ELSE ws.weight*ws.reps END),0) v,
                 COUNT(ws.id) sets, COUNT(DISTINCT we.exercise_id) exercises
          FROM workout_sets ws JOIN workout_exercises we ON we.id=ws.workout_exercise_id JOIN exercises e ON e.id=we.exercise_id
          WHERE we.workout_id=?''',(wid,),one=True)
    return {'volume':round(r['v'] or 0,1),'sets':r['sets'],'exercises':r['exercises']}

def previous_similar_workout(workout):
    if not workout: return None
    return q('SELECT * FROM workouts WHERE name=? AND date<? ORDER BY date DESC LIMIT 1',(workout['name'],workout['date']),one=True)


# ---------------- ATHENA 8 Performance Engine ----------------
def gamification_state():
    workouts = q('SELECT COUNT(*) c FROM workouts', one=True)['c'] or 0
    prs = len(personal_records(999))
    streak = consistency_engine(30)['current']
    try:
        xp_row = q('SELECT COALESCE(SUM(points),0) v FROM xp_events', one=True)
        manual = xp_row['v'] if xp_row else 0
    except Exception:
        manual = 0
    total_xp = int(manual + workouts*50 + prs*25 + streak*15)
    
    # NOWOŚĆ: użycie dynamicznych poziomów
    lvl_data = get_level_from_xp(total_xp)
    talent_points_earned = max(0, lvl_data['level'] - 1)
    
    checks = [
        ('First Session', 'Log your first workout.', workouts >= 1),
        ('10 Workouts', 'Build a 10-session base.', workouts >= 10),
        ('First PR', 'Record a personal best.', prs >= 1),
        ('7-Day Streak', 'Train or log consistently for 7 days.', streak >= 7),
        ('RIS Initiate', 'Save your first RIS test.', (q('SELECT COUNT(*) c FROM ris_tests', one=True)['c'] or 0) >= 1)
    ]
    return {
        'xp': total_xp, 'level': lvl_data['level'], 'progress': lvl_data['xp_in_level'], 
        'next': lvl_data['remaining_xp'], 'pct': lvl_data['pct'], 'talent_points': talent_points_earned,
        'badges': [{'title': a, 'description': b, 'unlocked': c} for a, b, c in checks]
    }

def athlete_intelligence():
    r = readiness_v2()
    latest = q('SELECT * FROM workouts ORDER BY date DESC LIMIT 1', one=True)
    fatigue = int((latest['fatigue'] if latest else 4) or 4)
    recovery = max(0, min(100, round(r['score'] - max(0, fatigue - 5) * 7)))
    fatigue_label = 'Low' if fatigue <= 3 else ('Moderate' if fatigue <= 6 else 'High')
    
    # NOWOŚĆ: Składnik ACWR zintegrowany z modulami Inteligencji
    acwr = calculate_acwr_status()
    
    today = datetime.date.today()
    week_start = today - datetime.timedelta(days=today.weekday())
    done = q('SELECT COUNT(*) c FROM workouts WHERE date>=?', (week_start.isoformat(),), one=True)['c'] or 0
    planned = q('SELECT COUNT(*) c FROM program_days', one=True)['c'] or 0
    missed = max(0, min(planned, planned - done)) if planned else 0
    warnings = []
    if acwr['tone'] in ('warning', 'danger'):
        warnings.append(acwr['text'])
    if recovery < 55:
        warnings.append('Recovery is low. Reduce intensity, keep technique crisp, or use a lighter variation.')
    if fatigue >= 7:
        warnings.append('High fatigue detected. Avoid forced PR attempts today.')
    if missed >= 2:
        warnings.append(f'{missed} planned sessions appear to be missed this week. Consider a simpler schedule.')
    if not warnings:
        warnings.append(f'Training state looks stable. ACWR: {acwr["ratio"]} ({acwr["status"]}). Keep RPE honest.')
    return {'recovery': recovery, 'fatigue': fatigue, 'fatigue_label': fatigue_label, 'readiness': r, 'missed': missed, 'warnings': warnings, 'acwr': acwr}

def previous_session_map(wid):
    workout=q('SELECT * FROM workouts WHERE id=?',(wid,),one=True)
    if not workout: return {}
    exs=q('SELECT we.id weid,we.exercise_id,e.name,e.exercise_type FROM workout_exercises we JOIN exercises e ON e.id=we.exercise_id WHERE we.workout_id=?',(wid,))
    out={}
    for e in exs:
        prev=q("""SELECT w.date,w.name workout_name,ws.*,e.exercise_type FROM workout_sets ws JOIN workout_exercises we ON we.id=ws.workout_exercise_id JOIN workouts w ON w.id=we.workout_id JOIN exercises e ON e.id=we.exercise_id WHERE we.exercise_id=? AND w.date<? ORDER BY w.date DESC, ws.set_number ASC LIMIT 6""",(e['exercise_id'], workout['date']))
        out[e['weid']]=[dict(p, display=set_display(p,p['exercise_type'])) for p in prev]
    return out

def progression_suggestions(wid):
    exs=q('SELECT we.id weid,e.id exercise_id,e.name,e.exercise_type FROM workout_exercises we JOIN exercises e ON e.id=we.exercise_id WHERE we.workout_id=?',(wid,))
    out={}
    for e in exs:
        sets=q('SELECT * FROM workout_sets WHERE workout_exercise_id=?',(e['weid'],))
        work=[s for s in sets if (s['set_type'] or 'Working')!='Skipped']
        if not work:
            out[e['weid']]='Log at least one working set to generate a progression target.'; continue
        avg_rpe=sum([(s['rpe'] or 7) for s in work])/len(work)
        best=max(work, key=lambda s:set_pr_score(s,e['exercise_type']))
        if (e['exercise_type'] or '').lower() in ('strength','bodyweight'):
            load=(best['weight'] or 0) + (best['additional_weight'] or 0); reps=best['reps'] or 0
            if avg_rpe<=7 and reps>=5: msg=f'Next time: add 2.5 kg if warm-ups feel normal. Target {load+2.5:g} kg x {reps}.'
            elif avg_rpe>=9: msg=f'Next time: repeat {load:g} kg and make it cleaner before adding load.'
            else: msg=f'Next time: keep {load:g} kg and add 1 rep if technique stays stable.'
        elif (e['exercise_type'] or '').lower() in ('timed','mobility'):
            msg='Next time: add 10-20 seconds if the set stayed controlled.'
        elif (e['exercise_type'] or '').lower() in ('cardio','distance'):
            msg='Next time: add 3-5% distance or keep distance and improve pacing.'
        else:
            msg='Next time: progress the easiest metric by 5-10% only if RPE stays under 8.'
        out[e['weid']]=msg
    return out

def volume_trends():
    rows=q("""SELECT substr(w.date,1,7) period, COALESCE(SUM(CASE WHEN e.exercise_type='Bodyweight' THEN ws.additional_weight*ws.reps ELSE ws.weight*ws.reps END),0) volume, COUNT(DISTINCT w.id) sessions FROM workouts w JOIN workout_exercises we ON we.workout_id=w.id JOIN workout_sets ws ON ws.workout_exercise_id=we.id JOIN exercises e ON e.id=we.exercise_id GROUP BY period ORDER BY period DESC LIMIT 8""")
    return list(reversed([dict(r) for r in rows]))

def strength_trends():
    out=[]
    for ex in q("SELECT id,name,exercise_type FROM exercises WHERE exercise_type IN ('Strength','Bodyweight') ORDER BY name LIMIT 12"):
        rows=exercise_progress_rows(ex['id'])
        if len(rows)<2: continue
        first=max([metric_score(r) for r in rows[:max(1,len(rows)//2)]] or [0])
        last=max([metric_score(r) for r in rows[max(0,len(rows)//2):]] or [0])
        out.append({'name':ex['name'],'first':round(first,1),'last':round(last,1),'delta':round(last-first,1),'direction':'up' if last>first else ('flat' if last==first else 'down')})
    return sorted(out, key=lambda x:x['delta'], reverse=True)[:8]

def exercise_frequency():
    return q("""SELECT e.name,e.muscle_group,COUNT(DISTINCT we.workout_id) sessions FROM exercises e JOIN workout_exercises we ON we.exercise_id=e.id GROUP BY e.id ORDER BY sessions DESC, e.name LIMIT 10""")

@app.route('/intelligence')
def intelligence_center():
    return render_template('intelligence.html', intelligence=athlete_intelligence(), gamification=gamification_state(), signal=coach_signal_v2(), compliance=training_compliance(), plateaus=plateau_detection(), weak_points=weak_point_detection(), attributes=rpg_attributes())


@app.route('/onboarding', methods=['GET','POST'])
def onboarding():
    flash('Setup has moved into Athlete Profile so all personalization stays in one place.')
    return redirect(url_for('athlete_profile') + '#setup')


@app.route('/weekly-review')
def weekly_review():
    return render_template('weekly_review.html', review=weekly_review_data(), smart_plan=smart_today_plan(), catalog=achievement_catalog(), compliance_v2=compliance_engine_v2(), gamification=gamification_state())


@app.route('/achievements')
def achievements_center():
    return render_template('achievements.html', gamification=gamification_state(), level=athlete_level(), catalog=achievement_catalog())

@app.route('/programs/<int:pid>/duplicate', methods=['POST'])
def program_duplicate(pid):
    with db() as conn:
        p=conn.execute('SELECT * FROM programs WHERE id=?',(pid,)).fetchone()
        if not p:
            flash('Program not found.'); return redirect(url_for('programs'))
        new_id=conn.execute('INSERT INTO programs(name,goal,duration_weeks,status,notes,phase_model) VALUES(?,?,?,?,?,?)',((p['name'] or 'Program')+' copy',p['goal'],p['duration_weeks'],'Draft',p['notes'],p['phase_model'] if 'phase_model' in p.keys() else '')).lastrowid
        for d in conn.execute('SELECT * FROM program_days WHERE program_id=? ORDER BY week_number,id',(pid,)):
            conn.execute('INSERT INTO program_days(program_id,week_number,day_name,routine_id,focus,notes,phase,intensity_target) VALUES(?,?,?,?,?,?,?,?)',(new_id,d['week_number'],d['day_name'],d['routine_id'],d['focus'],d['notes'],d['phase'] if 'phase' in d.keys() else 'Build',d['intensity_target'] if 'intensity_target' in d.keys() else 'RPE 7-8'))
        conn.commit()
    flash('Program duplicated.')
    return redirect(url_for('program_detail', pid=new_id))


@app.route('/recovery')
def recovery_center():
    return render_template('recovery.html', readiness=readiness_v2(), intelligence=athlete_intelligence(), series=recovery_series(45), signal=coach_signal_v2(), wellness=q('SELECT * FROM wellness ORDER BY date DESC LIMIT 12'))

@app.route('/skills', methods=['GET','POST'])
def skills_center():
    if request.method=='POST':
        if request.form.get('mode')=='create':
            insert('INSERT INTO athlete_skills(name,category,current_level,target_level,progress,notes) VALUES(?,?,?,?,?,?)',(request.form['name'],request.form.get('category','Strength Skill'),request.form.get('current_level') or 1,request.form.get('target_level') or 5,request.form.get('progress') or 0,request.form.get('notes','')))
            flash('Skill added to ATHENA Skill System.'); return redirect(url_for('skills_center'))
        sid=request.form.get('skill_id')
        q('UPDATE athlete_skills SET current_level=?, target_level=?, progress=?, notes=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',(request.form.get('current_level') or 1,request.form.get('target_level') or 5,request.form.get('progress') or 0,request.form.get('notes',''),sid),commit=True)
        flash('Skill updated.'); return redirect(url_for('skills_center'))
    skills=[dict(r) for r in q('SELECT * FROM athlete_skills ORDER BY category,name')]
    steps={r['id']:q('SELECT * FROM skill_steps WHERE skill_id=? ORDER BY step_order',(r['id'],)) for r in skills}
    return render_template('skills.html', skills=skills, steps=steps, attributes=rpg_attributes())

@app.route('/skills/<int:sid>/steps/<int:step_id>/toggle', methods=['POST'])
def skill_step_toggle(sid, step_id):
    row=q('SELECT completed FROM skill_steps WHERE id=? AND skill_id=?',(step_id,sid),one=True)
    if row:
        q('UPDATE skill_steps SET completed=? WHERE id=?',(0 if row['completed'] else 1, step_id),commit=True)
        recalc_skill_progress(sid)
    return redirect(url_for('skills_center'))


@app.route('/skills/<int:sid>/steps/<int:step_id>/evidence', methods=['POST'])
def skill_step_evidence_upload(sid, step_id):
    row=q('SELECT id FROM skill_steps WHERE id=? AND skill_id=?',(step_id,sid),one=True)
    if not row:
        flash('Skill step not found.')
        return redirect(url_for('skills_center'))
    image_path = save_image(request.files.get('evidence'))
    note = request.form.get('evidence_note','')
    if image_path or note:
        q('UPDATE skill_steps SET evidence_image_path=COALESCE(NULLIF(?,\'\'), evidence_image_path), evidence_note=?, evidence_at=CURRENT_TIMESTAMP, completed=1 WHERE id=?', (image_path, note, step_id), commit=True)
        recalc_skill_progress(sid)
        flash('Evidence saved and skill step marked complete.')
    else:
        flash('Add an image or a short evidence note first.')
    return redirect(url_for('skills_center'))


@app.route('/skills/<int:sid>/steps/add', methods=['POST'])
def skill_step_add(sid):
    title=(request.form.get('title') or '').strip()
    if title:
        order=request.form.get('step_order') or (q('SELECT COALESCE(MAX(step_order),0)+1 n FROM skill_steps WHERE skill_id=?',(sid,),one=True)['n'] or 1)
        q('INSERT INTO skill_steps(skill_id,step_order,title,description,completed) VALUES(?,?,?,?,?)',(sid,order,title,request.form.get('description',''),1 if request.form.get('completed') else 0),commit=True)
        recalc_skill_progress(sid)
        flash('Skill progression step added.')
    return redirect(url_for('skills_center'))

@app.route('/skills/<int:sid>/steps/<int:step_id>/edit', methods=['POST'])
def skill_step_edit(sid, step_id):
    q('UPDATE skill_steps SET step_order=?, title=?, description=?, completed=? WHERE id=? AND skill_id=?',(request.form.get('step_order') or 1,request.form.get('title','Step'),request.form.get('description',''),1 if request.form.get('completed') else 0,step_id,sid),commit=True)
    recalc_skill_progress(sid)
    flash('Skill progression step updated.')
    return redirect(url_for('skills_center'))

@app.route('/skills/<int:sid>/steps/<int:step_id>/delete', methods=['POST'])
def skill_step_delete(sid, step_id):
    q('DELETE FROM skill_steps WHERE id=? AND skill_id=?',(step_id,sid),commit=True)
    recalc_skill_progress(sid)
    flash('Skill progression step deleted.')
    return redirect(url_for('skills_center'))

@app.route('/skill-evidence')
def skill_evidence_gallery():
    rows=q('''SELECT ss.*, ask.name skill_name, ask.category FROM skill_steps ss JOIN athlete_skills ask ON ask.id=ss.skill_id
              WHERE COALESCE(ss.evidence_image_path,'')<>'' OR COALESCE(ss.evidence_note,'')<>''
              ORDER BY ss.evidence_at DESC, ask.name, ss.step_order''')
    return render_template('skill_evidence.html', rows=rows)

@app.route('/quests', methods=['GET','POST'])
def quests_center():
    if request.method=='POST':
        insert('INSERT INTO quests(title,description,quest_type,target,current,xp_reward,status,auto_rule,auto_complete) VALUES(?,?,?,?,?,?,?,?,?)',(request.form['title'],request.form.get('description',''),request.form.get('quest_type','Weekly'),request.form.get('target') or 1,0,request.form.get('xp_reward') or 50,'Active','',0))
        flash('Quest created.'); return redirect(url_for('quests_center'))
    return render_template('quests.html', quests=quest_state(), gamification=gamification_state(), mission=mission_state())

@app.route('/quests/<int:qid>/complete', methods=['POST'])
def quest_complete(qid):
    row=q('SELECT * FROM quests WHERE id=?',(qid,),one=True)
    if row and row['status']!='Completed':
        q('UPDATE quests SET status="Completed", current=target, completed_at=? WHERE id=?',(datetime.date.today().isoformat(),qid),commit=True)
        insert('INSERT INTO xp_events(source,points,note) VALUES(?,?,?)',('Quest', row['xp_reward'] or 50, row['title']))
        flash('Quest completed. XP awarded.')
    return redirect(url_for('quests_center'))

@app.route('/exercise-progressions')
def exercise_progressions_center():
    rows=q('''SELECT e.id,e.name,e.muscle_group,e.exercise_type,p.step_order,p.title,p.description FROM exercises e LEFT JOIN exercise_progressions p ON p.exercise_id=e.id ORDER BY e.name,p.step_order''')
    grouped={}
    for r in rows:
        grouped.setdefault(r['id'], {'exercise':r, 'steps':[]})
        if r['title']:
            grouped[r['id']]['steps'].append(r)
    return render_template('exercise_progressions.html', groups=grouped.values())

@app.route('/architecture')
def architecture_info():
    return render_template('architecture_info.html')


# ---------------- ATHENA 11.6 Profile, Skill Tree and Dashboard Intelligence ----------------
def athlete_rank_from_xp(xp):
    xp=int(xp or 0)
    ranks=[
        (0,'Novice','Build the base'),
        (750,'Apprentice','Consistent learner'),
        (1750,'Athlete','Training identity established'),
        (3500,'Competitor','Performance focused'),
        (6000,'Elite','High consistency and output'),
        (9500,'Master','Advanced performance system'),
        (14000,'Legend','Long-term ATHENA athlete'),
    ]
    current=ranks[0]
    nxt=None
    for i,r in enumerate(ranks):
        if xp>=r[0]:
            current=r
            nxt=ranks[i+1] if i+1 < len(ranks) else None
    if nxt:
        span=max(1,nxt[0]-current[0]); progress=round((xp-current[0])/span*100)
        to_next=max(0,nxt[0]-xp)
    else:
        progress=100; to_next=0
    return {'name':current[1], 'description':current[2], 'progress':progress, 'next':nxt[1] if nxt else 'Max Rank', 'to_next':to_next}

def streak_system_v2():
    c=consistency_engine(90)
    cur=int(c.get('current',0) or 0); best=int(c.get('best',0) or 0)
    milestones=[3,7,14,30,60,90,180,365]
    next_m=next((m for m in milestones if cur < m), milestones[-1])
    return {'current':cur, 'best':max(best,cur), 'next_milestone':next_m, 'remaining':max(0,next_m-cur), 'last_90':c.get('last_30',0)}

def profile_completion_score(profile=None):
    if profile is None:
        profile=q('SELECT * FROM athlete_profile WHERE id=1', one=True)
    fields=['name','experience','primary_goal','height_cm','weight_kg','weekly_target','equipment','training_focus','skill_focus','recovery_priority','notes']
    done=0
    for f in fields:
        try:
            if profile and profile[f] not in (None,'',0,'0'):
                done+=1
        except Exception:
            pass
    return round(done/max(1,len(fields))*100)

def skill_tree_view_data():
    skills=[dict(r) for r in q('SELECT * FROM athlete_skills ORDER BY category,name')]
    out=[]
    for s in skills:
        steps=[dict(x) for x in q('SELECT * FROM skill_steps WHERE skill_id=? ORDER BY step_order',(s['id'],))]
        completed=sum(1 for x in steps if x.get('completed'))
        total=max(1,len(steps))
        skill_xp=completed*75 + int(s.get('progress') or 0)*2
        for idx,st in enumerate(steps):
            previous_done = idx==0 or bool(steps[idx-1].get('completed'))
            st['locked'] = (not previous_done) and not st.get('completed')
            st['requirement'] = 'Complete previous node' if st['locked'] else ('Evidence recommended' if not st.get('completed') else 'Unlocked')
        s['steps']=steps
        s['completed_steps']=completed
        s['total_steps']=len(steps)
        s['skill_xp']=skill_xp
        s['skill_level']=max(1, skill_xp//250 + 1)
        s['next_skill_xp']=250-(skill_xp%250)
        out.append(s)
    return out

def featured_achievements(limit=3):
    unlocked=[a for a in achievement_catalog() if a.get('unlocked')]
    rarity_order={'Legendary':5,'Epic':4,'Rare':3,'Common':2}
    unlocked.sort(key=lambda a:(rarity_order.get(a.get('rarity'),1), a.get('progress',0)), reverse=True)
    return unlocked[:limit]

def upcoming_goals_data(limit=4):
    try:
        rows=q('SELECT * FROM goals ORDER BY id DESC LIMIT ?', (limit,))
        out=[]
        for g in rows:
            target=float(g['target'] or 1); cur=float(g['current'] or 0)
            out.append(dict(g, progress=round(min(100,cur/max(1,target)*100))))
        return out
    except Exception:
        return []

def smart_training_suggestion_v2():
    plan=smart_today_plan(); daily=athena_daily_score(); deload=deload_detection(); intel=athlete_intelligence(); streak=streak_system_v2()
    if deload.get('needed'):
        title='Deload / Recovery Day'; tone='danger'; action='Cut volume 30–50%, stay around RPE 6–7, and prioritize sleep.'
    elif daily['score']>=82 and intel['fatigue']<=5:
        title='Train Hard'; tone='good'; action='Good day for main lifts, quality volume, or a planned progression attempt.'
    elif daily['score']>=65:
        title='Build Session'; tone='neutral'; action='Keep the plan, but cap most sets around RPE 7–8 and avoid forced PRs.'
    else:
        title='Recovery Priority'; tone='warning'; action='Use an easier variation, mobility, or a short technique session.'
    reasons=[f"ATHENA Score {daily['score']}/100", f"Fatigue {intel['fatigue_label']}", f"Streak {streak['current']} days"]
    return {'title':title,'tone':tone,'action':action,'reasons':reasons,'base_plan':plan}

def dashboard_mission_v2():
    mission=mission_state(); goals=upcoming_goals_data(3); smart=smart_training_suggestion_v2()
    quick=[
        {'label':'Start Workout','href':'/execute','primary':True},
        {'label':'Log Weight','href':'/wellness'},
        {'label':'Recovery Check-In','href':'/wellness'},
        {'label':'Open Weekly Review','href':'/weekly-review'},
    ]
    return {'mission':mission, 'goals':goals, 'smart':smart, 'quick':quick}

@app.context_processor
def athena_v116_context():
    return dict(
        athlete_rank_from_xp=athlete_rank_from_xp,
        streak_system_v2=streak_system_v2,
        profile_completion_score=profile_completion_score,
        skill_tree_view_data=skill_tree_view_data,
        featured_achievements=featured_achievements,
        upcoming_goals_data=upcoming_goals_data,
        smart_training_suggestion_v2=smart_training_suggestion_v2,
        dashboard_mission_v2=dashboard_mission_v2,
    )


if __name__ == '__main__':
    init_db()
    app.run(debug=True)

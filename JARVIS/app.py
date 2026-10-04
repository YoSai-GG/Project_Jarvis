import ast
import json
import os
import array
import difflib
import queue
import random
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import END, Canvas, StringVar, Text, Tk, Toplevel, ttk

APP_NAME = "Jarvis Student Assistant"
APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "JarvisAssistant"
DATA_FILE = APP_DIR / "assignments.json"
REMINDERS_FILE = APP_DIR / "reminders.json"
SETTINGS_FILE = APP_DIR / "settings.json"
MODEL_DIR = Path(__file__).parent / "vosk-model-small-en-us-0.15"
SCHOOLOGY_DEFAULT = "https://api.schoology.com/v1"
CHAT_MODEL = "gpt-6-luna"


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path, data):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def calculate_math_request(text):
    expression = text.lower().strip()
    math_prefix = re.match(
        r"^(?:please\s+)?(?:what is the answer to|how much is|what is|what's|whats|calculate|compute|solve|work out)\s+",
        expression,
    )
    if math_prefix:
        expression = expression[math_prefix.end():]
        is_math = True
    else:
        is_math = bool(re.search(
            r"\b(plus|minus|times|multiplied by|divided by|over|modulo|mod|power of|square root|sqrt|squared|cubed|percent)\b|[+*/%^]",
            expression,
        ))
    if not is_math:
        return None

    expression = re.sub(r"\b(?:to the power of|raised to the power of|power of)\b", " ** ", expression)
    expression = re.sub(r"\b(?:multiplied by|times)\b|\bx\b", " * ", expression)
    expression = re.sub(r"\b(?:divided by|over)\b", " / ", expression)
    expression = re.sub(r"\bplus\b", " + ", expression)
    expression = re.sub(r"\bminus\b", " - ", expression)
    expression = re.sub(r"\b(?:modulo|mod)\b", " % ", expression)
    expression = re.sub(r"\bsquare root of\s*", "sqrt ", expression)
    expression = re.sub(r"\b(\d+(?:\.\d+)?)\s+percent(?:age)?\s+of\s+", r"(\1 / 100) * ", expression)
    expression = re.sub(r"\b(\d+(?:\.\d+)?)\s+squared\b", r"(\1 ** 2)", expression)
    expression = re.sub(r"\b(\d+(?:\.\d+)?)\s+cubed\b", r"(\1 ** 3)", expression)
    expression = re.sub(r"\b(?:equals?|what)\s*$", "", expression).strip()

    small_numbers = {
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
        "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
        "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
        "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    }
    number_words = set(small_numbers) | {"hundred", "thousand", "million"}
    tokens = re.findall(r"\d+(?:\.\d+)?|[a-z]+|[()+*/%.,^-]", expression)
    converted = []
    index = 0
    while index < len(tokens):
        if tokens[index] not in number_words:
            token = tokens[index]
            converted.append("**" if token == "^" else token)
            index += 1
            continue
        total = current = 0
        while index < len(tokens) and tokens[index] in number_words:
            word = tokens[index]
            if word == "hundred":
                current = max(1, current) * 100
            elif word in ("thousand", "million"):
                scale = 1000 if word == "thousand" else 1000000
                total += max(1, current) * scale
                current = 0
            else:
                current += small_numbers[word]
            index += 1
        converted.append(str(total + current))

    expression = " ".join(converted)
    expression = re.sub(r"(\d+(?:\.\d+)?)\s*%\s*of\s*", r"(\1 / 100) * ", expression)
    expression = re.sub(r"(\d+(?:\.\d+)?)\s+percent(?:age)?\s+of\s*", r"(\1 / 100) * ", expression)
    expression = re.sub(r"\b(\d+(?:\.\d+)?)\s+squared\b", r"(\1 ** 2)", expression)
    expression = re.sub(r"\b(\d+(?:\.\d+)?)\s+cubed\b", r"(\1 ** 3)", expression)
    if re.search(r"\bsqrt\b", expression):
        expression = re.sub(r"\bsqrt\s+(\d+(?:\.\d+)?)", r"sqrt(\1)", expression)
    try:
        tree = ast.parse(expression, mode="eval")

        def evaluate(node):
            if isinstance(node, ast.Expression):
                return evaluate(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                value = node.value
            elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                value = evaluate(node.operand)
                value = value if isinstance(node.op, ast.UAdd) else -value
            elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)):
                left, right = evaluate(node.left), evaluate(node.right)
                if isinstance(node.op, ast.Add): value = left + right
                elif isinstance(node.op, ast.Sub): value = left - right
                elif isinstance(node.op, ast.Mult): value = left * right
                elif isinstance(node.op, ast.Div): value = left / right
                elif isinstance(node.op, ast.FloorDiv): value = left // right
                elif isinstance(node.op, ast.Mod): value = left % right
                else:
                    if abs(right) > 12 or abs(left) > 1_000_000:
                        raise ValueError("Power is too large")
                    value = left ** right
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                  and node.func.id == "sqrt" and len(node.args) == 1):
                value = evaluate(node.args[0]) ** 0.5
            else:
                raise ValueError("Unsupported math expression")
            if not isinstance(value, (int, float)) or abs(value) > 1_000_000_000_000:
                raise ValueError("Math result is out of range")
            return value

        result = evaluate(tree)
    except ZeroDivisionError:
        return "Division by zero is undefined."
    except (SyntaxError, ValueError, TypeError, OverflowError):
        return None
    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return f"The answer is {result:.10g}." if isinstance(result, float) else f"The answer is {result}."


def answer_local_question(text):
    question = re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()
    question = re.sub(r"\s+", " ", question)
    if re.search(r"\b(?:is|why is) (?:the )?sky blue\b", question):
        return ("Yes, the sky usually looks blue. Air molecules scatter the shorter blue wavelengths of sunlight "
                "more than the longer red wavelengths. Near sunrise or sunset, sunlight travels through more air, "
                "so the sky can look orange or red.")
    if re.search(r"\b(?:is|why is) (?:the )?grass green\b", question):
        return ("Usually, yes. Chlorophyll in grass absorbs much of the red and blue light for photosynthesis "
                "and reflects more green light, which is why it looks green.")
    if question in {"what time is it", "tell me the time", "what is the time"}:
        return f"It's {datetime.now().strftime('%I:%M %p').lstrip('0')}."
    if question in {"what day is it", "what is today's date", "what is the date today"}:
        return f"Today is {datetime.now().strftime('%A, %B %d, %Y')}."
    return None


class Schoology:
    def __init__(self, key, secret, base_url):
        self.key = key.strip()
        self.secret = secret.strip()
        self.base_url = base_url.rstrip("/")

    def get(self, path):
        url = self.base_url + path
        nonce = os.urandom(12).hex()
        timestamp = str(int(time.time()))
        signature = self.secret + "&"
        fields = {
            "realm": "Schoology API",
            "oauth_consumer_key": self.key,
            "oauth_nonce": nonce,
            "oauth_signature": signature,
            "oauth_signature_method": "PLAINTEXT",
            "oauth_timestamp": timestamp,
            "oauth_token": "",
            "oauth_version": "1.0",
        }
        header = "OAuth " + ", ".join(
            f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="~")}"'
            for k, v in fields.items()
        )
        request = urllib.request.Request(
            url, headers={"Authorization": header, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:300]
            if exc.code in (401, 403):
                raise RuntimeError("Schoology denied API access. Check your credentials and ask your school whether API access is enabled.") from exc
            raise RuntimeError(f"Schoology API returned {exc.code}: {body}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Could not reach Schoology: {exc}") from exc

    def assignments(self, user_id="me"):
        sections_data = self.get(f"/users/{urllib.parse.quote(user_id)}/sections")
        sections = sections_data.get("section", [])
        if isinstance(sections, dict):
            sections = [sections]
        found = []
        for section in sections:
            section_id = section.get("id")
            if not section_id:
                continue
            data = self.get(f"/sections/{section_id}/assignments?limit=100")
            items = data.get("assignment", [])
            if isinstance(items, dict):
                items = [items]
            for item in items:
                due = item.get("due")
                if not due or str(item.get("published", "1")) == "0":
                    continue
                found.append({
                    "id": f"schoology:{section_id}:{item.get('id', item.get('title', ''))}",
                    "title": str(item.get("title") or "Untitled assignment"),
                    "course": str(section.get("course_title") or section.get("section_title") or "Schoology"),
                    "due": str(due),
                    "source": "Schoology",
                })
        return found


class JarvisApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1160x800")
        self.root.minsize(1020, 700)
        self.root.configure(bg="#050b13")
        self.assignments = read_json(DATA_FILE, [])
        saved_reminders = read_json(REMINDERS_FILE, [])
        self.reminders = saved_reminders if isinstance(saved_reminders, list) else []
        self.settings = read_json(SETTINGS_FILE, {})
        self.events = queue.Queue()
        self.listening = False
        self.audio_level = 0.0
        self.voice_thread = None
        self.voice_model = None
        self.mic_device_index = None
        self.audio_input_error = None
        self.mic_device_candidates = self.available_microphones()
        if self.mic_device_candidates:
            self.mic_device_index = self.mic_device_candidates[0]
        self.speech_queue = queue.Queue()
        threading.Thread(target=self._speech_worker, daemon=True, name="jarvis-speech").start()
        self.reminded = set()
        self.chat_window = None
        self.chat_history = []
        self.main_conversation_history = []
        self.main_reply_busy = False
        self.chat_busy = False
        self.chat_transcript = None
        self.chat_entry = None
        self.chat_send_button = None
        self.chat_pending_prompt = None
        self.chat_pending_speech = False
        self.chat_settings_dialog = None
        self._build()
        self.root.after(150, self.process_events)
        self.root.after(1000, self.reminder_tick)
        hour = datetime.now().hour
        greeting = "Morning" if hour < 12 else "Afternoon" if hour < 18 else "Evening"
        self.say(f"Hey, good {greeting.lower()}! I am here. What are we working on?")

    def available_microphones(self):
        self.audio_input_error = None
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            default_input = sd.default.device[0]
            supported = []
            for index, device in enumerate(devices):
                if not device["max_input_channels"]:
                    continue
                name = str(device["name"]).lower()
                if any(alias in name for alias in ("sound mapper", "primary sound capture", "stereo mix", "pc speaker")):
                    continue
                supported.append(index)
            if default_input in supported:
                supported.remove(default_input)
                supported.insert(0, default_input)
            return supported
        except Exception as exc:
            self.audio_input_error = str(exc)
            return []

    def _build(self):
        self.colors = {
            "bg": "#03080f", "panel": "#071521", "panel_edge": "#146076",
            "panel_inner": "#0a1c29", "cyan": "#54efff", "cyan_dim": "#168ba4",
            "text": "#e3f6fb", "muted": "#7897a8", "gold": "#ffc86b",
        }
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background=self.colors["bg"], foreground=self.colors["text"],
                        font=("Segoe UI", 10))
        style.configure("TFrame", background=self.colors["bg"])
        style.configure("Panel.TFrame", background=self.colors["panel"])
        style.configure("PanelInner.TFrame", background=self.colors["panel_inner"])
        style.configure("TLabel", background=self.colors["bg"], foreground=self.colors["text"])
        style.configure("Title.TLabel", background=self.colors["bg"], foreground=self.colors["cyan"],
                        font=("Segoe UI", 25, "bold"))
        style.configure("Eyebrow.TLabel", background=self.colors["bg"], foreground=self.colors["muted"],
                        font=("Consolas", 9, "bold"))
        style.configure("PanelTitle.TLabel", background=self.colors["panel"], foreground=self.colors["cyan"],
                        font=("Segoe UI", 11, "bold"))
        style.configure("PanelHint.TLabel", background=self.colors["panel"], foreground=self.colors["muted"],
                        font=("Segoe UI", 9))
        style.configure("Log.TLabel", background=self.colors["bg"], foreground=self.colors["cyan"],
                        font=("Segoe UI", 10))
        style.configure("Clock.TLabel", background=self.colors["bg"], foreground=self.colors["cyan"],
                        font=("Consolas", 11, "bold"))
        style.configure("Treeview", background=self.colors["panel_inner"], foreground=self.colors["text"],
                        fieldbackground=self.colors["panel_inner"], rowheight=34, borderwidth=0,
                        font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background="#153044", foreground=self.colors["cyan"],
                        font=("Consolas", 9, "bold"), padding=(8, 10), borderwidth=0)
        style.map("Treeview", background=[("selected", "#17465b")],
                  foreground=[("selected", "#ffffff")])
        style.configure("TButton", padding=(12, 9), background="#122b3d",
                        foreground=self.colors["text"], borderwidth=1, bordercolor=self.colors["panel_edge"],
                        font=("Segoe UI", 9, "bold"))
        style.map("TButton", background=[("active", "#1b4055"), ("pressed", "#16445a")])
        style.configure("Accent.TButton", background="#0d7892", foreground="#ffffff",
                        bordercolor=self.colors["cyan"])
        style.map("Accent.TButton", background=[("active", "#1299b4"), ("pressed", "#09677d")])
        style.configure("TEntry", fieldbackground="#08131d", foreground=self.colors["text"],
                        insertcolor=self.colors["cyan"], bordercolor=self.colors["panel_edge"],
                        padding=12)

        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=28, pady=(22, 18))
        mark = Canvas(header, width=42, height=42, bg=self.colors["bg"], highlightthickness=0)
        mark.pack(side="left", padx=(0, 12))
        mark.create_oval(4, 4, 38, 38, outline=self.colors["cyan_dim"], width=2)
        mark.create_oval(11, 11, 31, 31, outline=self.colors["cyan"], width=1)
        mark.create_text(21, 21, text="J", fill=self.colors["text"], font=("Segoe UI", 15, "bold"))
        title_stack = ttk.Frame(header)
        title_stack.pack(side="left")
        ttk.Label(title_stack, text="J.A.R.V.I.S.", style="Title.TLabel").pack(anchor="w")
        ttk.Label(title_stack, text="PERSONAL INTELLIGENCE  /  ONLINE",
                  style="Eyebrow.TLabel").pack(anchor="w", pady=(1, 0))
        ttk.Button(header, text="OPEN SCHOOLOGY", command=lambda: self.open_target("schoology")).pack(side="right", padx=(8, 0))
        self.clock_label = ttk.Label(header, style="Clock.TLabel")
        self.clock_label.pack(side="right", padx=(8, 18))
        self.update_clock()

        body = ttk.Frame(self.root)
        body.pack(fill="both", expand=True, padx=28)
        body.columnconfigure(0, weight=0, minsize=340)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        control_panel = ttk.Frame(body, style="Panel.TFrame", padding=18)
        control_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        ttk.Label(control_panel, text="TALK TO JARVIS", style="PanelTitle.TLabel").pack(anchor="w")
        ttk.Label(control_panel, text="VOICE INTERFACE  /  SPEECH RUNS LOCALLY",
                  style="PanelHint.TLabel").pack(anchor="w", pady=(4, 7))
        self.hud_canvas = Canvas(control_panel, width=296, height=318, bg=self.colors["panel"],
                                 highlightthickness=0)
        self.hud_canvas.pack(fill="x", pady=(2, 0))
        cx, cy = 148, 145
        self.hud_canvas.create_oval(cx-126, cy-126, cx+126, cy+126, outline="#123849", width=1)
        self.hud_canvas.create_oval(cx-115, cy-115, cx+115, cy+115, outline="#17516a", width=1)
        self.hud_canvas.create_oval(cx-93, cy-93, cx+93, cy+93, outline="#10374a", width=1)
        self.hud_canvas.create_oval(cx-82, cy-82, cx+82, cy+82, outline="#1a5467", width=1)
        self.hud_canvas.create_arc(cx-116, cy-116, cx+116, cy+116, start=15, extent=34,
                                   style="pieslice", fill="#0d3544", stipple="gray50",
                                   outline="", tags="radar_beam")
        self.hud_canvas.create_oval(cx-58, cy-58, cx+58, cy+58, outline="#286e80", width=2)
        for angle in range(0, 360, 15):
            import math
            rad = math.radians(angle)
            inner = 111 if angle % 30 == 0 else 119
            x1, y1 = cx + inner * math.cos(rad), cy + inner * math.sin(rad)
            x2, y2 = cx + 125 * math.cos(rad), cy + 125 * math.sin(rad)
            self.hud_canvas.create_line(x1, y1, x2, y2,
                                       fill="#54efff" if angle % 30 == 0 else "#245266",
                                       width=2 if angle % 30 == 0 else 1)
        self.hud_ticks = []
        for angle in range(0, 360, 6):
            rad = math.radians(angle)
            major = angle % 30 == 0
            inner = 130 if major else 135
            x1, y1 = cx + inner * math.cos(rad), cy + inner * math.sin(rad)
            x2, y2 = cx + 139 * math.cos(rad), cy + 139 * math.sin(rad)
            tick = self.hud_canvas.create_line(
                x1, y1, x2, y2,
                fill="#267d91" if major else "#164052",
                width=2 if major else 1,
            )
            self.hud_ticks.append((tick, angle))
        self.hud_canvas.create_arc(cx-103, cy-103, cx+103, cy+103, start=20, extent=68,
                                   style="arc", outline=self.colors["cyan"], width=3, tags="sweep")
        self.hud_canvas.create_arc(cx-88, cy-88, cx+88, cy+88, start=200, extent=36,
                                   style="arc", outline="#236b82", width=2, tags="counter_sweep")
        self.hud_canvas.create_arc(cx-116, cy-116, cx+116, cy+116, start=205, extent=28,
                                   style="arc", outline="#16485b", width=2, tags="scan_arc_a")
        self.hud_canvas.create_arc(cx-96, cy-96, cx+96, cy+96, start=18, extent=22,
                                   style="arc", outline="#28697d", width=2, tags="scan_arc_b")
        self.hud_canvas.create_oval(cx-69, cy-69, cx+69, cy+69, outline="#17475a",
                                    width=1, tags="pulse_ring")
        self.hud_hexagons = []
        for radius, phase in ((62, 0), (77, 30)):
            points = []
            for side in range(6):
                radians = math.radians(phase + side * 60)
                points.extend((cx + radius * math.cos(radians), cy + radius * math.sin(radians)))
            shape = self.hud_canvas.create_polygon(*points, fill="", outline="#1b7187", width=1)
            self.hud_hexagons.append((shape, radius, phase))
        self.hud_canvas.create_oval(cx-53, cy-53, cx+53, cy+53, fill="#082333",
                                    outline="#36c4d7", width=2)
        self.hud_canvas.create_oval(cx-42, cy-42, cx+42, cy+42, outline="#145f75", width=1)
        self.hud_canvas.create_text(cx, cy-9, text="J", fill=self.colors["text"],
                                    font=("Segoe UI", 30, "bold"))
        self.hud_canvas.create_text(cx, cy+27, text="JARVIS CORE", fill=self.colors["cyan"],
                                    font=("Consolas", 7, "bold"))
        self.hud_orbits = []
        for radius, angle, size, color in ((76, 30, 3, "#54efff"), (94, 155, 2, "#36c4d7"),
                                           (109, 245, 3, "#54efff"), (83, 305, 2, "#2788a1")):
            radians = math.radians(angle)
            x, y = cx + radius * math.cos(radians), cy + radius * math.sin(radians)
            marker = self.hud_canvas.create_oval(x-size, y-size, x+size, y+size,
                                                  fill=color, outline="")
            self.hud_orbits.append((marker, radius, angle, size))
        self.hud_canvas.create_text(24, 38, text="VOICE", anchor="w", fill=self.colors["muted"],
                                    font=("Consolas", 7, "bold"))
        self.hud_canvas.create_text(272, 38, text="LOCAL", anchor="e", fill=self.colors["cyan"],
                                    font=("Consolas", 7, "bold"))
        self.hud_canvas.create_line(24, 48, 272, 48, fill="#15394a")
        self.hud_canvas.create_line(24, 242, 272, 242, fill="#15394a")
        self.hud_canvas.create_text(24, 255, text="AUDIO STREAM", anchor="w", fill=self.colors["muted"],
                                    font=("Consolas", 7))
        self.wave_bars = []
        for bar in range(25):
            x = 34 + bar * 9
            item = self.hud_canvas.create_line(x, 289, x, 289, fill="#16758a", width=2)
            self.wave_bars.append(item)
        self.hud_canvas.create_text(272, 255, text="16 KHZ", anchor="e", fill=self.colors["cyan"],
                                    font=("Consolas", 7))
        self.hud_canvas.create_text(cx, 310, text="VOICE INPUT AUTO-SELECTED",
                                    fill=self.colors["muted"], font=("Consolas", 7))
        self.hud_canvas.create_text(cx, 204, text="MIC SIGNAL 00%", fill=self.colors["muted"],
                                    font=("Consolas", 7, "bold"), tags=("audio_meter",))
        self.hud_canvas.create_text(cx, 224, text="SYSTEM READY", fill=self.colors["cyan"],
                                    font=("Consolas", 8, "bold"), tags=("core_state",))
        self.animation_step = 20
        self.root.after(75, self.animate_hud)

        self.status = StringVar(value="SYSTEM READY")
        status_row = ttk.Frame(control_panel, style="PanelInner.TFrame", padding=(12, 10))
        status_row.pack(fill="x", pady=(4, 14))
        self.status_dot = Canvas(status_row, width=14, height=14, bg=self.colors["panel_inner"],
                                 highlightthickness=0)
        self.status_dot.pack(side="left", padx=(0, 8))
        self.status_dot.create_oval(3, 3, 11, 11, fill=self.colors["cyan"], outline="")
        ttk.Label(status_row, textvariable=self.status, style="PanelHint.TLabel",
                  wraplength=265).pack(side="left", fill="x", expand=True)

        self.listen_button = ttk.Button(control_panel, text="?   START VOICE LISTENING",
                                        style="Accent.TButton", command=self.toggle_voice)
        self.listen_button.pack(fill="x", pady=(0, 9))
        ttk.Button(control_panel, text="CHAT WITH JARVIS", command=self.open_chat).pack(fill="x")
        ttk.Label(control_panel, text="Try: â€œHey Jarvis, what is up?â€",
                  style="PanelHint.TLabel").pack(anchor="w", pady=(16, 0))

        feed_panel = ttk.Frame(body, style="Panel.TFrame", padding=18)
        feed_panel.grid(row=0, column=1, sticky="nsew")
        feed_panel.rowconfigure(1, weight=1)
        feed_panel.columnconfigure(0, weight=1)
        feed_header = ttk.Frame(feed_panel, style="Panel.TFrame")
        feed_header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(feed_header, text="JARVIS ACTIVITY", style="PanelTitle.TLabel").pack(side="left")
        ttk.Label(feed_header, text="VOICE  /  COMMANDS  /  RESPONSES",
                  style="PanelHint.TLabel").pack(side="right")
        self.feed = Text(feed_panel, wrap="word", state="disabled", bg="#06111a",
                         fg=self.colors["text"], insertbackground=self.colors["cyan"],
                         selectbackground="#17465b", relief="flat", padx=18, pady=16,
                         font=("Consolas", 10), spacing1=3, spacing3=10)
        self.feed.grid(row=1, column=0, sticky="nsew")
        feed_scroll = ttk.Scrollbar(feed_panel, orient="vertical", command=self.feed.yview)
        feed_scroll.grid(row=1, column=1, sticky="ns")
        self.feed.configure(yscrollcommand=feed_scroll.set)
        self.feed.tag_configure("user", foreground="#54efff", font=("Consolas", 10, "bold"))
        self.feed.tag_configure("jarvis", foreground=self.colors["text"])
        self.feed.tag_configure("time", foreground=self.colors["muted"], font=("Consolas", 8))

        command_panel = ttk.Frame(self.root, style="Panel.TFrame", padding=(18, 14))
        command_panel.pack(fill="x", padx=28, pady=(14, 0))
        ttk.Label(command_panel, text="SAY IT OR TYPE IT", style="PanelTitle.TLabel").pack(anchor="w")
        command_row = ttk.Frame(command_panel, style="Panel.TFrame")
        command_row.pack(fill="x", pady=(9, 0))
        self.command = ttk.Entry(command_row, font=("Segoe UI", 11))
        self.command.pack(side="left", fill="x", expand=True, padx=(0, 9))
        self.command.bind("<Return>", lambda _event: self.submit_command())
        ttk.Button(command_row, text="SEND COMMAND  ?", style="Accent.TButton",
                   command=self.submit_command).pack(side="right")

        self.log = ttk.Label(self.root, text="Jarvis is ready. Type a command below or start voice listening.",
                             style="Log.TLabel")
        self.log.pack(fill="x", padx=30, pady=(10, 16), anchor="w")

    def update_clock(self):
        self.clock_label.configure(text=datetime.now().strftime("%a, %b %d  %I:%M:%S %p"))
        self.root.after(1000, self.update_clock)

    def animate_hud(self):
        import math
        self.animation_step = (self.animation_step + 5) % 360
        accent = self.colors["cyan"] if self.listening else "#2788a1"
        self.hud_canvas.itemconfigure("sweep", start=self.animation_step, outline=accent)
        self.hud_canvas.itemconfigure("counter_sweep", start=-self.animation_step * 0.7)
        self.hud_canvas.itemconfigure("scan_arc_a", start=-self.animation_step * 1.25,
                                      outline="#38c7dc" if self.listening else "#16485b")
        self.hud_canvas.itemconfigure("scan_arc_b", start=self.animation_step * 0.8,
                                      outline="#1d7086" if self.listening else "#28697d")
        rotation = self.animation_step * (1.35 if self.listening else 0.55)
        self.hud_canvas.itemconfigure("radar_beam", start=rotation,
                                      fill="#12566b" if self.listening else "#0d3544")
        for shape, radius, phase in self.hud_hexagons:
            points = []
            spin = rotation * (0.8 if phase == 0 else -0.62)
            for side in range(6):
                radians = math.radians(phase + spin + side * 60)
                points.extend((148 + radius * math.cos(radians), 145 + radius * math.sin(radians)))
            self.hud_canvas.coords(shape, *points)
            self.hud_canvas.itemconfigure(shape, outline="#54efff" if self.listening else "#1b7187")
        for marker, radius, angle, size in self.hud_orbits:
            radians = math.radians(angle + rotation * (1 if angle % 2 else -0.72))
            x, y = 148 + radius * math.cos(radians), 145 + radius * math.sin(radians)
            self.hud_canvas.coords(marker, x-size, y-size, x+size, y+size)
        state_text = "LISTENING" if self.listening else "SYSTEM READY"
        self.hud_canvas.itemconfigure("core_state", text=state_text, fill=accent)
        pulse = 66 + 4 * math.sin(math.radians(self.animation_step * 2)) + self.audio_level * 10
        self.hud_canvas.itemconfigure("audio_meter", text=f"MIC SIGNAL {round(self.audio_level * 100):02d}%",
                                      fill="#54efff" if self.audio_level > 0.08 else self.colors["muted"])
        self.hud_canvas.coords("pulse_ring", 148 - pulse, 145 - pulse,
                               148 + pulse, 145 + pulse)
        self.hud_canvas.itemconfigure("pulse_ring", outline="#36c4d7" if self.listening else "#17475a")
        sweep_angle = (self.animation_step * 2) % 360
        for tick, angle in self.hud_ticks:
            distance = abs((angle - sweep_angle + 180) % 360 - 180)
            active = self.listening and distance < 19
            self.hud_canvas.itemconfigure(tick, fill="#54efff" if active else "#267d91" if angle % 30 == 0 else "#164052")
        for index, item in enumerate(self.wave_bars):
            phase = math.radians(self.animation_step * 2 + index * 31)
            envelope = 0.4 + 0.6 * abs(math.sin(math.radians(self.animation_step * 0.55 + index * 11)))
            if self.listening:
                level = 2 + abs(math.sin(phase)) * (3 + 22 * self.audio_level) * envelope
            else:
                level = 2 + 2 * abs(math.sin(phase * 0.55))
            x = 34 + index * 9
            self.hud_canvas.coords(item, x, 289 - level, x, 289 + level)
            bar_color = "#54efff" if self.listening and abs(math.sin(phase)) > 0.72 else accent if self.listening else "#1b8aa0"
            self.hud_canvas.itemconfigure(item, fill=bar_color)
        dot_color = self.colors["cyan"] if self.listening else "#7897a8"
        self.status_dot.itemconfigure(1, fill=dot_color)
        self.root.after(75, self.animate_hud)
    def say(self, text):
        self.status.set(text)
        self.log.configure(text=text)
        self.feed_message("JARVIS", text)
        self.speech_queue.put(text)

    def feed_message(self, speaker, text):
        if not hasattr(self, "feed"):
            return
        self.feed.configure(state="normal")
        self.feed.insert(END, f"[{datetime.now().strftime('%H:%M:%S')}]  ", "time")
        self.feed.insert(END, speaker.upper() + "\n", "user" if speaker.upper() == "YOU" else "jarvis")
        self.feed.insert(END, str(text).strip() + "\n\n", "user" if speaker.upper() == "YOU" else "jarvis")
        self.feed.configure(state="disabled")
        self.feed.see(END)

    def _speech_worker(self):
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", 178)
            engine.setProperty("volume", 0.95)
            voices = engine.getProperty("voices")
            preferred = ("david", "mark", "guy")
            chosen = next(
                (voice for name in preferred for voice in voices
                 if name in f"{voice.name} {voice.id}".lower()),
                next((voice for voice in voices if "english" in voice.name.lower()), None)
            )
            if chosen:
                engine.setProperty("voice", chosen.id)
        except Exception:
            return

        while True:
            text = self.speech_queue.get()
            if text is None:
                break
            try:
                engine.say(text)
                engine.runAndWait()
            except Exception:
                continue
    def refresh_assignments(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        self.assignments.sort(key=lambda x: self.parse_due(x.get("due", "")) or datetime.max)
        for item in self.assignments:
            due = item.get("due", "No date")
            self.tree.insert("", END, values=(item.get("course", ""), item.get("title", ""), due, item.get("source", "Manual")))

    @staticmethod
    def parse_due(value):
        if not value:
            return None
        value = str(value)
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(value[:19], fmt)
            except ValueError:
                continue
        return None

    @staticmethod
    def resample_pcm(audio_bytes, source_rate, target_rate=16000):
        import math
        if source_rate == target_rate:
            return audio_bytes
        samples = array.array("h")
        samples.frombytes(audio_bytes)
        if not samples:
            return audio_bytes

        # Low-pass windowed-sinc resampling prevents aliasing when a 44.1/48 kHz
        # microphone stream is converted to the 16 kHz Vosk model input.
        ratio = source_rate / target_rate
        cutoff = target_rate / source_rate
        radius = max(12, math.ceil(12 / cutoff))
        output_count = max(1, round(len(samples) / ratio))
        converted = array.array("h")
        for index in range(output_count):
            center = (index + 0.5) * ratio - 0.5
            first = max(0, math.floor(center - radius + 1))
            last = min(len(samples) - 1, math.ceil(center + radius - 1))
            weighted_sum = 0.0
            weight_total = 0.0
            for source_index in range(first, last + 1):
                distance = center - source_index
                scaled = cutoff * distance
                sinc = 1.0 if abs(scaled) < 1e-12 else math.sin(math.pi * scaled) / (math.pi * scaled)
                window_position = distance / radius
                window = (1.0 if abs(window_position) < 1e-12 else
                          math.sin(math.pi * window_position) / (math.pi * window_position))
                weight = cutoff * sinc * window
                weighted_sum += samples[source_index] * weight
                weight_total += weight
            sample = round(weighted_sum / weight_total) if weight_total else 0
            converted.append(max(-32768, min(32767, sample)))
        return converted.tobytes()

    @staticmethod
    def prepare_voice_audio(audio_bytes, state):
        samples = array.array("h")
        samples.frombytes(audio_bytes)
        if not samples:
            return audio_bytes

        previous_input, previous_output, previous_gain = state
        filtered = array.array("h")
        alpha = 0.976  # Gentle high-pass filter to reduce DC offset and low microphone rumble.
        for sample in samples:
            output = alpha * (previous_output + sample - previous_input)
            previous_input, previous_output = sample, output
            filtered.append(max(-32768, min(32767, round(output))))

        rms = (sum(sample * sample for sample in filtered) / len(filtered)) ** 0.5
        target_gain = min(2.2, 1350 / rms) if 120 < rms < 1100 else 1.0
        gain = previous_gain * 0.82 + target_gain * 0.18
        for index, sample in enumerate(filtered):
            filtered[index] = max(-32768, min(32767, round(sample * gain)))
        state[:] = [previous_input, previous_output, gain]
        return filtered.tobytes()

    def submit_command(self):
        command = self.command.get().strip()
        if not command:
            return
        self.command.delete(0, END)
        self.handle_command(command)

    def handle_command(self, command, from_voice=False):
        self.feed_message("YOU", command)
        text = command.lower().strip().rstrip("?!.,")
        for prefix in ("hey jarvis, ", "hey jarvis ", "jarvis, ", "jarvis ", "hey, ", "hey ",
                       "hi jarvis, ", "hi jarvis ", "hi ", "hello jarvis, ",
                       "hello jarvis ", "hello ", "yo jarvis, ", "yo jarvis ", "yo "):
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
                break

        if from_voice and text in ("open", "please open", "go to", "go on", "launch", "start"):
            self.say("Which site should I open? For example, say open YouTube.")
            return

        math_answer = calculate_math_request(text)
        local_answer = answer_local_question(text)
        if math_answer is not None:
            self.say(math_answer)
        elif local_answer is not None:
            self.say(local_answer)
        elif text.startswith(("remind me to ", "set a reminder to ", "set reminder to ")):
            self.add_reminder_from_text(text)
        elif text in ("list reminders", "show reminders", "what are my reminders", "read my reminders"):
            self.read_reminders()
        elif text in ("", "hi", "hey", "hello", "yo", "sup", "hey jarvis", "hi jarvis", "hello jarvis", "what's up", "what's up jarvis",
                    "whats up", "what is up", "what's going on", "howdy"):
            self.say(random.choice((
                "Hey! Not much, just hanging out in your computer. What's up with you?",
                "Hey, good to hear from you. What can I help with?",
                "I'm doing great, thanks for asking. What are we working on?",
                "Hey! I'm here and ready. Need a hand with anything?",
            )))
        elif text in ("how are you", "how are you doing", "how's it going", "hows it going"):
            self.say(random.choice((
                "Doing well! Ready when you are. What's on your mind?",
                "Pretty good, thanks. How can I help you today?",
            )))
        elif text.startswith(("good morning", "good afternoon", "good evening")):
            self.say("Hey! Hope your day's going well. What can I help you with?")
        elif text in ("thanks", "thank you", "thanks jarvis", "thank you jarvis"):
            self.say(random.choice(("Anytime! I've got you.", "You got it. Anything else?", "No problem, happy to help.")))
        elif text in ("bye", "goodbye", "see you", "good night"):
            self.say("Later! I'll be right here when you need me.")
        elif text in ("help", "what can you do", "commands"):
            self.say("I can open websites, open Spotify, check assignments, and chat about your questions. Just ask me.")
        elif "what" in text and ("due" in text or "assignment" in text):
            self.say("I removed assignment tracking. Open Schoology to check what is due.")
        elif "sync" in text and "schoology" in text:
            self.say("Assignment syncing is turned off. Use OPEN SCHOOLOGY to check your classes.")
        elif re.fullmatch(r"(?:please\s+)?(?:close|quit|exit|stop)\s+(?:the\s+)?spotify(?:\s+(?:app|player))?(?:\s+please)?", text):
            self.close_spotify()
        elif text.startswith(("open ", "go to ", "go on ", "go onto ", "launch ", "start ", "play ",
                              "please open ", "can you open ", "could you open ")):
            target = re.sub(r"^(?:please open|can you open|could you open|go to|go on|go onto|launch|start|play|open)\s+", "", text)
            target = re.sub(r"\b(?:please|for me|now|thanks)\b", " ", target)
            target = re.sub(r"\s+", " ", target).strip()
            in_chrome = target.endswith(" in google chrome") or target.endswith(" in chrome")
            if in_chrome:
                target = target.removesuffix(" in google chrome").removesuffix(" in chrome").strip()
            spotify_names = ["spotify", "spotfy", "spotifai", "spotifiy", "spottyfy", "spotfi", "spot ify", "spotty fi", "music", "music player"]
            if self.best_service_match(target, spotify_names):
                self.open_target("spotify")
            elif in_chrome:
                self.open_website(target)
            else:
                self.open_target(target)
        else:
            self.respond_to_conversation(command, from_voice)
    def find_chrome(self):
        chrome = shutil.which("chrome") or shutil.which("chrome.exe")
        if not chrome:
            candidates = [
                Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe",
                Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
                Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
            ]
            chrome = next((str(path) for path in candidates if path.exists()), None)
        return chrome

    @staticmethod
    def clean_target(target):
        target = target.lower().strip()
        target = re.sub(r"\b(?:please|for me|now|thanks|the app)\b", " ", target)
        return re.sub(r"\s+", " ", target).strip(" .,!?")

    @staticmethod
    def best_service_match(target, choices):
        normalized = re.sub(r"[^a-z0-9]", "", target.lower())
        if not normalized:
            return None
        scored = []
        for choice in choices:
            candidate = re.sub(r"[^a-z0-9]", "", choice.lower())
            scored.append((difflib.SequenceMatcher(None, normalized, candidate).ratio(), choice))
        score, choice = max(scored, default=(0, None))
        return choice if score >= 0.70 else None

    def open_website(self, target):
        aliases = {
            "schoology": "https://newarkcharter.schoology.com/home",
            "school reminders": "https://newarkcharter.schoology.com/calendar/27038429/2026-09",
            "youtube": "https://www.youtube.com/",
            "you tube": "https://www.youtube.com/",
            "you to": "https://www.youtube.com/",
            "you too": "https://www.youtube.com/",
            "u tube": "https://www.youtube.com/",
            "utube": "https://www.youtube.com/",
            "github": "https://github.com/dashboard",
            "github dashboard": "https://github.com/dashboard",
            "discord": "https://discord.com/app",
            "google": "https://www.google.com",
            "gmail": "https://mail.google.com",
            "google classroom": "https://classroom.google.com",
            "classroom": "https://classroom.google.com",
            "google drive": "https://drive.google.com",
            "drive": "https://drive.google.com",
            "google docs": "https://docs.google.com",
            "docs": "https://docs.google.com",
            "chatgpt": "https://chatgpt.com/",
            "tiktok": "https://www.tiktok.com",
            "twitch": "https://www.twitch.tv",
            "netflix": "https://www.netflix.com",
            "reddit": "https://www.reddit.com",
            "wikipedia": "https://www.wikipedia.org",
        }
        name = self.clean_target(target)
        url = aliases.get(name)
        if not url:
            match = self.best_service_match(name, list(aliases))
            if match:
                name = match
                url = aliases[match]
        if not url:
            if name.startswith(("http://", "https://")):
                url = name
            elif re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}(/[^\s]*)?", name):
                url = "https://" + name
            else:
                query = urllib.parse.quote_plus(target.strip())
                url = f"https://www.google.com/search?q={query}"
        chrome = self.find_chrome()
        if chrome:
            subprocess.Popen([chrome, url], close_fds=True)
            self.say(f"Opening {target} in Chrome.")
        else:
            webbrowser.open(url)
            self.say(f"Chrome wasn't found, so I opened {target} in your default browser.")

    def close_spotify(self):
        try:
            result = subprocess.run(
                ["taskkill", "/IM", "Spotify.exe", "/T"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired):
            self.say("I couldn't close Spotify right now. Please try again.")
            return
        if result.returncode == 0:
            self.say("Closing Spotify.")
        else:
            self.say("Spotify is already closed.")

    def open_target(self, target):
        if "schoology" in target:
            self.open_website("schoology")
        elif "spotify" in target:
            candidates = [
                Path(os.environ.get("APPDATA", "")) / "Spotify/Spotify.exe",
                Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Spotify/Spotify.exe",
                Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Spotify/Spotify.exe",
            ]
            spotify = shutil.which("Spotify.exe") or next(
                (str(path) for path in candidates if path.exists()), None
            )
            if spotify:
                subprocess.Popen([spotify], close_fds=True)
            else:
                try:
                    os.startfile("spotify:")
                except (AttributeError, OSError):
                    webbrowser.open("https://open.spotify.com")
            self.say("Opening Spotify.")
        elif self.clean_target(target) in ("chrome", "google chrome", "browser"):
            self.open_website("google.com")
        elif self.clean_target(target) == "google":
            self.open_website("google.com")
        else:
            cleaned = self.clean_target(target)
            spotify_aliases = ["spotify", "spotfy", "spotifai", "spotifiy", "spottyfy", "spotfi", "spot ify", "spotty fi", "music", "music player"]
            spotify_match = self.best_service_match(cleaned, spotify_aliases)
            if spotify_match:
                self.open_target("spotify")
            elif self.best_service_match(cleaned, ["schoology"]):
                self.open_website("schoology")
            else:
                self.open_website(cleaned)
    def read_due(self):
        upcoming = []
        today = date.today()
        for item in self.assignments:
            dt = self.parse_due(item.get("due", ""))
            if dt and dt.date() >= today:
                upcoming.append((dt, item))
        upcoming.sort(key=lambda pair: pair[0])
        if not upcoming:
            self.say("I don't see any upcoming assignments. Try syncing Schoology.")
            return
        lines = [f'{item.get("title", "Assignment")} for {item.get("course", "your class")} is due {dt.strftime("%A, %B %d")}.'
                 for dt, item in upcoming[:5]]
        self.say(" ".join(lines))

    def add_assignment_from_text(self, value):
        match = re.match(r"(.+?)\s+due\s+(\d{4}-\d{2}-\d{2})$", value, re.I)
        if not match:
            self.say("Use this format: add assignment Essay due 2026-10-01.")
            return
        title, due = match.groups()
        try:
            datetime.strptime(due, "%Y-%m-%d")
        except ValueError:
            self.say("That date doesn't look valid. Use year-month-day.")
            return
        self.assignments.append({"id": f"manual:{time.time_ns()}", "title": title.strip(),
                                 "course": "Personal", "due": due, "source": "Manual"})
        write_json(DATA_FILE, self.assignments)
        self.refresh_assignments()
        self.say(f"Added {title.strip()}, due {due}.")

    def add_assignment_dialog(self):
        dialog = Toplevel(self.root)
        dialog.title("Add assignment")
        dialog.transient(self.root)
        dialog.grab_set()
        fields = {}
        for row, (label, key, initial) in enumerate((("Assignment", "title", ""), ("Class", "course", ""), ("Due date (YYYY-MM-DD)", "due", ""))):
            ttk.Label(dialog, text=label).grid(row=row, column=0, padx=12, pady=8, sticky="w")
            entry = ttk.Entry(dialog, width=34)
            entry.grid(row=row, column=1, padx=12, pady=8)
            entry.insert(0, initial)
            fields[key] = entry

        feedback = ttk.Label(dialog, foreground="#ff9b8f")
        feedback.grid(row=3, column=0, columnspan=2, padx=12, sticky="w")

        def save():
            title, course, due = (fields[k].get().strip() for k in ("title", "course", "due"))
            if not title or not self.parse_due(due):
                feedback.configure(text="Enter an assignment name and a valid date like 2026-10-01.")
                return
            self.assignments.append({"id": f"manual:{time.time_ns()}", "title": title,
                                     "course": course or "Personal", "due": due, "source": "Manual"})
            write_json(DATA_FILE, self.assignments)
            self.refresh_assignments()
            dialog.destroy()
            self.say(f"Added {title}, due {due}.")

        ttk.Button(dialog, text="Save", command=save).grid(row=4, column=1, padx=12, pady=12, sticky="e")

    def schoology_settings(self):
        dialog = Toplevel(self.root)
        dialog.title("Schoology API settings")
        dialog.transient(self.root)
        dialog.grab_set()
        entries = {}
        labels = [
            ("Consumer key", "key"), ("Consumer secret", "secret"),
            ("Schoology user ID (optional)", "user_id"), ("API base URL", "base_url"),
        ]
        for row, (label, key) in enumerate(labels):
            ttk.Label(dialog, text=label).grid(row=row, column=0, padx=12, pady=8, sticky="w")
            entry = ttk.Entry(dialog, width=48, show="*" if key == "secret" else "")
            entry.grid(row=row, column=1, padx=12, pady=8)
            if key == "base_url":
                entry.insert(0, self.settings.get(key, SCHOOLOGY_DEFAULT))
            elif key != "secret":
                entry.insert(0, self.settings.get(key, ""))
            entries[key] = entry
        ttk.Label(dialog, text="Your school may need to enable API access. The secret is stored in Windows Credential Manager.",
                  wraplength=480).grid(row=4, column=0, columnspan=2, padx=12, pady=8, sticky="w")

        feedback = ttk.Label(dialog, foreground="#ff9b8f")
        feedback.grid(row=5, column=0, columnspan=2, padx=12, sticky="w")

        def save():
            key = entries["key"].get().strip()
            secret = entries["secret"].get().strip()
            if not key or not secret:
                feedback.configure(text="Enter the consumer key and secret from your school.")
                return
            try:
                import keyring
                keyring.set_password("JarvisSchoology", "consumer_secret", secret)
            except Exception as exc:
                feedback.configure(text=f"Secure storage unavailable: {exc}")
                return
            self.settings = {
                "key": key,
                "user_id": entries["user_id"].get().strip(),
                "base_url": entries["base_url"].get().strip().rstrip("/"),
            }
            write_json(SETTINGS_FILE, self.settings)
            dialog.destroy()
            self.say("Schoology settings saved. Starting sync.")
            self.sync_schoology()

        ttk.Button(dialog, text="Save and connect", command=save).grid(row=6, column=1, padx=12, pady=12, sticky="e")

    def sync_schoology(self):
        if not self.settings.get("key"):
            self.schoology_settings()
            return
        self.status.set("Connecting to Schoologyâ€¦")
        threading.Thread(target=self._sync_worker, daemon=True).start()

    def _sync_worker(self):
        try:
            import keyring
            secret = keyring.get_password("JarvisSchoology", "consumer_secret")
            if not secret:
                raise RuntimeError("Schoology secret not found. Open Schoology setup and save your credentials.")
            api = Schoology(self.settings["key"], secret, self.settings.get("base_url", SCHOOLOGY_DEFAULT))
            items = api.assignments(self.settings.get("user_id") or "me")
            self.events.put(("sync_ok", items))
        except Exception as exc:
            self.events.put(("error", f"Schoology sync failed: {exc}"))

    def process_events(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "sync_ok":
                    manual = [a for a in self.assignments if a.get("source") != "Schoology"]
                    self.assignments = manual + value
                    write_json(DATA_FILE, self.assignments)
                    self.refresh_assignments()
                    self.say(f"Synced {len(value)} assignments from Schoology.")
                elif kind == "partial":
                    self.status.set(f"HEARING: {value}")
                    self.log.configure(text=f'I heard: "{value}"')
                elif kind == "speech":
                    self.handle_command(value, from_voice=True)
                elif kind == "speech_unclear":
                    self.status.set("VOICE UNCLEAR - PLEASE REPEAT")
                    self.log.configure(text="I didn't catch that clearly. Please repeat the full command.")
                elif kind == "voice_device":
                    self.status.set(f"VOICE INPUT: {value}")
                elif kind == "chat_ok":
                    answer, speak_response = value
                    self.chat_busy = False
                    if self.chat_send_button is not None and self.chat_send_button.winfo_exists():
                        self.chat_send_button.configure(state="normal")
                    self._chat_append("Jarvis", answer)
                    if speak_response:
                        self.say(answer)
                elif kind == "chat_error":
                    self.chat_busy = False
                    if self.chat_send_button is not None and self.chat_send_button.winfo_exists():
                        self.chat_send_button.configure(state="normal")
                    self._chat_append("Jarvis", value)
                    self.status.set("CHAT NEEDS ATTENTION")
                    self.log.configure(text=value)
                elif kind == "main_reply_ok":
                    answer, speak_response = value
                    self.main_reply_busy = False
                    self.main_conversation_history.append({"role": "assistant", "content": answer})
                    self.main_conversation_history = self.main_conversation_history[-16:]
                    self.display_main_reply(answer, speak_response)
                elif kind == "main_reply_error":
                    message, speak_response = value
                    self.main_reply_busy = False
                    if self.main_conversation_history and self.main_conversation_history[-1].get("role") == "user":
                        self.main_conversation_history.pop()
                    self.display_main_reply(message, speak_response)
                    self.status.set("JARVIS COULDN'T CONNECT")
                elif kind == "error":
                    if value.startswith("Voice setup error:"):
                        self.listening = False
                        self.listen_button.configure(text="?   START VOICE LISTENING")
                    self.status.set(value)
                    self.log.configure(text=value)
        except queue.Empty:
            pass
        self.root.after(150, self.process_events)

    def add_reminder_from_text(self, text):
        match = re.match(r"^(?:remind me to|set (?:a )?reminder to)\s+(.+)$", text.strip().rstrip("?!.,"), re.I)
        if not match:
            self.say("Try: remind me to study in 20 minutes, or remind me to study at 2026-10-01 3:30 PM.")
            return
        reminder_text = match.group(1).strip()
        due = None
        relative = re.match(r"^(.+?)\s+in\s+(\d+)\s+(minutes?|hours?)$", reminder_text, re.I)
        if relative:
            reminder_text, amount, unit = relative.groups()
            amount = int(amount)
            if amount < 1 or amount > 100000:
                self.say("Choose a reminder delay between 1 minute and about 69 days.")
                return
            due = datetime.now() + timedelta(minutes=amount * (60 if unit.lower().startswith("hour") else 1))
        else:
            absolute = re.match(
                r"^(.+?)\s+at\s+(?:(\d{4}-\d{2}-\d{2})\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$",
                reminder_text,
                re.I,
            )
            if absolute:
                reminder_text, date_text, hour_text, minute_text, meridiem = absolute.groups()
                hour = int(hour_text)
                minute = int(minute_text or 0)
                if minute > 59:
                    due = None
                elif meridiem:
                    if not 1 <= hour <= 12:
                        due = None
                    else:
                        hour = hour % 12 + (12 if meridiem.lower() == "pm" else 0)
                elif not 0 <= hour <= 23 or (minute_text is None and hour <= 12):
                    due = None
                if (minute <= 59 and (meridiem is None or 1 <= int(hour_text) <= 12)
                        and (meridiem is not None or (0 <= int(hour_text) <= 23 and (minute_text is not None or int(hour_text) > 12)))):
                    try:
                        due_date = datetime.strptime(date_text, "%Y-%m-%d").date() if date_text else date.today()
                        due = datetime(due_date.year, due_date.month, due_date.day, hour, minute)
                        if not date_text and due <= datetime.now():
                            due += timedelta(days=1)
                    except ValueError:
                        due = None
        if not reminder_text or due is None:
            self.say("I couldn't read that reminder time. Try: remind me to study in 20 minutes, or at 2026-10-01 3:30 PM.")
            return
        if due <= datetime.now():
            self.say("That time has already passed. Please choose a future time.")
            return
        reminder = {"id": str(time.time_ns()), "text": reminder_text, "due": due.strftime("%Y-%m-%d %H:%M:%S")}
        self.reminders.append(reminder)
        write_json(REMINDERS_FILE, self.reminders)
        self.say(f"Reminder saved for {due.strftime('%A, %B %d at %I:%M %p')}: {reminder_text}.")

    def read_reminders(self):
        upcoming = []
        for reminder in self.reminders:
            due = self.parse_due(reminder.get("due", ""))
            if due:
                upcoming.append((due, reminder.get("text", "Reminder")))
        upcoming.sort(key=lambda item: item[0])
        if not upcoming:
            self.say("You don't have any saved reminders.")
            return
        self.say("Your reminders are: " + ". ".join(
            f"{text}, {due.strftime('%A, %B %d at %I:%M %p')}" for due, text in upcoming
        ))

    def reminder_tick(self):
        now = datetime.now()
        for item in self.assignments:
            due = self.parse_due(item.get("due", ""))
            if due and due.date() == now.date():
                reminder_id = item.get("id", item.get("title"))
                if reminder_id not in self.reminded:
                    self.reminded.add(reminder_id)
                    self.say(f"Reminder: {item.get('title')} is due today.")
        pending = []
        due_reminders = []
        for reminder in self.reminders:
            due = self.parse_due(reminder.get("due", ""))
            if due and due <= now:
                due_reminders.append(reminder)
            else:
                pending.append(reminder)
        if due_reminders:
            self.reminders = pending
            write_json(REMINDERS_FILE, self.reminders)
            for reminder in due_reminders:
                self.say(f"Reminder: {reminder.get('text', 'Your reminder')}.")
        self.root.after(15000, self.reminder_tick)

    def periodic_sync(self):
        if self.settings.get("key"):
            self.sync_schoology()
        self.root.after(1800000, self.periodic_sync)

    def toggle_voice(self):
        if self.listening:
            self.listening = False
            self.audio_level = 0.0
            self.listen_button.configure(text="?   START VOICE LISTENING")
            self.say("All right, I will wait here. Say the word when you need me.")
        else:
            if not MODEL_DIR.exists():
                message = "The local voice model is missing. Run setup.bat while online, then restart Jarvis."
                self.status.set("VOICE MODEL NEEDED")
                self.log.configure(text=message)
                return
            self.mic_device_candidates = self.available_microphones()
            self.mic_device_index = self.mic_device_candidates[0] if self.mic_device_candidates else None
            if self.mic_device_index is None:
                detail = self.audio_input_error or "Windows did not report an enabled audio input."
                message = f"No microphone found. Check Windows Settings > System > Sound > Input. Details: {detail}"
                self.status.set("VOICE INPUT UNAVAILABLE")
                self.log.configure(text=message)
                return
            self.listening = True
            self.listen_button.configure(text="Â¦   STOP VOICE LISTENING")
            self.say("I am listening. Speak clearly, a little closer to your microphone. What can I do for you?")
            self.voice_thread = threading.Thread(target=self._voice_worker, daemon=True)
            self.voice_thread.start()
    def _voice_worker(self):
        try:
            import sounddevice as sd
            from vosk import KaldiRecognizer, Model
            if self.voice_model is None:
                self.voice_model = Model(str(MODEL_DIR))
            candidates = self.available_microphones()
            if self.mic_device_index in candidates:
                candidates.remove(self.mic_device_index)
                candidates.insert(0, self.mic_device_index)
            if not candidates:
                raise RuntimeError("No microphone is selected.")
            errors = []
            for device_index in candidates:
                if not self.listening:
                    return
                try:
                    audio_blocks = queue.Queue(maxsize=32)
                    device_info = sd.query_devices(device_index)
                    default_rate = int(device_info["default_samplerate"])
                    sample_rate = None
                    # Vosk is trained for 16 kHz, so use it directly when available.
                    # Otherwise use the microphone's native rate and resample once.
                    candidate_rates = list(dict.fromkeys((16000, default_rate, 48000, 44100)))
                    for candidate_rate in candidate_rates:
                        try:
                            sd.check_input_settings(device=device_index, samplerate=candidate_rate,
                                                    channels=1, dtype="int16")
                            sample_rate = candidate_rate
                            break
                        except Exception:
                            continue
                    if sample_rate is None:
                        raise RuntimeError(f"Microphone does not support a usable sample rate (default {default_rate} Hz).")
                    blocksize = max(1, round(sample_rate * 0.08))
                    audio_filter_state = [0.0, 0.0, 1.0]
                    recognizer = KaldiRecognizer(self.voice_model, 16000)
                    recognizer.SetWords(True)
                    last_partial = ""

                    def callback(indata, frames, timing, status):
                        if self.listening:
                            try:
                                audio_bytes = bytes(indata)
                                samples = array.array("h")
                                samples.frombytes(audio_bytes)
                                if samples:
                                    rms = (sum(sample * sample for sample in samples) / len(samples)) ** 0.5
                                    self.audio_level = max(min(rms / 2600, 1.0), self.audio_level * 0.72)
                                audio_blocks.put_nowait(audio_bytes)
                            except queue.Full:
                                pass

                    with sd.RawInputStream(samplerate=sample_rate, blocksize=blocksize, dtype="int16",
                                           channels=1, device=device_index, callback=callback):
                        self.mic_device_index = device_index
                        device_name = sd.query_devices(device_index)["name"]
                        self.events.put(("voice_device", str(device_name)))
                        while self.listening:
                            try:
                                block = audio_blocks.get(timeout=0.25)
                            except queue.Empty:
                                continue
                            if sample_rate != 16000:
                                block = self.resample_pcm(block, sample_rate)
                            block = self.prepare_voice_audio(block, audio_filter_state)
                            if recognizer.AcceptWaveform(block):
                                result = json.loads(recognizer.Result())
                                phrase = result.get("text", "").strip()
                                last_partial = ""
                                if phrase:
                                    confidences = [float(word["conf"]) for word in result.get("result", [])
                                                   if isinstance(word, dict) and "conf" in word]
                                    if confidences and sum(confidences) / len(confidences) < 0.45:
                                        self.events.put(("speech_unclear", phrase))
                                    else:
                                        self.events.put(("speech", phrase))
                            else:
                                partial = json.loads(recognizer.PartialResult()).get("partial", "").strip()
                                if partial and partial != last_partial:
                                    last_partial = partial
                                    self.events.put(("partial", partial))
                    return
                except Exception as exc:
                    errors.append(f"{sd.query_devices(device_index)['name']}: {exc}")
            if self.listening:
                raise RuntimeError("Could not open any available microphone. " + " | ".join(errors))
        except Exception as exc:
            self.events.put(("error", f"Voice setup error: {exc}"))
            self.listening = False

    def open_chat(self, initial_prompt="", speak_response=False):
        if self.chat_window is not None and self.chat_window.winfo_exists():
            self.chat_window.deiconify()
            self.chat_window.lift()
        else:
            window = Toplevel(self.root)
            self.chat_window = window
            window.title("Chat with Jarvis")
            window.geometry("700x560")
            window.minsize(520, 400)
            window.configure(bg=self.colors["bg"])
            window.protocol("WM_DELETE_WINDOW", self._close_chat)
            top = ttk.Frame(window, style="Panel.TFrame", padding=(14, 10))
            top.pack(fill="x")
            ttk.Label(top, text="CHAT WITH JARVIS", style="PanelTitle.TLabel").pack(side="left")
            ttk.Button(top, text="OPEN CHATGPT", command=lambda: webbrowser.open("https://chatgpt.com/")).pack(side="right", padx=(8, 0))
            ttk.Button(top, text="API KEY", command=self.chat_api_settings).pack(side="right")
            ttk.Button(top, text="COPY CHAT", command=self.copy_chat_transcript).pack(side="right", padx=(8, 0))
            self.chat_transcript = Text(window, wrap="word", state="disabled", bg="#08131d",
                                        fg=self.colors["text"], insertbackground=self.colors["cyan"],
                                        selectbackground="#17465b", relief="flat", padx=14, pady=12,
                                        font=("Segoe UI", 10))
            self.chat_transcript.pack(fill="both", expand=True, padx=14, pady=12)
            self.chat_transcript.tag_configure("user", foreground=self.colors["cyan"], font=("Segoe UI", 10, "bold"))
            self.chat_transcript.tag_configure("jarvis", foreground=self.colors["text"], font=("Segoe UI", 10))
            compose = ttk.Frame(window, style="Panel.TFrame", padding=12)
            compose.pack(fill="x", padx=14, pady=(0, 14))
            self.chat_entry = ttk.Entry(compose)
            self.chat_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
            self.chat_entry.bind("<Return>", lambda _event: self.send_chat())
            self.chat_entry.focus_set()
            self.chat_send_button = ttk.Button(compose, text="SEND", style="Accent.TButton", command=self.send_chat)
            self.chat_send_button.pack(side="right")
            self._chat_append("Jarvis", "Hey! Ask me anything, or tell me what you are working on. Your conversation stays in this window.")
        if initial_prompt.strip():
            self._send_chat_text(initial_prompt.strip(), speak_response)

    def _close_chat(self):
        if self.chat_window is not None and self.chat_window.winfo_exists():
            self.chat_window.destroy()
        self.chat_window = None
        self.chat_transcript = None
        self.chat_entry = None
        self.chat_send_button = None

    def _chat_append(self, speaker, text):
        if self.chat_transcript is None:
            return
        self.chat_transcript.configure(state="normal")
        style = "user" if speaker == "You" else "jarvis"
        self.chat_transcript.insert(END, f"{speaker}\n", style)
        self.chat_transcript.insert(END, text + "\n\n", style)
        self.chat_transcript.configure(state="disabled")
        self.chat_transcript.see(END)

    def copy_chat_transcript(self):
        if self.chat_transcript is None:
            return
        transcript = self.chat_transcript.get("1.0", "end-1c").strip()
        if not transcript:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(transcript)
        self.root.update_idletasks()
        self.log.configure(text="Chat copied to clipboard.")

    def send_chat(self):
        if self.chat_entry is None:
            return
        prompt = self.chat_entry.get().strip()
        if not prompt:
            return
        self.chat_entry.delete(0, END)
        self._send_chat_text(prompt, False)

    def _send_chat_text(self, prompt, speak_response, already_shown=False):
        if self.chat_busy:
            self._chat_append("Jarvis", "One moment, I'm finishing the last reply.")
            return
        greeting = re.sub(r"[.!?,]+$", "", prompt.lower().strip())
        if greeting in {"hi", "hey", "hello", "hi jarvis", "hey jarvis", "hello jarvis"}:
            if not already_shown:
                self._chat_append("You", prompt)
            answer = random.choice((
                "Hey! Good to hear from you. What can I help with?",
                "Hello! I'm here and ready. What are we working on?",
                "Hey, how's it going? What can I do for you?",
            ))
            self._chat_append("Jarvis", answer)
            if speak_response:
                self.say(answer)
            return
        api_key = self.get_chat_api_key()
        if not api_key:
            self.chat_pending_prompt = "\n\n".join(filter(None, (self.chat_pending_prompt, prompt)))
            self.chat_pending_speech = speak_response
            self._chat_append("You", prompt)
            self._chat_append("Jarvis", "Your message is saved. Chat needs an OpenAI API key before it can answer. Select API KEY above; I will send your message after you save the key.")
            return
        self.chat_history.append({"role": "user", "content": prompt})
        if not already_shown:
            self._chat_append("You", prompt)
        self.chat_busy = True
        self.chat_send_button.configure(state="disabled")
        self._chat_append("Jarvis", "Thinkingâ€¦")
        threading.Thread(target=self._chat_worker, args=(api_key, list(self.chat_history), speak_response),
                         daemon=True, name="jarvis-chat").start()

    @staticmethod
    def get_chat_api_key():
        try:
            import keyring
            return keyring.get_password("JarvisOpenAI", "api_key")
        except Exception:
            return None

    def respond_to_conversation(self, prompt, speak_response=False):
        if self.main_reply_busy:
            message = "I'm finishing my last answer. Give me a moment, then tell me the next thing."
            self.display_main_reply(message, speak_response)
            return
        api_key = self.get_chat_api_key()
        if not api_key:
            message = ("I can't answer that one offline yet. For open-ended questions, connect an API key "
                       "using CHAT WITH JARVIS, then API KEY. Built-in commands, simple questions, and "
                       "calculations still work offline.")
            self.display_main_reply(message, speak_response)
            return
        self.main_conversation_history.append({"role": "user", "content": prompt})
        self.main_conversation_history = self.main_conversation_history[-16:]
        self.main_reply_busy = True
        self.status.set("JARVIS IS THINKING")
        self.log.configure(text="Thinking about what you said...")
        threading.Thread(
            target=self._main_conversation_worker,
            args=(api_key, list(self.main_conversation_history), speak_response),
            daemon=True,
            name="jarvis-conversation",
        ).start()

    def display_main_reply(self, text, speak_response=False):
        if speak_response:
            self.say(text)
        else:
            self.feed_message("JARVIS", text)
            self.status.set("JARVIS")
            self.log.configure(text=text)

    def _main_conversation_worker(self, api_key, history, speak_response):
        payload = {
            "model": CHAT_MODEL,
            "instructions": (
                "You are Jarvis, a thoughtful, friendly assistant. Respond directly to what the user said, "
                "including personal statements, instead of treating every message like a command. Make your "
                "point clearly: state your recommendation or view first, then give the main reason. Be honest "
                "about uncertainty, avoid pretending to have feelings or to have taken actions, and ask one "
                "focused question when more context is needed. Keep replies natural and concise."
            ),
            "input": history,
            "max_output_tokens": 900,
        }
        request = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                result = json.loads(response.read().decode("utf-8"))
            answer = result.get("output_text", "").strip()
            if not answer:
                answer = "\n".join(
                    part.get("text", "")
                    for item in result.get("output", []) if item.get("type") == "message"
                    for part in item.get("content", []) if part.get("type") == "output_text"
                ).strip()
            if not answer:
                raise RuntimeError("The API returned no text.")
            self.events.put(("main_reply_ok", (answer, speak_response)))
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                message = "Jarvis couldn't answer because the saved API key was rejected. Replace it in CHAT WITH JARVIS > API KEY."
            elif exc.code == 429:
                message = "Jarvis couldn't answer because API usage is unavailable. Check the API project's billing or quota."
            else:
                message = f"Jarvis couldn't answer. The API returned error {exc.code}."
            self.events.put(("main_reply_error", (message, speak_response)))
        except Exception as exc:
            self.events.put(("main_reply_error", (f"Jarvis couldn't connect for an answer: {exc}", speak_response)))

    def _chat_worker(self, api_key, history, speak_response):
        payload = {
            "model": CHAT_MODEL,
            "instructions": "You are Jarvis, a thoughtful, friendly assistant. Respond directly and make your point clearly, giving the main reason. Explain ideas clearly, guide the student through homework rather than simply doing graded work for them, and be honest when unsure. Keep replies concise unless asked for detail.",
            "input": history,
            "max_output_tokens": 1200,
        }
        request = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                result = json.loads(response.read().decode("utf-8"))
            answer = result.get("output_text", "").strip()
            if not answer:
                answer = "\n".join(
                    part.get("text", "")
                    for item in result.get("output", []) if item.get("type") == "message"
                    for part in item.get("content", []) if part.get("type") == "output_text"
                ).strip()
            if not answer:
                raise RuntimeError("The API returned no text. Please try again.")
            self.chat_history.append({"role": "assistant", "content": answer})
            self.events.put(("chat_ok", (answer, speak_response)))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")[:350]
            if exc.code == 401:
                message = "The API key was rejected. Open API KEY and replace it with a valid OpenAI API platform key."
            elif exc.code == 429:
                message = "The OpenAI API quota is unavailable. Check that API billing is active and the project has available credits."
            elif exc.code == 403:
                message = "This API project cannot use the selected model. Check project access and API billing."
            else:
                message = f"OpenAI API returned {exc.code}: {details}"
            self.events.put(("chat_error", message))
        except Exception as exc:
            self.events.put(("chat_error", f"Chat couldn't connect: {exc}"))

    def chat_api_settings(self):
        if self.chat_settings_dialog is not None and self.chat_settings_dialog.winfo_exists():
            self.chat_settings_dialog.lift()
            return
        dialog = Toplevel(self.root)
        self.chat_settings_dialog = dialog
        dialog.title("Jarvis AI chat settings")
        dialog.transient(self.chat_window if self.chat_window is not None and self.chat_window.winfo_exists() else self.root)
        dialog.grab_set()
        dialog.protocol("WM_DELETE_WINDOW", lambda: (dialog.destroy(), setattr(self, "chat_settings_dialog", None)))
        ttk.Label(dialog, text="OpenAI API key").grid(row=0, column=0, padx=12, pady=12, sticky="w")
        entry = ttk.Entry(dialog, width=48, show="*")
        entry.grid(row=0, column=1, padx=12, pady=12)
        entry.focus_set()
        ttk.Label(dialog, text="Create a key in the OpenAI API platform. API usage may be billed separately from ChatGPT.",
                  wraplength=450).grid(row=1, column=0, columnspan=2, padx=12, pady=4, sticky="w")

        feedback = ttk.Label(dialog, foreground="#ff9b8f")
        feedback.grid(row=2, column=0, columnspan=2, padx=12, sticky="w")

        def save():
            key = entry.get().strip()
            if not key:
                feedback.configure(text="Paste an OpenAI API key to enable chat.")
                return
            try:
                import keyring
                keyring.set_password("JarvisOpenAI", "api_key", key)
            except Exception as exc:
                feedback.configure(text=f"Secure storage unavailable: {exc}")
                return
            dialog.destroy()
            self.chat_settings_dialog = None
            pending_prompt = self.chat_pending_prompt
            pending_speech = self.chat_pending_speech
            self.chat_pending_prompt = None
            self.chat_pending_speech = False
            if pending_prompt:
                self._chat_append("Jarvis", "Key saved. Sending your question nowâ€¦")
                self._send_chat_text(pending_prompt, pending_speech, already_shown=True)
            else:
                self._chat_append("Jarvis", "API key saved securely. Chat is ready; send your question when you are.")

        ttk.Button(dialog, text="OPEN API KEYS", command=lambda: webbrowser.open("https://platform.openai.com/api-keys")).grid(
            row=3, column=0, padx=12, pady=12, sticky="w")
        ttk.Button(dialog, text="Save key", style="Accent.TButton", command=save).grid(
            row=3, column=1, padx=12, pady=12, sticky="e")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    APP_DIR.mkdir(parents=True, exist_ok=True)
    JarvisApp(Tk()).run()




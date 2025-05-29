import shutil
import flet as ft
import subprocess
import threading
import os
import re
from datetime import datetime
import uuid
import webbrowser
import json
# pip install flet requests pyinstaller

default_dir = os.path.join(os.path.expanduser("~"), "Videos", "Easy download YouTube")
if not os.path.exists(default_dir):
    os.makedirs(default_dir, exist_ok=True)
    
# צבעים והגדרות גלובליות
PRIMARY = "#3CB371"
SECONDARY = "#A8E6CF"
TEXT = "#111111"
WHITE = "#fff"
ERROR = "#d32f2f"
LOG_FILE = "yt_dlp_log.txt"
ffmpeg_actual = os.path.abspath(os.path.join("bin", "ffmpeg"))
if os.name == "nt":
    ffmpeg_actual += ".exe"
import urllib.parse


import requests
import urllib3

# לבטל אזהרות SSL (אם צריך)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def is_playlist(url):
    # בדיקה בסיסית: אם יש list= ב-URL
    return "list=" in url



def get_title_by_scraping(url):
    headers = {'User-Agent': 'Mozilla/5.0'}
    resp = requests.get(url, headers=headers, verify=False)
    if resp.status_code == 200:
        match = re.search(r'<title>(.*?)</title>', resp.text)
        if match:
            title = match.group(1).replace(" - YouTube", "").strip()
            return truncate_title(title)
    return "הורדה"

def truncate_title(title, max_words=6):
    words = title.split()
    if len(words) > max_words:
        return ' '.join(words[:max_words]) + '...'
    return title

def extract_video_id(url):
    # תופס את כל הצורות הנפוצות של קישורי YouTube
    match = re.search(r"(?:v=|be/|embed/|shorts/)([\w-]{11})", url)
    if match:
        return match.group(1)
    return None

def get_youtube_thumbnail_url(url):
    video_id = extract_video_id(url)
    if video_id:
        # HQ – איכות גבוהה, אפשר לשנות ל'mqdefault.jpg' או 'maxresdefault.jpg' (אם יש)
        return f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
    return ""  # או כתובת לתמונה ברירת מחדל


def write_log(msg):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{msg}\n")

def fetch_title_and_thumbnail(url):
    thumbnail_url = get_youtube_thumbnail_url(url)
    title = get_title_by_scraping(url)
    if not title.strip():
        title = "הורדה"
    return title, thumbnail_url

def show_snackbar(page, msg, success=True):
    page.snack_bar = ft.SnackBar(
        ft.Text(msg, color=WHITE),
        bgcolor=PRIMARY if success else ERROR,
        duration=2200
    )
    page.snack_bar.open = True
    page.update()


def run_download_with_cancel(
    page, url, format_option, output_dir,
    progress_bar, progress_text, status_text,
    show_snackbar_fn, on_done, download_id, cancel_event,
    title, ext
):
    try:
        cmd = format_option + [url]
        write_log(f"\n--- התחלת הורדה: {url} ---\n")
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=output_dir,
            encoding="utf-8",
            errors="replace",
            startupinfo=startupinfo
        )

        last_percent = -1
        all_output = ""
        output_filename = None

        for line in process.stdout:
            if cancel_event.is_set():
                process.terminate()
                status_text.value = "בוטל ע\"י המשתמש"
                status_text.update()
                show_snackbar_fn(page, "ההורדה בוטלה.", False)
                return False

            write_log(line.strip())
            all_output += line

            # שלוף את שם הקובץ מהפלט
            m_dest = re.search(r'\[download\] Destination: (.+)', line)
            if m_dest:
                output_filename = m_dest.group(1).strip()

            # עדיין תומך גם בזיהוי ממזוג
            m_merge = re.search(r"\[Merger\] Merging formats into \"(.+?)\"", line)
            if m_merge:
                output_filename = m_merge.group(1).strip()
                status_text.value = "ממזג קבצים..."
                status_text.update()

            found = re.search(r"(\d{1,3}(?:\.\d)?)%", line)
            if found:
                percent = float(found.group(1))
                if percent != last_percent:
                    progress_bar.value = percent / 100
                    progress_text.value = f"{percent:.1f}%"
                    progress_bar.update()
                    progress_text.update()
                    last_percent = percent

        process.wait()

        if process.returncode == 0:
            progress_bar.value = 1
            progress_text.value = "100%"
            progress_bar.update()
            progress_text.update()
            status_text.value = "הסתיים בהצלחה!"
            status_text.update()
            show_snackbar_fn(page, "✔️ ההורדה הסתיימה בהצלחה!", True)

            # בדוק את הקובץ שהתקבל מהפלט
            if output_filename and os.path.exists(output_filename):
                file_size = os.path.getsize(output_filename)
                # נניח סף של 50KB להצלחת הורדה
                if file_size > 50 * 1024:
                    show_snackbar_fn(page, f"✔️ הקובץ נשמר בתיקיית היעד! ({file_size // 1024} KB)", True)
                else:
                    show_snackbar_fn(page, f"שגיאה: הקובץ {output_filename} קטן מדי ({file_size} bytes), כנראה לא ירד כהלכה.", False)
                    write_log(f"שגיאה: הקובץ {output_filename} קטן מדי ({file_size} bytes)")
            else:
                show_snackbar_fn(page, f"שגיאה: לא נמצא קובץ הורדה בשם {output_filename or '[לא ידוע]'}!", False)
                write_log(f"שגיאה: לא נמצא קובץ הורדה בשם {output_filename or '[לא ידוע]'}!")
            return True
        else:
            status_text.value = "שגיאה בהורדה"
            status_text.update()
            if "certificate verify failed" in all_output:
                show_snackbar_fn(page, "❌ שגיאת אבטחה. בדוק את חיבור האינטרנט או את התעודות במערכת.", False)
            else:
                show_snackbar_fn(page, "❌ שגיאה בהורדה. בדוק את הלוג.", False)
            return False
    except Exception as e:
        status_text.value = "שגיאה כללית"
        status_text.update()
        write_log(f"שגיאה כללית: {e}")
        show_snackbar_fn(page, "❌ שגיאה כללית. בדוק את הלוג.", False)
        return False
    finally:
        if on_done:
            on_done()

def add_download_row(page, downloads_column, url, title, thumbnail_url, format_option, dest_dir_value, ext, try_only=False):
    download_id = str(uuid.uuid4())
    cancel_event = threading.Event()

    # נניח thumbnail_url כבר קיים
    thumb = ft.Image(
        src=thumbnail_url if thumbnail_url else "assets/no_thumbnail.png",
        width=100, height=56,
        border_radius=8, fit=ft.ImageFit.COVER
    )

    progress_anim = ft.Container(
        ft.ProgressRing(width=32, height=32, color=PRIMARY),
        alignment=ft.alignment.top_center,
        padding=6,
        visible=True  # תעדכן ל־False כשההורדה מסתיימת
    )

    thumb_stack = ft.Stack([
        thumb,
        progress_anim
    ], width=100, height=56)

    # בתוך ה־Row של הפס:
    ft.Row([
        ft.Container(
            thumb_stack,
            alignment=ft.alignment.center,
            expand=True,
            height=100
        ),
        ...
    ], vertical_alignment=ft.CrossAxisAlignment.CENTER)

    progress_bar = ft.ProgressBar(color=PRIMARY, bgcolor=SECONDARY, value=0, bar_height=58)#width=460, 
    progress_text = ft.Text("0%", size=16, color=PRIMARY, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER, width=250)
    status_text = ft.Text("מוריד...", size=14, color=TEXT)

    def cancel_download(e):
        cancel_event.set()

    def open_folder(e):
        folder = dest_dir_value
        try:
            if os.name == 'nt':
                os.startfile(folder)
            elif os.name == 'posix':
                subprocess.Popen(['xdg-open', folder])
            else:
                show_snackbar(page, "לא נתמך", False)
        except Exception:
            show_snackbar(page, "לא ניתן לפתוח תיקיה", False)

    cancel_btn = ft.IconButton(ft.Icons.CANCEL, tooltip="ביטול", on_click=cancel_download)
    open_folder_btn = ft.IconButton(ft.Icons.FOLDER_OPEN, tooltip="פתח תיקיה", on_click=open_folder)
    title, thumbnail_url = fetch_title_and_thumbnail(url)
    if not title.strip() or title == "לא ידוע":
        title = "הורדה"

    row = ft.Container(
        content=ft.Column([
            ft.Text(title, size=17, weight=ft.FontWeight.BOLD, color=PRIMARY),
            ft.Row([
                thumb,
                ft.Column([
                    ft.Stack([
                        progress_bar,
                        ft.Container(progress_text, alignment=ft.alignment.center)
                    ]),
                    status_text
                ], spacing=8,expand=True),  
                ft.Column([cancel_btn, open_folder_btn], spacing=6, alignment=ft.MainAxisAlignment.END)
            ], spacing=18, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ], spacing=10),
        bgcolor="#E3F2FD",
        border_radius=10,
        padding=12,
        margin=ft.Margin(0, 0, 0, 0),  # רווח מימין
        #width=380,  # או פחות/יותר לפי הצורך
        alignment=ft.alignment.center_right
    )

    downloads_column.controls.insert(0, row)
    page.update()

    threading.Thread(
        target=run_download_with_cancel,
        args=(
            page, url, format_option, dest_dir_value,
            progress_bar, progress_text, status_text,
            show_snackbar, None, download_id, cancel_event,
            title, ext 
        ),
        daemon=True
    ).start()

def main(page: ft.Page):
    BG = "#F6FFF6"
    page.title = "Easy download YouTube"
    page.window_min_width = 320
    page.window_max_width = 480
    page.bgcolor = BG
    page.theme = ft.Theme(
        color_scheme=ft.ColorScheme(
            primary=PRIMARY,
            secondary=SECONDARY,
            on_primary=WHITE,
            background=BG,
            surface=WHITE,
            on_surface=TEXT,
        )
    )

    download_mode = {"type": None}  # "playlist" או "single"
        
    url_input = ft.TextField(
        label="הדבק קישורים לסרטוני YouTube ",
        multiline=True,             # הפוך לשדה רב שורות
        min_lines=1,                # גובה התיבה
        max_lines=8,
        border_radius=10,
        border_color=PRIMARY,
        bgcolor=WHITE,
        color=TEXT,
        autofocus=True,
        expand=True,
    )

    format_choice = ft.RadioGroup(
        content=ft.Row([
            ft.Radio(value="mp4", label="וידאו (MP4)", fill_color=PRIMARY),
            ft.Radio(value="mp3", label="אודיו (MP3)", fill_color=PRIMARY),
        ]),
        value="mp4"
    )

    dest_dir_label = ft.Text(default_dir, color=PRIMARY, size=13, tooltip="תיקיית יעד נוכחית")

    dest_dir = ft.TextField(
        label="תיקיית יעד",
        value=default_dir,
        read_only=True,
        border_radius=10,
        border_color=PRIMARY,
        bgcolor=WHITE,
        color=TEXT,
        width=220
    )

    dlg = ft.FilePicker()
    page.overlay.append(dlg)


    def choose_folder(e):
        def set_dir(res: ft.FilePickerResultEvent):
            if res.path:
                dest_dir.value = res.path
                dest_dir_label.value = res.path      # ← עדכון התווית
                page.update()                        # ← רענון הדף
        dlg.on_result = set_dir
        dlg.get_directory_path()

    choose_folder_btn = ft.ElevatedButton(
        "תיקיית יעד", icon=ft.Icons.FOLDER_OPEN, bgcolor=SECONDARY, color=PRIMARY, on_click=choose_folder
    )

    def show_playlist_dialog(url, download_attempts, do_download, title, thumbnail_url):
        def handle_choice(e):
            choice = e.control.text
            page.close(banner)
            if choice == "הורד את כל הפלייליסט":
                video_urls = get_playlist_video_urls(url)
                if not video_urls:
                    show_snackbar(page, "לא נמצאו סרטונים בפלייליסט או שישנה שגיאה.", False)
                    return
                show_snackbar(page, f"נמצאו {len(video_urls)} סרטונים בפלייליסט, מתחיל להוריד...", True)
                for i, v_url in enumerate(video_urls, 1):
                    actual_url = f"https://www.youtube.com/watch?v={v_url}"
                    actual_title, actual_thumbnail = fetch_title_and_thumbnail(actual_url)
                    threading.Thread(
                        target=do_download,
                        args=(actual_url, actual_title, actual_thumbnail, download_attempts),
                        daemon=True
                    ).start()
            elif choice == "הורד רק את הסרטון הזה":
                    single_url = extract_single_video_url(url)
                    threading.Thread(
                        target=do_download,
                        args=(single_url, title, thumbnail_url, download_attempts),
                        daemon=True
                    ).start()

        action_button_style = ft.ButtonStyle(color=ft.Colors.BLUE)
        banner = ft.Banner(
            bgcolor=ft.Colors.AMBER_100,
            leading=ft.Icon(ft.Icons.QUEUE_PLAY_NEXT, color=ft.Colors.AMBER, size=40),
            content=ft.Text("זיהינו קישור לפלייליסט. מה תרצה להוריד?", color=ft.Colors.BLACK),
            actions=[
                ft.TextButton(text="הורד את כל הפלייליסט", style=action_button_style, on_click=handle_choice),
                ft.TextButton(text="הורד רק את הסרטון הזה", style=action_button_style, on_click=handle_choice),
                ft.TextButton(text="ביטול", style=action_button_style, on_click=lambda e: page.close(banner)),
            ],
        )
        page.open(banner)
        
    def open_log(e):
        try:
            os.startfile(LOG_FILE)
        except Exception:
            show_snackbar(page, "לא נמצא קובץ לוג", False)

    open_log_btn = ft.IconButton(
        icon=ft.Icons.DESCRIPTION,
        on_click=open_log,
        bgcolor=SECONDARY,
        icon_color=PRIMARY,
        tooltip="לוג"
    )
    downloads_column = ft.Column(spacing=16, expand=True, scroll=ft.ScrollMode.ALWAYS)


    def extract_single_video_url(youtube_url):
        """
        מקבלת קישור יוטיוב (גם מתוך פלייליסט) ומחזירה קישור לסרטון בודד.
        """
        parsed = urllib.parse.urlparse(youtube_url)
        qs = urllib.parse.parse_qs(parsed.query)
        if "v" not in qs:
            return youtube_url  # לא נמצא מזהה סרטון, תחזיר את המקורי
        video_id = qs["v"][0]
        return f"https://www.youtube.com/watch?v={video_id}"

    def get_playlist_video_urls(playlist_url):
        import subprocess, json
        result = subprocess.run([
            "yt-dlp", "--flat-playlist", "--dump-single-json", "--no-check-certificate", playlist_url
        ], capture_output=True, text=True)
        try:
            info = json.loads(result.stdout)
            if not isinstance(info, dict) or 'entries' not in info:
                print("yt-dlp did not return a dict:", result.stdout)
                return []
            entries = info['entries']
            return [entry['id'] for entry in entries if entry and 'id' in entry]
        except Exception as e:
            print("yt-dlp error:", e, result.stdout)
            return []
    
    def on_download(e):
        # פיצול הקלט לרשימת קישורים
        urls = url_input.value.strip().splitlines()
        urls = [u.strip() for u in urls if u.strip()]
        if not urls:
            show_snackbar(page, "אנא הדבק קישור או קישורים לסרטונים.", False)
            return

        value = format_choice.value
        if value is None:
            show_snackbar(page, "בחר פורמט להורדה.", False)
            return

        ext = "mp4" if value == "mp4" else "mp3"
        output_template = "%(title)s.%(ext)s"

        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"אתחול לוג: {datetime.now()}\n")

        for url in urls:
            # שליפת שם ותמונה
            title, thumbnail_url = fetch_title_and_thumbnail(url)
            if not title or title.strip() == "":
                title = "הורדה"

            # יצירת פסי התקדמות ופקדים לכל קישור
            progress_bar = ft.ProgressBar( color=PRIMARY, bgcolor=SECONDARY, value=0, bar_height=58)#width=460,
            progress_text = ft.Text("0%", size=16, color=PRIMARY, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER)#, width=250
            status_text = ft.Text("מוריד...", size=14, color=TEXT)
            cancel_event = threading.Event()
            download_id = str(uuid.uuid4())

            def cancel_download(ev, ce=cancel_event):
                ce.set()

            def open_folder(ev):
                folder = dest_dir.value
                try:
                    if os.name == 'nt':
                        os.startfile(folder)
                    elif os.name == 'posix':
                        subprocess.Popen(['xdg-open', folder])
                    else:
                        show_snackbar(page, "לא נתמך", False)
                except Exception:
                    show_snackbar(page, "לא ניתן לפתוח תיקיה", False)

            cancel_btn = ft.IconButton(ft.Icons.CANCEL, tooltip="ביטול", on_click=cancel_download)
            open_folder_btn = ft.IconButton(ft.Icons.FOLDER_OPEN, tooltip="פתח תיקיה", on_click=open_folder)

            row = ft.Container(
                content=ft.Column([
                    ft.Text(title, size=17, weight=ft.FontWeight.BOLD, color=PRIMARY),
                    ft.Row([
                        ft.Image(src=thumbnail_url or "assets/no_thumbnail.png", width=100, height=70, border_radius=8, fit=ft.ImageFit.COVER),
                        ft.Column([
                            ft.Stack([
                                progress_bar,
                                ft.Container(progress_text, alignment=ft.alignment.center)
                            ]),
                            status_text
                        ], spacing=8, expand=True),
                        ft.Column([cancel_btn, open_folder_btn], spacing=6, alignment=ft.MainAxisAlignment.END)
                    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ], spacing=10),
                bgcolor="#E3F2FD",
                border_radius=10,
                padding=12,
                margin=ft.Margin(0, 0, 0, 0),
                #width=680,
                alignment=ft.alignment.center_right
            )
            downloads_column.controls.insert(0, row)
            page.update()

            # רשימת נסיונות פורמט
            download_attempts = []
            if value == "mp4":
                download_attempts.append([
                    "yt-dlp",
                    "--no-check-certificate",
                    "-f", "best[ext=mp4][vcodec^=avc1]",
                    "-P", dest_dir.value,
                    "--ffmpeg-location", ffmpeg_actual,
                    "-o", output_template
                ])
                download_attempts.append([
                    "yt-dlp",
                    "--no-check-certificate",
                    "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4",
                    "--merge-output-format", "mp4",
                    "-P", dest_dir.value,
                    "--ffmpeg-location", ffmpeg_actual,
                    "-o", output_template
                ])
            else:
                download_attempts.append([
                    "yt-dlp", "--no-check-certificate",
                    "-x", "--audio-format", "mp3",
                    "--embed-thumbnail", "--add-metadata",
                    "-P", dest_dir.value,
                    "--ffmpeg-location", ffmpeg_actual,
                    "-o", output_template
                ])

            def do_download(actual_url, actual_title, actual_thumbnail, attempts, ce=cancel_event):
                for format_option in attempts:
                    success = run_download_with_cancel(
                        page, actual_url, format_option, dest_dir.value,
                        progress_bar, progress_text, status_text,
                        show_snackbar, None, download_id, ce,
                        actual_title, ext
                    )
                    if success:
                        break
                else:
                    status_text.value = "שגיאה: כל נסיונות ההורדה כשלו."
                    status_text.update()
                    show_snackbar(page, "שגיאה: כל נסיונות ההורדה כשלו.", False)

            # תמיכה בפלייליסטים עבור כל קישור
            if is_playlist(url):
                # פתח דיאלוג בחירה – לא מתחיל מיד להוריד
                show_playlist_dialog(url, download_attempts, do_download, title, thumbnail_url)
            else:
                threading.Thread(
                    target=do_download,
                    args=(url, title, thumbnail_url, download_attempts),
                    daemon=True
                ).start()

    top_row = ft.Row(
        [
            url_input,
            ft.IconButton(
                icon=ft.Icons.DOWNLOAD,
                on_click=on_download,     
                bgcolor=SECONDARY,        
                icon_color=PRIMARY,        
                tooltip="הורד"              
            ),
            open_log_btn,
        ],
        alignment=ft.MainAxisAlignment.START,
        spacing=10
    )


    # עמודת תמונות קישור (ימין)
    def open_youtube(e):
        webbrowser.open("https://www.youtube.com/channel/UCbCqf6LCwGIK4ylilMIVeMA")

    def open_chasiditube(e):
        webbrowser.open("https://chasiditube.com/")

    def open_progmedia(e):
        webbrowser.open("https://www.prog.co.il/forums/%D7%A4%D7%A8%D7%95%D7%92%D7%9E%D7%93%D7%99%D7%94.889/")         

    def open_github(e):
        webbrowser.open("https://video-tov.glat.ovh/")

    ICON_BOX_SIZE = 100  # גודל הריבוע, שנה כרצונך
    ICON_BG = "#F0F0F0"  # צבע רקע עדין
    ICON_RADIUS = 12     # עיגול פינות

    def icon_box(img, on_click, tooltip):
        return ft.Container(
            content=ft.Container(
                content=img,
                alignment=ft.alignment.center,
                width=ICON_BOX_SIZE,
                height=ICON_BOX_SIZE,
            ),
            width=ICON_BOX_SIZE,
            height=ICON_BOX_SIZE,
            bgcolor=ICON_BG,
            border_radius=ICON_RADIUS,
            alignment=ft.alignment.center,
            on_click=on_click,
            tooltip=tooltip,
            margin=ft.Margin(10, 0, 10, 0),
        )

    images_raw = ft.Column(
        [
            icon_box(
                ft.Image(
                    src="https://img.Icons8.com/ios-filled/100/000000/youtube-play.png",
                    width=48, height=48, fit=ft.ImageFit.CONTAIN
                ),
                open_youtube,
                "YouTube"
            ),
            icon_box(
                ft.Image(
                    src="https://video-tov.glat.ovh/assets/img/black-logo.png",
                    width=48, height=48, fit=ft.ImageFit.CONTAIN
                ),
                open_github,
                "וידאו טוב"
            ),
            icon_box(
                ft.Image(
                    src="https://chasiditube.com/wp-content/uploads/2020/01/%D7%90%D7%9C%D7%9E%D7%A0%D7%98%D7%95%D7%A8-%D7%94%D7%99%D7%93%D7%A8.png",
                    width=58, height=48, fit=ft.ImageFit.CONTAIN
                ),
                open_chasiditube,
                "חסידיוטיוב"
            ),
            icon_box(
                ft.Image(
                    src="https://s3.prog.co.il/data/avatars/m/117/117517.jpg?1734231571",
                    width=48, height=48, fit=ft.ImageFit.CONTAIN
                ),
                open_progmedia,
                "פרוגמדיה"
            ),
        ],
        spacing=8,
        alignment=ft.MainAxisAlignment.START
    )
    page.add(
        ft.Container(
            content=ft.Row(
                [
                    ft.Image(src="assets/icon.ico", width=60, height=60),
                    ft.Text("Easy download YouTube", size=32, weight=ft.FontWeight.BOLD, color=PRIMARY),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=10
            ),
            alignment=ft.alignment.center,
            padding=10
        ),
        # שורת קלט ה-URL וכפתורי הורדה ולוג
        top_row,
        # פקדי בחירת תיקייה ופורמט - בתוך Row עם spacing קטן וללא padding
        ft.Row(
            [
                choose_folder_btn,
                dest_dir_label,    # ← מציג את הנתיב הנוכחי
                format_choice,
            ],
            spacing=8,
            alignment=ft.MainAxisAlignment.START
        ),
        ft.Divider(height=1, color=SECONDARY),
        ft.Row(
            [
                ft.Container(downloads_column, expand=True, alignment=ft.alignment.top_left),
                ft.Container(images_raw, width=150, alignment=ft.alignment.top_right)
            ],
            expand=True,
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.START
        ),
    )
ft.app(target=main)

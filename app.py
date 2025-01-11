import openai, os, pymysql, hashlib, pytz, uuid, json, re, random, base64, mimetypes, io
import google.generativeai as genai
from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash, Response
from flask_mail import Mail, Message
from werkzeug.utils import secure_filename
from flask_socketio import SocketIO, emit
from datetime import datetime
from flask_cors import CORS
from collections import defaultdict
from apscheduler.schedulers.background import BackgroundScheduler
from PIL import Image

app = Flask(__name__)
socketio = SocketIO(app)
CORS(app)
scheduler = BackgroundScheduler()

ALLOWED_EXTENSIONS = {'pdf', 'txt' ,'doc', 'docx', 'txt', 'jpg', 'jpeg', 'png', 'gif', 'mp4', 'avi', 'mov', 'mkv', 'py', 'cpp', 'json'} 
IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png'}
VIDEO_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv'}

app.config.update(
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=465,
    MAIL_USE_TLS=False,
    MAIL_USE_SSL=True,
    MAIL_USERNAME=os.getenv('MAIL_USERNAME'),
    MAIL_PASSWORD=os.getenv('MAIL_PASSWORD'),
    SECRET_KEY=os.urandom(24),
)
mail = Mail(app)

# Configure Gemini AI
api_key = os.getenv("GOOGLE_API_KEY")
genai.configure(api_key=api_key)
generation_config = {
    "temperature": 0.5,
    "top_p": 0.95,
    "top_k": 64,
    "max_output_tokens": 8192,
    "response_mime_type": "text/plain",
}

model = genai.GenerativeModel(
    model_name="gemini-1.5-pro",
    generation_config=generation_config,
    system_instruction=(
        "You are here to empower students in their learning journey. "
        "Aim to be a reliable resource, guiding them through challenges "
        "in cybersecurity, networking, and programming."
    ),
)

# Configure OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")

# Database connection
def get_db_connection():
    return pymysql.connect(
        host='sql11.freesqldatabase.com',
        user='sql11738878',
        password='UeYdflLp4i',
        db='sql11738878',
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )

def is_admin():
    return session.get('role') == 'admin'

def schedule_tasks():
    scheduler = BackgroundScheduler()
    # Schedule the delete_unverified_users function to run every 7 days
    scheduler.add_job(delete_unverified_users, 'interval', weeks=1, id='delete_unverified_users')
    scheduler.start()
    # Shut down the scheduler when exiting the app
    import atexit
    atexit.register(lambda: scheduler.shutdown())

def delete_unverified_users():
    try:
        db = get_db_connection()
        with db.cursor() as cursor:
            cursor.execute("""DELETE FROM users WHERE verify = 0 AND created_at < NOW() - INTERVAL 7 DAY""")
            rows_deleted = cursor.rowcount
            db.commit()

        if rows_deleted > 0:
            print(f"Unverified users deleted successfully. Total deleted: {rows_deleted}.")
        else:
            print("No unverified users to delete.")
    except Exception as e:
        print(f"Error deleting unverified users: {e}")
    finally:
        db.close()

def verificatiom_code():
    code = random.randint(0, 999999)
    return code

def open_file(filename):
    with open(filename) as file:
        data = json.load(file)
    file.close()
    return data

def allowed_file(filename, type="all"):
    if "is_video_file" == type:
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in VIDEO_EXTENSIONS
    elif "is_image_file" == type:
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in IMAGE_EXTENSIONS
    else:
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def contains_bad_words(message):
    message = message.lower()
    bad_lists = open_file('bad_words.json')
    all_bad_words = bad_lists['swedish'] + bad_lists['arabic'] + bad_lists['english'] + bad_lists['spanish'] + bad_lists['french'] + bad_lists['german']+ bad_lists['italian']
    pattern = re.compile(r'\b(' + '|'.join(re.escape(word) for word in all_bad_words) + r')\b', re.IGNORECASE)
    return bool(pattern.search(message))

def get_local_time():
    return datetime.utcnow().replace(tzinfo=pytz.utc).astimezone(pytz.timezone('Europe/Stockholm')).strftime('%Y-%m-%d %H:%M')

def get_mime_type(filename):
    file = allowed_file(filename)
    return f"image/{file}"

#=====================================================
#======================= About =======================
#=====================================================
@app.route('/about')
def about():
    return render_template('about.html')

#=====================================================
#==================== Admin panel ====================
#=====================================================
@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    if not is_admin():
        flash('Access denied. Admins only.', 'error')
        return redirect(url_for('welcome'))

    db = get_db_connection()
    active_tab = request.args.get('tab', 'users')
    try:
        if request.method == 'POST':
            action = request.form.get('action')
            active_tab = request.args.get('tab', 'admin_panel-users')
            try:
                with db.cursor() as cursor:
                    #====================== USERS ======================
                    if action == 'edit_user':
                        user_id = request.form.get('user_id')
                        first_name = request.form.get('first_name')
                        last_name = request.form.get('last_name')
                        email = request.form.get('email')
                        phone_number = request.form.get('phone_number')
                        program_id = request.form.get('program')
                        start_year = request.form.get('start_year')
                        role = request.form.get('role')

                        cursor.execute("SELECT program_id FROM users WHERE id=%s", (user_id,))
                        old_program_id = cursor.fetchone()['program_id']

                        cursor.execute(
                            "UPDATE users SET first_name=%s, last_name=%s, email=%s, phone_number=%s, program_id=%s, start_year=%s, role=%s WHERE id=%s",
                            (first_name, last_name, email, phone_number, program_id, start_year, role, user_id)
                        )

                        # If program has changed, update folders
                        if old_program_id != int(program_id):
                            # Delete old folders
                            cursor.execute("DELETE FROM folders WHERE user_id = %s", (user_id,))
                            db.commit()

                            # Add new folders based on the new program
                            cursor.execute("""
                                SELECT c.id, c.name 
                                FROM courses c
                                JOIN program_course pc ON c.id = pc.course_id
                                WHERE pc.program_id = %s
                            """, (program_id,))
                            courses = cursor.fetchall()

                            for course in courses:
                                cursor.execute(
                                    "INSERT INTO folders (user_id, course_id, name) VALUES (%s, %s, %s)",
                                    (user_id, course['id'], course['name'])
                                )

                        db.commit()
                        return jsonify({"success": True})
                    
                    elif action == 'add_user':
                        email = request.form['email']
                        first_name = request.form['first_name']
                        last_name = request.form['last_name']
                        password = request.form['password']
                        phone_number = request.form['phone_number']
                        program_id = request.form['program']
                        start_year = request.form['start_year']
                        role = request.form['role']
                        profile_image = request.files.get('profile_image')
                        password_hash = hashlib.sha256(password.encode()).hexdigest()

                        profile_image_filename = None
                        if profile_image:
                            profile_image_filename = secure_filename(profile_image.filename)
                            profile_image.save(os.path.join('uploads', profile_image_filename))

                        if email and first_name and last_name and password_hash and phone_number and program_id and start_year and role:
                            cursor.execute(
                                "INSERT INTO users (email, first_name, last_name, password_hash, phone_number, profile_image, program_id, start_year, role) "
                                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                                (email, first_name, last_name, password_hash, phone_number, profile_image_filename, program_id, start_year, role)
                            )
                            user_id = cursor.lastrowid

                            # Add folders based on the user's program
                            cursor.execute("""
                                SELECT c.id, c.name 
                                FROM courses c
                                JOIN program_course pc ON c.id = pc.course_id
                                WHERE pc.program_id = %s
                            """, (program_id,))
                            courses = cursor.fetchall()

                            for course in courses:
                                cursor.execute(
                                    "INSERT INTO folders (user_id, course_id, name) VALUES (%s, %s, %s)",
                                    (user_id, course['id'], course['name'])
                                )
                            db.commit()
                            flash(f"New user {first_name} {last_name} added successfully!", "success")
                        else:
                            flash("Missing required fields for adding a user.", "error")

                    elif action == 'delete_user': 
                        user_id = request.form.get('user_id')
                        if not user_id:
                            return jsonify({"success": False, "error": "User ID is missing."}), 400
                        try:
                            cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
                            db.commit()
                            return jsonify({"success": True})
                        except Exception as e:
                            db.rollback()
                            return jsonify({"success": False, "error": str(e)}), 500

                    #===================== PROGRAM =====================
                    elif action == 'add_program':
                        name = request.form.get('add_program')
                        cursor.execute("INSERT INTO programs (name) VALUES (%s)", (name,))
                        db.commit()
                        flash("Program added successfully.", "success")
                        return redirect(url_for('admin_panel', tab='admin_panel-programs'))
                        
                    elif action == 'edit_program':
                        program_id = request.form.get('program_id')
                        name = request.form.get('name')
                        if not program_id or not name:
                            return jsonify({"success": False, "error": "Program ID and name are required."}), 400
                        try:
                            cursor.execute("UPDATE programs SET name = %s WHERE id = %s", (name, program_id))
                            db.commit()
                            return jsonify({"success": True})
                        except Exception as e:
                            db.rollback()
                            return jsonify({"success": False, "error": str(e)}), 500
                        
                    elif action == 'delete_program':
                        program_id = request.form.get('program_id')
                        if not program_id:
                            return jsonify({"success": False, "error": "Program ID is required."}), 400
                        try:
                            cursor.execute("DELETE FROM programs WHERE id = %s", (program_id,))
                            db.commit()
                            return jsonify({"success": True})
                        except Exception as e:
                            db.rollback()
                            return jsonify({"success": False, "error": str(e)}), 500

                    #===================== COURSE ======================
                    elif action == 'add_course':
                        name = request.form.get('name')
                        program_id = request.form.get('program_id')
                        cursor.execute(
                            "INSERT INTO courses (name, program_id) VALUES (%s, %s)",
                            (name, program_id)
                        )
                        db.commit()
                        flash("Course added successfully.", "success")
                        return redirect(url_for('admin_panel', tab='admin_panel-courses'))
                    
                    elif action == 'edit_course':
                        course_id = request.form.get('course_id')
                        course_name = request.form.get('name')
                        course_program_id = request.form.get('program_id')
                        if not all([course_id, course_name, course_program_id]):
                            return jsonify({"success": False, "error": "All fields are required."}), 400
                        try:
                            cursor.execute(
                                "UPDATE courses SET name=%s, program_id=%s WHERE id=%s",
                                (course_name, course_program_id, course_id)
                            )
                            db.commit()
                            return jsonify({"success": True})
                        except Exception as e:
                            db.rollback()
                            return jsonify({"success": False, "error": str(e)}), 500
                    
                    elif action == 'delete_course':
                        course_id = request.form.get('course_id')
                        if not course_id:
                            return jsonify({"success": False, "error": "Course ID is required."}), 400
                        try:
                            cursor.execute("DELETE FROM courses WHERE id = %s", (course_id,))
                            db.commit()
                            return jsonify({"success": True, "message": "Course deleted successfully."})
                        except Exception as e:
                            db.rollback()
                            return jsonify({"success": False, "error": str(e)}), 500

                    #====================== CHAT =======================
                    elif action == 'delete_chat':
                        chat_id = request.form.get('chat_id')
                        cursor.execute("DELETE FROM chat WHERE id = %s", (chat_id,))
                        db.commit()
                        flash("Chat deleted successfully.", "success")
                        return redirect(url_for('admin_panel', tab='admin_panel-chats'))

                    #====================== BOOK =======================
                    elif action == 'delete_book':
                        book_id = request.form.get('book_id')
                        cursor.execute("DELETE FROM books WHERE id = %s", (book_id,))
                        db.commit()
                        flash("Book deleted successfully.", "success")
                        return redirect(url_for('admin_panel', tab='admin_panel-books'))

                    #=================== MATERIAL REVIEW ===================
                    elif action == 'materials':
                        value = request.form.get('value')
                        material_id = request.form.get('material_id')
                        if not material_id:
                            flash("Material ID is required.", "error")
                            return redirect(url_for('admin_panel', tab='materials'))

                        try:
                            with db.cursor() as cursor:
                                if value == 'approve_material':
                                    cursor.execute("UPDATE materials SET status='approved' WHERE id=%s", (material_id,))
                                elif value == 'reject_material':
                                    cursor.execute("DELETE FROM materials WHERE id=%s", (material_id,))
                                else:
                                    flash("Invalid action for material.", "error")
                                    return redirect(url_for('admin_panel', tab='admin_panel-materials'))

                                db.commit()
                                flash(f"Material {value.replace('_', ' ')} successfully.", "success")
                                return redirect(url_for('admin_panel', tab='admin_panel-materials'))
                        except Exception as e:
                            db.rollback()
                            flash(f"Error processing material: {str(e)}", "danger")
            except Exception as e:
                db.rollback()
                flash(f"Error processing material: {str(e)}", "danger")
                return jsonify({"success": False, "error": str(e)}), 500
            return redirect(url_for('admin_panel', tab=active_tab))

        # Fetch data for rendering the admin panel
        with db.cursor() as cursor:
            cursor.execute("SELECT * FROM programs")
            programs = cursor.fetchall()
            cursor.execute("SELECT * FROM courses")
            courses = cursor.fetchall()
            cursor.execute("SELECT * FROM books")
            books = cursor.fetchall()
            cursor.execute("SELECT * FROM chat")
            chats = cursor.fetchall()
            cursor.execute("SELECT * FROM users")
            users = cursor.fetchall()
            cursor.execute("""SELECT materials.id, materials.title, materials.link, materials.type, users.first_name, users.last_name 
                FROM materials JOIN users ON materials.user_id = users.id WHERE materials.status='pending'""")
            materials = cursor.fetchall()

            start_years = [year for year in range(datetime.now().year, datetime.now().year - 10, -1)]

    finally:
        db.close()

    return render_template(
        'admin_panel.html',
        users=users,
        programs=programs,
        courses=courses,
        books=books,
        chats=chats,
        materials=materials,
        start_years=start_years,
        active_tab=active_tab
    )

#=====================================================
#=================== Book details ====================
#=====================================================
@app.route('/book/<int:book_id>')
def book_detail(book_id):
    db = get_db_connection()
    with db.cursor() as cursor:
        cursor.execute("SELECT * FROM books WHERE id = %s", (book_id,))
        book = cursor.fetchone()

        if not book:
            return "Book not found", 404

        cursor.execute("SELECT * FROM users WHERE id = %s", (book['user_id'],))
        seller = cursor.fetchone()
    db.close()
    return render_template('book_details.html', book=book, seller=seller)

#=====================================================
#==================== Books repo =====================
#=====================================================
@app.route('/book_main')
def book_main():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db_connection()
    with db.cursor() as cursor:
        cursor.execute("SELECT * FROM books")
        books = cursor.fetchall()
        cursor.execute("SELECT * FROM books WHERE user_id = %s", (session['user_id'],))
        user_books = cursor.fetchall()
    db.close()
    return render_template('books_repo.html', books=books, user_books=user_books)

@app.route('/delete_book/<int:book_id>', methods=['POST'])
def delete_book(book_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    db = get_db_connection()
    try:
        with db.cursor() as cursor:
            cursor.execute("DELETE FROM books WHERE id = %s AND user_id = %s", (book_id, session['user_id']))
            db.commit()
        flash('Book removed successfully!', 'success')
    except Exception as e:
        flash(f'Error removing book: {str(e)}', 'error')
    finally:
        db.close()

    return redirect(url_for('book_main'))

#=====================================================
#==================== Contact us =====================
#=====================================================
@app.route('/contact_us')
def contact_us():
    return render_template('contact_us.html')

#=====================================================
#================== Course folders ===================
#=====================================================
@app.route('/course/<course_id>')
def course_folders(course_id):
    db = get_db_connection()
    with db.cursor() as cursor:
        # Get the course name
        cursor.execute("SELECT name FROM courses WHERE id = %s", (course_id,))
        course = cursor.fetchone()
        
        if not course:
            return "Course not found", 404
        
        course_name = course['name']

        # Get folders with materials grouped by start_year
        cursor.execute("""
            SELECT DISTINCT folders.id AS folder_id, folders.name AS folder_name, 
                   users.first_name, users.last_name, users.start_year
            FROM folders
            JOIN users ON folders.user_id = users.id
            JOIN materials ON folders.id = materials.folder_id
            WHERE folders.course_id = %s
            ORDER BY users.start_year DESC
        """, (course_id,))
        folders = cursor.fetchall()

        # Group folders by start_year
        folders_by_year = {}
        for folder in folders:
            year = folder['start_year']
            if year not in folders_by_year:
                folders_by_year[year] = []
            folders_by_year[year].append(folder)

    db.close()
    return render_template('course_folders.html', course_name=course_name, folders_by_year=folders_by_year)

#=====================================================
#================= Course repository =================
#=====================================================
@app.route('/program/<int:program_id>')
def course_repository(program_id):
    year = request.args.get('year')
    query = request.args.get('query')

    db = get_db_connection()
    with db.cursor() as cursor:
        # Build query dynamically based on parameters
        if query:
            cursor.execute(
                """
                SELECT c.* 
                FROM courses c
                INNER JOIN program_course pc ON c.id = pc.course_id
                WHERE pc.program_id = %s AND c.name LIKE %s
                """,
                (program_id, f"%{query}%")
            )
        elif year:
            cursor.execute(
                """
                SELECT c.* 
                FROM courses c
                INNER JOIN program_course pc ON c.id = pc.course_id
                WHERE pc.program_id = %s AND c.year = %s
                """,
                (program_id, year)
            )
        else:
            cursor.execute(
                """
                SELECT c.* 
                FROM courses c
                INNER JOIN program_course pc ON c.id = pc.course_id
                WHERE pc.program_id = %s
                """,
                (program_id,)
            )
        
        courses = cursor.fetchall()

        # Fetch the program name
        cursor.execute("SELECT name FROM programs WHERE id=%s", (program_id,))
        program_name = cursor.fetchone().get('name') if cursor.rowcount > 0 else "Unknown Program"

    db.close()
    return render_template('course_repository.html', courses=courses, program_id=program_id, program_name=program_name)
    
#=====================================================
#======================= Folder ======================
#=====================================================
@app.route('/folder/<int:folder_id>', methods=['GET'])
def view_folder(folder_id):
    user_id = session.get('user_id')

    if not user_id:
        return redirect(url_for('login'))

    db = get_db_connection()
    with db.cursor() as cursor:
        cursor.execute("""
            SELECT f.id, f.name AS folder_name, f.user_id, u.first_name, u.last_name
            FROM folders f
            JOIN users u ON f.user_id = u.id
            WHERE f.id = %s
        """, (folder_id,))
        folder_details = cursor.fetchone()

        if not folder_details:
            return "Folder not found", 404

        cursor.execute("""
            SELECT id, title, link, type, language, status
            FROM materials
            WHERE folder_id = %s AND status = 'approved'
        """, (folder_id,))
        materials = cursor.fetchall()

    db.close()

    is_owner = user_id == folder_details['user_id']

    return render_template(
        "folder.html",
        folder=folder_details,
        materials=materials,
        is_owner=is_owner
    )

@app.route('/upload_material', methods=['POST'])
def upload_material():
    folder_id = request.form.get('folder_id')
    title = request.form.get('title')
    material_type = request.form.get('type')
    language = request.form.get('language')
    file = request.files.get('file')
    link = request.form.get('link')
    delete_materials = request.form.get('delete_materials')
    material_state_for_del = request.form.get('material_delete_true') == 'True'
    db = get_db_connection()
    message, status = "", ""
    folder, materials = None, []

    try:
        with db.cursor() as cursor:
            # Retrieve folder
            cursor.execute("SELECT * FROM folders WHERE id = %s", (folder_id,))
            folder = cursor.fetchone()

            if not folder:
                raise ValueError("Folder not found.")

            # Validate ownership
            if folder['user_id'] != session.get('user_id'):
                raise PermissionError("You do not have permission to modify this folder.")

            if delete_materials and material_state_for_del:
                # Delete the material
                cursor.execute(
                    "DELETE FROM materials WHERE id = %s AND user_id = %s",
                    (delete_materials, session['user_id'])
                )
                db.commit()
                message = "Material deleted successfully."
                status = "success"
            elif material_type == 'youtube' and link:
                # Insert YouTube material
                cursor.execute(
                    """
                    INSERT INTO materials (title, link, type, language, folder_id, status, user_id)
                    VALUES (%s, %s, %s, %s, %s, 'pending', %s)
                    """,
                    (title, link, material_type, language, folder_id, session['user_id'])
                )
            elif material_type == 'note' and file:
                # Handle file uploads
                file_name = secure_filename(file.filename)
                file_data = file.read()
                file_extension = file_name.rsplit('.', 1)[-1].lower()

                if not allowed_file(file_name):
                    raise ValueError(f"Invalid file type: {file_extension}")

                cursor.execute(
                    """
                    INSERT INTO materials (title, file_data, file_extension, type, folder_id, status, user_id)
                    VALUES (%s, %s, %s, %s, %s, 'pending', %s)
                    """,
                    (title, file_data, file_extension, material_type, folder_id, session['user_id'])
                )
            else:
                raise ValueError("Invalid material type or missing required fields.")

            db.commit()
            if not delete_materials:
                message = "Material uploaded successfully. Awaiting approval."
                status = "success"

        # Fetch updated materials
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT id, title, link, type, language, status FROM materials WHERE folder_id = %s",
                (folder_id,)
            )
            materials = cursor.fetchall()

    except Exception as e:
        db.rollback()
        message = f"An error occurred: {str(e)}"
        status = "error"
    finally:
        db.close()

    if not folder:
        return render_template("404.html", message=message, status=status)

    is_owner = session.get('user_id') == folder['user_id']
    return render_template(
        "folder.html",
        folder=folder,
        materials=materials,
        is_owner=is_owner,
        message=message,
        status=status
    )

#=====================================================
#======================= Login =======================
#=====================================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email, password = request.form['username'], request.form['password']
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        db = get_db_connection()
        with db.cursor() as cursor:
            cursor.execute("""SELECT id, first_name, last_name, role, generated_code, verify FROM users WHERE email = %s AND password_hash = %s""", (email, password_hash))            
            user = cursor.fetchone()  
        db.close()
        
        if not user:
            return render_template("login.html", error="Invalid email or password.")
        
        session['temp_user_id'] = user['id']
        session['first_name'] = user['first_name']
        session['last_name'] = user['last_name']
        session['role'] = user['role']

        if user['verify'] == 1:
            session['user_id'] = user['id']
            if user['role'] == 'admin':
                return redirect(url_for('admin_panel'))
            else:
                return redirect(url_for('main'))
        else:
            return render_template("login.html", show_code_popup=True)
    return render_template("login.html")

@app.route('/verify_code', methods=['POST'])
def verify_code():
    user_id = session.get('temp_user_id')
    if not user_id:
        flash("Session expired. Please log in again.", "error")
        return redirect(url_for('login'))

    entered_code = request.form.get('verification_code')
    db = get_db_connection()
    with db.cursor() as cursor:
        cursor.execute("""SELECT generated_code, role FROM users WHERE id = %s""", (user_id,))
        result = cursor.fetchone() 

    if not result:
        flash("User not found.", "error")
        return redirect(url_for('login'))

    correct_code = result['generated_code']
    user_role = result['role']

    if not entered_code or correct_code is None:
        return render_template("login.html", show_code_popup=True, error="Verification code cannot be empty. Please try again.")

    try:
        if int(entered_code) == int(correct_code):
            with db.cursor() as cursor:
                cursor.execute("""UPDATE users SET verify = 1 WHERE id = %s """, (user_id,))
            db.commit()
            session['user_id'] = user_id
            session.pop('temp_user_id', None)
            db.close()
            if user_role == 'admin':
                return redirect(url_for('admin_panel'))
            else:
                return redirect(url_for('main'))
        else:
            return render_template(
                "login.html",
                show_code_popup=True,
                error="Incorrect verification code."
            )
    except ValueError:
        return render_template(
            "login.html",
            show_code_popup=True,
            error="Verification code must be a valid number."
        )

#=====================================================
#======================= Logout ======================
#=====================================================
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('welcome'))

#=====================================================
#======================= Main ========================
#=====================================================
@app.route('/main')
def main():
    return render_template("main.html")

@app.route("/search_users", methods=["GET"])
def search_users():
    query = request.args.get("q", "").strip()
    if not query:
        flash("No search query provided.")
        return redirect(url_for("welcome"))
    
    db = get_db_connection()
    with db.cursor() as cursor:
        cursor.execute("""
            SELECT id, first_name, last_name
            FROM users
            WHERE CONCAT_WS(' ', first_name, last_name) LIKE %s
        """, (f"%{query}%",))
        results = cursor.fetchall()
    db.close()

    if not results:
        flash("No users found.")
        return redirect(url_for("main"))

    if len(results) == 1:
        user_id = results[0]["id"]
        return redirect(url_for("public_profile", user_id=user_id))

    first_user_id = results[0]["id"]
    flash(f"Multiple users found. Showing the first match: {results[0]['first_name']} {results[0]['last_name']}")
    return redirect(url_for("public_profile", user_id=first_user_id))

@app.route("/autocomplete_users", methods=["GET"])
def autocomplete_users():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify([])  # No query -> return empty list

    db = get_db_connection()
    with db.cursor() as cursor:
        cursor.execute("""
            SELECT first_name, last_name
            FROM users
            WHERE first_name LIKE %s
               OR last_name LIKE %s
            LIMIT 10
        """, (f"%{query}%", f"%{query}%"))
        rows = cursor.fetchall()
    db.close()
    
    suggestions = []
    for row in rows:
        suggestions.append({
            "first_name": row["first_name"],
            "last_name": row["last_name"]
        })

    return jsonify(suggestions)

#=====================================================
#====================== Profile ======================
#=====================================================
@app.route('/profile', methods=['GET'])
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    db = get_db_connection()
    with db.cursor() as cursor:
        # Fetch user details
        cursor.execute("""
            SELECT u.id, u.email, u.first_name, u.last_name, u.phone_number,
                   u.profile_image, u.bio, u.start_year, p.name as program_name
            FROM users u
            LEFT JOIN programs p ON u.program_id = p.id
            WHERE u.id = %s
        """, (session['user_id'],))
        user = cursor.fetchone()

        if not user:
            return "User not found", 404

        # Convert profile_image to Base64 if it exists
        if user['profile_image']:
            mime_type = "image/jpeg"
            user['profile_image'] = f"data:{mime_type};base64," + base64.b64encode(user['profile_image']).decode('utf-8')

        cursor.execute("""SELECT f.id, f.name FROM folders f WHERE f.user_id = %s""", (session['user_id'],))
        folders = cursor.fetchall()
    db.close()

    return render_template("profile.html", user=user, folders=folders)
    
#=====================================================
#================= Program repository ================
#=====================================================
@app.route('/programs')
def programs():
    db = get_db_connection()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM programs")
    programs = cursor.fetchall()
    cursor.close()
    db.close()
    return render_template('program_repository.html', programs=programs)

#=====================================================
#=================== Public chat =====================
#=====================================================
@app.route('/public_chat')
def public_chat():
    username = f"{session.get('first_name', 'Guest')} {session.get('last_name', '')}".strip()  # Get full name
    db = get_db_connection()
    with db.cursor() as cursor:
        cursor.execute("SELECT username, message, timestamp FROM chat ORDER BY timestamp ASC")
        chat_history = cursor.fetchall()
    db.close()
    return render_template('public_chat.html', chat_history=chat_history, username=username)

@socketio.on('send_message')
def handle_message(data):
    username = f"{session.get('first_name', 'Guest')} {session.get('last_name', '')}".strip()
    message = data['message']

    # Check for bad words
    if contains_bad_words(message):
        emit('message_rejected', {'reason': 'Your message contains inappropriate language.'}, room=request.sid)
        return

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    # Insert the message into the database
    db = get_db_connection()
    with db.cursor() as cursor:
        cursor.execute("INSERT INTO chat (username, message, timestamp) VALUES (%s, %s, %s)",
                       (username, message, timestamp))
        db.commit()
    db.close()

    # Emit the message to all clients
    emit('receive_message', {'username': username, 'message': message, 'timestamp': timestamp}, broadcast=True)
    
#=====================================================
#================== Public profile ===================
#=====================================================
@app.route("/public_profile/<int:user_id>", methods=["GET"])
def public_profile(user_id):
    db = get_db_connection()
    with db.cursor() as cursor:
        # Fetch user details
        cursor.execute("""
            SELECT first_name, last_name, profile_image, bio, program_id, start_year
            FROM users
            WHERE id = %s
        """, (user_id,))
        user = cursor.fetchone()

        if not user:
            return "User not found", 404

        # Convert profile_image to Base64 if it exists
        if user["profile_image"]:
            mime_type = get_mime_type('profile.png')  # Dynamically determine MIME type
            user["profile_image"] = f"data:{mime_type};base64,{base64.b64encode(user['profile_image']).decode('utf-8')}"

        # Fetch program name
        cursor.execute("SELECT name FROM programs WHERE id = %s", (user["program_id"],))
        program_row = cursor.fetchone()
        user["program_name"] = program_row["name"] if program_row else None

        # Fetch folders
        cursor.execute("SELECT id, name FROM folders WHERE user_id = %s", (user_id,))
        folders = cursor.fetchall()

    db.close()

    return render_template("public_profile.html", user=user, folders=folders)

@app.route('/download/<int:material_id>')
def download_file(material_id):
    db = get_db_connection()
    try:
        with db.cursor() as cursor:
            cursor.execute("SELECT title, file_data, file_extension FROM materials WHERE id = %s", (material_id,))
            material = cursor.fetchone()

            if material and material['file_data']:
                # Map file extensions to MIME types
                extension_to_mime = open_file('extension_to_mime.json')
                # Get the MIME type or default to binary
                content_type = extension_to_mime.get(material['file_extension'], 'application/octet-stream')

                return Response(
                    material['file_data'],
                    mimetype=content_type,
                    headers={"Content-Disposition": f"attachment; filename={material['title']}.{material['file_extension']}"}
                )
            else:
                return "File not found", 404
    finally:
        db.close()
#=====================================================
#==================== AI Chatbot =====================
#=====================================================
#This for the Gemini chatbot
'''
@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.json.get("message")

    # Ensure chat session is started here
    chat_session = model.start_chat()

    try:
        # Send user input to the chat session and get the response
        response = chat_session.send_message(user_input)

        # Extract the message from the response
        if hasattr(response, 'candidates') and len(response.candidates) > 0:
            model_response = response.candidates[0].content.parts[0].text if hasattr(response.candidates[0].content, 'parts') and len(response.candidates[0].content.parts) > 0 else "No response available."
        else:
            model_response = "No candidates available."

        # Format the response for code snippets
        if '```' in model_response:  # Check if response includes code block
            code_part = model_response.split('```')[1]  # Extract the code
            explanation_part = model_response.split('```')[2]  # Extract explanation
            formatted_response = f"""
            <div>
                <pre><code>{code_part.strip()}</code></pre>
                <p>{explanation_part.strip()}</p>
            </div>
            """
            model_response = formatted_response  # Update the response with HTML formatting

    except Exception as e:
        print(f"Error in chat response: {e}")
        return jsonify({"response": "Sorry, I couldn't process your request."}), 500

    # Return the formatted response
    return jsonify({"response": model_response})
'''
#=====================================================
#This for the OpenAI chatbot
@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.json.get("message")
    if not user_input:
        return jsonify({"response": "No input provided."}), 400

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",  # Specify the model
            messages=[
                {"role": "system", "content": "You are an AI assistant specialized in helping students with computer engineering, cybersecurity, networking, and general topics. Provide detailed and helpful explanations."},
                {"role": "user", "content": user_input}
            ]
        )
        assistant_reply = response['choices'][0]['message']['content']
        return jsonify({"response": assistant_reply})
    except Exception as e:
        return jsonify({"response": f"An error occurred: {str(e)}"}), 500

#=====================================================
#===================== Register ======================
#=====================================================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            form = request.form
            first_name, last_name = form['first_name'], form['last_name']
            email, password = form['email'], form['password']
            phone_number, program_id, start_year = form['phone_number'], form['program'], form['start_year']
            if not (email.endswith("@student.hv.se") or email.endswith("@hv.se")):
                return jsonify({"error": "You must use a university email."}), 400

            password_hash = hashlib.sha256(password.encode()).hexdigest()

            # Initialize profile_image_data
            profile_image_data = None

            if 'profile_picture' in request.files:
                profile_picture = request.files['profile_picture']
                if profile_picture and allowed_file(profile_picture.filename, "is_image_file"):
                    # Resize and optimize the image
                    img = Image.open(profile_picture)
                    img = img.convert("RGB") 
                    img.thumbnail((300, 300)) 
                    buffer = io.BytesIO()
                    img.save(buffer, format="JPEG", optimize=True, quality=85)
                    profile_image_data = buffer.getvalue()
                else:
                    return jsonify({"error": "Invalid file type."}), 400

            db = get_db_connection()
            with db.cursor() as cursor:
                cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
                if cursor.fetchone():
                    return jsonify({"error": "User already registered!"}), 400

                generated_code = verificatiom_code()

                cursor.execute(
                    """INSERT INTO users 
                    (email, first_name, last_name, password_hash, phone_number, profile_image, program_id, start_year, role, generated_code)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'user', %s)""",
                    (email, first_name, last_name, password_hash, phone_number, profile_image_data, program_id, start_year, generated_code)
                )
                user_id = cursor.lastrowid  
                db.commit()

                cursor.execute("""
                    SELECT c.id, c.name 
                    FROM courses c
                    JOIN program_course pc ON c.id = pc.course_id
                    WHERE pc.program_id = %s
                """, (program_id,))
                courses = cursor.fetchall()

                for course in courses:
                    cursor.execute(
                        """INSERT INTO folders (user_id, course_id, name) 
                        VALUES (%s, %s, %s)""",
                        (user_id, course['id'], course['name'])
                    )
                db.commit()

                # Send a welcome email
                msg = Message(
                    "Welcome to WestLink",
                    sender=app.config['MAIL_USERNAME'],
                    recipients=[email]
                )
                msg.body = f"Hello {first_name},\n\nThank you for registering with WestLink!\nHere is your verification code: {generated_code}.\n\nBest regards,\nWestLink Team."
                mail.send(msg)

            db.close()
            return jsonify({"message": "Registration successful! Check your email for verification code."}), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return render_template("register.html")


@app.route('/get_programs', methods=['GET'])
def get_programs():
    try:
        db = get_db_connection()
        with db.cursor() as cursor:
            cursor.execute("SELECT id, name FROM programs")
            programs = cursor.fetchall()
            return jsonify(programs), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/user_profile_image/<int:user_id>')
def user_profile_image(user_id):
    db = get_db_connection()
    try:
        with db.cursor() as cursor:
            cursor.execute("""
                SELECT profile_image FROM users WHERE id = %s
            """, (user_id,))
            result = cursor.fetchone()

        if result and result['profile_image']:
            return Response(result['profile_image'], mimetype='image/jpeg')
        else:
            return redirect(url_for('static', filename='images/default_profile.png'))
    finally:
        db.close()
    
#=====================================================
#===================== Settings ======================
#=====================================================
@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if 'user_id' not in session:
        return redirect(url_for('login'))  # Ensure user is logged in

    db = get_db_connection()

    if request.method == 'GET':
        try:
            with db.cursor() as cursor:
                # Fetch user details
                cursor.execute("""
                    SELECT first_name, last_name, email, phone_number, profile_image, bio, program_id, start_year
                    FROM users
                    WHERE id = %s
                """, (session['user_id'],))
                user = cursor.fetchone()

                if user and user['profile_image']:
                    mime_type = "image/jpeg"
                    user['profile_image'] = f"data:{mime_type};base64," + base64.b64encode(user['profile_image']).decode('utf-8')

                # Fetch user folders
                cursor.execute("""
                    SELECT id, name
                    FROM folders
                    WHERE user_id = %s
                """, (session['user_id'],))
                folders = cursor.fetchall()

                # Fetch all programs
                cursor.execute("SELECT id, name FROM programs")
                programs = cursor.fetchall()

                # Generate the start years list
                start_years = [year for year in range(datetime.now().year, datetime.now().year - 10, -1)]

            return render_template("settings.html", user=user, folders=folders, programs=programs, start_years=start_years)
        except Exception as e:
            print(f"Error in GET /settings: {e}")
            return jsonify({"error": "Failed to load settings page."}), 500
        finally:
            db.close()

    if request.method == 'POST':
        try:
            # Fetch submitted data
            first_name = request.form['first_name']
            last_name = request.form['last_name']
            phone_number = request.form['phone_number']
            bio = request.form.get('bio', '')
            password = request.form.get('password', '')
            program_id = int(request.form.get('program'))  # Convert to int for comparison
            start_year = request.form.get('start_year')

            profile_image_data = None
            if 'profile_picture' in request.files:
                profile_picture = request.files['profile_picture']
                if profile_picture and allowed_file(profile_picture.filename, "is_image_file"):
                    image = Image.open(profile_picture)
                    if image.mode == 'RGBA':
                        image = image.convert('RGB')
                    image = image.resize((300, 300))  # Resize to 300x300
                    byte_io = io.BytesIO()
                    image.save(byte_io, format='JPEG')
                    profile_image_data = byte_io.getvalue()
                else:
                    return jsonify({"error": "Invalid file type."}), 400

            with db.cursor() as cursor:
                # Fetch the current program ID to check if it changes
                cursor.execute("SELECT program_id FROM users WHERE id = %s", (session['user_id'],))
                current_program_id = cursor.fetchone()['program_id']

                # Update user info
                if password.strip():
                    password_hash = hashlib.sha256(password.encode()).hexdigest()
                    cursor.execute("""
                        UPDATE users
                        SET first_name = %s,
                            last_name = %s,
                            phone_number = %s,
                            password_hash = %s,
                            bio = %s,
                            profile_image = COALESCE(%s, profile_image),
                            program_id = %s,
                            start_year = %s
                        WHERE id = %s
                    """, (
                        first_name, last_name, phone_number, password_hash, bio, profile_image_data, program_id, start_year, session['user_id']
                    ))
                else:
                    cursor.execute("""
                        UPDATE users
                        SET first_name = %s,
                            last_name = %s,
                            phone_number = %s,
                            bio = %s,
                            profile_image = COALESCE(%s, profile_image),
                            program_id = %s,
                            start_year = %s
                        WHERE id = %s
                    """, (
                        first_name, last_name, phone_number, bio, profile_image_data, program_id, start_year, session['user_id']
                    ))

                # If the program has changed, update the folders
                if current_program_id != program_id:
                    cursor.execute("DELETE FROM folders WHERE user_id = %s", (session['user_id'],))
                    cursor.execute("""
                        SELECT c.id, c.name
                        FROM courses c
                        JOIN program_course pc ON c.id = pc.course_id
                        WHERE pc.program_id = %s
                    """, (program_id,))
                    courses = cursor.fetchall()
                    for course in courses:
                        cursor.execute(
                            "INSERT INTO folders (user_id, course_id, name) VALUES (%s, %s, %s)",
                            (session['user_id'], course['id'], course['name'])
                        )
                db.commit()
            
            return jsonify({"message": "Settings updated successfully!"})  
        except Exception as e:
            print(f"Error in POST /settings: {e}")
            return jsonify({"error": "Failed to update settings."}), 500
        finally:
            db.close()
            
@app.route('/remove_profile_picture', methods=['POST'])
def remove_profile_picture():
    if 'user_id' not in session:
        return jsonify({"message": "Unauthorized"}), 401

    db = get_db_connection()
    try:
        with db.cursor() as cursor:
            cursor.execute("""
                UPDATE users SET profile_image = NULL WHERE id = %s
            """, (session['user_id'],))
            db.commit()

        return jsonify({"message": "Profile picture removed successfully!"})
    finally:
        db.close()

#=====================================================
#==================== Upload book ====================
#=====================================================
@app.route('/upload', methods=['GET', 'POST'])
def upload_book():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        title = request.form['title']
        isbn = request.form['isbn']
        author = request.form['author']
        description = request.form['description']
        price = request.form['price']
        image_url = request.form['image_url']
        user_id = session['user_id']
        db = get_db_connection()
        try:
            with db.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO books (title, isbn, author, description, price, image_url, user_id) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (title, isbn, author, description, price, image_url, user_id)
                )
                db.commit()
            flash('Book added successfully!', 'success')
            return redirect(url_for('book_main'))
        
        except Exception as e:
            flash('Failed to add the book. Please try again.', 'error')
            return redirect(url_for('upload_book'))
        
        finally:
            db.close()
    return render_template('upload_book.html')
#=====================================================
#====================== Welcome ======================
#=====================================================
@app.route('/')
def welcome():
    return render_template("welcome.html")

#=====================================================
#=====================================================
#=====================================================

if __name__ == '__main__':
    # Start the scheduler
    schedule_tasks()
    socketio.run(app, host='0.0.0.0', port=8080, debug=True)

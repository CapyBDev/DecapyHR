from flask import Flask, render_template, request, redirect, session, url_for, flash
import os
from werkzeug.utils import secure_filename
import psycopg2
from flask_mail import Mail, Message
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from functools import wraps

load_dotenv()

app = Flask(__name__)
app.secret_key = "secret123"

UPLOAD_FOLDER = "static/uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# app.config.update(
#     MAIL_SERVER=os.getenv("MAIL_SERVER"),
#     MAIL_PORT=int(os.getenv("MAIL_PORT")),
#     MAIL_USE_TLS=True,
#     MAIL_USERNAME=os.getenv("MAIL_USERNAME"),
#     MAIL_PASSWORD=os.getenv("MAIL_PASSWORD")
# )
# mail = Mail(app)

scheduler = BackgroundScheduler()

if not scheduler.running:
    scheduler.start()

LEAVE_UPLOAD_FOLDER = os.path.join("static", "uploads", "leave_docs")
os.makedirs(LEAVE_UPLOAD_FOLDER, exist_ok=True)

ALLOWED_LEAVE_EXTENSIONS = {"png", "jpg", "jpeg", "pdf"}
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif"}

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/")
        return f(*args, **kwargs)
    return decorated

def allowed_leave_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_LEAVE_EXTENSIONS
    )
# ================= DATABASE =================
def get_db():
    db_url = os.environ.get("DATABASE_URL")
    return psycopg2.connect(db_url, sslmode='require')
DB_PATH = os.path.join(os.path.dirname(__file__), "database.db")
# ---------------------- Position Hierarchy ----------------------
POSITION_HIERARCHY = {
    "Staff": "Supervisor",
    "Supervisor": "Manager",
    "Manager": "General Manager",
    "General Manager": "CEO",
    "CEO": None  # top of chain
}

def calculate_working_days(start_date, end_date):
    """Return number of working days between start & end,
    excluding Sat/Sun & public holidays."""

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT date FROM holidays")
    holiday_rows = c.fetchall()
    holidays = {h["date"] for h in holiday_rows}
    conn.close()

    if isinstance(start_date, str):
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
    else:
        start = start_date

    if isinstance(end_date, str):
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
    else:
        end = end_date

    count = 0
    current = start

    while current <= end:
        if current.weekday() < 5:
            if current.isoformat() not in holidays:
                count += 1
        current += timedelta(days=1)

    return count

def get_used_leave_days(user_id, year=None):
    conn = get_db()
    c = conn.cursor()

    sql = """
        SELECT COALESCE(SUM(total_days), 0) AS total
        FROM leave_applications
        WHERE user_id = %s
          AND status = 'Approved'
          AND leave_type != 'MC'
    """
    params = [user_id]

    if year:
        sql += " AND EXTRACT(YEAR FROM DATE(start_date)) = %s"
        params.append(int(year))

    c.execute(sql, params)

    row = c.fetchone()
    used = row["total"] if row and row["total"] is not None else 0

    conn.close()

    return used

def get_next_position(position):
    """Return next higher position for approval or checking chain."""
    return POSITION_HIERARCHY.get(position, None)

def allowed_photo(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def normalize_date(value):
    from datetime import datetime, date

    if value is None:
        return None

    if isinstance(value, str):
        return datetime.strptime(value, "%Y-%m-%d").date()

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    return value

# ================= LOGIN =================
@app.route("/", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        if email == "admin@test.com":
            session["user_id"] = 1
            session["role"] = "admin"
            session["name"] = "Admin"
            return redirect("/admin/dashboard")

        elif email == "user@test.com":
            session["user_id"] = 2
            session["role"] = "user"
            session["name"] = "User"
            return redirect("/users")

    return render_template("login.html")

# ================= USER DASHBOARD =================
@app.route("/users")
def user_dashboard():
    if "user_id" not in session:
        return redirect("/")

    conn = get_db()
    cur = conn.cursor()

    user_id = session["user_id"]

    # ===== USER INFO =====
    cur.execute("""
        SELECT full_name, email, phone, address, position
        FROM users
        WHERE id = %s
    """, (user_id,))
    u = cur.fetchone()

    user = {
        "name": u[0],
        "email": u[1],
        "phone": u[2],
        "address": u[3],
        "position": u[4],
        "id": user_id,
        "department": "N/A",
        "duration": "1 year"
    }

    # ===== CLAIMS =====
    cur.execute("""
        SELECT id, amount, category, status, created_at
        FROM claims
        WHERE user_id = %s
        ORDER BY id DESC
    """, (user_id,))
    claims = cur.fetchall()

    # ===== CLAIM STATS =====
    total = len(claims)
    pending = len([c for c in claims if c[3] == "Pending"])
    approved = len([c for c in claims if c[3] == "Approved"])
    rejected = len([c for c in claims if c[3] == "Rejected"])

    # ===== NOTICE =====
    cur.execute("""
        SELECT content FROM notices
        ORDER BY created_at DESC LIMIT 1
    """)
    notice = cur.fetchone()

    # ===== POLICY =====
    cur.execute("""
        SELECT filename FROM policies
        ORDER BY id DESC LIMIT 1
    """)
    policy = cur.fetchone()

    conn.close()

    return render_template("user_dashboard.html",
        user=user,
        claims=claims,
        total=total,
        pending=pending,
        approved=approved,
        rejected=rejected,
        notice=notice,
        policy=policy,
        attendance="0/28",
        leaves="0/440",
        awards="0"
    )

@app.route("/tasks", methods=["GET","POST"])
def tasks():
    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":
        cur.execute("""
            INSERT INTO tasks (user_id, title, start_time, end_time, color)
            VALUES (%s,%s,%s,%s,%s)
        """, (
            session["user_id"],
            request.form["title"],
            request.form["date"],
            request.form["date"],
            request.form["color"]
        ))
        conn.commit()

        # 🔔 add notification
        cur.execute("""
            INSERT INTO notifications (user_id, message)
            VALUES (%s,%s)
        """, (
            session["user_id"],
            f"New task added: {request.form['title']}"
        ))
        conn.commit()

    cur.execute("""
        SELECT id, title, date, color
        FROM tasks
        WHERE user_id=%s
    """, (session["user_id"],))

    tasks = cur.fetchall()
    conn.close()

    return {"tasks": [
        {"id": t[0], "title": t[1], "date": str(t[2]), "color": t[3]}
        for t in tasks
    ]}

@app.route("/tasks/delete/<int:id>")
def delete_task(id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("DELETE FROM tasks WHERE id=%s", (id,))
    conn.commit()
    conn.close()

    return redirect("/users")
# ================= DASHBOARD =================
@app.route("/admin/dashboard")
def admin_dashboard():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM users")
    total_employees = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM departments")
    total_departments = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM leaves WHERE status='Pending'")
    pending_leaves = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM claims")
    total_claims = cur.fetchone()[0]
    
    # NEW EMPLOYEES (example: last 30 days)
    cur.execute("SELECT COUNT(*) FROM users")
    new_employees = cur.fetchone()[0]

    # SIMPLE HAPPINESS RATE (dummy logic)
    happiness_rate = 82

    # WORKING FORMAT (example static for now)
    work_format = [50, 20, 30]

    # PROJECT DATA
    project_data = [80,100,150,200,140,220,300]

    # ATTENDANCE DATA
    attendance_data = {
        "ontime": [30,20,15,25,28,35],
        "late": [20,15,10,20,18,25],
        "absent": [10,8,5,15,12,18]
    }

    # NOTICE
    cur.execute("SELECT content, file FROM notices ORDER BY created_at DESC LIMIT 1")
    notice = cur.fetchone()

    # CHART (example)
    trend_labels = ["Jan","Feb","Mar","Apr"]
    trend_data = [5,10,7,12]

    conn.close()

    return render_template("admin_dashboard.html",
        total_employees=total_employees,
        pending_leaves=pending_leaves,
        total_departments=total_departments,
        total_claims=total_claims,
        notice=notice,
        trend_labels=trend_labels,
        trend_data=trend_data,

        new_employees=new_employees,
        happiness_rate=happiness_rate,
        work_format=work_format,
        project_data=project_data,
        attendance_data=attendance_data
    )

# ================= EMPLOYEES =================
@app.route("/admin/users")
def admin_users():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT 
            u.id,
            u.full_name,
            u.email,
            u.phone,
            u.address,
            u.position,
            u.dept_id,
            u.entitlement,
            u.availability,
            d.name AS department_name
        FROM users u
        LEFT JOIN departments d ON u.dept_id = d.id
    """)

    columns = [col[0] for col in cur.description]
    users = [dict(zip(columns, row)) for row in cur.fetchall()]

    cur.execute("SELECT id, name FROM departments")
    dept_columns = [col[0] for col in cur.description]
    departments = [dict(zip(dept_columns, row)) for row in cur.fetchall()]

    conn.close()

    return render_template("manage_staff.html",
                           users=users,
                           departments=departments)


# ===== CREATE USER (FIXED) =====
@app.route("/admin/users/create", methods=["POST"])
def create_user():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO users 
        (full_name, email, phone, address, position, dept_id, entitlement, availability, username, password, role)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        request.form["full_name"],
        request.form.get("email"),
        request.form.get("phone"),
        request.form.get("address"),
        request.form.get("position"),
        request.form.get("dept_id"),
        request.form.get("entitlement", 14),
        "Available",
        request.form.get("username"),
        request.form.get("password"),
        request.form.get("role", "user")
    ))

    conn.commit()
    conn.close()

    return redirect("/admin/users")

# ===== UPDATE PROFILE (FIXED) =====
@app.route("/user/update-profile", methods=["POST"])
def update_profile():
    if "user_id" not in session:
        return redirect("/")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET full_name=%s, email=%s, password=%s
        WHERE id=%s
    """, (
        request.form["name"],
        request.form["email"],
        request.form["password"],
        session["user_id"]
    ))

    conn.commit()
    conn.close()

    return redirect("/users")

@app.route("/user/upload-image", methods=["POST"])
def upload_image():
    file = request.files.get("file")

    if file and file.filename != "":
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users SET profile_image=%s WHERE id=%s
    """, (filename, session["user_id"]))

    conn.commit()
    conn.close()

    return redirect("/users")

# ===== UPDATE USER (FIXED) =====
@app.route("/admin/users/update/<int:id>", methods=["POST"])
def update_user(id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET 
            full_name=%s,
            email=%s,
            phone=%s,
            address=%s,
            position=%s,
            dept_id=%s,
            entitlement=%s,
            availability=%s
        WHERE id=%s
    """, (
        request.form["full_name"],
        request.form["email"],
        request.form["phone"],
        request.form["address"],
        request.form["position"],
        request.form["dept_id"],
        request.form["entitlement"],
        request.form["availability"],
        id
    ))

    conn.commit()
    conn.close()

    return redirect("/admin/users")


# ===== DELETE USER =====
@app.route("/admin/users/delete/<int:id>", methods=["POST"])
def delete_user(id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("DELETE FROM users WHERE id=%s", (id,))
    conn.commit()
    conn.close()

    return redirect("/admin/users")
# ================= DEPARTMENTS =================
@app.route("/admin/departments", methods=["GET", "POST"])
def manage_departments():
    conn = get_db()
    cur = conn.cursor()

    # ADD DEPARTMENT
    if request.method == "POST":
        cur.execute(
            "INSERT INTO departments (name) VALUES (%s)",
            (request.form["name"],)
        )
        conn.commit()

    # GET ALL DEPARTMENTS
    cur.execute("SELECT id, name FROM departments")

    columns = [col[0] for col in cur.description]
    departments = [dict(zip(columns, row)) for row in cur.fetchall()]

    conn.close()

    return render_template("manage_department.html",
                           departments=departments)

# ================= DELETE DEPARTMENT =================
@app.route("/admin/departments/delete/<int:dept_id>", methods=["POST"])
def delete_department(dept_id):
    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute("DELETE FROM departments WHERE id=%s", (dept_id,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        return "Cannot delete department (might have employees assigned)"

    conn.close()

    return redirect("/admin/departments")

# ================= DEPARTMENT EMPLOYEES =================

# ================= LEAVES (ADMIN DASHBOARD)=================
@app.route("/admin/leaves")
def admin_leaves():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT 
            l.id,
            u.full_name,
            l.leave_type,
            l.start_date,
            l.end_date,
            l.status
        FROM leaves l
        JOIN users u ON l.user_id = u.id
    """)

    leaves = cur.fetchall()

    # STATS
    cur.execute("SELECT COUNT(*) FROM leaves")
    total = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM leaves WHERE status='Pending'")
    pending = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM leaves WHERE status='Approved'")
    approved = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM leaves WHERE status='Rejected'")
    rejected = cur.fetchone()[0]

    conn.close()

    return render_template(
        "admin_leave_dashboard.html",
        leaves=leaves,
        total=total,
        pending=pending,
        approved=approved,
        rejected=rejected
    )

@app.route("/leave/update/<int:id>/<status>")
def update_leave(id, status):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("UPDATE leaves SET status=%s WHERE id=%s",
                (status, id))

    conn.commit()
    conn.close()

    return redirect("/admin/leaves")

# ================= USER LEAVES =================
@app.route("/leave/my")
@login_required
def my_leaves():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT leave_type, start_date, end_date, status, total_days, reason, support_doc
        FROM leave_applications
        WHERE user_id = %s
        ORDER BY created_at DESC
    """, (session["user_id"],))

    leaves = cur.fetchall()
    conn.close()

    return render_template("leave_user.html", leaves=leaves)

# ================= APPLY LEAVE =================
@app.route("/leave/apply", methods=["GET", "POST"])
@login_required
def apply_leave():

    user_id = session["user_id"]

    conn = get_db()
    c = conn.cursor()

    # ================= GET USER =================
    c.execute("SELECT * FROM users WHERE id=%s", (user_id,))
    user = c.fetchone()

    if request.method == "POST":

        start_date = request.form.get("start_date")
        end_date   = request.form.get("end_date")
        leave_type = request.form.get("leave_type")
        reason     = request.form.get("reason")
        address    = request.form.get("contact_address")
        phone      = request.form.get("contact_phone")

        # ================= CALCULATE DAYS =================
        total_days = calculate_working_days(start_date, end_date)

        # ================= GET USED LEAVE =================
        used_days = get_used_leave_days(user_id)

        entitlement = user["entitlement"] or 0

        # ================= VALIDATION =================
        if used_days + total_days > entitlement:
            flash("Not enough leave balance!", "danger")
            return redirect(url_for("apply_leave"))

        # ================= FILE UPLOAD =================
        file = request.files.get("support_doc")
        filename = None

        if file and allowed_leave_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(LEAVE_UPLOAD_FOLDER, filename))

        # ================= APPROVAL FLOW =================
        checker_position = get_next_position(user["position"])
        approver_position = get_next_position(checker_position)

        # fallback if None
        checker_name = checker_position or "Manager"
        approver_name = approver_position or "Admin"

        # ================= INSERT =================
        c.execute("""
            INSERT INTO leave_applications (
                user_id,
                full_name,
                position,
                leave_type,
                start_date,
                end_date,
                total_days,
                reason,
                checker_name,
                approver_name,
                contact_address,
                contact_phone,
                support_doc,
                created_at
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            user_id,
            user["full_name"],
            user["position"],
            leave_type,
            start_date,
            end_date,
            total_days,
            reason,
            checker_name,
            approver_name,
            address,
            phone,
            filename,
            datetime.utcnow().isoformat()
        ))

        conn.commit()
        conn.close()

        flash("Leave applied successfully!", "success")
        return redirect(url_for("leave_user"))

    # ================= GET PAGE =================
    used_days = get_used_leave_days(user_id)
    entitlement = user["entitlement"] or 0
    remaining_leave = max(0, entitlement - used_days)

    return render_template(
        "apply_leave.html",
        user=user,
        remaining_leave=remaining_leave,
        current_date=datetime.now().strftime("%d-%m-%Y"),
        checker_name=get_next_position(user["position"]) or "Manager",
        approver_name="Admin"
    )
    
@app.route("/leave/approval")
@login_required
def leave_approval():

    position = session.get("position")

    conn = get_db()
    c = conn.cursor()

    # show leaves based on role
    c.execute("""
        SELECT *
        FROM leave_applications
        WHERE 
            (checker_name = %s AND status = 'Pending Recommender')
            OR
            (approver_name = %s AND status = 'Pending Approver')
        ORDER BY created_at DESC
    """, (position, position))

    leaves = c.fetchall()
    conn.close()

    return render_template("leave_approval.html", leaves=leaves)

@app.route("/leave/approve/<int:id>")
@login_required
def approve_leave(id):

    position = session.get("position")

    conn = get_db()
    c = conn.cursor()

    # get leave
    c.execute("SELECT * FROM leave_applications WHERE id=%s", (id,))
    leave = c.fetchone()

    if not leave:
        return "Not found"

    # ================= CHECKER =================
    if leave["checker_name"] == position and leave["status"] == "Pending Recommender":
        c.execute("""
            UPDATE leave_applications
            SET status='Pending Approver'
            WHERE id=%s
        """, (id,))

    # ================= APPROVER =================
    elif leave["approver_name"] == position and leave["status"] == "Pending Approver":
        c.execute("""
            UPDATE leave_applications
            SET status='Approved'
            WHERE id=%s
        """, (id,))

    conn.commit()
    conn.close()

    return redirect("/leave/approval")

@app.route("/leave/reject/<int:id>")
@login_required
def reject_leave(id):

    conn = get_db()
    c = conn.cursor()

    c.execute("""
        UPDATE leave_applications
        SET status='Rejected'
        WHERE id=%s
    """, (id,))

    conn.commit()
    conn.close()

    return redirect("/leave/approval")

@app.route("/claims/submit", methods=["GET","POST"])
def user_claim():
    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":
        cur.execute("""
            INSERT INTO claims (user_id, title, amount, status)
            VALUES (%s,%s,%s,'Pending')
        """, (
            session["user_id"],
            request.form["title"],
            request.form["amount"]
        ))
        conn.commit()

    cur.execute("""
        SELECT id, title, amount, status
        FROM claims
        WHERE user_id=%s
    """, (session["user_id"],))

    claims = cur.fetchall()
    conn.close()

    return render_template("claim_user.html", claims=claims)

# ================= CLAIMS =================
@app.route("/admin/claims")
def admin_claims():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, title, amount, status
        FROM claims
    """)

    claims = cur.fetchall()
    conn.close()

    return render_template("claims/claims_dashboard.html",
                           claims=claims)


@app.route("/claim/update/<int:id>/<status>")
def update_claim(id, status):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("UPDATE claims SET status=%s WHERE id=%s",
                (status, id))

    conn.commit()
    conn.close()

    return redirect("/admin/claims")

@app.route("/admin/policy")
def policy():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT filename FROM policies
        ORDER BY id DESC LIMIT 1
    """)

    result = cur.fetchone()
    policy_file = result[0] if result else None

    conn.close()

    return render_template("policy.html", policy_file=policy_file)

@app.route("/admin/policy/upload", methods=["POST"])
def upload_policy():
    file = request.files.get("file")

    if file and file.filename != "":
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO policies (filename)
            VALUES (%s)
        """, (filename,))

        conn.commit()
        conn.close()

    return redirect("/admin/policy")

# ================ USER POLICY ==================
@app.route("/policy")
def user_policy():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT filename FROM policies
        ORDER BY id DESC LIMIT 1
    """)

    result = cur.fetchone()
    policy_file = result[0] if result else None

    conn.close()

    return render_template("user_policy.html", policy_file=policy_file)

# ================= NOTICE =================
@app.route("/admin/notice", methods=["POST"])
def update_notice():
    conn = get_db()
    cur = conn.cursor()

    content = request.form["content"]
    file = request.files.get("file")

    filename = None

    if file and file.filename != "":
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

    cur.execute("""
        INSERT INTO notices (content, file)
        VALUES (%s, %s)
    """, (content, filename))

    conn.commit()
    conn.close()

    return redirect("/admin/dashboard")

# ================= NOTIFICATIONS =================
@app.route("/notifications")
@login_required
def get_notifications():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT message FROM notifications
        WHERE user_id=%s
        ORDER BY id DESC LIMIT 5
    """, (session["user_id"],))

    data = cur.fetchall()
    conn.close()

    return {"notifications": [n[0] for n in data]}

# ================= REMINDER CHECKER (SCHEDULED) =================
def check_reminders():
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT id, user_id, title
            FROM tasks
            WHERE reminder_time <= NOW()
            AND reminder_time > NOW() - INTERVAL '1 minute'
        """)

        for task_id, user_id, title in cur.fetchall():
            cur.execute("""
                INSERT INTO notifications (user_id, message)
                VALUES (%s, %s)
            """, (user_id, f"Reminder: {title} soon"))

        conn.commit()
        conn.close()
    except Exception as e:
        print("Scheduler error:", e)

# # ================= EMAIL SENDER (EXAMPLE) =================
# def send_email(to, subject, body):
#     msg = Message(subject, recipients=[to])
#     msg.body = body
#     mail.send(msg)

# ===========ADMIN ANALYTICS DASHBOARD===========
@app.route("/admin/analytics")
def admin_analytics():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM users")
    users = cur.fetchone()[0]

    cur.execute("SELECT status, COUNT(*) FROM claims GROUP BY status")
    claims = dict(cur.fetchall())

    conn.close()

    return render_template("admin_analytics.html",
        users=users,
        claims=claims
    )
# ================= DASHBOARD DATA (AJAX) =================
@app.route("/dashboard-data")
def dashboard_data():
    user_id = session["user_id"]
    conn = get_db()
    cur = conn.cursor()

    # Attendance stats
    cur.execute("""
        SELECT status, COUNT(*) 
        FROM attendance
        WHERE user_id=%s
        GROUP BY status
    """, (user_id,))
    att = dict(cur.fetchall())

    ontime = att.get("OnTime", 0)
    late = att.get("Late", 0)
    absent = att.get("Absent", 0)

    total_days = ontime + late + absent if (ontime+late+absent)>0 else 1
    attendance_rate = round((ontime / total_days) * 100, 1)

    # Leave balance (example static logic)
    leave_balance = 14

    # Productivity dummy
    productivity = min(100, attendance_rate + 10)

    conn.close()

    return {
        "attendance": [ontime, late, absent],
        "attendance_rate": attendance_rate,
        "leave_balance": leave_balance,
        "productivity": productivity
    }
# ================= CALENDAR EVENTS =================
@app.route("/calendar-events")
def calendar_events():
    user_id = session["user_id"]
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, title, start_time, end_time
        FROM tasks
        WHERE user_id=%s
    """, (user_id,))

    events = [
        {
            "id": r[0],
            "title": r[1],
            "start": r[2].isoformat() if r[2] else None,
            "end": r[3].isoformat() if r[3] else None
        }
        for r in cur.fetchall()
    ]

    conn.close()
    return events

@app.route("/calendar-update", methods=["POST"])
def update_calendar():
    data = request.json
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE tasks
        SET start_time=%s, end_time=%s
        WHERE id=%s
    """, (data["start"], data["end"], data["id"]))

    conn.commit()
    conn.close()
    return {"status": "ok"}

# ================= GOOGLE OAUTH LOGIN (EXAMPLE) =================
@app.route("/google/login")
def google_login():
    flow = Flow.from_client_config({
        "web":{
            "client_id":os.getenv("GOOGLE_CLIENT_ID"),
            "client_secret":os.getenv("GOOGLE_CLIENT_SECRET"),
            "auth_uri":"https://accounts.google.com/o/oauth2/auth",
            "token_uri":"https://oauth2.googleapis.com/token"
        }
    }, scopes=["https://www.googleapis.com/auth/calendar"])

    flow.redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
    auth_url, _ = flow.authorization_url(prompt='consent')
    return redirect(auth_url)

def push_to_google(token, task):
    service = build('calendar', 'v3', credentials=token)

    event = {
        'summary': task['title'],
        'start': {'dateTime': task['start']},
        'end': {'dateTime': task['end']}
    }

    service.events().insert(calendarId='primary', body=event).execute()
# ================= LOGOUT =================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ================= RUN =================
if __name__ == "__main__":
    app.run(debug=True)